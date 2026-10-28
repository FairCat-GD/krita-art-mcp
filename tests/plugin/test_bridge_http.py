import http.client
import json
import logging
import signal
import socket
import struct
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from bridge_core import bridge_file
from bridge_core.bridge import Bridge
from bridge_core.jobs import Call
from fake_krita import MainThread

PLUGIN_PACKAGE = Path(__file__).resolve().parents[2] / "plugin" / "krita_art_mcp_bridge"
FACTS = {"krita_version": "5.3.4", "qt_major": 5}


class Live:
    def __init__(self, bridge: Bridge, data_dir: Path) -> None:
        self.bridge = bridge
        written = bridge_file.read(data_dir / "bridge.json")
        assert written is not None
        self.port: int = written["port"]
        self.token: str = written["token"]

    def request(
        self,
        method: str,
        path: str,
        body: Any = None,
        *,
        token: str | None = "",
        host: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        connection.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        connection.putheader("Host", host or f"127.0.0.1:{self.port}")
        if token is not None:
            connection.putheader("Authorization", f"Bearer {token or self.token}")
        data = None if body is None else json.dumps(body).encode()
        extra = dict(headers or {})
        if data is not None:
            extra.setdefault("Content-Length", str(len(data)))
        for name, value in extra.items():
            connection.putheader(name, value)
        connection.endheaders(data)
        response = connection.getresponse()
        reply = json.loads(response.read())
        connection.close()
        return response.status, reply

    def call(self, op: str, operation_id: str, wait_s: float = 5, **args: Any) -> dict[str, Any]:
        body = {
            "op": op,
            "args": args,
            "request_id": f"req-{operation_id}",
            "operation_id": operation_id,
            "client": {"pid": 1, "started_at": "test"},
            "wait_s": wait_s,
        }
        status, reply = self.request("POST", "/v1/call", body)
        assert status == 200
        return reply


@pytest.fixture
def live(tmp_path: Path) -> Iterator[Live]:
    main = MainThread()
    release = threading.Event()

    def hold(args: dict[str, Any], call: Call) -> dict[str, Any]:
        release.wait(5)
        return {"held": True}

    bridge = Bridge(
        data_dir=tmp_path,
        package_dir=PLUGIN_PACKAGE,
        facts=FACTS,
        handlers={"echo": lambda args, call: {"echo": args}, "hold": hold},
        wake=main.wake,
        on_main_thread=main.is_current,
        is_live_krita=lambda pid: False,
        log=logging.getLogger("test_bridge_http"),
    )
    main.bridge = bridge
    main.thread.start()
    assert bridge.start()
    try:
        yield Live(bridge, tmp_path)
    finally:
        release.set()
        bridge.stop()
        main.stopping = True
        main.thread.join(5)


def test_health_answers_with_the_cached_snapshot(live: Live) -> None:
    status, reply = live.request("GET", "/v1/health")
    assert status == 200
    assert reply["status"] == "done"
    assert reply["session_id"] == live.bridge.session_id
    health = reply["result"]
    assert health["protocol"] == 1
    assert health["krita_version"] == "5.3.4"
    assert health["session_id"] == live.bridge.session_id
    assert set(health["capabilities"]) >= {"stroke.native_brush", "animation"}


def test_a_call_runs_on_the_main_thread_and_carries_its_ids(live: Live) -> None:
    reply = live.call("echo", "op-1", colour="red")
    assert reply == {
        "session_id": live.bridge.session_id,
        "status": "done",
        "operation_id": "op-1",
        "request_id": "req-op-1",
        "op": "echo",
        "result": {"echo": {"colour": "red"}},
    }
    assert live.call("server_info", "op-2")["result"] == {
        **live.bridge.health,
        "allowed_roots": [],
    }


def test_a_call_still_queued_after_wait_s_is_reported_then_found(live: Live) -> None:
    held = live.call("hold", "op-hold", wait_s=0.2)
    assert held["status"] == "running"
    queued = live.call("echo", "op-next", wait_s=0.2)
    assert queued["status"] == "queued"
    status, cancelled = live.request("POST", "/v1/operations/op-next/cancel", None)
    assert status == 200
    assert cancelled["cancelled"] is True
    assert cancelled["error"]["code"] == "CANCELLED"
    status, running = live.request("POST", "/v1/operations/op-hold/cancel", None)
    assert (running["status"], running["cancelled"]) == ("running", False)


def test_an_operation_is_polled_until_done(live: Live) -> None:
    live.call("echo", "op-1")
    status, reply = live.request("GET", "/v1/operations/op-1?wait_s=1")
    assert status == 200
    assert reply["result"] == {"echo": {}}
    status, unknown = live.request("GET", "/v1/operations/op-404")
    assert status == 404
    assert unknown["operation_id"] == "op-404"
    assert unknown["error"]["code"] == "INVALID_ARGUMENT"


@pytest.mark.parametrize(
    ("token", "host", "expected"),
    [
        (None, None, 401),
        ("wrong", None, 401),
        ("café", None, 401),
        ("", "evil.example:80", 403),
        ("", "127.0.0.1:1", 403),
    ],
)
def test_requests_without_the_token_or_from_another_host_are_refused(
    live: Live, token: str | None, host: str | None, expected: int
) -> None:
    status, reply = live.request("GET", "/v1/health", token=token, host=host)
    assert status == expected
    assert reply["status"] == "error"
    assert "result" not in reply
    assert live.token not in json.dumps(reply)


def test_localhost_is_an_accepted_host(live: Live) -> None:
    status, _ = live.request("GET", "/v1/health", host=f"localhost:{live.port}")
    assert status == 200


def test_a_body_over_64_mb_is_refused_before_it_is_read(live: Live) -> None:
    oversized = str(64 * 1024 * 1024 + 1)
    status, reply = live.request("POST", "/v1/call", headers={"Content-Length": oversized})
    assert status == 413
    assert reply["error"]["code"] == "INVALID_ARGUMENT"


@pytest.mark.parametrize(
    "headers",
    [{}, {"Transfer-Encoding": "chunked", "Content-Length": "2"}],
    ids=["no length", "chunked"],
)
def test_a_body_without_a_length_is_refused(live: Live, headers: dict[str, str]) -> None:
    status, _ = live.request("POST", "/v1/call", headers=headers)
    assert status == 411


def test_a_malformed_call_is_refused(live: Live) -> None:
    status, reply = live.request("POST", "/v1/call", {"op": "echo"})
    assert status == 400
    assert reply["error"]["code"] == "INVALID_ARGUMENT"


@pytest.mark.parametrize(
    "client",
    [
        {"pid": 1},
        {"pid": 1, "started_at": ""},
        {"pid": True, "started_at": "x"},
        {"pid": "1", "started_at": "x"},
        {"pid": 1, "started_at": "x", "extra": 1},
        [],
    ],
)
def test_a_call_needs_a_client_the_lease_can_tell_apart(live: Live, client: Any) -> None:
    body = {
        "op": "echo",
        "args": {},
        "request_id": "req-1",
        "operation_id": "op-1",
        "client": client,
        "wait_s": 1,
    }
    status, reply = live.request("POST", "/v1/call", body)
    assert status == 400
    assert "client" in reply["error"]["message"]


def test_a_reused_operation_id_is_refused_without_reporting_the_other_call(live: Live) -> None:
    assert live.call("echo", "op-1", colour="red")["status"] == "done"
    body = {
        "op": "echo",
        "args": {"colour": "blue"},
        "request_id": "req-other",
        "operation_id": "op-1",
        "client": {"pid": 1, "started_at": "test"},
        "wait_s": 1,
    }
    status, reply = live.request("POST", "/v1/call", body)
    assert status == 200
    assert reply["request_id"] == "req-other"
    assert reply["error"]["code"] == "INVALID_ARGUMENT"


class _Warnings(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def test_a_client_that_left_is_not_logged_as_a_failure(live: Live) -> None:
    httpd = live.bridge._httpd
    assert httpd is not None
    warnings = _Warnings()
    httpd.log.addHandler(warnings)
    try:
        for gone in (BrokenPipeError(), ConnectionResetError(), TimeoutError()):
            try:
                raise gone
            except OSError:
                httpd.handle_error(None, ("127.0.0.1", 1))
        assert warnings.records == []
        try:
            raise ValueError("a real failure")
        except ValueError:
            httpd.handle_error(None, ("127.0.0.1", 1))
        assert len(warnings.records) == 1
    finally:
        httpd.log.removeHandler(warnings)


@pytest.mark.skipif(sys.platform != "darwin", reason="SO_NOSIGPIPE is Darwin's")
def test_a_client_that_hangs_up_before_its_reply_cannot_kill_the_process(live: Live) -> None:
    # Krita's embedded Python leaves SIGPIPE at its default, as this test does; the bridge's
    # reply to a client that had reset its connection killed Krita that way.
    body = json.dumps(
        {
            "op": "hold",
            "args": {},
            "request_id": "req-gone",
            "operation_id": "op-gone",
            "client": {"pid": 1, "started_at": "test"},
            "wait_s": 1.0,
        }
    ).encode()
    head = (
        f"POST /v1/call HTTP/1.1\r\nHost: 127.0.0.1:{live.port}\r\n"
        f"Authorization: Bearer {live.token}\r\nContent-Length: {len(body)}\r\n\r\n"
    ).encode()
    previous = signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    try:
        client = socket.create_connection(("127.0.0.1", live.port))
        client.sendall(head + body)
        # Once the call is registered the bridge has read the request, so its reply is next.
        deadline = time.monotonic() + 5
        while live.request("GET", "/v1/operations/op-gone?wait_s=0")[0] != 200:
            assert time.monotonic() < deadline
        # A zero linger resets the connection rather than closing it.
        client.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
        client.close()
        time.sleep(1.5)
        status, _ = live.request("GET", "/v1/health")
    finally:
        signal.signal(signal.SIGPIPE, previous)
    assert status == 200


def test_a_stopping_bridge_answers_503(live: Live) -> None:
    live.bridge.jobs.stop()
    status, reply = live.request("GET", "/v1/health")
    assert status == 503
    assert reply["error"]["code"] == "KRITA_NOT_RUNNING"


def test_a_read_is_marked_sent_once_its_final_reply_is_written(live: Live) -> None:
    body = {
        "op": "echo",
        "args": {},
        "request_id": "req-minted",
        "operation_id": "op-read",
        "client": {"pid": 1, "started_at": "test"},
        "wait_s": 5,
        "ephemeral": True,
    }
    status, reply = live.request("POST", "/v1/call", body)
    assert (status, reply["status"]) == (200, "done")
    operation = live.bridge.jobs._operations["op-read"]
    assert operation.ephemeral and operation.delivered_at is not None


def test_a_reply_still_running_is_not_marked_sent(
    live: Live, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = {
        "op": "hold",
        "args": {},
        "request_id": "req-minted",
        "operation_id": "op-held",
        "client": {"pid": 1, "started_at": "test"},
        "wait_s": 0,
        "ephemeral": True,
    }
    marked: list[str] = []
    monkeypatch.setattr(live.bridge.jobs, "delivered", marked.append)
    _, reply = live.request("POST", "/v1/call", body)
    assert reply["status"] in ("queued", "running")
    assert marked == []


@pytest.mark.parametrize("value", ["yes", 1, None])
def test_ephemeral_must_be_a_boolean(live: Live, value: Any) -> None:
    body = {
        "op": "echo",
        "args": {},
        "request_id": "req-1",
        "operation_id": "op-1",
        "client": {"pid": 1, "started_at": "test"},
        "wait_s": 1,
        "ephemeral": value,
    }
    status, reply = live.request("POST", "/v1/call", body)
    assert status == 400 and "ephemeral" in reply["error"]["message"]
