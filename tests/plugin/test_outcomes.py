import ast
import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any

import pytest
from bridge_core import documents, files, harness, jobs, painting, protection, resources
from bridge_core.errors import OUTCOMES, BridgeError, cleaned
from bridge_core.jobs import BOUNDED, HARNESS, READS, Call, Handler, Jobs
from bridge_core.registry import Registry
from fake_krita import FakePort, FakeResources, fake_node, layer_id

A: dict[str, Any] = {"pid": 101, "started_at": "Mon Nov  2 10:00:00 2026"}
B: dict[str, Any] = {"pid": 202, "started_at": "Mon Nov  2 10:05:00 2026"}
WIDTH, HEIGHT = 200, 120
CREATE = {
    "name": "sketch",
    "size_px": [WIDTH, HEIGHT],
    "color_model": "RGBA",
    "depth": "U8",
    "profile_id": documents.SRGB_PROFILE,
    "background": "transparent",
}
BASE, PAINT = layer_id(1, 0), layer_id(1, 1)
ACCEPTED = b"accepted art"
PLUGIN = Path(__file__).resolve().parents[2] / "plugin" / "krita_art_mcp_bridge"
NOT_APPLIED, UNCERTAIN = "not_applied", "uncertain"
# Each retryable raise in the plugin, by file and code; each has a test here that it changed
# nothing, because that is what its not_applied rests on.
RETRYABLE = [
    ("bridge_core/files.py", "FILE_EXISTS"),
    ("bridge_core/harness.py", "BUSY"),
    ("bridge_core/history.py", "INTERNAL_ERROR"),
    ("bridge_core/jobs.py", "CANCELLED"),
    ("bridge_core/jobs.py", "CANCELLED"),
    ("bridge_core/saving.py", "BUSY"),
    ("bridge_core/transfer.py", "IO_ERROR"),
    ("krita_adapter/documents.py", "KRITA_MODAL_DIALOG"),
    ("krita_adapter/documents.py", "MULTIPLE_WINDOWS"),
]


class World:
    # Every op runs through Jobs, and the fake refuses a mutating port call while a bounded op's
    # marker is unset, so a misplaced marker fails on its own path.
    def __init__(self, tmp: Path) -> None:
        self.data = tmp / "data"
        (self.data / "harness").mkdir(parents=True)
        self.art = tmp / "art"
        (self.art / "accepted").mkdir(parents=True)
        self.work = self.art / "work"
        self.saves = self.art / "revisions"
        roots = {"v": 1, "roots": [os.path.realpath(self.art)]}
        (self.data / "config.json").write_text(json.dumps(roots))
        self.port = FakePort()
        self.resources = FakeResources()
        self.resources.add_stroke_presets()
        self.registry = Registry(self.port, lambda client: True)
        self.ops: dict[str, Handler] = {
            **documents.handlers(self.registry, self.port, self.data),
            **harness.handlers(self.registry, self.port, self.data),
            **painting.handlers(self.registry, self.port, self.resources, self.data),
        }
        armed = {op: self._armed(handler) for op, handler in self.ops.items() if op in BOUNDED}
        log = logging.getLogger("test_outcomes")
        self.jobs = Jobs({**self.ops, **armed}, lambda: None, lambda: True, log)
        self.number = 0

    def _armed(self, handler: Handler) -> Handler:
        def run(args: dict[str, Any], call: Call) -> dict[str, Any]:
            self.port.marker = call
            try:
                result = handler(args, call)
            finally:
                self.port.marker = None
            # Nothing else can see a path whose changes are all the bridge's own state.
            assert call.changing, "a bounded op finished without its marker"
            return result

        return run

    def reply(self, op: str, args: dict[str, Any], client: dict[str, Any] = A) -> dict[str, Any]:
        self.number += 1
        operation_id = f"op-{self.number:032x}"
        submitted = self.jobs.submit(operation_id, f"req-{self.number}", op, args, client)
        assert submitted is not None
        self.jobs.drain()
        reply = self.jobs.wait(operation_id, 0)
        assert reply is not None
        return reply

    def done(self, op: str, args: dict[str, Any]) -> dict[str, Any]:
        reply = self.reply(op, args)
        assert reply["status"] == "done", reply
        result: dict[str, Any] = reply["result"]
        return result

    def failure(self, op: str, args: dict[str, Any], client: dict[str, Any] = A) -> dict[str, Any]:
        reply = self.reply(op, args, client)
        assert reply["status"] == "error", reply
        found: dict[str, Any] = reply["error"]
        return found

    def open_args(self, mode: str = "working_copy", **changes: Any) -> dict[str, Any]:
        path = self.art / "accepted" / "hero.kra"
        path.write_bytes(ACCEPTED)
        return {
            "source_path": str(path),
            "source_sha256": hashlib.sha256(ACCEPTED).hexdigest(),
            "mode": mode,
            "working_dir": str(self.work) if mode == "working_copy" else None,
            "editable_layer_ids": None,
            "editable_layer_names": None,
            **changes,
        }

    def document(self) -> str:
        # A protected base under the whole canvas and an empty editable layer.
        document_id: str = self.done("document.create", CREATE)["document_id"]
        handle = self.registry.find(document_id)
        tree = self.port._tree(1)
        box = {"x": 0, "y": 0, "width": WIDTH, "height": HEIGHT}
        tree["nodes"] = [
            fake_node(1, 0, "base", tree["root_id"], 0, bounds_px=box),
            fake_node(1, 1, "paint", tree["root_id"], 1),
        ]
        tree["active_id"] = PAINT
        handle.protected = {BASE}
        self.port.paintable(1)
        self.port.buffers[BASE] = bytearray(bytes([9, 8, 7, 255]) * (WIDTH * HEIGHT))
        return document_id

    def stroke_args(self, document_id: str, **changes: Any) -> dict[str, Any]:
        return {
            "document_id": document_id,
            "layer_id": PAINT,
            "verify": "region",
            "accepted_points": 2,
            "brush": {
                "preset_id": "basic-round.kpp",
                "preset_sha256": None,
                "size_px": 10,
                "opacity": 1,
                "flow": 1,
                "color": [1, 0.5, 0, 1],
                "eraser": False,
                "blend_mode": "normal",
                "alpha_lock": False,
                "rotation_deg": 0,
            },
            "path": {"start": [40, 60], "segments": [[50, 60]]},
            **changes,
        }

    def protection_args(self, document_id: str, **changes: Any) -> dict[str, Any]:
        return {
            "document_id": document_id,
            "protected_layer_ids": [BASE],
            "allowed_change_mask": None,
            "preserve_composite_alpha": False,
            "preserve_canvas": False,
            **changes,
        }

    def selection_args(self, document_id: str, shape: str, **changes: Any) -> dict[str, Any]:
        return {
            "document_id": document_id,
            "combine": "replace",
            "shape": {"kind": shape},
            "grow_px": 0,
            "shrink_px": 0,
            "feather_px": 0,
            "invert": False,
            **changes,
        }

    def layer_args(self, document_id: str, **changes: Any) -> dict[str, Any]:
        return {
            "document_id": document_id,
            "parent_id": self.port._tree(1)["root_id"],
            "above_id": None,
            "type": "paint",
            "name": "repair",
            **changes,
        }

    def update_args(self, document_id: str, **properties: Any) -> dict[str, Any]:
        return {
            "document_id": document_id,
            "layer_id": PAINT,
            "properties": properties,
            "verify": "region",
        }

    def history_args(self, document_id: str, action: str = "undo") -> dict[str, Any]:
        return {"document_id": document_id, "action": action, "steps": 1}

    def save_args(self, document_id: str, name: str = "hero-r02.kra") -> dict[str, Any]:
        return {"document_id": document_id, "path": str(self.saves / name)}

    def finish_args(self, saved: dict[str, Any], **changes: Any) -> dict[str, Any]:
        return {
            "document_id": saved["document_id"],
            "save_id": saved["save_id"],
            "merged_sha256": saved["composite_sha256"],
            "merged_problem": None,
            **changes,
        }

    def saved(self) -> dict[str, Any]:
        return self.done("document.save", self.save_args(self.document()))


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


