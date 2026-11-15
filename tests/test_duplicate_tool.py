import hashlib
import itertools
import os
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from bridge_core.errors import BridgeError
from worlds import B, World, running_world

from krita_art_mcp import baselines, bridge_client, roots
from krita_art_mcp.bridge_client import Done, Failed
from krita_art_mcp.errors import error_body
from krita_art_mcp.tools import branching, saving

SESSION = "krita-1"


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    with running_world(tmp_path) as running:
        yield running


def _art(world: World) -> Path:
    art = world.tmp_path / "art"
    (art / "accepted").mkdir(parents=True, exist_ok=True)
    roots.save(world.data / "config.json", [str(art)])
    return art


def _opened(world: World) -> str:
    art = _art(world)
    source = art / "accepted" / "hero.kra"
    source.write_bytes(b"accepted art")
    arguments = {
        "source_path": str(source),
        "source_sha256": hashlib.sha256(b"accepted art").hexdigest(),
        "mode": "working_copy",
        "working_dir": str(art / "work"),
        "request_id": "req-open",
    }
    opened = world.server().content("krita_document_open", arguments)
    assert opened["status"] == "completed"
    document_id: str = opened["document_id"]
    return document_id


def _target(world: World, name: str = "hero-b.kra") -> Path:
    return world.tmp_path / "art" / "branches" / name


def _duplicate(document_id: str, path: Path, request_id: str = "req-duplicate") -> dict[str, Any]:
    return {"guard": {"document_id": document_id, "request_id": request_id}, "path": str(path)}


def _branches(world: World) -> list[str]:
    folder = world.tmp_path / "art" / "branches"
    return sorted(os.listdir(folder)) if folder.exists() else []


def _listed(world: World) -> dict[str, dict[str, Any]]:
    listed = world.server().content("krita_document_list", {})["data"]["documents"]
    return {entry["document_id"]: entry for entry in listed}


def _inspect(world: World, document_id: str) -> dict[str, Any]:
    found = world.server().content(
        "krita_document_inspect", {"document_id": document_id, "frame": 0}
    )
    return dict(found["data"])


def _mark_dirty(world: World, document_id: str) -> None:
    arguments = {
        "guard": {"document_id": document_id, "request_id": f"req-layer-{document_id}"},
        "parent_id": _inspect(world, document_id)["root_layer_id"],
        "above_id": None,
        "type": "paint",
        "name": "mine",
    }
    assert world.server().content("krita_layer_create", arguments)["status"] == "completed"


def _render(*sources: dict[str, Any]) -> dict[str, Any]:
    return {
        "recipes": [{"id": "native", "target_size_px": [8, 4]}],
        "filter": "nearest",
        "sources": list(sources),
        "overlays": [],
        "backgrounds": ["transparent"],
    }


def _source(document_id: str, baseline_id: str) -> dict[str, Any]:
    return {
        "document_id": document_id,
        "frame": 0,
        "target": "composite",
        "baseline_id": baseline_id,
    }


def _held(world: World) -> None:
    # The duplicate's write waits in Krita until the gate opens, past a short wait.
    world.gate.clear()
    world.port.on_export.append(lambda saved: world.gate.wait(10))


def _settled(server: Any, operation_id: str) -> dict[str, Any]:
    for _ in range(40):
        got = server.content("krita_operation_get", {"operation_id": operation_id})
        if got["data"]["state"] not in ("queued", "running"):
            return dict(got["data"])
    raise AssertionError(f"{operation_id} never settled")


