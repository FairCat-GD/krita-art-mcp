import hashlib
import json
import logging
import threading
import time
import traceback
from collections import deque
from collections.abc import Callable, Mapping
from typing import Any

from .errors import NOT_APPLIED, UNCERTAIN, BridgeError, error

# A read's request_id was minted by its server and is never retried, so its operation is kept only
# for late polls: this long after its final reply was sent, or after it finished unsent.
READ_KEEP_S = 600.0
READ_UNSENT_S = 3600.0
PRUNE_EVERY_S = 60.0

# Every op is one of three kinds, which says what a raise from it proves. A read changes nothing.
READS = frozenset(
    {
        "server_info",
        "bridge.unsaved_documents",
        "document.list",
        "document.baselines",
        "document.inspect",
        "resource.list",
        "capture.read",
        "sample.read",
        "preview.read",
    }
)
# Each of these marks its call before its first change, so a refusal before that changed nothing.
BOUNDED = frozenset(
    {
        "document.open",
        "document.create",
        "document.close",
        "document.save",
        "document.save_finish",
        "layer.create",
        "layer.update",
        "selection.set",
        "protection.set",
        "history.step",
        "paint.stroke",
    }
)
# Fixture ops have no marker, so a raise from one proves nothing.
HARNESS = "harness."


class Call:
    # What a handler knows about the call beside its arguments.
    def __init__(self, operation_id: str, request_id: str, client: dict[str, Any]) -> None:
        self.operation_id = operation_id
        self.request_id = request_id
        self.client = client
        # Set just before the op's first change of any kind but the window-wide brush.
        self.changing = False

    def mark(self) -> None:
        self.changing = True


Handler = Callable[[dict[str, Any], Call], dict[str, Any]]

QUEUED = "queued"
RUNNING = "running"
DONE = "done"
FAILED = "error"


