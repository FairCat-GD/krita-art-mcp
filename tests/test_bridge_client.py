import asyncio
import json
import logging
import socket
import threading
import time
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from bridge_core.bridge import Bridge
from bridge_core.jobs import Call
from fake_krita import MainThread
from jsonschema import Draft202012Validator
from mcp import Client
from mcp.types import CallToolResult

from krita_art_mcp import schemas
from krita_art_mcp.bridge_client import BridgeClient, Done, Failed, Pending
from krita_art_mcp.journal import Journal
from krita_art_mcp.paths import Places
from krita_art_mcp.server import build_server
from krita_art_mcp.setup_checks import Step

PLUGIN_PACKAGE = Path(__file__).resolve().parents[1] / "plugin" / "krita_art_mcp_bridge"
FACTS = {"krita_version": "5.3.4", "qt_major": 5}
NOT_RUNNING = Step("Krita is running", False, "no krita process", "Start Krita.")


class Live:
    def __init__(self, bridge: Bridge, bridge_file: Path, release: threading.Event) -> None:
        self.bridge = bridge
        self.bridge_file = bridge_file
        self.release = release

    def client(self, budget_s: float = 2.0, **options: Any) -> BridgeClient:
        return _client(self.bridge_file, budget_s=budget_s, **options)


def _client(
    bridge_file: Path,
    budget_s: float = 2.0,
    is_live_krita: Callable[[int], bool] = lambda pid: True,
) -> BridgeClient:
    return BridgeClient(
        bridge_file=bridge_file,
        budget_s=budget_s,
        poll_s=0.2,
        is_live_krita=is_live_krita,
        explain=lambda: NOT_RUNNING,
    )


@pytest.fixture
def live(tmp_path: Path) -> Iterator[Live]:
    main = MainThread()
    release = threading.Event()

    def hold(args: dict[str, Any], call: Call) -> dict[str, Any]:
        release.wait(10)
        return {"held": True}

    def boom(args: dict[str, Any], call: Call) -> dict[str, Any]:
        raise RuntimeError("boom")

    bridge = Bridge(
        data_dir=tmp_path,
        package_dir=PLUGIN_PACKAGE,
        facts=FACTS,
        handlers={"echo": lambda args, call: {"echo": args}, "hold": hold, "boom": boom},
        wake=main.wake,
        on_main_thread=main.is_current,
        is_live_krita=lambda pid: False,
        log=logging.getLogger("test_bridge_client"),
    )
    main.bridge = bridge
    main.thread.start()
    assert bridge.start()
    try:
        yield Live(bridge, tmp_path / "bridge.json", release)
    finally:
        release.set()
        bridge.stop()
        main.stopping = True
        main.thread.join(5)


class Scripted(ThreadingHTTPServer):
    # A fake bridge that answers each request from a script.
    daemon_threads = True

    def __init__(self, replies: list[tuple[int, Any]]) -> None:
        super().__init__(("127.0.0.1", 0), _ScriptedHandler)
        self.replies = replies
        self.paths: list[str] = []