def test_a_duplicate_opens_a_branch_and_leaves_its_source_dirty(world: World) -> None:
    document_id = _opened(world)
    _mark_dirty(world, document_id)
    source = _inspect(world, document_id)
    target = _target(world)
    got = world.server().content("krita_document_duplicate", _duplicate(document_id, target))
    assert got["status"] == "completed" and got["document_id"] == document_id
    data = got["data"]
    new_id = data["new_document_id"]
    assert new_id != document_id and _branches(world) == ["hero-b.kra"]
    assert (
        data["path"] == str(target)
        and data["sha256"] == hashlib.sha256(target.read_bytes()).hexdigest()
    )
    assert data["reopened_verified"] is True and data["baseline_untouched"] is True
    assert data["recompose"] == {
        "changed_px": 0,
        "visible_changed_px": 0,
        "changed_bounds_px": None,
    }
    assert (data["source_dirty"], data["source_krita_modified"]) == (True, True)
    assert data["mode"] == "working_copy" and data["source_path"] == source["source_path"]
    listed = _listed(world)
    assert listed[document_id]["dirty"] is True and listed[new_id]["dirty"] is False
    branch = _inspect(world, new_id)
    assert branch["path"] == str(target) and branch["baseline_id"] == data["baseline_id"]
    assert branch["baseline_id"] != source["baseline_id"]
    # Every layer id and its protection come through.
    protected = {layer["id"]: layer["protected"] for layer in source["layers"]}
    assert {layer["id"]: layer["protected"] for layer in branch["layers"]} == protected
    assert branch["protection"] == source["protection"] == data["protection"]
    assert branch["history"]["undo_available"] == 0


def test_a_retry_returns_the_receipt_and_makes_no_second_branch(world: World) -> None:
    document_id = _opened(world)
    target = _target(world)
    first = world.server().content("krita_document_duplicate", _duplicate(document_id, target))
    again = world.server().content("krita_document_duplicate", _duplicate(document_id, target))
    from_b = world.server(B, "b").content(
        "krita_document_duplicate", _duplicate(document_id, target)
    )
    assert again == first == from_b
    assert world.port.calls.count("export") == 1 and len(_listed(world)) == 2


def test_each_document_reads_its_own_baseline_and_a_close_keeps_the_others(world: World) -> None:
    document_id = _opened(world)
    got = world.server().content(
        "krita_document_duplicate", _duplicate(document_id, _target(world))
    )
    branch_id = got["data"]["new_document_id"]
    source_baseline = _inspect(world, document_id)["baseline_id"]
    branch_baseline = got["data"]["baseline_id"]
    render = _render(_source(document_id, source_baseline), _source(branch_id, branch_baseline))
    assert world.server().content("krita_preview_render", render)["status"] == "completed"
    folder = world.places().baselines_dir
    held = {baseline: folder / f"{baseline}.npy" for baseline in (source_baseline, branch_baseline)}
    assert baselines.path_of(folder, branch_baseline) == held[branch_baseline]
    assert all(path.exists() for path in held.values())
    closed = world.server().content(
        "krita_document_close",
        {"guard": {"document_id": branch_id, "request_id": "req-close"}, "dirty_policy": "discard"},
    )
    assert closed["status"] == "completed"
    assert held[source_baseline].exists() and not held[branch_baseline].exists()
    # The source's baseline serves on, read no more.
    opened = len(world.port.opened)
    again = world.server().content(
        "krita_preview_render", _render(_source(document_id, source_baseline))
    )
    assert again["status"] == "completed" and len(world.port.opened) == opened


@pytest.mark.parametrize(
    ("name", "code"),
    [("hero-b.ora", "UNSUPPORTED_CAPABILITY"), ("hero-b.png", "UNSUPPORTED_CAPABILITY")],
)
def test_a_duplicate_is_a_kra_alone(world: World, name: str, code: str) -> None:
    document_id = _opened(world)
    got = world.server().content(
        "krita_document_duplicate", _duplicate(document_id, _target(world, name))
    )
    assert got["error"]["code"] == code and got["error"]["details"]["formats"] == [".kra"]
    assert got["operation_id"] is None and _branches(world) == []


