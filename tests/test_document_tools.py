import asyncio
import datetime
import json
import logging
import stat
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from bridge_core import documents
from bridge_core.bridge import Bridge
from bridge_core.errors import BridgeError
from bridge_core.jobs import Call
from bridge_core.registry import Registry
from fake_krita import FakePort, MainThread
from mcp import Client
from mcp.types import CallToolResult

from krita_art_mcp import journal, paths
from krita_art_mcp.bridge_client import BridgeClient, Done, Failed
from krita_art_mcp.journal import Journal
from krita_art_mcp.server import build_server
from krita_art_mcp.setup_checks import Step
from krita_art_mcp.tools import operations
from krita_art_mcp.tools.dispatch import outcome_of

PLUGIN_PACKAGE = Path(__file__).resolve().parents[1] / "plugin" / "krita_art_mcp_bridge"
A: dict[str, Any] = {"pid": 101, "started_at": "Sat Oct 24 10:00:00 2026"}
B: dict[str, Any] = {"pid": 202, "started_at": "Sat Oct 24 10:05:00 2026"}
NOT_RUNNING = Step("Krita is running", False, "no krita process", "Start Krita.")
NOW = datetime.datetime(2026, 10, 24, 12, 0, tzinfo=datetime.UTC)


def _create(request_id: str = "req-new", **changes: Any) -> dict[str, Any]:
    return {
        "name": "sketch",
        "size_px": [64, 32],
        "color_model": "RGBA",
        "depth": "U8",
        "profile_id": documents.SRGB_PROFILE,
        "background": "transparent",
        "request_id": request_id,
        **changes,
    }


class World:
    def __init__(self, tmp_path: Path, bridge: Bridge, port: FakePort) -> None:
        self.tmp_path = tmp_path
        self.bridge = bridge
        self.port = port
        self.alive: dict[int, bool] = {}
        self.gate = threading.Event()
        self.gate.set()

    def journal(self, name: str = "a") -> Journal:
        return Journal(self.tmp_path / name / "journal", now=lambda: NOW)

    def client(self, identity: dict[str, Any] = A, budget_s: float = 3.0) -> BridgeClient:
        return BridgeClient(
            bridge_file=self.tmp_path / "bridge.json",
            budget_s=budget_s,
            poll_s=0.2,
            is_live_krita=lambda pid: True,
            explain=lambda: NOT_RUNNING,
            identity=identity,
        )

    def server(self, identity: dict[str, Any] = A, name: str = "a", budget_s: float = 3.0) -> Any:
        return Server(build_server(self.client(identity, budget_s), self.journal(name)))


