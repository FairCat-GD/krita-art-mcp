import json
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from bridge_core import documents
from bridge_core import errors as plugin_errors
from bridge_core import jobs as plugin_jobs
from bridge_core.errors import BridgeError
from fake_krita import layer_id
from jsonschema import Draft202012Validator
from mcp.types import CallToolResult
from worlds import NOW, B, Server, World, running_world

from krita_art_mcp import (
    bridge_client,
    envelope,
    errors,
    journal,
    schemas,
    tools,
    verification,
)
from krita_art_mcp.bridge_client import BridgeClient, Done, Failed
from krita_art_mcp.errors import error_body
from krita_art_mcp.server import build_server
from krita_art_mcp.tools import changes, dispatch, operations, painting, pixels, saving

CREATE = {
    "name": "sketch",
    "size_px": [32, 16],
    "color_model": "RGBA",
    "depth": "U8",
    "profile_id": documents.SRGB_PROFILE,
    "background": "transparent",
}
LAYER = layer_id(1, 0)
# Text a bad receipt holds, which no answer may quote.
TELLTALE = "telltale-of-the-whole-instance"


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    with running_world(tmp_path) as running:
        yield running


def _document(world: World) -> str:
    created = world.server().content("krita_document_create", {**CREATE, "request_id": "req-c"})
    return str(created["document_id"])


def _stroke(document_id: str, request_id: str = "req-s", **changes: Any) -> dict[str, Any]:
    return {
        "guard": {"document_id": document_id, "request_id": request_id},
        "layer_id": LAYER,
        "brush": {
            "preset_id": "basic-round.kpp",
            "size_px": 4,
            "opacity": 1,
            "flow": 1,
            "color": {"space": "srgb", "rgba": [0.8, 0.2, 0.4, 1]},
            "eraser": False,
        },
        "points": [{"x": 4.5, "y": 4.5}, {"x": 10.5, "y": 6.5}],
        **changes,
    }


def _lines(world: World, name: str = "a") -> list[dict[str, Any]]:
    path = world.tmp_path / name / "journal" / f"{NOW.date().isoformat()}.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


def _finished(world: World, request_id: str = "req-s") -> list[str]:
    return [
        line["outcome"]
        for line in _lines(world)
        if line["phase"] == "finished" and line["request_id"] == request_id
    ]


def _bad_receipt(outcome: Any) -> CallToolResult:
    # A receipt its tool's schema refuses, as an overhanging stroke's once was.
    return envelope.completed(
        {"found": TELLTALE},
        "x",
        document_id=outcome.result["document_id"],
        operation_id=outcome.operation_id,
    )


def _raises(*args: Any, **kwargs: Any) -> Any:
    raise KeyError("a receipt that cannot be built")


def _sent(world: World, document_id: str, operation_id: str = "op-" + "a" * 32) -> str:
    # A stroke the journal saw go out and never heard back from.
    arguments = _stroke(document_id)
    op_args = painting.stroke_op(arguments)
    assert isinstance(op_args, dict)
    world.journal().dispatched(
        client=None,
        request_id="req-s",
        operation_id=operation_id,
        tool="krita_paint_stroke",
        args_sha256=dispatch.args_sha256("krita_paint_stroke", arguments),
        session_id=world.bridge.session_id,
        args=arguments,
    )
    done = world.client().call(
        "paint.stroke", op_args, request_id="req-s", operation_id=operation_id
    )
    assert isinstance(done, Done)
    return operation_id


def _past(
    world: World,
    outcome: str,
    result: dict[str, Any] | None,
    tool: str = "krita_paint_stroke",
    operation_id: str = "op-old",
) -> str:
    # A call an earlier Krita session answered, as the journal holds it.
    old = world.journal()
    old.dispatched(
        client=None,
        request_id="req-old",
        operation_id=operation_id,
        tool=tool,
        args_sha256="0" * 64,
        session_id="an-earlier-krita",
        args={},
    )
    old.finished(
        client=None,
        request_id="req-old",
        operation_id=operation_id,
        tool=tool,
        args_sha256="0" * 64,
        session_id="an-earlier-krita",
        outcome=outcome,
        result=result,  # type: ignore[arg-type]
    )
    return operation_id