def test_a_duplicate_never_overwrites_and_stays_inside_the_roots(world: World) -> None:
    document_id = _opened(world)
    taken = _target(world, "taken.kra")
    taken.parent.mkdir(parents=True)
    taken.write_bytes(b"there first")
    exists = world.server().content("krita_document_duplicate", _duplicate(document_id, taken))
    assert exists["error"]["code"] == "FILE_EXISTS" and taken.read_bytes() == b"there first"
    outside = world.tmp_path / "elsewhere" / "hero-b.kra"
    refused = world.server().content(
        "krita_document_duplicate", _duplicate(document_id, outside, "req-out")
    )
    assert refused["error"]["code"] == "PATH_NOT_ALLOWED" and not outside.parent.exists()


def test_a_created_documents_branch_has_no_source(world: World) -> None:
    _art(world)
    created = world.server().content(
        "krita_document_create",
        {
            "name": "sketch",
            "size_px": [8, 4],
            "color_model": "RGBA",
            "depth": "U8",
            "profile_id": "sRGB-elle-V2-srgbtrc.icc",
            "background": "transparent",
            "request_id": "req-new",
        },
    )
    got = world.server().content(
        "krita_document_duplicate", _duplicate(created["document_id"], _target(world))
    )
    data = got["data"]
    assert data["mode"] == "new" and (data["source_path"], data["source_sha256"]) == (None, None)
    assert data["baseline_untouched"] is None
    render = _render(_source(data["new_document_id"], data["baseline_id"]))
    assert world.server().content("krita_preview_render", render)["status"] == "completed"


def test_a_duplicate_that_runs_past_the_wait_is_placed_and_opened_by_operation_get(
    world: World,
) -> None:
    document_id = _opened(world)
    _held(world)
    server = world.server(budget_s=0.5)
    running = server.content("krita_document_duplicate", _duplicate(document_id, _target(world)))
    assert running["status"] == "running" and _branches(world) == []
    world.gate.set()
    receipt = _settled(server, running["operation_id"])["receipt"]
    assert receipt["status"] == "completed" and receipt["operation_id"] == running["operation_id"]
    assert _branches(world) == ["hero-b.kra"] and receipt["data"]["new_document_id"] in _listed(
        world
    )


def test_a_poll_from_another_process_opens_no_branch_and_says_how_to(world: World) -> None:
    document_id = _opened(world)
    _held(world)
    a = world.server(budget_s=0.5)
    running = a.content("krita_document_duplicate", _duplicate(document_id, _target(world)))
    operation_id = running["operation_id"]
    b = world.server(B, "b", budget_s=0.5)
    world.gate.set()
    polled = _settled(b, operation_id)
    assert (polled["state"], polled["outcome"]) == ("failed", "uncertain")
    error = polled["receipt"]["error"]
    assert error["retryable"] is False and "the same request_id finishes it" in error["message"]
    assert saving.finish_operation_id(operation_id) not in world.bridge.jobs._operations
    assert branching.open_operation_id(operation_id) not in world.bridge.jobs._operations
    assert len(_listed(world)) == 1
    done = _settled(a, operation_id)
    assert done["receipt"]["status"] == "completed" and len(_listed(world)) == 2
    # Once A has opened it, B reads what the bridge holds of each step.
    assert _settled(b, operation_id)["receipt"] == done["receipt"]