class Server:
    def __init__(self, mcp_server: Any) -> None:
        self.mcp_server = mcp_server

    def call(self, tool: str, arguments: dict[str, Any]) -> CallToolResult:
        async def run() -> CallToolResult:
            async with Client(self.mcp_server) as mcp:
                return await mcp.call_tool(tool, arguments)

        return asyncio.run(run())

    def content(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = self.call(tool, arguments)
        content: dict[str, Any] | None = result.structured_content
        assert content is not None
        return content


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    main = MainThread()
    port = FakePort()
    state: dict[str, World] = {}
    registry = Registry(port, lambda client: state["world"].alive.get(client["pid"], True))

    def slow(args: dict[str, Any], call: Call) -> dict[str, Any]:
        state["world"].gate.wait(10)
        return {"slow": True}

    bridge = Bridge(
        data_dir=tmp_path,
        package_dir=PLUGIN_PACKAGE,
        facts={"krita_version": "5.3.4", "qt_major": 5},
        handlers={**documents.handlers(registry, port), "slow": slow},
        wake=main.wake,
        on_main_thread=main.is_current,
        is_live_krita=lambda pid: False,
        log=logging.getLogger("test_document_tools"),
    )
    main.bridge = bridge
    main.thread.start()
    assert bridge.start()
    state["world"] = World(tmp_path, bridge, port)
    try:
        yield state["world"]
    finally:
        state["world"].gate.set()
        bridge.stop()
        main.stopping = True
        main.thread.join(5)


def _lines(world: World, name: str = "a") -> list[dict[str, Any]]:
    path = world.tmp_path / name / "journal" / "2026-10-24.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_create_list_and_close_through_the_tools(world: World) -> None:
    server = world.server()
    created = server.content("krita_document_create", _create())
    assert created["status"] == "completed"
    document_id = created["document_id"]
    assert created["data"]["mode"] == "new"
    listed = server.content("krita_document_list", {})["data"]["documents"]
    assert [(entry["document_id"], entry["dirty"], entry["mode"]) for entry in listed] == [
        (document_id, False, "new")
    ]
    guard = {"document_id": document_id, "request_id": "req-close"}
    closed = server.content("krita_document_close", {"guard": guard, "dirty_policy": "refuse"})
    assert (closed["status"], closed["document_id"], closed["data"]) == (
        "completed",
        document_id,
        {"closed": True, "baseline_untouched": None},
    )
    assert server.content("krita_document_list", {})["data"]["documents"] == []


def test_the_journal_line_is_written_before_the_call_is_sent(world: World) -> None:
    seen: list[list[str]] = []
    world.port.on_create.append(lambda: seen.append([line["phase"] for line in _lines(world)]))
    world.server().content("krita_document_create", _create())
    assert seen == [["dispatched"]]
    lines = _lines(world)
    assert [line["phase"] for line in lines] == ["dispatched", "finished"]
    assert lines[0]["args"] == _create()
    assert lines[0]["session_id"] == world.bridge.session_id
    assert lines[1]["outcome"] == journal.RECEIPT


def test_the_journal_is_private(world: World) -> None:
    world.server().content("krita_document_create", _create())
    folder = world.tmp_path / "a" / "journal"
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700
    assert stat.S_IMODE((folder / "2026-10-24.jsonl").stat().st_mode) == 0o600


def test_reads_are_not_journaled(world: World) -> None:
    world.server().content("krita_document_list", {})
    assert not (world.tmp_path / "a" / "journal").exists()


def test_a_retry_returns_the_original_receipt_and_makes_nothing(world: World) -> None:
    server = world.server()
    first = server.content("krita_document_create", _create())
    again = server.content("krita_document_create", _create())
    assert again == first
    assert world.port.created == 1
    # Answered from the journal: nothing more was sent.
    assert [line["phase"] for line in _lines(world)] == ["dispatched", "finished"]


def test_a_retry_through_another_server_is_answered_by_the_bridge(world: World) -> None:
    first = world.server(A, "a").content("krita_document_create", _create())
    again = world.server(B, "b").content("krita_document_create", _create())
    assert again == first
    assert world.port.created == 1


def test_other_arguments_under_the_same_request_id_conflict_on_both_sides(world: World) -> None:
    world.server(A, "a").content("krita_document_create", _create())
    changed = _create(name="other")
    by_journal = world.server(A, "a").content("krita_document_create", changed)
    by_bridge = world.server(B, "b").content("krita_document_create", changed)
    assert by_journal["error"]["code"] == by_bridge["error"]["code"] == "REQUEST_ID_CONFLICT"
    assert world.port.created == 1
    assert [line["phase"] for line in _lines(world, "a")] == ["dispatched", "finished"]


def test_a_bridge_conflict_does_not_bind_the_request_id_to_the_refused_arguments(
    world: World,
) -> None:
    first = world.server(A, "a").content("krita_document_create", _create())
    server_b = world.server(B, "b")
    assert (
        server_b.content("krita_document_create", _create(name="other"))["error"]["code"]
        == "REQUEST_ID_CONFLICT"
    )
    assert server_b.content("krita_document_create", _create()) == first


def test_a_call_whose_krita_session_ended_is_never_sent_again(world: World) -> None:
    old = world.journal()
    digest = _digest(_create())
    old.dispatched(
        client="codex",
        request_id="req-new",
        operation_id="op-lost",
        tool="krita_document_create",
        args_sha256=digest,
        session_id="an-earlier-krita",
        args=_create(),
    )
    result = world.server().content("krita_document_create", _create())
    assert result["error"]["code"] == "INTERNAL_ERROR"
    assert result["error"]["retryable"] is False
    assert result["error"]["details"] == {"outcome": "uncertain", "operation_id": "op-lost"}
    assert world.port.created == 0
    assert [line["phase"] for line in _lines(world)] == ["dispatched"]


def test_an_unfinished_call_in_this_krita_session_is_sent_and_deduplicated(world: World) -> None:
    first = world.server(A, "a").content("krita_document_create", _create())
    crashed = world.journal("b")
    crashed.dispatched(
        client="codex",
        request_id="req-new",
        operation_id="op-crashed",
        tool="krita_document_create",
        args_sha256=_digest(_create()),
        session_id=world.bridge.session_id,
        args=_create(),
    )
    assert world.server(A, "b").content("krita_document_create", _create()) == first
    assert world.port.created == 1


def _digest(arguments: dict[str, Any]) -> str:
    from krita_art_mcp.tools.dispatch import args_sha256

    return args_sha256("krita_document_create", arguments)


def test_a_call_refused_before_it_changed_anything_runs_on_retry(world: World) -> None:
    server = world.server()
    world.port.refuse = BridgeError("KRITA_MODAL_DIALOG", "A dialog is open.", True)
    refused = server.content("krita_document_create", _create())
    assert refused["error"]["code"] == "KRITA_MODAL_DIALOG"
    world.port.refuse = None
    created = server.content("krita_document_create", _create())
    assert created["status"] == "completed"
    assert world.port.created == 1
    assert [line.get("outcome") for line in _lines(world)] == [
        None,
        journal.NO_EFFECT,
        None,
        journal.RECEIPT,
    ]


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        (Done({}, "op"), journal.RECEIPT),
        (
            Failed({"code": "DOCUMENT_DIRTY", "retryable": False, "details": {}}, submitted=True),
            journal.RECEIPT,
        ),
        (
            Failed(
                {"code": "KRITA_MODAL_DIALOG", "retryable": True, "details": {}}, submitted=True
            ),
            journal.NO_EFFECT,
        ),
        # stop() fails queued calls as retryable, because they never ran.
        (
            Failed({"code": "CANCELLED", "retryable": True, "details": {}}, submitted=True),
            journal.NO_EFFECT,
        ),
        (
            Failed({"code": "CANCELLED", "retryable": False, "details": {}}, submitted=True),
            journal.RECEIPT,
        ),
        (
            Failed(
                {"code": "REQUEST_ID_CONFLICT", "retryable": False, "details": {}}, submitted=True
            ),
            journal.CONFLICT,
        ),
        # A 503 while Krita quits, or a refused connection: the bridge never took the call.
        (
            Failed({"code": "KRITA_NOT_RUNNING", "retryable": False, "details": {}}),
            journal.NOT_SENT,
        ),
        (
            Failed(
                {"code": "INTERNAL_ERROR", "retryable": False, "details": {"outcome": "uncertain"}}
            ),
            journal.UNKNOWN,
        ),
    ],
)
def test_each_outcome_is_journaled_for_what_it_says_about_a_retry(
    outcome: Done | Failed, expected: str
) -> None:
    assert outcome_of(outcome) == expected


