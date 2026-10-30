import http.client
import json
import os
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from krita_art_mcp import __version__, paths, processes, setup_checks
from krita_art_mcp.errors import CODES, PROTOCOL, error_body

# The server owns the wait budget: the bridge cannot answer while a Krita call holds the GIL
# (K40). 45 s stays under Codex's default 60 s tool timeout.
WAIT_BUDGET_S = 45.0
POLL_S = 2.0
SOCKET_SLACK_S = 3.0
HEALTH_TIMEOUT_S = 5.0
# A POST stuck behind a long Krita call registers a moment after the bridge answers again, so
# only a 404 answered promptly for this long means the call never arrived.
REGISTER_GRACE_S = 2.0
# A reply this slow came while Krita held the GIL, when nothing could register.
SLOW_REPLY_S = 0.5
MAX_BODY = 64 * 1024 * 1024


@dataclass(frozen=True)
class Done:
    result: dict[str, Any]
    operation_id: str | None
    op: str | None = None
    request_id: str | None = None
    session_id: str | None = None


@dataclass(frozen=True)
class Failed:
    error: dict[str, Any]
    operation_id: str | None = None
    # True only when the bridge accepted the call and answered with this error itself.
    submitted: bool = False
    op: str | None = None
    request_id: str | None = None
    session_id: str | None = None


@dataclass(frozen=True)
class Pending:
    status: str
    operation_id: str
    op: str | None = None


