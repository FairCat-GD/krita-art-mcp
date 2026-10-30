import datetime
import hashlib
import json
import os
import stat
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from bridge_core import documents
from bridge_core.errors import BridgeError
from fake_krita import bgra
from worlds import NOT_RUNNING, NOW, A, B, Server, World, running_world

from krita_art_mcp import baselines, journal, paths, roots
from krita_art_mcp.bridge_client import BridgeClient, Done, Failed
from krita_art_mcp.journal import Journal
from krita_art_mcp.server import build_server
from krita_art_mcp.tools import documents as documents_tools
from krita_art_mcp.tools import operations
from krita_art_mcp.tools.dispatch import args_sha256, outcome_of


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


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    with running_world(tmp_path) as running:
        yield running


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
    assert journal.arguments(world.tmp_path / "a" / "journal", lines[0]) == _create()
    assert lines[0]["session_id"] == world.bridge.session_id
    assert lines[1]["outcome"] == journal.RECEIPT


def test_the_journal_is_private(world: World) -> None:
    world.server().content("krita_document_create", _create())
    folder = world.tmp_path / "a" / "journal"
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700
    assert stat.S_IMODE((folder / "2026-10-24.jsonl").stat().st_mode) == 0o600


def test_a_line_names_its_arguments_file_and_never_holds_them(world: World) -> None:
    world.server().content("krita_document_create", _create())
    folder = world.tmp_path / "a" / "journal"
    dispatched = _lines(world)[0]
    assert dispatched["v"] == journal.VERSION == 2
    assert "args" not in dispatched
    held = folder / dispatched["args_file"]
    assert held.parent.parent == folder / journal.ARGS_DIR
    assert json.loads(held.read_text()) == _create()
    for path in (folder / journal.ARGS_DIR, held.parent, held):
        assert stat.S_IMODE(path.stat().st_mode) == (0o600 if path.is_file() else 0o700)
    assert not list(held.parent.glob("*.partial"))


def test_a_day_s_argument_folder_is_made_private_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    made: list[Path] = []
    real = paths.private_dir

    def counted(path: Path) -> Path:
        made.append(path)
        return real(path)

    monkeypatch.setattr(journal, "private_dir", counted)
    writer = _journal_on(tmp_path, NOW)
    _attempt(writer, "op-1")
    first = len(made)
    _attempt(writer, "op-2")
    # The second call makes only the journal's own folder private, for its line.
    assert len(made) - first == 1
    assert (tmp_path / "journal" / journal.ARGS_DIR).is_dir()


