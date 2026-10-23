import http.client
import json
import os
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from krita_art_mcp import paths, processes, setup_checks
from krita_art_mcp.errors import CODES, PROTOCOL, error_body

# The server owns the wait budget: the bridge cannot answer while a Krita call holds the GIL
# (K40). 45 s stays under Codex's default 60 s tool timeout.
WAIT_BUDGET_S = 45.0
POLL_S = 2.0
SOCKET_SLACK_S = 3.0
HEALTH_TIMEOUT_S = 5.0
MAX_BODY = 64 * 1024 * 1024


@dataclass(frozen=True)
class Done:
    result: dict[str, Any]
    operation_id: str | None


@dataclass(frozen=True)
class Failed:
    error: dict[str, Any]
    operation_id: str | None = None


@dataclass(frozen=True)
class Pending:
    status: str
    operation_id: str


Outcome = Done | Failed | Pending


@dataclass(frozen=True)
class _Bridge:
    port: int
    token: str
    session_id: str


class _Malformed(Exception):
    pass


class BridgeClient:
    def __init__(
        self,
        *,
        bridge_file: Path | None = None,
        budget_s: float = WAIT_BUDGET_S,
        poll_s: float = POLL_S,
        is_live_krita: Callable[[int], bool] = processes.is_live_krita,
        explain: Callable[[], setup_checks.Step] | None = None,
    ) -> None:
        self._bridge_file = bridge_file or paths.bridge_file()
        self._budget_s = budget_s
        self._poll_s = poll_s
        self._is_live_krita = is_live_krita
        self._explain = explain or _explain_not_running
        self._identity: dict[str, Any] | None = None

    def health(self) -> Done | Failed:
        bridge = self._open()
        if isinstance(bridge, Failed):
            return bridge
        try:
            status, reply = self._request(bridge, "GET", "/v1/health", None, HEALTH_TIMEOUT_S)
        except ConnectionRefusedError:
            return self._refused()
        except (OSError, _Malformed) as problem:
            message = f"The bridge did not answer its health check: {problem}."
            return Failed(error_body("INTERNAL_ERROR", message, retryable=True))
        outcome = self._outcome(status, reply)
        if isinstance(outcome, Pending):
            return Failed(error_body("INTERNAL_ERROR", "The health check came back pending."))
        return outcome

    def call(
        self, op: str, args: dict[str, Any] | None = None, *, request_id: str | None = None
    ) -> Outcome:
        deadline = time.monotonic() + self._budget_s
        operation_id = f"op-{uuid.uuid4().hex}"
        bridge = self._open()
        if isinstance(bridge, Failed):
            return bridge
        call: dict[str, Any] | None = {
            "op": op,
            "args": args or {},
            "request_id": request_id or f"req-{uuid.uuid4().hex}",
            "operation_id": operation_id,
            "client": self._client(),
            "wait_s": 0.0,
        }
        if len(json.dumps(call).encode("utf-8")) > MAX_BODY:
            return Failed(error_body("INVALID_ARGUMENT", "The call is over 64 MB."))
        return self._follow(bridge, operation_id, call, deadline)

    def operation(self, operation_id: str) -> Outcome:
        # Follows a call already sent, for one more wait budget.
        deadline = time.monotonic() + self._budget_s
        bridge = self._open()
        if isinstance(bridge, Failed):
            return bridge
        return self._follow(bridge, operation_id, None, deadline)

    def _follow(
        self, bridge: _Bridge, operation_id: str, call: dict[str, Any] | None, deadline: float
    ) -> Outcome:
        # The bridge, its token and its session are pinned for the whole call, so a Krita that
        # restarts mid-call is noticed rather than silently asked again.
        last_status = "running"
        answered = call is None
        while True:
            wait_s = max(0.0, min(self._poll_s, deadline - time.monotonic()))
            if call is not None:
                call["wait_s"] = wait_s
                method, path = "POST", "/v1/call"
            else:
                method, path = "GET", f"/v1/operations/{operation_id}?wait_s={wait_s:.3f}"
            timeout = max(0.05, min(wait_s + SOCKET_SLACK_S, deadline - time.monotonic()))
            try:
                status, reply = self._request(bridge, method, path, call, timeout)
            except ConnectionRefusedError:
                if call is not None:
                    return self._refused()
                return _uncertain(operation_id, "the bridge stopped accepting connections")
            except TimeoutError:
                pass  # A silent bridge: Krita is inside a call that holds the GIL.
            except _Malformed:
                return _uncertain(operation_id, "the bridge sent a malformed reply")
            except OSError:
                time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
            else:
                if reply.get("session_id") != bridge.session_id:
                    return _uncertain(operation_id, "another Krita session answered")
                if call is None and status == 404 and not answered:
                    # A call whose POST timed out may not be registered yet.
                    time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
                elif call is None and status == 404:
                    return _uncertain(operation_id, "the bridge no longer knows the call")
                elif call is None and status != 200:
                    return _uncertain(operation_id, f"the bridge answered HTTP {status}")
                else:
                    outcome = self._outcome(status, reply)
                    if not isinstance(outcome, Pending):
                        return outcome
                    answered = True
                    last_status = outcome.status
            call = None
            if time.monotonic() >= deadline:
                return Pending(last_status, operation_id)

    def _open(self) -> _Bridge | Failed:
        try:
            info = json.loads(self._bridge_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            info = None
        if not isinstance(info, dict):
            return self._not_running()
        pid = info.get("pid")
        if not isinstance(pid, int) or isinstance(pid, bool) or not self._is_live_krita(pid):
            return self._not_running()
        if info.get("protocol") != PROTOCOL:
            details = {"bridge_protocol": info.get("protocol"), "server_protocol": PROTOCOL}
            return Failed(error_body("PROTOCOL_MISMATCH", details=details))
        port, token, session_id = info.get("port"), info.get("token"), info.get("session_id")
        if not (isinstance(port, int) and isinstance(token, str) and isinstance(session_id, str)):
            return Failed(error_body("INTERNAL_ERROR", "bridge.json is malformed; restart Krita."))
        return _Bridge(port, token, session_id)

    def _request(
        self, bridge: _Bridge, method: str, path: str, body: Any, timeout: float
    ) -> tuple[int, dict[str, Any]]:
        connection = http.client.HTTPConnection("127.0.0.1", bridge.port, timeout=timeout)
        headers = {"Authorization": f"Bearer {bridge.token}"}
        data = None if body is None else json.dumps(body).encode("utf-8")
        if data is not None:
            headers["Content-Type"] = "application/json"
        try:
            connection.request(method, path, body=data, headers=headers)
            response = connection.getresponse()
            status, raw = response.status, response.read()
        finally:
            connection.close()
        try:
            reply = json.loads(raw)
        except ValueError as problem:
            raise _Malformed(str(problem)) from problem
        if not isinstance(reply, dict):
            raise _Malformed("the reply is not an object")
        return status, reply

    def _outcome(self, status: int, reply: dict[str, Any]) -> Outcome:
        operation_id = reply.get("operation_id")
        operation_id = operation_id if isinstance(operation_id, str) else None
        state = reply.get("status")
        if state == "done" and status == 200 and isinstance(reply.get("result"), dict):
            return Done(reply["result"], operation_id)
        if state in ("queued", "running") and operation_id is not None:
            return Pending(state, operation_id)
        if state == "error":
            return Failed(_bridge_error(reply.get("error")), operation_id)
        message = f"The bridge sent an unexpected reply (HTTP {status})."
        return Failed(error_body("INTERNAL_ERROR", message), operation_id)

    def _not_running(self) -> Failed:
        step = self._explain()
        message = f"Krita is not running with the bridge plugin: {step.detail}. {step.fix}"
        return Failed(error_body("KRITA_NOT_RUNNING", message, details=_step_details(step)))

    def _refused(self) -> Failed:
        # Nothing was sent. A Krita that died since bridge.json was read is simply not running.
        if isinstance(self._open(), Failed):
            return self._not_running()
        message = "Krita runs, but its bridge refused the connection; retry, or restart Krita."
        return Failed(error_body("INTERNAL_ERROR", message, retryable=True))

    def _client(self) -> dict[str, Any]:
        if self._identity is None:
            pid = os.getpid()
            self._identity = {"pid": pid, "started_at": processes.start_time(pid)}
        return self._identity


def _bridge_error(body: Any) -> dict[str, Any]:
    if (
        isinstance(body, dict)
        and body.get("code") in CODES
        and isinstance(body.get("message"), str)
        and body["message"]
        and isinstance(body.get("retryable"), bool)
        and isinstance(body.get("details"), dict)
    ):
        return {key: body[key] for key in ("code", "message", "retryable", "details")}
    return error_body("INTERNAL_ERROR", "The bridge sent a malformed error.")


def _uncertain(operation_id: str, reason: str) -> Failed:
    # The call was sent, so it may have run; a retry could repeat it (invariant 9).
    message = f"Krita stopped answering mid-call ({reason}); whether the call ran is unknown."
    details = {"outcome": "uncertain", "operation_id": operation_id}
    return Failed(error_body("INTERNAL_ERROR", message, retryable=False, details=details))


def _step_details(step: setup_checks.Step) -> dict[str, Any]:
    return {"step": step.name, "detail": step.detail, "fix": step.fix}


def _explain_not_running() -> setup_checks.Step:
    return setup_checks.first_local_failure(setup_checks.Setup()) or setup_checks.bridge_missing()
