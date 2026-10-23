import logging
import threading
import time
import traceback
from collections import deque
from collections.abc import Callable, Mapping
from typing import Any

from .errors import BridgeError, error

Handler = Callable[[dict[str, Any]], dict[str, Any]]

QUEUED = "queued"
RUNNING = "running"
DONE = "done"
FAILED = "error"


class Operation:
    def __init__(
        self,
        operation_id: str,
        request_id: str,
        op: str,
        args: dict[str, Any],
        client: dict[str, Any],
    ) -> None:
        self.operation_id = operation_id
        self.request_id = request_id
        self.op = op
        self.args = args
        self.client = client
        self.state = QUEUED
        self.result: dict[str, Any] | None = None
        self.error: dict[str, Any] | None = None

    def reply(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "status": self.state,
            "operation_id": self.operation_id,
            "request_id": self.request_id,
        }
        if self.state == DONE:
            body["result"] = self.result
        elif self.state == FAILED:
            body["error"] = self.error
        return body


# Operations run one at a time on Krita's main thread; HTTP threads only enqueue and wait.
class Jobs:
    def __init__(
        self,
        handlers: Mapping[str, Handler],
        wake: Callable[[], None],
        on_main_thread: Callable[[], bool],
        log: logging.Logger,
    ) -> None:
        self._handlers = handlers
        self._wake = wake
        self._on_main_thread = on_main_thread
        self._log = log
        # One condition guards every state change, so cancel, stop and drain never race.
        self._lock = threading.Condition()
        self._queue: deque[Operation] = deque()
        self._operations: dict[str, Operation] = {}
        self._accepting = True
        self._job_active = False

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
    ) -> Operation | None:
        with self._lock:
            if not self._accepting:
                return None
            known = self._operations.get(operation_id)
            if known is not None:
                return known
            operation = Operation(operation_id, request_id, op, args, client)
            self._operations[operation_id] = operation
            if op not in self._handlers:
                operation.state = FAILED
                operation.error = error(
                    "INVALID_ARGUMENT", f"Unknown op {op!r}.", False, {"op": op}
                )
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
                self._job_active = False

    def _run(self, operation: Operation) -> None:
        result = None
        failure: dict[str, Any] | None = error("INTERNAL_ERROR", "The op did not finish.")
        try:
            result = self._handlers[operation.op](operation.args)
            failure = None
        except BridgeError as raised:
            failure = raised.body
        except Exception:
            self._log.error(
                "op %s (%s) raised\n%s",
                operation.op,
                operation.operation_id,
                traceback.format_exc(),
            )
            message = "The plugin raised an unexpected error; see plugin.log."
            failure = error("INTERNAL_ERROR", message, False, {"op": operation.op})
        finally:
            with self._lock:
                operation.state = DONE if failure is None else FAILED
                operation.result = result if failure is None else None
                operation.error = failure
                self._lock.notify_all()

    def wait(self, operation_id: str, wait_s: float) -> dict[str, Any] | None:
        deadline = time.monotonic() + wait_s
        with self._lock:
            operation = self._operations.get(operation_id)
            if operation is None:
                return None
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
                operation.state = FAILED
                operation.error = error("CANCELLED", "The operation was cancelled before it ran.")
                self._lock.notify_all()
            return operation.reply(), cancelled

    def stop(self) -> None:
        with self._lock:
            self._accepting = False
            while self._queue:
                operation = self._queue.popleft()
                operation.state = FAILED
                operation.error = error("CANCELLED", "Krita is quitting; the operation never ran.")
            self._lock.notify_all()