def _raises(error: BaseException) -> Any:
    def raiser(*args: Any, **kwargs: Any) -> Any:
        raise error

    return raiser


def _outcome(body: dict[str, Any]) -> str:
    found: str = body["details"]["outcome"]
    return found


# The classes.


def test_every_op_is_classed(world: World) -> None:
    from_elsewhere = {"server_info", "bridge.unsaved_documents", "harness.retention"}
    from_elsewhere |= set(resources.handlers(world.resources))
    registered = set(world.ops) | from_elsewhere
    fixtures = {op for op in registered if op.startswith(HARNESS)}
    assert READS.isdisjoint(BOUNDED) and not (READS | BOUNDED) & fixtures
    assert registered == READS | BOUNDED | fixtures
    assert len(registered) == 31
    # The prefix hides no tool op: these are the fixture ops, by name.
    assert fixtures == set(harness.handlers(world.registry, world.port, world.data)) | {
        "harness.retention"
    }


def test_outcomes_the_plugin_names_are_the_servers() -> None:
    assert OUTCOMES == ("applied", "not_applied", "uncertain", "unregistered")


def test_a_read_that_refuses_changed_nothing(world: World) -> None:
    args = {"document_id": "doc-none", "frame": 0}
    assert _outcome(world.failure("document.inspect", args)) == NOT_APPLIED