Outcome = Done | Failed | Pending
# Runs once the bridge is pinned and before anything is sent; a Failed it returns is the answer.
BeforeSend = Callable[[str, str], "Failed | None"]


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
        grace_s: float = REGISTER_GRACE_S,
        is_live_krita: Callable[[int], bool] = processes.is_live_krita,
        explain: Callable[[], setup_checks.Step] | None = None,
        identity: dict[str, Any] | None = None,
        # For doctor and the probe, which judge a stale plugin by its hash and must still read
        # the unsaved count the restart rule needs.
        any_plugin: bool = False,
    ) -> None:
        self._bridge_file = bridge_file or paths.bridge_file()
        self._budget_s = budget_s
        self._poll_s = poll_s
        self._grace_s = grace_s
        self._is_live_krita = is_live_krita
        self._explain = explain or _explain_not_running
        self._identity = identity
        self._any_plugin = any_plugin
        # The Krita session of each call this process left running, so a later poll can tell a
        # call still on its way from one the bridge never heard of.
        self._sent: dict[str, str] = {}

    @property
    def budget_s(self) -> float:
        return self._budget_s

    def health(self, timeout_s: float = HEALTH_TIMEOUT_S) -> Done | Failed:
        bridge = self._open()
        if isinstance(bridge, Failed):
            return bridge
        try:
            status, reply = self._request(bridge, "GET", "/v1/health", None, timeout_s)
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
        self,
        op: str,
        args: dict[str, Any] | None = None,
        *,
        request_id: str | None = None,
        before_send: BeforeSend | None = None,
        budget_s: float | None = None,
        operation_id: str | None = None,
    ) -> Outcome:
        # budget_s lets a call that follows another in one tool call share its budget; an
        # operation_id derived from another call's lets a later poll find it.
        deadline = time.monotonic() + (self._budget_s if budget_s is None else budget_s)
        operation_id = operation_id or f"op-{uuid.uuid4().hex}"
        bridge = self._open()
        if isinstance(bridge, Failed):
            return bridge
        client = self._client()
        if client is None:
            message = "The server could not read its own start time, which the lease needs."
            return Failed(error_body("INTERNAL_ERROR", message, retryable=True))
        body = json.dumps(
            {
                "op": op,
                "args": args or {},
                "request_id": request_id or f"req-{uuid.uuid4().hex}",
                "operation_id": operation_id,
                "client": client,
                "wait_s": self._wait_s(deadline),
                # Nobody retries an id minted here, so the bridge may forget the call once answered.
                "ephemeral": request_id is None,
            }
        ).encode("utf-8")
        if len(body) > MAX_BODY:
            return Failed(error_body("INVALID_ARGUMENT", "The call is over 64 MB."))
        refused = before_send(bridge.session_id, operation_id) if before_send else None
        if refused is not None:
            return refused
        return self._follow(bridge, operation_id, body, deadline, op=op)

    def operation(self, operation_id: str, *, sent_in: str | None = None) -> Outcome:
        # Follows a call already sent, for one more wait budget. `sent_in` names the Krita
        # session another process sent it to; an id sent nowhere known is refused at once.
        deadline = time.monotonic() + self._budget_s
        bridge = self._open()
        if isinstance(bridge, Failed):
            return bridge
        session = self._sent.get(operation_id, sent_in)
        if session is not None and session != bridge.session_id:
            return _uncertain(operation_id, "Krita restarted since the call was sent")
        return self._follow(bridge, operation_id, None, deadline, strict=session is None)

    def cancel(self, operation_id: str, *, before_send: BeforeSend | None = None) -> Outcome:
        # Cancels a queued operation; the reply is the operation's state, with `cancelled`.
        bridge = self._open()
        if isinstance(bridge, Failed):
            return bridge
        refused = before_send(bridge.session_id, f"cancel-{operation_id}") if before_send else None
        if refused is not None:
            return refused
        path = f"/v1/operations/{operation_id}/cancel"
        try:
            status, reply = self._request(bridge, "POST", path, b"{}", HEALTH_TIMEOUT_S)
        except ConnectionRefusedError:
            return self._refused()
        except (OSError, _Malformed):
            return _uncertain(operation_id, "the bridge did not answer the cancel")
        if reply.get("session_id") != bridge.session_id:
            return _uncertain(operation_id, "another Krita session answered")
        if status == 404:
            return _unknown_operation(operation_id)
        if status != 200 or not isinstance(reply.get("cancelled"), bool):
            outcome = self._outcome(status, reply)
            return outcome if isinstance(outcome, Failed) else _unexpected(status)
        return Done(reply, operation_id, _text(reply.get("op")), session_id=bridge.session_id)

    def _follow(
        self,
        bridge: _Bridge,
        operation_id: str,
        call: bytes | None,
        deadline: float,
        strict: bool = False,
        op: str | None = None,
    ) -> Outcome:
        # The bridge, its token and its session are pinned for the whole call, so a Krita that
        # restarts mid-call is noticed rather than silently asked again.
        last_status = "running"
        # The bridge keeps every operation for its Krita session, so a 404 before the bridge has
        # answered means the call is not registered yet, not that it was lost.
        answered = False
        # When the bridge began answering 404 promptly; silence or a slow reply restarts it.
        unknown_since: float | None = None
        while True:
            wait_s = self._wait_s(deadline)
            if call is not None:
                method, path = "POST", "/v1/call"
            else:
                method, path = "GET", f"/v1/operations/{operation_id}?wait_s={wait_s:.3f}"
            timeout = max(0.05, min(wait_s + SOCKET_SLACK_S, deadline - time.monotonic()))
            sent_at = time.monotonic()
            try:
                status, reply = self._request(bridge, method, path, call, timeout)
            except ConnectionRefusedError:
                if call is not None:
                    return self._refused()
                return _uncertain(operation_id, "the bridge stopped accepting connections")
            except TimeoutError:
                unknown_since = None  # A silent bridge: Krita is inside a call that holds the GIL.
            except _Malformed:
                return _uncertain(operation_id, "the bridge sent a malformed reply")
            except OSError:
                unknown_since = None
                time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
            else:
                if reply.get("session_id") != bridge.session_id:
                    return _uncertain(operation_id, "another Krita session answered")
                if call is None and status == 404 and strict:
                    return _unknown_operation(operation_id)
                if call is None and status == 404 and not answered:
                    # A call whose POST timed out may not be registered yet.
                    now = time.monotonic()
                    if unknown_since is None or now - sent_at > SLOW_REPLY_S:
                        unknown_since = now
                    elif now - unknown_since >= self._grace_s:
                        self._sent.pop(operation_id, None)
                        return _unregistered(operation_id)
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
                    op = outcome.op or op
                    # A retry is answered with the original operation; follow that one.
                    operation_id = outcome.operation_id
            call = None
            if time.monotonic() >= deadline:
                self._sent[operation_id] = bridge.session_id
                return Pending(last_status, operation_id, op)

    def _wait_s(self, deadline: float) -> float:
        return max(0.0, min(self._poll_s, deadline - time.monotonic()))

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
        if not self._any_plugin:
            if info.get("protocol") != PROTOCOL:
                details = {"bridge_protocol": info.get("protocol"), "server_protocol": PROTOCOL}
                return Failed(error_body("PROTOCOL_MISMATCH", details=details))
            if info.get("plugin_version") != __version__:
                return _other_version(info.get("plugin_version"))
        port, token, session_id = info.get("port"), info.get("token"), info.get("session_id")
        if not (isinstance(port, int) and isinstance(token, str) and isinstance(session_id, str)):
            return Failed(error_body("INTERNAL_ERROR", "bridge.json is malformed; restart Krita."))
        return _Bridge(port, token, session_id)

    def _request(
        self, bridge: _Bridge, method: str, path: str, data: bytes | None, timeout: float
    ) -> tuple[int, dict[str, Any]]:
        connection = http.client.HTTPConnection("127.0.0.1", bridge.port, timeout=timeout)
        headers = {"Authorization": f"Bearer {bridge.token}"}
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
        op = _text(reply.get("op"))
        ids = {
            "request_id": _text(reply.get("request_id")),
            "session_id": _text(reply.get("session_id")),
        }
        state = reply.get("status")
        if state == "done" and status == 200 and isinstance(reply.get("result"), dict):
            return Done(reply["result"], operation_id, op, **ids)
        if state in ("queued", "running") and operation_id is not None:
            return Pending(state, operation_id, op)
        if state == "error":
            # Any status but 200 is a refusal before the bridge took the call (401, 503…).
            error = _bridge_error(reply.get("error"))
            return Failed(error, operation_id, submitted=status == 200, op=op, **ids)
        return Failed(_unexpected(status).error, operation_id)

    def _not_running(self) -> Failed:
        step = self._explain()
        message = f"Krita is not running with the bridge plugin: {step.detail}. {step.fix}"
        return Failed(error_body("KRITA_NOT_RUNNING", message, details=_step_details(step)))

    def _refused(self) -> Failed:
        # Nothing was sent. A Krita that died since bridge.json was read is simply not running.
        opened = self._open()
        if isinstance(opened, Failed):
            return opened
        message = "Krita runs, but its bridge refused the connection; retry, or restart Krita."
        return Failed(error_body("INTERNAL_ERROR", message, retryable=True))

    def _client(self) -> dict[str, Any] | None:
        if self._identity is None:
            pid = os.getpid()
            started = processes.start_time(pid)
            if not started:
                return None
            self._identity = {"pid": pid, "started_at": started}
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


