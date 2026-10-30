import contextlib
import hmac
import json
import logging
import math
import socket
import sys
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

from .errors import error
from .jobs import Jobs

MAX_BODY = 64 * 1024 * 1024
MAX_WAIT_S = 10.0
# `ephemeral` is true on a read whose request_id the server minted: its operation need not
# outlive it.
CALL_FIELDS = {"op", "args", "request_id", "operation_id", "client", "wait_s", "ephemeral"}
FINAL = ("done", "error")
OPERATIONS = "/v1/operations/"

Reply = tuple[int, dict[str, Any]]
# Darwin's SO_NOSIGPIPE (sys/socket.h), which Python does not name.
NO_SIGPIPE = getattr(socket, "SO_NOSIGPIPE", 0x1022 if sys.platform == "darwin" else None)


class BridgeHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    # Every poll that times out during a long Krita call leaves a connection in the backlog.
    request_queue_size = 64

    def __init__(
        self, token: str, session_id: str, jobs: Jobs, health: dict[str, Any], log: logging.Logger
    ) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.token = token.encode("ascii")
        self.session_id = session_id
        self.jobs = jobs
        self.health = health
        self.log = log
        self._in_flight = 0
        self._idle = threading.Condition()

    @property
    def port(self) -> int:
        return int(self.server_address[1])

    @contextlib.contextmanager
    def tracked(self) -> Iterator[None]:
        with self._idle:
            self._in_flight += 1
        try:
            yield
        finally:
            with self._idle:
                self._in_flight -= 1
                self._idle.notify_all()

    def wait_idle(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        with self._idle:
            while self._in_flight:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._idle.wait(remaining)
            return True

    def get_request(self) -> tuple[socket.socket, Any]:
        connection, address = super().get_request()
        # A client that gave up mid-call has closed its end before the reply is written. Krita's
        # embedded Python leaves SIGPIPE at its default, so that write would kill Krita; with this
        # it fails as BrokenPipeError instead.
        if NO_SIGPIPE is not None:
            connection.setsockopt(socket.SOL_SOCKET, NO_SIGPIPE, 1)
        return connection, address

    def handle_error(self, request: Any, client_address: Any) -> None:
        # A client whose poll timed out during a long Krita call has gone; that is routine.
        if isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError, TimeoutError)):
            self.log.debug("a client left before its reply")
            return
        self.log.warning("a bridge request failed", exc_info=True)