def test_an_unexpected_raise_is_uncertain_even_in_a_read(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    document_id = world.document()
    monkeypatch.setattr(world.port, "tree", _raises(RuntimeError("Krita raised")))
    body = world.failure("document.inspect", {"document_id": document_id, "frame": 0})
    assert _outcome(body) == UNCERTAIN


def test_a_harness_op_has_no_marker_to_prove_anything(world: World) -> None:
    assert _outcome(world.failure("harness.undo", {"document_id": "doc-none"})) == UNCERTAIN


def test_an_op_nothing_classes_proves_nothing(tmp_path: Path) -> None:
    def refuses(args: dict[str, Any], call: Call) -> dict[str, Any]:
        raise BridgeError("INVALID_ARGUMENT", "No.")

    queue = Jobs({"new.op": refuses}, lambda: None, lambda: True, logging.getLogger("test"))
    queue.submit("op-1", "req-1", "new.op", {}, A)
    queue.drain()
    reply = queue.wait("op-1", 0)
    assert reply is not None and _outcome(reply["error"]) == UNCERTAIN


# Failures that never reach _run.


def test_a_request_conflict_never_ran(world: World) -> None:
    assert world.jobs.submit("op-1", "req-x", "document.list", {}, A) is not None
    conflict = world.jobs.submit("op-2", "req-x", "document.create", {"name": "x"}, A)
    assert conflict is not None and conflict.error is not None
    assert conflict.error["code"] == "REQUEST_ID_CONFLICT"
    assert _outcome(conflict.error) == NOT_APPLIED


def test_an_operation_id_already_taken_never_ran(world: World) -> None:
    assert world.jobs.submit("op-1", "req-1", "document.list", {}, A) is not None
    refused = world.jobs.submit("op-1", "req-2", "document.list", {}, A)
    assert refused is not None and refused.error is not None
    assert _outcome(refused.error) == NOT_APPLIED


def test_an_unknown_op_never_ran(world: World) -> None:
    unknown = world.jobs.submit("op-1", "req-1", "no.such", {}, A)
    assert unknown is not None and unknown.error is not None
    assert _outcome(unknown.error) == NOT_APPLIED


def test_a_cancelled_job_never_ran(world: World) -> None:
    assert world.jobs.submit("op-1", "req-1", "document.create", CREATE, A) is not None
    cancelled = world.jobs.cancel("op-1")
    assert cancelled is not None
    reply, stopped = cancelled
    assert stopped and reply["error"]["code"] == "CANCELLED"
    assert _outcome(reply["error"]) == NOT_APPLIED and reply["error"]["retryable"] is True
    world.jobs.drain()
    assert world.port.created == 0


def test_a_job_stopped_at_quit_never_ran(world: World) -> None:
    assert world.jobs.submit("op-1", "req-1", "document.create", CREATE, A) is not None
    world.jobs.stop()
    reply = world.jobs.wait("op-1", 0)
    assert reply is not None and _outcome(reply["error"]) == NOT_APPLIED
    assert reply["error"]["retryable"] is True and world.port.created == 0


def test_a_job_an_interrupt_stopped_is_uncertain() -> None:
    class Stops(Jobs):
        def _run(self, operation: jobs.Operation) -> None:
            raise KeyboardInterrupt

    queue = Stops({"x": lambda args, call: {}}, lambda: None, lambda: True, logging.getLogger("t"))
    queue.submit("op-1", "req-1", "x", {}, A)
    with pytest.raises(KeyboardInterrupt):
        queue.drain()
    reply = queue.wait("op-1", 0)
    assert reply is not None and _outcome(reply["error"]) == UNCERTAIN


def test_an_error_that_cannot_be_sent_is_uncertain() -> None:
    def odd(args: dict[str, Any], call: Call) -> dict[str, Any]:
        raise BridgeError("INVALID_ARGUMENT", "No.", False, {"bad": object()})

    queue = Jobs({"document.list": odd}, lambda: None, lambda: True, logging.getLogger("test"))
    queue.submit("op-1", "req-1", "document.list", {}, A)
    queue.drain()
    reply = queue.wait("op-1", 0)
    assert reply is not None and _outcome(reply["error"]) == UNCERTAIN


# Every path through every mutating op passes under the fake's refusal.


def test_a_working_copy_open_passes_its_marker(world: World) -> None:
    assert world.done("document.open", world.open_args())["working_copy"] is True


def test_a_read_only_open_passes_its_marker(world: World) -> None:
    assert world.done("document.open", world.open_args("read_only"))["mode"] == "read_only"


def test_a_stroke_and_history_pass_their_markers(world: World) -> None:
    document_id = world.document()
    world.done("paint.stroke", world.stroke_args(document_id))
    assert world.done("history.step", world.history_args(document_id))["steps_applied"] == 1
    assert world.done("history.step", world.history_args(document_id, "redo"))["verified"]


@pytest.mark.parametrize(
    "properties",
    [{"name": "kept"}, {"blend_mode": "multiply"}, {"opacity": 0.5}, {"active": True}],
    ids=["a property", "a blend", "an appearance", "active alone"],
)
def test_each_layer_update_passes_its_marker(world: World, properties: dict[str, Any]) -> None:
    document_id = world.document()
    world.done("layer.update", world.update_args(document_id, **properties))


def test_an_update_that_writes_nothing_passes_its_marker(world: World) -> None:
    document_id = world.document()
    world.done("layer.update", world.update_args(document_id, name="paint"))


def test_a_layer_and_a_close_pass_their_markers(world: World) -> None:
    document_id = world.document()
    world.done("layer.create", world.layer_args(document_id))
    closing = {"document_id": document_id, "dirty_policy": "discard"}
    assert world.done("document.close", closing)["closed"] is True


def test_each_selection_passes_its_marker(world: World) -> None:
    document_id = world.document()
    assert world.done("selection.set", world.selection_args(document_id, "all"))["undo_steps"] == 1
    assert world.done("selection.set", world.selection_args(document_id, "none"))["undo_steps"] == 1


def test_clearing_no_selection_passes_its_marker(world: World) -> None:
    document_id = world.document()
    assert world.done("selection.set", world.selection_args(document_id, "none"))["undo_steps"] == 0
    assert world.registry.find(document_id).dirty is True


def test_a_save_passes_both_markers(world: World) -> None:
    saved = world.saved()
    finished = world.done("document.save_finish", world.finish_args(saved))
    assert finished["dirty_cleared"] is True


def test_a_protection_change_passes_its_marker(world: World) -> None:
    document_id = world.document()
    assert world.done("protection.set", world.protection_args(document_id))["undo_steps"] == 0


# Each op, before its marker: an ordinary refusal changed nothing.


def test_an_open_refused_before_its_copy(world: World) -> None:
    source = world.open_args()["source_path"]
    args = world.open_args(working_dir=os.path.dirname(source))
    assert _outcome(world.failure("document.open", args)) == NOT_APPLIED


def test_a_read_only_open_of_a_changed_source(world: World) -> None:
    args = world.open_args("read_only", source_sha256="0" * 64)
    assert _outcome(world.failure("document.open", args)) == NOT_APPLIED


def test_a_create_refused_before_krita_makes_it(world: World) -> None:
    args = {**CREATE, "depth": "U16"}
    assert _outcome(world.failure("document.create", args)) == NOT_APPLIED


def test_a_close_refused_as_dirty(world: World) -> None:
    document_id = world.document()
    closing = {"document_id": document_id, "dirty_policy": "refuse"}
    world.registry.find(document_id).dirty = True
    assert _outcome(world.failure("document.close", closing)) == NOT_APPLIED


def test_a_save_refused_over_a_file(world: World) -> None:
    world.saves.mkdir()
    (world.saves / "hero-r02.kra").write_bytes(b"there")
    body = world.failure("document.save", world.save_args(world.document()))
    assert body["code"] == "FILE_EXISTS" and _outcome(body) == NOT_APPLIED


def test_a_finish_for_no_pending_save(world: World) -> None:
    document_id = world.document()
    args = {
        "document_id": document_id,
        "save_id": "op-none",
        "merged_sha256": None,
        "merged_problem": None,
    }
    assert _outcome(world.failure("document.save_finish", args)) == NOT_APPLIED


def test_a_protection_loosening_refused(world: World) -> None:
    args = world.protection_args(world.document(), protected_layer_ids=[])
    assert _outcome(world.failure("protection.set", args)) == NOT_APPLIED


def test_a_selection_refused_with_nothing_to_combine(world: World) -> None:
    args = world.selection_args(world.document(), "all", combine="subtract")
    assert _outcome(world.failure("selection.set", args)) == NOT_APPLIED


def test_a_layer_refused_for_its_parent(world: World) -> None:
    args = world.layer_args(world.document(), parent_id=layer_id(1, 9))
    assert _outcome(world.failure("layer.create", args)) == NOT_APPLIED


def test_an_update_refused_on_a_protected_layer(world: World) -> None:
    args = {**world.update_args(world.document(), name="x"), "layer_id": BASE}
    assert _outcome(world.failure("layer.update", args)) == NOT_APPLIED


def test_a_stroke_refused_on_a_protected_layer(world: World) -> None:
    args = world.stroke_args(world.document(), layer_id=BASE)
    assert _outcome(world.failure("paint.stroke", args)) == NOT_APPLIED


def test_the_brush_is_no_change_a_refused_stroke_answers_for(world: World) -> None:
    # The window-wide brush was set, and the marker says what the document did.
    document_id = world.document()
    world.port.brush_drift = {"size_px": 99}
    body = world.failure("paint.stroke", world.stroke_args(document_id))
    assert body["code"] == "INTERNAL_ERROR" and _outcome(body) == NOT_APPLIED


def test_a_history_step_refused_for_its_count(world: World) -> None:
    args = world.history_args(world.document())
    assert _outcome(world.failure("history.step", args)) == NOT_APPLIED


def test_a_history_step_that_meets_a_foreign_step(world: World) -> None:
    document_id = world.document()
    world.done("paint.stroke", world.stroke_args(document_id))
    world.port.undo(world.registry.find(document_id).document)
    body = world.failure("history.step", world.history_args(document_id))
    assert body["code"] == "INVALID_ARGUMENT" and _outcome(body) == NOT_APPLIED


def test_a_job_start_refusal_changed_nothing(world: World) -> None:
    document_id = world.document()
    world.port.refuse = BridgeError("KRITA_MODAL_DIALOG", "A dialog is open.", True)
    body = world.failure("paint.stroke", world.stroke_args(document_id))
    assert _outcome(body) == NOT_APPLIED and body["retryable"] is True
    assert world.port.paths == []


def test_a_lease_refusal_changed_nothing(world: World) -> None:
    document_id = world.document()
    body = world.failure("paint.stroke", world.stroke_args(document_id), B)
    assert body["code"] == "DOCUMENT_IN_USE" and _outcome(body) == NOT_APPLIED


# Each op, past its marker: only a verified cleanup or rollback proves it changed nothing.


def test_an_open_that_keeps_its_document_is_uncertain(world: World) -> None:
    world.port.close_works = False
    world.port.fail["tree"] = BridgeError("IO_ERROR", "tree failed")
    body = world.failure("document.open", world.open_args("read_only"))
    del world.port.fail["tree"]
    assert _outcome(body) == UNCERTAIN and isinstance(body["details"]["document_id"], str)
    assert body["details"]["rollback_verified"] is False


def test_a_retryable_raise_that_keeps_its_document_is_no_retry(world: World) -> None:
    world.port.close_works = False
    world.port.fail["tree"] = BridgeError("BUSY", "Retry.", True)
    body = world.failure("document.open", world.open_args("read_only"))
    del world.port.fail["tree"]
    assert body["retryable"] is False and _outcome(body) == UNCERTAIN


def test_a_retryable_raise_that_keeps_a_new_document_is_no_retry(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.port.close_works = False
    monkeypatch.setattr(world.port, "layers", _raises(BridgeError("BUSY", "Retry.", True)))
    body = world.failure("document.create", CREATE)
    assert body["retryable"] is False and _outcome(body) == UNCERTAIN


def test_an_open_undone_is_not_applied(world: World) -> None:
    world.port.fail["tree"] = BridgeError("IO_ERROR", "tree failed")
    body = world.failure("document.open", world.open_args())
    del world.port.fail["tree"]
    assert _outcome(body) == NOT_APPLIED and body["details"]["rollback_verified"] is True
    assert not world.work.exists()


def test_an_open_krita_could_not_read_is_not_applied(world: World) -> None:
    world.port.fail["open"] = BridgeError("IO_ERROR", "Krita could not open the file.")
    body = world.failure("document.open", world.open_args("read_only"))
    assert _outcome(body) == NOT_APPLIED and body["details"]["rollback_verified"] is True


def test_a_wrong_hash_on_a_working_copy_is_an_ordinary_refusal(world: World) -> None:
    body = world.failure("document.open", world.open_args(source_sha256="0" * 64))
    assert body["code"] == "SOURCE_HASH_MISMATCH"
    assert _outcome(body) == NOT_APPLIED and body["details"]["rollback_verified"] is True
    assert not world.work.exists()


def test_a_copy_that_stays_is_uncertain(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(files, "remove", lambda path: False)
    body = world.failure("document.open", world.open_args(source_sha256="0" * 64))
    assert _outcome(body) == UNCERTAIN and body["details"]["rollback_verified"] is False


def test_a_folder_that_stays_is_uncertain(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(files, "unmake", lambda made: False)
    body = world.failure("document.open", world.open_args(source_sha256="0" * 64))
    assert _outcome(body) == UNCERTAIN and body["details"]["rollback_verified"] is False


def test_a_create_krita_kept_is_uncertain(world: World) -> None:
    world.port.close_works = False
    world.port.layer = {**world.port.layer, "alpha_at_origin": 255}
    body = world.failure("document.create", CREATE)
    assert _outcome(body) == UNCERTAIN and isinstance(body["details"]["document_id"], str)


def test_a_create_undone_is_not_applied(world: World) -> None:
    world.port.layer = {**world.port.layer, "alpha_at_origin": 255}
    body = world.failure("document.create", CREATE)
    assert _outcome(body) == NOT_APPLIED and body["details"]["rollback_verified"] is True
    assert world.registry.sync() == []


def test_a_create_krita_refused_is_uncertain(world: World) -> None:
    def refuses() -> None:
        raise BridgeError("INTERNAL_ERROR", "Krita did not create the document.")

    world.port.on_create.append(refuses)
    assert _outcome(world.failure("document.create", CREATE)) == UNCERTAIN


def test_a_close_krita_refused_is_uncertain(world: World) -> None:
    document_id = world.document()
    world.port.close_works = False
    closing = {"document_id": document_id, "dirty_policy": "discard"}
    assert _outcome(world.failure("document.close", closing)) == UNCERTAIN


def test_a_save_that_moved_the_document_is_uncertain_however_clean_its_file(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    document_id = world.document()
    described = world.port.describe

    def moved(document: Any) -> dict[str, Any]:
        info = described(document)
        return {**info, "path": "/moved.kra"} if world.port.calls[-1:] == ["export"] else info

    monkeypatch.setattr(world.port, "describe", moved)
    body = world.failure("document.save", world.save_args(document_id))
    assert _outcome(body) == UNCERTAIN and body["details"]["rollback_verified"] is True
    assert not world.saves.exists()


def test_a_save_that_failed_its_verification_is_undone(world: World) -> None:
    document_id = world.document()

    def changes(saved: dict[str, Any]) -> None:
        saved["composite"] = bytes(len(saved["composite"]))

    world.port.on_export.append(changes)
    body = world.failure("document.save", world.save_args(document_id))
    assert body["code"] == "SAVE_VERIFY_FAILED"
    assert _outcome(body) == NOT_APPLIED and body["details"]["rollback_verified"] is True
    assert not world.saves.exists()


def test_a_save_refused_for_its_folder_is_undone(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    document_id = world.document()
    monkeypatch.setattr(os, "access", lambda path, mode: False)
    body = world.failure("document.save", world.save_args(document_id))
    assert body["code"] == "IO_ERROR"
    assert _outcome(body) == NOT_APPLIED and body["details"]["rollback_verified"] is True
    assert not world.saves.exists()


def test_a_save_whose_file_stays_is_uncertain(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    document_id = world.document()
    monkeypatch.setattr(files, "remove", lambda path: False)
    world.port.export_works = False
    body = world.failure("document.save", world.save_args(document_id))
    assert body["code"] == "BUSY" and body["retryable"] is False
    assert _outcome(body) == UNCERTAIN and body["details"]["rollback_verified"] is False


def test_a_finish_discarded_is_not_applied(world: World) -> None:
    saved = world.saved()
    args = world.finish_args(saved, merged_sha256="0" * 64)
    body = world.failure("document.save_finish", args)
    assert body["code"] == "SAVE_VERIFY_FAILED"
    assert _outcome(body) == NOT_APPLIED and body["details"]["rollback_verified"] is True
    assert not os.path.lexists(saved["written"]) and not world.saves.exists()


def test_a_finish_that_could_not_discard_is_uncertain(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    saved = world.saved()
    monkeypatch.setattr(files, "remove", lambda path: False)
    body = world.failure("document.save_finish", world.finish_args(saved, merged_sha256="0" * 64))
    assert _outcome(body) == UNCERTAIN and body["details"]["rollback_verified"] is False


def test_a_finish_that_changed_file_is_discarded(world: World) -> None:
    saved = world.saved()
    Path(saved["written"]).write_bytes(b"something else")
    body = world.failure("document.save_finish", world.finish_args(saved))
    assert _outcome(body) == NOT_APPLIED and body["details"]["rollback_verified"] is True


def test_a_finish_that_cannot_place_its_file_is_undone(world: World) -> None:
    saved = world.saved()
    Path(saved["path"]).write_bytes(b"there first")
    body = world.failure("document.save_finish", world.finish_args(saved))
    assert body["code"] == "FILE_EXISTS"
    assert _outcome(body) == NOT_APPLIED and body["details"]["rollback_verified"] is True
    assert not os.path.lexists(saved["written"])


def test_a_protection_write_that_raised_is_uncertain(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    document_id = world.document()
    rect = {"x": 0, "y": 0, "width": WIDTH, "height": HEIGHT}
    data = b"\xff" * (WIDTH * HEIGHT)
    digest = hashlib.sha256(data).hexdigest()
    key = hashlib.sha256(f"req-{world.number + 1}".encode()).hexdigest()[:16]
    folder = world.data / "transfer"
    folder.mkdir(exist_ok=True)
    path = folder / f"mask-{key}-{digest}.a8"
    path.write_bytes(data)
    spec = {"path": str(path), "size_px": [WIDTH, HEIGHT], "format": "A8", "sha256": digest}
    mask = {"origin_px": [rect["x"], rect["y"]], "mask": spec, "source_path": None}
    monkeypatch.setattr(protection, "summary", _raises(BridgeError("INTERNAL_ERROR", "No.")))
    args = world.protection_args(document_id, allowed_change_mask=mask)
    assert _outcome(world.failure("protection.set", args)) == UNCERTAIN


def test_a_selection_krita_refused_is_uncertain(world: World) -> None:
    document_id = world.document()
    world.port.fail["set_selection"] = BridgeError("INTERNAL_ERROR", "No.")
    args = world.selection_args(document_id, "all")
    assert _outcome(world.failure("selection.set", args)) == UNCERTAIN


def test_a_layer_krita_refused_is_uncertain(world: World) -> None:
    document_id = world.document()
    world.port.fail["create_layer"] = BridgeError("INTERNAL_ERROR", "Krita did not add the layer.")
    assert _outcome(world.failure("layer.create", world.layer_args(document_id))) == UNCERTAIN


def _misplaced(tree: dict[str, Any], node: dict[str, Any]) -> None:
    node["name"] = "elsewhere"


def test_a_layer_rolled_back_is_not_applied(world: World) -> None:
    document_id = world.document()
    world.port.on_layer.append(_misplaced)
    body = world.failure("layer.create", world.layer_args(document_id))
    assert body["details"]["rolled_back"] is True and body["details"]["rollback_verified"] is True
    assert _outcome(body) == NOT_APPLIED


def test_a_layer_that_could_not_be_rolled_back_is_uncertain(world: World) -> None:
    document_id = world.document()
    world.port.on_layer.append(_misplaced)
    world.port.undo_works = False
    body = world.failure("layer.create", world.layer_args(document_id))
    assert body["code"] == "ROLLBACK_FAILED" and body["details"]["rollback_verified"] is False
    assert _outcome(body) == UNCERTAIN


def test_an_update_krita_raised_in_is_rolled_back(world: World) -> None:
    document_id = world.document()
    raised: list[str] = []

    def once(*args: Any) -> None:
        if not raised:
            raised.append("once")
            raise BridgeError("INTERNAL_ERROR", "No.")

    world.port.on_properties.append(once)
    body = world.failure("layer.update", world.update_args(document_id, name="kept"))
    assert body["details"]["rollback_verified"] is True and _outcome(body) == NOT_APPLIED


def test_an_activation_krita_refused_is_uncertain(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    document_id = world.document()
    monkeypatch.setattr(world.port, "activate", _raises(BridgeError("INTERNAL_ERROR", "No.")))
    body = world.failure("layer.update", world.update_args(document_id, active=True))
    assert _outcome(body) == UNCERTAIN


def test_a_leak_rolled_back_is_not_applied_and_a_stuck_one_uncertain(world: World) -> None:
    document_id = world.document()
    leak = {"x": 100, "y": 100, "width": 4, "height": 4}
    world.done(
        "protection.set",
        world.protection_args(document_id, preserve_composite_alpha=False),
    )
    world.port.stray = [leak]
    world.port.layer_pixels[BASE] = bytes(4)
    args = world.stroke_args(document_id, verify="full")
    handle = world.registry.find(document_id)
    handle.allowed_mask = bytes(WIDTH * HEIGHT)
    region = bytearray(WIDTH * HEIGHT)
    for row in range(40, 80):
        region[row * WIDTH + 20 : row * WIDTH + 80] = b"\xff" * 60
    handle.allowed_mask = bytes(region)
    body = world.failure("paint.stroke", args)
    assert body["code"] == "PROTECTED_REGION_CHANGED" and _outcome(body) == NOT_APPLIED
    assert body["details"]["rollback_verified"] is True and body["retryable"] is False
    world.port.undo_works = False
    stuck = world.failure("paint.stroke", args)
    assert stuck["code"] == "ROLLBACK_FAILED" and _outcome(stuck) == UNCERTAIN
    assert stuck["details"]["rollback_verified"] is False


def test_a_stroke_krita_raised_in_is_uncertain_when_nothing_confirms_it(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    document_id = world.document()
    monkeypatch.setattr(world.port, "paint_path", _raises(KeyboardInterrupt()))
    body = world.failure("paint.stroke", world.stroke_args(document_id))
    assert _outcome(body) == UNCERTAIN
    assert world.registry.find(document_id).unsafe is True


def test_a_step_krita_did_not_take_is_retryable_and_changed_nothing(world: World) -> None:
    document_id = world.document()
    world.done("paint.stroke", world.stroke_args(document_id))
    handle = world.registry.find(document_id)
    handle.dirty = False
    world.port.undo_works = False
    before = len(handle.ledger.steps)
    body = world.failure("history.step", world.history_args(document_id))
    assert body["retryable"] is True and _outcome(body) == NOT_APPLIED
    assert handle.dirty is False and len(handle.ledger.steps) == before


def test_a_step_krita_lost_is_uncertain(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    document_id = world.document()
    world.done("paint.stroke", world.stroke_args(document_id))
    monkeypatch.setattr(world.port, "undo", _raises(RuntimeError("Krita raised")))
    body = world.failure("history.step", world.history_args(document_id))
    assert body["code"] == "INTERNAL_ERROR" and _outcome(body) == UNCERTAIN
    assert world.registry.find(document_id).unsafe is True


def test_a_read_that_leaves_a_document_says_so(world: World) -> None:
    document_id = world.document()
    world.port.close_works = False
    body = world.failure("document.save", world.save_args(document_id))
    assert _outcome(body) == UNCERTAIN and isinstance(body["details"]["document_id"], str)


def test_a_read_whose_file_stays_open_after_it_raised_says_so(world: World) -> None:
    opened = world.done("document.open", world.open_args())
    world.port.files[opened["path"]] = {"size_px": [9, 9]}
    world.port.close_works = False
    source = {
        "document_id": opened["document_id"],
        "frame": 0,
        "target": "composite",
        "layer_id": None,
        "rect": None,
        "baseline_id": opened["baseline_id"],
        "read_baseline": True,
        "overlays": [],
    }
    body = world.failure("preview.read", {"sources": [source], "render": {}})
    assert isinstance(body["details"]["left_open"], str) and _outcome(body) == UNCERTAIN


# A retryable raise changed nothing, at every site.


def _retryable_raises() -> list[tuple[str, str]]:
    found = []
    for path in sorted(PLUGIN.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", getattr(node.func, "attr", None))
            flag = node.args[2] if len(node.args) >= 3 else None
            if name in ("BridgeError", "error") and isinstance(flag, ast.Constant) and flag.value:
                code = ast.literal_eval(node.args[0])
                found.append((path.relative_to(PLUGIN).as_posix(), code))
    return found


def test_every_retryable_raise_is_one_this_file_answers_for() -> None:
    assert _retryable_raises() == RETRYABLE


def test_a_name_collision_is_retryable_and_changed_nothing(world: World) -> None:
    world.work.mkdir()
    taken = world.work / files.copy_name("hero.kra", _now())
    taken.write_bytes(b"someone's work")
    ops = _opening_at(world)
    with pytest.raises(BridgeError) as refused:
        ops["document.open"](world.open_args(), Call("op-n", "req-n", A))
    body = refused.value.body
    assert body["code"] == "FILE_EXISTS" and body["retryable"] is True
    assert taken.read_bytes() == b"someone's work" and world.work.exists()


def test_busy_leaves_an_earlier_unfinished_save_as_it_was(world: World) -> None:
    saved = world.saved()
    pending = world.registry.find(saved["document_id"]).pending_save
    world.port.export_works = False
    body = world.failure("document.save", world.save_args(saved["document_id"], "other.kra"))
    assert body["code"] == "BUSY" and body["retryable"] is True and _outcome(body) == NOT_APPLIED
    assert world.registry.find(saved["document_id"]).pending_save is pending
    assert os.path.lexists(saved["written"])
    assert sorted(os.listdir(world.saves)) == [os.path.basename(saved["written"])]


def test_a_failed_verify_leaves_an_earlier_unfinished_save_too(world: World) -> None:
    saved = world.saved()
    pending = world.registry.find(saved["document_id"]).pending_save

    def changes(found: dict[str, Any]) -> None:
        found["composite"] = bytes(len(found["composite"]))

    world.port.on_export.append(changes)
    body = world.failure("document.save", world.save_args(saved["document_id"], "other.kra"))
    assert body["code"] == "SAVE_VERIFY_FAILED"
    assert world.registry.find(saved["document_id"]).pending_save is pending
    assert os.path.lexists(saved["written"])


def test_a_verified_save_replaces_an_earlier_unfinished_one(world: World) -> None:
    saved = world.saved()
    again = world.done("document.save", world.save_args(saved["document_id"], "other.kra"))
    assert not os.path.lexists(saved["written"]) and os.path.lexists(again["written"])
    pending = world.registry.find(saved["document_id"]).pending_save
    assert pending.save_id == again["save_id"]


def test_a_mask_gone_is_retryable_and_changed_nothing(world: World) -> None:
    document_id = world.document()
    digest = hashlib.sha256(b"\xff").hexdigest()
    key = hashlib.sha256(f"req-{world.number + 1}".encode()).hexdigest()[:16]
    (world.data / "transfer").mkdir(exist_ok=True)
    path = world.data / "transfer" / f"mask-{key}-{digest}.a8"
    spec = {"path": str(path), "size_px": [1, 1], "format": "A8", "sha256": digest}
    mask = {"origin_px": [0, 0], "mask": spec, "source_path": None}
    args = world.protection_args(document_id, allowed_change_mask=mask)
    body = world.failure("protection.set", args)
    assert body["retryable"] is True and _outcome(body) == NOT_APPLIED
    assert world.registry.find(document_id).allowed_mask is None


def test_a_harness_export_refused_is_retryable_and_wrote_nothing(tmp_path: Path) -> None:
    world = World(tmp_path)
    folder = world.data / "harness"
    source = folder / "fixture.ora"
    source.write_bytes(ACCEPTED)
    opened = world.done(
        "document.open",
        {
            "source_path": str(source),
            "source_sha256": hashlib.sha256(ACCEPTED).hexdigest(),
            "mode": "read_only",
            "working_dir": None,
            "editable_layer_ids": None,
            "editable_layer_names": None,
        },
    )
    world.port.export_works = False
    args = {"document_id": opened["document_id"], "target_path": str(folder / "copy.kra")}
    body = world.failure("harness.export_kra", args)
    assert body["retryable"] is True and _outcome(body) == NOT_APPLIED
    assert not (folder / "copy.kra").exists()


# The cleanup helpers.


def test_a_folder_something_else_filled_counts_as_cleaned(tmp_path: Path) -> None:
    folder = tmp_path / "deep" / "er"
    made = files.make_folder(str(folder), "folder")
    assert made == [str(folder), str(folder.parent)]
    (folder.parent / "theirs.txt").write_text("kept")
    assert files.unmake(made) is True
    assert not folder.exists() and (folder.parent / "theirs.txt").exists()


def test_a_folder_of_ours_that_stays_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def denied(path: str) -> None:
        raise PermissionError(13, "denied")

    monkeypatch.setattr(os, "rmdir", denied)
    assert files.unmake([str(tmp_path)]) is False


def test_a_folder_that_went_counts_as_cleaned(tmp_path: Path) -> None:
    assert files.unmake([str(tmp_path / "gone")]) is True


def test_a_failed_folder_reports_what_it_left(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fails(path: str, exist_ok: bool = False) -> None:
        raise PermissionError(13, "denied")

    monkeypatch.setattr(os, "makedirs", fails)
    with pytest.raises(BridgeError) as refused:
        files.make_folder(str(tmp_path / "new"), "path's folder")
    assert refused.value.body["details"]["rollback_verified"] is True
    assert "path's folder cannot be made" in refused.value.body["message"]


def test_a_removal_is_checked_by_what_is_left(tmp_path: Path) -> None:
    path = tmp_path / "file"
    path.write_bytes(b"x")
    assert files.remove(str(path)) is True
    assert files.remove(str(path)) is True
    folder = tmp_path / "folder"
    folder.mkdir()
    assert files.remove(str(folder)) is False


def test_cleaned_only_narrows() -> None:
    raised = BridgeError("BUSY", "Retry.", True)
    cleaned(raised, True)
    assert raised.body["retryable"] is True
    cleaned(raised, False)
    assert raised.body["retryable"] is False
    cleaned(raised, True)
    assert raised.body["details"]["rollback_verified"] is False


def test_cleaned_leaves_an_unexpected_raise_alone() -> None:
    cleaned(RuntimeError("Krita raised"), False)


def _now() -> Any:
    import datetime

    return datetime.datetime(2026, 11, 2, 12, 0, tzinfo=datetime.timezone.utc)


def _opening_at(world: World) -> dict[str, Handler]:
    from bridge_core import opening

    return opening.handlers(world.registry, world.port, world.data, now=_now)