def test_a_503_from_a_quitting_bridge_is_not_submitted(world: World) -> None:
    world.bridge.jobs.stop()
    outcome = world.client().call("document.list")
    assert isinstance(outcome, Failed)
    assert (outcome.error["code"], outcome.submitted) == ("KRITA_NOT_RUNNING", False)


def test_the_lease_holds_across_two_server_processes(world: World) -> None:
    created = world.server(A, "a").content("krita_document_create", _create())
    document_id = created["document_id"]
    server_b = world.server(B, "b")
    guard = {"document_id": document_id, "request_id": "req-b-close"}
    refused = server_b.content("krita_document_close", {"guard": guard, "dirty_policy": "discard"})
    assert refused["error"]["code"] == "DOCUMENT_IN_USE"
    assert refused["document_id"] == document_id
    listed = server_b.content("krita_document_list", {})["data"]["documents"]
    assert [entry["document_id"] for entry in listed] == [document_id]
    world.alive[A["pid"]] = False
    guard = {"document_id": document_id, "request_id": "req-b-close-2"}
    closed = server_b.content("krita_document_close", {"guard": guard, "dirty_policy": "discard"})
    assert closed["data"]["closed"] is True


def test_unsupported_depths_and_profiles_are_refused_before_anything_is_sent(
    world: World,
) -> None:
    server = world.server()
    for changes in ({"depth": "U16"}, {"profile_id": "sRGB-elle-V2-g10.icc"}):
        result = server.content("krita_document_create", _create(**changes))
        assert result["error"]["code"] == "UNSUPPORTED_CAPABILITY"
    assert world.port.created == 0
    assert not (world.tmp_path / "a" / "journal").exists()