def _other_version(found: Any) -> Failed:
    # The two ship together, so neither ever meets an op or a field the other lacks.
    fix = f"{setup_checks.INSTALL} If the plugin is the newer, restart the MCP client instead."
    message = f"Krita runs plugin {found}, and this server is {__version__}. {fix}"
    details = {"plugin_version": found, "server_version": __version__, "fix": fix}
    return Failed(error_body("PROTOCOL_MISMATCH", message, details=details))


def _uncertain(operation_id: str, reason: str) -> Failed:
    # The call was sent, so it may have run; a retry could repeat it (invariant 9).
    message = f"Krita stopped answering mid-call ({reason}); whether the call ran is unknown."
    details = {"outcome": "uncertain", "operation_id": operation_id}
    return Failed(error_body("INTERNAL_ERROR", message, retryable=False, details=details))


def _unregistered(operation_id: str) -> Failed:
    # The journal keeps the attempt unsettled, so a retry is sent only to this Krita session.
    message = (
        "Krita's bridge has no record of this call: it most likely never arrived and did not run, "
        "but it may still arrive. Retry it, with the same request_id if it has one."
    )
    details = {"outcome": "unregistered", "operation_id": operation_id}
    return Failed(error_body("INTERNAL_ERROR", message, retryable=True, details=details))


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _unknown_operation(operation_id: str) -> Failed:
    message = "No operation has that id in this Krita session."
    details = {"operation_id": operation_id}
    return Failed(error_body("INVALID_ARGUMENT", message, details=details), submitted=True)


def _unexpected(status: int) -> Failed:
    return Failed(
        error_body("INTERNAL_ERROR", f"The bridge sent an unexpected reply (HTTP {status}).")
    )


def _step_details(step: setup_checks.Step) -> dict[str, Any]:
    return {"step": step.name, "detail": step.detail, "fix": step.fix}


def _explain_not_running() -> setup_checks.Step:
    return setup_checks.first_local_failure(setup_checks.Setup()) or setup_checks.bridge_missing()