def args_sha256(op: str, args: dict[str, Any]) -> str:
    canonical = json.dumps(
        {"op": op, "args": args}, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def stated(op: str, call: Call, body: dict[str, Any]) -> dict[str, Any]:
    # Whether a raise applied, on proof: anything unproven is uncertain.
    details = body["details"]
    if "outcome" in details:
        return body
    proven = (
        body["retryable"]
        or details.get("rollback_verified") is True
        or op in READS
        or (op in BOUNDED and not call.changing)
    )
    return {**body, "details": {**details, "outcome": NOT_APPLIED if proven else UNCERTAIN}}


class Operation:
    def __init__(
        self,
        operation_id: str,
        request_id: str,
        op: str,
        args: dict[str, Any],
        client: dict[str, Any],
        ephemeral: bool = False,
    ) -> None:
        self.operation_id = operation_id
        self.request_id = request_id
        self.op = op
        self.args = args
        self.client = client
        self.ephemeral = ephemeral
        self.state = QUEUED
        self.result: dict[str, Any] | None = None
        self.error: dict[str, Any] | None = None
        self.finished_at: float | None = None
        self.delivered_at: float | None = None

    def fail(self, body: dict[str, Any]) -> None:
        self.state = FAILED
        self.error = body
        # Dedup needs only the hash, so a session of long strokes holds receipts, not points.
        self.args = {}

    def reply(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "status": self.state,
            "operation_id": self.operation_id,
            "request_id": self.request_id,
            "op": self.op,
        }
        if self.state == DONE:
            body["result"] = self.result
        elif self.state == FAILED:
            body["error"] = self.error
        return body


# Operations run one at a time on Krita's main thread; HTTP threads only enqueue and wait.
# A request_id names one operation for the whole Krita session, so a retry never runs twice.
class Jobs:
    def __init__(
        self,
        handlers: Mapping[str, Handler],
        wake: Callable[[], None],
        on_main_thread: Callable[[], bool],
        log: logging.Logger,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._handlers = handlers
        self._wake = wake
        self._on_main_thread = on_main_thread
        self._log = log
        # One condition guards every state change, so cancel, stop and drain never race.
        self._lock = threading.Condition()
        self._queue: deque[Operation] = deque()
        # Keyed by every operation_id a call arrived with, so a retry's own id finds the original.
        self._operations: dict[str, Operation] = {}
        self._requests: dict[str, Operation] = {}
        # Outlives a released request, so other arguments under the same id still conflict.
        self._bound: dict[str, str] = {}
        self._accepting = True
        self._job_active = False
        self._clock = clock
        self._pruned_at = clock()

    @property
    def accepting(self) -> bool:
        with self._lock:
            return self._accepting

    def submit(
        self,
        operation_id: str,
        request_id: str,
        op: str,
        args: dict[str, Any],
        client: dict[str, Any],
        ephemeral: bool = False,
    ) -> Operation | None:
        digest = args_sha256(op, args)
        with self._lock:
            if not self._accepting:
                return None
            self._prune()
            known = self._operations.get(operation_id)
            if known is not None:
                if known.request_id == request_id:
                    return known
                refused = Operation(operation_id, request_id, op, {}, client)
                message = "That operation_id already names another request."
                details = {"op": op, "outcome": NOT_APPLIED}
                refused.fail(error("INVALID_ARGUMENT", message, False, details))
                return refused
            bound = self._bound.get(request_id)
            if bound is not None and bound != digest:
                conflict = Operation(operation_id, request_id, op, {}, client, ephemeral)
                message = "That request_id was used with different arguments."
                details = {"request_id": request_id, "outcome": NOT_APPLIED}
                self._finish_failed(conflict, error("REQUEST_ID_CONFLICT", message, False, details))
                self._operations[operation_id] = conflict
                return conflict
            existing = self._requests.get(request_id)
            if existing is not None:
                self._operations[operation_id] = existing
                return existing
            operation = Operation(operation_id, request_id, op, args, client, ephemeral)
            self._operations[operation_id] = operation
            self._requests[request_id] = operation
            self._bound[request_id] = digest
            if op not in self._handlers:
                details = {"op": op, "outcome": NOT_APPLIED}
                unknown = error("INVALID_ARGUMENT", f"Unknown op {op!r}.", False, details)
                self._finish_failed(operation, unknown)
                return operation
            self._queue.append(operation)
        self._wake()
        return operation

    def drain(self) -> None:
        if not self._on_main_thread():
            raise RuntimeError("jobs run only on Krita's main thread")
        with self._lock:
            # A job's nested event loop (waitForDone, a save) delivers the wake signal again.
            if self._job_active:
                return
            self._job_active = True
        operation: Operation | None = None
        try:
            while True:
                with self._lock:
                    if not self._queue:
                        return
                    operation = self._queue.popleft()
                    operation.state = RUNNING
                    self._lock.notify_all()
                self._run(operation)
        finally:
            with self._lock:
                # An interrupt between taking a job and running it must not strand it running.
                if operation is not None and operation.state == RUNNING:
                    details = {"outcome": UNCERTAIN}
                    self._finish_failed(
                        operation, error("INTERNAL_ERROR", "The op did not finish.", False, details)
                    )
                    self._lock.notify_all()
                self._job_active = False

    def _run(self, operation: Operation) -> None:
        result = None
        failure: dict[str, Any] | None = error(
            "INTERNAL_ERROR", "The op did not finish.", False, {"outcome": UNCERTAIN}
        )
        call = Call(operation.operation_id, operation.request_id, operation.client)
        try:
            result = _sendable(self._handlers[operation.op](operation.args, call))
            failure = None
        except BridgeError as raised:
            failure = stated(operation.op, call, raised.body)
        except BaseException:
            # Even an interrupt fails only its own op: anything leaving the Qt slot ends Krita.
            self._log.error(
                "op %s (%s) raised\n%s",
                operation.op,
                operation.operation_id,
                traceback.format_exc(),
            )
            message = "The plugin raised an unexpected error; see plugin.log."
            details = {"op": operation.op, "outcome": UNCERTAIN}
            failure = error("INTERNAL_ERROR", message, False, details)
        finally:
            with self._lock:
                if failure is None:
                    operation.state = DONE
                    operation.result = result
                    operation.args = {}
                    operation.finished_at = self._clock()
                else:
                    self._finish_failed(operation, failure)
                self._lock.notify_all()

    def _finish_failed(self, operation: Operation, failure: dict[str, Any]) -> None:
        try:
            json.dumps(failure, allow_nan=False)
        except (TypeError, ValueError, RecursionError):
            # Replaced, so every poll of the operation still gets an answer.
            self._log.error(
                "op %s (%s) failed with an error that is not JSON",
                operation.op,
                operation.operation_id,
            )
            message = "The op failed with an error the bridge could not send; see plugin.log."
            details = {"op": operation.op, "outcome": UNCERTAIN}
            failure = error("INTERNAL_ERROR", message, False, details)
        operation.fail(failure)
        operation.finished_at = self._clock()
        # Retryable means the op changed nothing, so a retry under the same id runs again.
        if failure["retryable"] and self._requests.get(operation.request_id) is operation:
            del self._requests[operation.request_id]

    def retention(self) -> dict[str, int]:
        # What the bridge holds for dedup, so a long session's growth can be measured.
        with self._lock:
            return {
                "operations": len(self._operations),
                "requests": len(self._requests),
                "bound": len(self._bound),
            }

    def delivered(self, operation_id: str) -> None:
        # Called once a final reply has been written, so a read lost on the way is still found.
        with self._lock:
            operation = self._operations.get(operation_id)
            if (
                operation is not None
                and operation.state in (DONE, FAILED)
                and operation.delivered_at is None
            ):
                operation.delivered_at = self._clock()

    def _prune(self) -> None:
        # Under the lock. Agents' request ids stay for the session (invariant 9); reads do not.
        now = self._clock()
        if now - self._pruned_at < PRUNE_EVERY_S:
            return
        self._pruned_at = now

        def gone(operation: Operation) -> bool:
            if not operation.ephemeral or operation.finished_at is None:
                return False
            if operation.delivered_at is not None:
                return now - operation.delivered_at >= READ_KEEP_S
            return now - operation.finished_at >= READ_UNSENT_S

        dropped = [key for key, operation in self._operations.items() if gone(operation)]
        released = {self._operations[key].request_id for key in dropped}
        for key in dropped:
            del self._operations[key]
        for request_id in released:
            if self._requests.get(request_id) is not None and gone(self._requests[request_id]):
                del self._requests[request_id]
            self._bound.pop(request_id, None)

    def wait(self, operation_id: str, wait_s: float) -> dict[str, Any] | None:
        with self._lock:
            operation = self._operations.get(operation_id)
        return None if operation is None else self.follow(operation, wait_s)

    def follow(self, operation: Operation, wait_s: float) -> dict[str, Any]:
        deadline = time.monotonic() + wait_s
        with self._lock:
            while operation.state in (QUEUED, RUNNING):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._lock.wait(remaining)
            return operation.reply()

    def cancel(self, operation_id: str) -> tuple[dict[str, Any], bool] | None:
        with self._lock:
            operation = self._operations.get(operation_id)
            if operation is None:
                return None
            cancelled = operation.state == QUEUED
            if cancelled:
                self._queue.remove(operation)
                message = "The operation was cancelled before it ran."
                details = {"outcome": NOT_APPLIED}
                self._finish_failed(operation, error("CANCELLED", message, True, details))
                self._lock.notify_all()
            return operation.reply(), cancelled

    def stop(self) -> None:
        with self._lock:
            self._accepting = False
            while self._queue:
                operation = self._queue.popleft()
                message = "Krita is quitting; the operation never ran."
                details = {"outcome": NOT_APPLIED}
                self._finish_failed(operation, error("CANCELLED", message, True, details))
            self._lock.notify_all()


def drain_in_slot(drain: Callable[[], None], log: logging.Logger) -> None:
    # Krita's Qt slot runs the drain: anything leaving a PyQt5 slot, SystemExit included, ends
    # Krita with the owner's unsaved work.
    try:
        drain()
    except BaseException:
        log.exception("the job queue failed")


def _sendable(result: Any) -> dict[str, Any]:
    # A reply the HTTP thread cannot send would leave every poll of it unanswered; the round
    # trip also keeps a snapshot that later changes to the handler's objects cannot reach.
    if not isinstance(result, dict):
        raise TypeError(f"the op returned a {type(result).__name__}, not an object")
    snapshot: dict[str, Any] = json.loads(json.dumps(result, allow_nan=False))
    return snapshot