def test_a_version_1_line_with_its_arguments_inline_is_still_read(tmp_path: Path) -> None:
    folder = tmp_path / "journal"
    folder.mkdir()
    line = {
        "v": 1,
        "ts": "2026-10-24T10:00:00.000+00:00",
        "client": None,
        "request_id": "req-old",
        "operation_id": "op-old",
        "tool": "krita_document_create",
        "args_sha256": "a" * 64,
        "session_id": "s-old",
        "phase": "dispatched",
        "args": {"name": "kept"},
        "document_path": None,
        "layer_names": [],
    }
    (folder / "2026-10-24.jsonl").write_text(json.dumps(line) + "\n")
    prior = _journal_on(tmp_path, NOW).lookup("req-old")
    assert prior is not None and prior.binding() == ("krita_document_create", "a" * 64)
    assert journal.arguments(folder, line) == {"name": "kept"}


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
        # A queued call that is cancelled, or failed at stop, never ran.
        (
            Failed({"code": "CANCELLED", "retryable": True, "details": {}}, submitted=True),
            journal.NO_EFFECT,
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
        # The bridge never registered it, but a late arrival could still run it.
        (
            Failed(
                {
                    "code": "INTERNAL_ERROR",
                    "retryable": True,
                    "details": {"outcome": "unregistered"},
                }
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
    got = Server(build_server(client, world.journal(), world.places())).content(
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
    cancel_server = Server(build_server(client, world.journal(), world.places()))
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
    newer = {"v": journal.VERSION + 1, "request_id": "x"}
    (folder / "2026-10-24.jsonl").write_text(json.dumps(newer) + "\n")
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
        bridge_file=world.data / "bridge.json",
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

    broken = operations.Known(
        "krita_document_list", lambda outcome: envelope.completed({"wrong": 1}, "x")
    )
    monkeypatch.setitem(operations.RECEIPTS, "document.list", broken)
    client = world.client()
    done = client.call("document.list")
    assert isinstance(done, Done)
    got = Server(build_server(client, world.journal(), world.places())).content(
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


def _finish(
    journal_: Journal, operation_id: str, outcome: str, bridge_operation_id: str | None = None
) -> None:
    journal_.finished(
        client=None,
        request_id="req-1",
        operation_id=operation_id,
        tool="t",
        args_sha256="0" * 64,
        session_id="s",
        outcome=outcome,
        result={"structured": {}, "text": "", "is_error": False},
        bridge_operation_id=bridge_operation_id,
    )


@pytest.mark.parametrize(
    ("outcome", "bridge_operation", "settled"),
    [
        (journal.RECEIPT, "op-2", [journal.RECEIPT, journal.RECEIPT]),
        # The bridge answered op-2 with op-1's operation, so the refusal is both attempts'.
        (journal.NO_EFFECT, "op-1", [journal.NO_EFFECT, journal.NO_EFFECT]),
        # Its own operation: op-1 may be another attempt, sent after a release, that ran.
        (journal.NO_EFFECT, "op-2", [journal.UNKNOWN, journal.NO_EFFECT]),
    ],
    ids=["a receipt", "a deduplicated refusal", "a refusal of its own"],
)
def test_a_receipt_settles_every_attempt_it_deduplicated_and_a_refusal_only_those_it_names(
    tmp_path: Path, outcome: str, bridge_operation: str, settled: list[str]
) -> None:
    writer = _journal_on(tmp_path, NOW)
    _attempt(writer, "op-1")
    _attempt(writer, "op-2")
    _finish(writer, "op-2", outcome, bridge_operation)
    prior = _journal_on(tmp_path, NOW).lookup("req-1")
    assert prior is not None
    assert [attempt.outcome for attempt in prior.attempts] == settled


def test_a_refusal_a_retry_shared_settles_both_attempts(world: World) -> None:
    # The retry joined the running call, so the bridge answers it with that call's outcome.
    def refused_once_released() -> None:
        world.gate.wait(10)
        raise BridgeError("KRITA_MODAL_DIALOG", "A dialog is open.", True)

    world.gate.clear()
    world.port.on_create.append(refused_once_released)
    running = world.server(budget_s=0.4).content("krita_document_create", _create())
    assert running["status"] == "running"
    retried: list[dict[str, Any]] = []
    retry = threading.Thread(
        target=lambda: retried.append(
            world.server(budget_s=5.0).content("krita_document_create", _create())
        )
    )
    retry.start()
    time.sleep(0.3)
    world.gate.set()
    retry.join(10)
    assert retried[0]["error"]["code"] == "KRITA_MODAL_DIALOG"
    prior = world.journal().lookup("req-new")
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


def test_a_call_the_bridge_never_registered_ends_and_its_retry_runs_once(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = world.client(grace_s=0.3)
    send = client._request

    def lossy(bridge: Any, method: str, path: str, body: Any, timeout: float) -> Any:
        if path == "/v1/call":
            raise ConnectionResetError("the connection was reset before the bridge read it")
        return send(bridge, method, path, body, timeout)

    monkeypatch.setattr(client, "_request", lossy)
    server = Server(build_server(client, world.journal(), world.places()))
    lost = server.content("krita_document_create", _create())
    assert lost["error"]["details"]["outcome"] == "unregistered"
    assert lost["error"]["retryable"] is True
    monkeypatch.setattr(client, "_request", send)
    created = server.content("krita_document_create", _create())
    assert created["status"] == "completed"
    assert world.port.created == 1
    assert [line.get("outcome") for line in _lines(world)] == [
        None,
        journal.UNKNOWN,
        None,
        journal.RECEIPT,
    ]


def test_a_poll_waits_for_a_call_the_bridge_has_not_registered_yet(world: World) -> None:
    # A POST stuck behind a long Krita call reaches the bridge after its own polls began.
    def late() -> None:
        time.sleep(0.5)
        world.bridge.jobs.submit("op-late", "req-late", "document.list", {}, A)

    threading.Thread(target=late, daemon=True).start()
    outcome = world.client().operation("op-late", sent_in=world.bridge.session_id)
    assert isinstance(outcome, Done)
    assert outcome.result == {"documents": []}


@pytest.mark.parametrize(
    "line",
    [
        {"v": 1},
        {"v": 1, "request_id": "req-x", "phase": "dispatched"},
        {
            "v": 1,
            "request_id": "req-x",
            "phase": "elsewhere",
            "operation_id": "o",
            "session_id": "s",
            "tool": "t",
            "args_sha256": "0",
        },
        {
            "v": 1,
            "request_id": "req-x",
            "phase": "finished",
            "operation_id": "o",
            "session_id": "s",
            "tool": "t",
            "args_sha256": "0",
            "outcome": "maybe",
        },
    ],
)
def test_a_malformed_line_is_skipped_and_the_journal_keeps_working(
    world: World, line: dict[str, Any]
) -> None:
    folder = world.tmp_path / "a" / "journal"
    folder.mkdir(parents=True)
    (folder / "2026-10-24.jsonl").write_text(json.dumps(line) + "\n")
    server = world.server()
    first = server.content("krita_document_create", _create())
    assert first["status"] == "completed"
    assert server.content("krita_document_create", _create()) == first
    assert world.port.created == 1


def test_a_refused_read_never_applies_a_line_twice(tmp_path: Path) -> None:
    writer = _journal_on(tmp_path, NOW)
    _attempt(writer, "op-1")
    path = tmp_path / "journal" / "2026-10-24.jsonl"
    with path.open("a") as stream:
        stream.write(json.dumps({"v": journal.VERSION + 1, "request_id": "req-new"}) + "\n")
    reader = _journal_on(tmp_path, NOW)
    for _ in range(2):
        with pytest.raises(journal.JournalError):
            reader.lookup("req-1")
    lines = path.read_text().splitlines()
    path.write_text(lines[0] + "\n")
    prior = reader.lookup("req-1")
    assert prior is not None and len(prior.attempts) == 1


def test_a_finished_call_is_not_remembered_by_the_client(world: World) -> None:
    client = world.client()
    done = client.call("document.list")
    assert isinstance(done, Done) and done.operation_id is not None
    # A finished id this process sent is followed like any other: strict, and found.
    again = client.operation(done.operation_id)
    assert isinstance(again, Done)
    assert client._sent == {}


def _art(world: World) -> Path:
    # A root of the world's own; the bridge and the servers read the same config.json.
    art = world.tmp_path / "art"
    (art / "accepted").mkdir(parents=True, exist_ok=True)
    roots.save(world.data / "config.json", [str(art)])
    return art


def _open(world: World, request_id: str = "req-open", **changes: Any) -> dict[str, Any]:
    art = _art(world)
    source = art / "accepted" / "hero.kra"
    source.write_bytes(b"accepted art")
    return {
        "source_path": str(source),
        "source_sha256": hashlib.sha256(b"accepted art").hexdigest(),
        "mode": "working_copy",
        "working_dir": str(art / "work"),
        "request_id": request_id,
        **changes,
    }


def _baselines(world: World, name: str = "a") -> list[str]:
    folder = world.tmp_path / name / "baselines"
    return sorted(path.name for path in folder.iterdir()) if folder.exists() else []


def _render(world: World, opened: dict[str, Any]) -> dict[str, Any]:
    # The first render that needs the baseline reads it.
    source = {
        "document_id": opened["document_id"],
        "frame": 0,
        "target": "composite",
        "baseline_id": opened["data"]["baseline_id"],
    }
    arguments = {
        "recipes": [{"id": "native", "target_size_px": [8, 4]}],
        "filter": "nearest",
        "sources": [source],
        "overlays": [],
        "backgrounds": ["transparent"],
    }
    rendered: dict[str, Any] = world.server().content("krita_preview_render", arguments)
    return rendered


def test_open_names_a_baseline_that_a_render_keeps_and_close_drops(world: World) -> None:
    server = world.server()
    opened = server.content("krita_document_open", _open(world))
    assert opened["status"] == "completed"
    data = opened["data"]
    assert data["working_copy"] is True and data["mode"] == "working_copy"
    assert set(data) == set(documents_tools.OPEN_DATA)
    document_id = opened["document_id"]
    # Lazily: the open writes nothing, and a render keeps the composite as RGBA.
    assert _baselines(world) == [] and list((world.data / "transfer").iterdir()) == []
    seen = server.content("krita_document_inspect", {"document_id": document_id, "frame": 0})
    assert seen["status"] == "completed" and seen["data"]["layers"] == data["layers"]
    assert seen["data"]["baseline_id"] == data["baseline_id"]
    assert _render(world, opened)["status"] == "completed"
    assert _baselines(world) == [f"{data['baseline_id']}.npy"]
    kept = baselines.load(world.tmp_path / "a" / "baselines", data["baseline_id"])
    assert kept is not None
    raw = np.frombuffer(bgra(8, 4), dtype=np.uint8).reshape(4, 8, 4)
    assert (kept == raw[..., [2, 1, 0, 3]]).all()
    assert list((world.data / "transfer").iterdir()) == []
    guard = {"document_id": document_id, "request_id": "req-close"}
    closed = server.content("krita_document_close", {"guard": guard, "dirty_policy": "refuse"})
    assert closed["data"] == {"closed": True, "baseline_untouched": True}
    assert _baselines(world) == []


def test_a_retried_open_returns_its_receipt_and_copies_once(world: World) -> None:
    first = world.server().content("krita_document_open", _open(world))
    assert world.server().content("krita_document_open", _open(world)) == first
    # Through another server, the bridge answers with the same operation.
    assert world.server(B, "b").content("krita_document_open", _open(world)) == first
    assert len(world.port.opened) == 1
    assert len(os.listdir(world.tmp_path / "art" / "work")) == 1


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"source_path": "/elsewhere/hero.kra"}, "PATH_NOT_ALLOWED"),
        ({"working_dir": "/elsewhere/work"}, "PATH_NOT_ALLOWED"),
        ({"source_path": "/elsewhere/hero.psd"}, "UNSUPPORTED_CAPABILITY"),
        ({"editable_layer_names": ["rim"]}, "INVALID_ARGUMENT"),
        ({"editable_layer_names": ["rim", "rim"]}, "INVALID_ARGUMENT"),
        ({"mode": "read_only"}, "INVALID_ARGUMENT"),
        ({"working_dir": None}, "INVALID_ARGUMENT"),
        ({"source_path": "relative/hero.kra"}, "INVALID_ARGUMENT"),
    ],
    ids=[
        "source outside",
        "working_dir outside",
        "another format",
        "names for a KRA",
        "a name twice",
        "read_only with a working_dir",
        "no working_dir",
        "a relative path",
    ],
)
def test_the_server_refuses_an_open_before_anything_is_sent(
    world: World, changes: dict[str, Any], code: str
) -> None:
    arguments = {
        key: value for key, value in {**_open(world), **changes}.items() if value is not None
    }
    refused = world.server().content("krita_document_open", arguments)
    assert refused["error"]["code"] == code
    assert refused["operation_id"] is None
    assert world.port.opened == [] and not (world.tmp_path / "a" / "journal").exists()


def test_the_working_dir_is_never_the_sources_folder(world: World) -> None:
    arguments = _open(world, working_dir=str(world.tmp_path / "art" / "accepted"))
    refused = world.server().content("krita_document_open", arguments)
    assert refused["error"]["code"] == "INVALID_ARGUMENT"
    assert refused["error"]["details"] == {"field": "working_dir"}
    assert refused["operation_id"] is None and world.port.opened == []


def test_a_root_removed_after_the_send_never_refuses_the_call_that_ran(world: World) -> None:
    arguments = _open(world)
    op_args = {key: arguments.get(key) for key in documents_tools.OPEN_FIELDS}
    ran = world.client().call("document.open", op_args, request_id="req-open")
    assert isinstance(ran, Done)
    # A server that sent it and died: its attempt is unsettled in the journal.
    world.journal().dispatched(
        client=None,
        request_id="req-open",
        operation_id="op-died",
        tool="krita_document_open",
        args_sha256=args_sha256("krita_document_open", arguments),
        session_id=world.bridge.session_id,
        args=arguments,
    )
    roots.save(world.data / "config.json", [])
    retried = world.server().content("krita_document_open", arguments)
    assert retried["status"] == "completed"
    assert retried["data"]["baseline_id"] == ran.result["baseline_id"]
    assert len(world.port.opened) == 1


def test_operation_get_finishes_an_open_that_came_back_running(world: World) -> None:
    world.gate.clear()
    world.port.on_open.append(lambda: world.gate.wait(10))
    running = world.server(budget_s=0.6).content("krita_document_open", _open(world))
    assert running["status"] == "running" and _baselines(world) == []
    world.gate.set()
    got = world.server().content("krita_operation_get", {"operation_id": running["operation_id"]})
    receipt = got["data"]["receipt"]
    assert receipt["status"] == "completed" and got["data"]["tool"] == "krita_document_open"
    assert _baselines(world) == []


def test_inspect_counts_the_selection_and_reads_frame_0_only(world: World) -> None:
    server = world.server()
    created = server.content("krita_document_create", _create())
    key = next(iter(world.port.live))
    pixels = bytes([0, 255, 128, 0, 255, 255])
    world.port.live[key]["selection"] = ({"x": 4, "y": 2, "width": 3, "height": 2}, pixels)
    arguments = {"document_id": created["document_id"], "frame": 0}
    seen = server.content("krita_document_inspect", arguments)
    assert seen["data"]["selection"] == {
        "bounds_px": {"x": 4, "y": 2, "width": 3, "height": 2},
        "selected_pixels": 4,
        "coverage_px": (255 + 128 + 255 + 255) / 255,
    }
    transfer = world.data / "transfer"
    assert not transfer.exists() or list(transfer.iterdir()) == []
    later = server.content("krita_document_inspect", {**arguments, "frame": 1})
    assert later["error"]["code"] == "UNSUPPORTED_CAPABILITY" and later["operation_id"] is None


def test_server_info_reports_the_roots_the_plugin_enforces(world: World) -> None:
    art = _art(world)
    info = world.server().content("krita_server_info", {})
    assert info["data"]["allowed_roots"] == [str(art)]


def test_the_sweep_at_server_start_keeps_only_live_baselines(world: World) -> None:
    opened = world.server().content("krita_document_open", _open(world))
    assert _render(world, opened)["status"] == "completed"
    orphan = world.tmp_path / "a" / "baselines" / "baseline-ffffffffffff.npy"
    orphan.write_bytes(b"from an ended Krita session")
    assert baselines.sweep(world.client(), world.tmp_path / "a" / "baselines") == 1
    assert _baselines(world) == [f"{opened['data']['baseline_id']}.npy"]