def test_operation_get_finishes_a_call_that_came_back_running(world: World) -> None:
    world.gate.clear()
    world.port.on_create.append(lambda: world.gate.wait(10))
    server = world.server(budget_s=0.6)
    running = server.content("krita_document_create", _create())
    assert running["status"] == "running"
    assert [line["phase"] for line in _lines(world)] == ["dispatched"]
    world.gate.set()
    got = world.server(budget_s=3.0).content(
        "krita_operation_get", {"operation_id": running["operation_id"]}
    )
    assert got["status"] == "completed"
    data = got["data"]
    assert (data["tool"], data["state"], data["progress"]) == (
        "krita_document_create",
        "completed",
        None,
    )
    assert data["receipt"]["status"] == "completed"
    assert got["document_id"] == data["receipt"]["document_id"]
    assert [line["phase"] for line in _lines(world)] == ["dispatched", "finished"]
    # The retry now has a receipt, so it is answered from the journal.
    assert server.content("krita_document_create", _create()) == data["receipt"]
    assert world.port.created == 1


def test_operation_get_on_a_settled_call_adds_nothing_to_the_journal(world: World) -> None:
    server = world.server()
    created = server.content("krita_document_create", _create())
    got = server.content("krita_operation_get", {"operation_id": created["operation_id"]})
    assert got["data"]["receipt"] == created
    assert [line["phase"] for line in _lines(world)] == ["dispatched", "finished"]


def test_operation_get_refuses_an_id_nobody_sent_at_once(world: World) -> None:
    started = time.monotonic()
    result = world.server().content("krita_operation_get", {"operation_id": "op-nobody"})
    assert result["error"]["code"] == "INVALID_ARGUMENT"
    assert time.monotonic() - started < 1.5


def test_operation_get_after_a_krita_restart_is_uncertain(world: World) -> None:
    world.journal().dispatched(
        client=None,
        request_id="req-old",
        operation_id="op-old",
        tool="krita_document_create",
        args_sha256="0" * 64,
        session_id="an-earlier-krita",
        args={},
    )
    result = world.server().content("krita_operation_get", {"operation_id": "op-old"})
    assert result["error"]["details"]["outcome"] == "uncertain"