class _Handler(BaseHTTPRequestHandler):
    server: BridgeHTTPServer
    protocol_version = "HTTP/1.1"
    # A client that connects and sends nothing must not keep its thread alive.
    timeout = 10

    def log_message(self, format: str, *args: Any) -> None:
        self.server.log.debug(format, *args)

    def do_GET(self) -> None:
        self._respond("GET")

    def do_POST(self) -> None:
        self._respond("POST")

    def _respond(self, method: str) -> None:
        self.close_connection = True
        with self.server.tracked():
            status, body = self._route(method)
            data = json.dumps({"session_id": self.server.session_id, **body}).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(data)
            if body.get("status") in FINAL and isinstance(body.get("operation_id"), str):
                self.server.jobs.delivered(body["operation_id"])

    def _route(self, method: str) -> Reply:
        refusal = self._refusal()
        if refusal is not None:
            return refusal
        url = urlsplit(self.path)
        wait_s = _wait_s(parse_qs(url.query).get("wait_s", ["0"])[0])
        if method == "GET" and url.path == "/v1/health":
            return 200, {"status": "done", **_ids(), "result": self.server.health}
        if method == "POST" and url.path == "/v1/call":
            return self._call()
        if url.path.startswith(OPERATIONS):
            rest = url.path[len(OPERATIONS) :]
            if method == "GET" and rest and "/" not in rest:
                return self._operation(rest, wait_s)
            if method == "POST" and rest.endswith("/cancel") and "/" not in rest[: -len("/cancel")]:
                return self._cancel(rest[: -len("/cancel")])
        return _failure(404, "INVALID_ARGUMENT", "Unknown endpoint.", {"path": url.path})

    def _refusal(self) -> Reply | None:
        port = self.server.port
        if self.headers.get("Host", "") not in (f"127.0.0.1:{port}", f"localhost:{port}"):
            return _failure(403, "INTERNAL_ERROR", "The bridge refused this Host header.")
        supplied = self.headers.get("Authorization", "").encode("latin-1", "replace")
        if not hmac.compare_digest(supplied, b"Bearer " + self.server.token):
            return _failure(401, "INTERNAL_ERROR", "The bridge refused a missing or wrong token.")
        if not self.server.jobs.accepting:
            return _failure(503, "KRITA_NOT_RUNNING", "Krita is quitting.")
        return None

    def _body(self) -> dict[str, Any] | Reply:
        # Oversized bodies are refused before a byte of them is read.
        if self.headers.get("Transfer-Encoding") is not None:
            return _failure(411, "INVALID_ARGUMENT", "Send a Content-Length, not chunks.")
        length_text = self.headers.get("Content-Length")
        if length_text is None:
            return _failure(411, "INVALID_ARGUMENT", "A Content-Length is required.")
        try:
            length = int(length_text)
        except ValueError:
            return _failure(400, "INVALID_ARGUMENT", "Content-Length is not a number.")
        if length < 0:
            return _failure(400, "INVALID_ARGUMENT", "Content-Length is negative.")
        if length > MAX_BODY:
            return _failure(413, "INVALID_ARGUMENT", "The body is over 64 MB.")
        try:
            body = json.loads(self.rfile.read(length))
        except ValueError:
            return _failure(400, "INVALID_ARGUMENT", "The body is not JSON.")
        if not isinstance(body, dict):
            return _failure(400, "INVALID_ARGUMENT", "The body is not a JSON object.")
        return body

    def _call(self) -> Reply:
        body = self._body()
        if isinstance(body, tuple):
            return body
        problem = _call_problem(body)
        if problem is not None:
            return _failure(400, "INVALID_ARGUMENT", problem)
        operation = self.server.jobs.submit(
            body["operation_id"],
            body["request_id"],
            body["op"],
            body["args"],
            body["client"],
            body["ephemeral"],
        )
        if operation is None:
            return _failure(503, "KRITA_NOT_RUNNING", "Krita is quitting.")
        return 200, self.server.jobs.follow(operation, _wait_s(body["wait_s"]))

    def _operation(self, operation_id: str, wait_s: float) -> Reply:
        reply = self.server.jobs.wait(operation_id, wait_s)
        if reply is None:
            return _unknown(operation_id)
        return 200, reply

    def _cancel(self, operation_id: str) -> Reply:
        outcome = self.server.jobs.cancel(operation_id)
        if outcome is None:
            return _unknown(operation_id)
        reply, cancelled = outcome
        return 200, {**reply, "cancelled": cancelled}


def _call_problem(body: dict[str, Any]) -> str | None:
    if set(body) != CALL_FIELDS:
        return f"A call has the fields {sorted(CALL_FIELDS)}."
    if not isinstance(body["ephemeral"], bool):
        return "ephemeral must be true or false."
    for field in ("op", "request_id", "operation_id"):
        if not isinstance(body[field], str) or not body[field]:
            return f"{field} must be a non-empty string."
    if not isinstance(body["args"], dict):
        return "args must be an object."
    client = body["client"]
    # The writer lease tells server processes apart by both fields.
    if (
        not isinstance(client, dict)
        or set(client) != {"pid", "started_at"}
        or isinstance(client["pid"], bool)
        or not isinstance(client["pid"], int)
        or not isinstance(client["started_at"], str)
        or not client["started_at"]
    ):
        return "client must be {pid, started_at}, with a non-empty start time."
    wait_s = body["wait_s"]
    if isinstance(wait_s, bool) or not isinstance(wait_s, (int, float)) or wait_s < 0:
        return "wait_s must be a number of seconds, zero or more."
    return None


def _wait_s(value: Any) -> float:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if math.isnan(seconds) else min(max(seconds, 0.0), MAX_WAIT_S)


def _ids(operation_id: str | None = None) -> dict[str, Any]:
    return {"operation_id": operation_id, "request_id": None}


def _failure(
    status: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    operation_id: str | None = None,
) -> Reply:
    body = {"status": "error", **_ids(operation_id), "error": error(code, message, False, details)}
    return status, body


def _unknown(operation_id: str) -> Reply:
    message = "Unknown operation in this Krita session."
    return _failure(404, "INVALID_ARGUMENT", message, {"operation_id": operation_id}, operation_id)