class _ScriptedHandler(BaseHTTPRequestHandler):
    server: Scripted

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def _answer(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        self.server.paths.append(self.path)
        status, body = self.server.replies.pop(0) if self.server.replies else (500, None)
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = _answer
    do_POST = _answer


@pytest.fixture
def scripted(tmp_path: Path) -> Iterator[Callable[[list[tuple[int, Any]]], Path]]:
    servers: list[Scripted] = []

    def start(replies: list[tuple[int, Any]]) -> Path:
        server = Scripted(replies)
        servers.append(server)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return _write_bridge_file(tmp_path, server.server_address[1], "scripted")

    yield start
    for server in servers:
        server.shutdown()
        server.server_close()


def _write_bridge_file(directory: Path, port: int, session_id: str, **overrides: Any) -> Path:
    path = directory / "bridge.json"
    info = {
        "port": port,
        "token": "t" * 64,
        "pid": 4242,
        "session_id": session_id,
        "protocol": 1,
        "plugin_version": "0.2.0",
        "plugin_hash": "0" * 64,
        "krita_version": "5.3.4",
        "qt_major": 5,
        **overrides,
    }
    path.write_text(json.dumps(info))
    return path


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _code(outcome: Any) -> str:
    assert isinstance(outcome, Failed), outcome
    return str(outcome.error["code"])


def test_a_call_comes_back_done(live: Live) -> None:
    outcome = live.client().call("echo", {"colour": "red"})
    assert isinstance(outcome, Done)
    assert outcome.result == {"echo": {"colour": "red"}}
    assert outcome.operation_id is not None and outcome.operation_id.startswith("op-")


def test_health_comes_back_done(live: Live) -> None:
    health = live.client().health()
    assert isinstance(health, Done)
    assert health.result["session_id"] == live.bridge.session_id


def test_a_long_call_returns_running_after_the_budget_then_its_result(live: Live) -> None:
    client = live.client(budget_s=0.6)
    started = time.monotonic()
    outcome = client.call("hold")
    elapsed = time.monotonic() - started
    assert isinstance(outcome, Pending)
    assert outcome.status == "running"
    # Polls are capped at what is left of the budget.
    assert 0.6 <= elapsed < 1.2
    live.release.set()
    later = client.operation(outcome.operation_id)
    assert isinstance(later, Done)
    assert later.result == {"held": True}


def test_a_plugin_error_passes_through(live: Live) -> None:
    outcome = live.client().call("boom")
    assert _code(outcome) == "INTERNAL_ERROR"
    assert isinstance(outcome, Failed) and outcome.error["details"] == {"op": "boom"}
    assert _code(live.client().call("paint_everything")) == "INVALID_ARGUMENT"


def test_a_wrong_token_is_refused_by_the_bridge(live: Live) -> None:
    info = json.loads(live.bridge_file.read_text())
    _write_bridge_file(live.bridge_file.parent, info["port"], info["session_id"], token="x" * 64)
    outcome = live.client().call("echo")
    assert _code(outcome) == "INTERNAL_ERROR"
    assert isinstance(outcome, Failed) and "token" in outcome.error["message"]


def test_no_bridge_file_means_krita_is_not_running(tmp_path: Path) -> None:
    outcome = _client(tmp_path / "bridge.json").call("echo")
    assert _code(outcome) == "KRITA_NOT_RUNNING"
    assert isinstance(outcome, Failed)
    assert outcome.error["details"] == {
        "step": "Krita is running",
        "detail": "no krita process",
        "fix": "Start Krita.",
    }


def test_a_stale_bridge_file_means_krita_is_not_running(tmp_path: Path) -> None:
    path = _write_bridge_file(tmp_path, _free_port(), "stale")
    outcome = _client(path, is_live_krita=lambda pid: False).call("echo")
    assert _code(outcome) == "KRITA_NOT_RUNNING"


def test_a_refused_connection_with_krita_alive_is_retryable(tmp_path: Path) -> None:
    path = _write_bridge_file(tmp_path, _free_port(), "refusing")
    outcome = _client(path).call("echo")
    assert _code(outcome) == "INTERNAL_ERROR"
    assert isinstance(outcome, Failed) and outcome.error["retryable"] is True


def test_a_refused_connection_after_krita_died_means_not_running(tmp_path: Path) -> None:
    path = _write_bridge_file(tmp_path, _free_port(), "dying")
    answers = iter([True, False])
    outcome = _client(path, is_live_krita=lambda pid: next(answers)).call("echo")
    assert _code(outcome) == "KRITA_NOT_RUNNING"


def test_another_protocol_is_a_mismatch(tmp_path: Path) -> None:
    path = _write_bridge_file(tmp_path, _free_port(), "future", protocol=2)
    outcome = _client(path).call("echo")
    assert _code(outcome) == "PROTOCOL_MISMATCH"
    assert isinstance(outcome, Failed)
    assert outcome.error["details"] == {"bridge_protocol": 2, "server_protocol": 1}


def test_a_malformed_bridge_file_is_an_internal_error(tmp_path: Path) -> None:
    path = _write_bridge_file(tmp_path, _free_port(), "broken", token=7)
    outcome = _client(path).call("echo")
    assert _code(outcome) == "INTERNAL_ERROR"
    assert isinstance(outcome, Failed) and "bridge.json is malformed" in outcome.error["message"]


def test_a_silent_bridge_returns_running_within_the_budget(tmp_path: Path) -> None:
    # A listening socket that never accepts: connected, but Krita holds the GIL.
    with socket.socket() as silent:
        silent.bind(("127.0.0.1", 0))
        silent.listen(16)
        path = _write_bridge_file(tmp_path, silent.getsockname()[1], "silent")
        started = time.monotonic()
        outcome = _client(path, budget_s=0.6).call("echo")
        elapsed = time.monotonic() - started
    assert isinstance(outcome, Pending)
    assert outcome.status == "running"
    assert 0.6 <= elapsed < 1.2


def _uncertain(outcome: Any) -> bool:
    return (
        isinstance(outcome, Failed)
        and outcome.error["code"] == "INTERNAL_ERROR"
        and outcome.error["retryable"] is False
        and outcome.error["details"].get("outcome") == "uncertain"
    )


def _running(session_id: str = "scripted") -> tuple[int, Any]:
    return 200, {
        "session_id": session_id,
        "status": "running",
        "operation_id": "op-x",
        "request_id": "req-x",
    }


@pytest.mark.parametrize(
    ("replies", "reason"),
    [
        ([_running(), _running("another")], "another Krita session answered"),
        ([_running(), (200, b"not json")], "malformed reply"),
        ([_running(), (404, {"session_id": "scripted", "status": "error"})], "no longer knows"),
        ([_running(), (503, {"session_id": "scripted", "status": "error"})], "HTTP 503"),
    ],
    ids=["session changed", "malformed", "forgotten", "quitting"],
)
def test_a_bridge_lost_after_the_call_was_sent_is_uncertain(
    scripted: Callable[[list[tuple[int, Any]]], Path],
    replies: list[tuple[int, Any]],
    reason: str,
) -> None:
    outcome = _client(scripted(replies)).call("echo")
    assert _uncertain(outcome)
    assert isinstance(outcome, Failed) and reason in outcome.error["message"]


def test_a_bridge_that_stops_mid_call_is_uncertain(live: Live) -> None:
    client = live.client(budget_s=5.0)
    outcomes: list[Any] = []
    caller = threading.Thread(target=lambda: outcomes.append(client.call("hold")))
    caller.start()
    time.sleep(0.4)
    # Krita quits while the call runs: the call may still finish, but nobody can report it.
    live.bridge.stop()
    caller.join(10)
    [outcome] = outcomes
    assert _uncertain(outcome)


def test_a_bridge_that_stops_listening_mid_call_is_uncertain(tmp_path: Path) -> None:
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    body = json.dumps(_running()[1]).encode()

    def answer_once_then_close() -> None:
        connection, _ = listener.accept()
        connection.recv(65536)
        head = f"HTTP/1.1 200 OK\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n"
        connection.sendall(head.encode() + body)
        connection.close()
        listener.close()

    threading.Thread(target=answer_once_then_close, daemon=True).start()
    path = _write_bridge_file(tmp_path, listener.getsockname()[1], "scripted")
    outcome = _client(path).call("echo")
    assert _uncertain(outcome)
    assert isinstance(outcome, Failed) and "stopped accepting" in outcome.error["message"]


def _call_tool(client: BridgeClient, name: str, data_dir: Path) -> CallToolResult:
    async def call() -> CallToolResult:
        places = Places.under(data_dir, data_dir)
        async with Client(build_server(client, Journal(data_dir / "journal"), places)) as mcp:
            return await mcp.call_tool(name, {})

    return asyncio.run(call())


def _valid(result: CallToolResult) -> dict[str, Any]:
    schema = schemas.load("krita_server_info")["outputSchema"]
    content = result.structured_content
    assert content is not None
    assert [error.message for error in Draft202012Validator(schema).iter_errors(content)] == []
    return dict(content)


def test_krita_server_info_reports_the_bridge(live: Live) -> None:
    result = _call_tool(live.client(), "krita_server_info", live.bridge_file.parent)
    content = _valid(result)
    assert result.is_error is False
    assert content["status"] == "completed"
    data = content["data"]
    assert data["session_id"] == live.bridge.session_id
    assert (data["krita_version"], data["qt_major"], data["protocol"]) == ("5.3.4", 5, 1)
    assert data["capabilities"] == live.bridge.health["capabilities"]
    assert result.content[0].type == "text"


def test_krita_server_info_names_the_missing_step(tmp_path: Path) -> None:
    result = _call_tool(_client(tmp_path / "bridge.json"), "krita_server_info", tmp_path)
    content = _valid(result)
    assert result.is_error is True
    assert content["status"] == "failed"
    assert content["error"]["code"] == "KRITA_NOT_RUNNING"
    assert "Start Krita." in content["error"]["message"]


def test_krita_server_info_reports_running_after_the_budget(tmp_path: Path) -> None:
    with socket.socket() as silent:
        silent.bind(("127.0.0.1", 0))
        silent.listen(16)
        path = _write_bridge_file(tmp_path, silent.getsockname()[1], "silent")
        result = _call_tool(_client(path, budget_s=0.4), "krita_server_info", tmp_path)
    content = _valid(result)
    assert result.is_error is False
    assert content["status"] == "running"
    assert content["operation_id"].startswith("op-")