def _failed_receipt(said: str | None) -> dict[str, Any]:
    details = {} if said is None else {"outcome": said}
    error = error_body("LOCKED_TARGET", details=details)
    result = envelope.failed(error, document_id="doc-1", operation_id="op-old")
    return dispatch.stored(result)


# One list on each side, and one rule for what mutates.


def test_the_two_lists_of_outcomes_are_equal() -> None:
    assert errors.OUTCOMES == plugin_errors.OUTCOMES


def test_operation_get_takes_every_outcome() -> None:
    data = schemas.load("krita_operation_get")["outputSchema"]["properties"]["data"]["anyOf"][0]
    assert data["properties"]["outcome"]["anyOf"][0]["enum"] == list(errors.OUTCOMES)


def test_every_schema_types_the_outcome() -> None:
    for name in schemas.tool_names():
        error = schemas.load(name)["outputSchema"]["properties"]["error"]["anyOf"][0]
        typed = error["properties"]["details"]["properties"]["outcome"]
        assert typed == {"type": "string", "enum": list(errors.OUTCOMES)}


def test_the_bounded_ops_are_the_mutating_tools_ops() -> None:
    mutating = {
        op
        for op, known in operations.RECEIPTS.items()
        if not schemas.load(known.tool)["annotations"]["readOnlyHint"]
    }
    assert plugin_jobs.BOUNDED == mutating | {"document.save_finish"}
    reads = set(operations.RECEIPTS) - mutating
    assert plugin_jobs.READS == reads | {"bridge.unsaved_documents", "document.baselines"}


# After the bridge said done: identity survives, and nothing paints twice.