def test_operation_get_reports_a_read_still_running(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(operations.RECEIPTS, "slow", operations.RECEIPTS["server_info"])
    world.gate.clear()
    client = world.client(budget_s=0.4)
    pending = client.call("slow")
    assert not isinstance(pending, Done | Failed)
    got = Server(build_server(client, world.journal())).content(
        "krita_operation_get", {"operation_id": pending.operation_id}
    )
    world.gate.set()
    assert got["status"] == "completed"
    assert got["data"]["state"] in ("queued", "running")
    assert got["data"]["receipt"] is None


def test_cancel_reports_a_finished_operation_and_refuses_a_running_one(world: World) -> None:
    server = world.server()
    created = server.content("krita_document_create", _create())
    done = server.content(
        "krita_operation_cancel",
        {"operation_id": created["operation_id"], "request_id": "req-cancel-1"},
    )
    assert done["data"] == {"operation_id": created["operation_id"], "state": "completed"}
    world.gate.clear()
    client = world.client(budget_s=0.4)
    running = client.call("slow")
    assert not isinstance(running, Done | Failed)
    queued = client.call("document.list")
    assert not isinstance(queued, Done | Failed)
    cancel_server = Server(build_server(client, world.journal()))
    refused = cancel_server.content(
        "krita_operation_cancel", {"operation_id": running.operation_id, "request_id": "req-c2"}
    )
    cancelled = cancel_server.content(
        "krita_operation_cancel", {"operation_id": queued.operation_id, "request_id": "req-c3"}
    )
    world.gate.set()
    assert refused["error"]["code"] == "UNSUPPORTED_CAPABILITY"
    assert refused["error"]["details"]["state"] == "running"
    assert cancelled["data"] == {"operation_id": queued.operation_id, "state": "cancelled"}


def test_a_newer_journal_is_refused_with_a_clear_error(world: World) -> None:
    folder = world.tmp_path / "a" / "journal"
    folder.mkdir(parents=True)
    (folder / "2026-10-24.jsonl").write_text(json.dumps({"v": 2, "request_id": "x"}) + "\n")
    result = world.server().content("krita_document_create", _create())
    assert result["error"]["code"] == "INTERNAL_ERROR"
    assert "newer" in result["error"]["message"]
    assert world.port.created == 0


def _journal_on(tmp_path: Path, day: datetime.datetime) -> Journal:
    return Journal(tmp_path / "journal", now=lambda: day)


def test_the_journal_remembers_a_request_for_seven_days(tmp_path: Path) -> None:
    for days_ago in (6, 7):
        _journal_on(tmp_path, NOW - datetime.timedelta(days=days_ago)).dispatched(
            client=None,
            request_id=f"req-{days_ago}",
            operation_id=f"op-{days_ago}",
            tool="krita_document_create",
            args_sha256="0" * 64,
            session_id="s",
            args={},
        )
    today = _journal_on(tmp_path, NOW)
    assert today.lookup("req-6") is not None
    assert today.lookup("req-7") is None


def test_the_journal_follows_lines_other_processes_append(tmp_path: Path) -> None:
    mine, theirs = _journal_on(tmp_path, NOW), _journal_on(tmp_path, NOW)
    theirs.dispatched(
        client=None,
        request_id="req-0",
        operation_id="op-0",
        tool="t",
        args_sha256="0" * 64,
        session_id="s",
        args={},
    )
    assert mine.lookup("req-0") is not None
    assert mine.lookup("req-1") is None
    theirs.dispatched(
        client=None,
        request_id="req-1",
        operation_id="op-1",
        tool="t",
        args_sha256="0" * 64,
        session_id="s",
        args={},
    )
    prior = mine.lookup("req-1")
    assert prior is not None and prior.attempts[0].operation_id == "op-1"


def test_a_line_cut_short_by_a_crash_neither_breaks_the_journal_nor_the_next_line(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "journal"
    folder.mkdir()
    (folder / "2026-10-24.jsonl").write_bytes(b'{"v": 1, "request_id": "req-cut", "pha')
    writer = _journal_on(tmp_path, NOW)
    writer.dispatched(
        client=None,
        request_id="req-1",
        operation_id="op-1",
        tool="t",
        args_sha256="0" * 64,
        session_id="s",
        args={},
    )
    reader = _journal_on(tmp_path, NOW)
    assert reader.lookup("req-1") is not None
    assert reader.lookup("req-cut") is None


def test_the_journal_follows_the_data_dir_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KRITA_ART_MCP_DATA_DIR", str(tmp_path))
    assert paths.journal_dir() == tmp_path / "journal"
    assert paths.bridge_file() == paths.default_data_dir() / "bridge.json"
    monkeypatch.delenv("KRITA_ART_MCP_DATA_DIR")
    assert paths.journal_dir() == paths.default_data_dir() / "journal"


def test_a_retry_of_a_running_call_follows_the_original_operation(world: World) -> None:
    world.gate.clear()
    world.port.on_create.append(lambda: world.gate.wait(10))
    first = world.server(A, "a", budget_s=0.6).content("krita_document_create", _create())
    again = world.server(B, "b", budget_s=0.6).content("krita_document_create", _create())
    world.gate.set()
    assert first["status"] == again["status"] == "running"
    assert again["operation_id"] == first["operation_id"]


def test_a_server_that_cannot_read_its_start_time_sends_nothing(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    from krita_art_mcp import processes

    monkeypatch.setattr(processes, "start_time", lambda pid: "")
    client = BridgeClient(
        bridge_file=world.tmp_path / "bridge.json",
        is_live_krita=lambda pid: True,
        explain=lambda: NOT_RUNNING,
    )
    outcome = client.call("document.list")
    assert isinstance(outcome, Failed)
    assert (outcome.error["code"], outcome.error["retryable"]) == ("INTERNAL_ERROR", True)


def test_a_receipt_that_breaks_its_tools_schema_is_an_internal_error(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    from krita_art_mcp import envelope

    broken = ("krita_document_list", lambda outcome: envelope.completed({"wrong": 1}, "x"))
    monkeypatch.setitem(operations.RECEIPTS, "document.list", broken)
    client = world.client()
    done = client.call("document.list")
    assert isinstance(done, Done)
    got = Server(build_server(client, world.journal())).content(
        "krita_operation_get", {"operation_id": done.operation_id}
    )
    assert got["error"]["code"] == "INTERNAL_ERROR"
    assert "krita_document_list" in got["error"]["details"]["reason"]


def _attempt(journal_: Journal, operation_id: str, session_id: str = "s") -> None:
    journal_.dispatched(
        client=None,
        request_id="req-1",
        operation_id=operation_id,
        tool="t",
        args_sha256="0" * 64,
        session_id=session_id,
        args={},
    )


def _finish(journal_: Journal, operation_id: str, outcome: str) -> None:
    journal_.finished(
        client=None,
        request_id="req-1",
        operation_id=operation_id,
        tool="t",
        args_sha256="0" * 64,
        session_id="s",
        outcome=outcome,
        result={"structured": {}, "text": "", "is_error": False},
    )


def test_an_outcome_from_the_bridge_settles_every_attempt_it_deduplicated(
    tmp_path: Path,
) -> None:
    writer = _journal_on(tmp_path, NOW)
    _attempt(writer, "op-1")
    _attempt(writer, "op-2")
    _finish(writer, "op-2", journal.NO_EFFECT)
    prior = _journal_on(tmp_path, NOW).lookup("req-1")
    assert prior is not None
    assert [attempt.outcome for attempt in prior.attempts] == [journal.NO_EFFECT] * 2


def test_a_call_that_never_reached_the_bridge_settles_only_itself(tmp_path: Path) -> None:
    writer = _journal_on(tmp_path, NOW)
    _attempt(writer, "op-1")
    _attempt(writer, "op-2")
    _finish(writer, "op-2", journal.NOT_SENT)
    prior = _journal_on(tmp_path, NOW).lookup("req-1")
    assert prior is not None
    assert [attempt.outcome for attempt in prior.attempts] == [journal.UNKNOWN, journal.NOT_SENT]
    assert prior.unknown_elsewhere("later-krita") is prior.attempts[0]


def test_a_poll_waits_for_a_call_the_bridge_has_not_registered_yet(world: World) -> None:
    # A POST stuck behind a long Krita call reaches the bridge after its own polls began.
    def late() -> None:
        time.sleep(0.5)
        world.bridge.jobs.submit("op-late", "req-late", "document.list", {}, A)

    threading.Thread(target=late, daemon=True).start()
    outcome = world.client().operation("op-late", sent_in=world.bridge.session_id)
    assert isinstance(outcome, Done)
    assert outcome.result == {"documents": []}