def test_an_open_refused_at_job_start_is_uncertain_and_a_retry_opens_it(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    document_id = _opened(world)
    # The third guarded job of the call, the open, meets a dialog.
    count = itertools.count()
    dialog = BridgeError("KRITA_MODAL_DIALOG", "A dialog is open.", True)
    monkeypatch.setattr(world.port, "refusal", lambda: dialog if next(count) == 2 else None)
    target = _target(world)
    failed = world.server().content("krita_document_duplicate", _duplicate(document_id, target))
    error = failed["error"]
    assert error["details"]["outcome"] == "uncertain" and error["retryable"] is False
    assert (
        "Retrying krita_document_duplicate with the same request_id opens it." in error["message"]
    )
    assert error["details"]["path"] == str(target) and _branches(world) == ["hero-b.kra"]
    assert len(_listed(world)) == 1
    monkeypatch.setattr(world.port, "refusal", lambda: None)
    got = world.server().content("krita_document_duplicate", _duplicate(document_id, target))
    assert got["status"] == "completed" and len(_listed(world)) == 2
    assert world.port.calls.count("export") == 1


# The chain's outcomes, step by step, on a bridge that answers each op as told.


def _written() -> Done:
    result = {
        "document_id": "doc-1",
        "save_id": "op-1",
        "written": "/nowhere/.hero-b.saving.kra",
        "path": "/nowhere/hero-b.kra",
        "sha256": "0" * 64,
        "size_px": [8, 4],
    }
    return Done(result, "op-1", "document.duplicate", "req-1", SESSION)


def _placed() -> Done:
    result = {"document_id": "doc-1", "path": "/nowhere/hero-b.kra", "sha256": "0" * 64}
    return Done(result, "op-f", "document.save_finish", "req-1:finish", SESSION)


def _refused(code: str, retryable: bool, details: dict[str, Any], session: str = SESSION) -> Failed:
    error = error_body(code, "Refused.", retryable=retryable, details=details)
    return Failed(error, "op-o", submitted=True, op="document.duplicate_open", session_id=session)


def _bridge(steps: dict[str, Any], made: bool = True) -> Any:
    def call(op: str, *args: Any, **kwargs: Any) -> Any:
        return steps[op]

    def operation(operation_id: str, **kwargs: Any) -> Any:
        return steps[operation_id]

    bridge = SimpleNamespace(call=call, operation=operation, made=lambda one: made, budget_s=5.0)
    return SimpleNamespace(bridge=bridge, places=None)


@pytest.fixture
def merged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(saving, "_merged", lambda places, result: ("0" * 64, None))


NOT_APPLIED = {"outcome": "not_applied", "rollback_verified": True, "document_id": "doc-1"}
REFUSED = {"outcome": "not_applied", "document_id": "doc-1"}
OPEN_IT = "krita_document_open opens it, with every layer protected."
RETRY = "Retrying krita_document_duplicate with the same request_id opens it"


@pytest.mark.parametrize(
    ("code", "retryable", "details", "session", "said"),
    [
        ("IO_ERROR", False, NOT_APPLIED, SESSION, OPEN_IT),
        ("KRITA_MODAL_DIALOG", True, REFUSED, SESSION, f"{RETRY}."),
        (
            "DOCUMENT_IN_USE",
            True,
            {**REFUSED, "holder_pid": 7},
            SESSION,
            f"{RETRY} from the server process 7",
        ),
        ("KRITA_MODAL_DIALOG", True, REFUSED, "krita-2", OPEN_IT),
        ("CANCELLED", True, REFUSED, SESSION, OPEN_IT),
    ],
    ids=["its-own-close-verified", "refused-at-job-start", "lease", "another-session", "cancelled"],
)
@pytest.mark.usefixtures("merged")
def test_an_open_that_failed_is_never_not_applied(
    code: str, retryable: bool, details: dict[str, Any], session: str, said: str
) -> None:
    # The file is in place whatever the open did.
    opened = _refused(code, retryable, details, session)
    steps = {"document.save_finish": _placed(), "document.duplicate_open": opened}
    failed = branching.finish_duplicate(_bridge(steps), _written(), 5.0)
    assert isinstance(failed, Failed)
    assert (failed.operation_id, failed.request_id, failed.session_id) == ("op-1", "req-1", SESSION)
    error = failed.error
    assert error["details"]["outcome"] == "uncertain" and error["retryable"] is False
    assert (
        error["details"]["path"] == "/nowhere/hero-b.kra" and error["details"]["sha256"] == "0" * 64
    )
    assert said in error["message"]
    # Nothing of the call was rolled back, whatever the open's own cleanup did.
    assert error["details"]["rollback_verified"] is False


@pytest.mark.usefixtures("merged")
def test_an_open_lost_mid_call_is_not_told_it_may_never_have_been_sent() -> None:
    # _uncertain leaves submitted false, and it was sent: only an unregistered call was not.
    opened = bridge_client._uncertain("op-o", "the connection closed")
    steps = {"document.save_finish": _placed(), "document.duplicate_open": opened}
    failed = branching.finish_duplicate(_bridge(steps), _written(), 5.0)
    assert isinstance(failed, Failed)
    assert OPEN_IT in failed.error["message"] and RETRY not in failed.error["message"]


@pytest.mark.usefixtures("merged")
def test_a_failed_step_names_the_calls_own_id_and_keeps_its_own() -> None:
    # krita_operation_get answers for no step's id, so an agent is given the duplicate's.
    opened = bridge_client._uncertain("op-o", "the connection closed")
    steps = {"document.save_finish": _placed(), "document.duplicate_open": opened}
    failed = branching.finish_duplicate(_bridge(steps), _written(), 5.0)
    assert isinstance(failed, Failed)
    details = failed.error["details"]
    assert (details["operation_id"], details["step_operation_id"]) == ("op-1", "op-o")


@pytest.mark.parametrize(
    "opened",
    [
        Failed(error_body("KRITA_NOT_RUNNING", "Gone.", retryable=True, details={})),
        bridge_client._unregistered("op-o"),
    ],
    ids=["unsent", "unregistered"],
)
@pytest.mark.usefixtures("merged")
def test_an_open_that_never_reached_the_bridge_says_a_retry_opens_it(opened: Failed) -> None:
    steps = {"document.save_finish": _placed(), "document.duplicate_open": opened}
    failed = branching.finish_duplicate(_bridge(steps), _written(), 5.0)
    assert isinstance(failed, Failed) and failed.error["details"]["outcome"] == "uncertain"
    message = failed.error["message"]
    assert f"{RETRY} in this Krita session" in message and "After a restart" in message


@pytest.mark.usefixtures("merged")
def test_a_finish_refused_retryably_names_the_duplicate() -> None:
    error = error_body("KRITA_MODAL_DIALOG", "A dialog.", retryable=True, details=REFUSED)
    refused = Failed(error, "op-f", submitted=True, op="document.save_finish", session_id=SESSION)
    failed = branching.finish_duplicate(_bridge({"document.save_finish": refused}), _written(), 5.0)
    assert isinstance(failed, Failed) and failed.error["details"]["outcome"] == "uncertain"
    hint = "Retrying krita_document_duplicate with the same request_id finishes the duplicate."
    assert hint in failed.error["message"]


def test_another_processs_poll_reads_each_step_and_keeps_an_open_failure_uncertain() -> None:
    finish_id = saving.finish_operation_id("op-1")
    open_id = branching.open_operation_id("op-1")
    opened = _refused("IO_ERROR", False, NOT_APPLIED)
    read = branching.poll_duplicate(
        _bridge({finish_id: _placed(), open_id: opened}, made=False), _written(), 5.0
    )
    assert isinstance(read, Failed) and read.error["details"]["outcome"] == "uncertain"
    unknown = Failed(error_body("INVALID_ARGUMENT", "No such operation."))
    missing = branching.poll_duplicate(
        _bridge({finish_id: _placed(), open_id: unknown}, made=False), _written(), 5.0
    )
    assert isinstance(missing, Failed) and missing.error["details"]["outcome"] == "uncertain"
    assert "the same request_id finishes it" in missing.error["message"]
    never = branching.poll_duplicate(_bridge({finish_id: unknown}, made=False), _written(), 5.0)
    assert isinstance(never, Failed) and "not in place, or not open" in never.error["message"]


def test_a_duplicate_not_opened_is_never_a_receipt() -> None:
    receipt = branching.duplicate_receipt(_placed())
    content = receipt.structured_content or {}
    assert content["status"] == "failed" and content["error"]["details"]["outcome"] == "uncertain"