def test_a_receipt_that_breaks_its_contract_keeps_its_ids_and_says_applied(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    document_id = _document(world)
    monkeypatch.setattr(painting, "paint_receipt", _bad_receipt)
    server = world.server()
    failed = server.content("krita_paint_stroke", _stroke(document_id))
    assert failed["status"] == "failed"
    assert failed["document_id"] == document_id and failed["operation_id"]
    error = failed["error"]
    assert (error["code"], error["retryable"]) == ("INTERNAL_ERROR", False)
    assert error["details"]["outcome"] == "applied"
    assert TELLTALE not in json.dumps(failed)
    assert _finished(world) == [journal.RECEIPT]
    assert server.content("krita_paint_stroke", _stroke(document_id)) == failed
    assert len(world.port.paths) == 1


def test_a_read_whose_receipt_breaks_its_contract_says_nothing_of_applying(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "krita_art_mcp.tools.documents.list_receipt",
        lambda outcome: envelope.completed({"found": TELLTALE}, "x"),
    )
    failed = world.server().content("krita_document_list", {})
    assert failed["error"]["code"] == "INTERNAL_ERROR"
    assert "outcome" not in failed["error"]["details"]
    assert TELLTALE not in json.dumps(failed)


def test_a_receipt_that_raises_keeps_its_ids_and_says_applied(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    document_id = _document(world)
    monkeypatch.setattr(painting, "paint_receipt", _raises)
    server = world.server()
    failed = server.content("krita_paint_stroke", _stroke(document_id))
    assert failed["document_id"] == document_id and failed["operation_id"]
    assert failed["error"]["details"]["outcome"] == "applied"
    assert _finished(world) == [journal.RECEIPT]
    assert server.content("krita_paint_stroke", _stroke(document_id)) == failed
    assert len(world.port.paths) == 1


def test_a_failure_whose_receipt_raises_stays_that_failure(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    document_id = _document(world)
    monkeypatch.setattr(painting, "paint_receipt", _raises)
    arguments = _stroke(document_id, layer_id=layer_id(1, 9))
    failed = world.server().content("krita_paint_stroke", arguments)
    assert failed["error"]["code"] == "LAYER_NOT_FOUND" and failed["operation_id"]
    assert failed["error"]["details"]["outcome"] == "not_applied"


def test_a_raise_after_the_call_went_out_is_uncertain_and_keeps_its_id(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    document_id = _document(world)
    monkeypatch.setattr(changes, "resolve_update", _raises)
    server = world.server()
    failed = server.content("krita_paint_stroke", _stroke(document_id))
    assert failed["operation_id"] and failed["error"]["details"]["outcome"] == "uncertain"
    assert failed["error"]["retryable"] is False
    assert _finished(world) == [journal.UNKNOWN]
    monkeypatch.undo()
    again = server.content("krita_paint_stroke", _stroke(document_id))
    assert again["status"] == "completed" and len(world.port.paths) == 1


def test_a_raise_before_the_call_went_out_is_not_applied(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    document_id = _document(world)
    monkeypatch.setattr(BridgeClient, "call", _raises)
    failed = world.server().content("krita_paint_stroke", _stroke(document_id))
    assert failed["operation_id"] is None
    assert failed["error"]["details"]["outcome"] == "not_applied"
    assert world.port.paths == []


def test_a_finished_line_that_cannot_be_written_never_fails_the_call(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    document_id = _document(world)
    monkeypatch.setattr(journal.Journal, "finished", _raises)
    done = world.server().content("krita_paint_stroke", _stroke(document_id))
    assert done["status"] == "completed"


@pytest.mark.parametrize(
    ("resolve", "broken"),
    [
        (changes.resolve_selection, "_selection_files"),
        (changes.resolve_history, "_history_files"),
    ],
)
def test_applied_work_whose_file_was_not_made_says_applied(
    monkeypatch: pytest.MonkeyPatch, resolve: Any, broken: str
) -> None:
    monkeypatch.setattr(changes, broken, _raises)
    done = Done({"document_id": "doc-1"}, "op-1", "selection.set", "req-1", "krita-1")
    failed = resolve(SimpleNamespace(transfer_dir=Path("/nowhere")), done)
    assert isinstance(failed, Failed)
    assert failed.error["retryable"] is False and failed.error["details"]["outcome"] == "applied"
    assert (failed.operation_id, failed.request_id) == ("op-1", "req-1")
    assert failed.error["details"]["document_id"] == "doc-1"
    assert dispatch.outcome_of(failed) == journal.RECEIPT
    receipt = changes.selection_receipt(failed).structured_content or {}
    assert (receipt["document_id"], receipt["operation_id"]) == ("doc-1", "op-1")


def test_a_png_that_could_not_be_written_says_applied_not_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def full(*args: Any, **kwargs: Any) -> Any:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(verification, "keep", full)
    discarded: list[Any] = []
    monkeypatch.setattr(changes, "discard", lambda places, spec: discarded.append(spec))
    done = Done({"document_id": "doc-1"}, "op-" + "a" * 32, "selection.set", "req-1", "krita-1")
    places: Any = SimpleNamespace()
    failed = changes._kept_png(places, done, {"path": "x"}, "selection's mask")
    assert isinstance(failed, Failed)
    assert (failed.error["code"], failed.error["retryable"]) == ("IO_ERROR", False)
    assert failed.error["details"]["outcome"] == "applied"
    assert discarded == [{"path": "x"}]


def test_a_read_the_server_could_not_finish_changed_nothing() -> None:
    done = Done({"document_id": "doc-1"}, "op-1", "capture.read", "req-1", "krita-1")
    failed = pixels.failed(done, error_body("INTERNAL_ERROR", retryable=True))
    assert failed.error["details"]["outcome"] == "not_applied"
    assert (failed.operation_id, failed.op) == ("op-1", "capture.read")


# What the journal makes of each outcome.


def test_applied_settles_as_a_receipt_however_it_arrived() -> None:
    error = error_body("INTERNAL_ERROR", details={"outcome": "applied"})
    assert dispatch.outcome_of(Failed(error, "op-1")) == journal.RECEIPT


def test_a_contract_problem_names_the_rule_and_never_the_instance() -> None:
    validator = Draft202012Validator(
        {"type": "object", "properties": {"found": {"type": "integer"}}}
    )
    problem = dispatch.contract_problem(validator, {"found": TELLTALE})
    assert problem is not None and "$.found" in problem and TELLTALE not in problem
    assert dispatch.contract_problem(validator, {"found": 1}) is None


# The server's own time on each call, so a client's wall clock can be told from it.


def test_a_finished_line_carries_the_server_s_time_and_the_index_reads_it_back(
    world: World,
) -> None:
    world.port.on_create.append(lambda: time.sleep(0.05))
    created = world.server().content("krita_document_create", {**CREATE, "request_id": "req-c"})
    [line] = [line for line in _lines(world) if line["phase"] == "finished"]
    assert isinstance(line["elapsed_ms"], int) and line["elapsed_ms"] >= 50
    found = world.journal().finished_line(created["operation_id"])
    assert found is not None and found.elapsed_ms == line["elapsed_ms"]


class _Held:
    # The calls' lock, held by the test, saying when a call starts to wait for it.
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.waiting = threading.Event()

    def __enter__(self) -> None:
        self.waiting.set()
        self.lock.acquire()

    def __exit__(self, *raised: object) -> None:
        self.lock.release()


def test_a_call_s_time_counts_its_wait_for_the_lock(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    held = _Held()
    monkeypatch.setattr(tools, "CALLS", held)
    server = world.server()
    caller = threading.Thread(
        target=server.content, args=("krita_document_create", {**CREATE, "request_id": "req-c"})
    )
    held.lock.acquire()
    caller.start()
    assert held.waiting.wait(10)
    time.sleep(0.1)
    held.lock.release()
    caller.join(10)
    [line] = [line for line in _lines(world) if line["phase"] == "finished"]
    assert line["elapsed_ms"] >= 100


@pytest.mark.parametrize("timing", [{}, {"elapsed_ms": "12"}, {"elapsed_ms": True}])
def test_a_line_without_a_whole_number_of_ms_reads_as_none_and_still_settles(
    world: World, timing: dict[str, Any]
) -> None:
    folder = world.tmp_path / "a" / "journal"
    folder.mkdir(parents=True)
    line = {
        "v": journal.VERSION,
        "ts": NOW.isoformat(timespec="milliseconds"),
        "request_id": "req-old",
        "operation_id": "op-old",
        "tool": "krita_paint_stroke",
        "args_sha256": "0" * 64,
        "session_id": "an-earlier-krita",
        "phase": "finished",
        "outcome": journal.RECEIPT,
        "result": None,
        **timing,
    }
    (folder / f"{NOW.date().isoformat()}.jsonl").write_text(json.dumps(line) + "\n")
    found = world.journal().finished_line("op-old")
    assert found is not None and found.elapsed_ms is None and found.outcome == journal.RECEIPT


# A resend needs proof.


def test_an_uncertain_call_is_sent_again_only_to_its_own_session_and_runs_once(
    world: World,
) -> None:
    document_id = _document(world)
    # The stroke lands, and neither its check nor its rollback can be confirmed.
    world.port.fail["paint_path_after"] = RuntimeError("Krita raised")
    world.port.undo_works = False
    server = world.server()
    failed = server.content("krita_paint_stroke", _stroke(document_id))
    assert failed["error"]["code"] == "ROLLBACK_FAILED"
    assert failed["error"]["details"]["outcome"] == "uncertain"
    assert _finished(world) == [journal.UNKNOWN]
    assert server.content("krita_paint_stroke", _stroke(document_id)) == failed
    assert len(world.port.paths) == 1


def test_a_restart_sends_no_uncertain_call_again(world: World) -> None:
    document_id = _document(world)
    arguments = _stroke(document_id)
    world.journal().dispatched(
        client=None,
        request_id="req-s",
        operation_id="op-lost",
        tool="krita_paint_stroke",
        args_sha256=dispatch.args_sha256("krita_paint_stroke", arguments),
        session_id="an-earlier-krita",
        args=arguments,
    )
    failed = world.server().content("krita_paint_stroke", arguments)
    assert failed["operation_id"] == "op-lost"
    assert failed["error"]["details"]["outcome"] == "uncertain" and world.port.paths == []


def test_a_settled_receipt_answers_after_a_restart_with_nothing_sent(world: World) -> None:
    document_id = _document(world)
    arguments = _stroke(document_id)
    digest = dispatch.args_sha256("krita_paint_stroke", arguments)
    old = world.journal()
    old.dispatched(
        client=None,
        request_id="req-s",
        operation_id="op-old",
        tool="krita_paint_stroke",
        args_sha256=digest,
        session_id="an-earlier-krita",
        args=arguments,
    )
    stored = dispatch.stored(
        envelope.failed(
            error_body("INTERNAL_ERROR", details={"outcome": "applied"}),
            document_id=document_id,
            operation_id="op-old",
        )
    )
    old.finished(
        client=None,
        request_id="req-s",
        operation_id="op-old",
        tool="krita_paint_stroke",
        args_sha256=digest,
        session_id="an-earlier-krita",
        outcome=journal.RECEIPT,
        result=stored,
    )
    answered = world.server().content("krita_paint_stroke", arguments)
    assert answered["error"]["details"]["outcome"] == "applied" and world.port.paths == []


def test_a_retryable_failure_changed_nothing_so_its_retry_runs(world: World) -> None:
    document_id = _document(world)
    world.port.refuse = BridgeError("KRITA_MODAL_DIALOG", "A dialog is open.", True)
    server = world.server()
    refused = server.content("krita_paint_stroke", _stroke(document_id))
    assert refused["error"]["retryable"] is True
    assert refused["error"]["details"]["outcome"] == "not_applied"
    assert _finished(world) == [journal.NO_EFFECT]
    world.port.refuse = None
    done = server.content("krita_paint_stroke", _stroke(document_id))
    assert done["status"] == "completed" and len(world.port.paths) == 1


def test_an_unregistered_call_is_not_sent_to_another_session(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = world.client(grace_s=0.3)
    send = client._request

    def lossy(bridge: Any, method: str, path: str, body: Any, timeout: float) -> Any:
        if path == "/v1/call":
            raise ConnectionResetError("the connection was reset before the bridge read it")
        return send(bridge, method, path, body, timeout)

    document_id = _document(world)
    monkeypatch.setattr(client, "_request", lossy)
    server = Server(build_server(client, world.journal(), world.places()))
    arguments = _stroke(document_id)
    lost = server.content("krita_paint_stroke", arguments)
    assert lost["operation_id"] and lost["error"]["details"]["outcome"] == "unregistered"
    monkeypatch.setattr(client, "_request", send)
    prior = world.journal().lookup("req-s")
    assert prior is not None and prior.unknown_elsewhere("a-later-krita") is not None


# Refusals say they changed nothing.


def test_a_schema_refusal_is_not_applied(world: World) -> None:
    refused = world.server().content("krita_paint_stroke", {"guard": {}})
    assert refused["error"]["code"] == "INVALID_ARGUMENT"
    assert refused["operation_id"] is None
    assert refused["error"]["details"]["outcome"] == "not_applied"


def test_a_tools_own_refusal_is_not_applied(world: World) -> None:
    document_id = _document(world)
    arguments = _stroke(document_id)
    arguments["points"] = [{**point, "pressure": 0.5} for point in arguments["points"]]
    refused = world.server().content("krita_paint_stroke", arguments)
    assert refused["error"]["code"] == "UNSUPPORTED_CAPABILITY"
    assert refused["error"]["details"]["outcome"] == "not_applied"


def test_a_conflict_is_not_applied_from_the_journal_and_the_bridge(world: World) -> None:
    document_id = _document(world)
    server = world.server()
    server.content("krita_paint_stroke", _stroke(document_id))
    other = _stroke(document_id, points=[{"x": 2.5, "y": 2.5}, {"x": 9.5, "y": 9.5}])
    for answered in (
        server.content("krita_paint_stroke", other),
        world.server(B, "b").content("krita_paint_stroke", other),
    ):
        assert answered["error"]["code"] == "REQUEST_ID_CONFLICT"
        assert answered["error"]["details"]["outcome"] == "not_applied"
    assert len(world.port.paths) == 1


def test_a_cancelled_job_is_not_applied(world: World) -> None:
    document_id = _document(world)
    world.gate.clear()
    client = world.client(budget_s=0.4)
    assert not isinstance(client.call("slow"), Done | Failed)
    op_args = painting.stroke_op(_stroke(document_id))
    assert isinstance(op_args, dict)
    queued = client.call("paint.stroke", op_args, request_id="req-s")
    assert not isinstance(queued, Done | Failed)
    server = Server(build_server(client, world.journal(), world.places()))
    arguments = {"operation_id": queued.operation_id, "request_id": "req-cancel"}
    cancelled = server.content("krita_operation_cancel", arguments)
    got = server.content("krita_operation_get", {"operation_id": queued.operation_id})
    world.gate.set()
    assert cancelled["data"]["state"] == "cancelled"
    assert (got["data"]["state"], got["data"]["outcome"]) == ("cancelled", "not_applied")
    assert world.port.paths == []


def test_a_read_refused_by_the_server_states_nothing(world: World) -> None:
    refused = world.server().content("krita_document_inspect", {"document_id": "doc-1", "frame": 1})
    assert refused["error"]["code"] == "UNSUPPORTED_CAPABILITY"
    assert "outcome" not in refused["error"]["details"]


def test_a_failure_with_an_id_and_no_statement_is_uncertain(
    monkeypatch: pytest.MonkeyPatch, world: World
) -> None:
    document_id = _document(world)

    def silent(outcome: Any) -> CallToolResult:
        return envelope.failed(error_body("IO_ERROR"), operation_id="op-1")

    monkeypatch.setattr(painting, "paint_receipt", silent)
    failed = world.server().content("krita_paint_stroke", _stroke(document_id))
    assert failed["error"]["details"]["outcome"] == "uncertain"
    assert world.server().content("krita_paint_stroke", _stroke(document_id))["operation_id"]


# The bridge client's own failures.


def test_a_lost_call_keeps_its_operation_id() -> None:
    assert bridge_client._uncertain("op-1", "gone").operation_id == "op-1"
    assert bridge_client._unregistered("op-1").operation_id == "op-1"


def test_a_reply_nobody_can_read_is_uncertain() -> None:
    assert bridge_client._bridge_error(None)["details"]["outcome"] == "uncertain"
    assert bridge_client._unexpected(500).error["details"]["outcome"] == "uncertain"


# The save's second half.


def _saved() -> Done:
    result = {
        "document_id": "doc-1",
        "save_id": "op-1",
        "written": "/nowhere/.hero.saving.kra",
        "path": "/nowhere/hero.kra",
        "sha256": "0" * 64,
        "size_px": [8, 4],
    }
    return Done(result, "op-1", "document.save", "req-1", "krita-1")


def _call_with(finished: Any, places: Any = None) -> Any:
    bridge = SimpleNamespace(call=lambda *args, **kwargs: finished, budget_s=5.0)
    return SimpleNamespace(bridge=bridge, places=places)


def test_a_finish_that_says_nothing_leaves_the_save_uncertain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(saving, "_merged", lambda places, result: (None, "no"))
    refused = Failed(error_body("INTERNAL_ERROR", "Retry.", retryable=True))
    failed = saving.finish_save(_call_with(refused), _saved(), 5.0)
    assert isinstance(failed, Failed)
    assert failed.error["details"]["outcome"] == "uncertain"
    assert failed.error["retryable"] is False and failed.operation_id == "op-1"


def test_a_finish_that_states_its_outcome_keeps_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(saving, "_merged", lambda places, result: (None, "no"))
    error = error_body("SAVE_VERIFY_FAILED", details={"outcome": "not_applied"})
    refused = Failed(error, "op-f", submitted=True)
    failed = saving.finish_save(_call_with(refused), _saved(), 5.0)
    assert isinstance(failed, Failed)
    assert failed.error["details"]["outcome"] == "not_applied"
    assert failed.operation_id == "op-1"


def test_a_merged_image_that_raises_never_stops_the_finish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(saving, "_merged_sha256", _raises)
    places: Any = SimpleNamespace()
    merged, problem = saving._merged(places, _saved().result)
    assert merged is None and problem is not None and "cannot be read" in problem


def test_a_save_never_finished_keeps_its_ids() -> None:
    receipt = saving.save_receipt(Done({"document_id": "doc-1"}, "op-1")).structured_content or {}
    assert (receipt["document_id"], receipt["operation_id"]) == ("doc-1", "op-1")
    assert receipt["error"]["details"]["outcome"] == "uncertain"


# krita_operation_get.


def test_operation_get_says_a_finished_stroke_applied(world: World) -> None:
    document_id = _document(world)
    done = world.server().content("krita_paint_stroke", _stroke(document_id))
    got = world.server().content("krita_operation_get", {"operation_id": done["operation_id"]})
    data = got["data"]
    assert data["receipt"] == done
    assert (data["outcome"], data["receipt_valid"]) == ("applied", True)
    assert data["receipt_problem"] is None


def test_operation_get_says_a_refused_stroke_did_not(world: World) -> None:
    document_id = _document(world)
    server = world.server()
    refused = server.content("krita_paint_stroke", _stroke(document_id, layer_id=layer_id(1, 9)))
    got = server.content("krita_operation_get", {"operation_id": refused["operation_id"]})
    assert (got["data"]["state"], got["data"]["outcome"]) == ("failed", "not_applied")
    assert got["data"]["receipt_valid"] is True


def test_operation_get_is_null_while_a_call_runs(world: World) -> None:
    world.gate.clear()
    world.port.on_create.append(lambda: world.gate.wait(10))
    running = world.server(budget_s=0.6).content(
        "krita_document_create", {**CREATE, "request_id": "req-c"}
    )
    got = world.server(budget_s=0.6).content(
        "krita_operation_get", {"operation_id": running["operation_id"]}
    )
    world.gate.set()
    data = got["data"]
    assert (data["receipt"], data["outcome"]) == (None, None)
    assert (data["receipt_valid"], data["receipt_problem"]) == (None, None)


def test_operation_get_returns_a_bad_receipt_as_data_and_settles_the_journal(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    document_id = _document(world)
    operation_id = _sent(world, document_id)
    known = operations.Known("krita_paint_stroke", _bad_receipt, changes.resolve_update)
    monkeypatch.setitem(operations.RECEIPTS, "paint.stroke", known)
    server = world.server()
    got = server.content("krita_operation_get", {"operation_id": operation_id})
    assert got["status"] == "completed" and got["document_id"] == document_id
    data = got["data"]
    assert (data["outcome"], data["receipt_valid"]) == ("applied", False)
    assert data["receipt"]["data"] == {"found": TELLTALE}
    assert TELLTALE not in data["receipt_problem"]
    assert _finished(world) == [journal.RECEIPT]
    retried = server.content("krita_paint_stroke", _stroke(document_id))
    assert retried["operation_id"] == operation_id
    assert retried["error"]["details"]["outcome"] == "applied"
    assert len(world.port.paths) == 1


def test_operation_get_survives_a_receipt_that_raises(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    document_id = _document(world)
    operation_id = _sent(world, document_id)
    known = operations.Known("krita_paint_stroke", _raises, changes.resolve_update)
    monkeypatch.setitem(operations.RECEIPTS, "paint.stroke", known)
    got = world.server().content("krita_operation_get", {"operation_id": operation_id})
    data = got["data"]
    assert (data["outcome"], data["receipt_valid"]) == ("applied", False)
    assert data["receipt"]["data"]["stroke_id"] == operation_id
    assert got["document_id"] == document_id
    assert _finished(world) == [journal.RECEIPT]


def test_operation_get_keeps_a_failure_its_receipt_could_not_build(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    document_id = _document(world)
    server = world.server()
    refused = server.content("krita_paint_stroke", _stroke(document_id, layer_id=layer_id(1, 9)))
    known = operations.Known("krita_paint_stroke", _raises, changes.resolve_update)
    monkeypatch.setitem(operations.RECEIPTS, "paint.stroke", known)
    got = server.content("krita_operation_get", {"operation_id": refused["operation_id"]})
    assert got["data"]["receipt"]["error"]["code"] == "LAYER_NOT_FOUND"
    assert got["data"]["outcome"] == "not_applied"


@pytest.mark.parametrize(
    ("line", "result", "said"),
    [
        (journal.RECEIPT, _failed_receipt("not_applied"), "not_applied"),
        (journal.RECEIPT, _failed_receipt("applied"), "applied"),
        (journal.RECEIPT, _failed_receipt(None), "uncertain"),
        (journal.NO_EFFECT, _failed_receipt(None), "not_applied"),
        (journal.NOT_SENT, _failed_receipt(None), "not_applied"),
        (journal.CONFLICT, _failed_receipt(None), "not_applied"),
        (journal.UNKNOWN, _failed_receipt("unregistered"), "uncertain"),
    ],
    ids=["refused", "applied", "old line", "no effect", "not sent", "conflict", "unknown"],
)
def test_after_a_restart_a_finished_line_answers_with_its_own_outcome(
    world: World, line: str, result: dict[str, Any], said: str
) -> None:
    operation_id = _past(world, line, result)
    got = world.server().content("krita_operation_get", {"operation_id": operation_id})
    assert got["status"] == "completed"
    data = got["data"]
    assert (data["tool"], data["state"], data["outcome"]) == ("krita_paint_stroke", "failed", said)
    assert data["receipt"] == result["structured"]


def test_after_a_restart_a_completed_line_is_applied_and_its_receipt_is_judged(
    world: World,
) -> None:
    content = envelope.completed({"found": TELLTALE}, "x", operation_id="op-old")
    operation_id = _past(world, journal.RECEIPT, dispatch.stored(content))
    data = world.server().content("krita_operation_get", {"operation_id": operation_id})["data"]
    assert (data["state"], data["outcome"], data["receipt_valid"]) == (
        "completed",
        "applied",
        False,
    )


def test_a_retry_s_line_answers_for_the_operation_the_bridge_named(world: World) -> None:
    old = world.journal()
    old.dispatched(
        client=None,
        request_id="req-old",
        operation_id="op-2",
        tool="krita_paint_stroke",
        args_sha256="0" * 64,
        session_id="an-earlier-krita",
        args={},
    )
    old.finished(
        client=None,
        request_id="req-old",
        operation_id="op-2",
        bridge_operation_id="op-1",
        tool="krita_paint_stroke",
        args_sha256="0" * 64,
        session_id="an-earlier-krita",
        outcome=journal.RECEIPT,
        result=_failed_receipt("not_applied"),
    )
    assert world.journal().finished_line("op-1") == world.journal().finished_line("op-2")


def test_an_unknown_line_never_overwrites_a_settled_one(world: World) -> None:
    operation_id = _past(world, journal.RECEIPT, _failed_receipt("not_applied"))
    world.journal().finished(
        client=None,
        request_id="req-old",
        operation_id=operation_id,
        tool="krita_paint_stroke",
        args_sha256="0" * 64,
        session_id="an-earlier-krita",
        outcome=journal.UNKNOWN,
        result=_failed_receipt("uncertain"),
    )
    found = world.journal().finished_line(operation_id)
    assert found is not None and found.outcome == journal.RECEIPT


def test_a_finished_line_with_no_receipt_answers_uncertain(world: World) -> None:
    operation_id = _past(world, journal.UNKNOWN, None)
    got = world.server().content("krita_operation_get", {"operation_id": operation_id})
    assert got["error"]["details"]["outcome"] == "uncertain"


def test_a_line_from_a_tool_this_server_does_not_have_answers_uncertain(world: World) -> None:
    operation_id = _past(world, journal.RECEIPT, _failed_receipt("applied"), tool="krita_gone")
    got = world.server().content("krita_operation_get", {"operation_id": operation_id})
    assert got["error"]["details"]["outcome"] == "uncertain"


def test_the_journal_answers_while_krita_is_not_running(world: World) -> None:
    operation_id = _past(world, journal.RECEIPT, _failed_receipt("not_applied"))
    (world.data / "bridge.json").unlink()
    got = world.server().content("krita_operation_get", {"operation_id": operation_id})
    assert got["data"]["outcome"] == "not_applied"
