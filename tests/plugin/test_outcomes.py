import ast
import datetime
import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any

import pytest
from bridge_core import (
    documents,
    files,
    harness,
    history,
    jobs,
    log,
    opening,
    painting,
    protection,
    resources,
)
from bridge_core.errors import OUTCOMES, BridgeError, cleaned
from bridge_core.jobs import BOUNDED, HARNESS, READS, Call, Handler, Jobs
from bridge_core.registry import Registry
from bridge_core.resources import fingerprint
from fake_krita import (
    PRESET_XML,
    FakePort,
    FakeResources,
    fake_node,
    layer_id,
)

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
NOW = datetime.datetime(2026, 11, 2, 12, 0, tzinfo=datetime.timezone.utc)
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
    ("bridge_core/mutation.py", "INTERNAL_ERROR"),
    ("bridge_core/registry.py", "DOCUMENT_IN_USE (computed)"),
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
                "mask": None,
                "eraser": False,
                "blend_mode": "normal",
                "alpha_lock": False,
                "rotation_deg": 0,
            },
            "path": {"start": [40, 60], "segments": [[50, 60]]},
            "dynamics": None,
            **changes,
        }

    def fill_args(self, document_id: str, **changes: Any) -> dict[str, Any]:
        return {
            "document_id": document_id,
            "layer_id": PAINT,
            "verify": "region",
            "shape": {"kind": "rect", "rect": {"x": 40, "y": 50, "width": 20, "height": 10}},
            "fill": {
                "color": [1, 0.5, 0, 1],
                "mask": None,
                "opacity": 1,
                "blend_mode": "normal",
                "alpha_lock": False,
            },
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
            "coverage": None,
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

    def translate_args(self, document_id: str, by: list[int]) -> dict[str, Any]:
        return {
            "document_id": document_id,
            "layer_id": PAINT,
            "operation": {"type": "translate", "by_px": by},
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
    assert len(registered) == 39
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


def test_a_tapered_stroke_passes_its_marker(world: World) -> None:
    # The preset's edit and its restore are changes of Krita's, so both come after the marker.
    document_id = world.document()
    taper = {"size": [{"at": 0, "value": 0.2}, {"at": 1, "value": 1}], "opacity": None}
    brush = {**world.stroke_args(document_id)["brush"], "preset_sha256": fingerprint(PRESET_XML)[1]}
    args = world.stroke_args(document_id, brush=brush, dynamics=taper)
    assert world.done("paint.stroke", args)["effective_brush"]["dynamics"] is not None


def test_a_fill_passes_its_marker_and_a_refused_one_is_not_applied(world: World) -> None:
    document_id = world.document()
    assert world.done("paint.fill", world.fill_args(document_id))["undo_steps"] == 1
    body = world.failure("paint.fill", world.fill_args(document_id, layer_id=BASE))
    assert (body["code"], body["details"]["outcome"]) == ("LOCKED_TARGET", "not_applied")


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


def test_the_layer_ops_pass_their_markers(world: World) -> None:
    document_id = world.document()
    duplicate = {"document_id": document_id, "layer_id": BASE, "name": "trial"}
    copy = world.done("layer.duplicate", duplicate)["layer_id"]
    group = world.done("layer.create", world.layer_args(document_id, type="group"))["layer_id"]
    move = {"document_id": document_id, "layer_id": PAINT, "parent_id": group, "above_id": None}
    assert world.done("layer.reorder", move)["undo_steps"] == 2
    # Already there: nothing moves, and the call still passes its marker.
    assert world.done("layer.reorder", move)["undo_steps"] == 0
    removal = {"document_id": document_id, "layer_id": copy, "verify": "full"}
    assert world.done("layer.remove", removal)["removed"] == [copy]


def test_a_translate_passes_its_marker_making_and_moving_its_mask(world: World) -> None:
    document_id = world.document()
    made = world.done("layer.transform", world.translate_args(document_id, [3, -2]))
    assert made["created_mask"] is True and made["undo_steps"] == 2
    moved = world.done("layer.transform", world.translate_args(document_id, [1, 1]))
    assert moved["created_mask"] is False and moved["translation_px"] == [4, -1]


def test_a_translate_whose_document_changed_as_it_began_changed_nothing(world: World) -> None:
    document_id = world.document()
    tree = world.port._tree(1)

    def renamed() -> None:
        tree["nodes"][0]["name"] = "renamed by hand"

    world.port.on_read.append(renamed)
    body = world.failure("layer.transform", world.translate_args(document_id, [3, 0]))
    assert body["code"] == "INTERNAL_ERROR" and body["retryable"] is True
    assert _outcome(body) == NOT_APPLIED
    assert world.port.live[1].get("stack", []) == []
    assert all(node["type"] != "transformmask" for node in world.port._tree(1)["nodes"])


def _painted(world: World) -> None:
    buffer = world.port.buffers[PAINT]
    for y in range(10, 20):
        buffer[(y * WIDTH + 10) * 4 : (y * WIDTH + 30) * 4] = bytes([1, 2, 3, 255]) * 20
    world.port._layer(1, PAINT)["bounds_px"] = {"x": 10, "y": 10, "width": 20, "height": 10}


def _reshape(document_id: str, operation: dict[str, Any]) -> dict[str, Any]:
    return {"document_id": document_id, "layer_id": PAINT, "operation": operation}


@pytest.mark.parametrize(
    "operation",
    [
        {"type": "scale", "size_px": [40, 20], "filter": "Bicubic"},
        {"type": "rotate", "degrees": 30},
        {"type": "shear", "degrees": [0, 20]},
    ],
)
def test_a_scale_rotate_or_shear_passes_its_marker(world: World, operation: dict[str, Any]) -> None:
    document_id = world.document()
    _painted(world)
    assert world.done("layer.transform", _reshape(document_id, operation))["undo_steps"] == 1


def test_a_transform_whose_document_changed_as_it_began_changed_nothing(world: World) -> None:
    document_id = world.document()
    _painted(world)
    tree = world.port._tree(1)

    def renamed() -> None:
        tree["nodes"][0]["name"] = "renamed by hand"

    world.port.on_read.append(renamed)
    operation = {"type": "rotate", "degrees": 30}
    body = world.failure("layer.transform", _reshape(document_id, operation))
    assert body["code"] == "INTERNAL_ERROR" and body["retryable"] is True
    assert _outcome(body) == NOT_APPLIED
    assert world.port.live[1].get("stack", []) == [] and world.port.reshaped == []


def _moved(world: World) -> None:
    # A change of the owner's, landing while Krita is waited on, on a node no op here names.
    world.port._tree(1)["nodes"][0]["name"] = "renamed by hand"


@pytest.mark.parametrize(
    ("op", "arguments"),
    [
        ("layer.duplicate", {"layer_id": PAINT, "name": "trial"}),
        ("layer.remove", {"layer_id": PAINT, "verify": "region"}),
        ("layer.update", {"layer_id": PAINT, "properties": {"opacity": 0.5}, "verify": "region"}),
    ],
)
def test_an_op_whose_document_changed_as_it_began_changed_nothing(
    world: World, op: str, arguments: dict[str, Any]
) -> None:
    document_id = world.document()
    _painted(world)
    steps = len(world.registry.find(document_id).ledger.steps)
    world.port.on_read.append(lambda: _moved(world))
    body = world.failure(op, {"document_id": document_id, **arguments})
    assert body["code"] == "INTERNAL_ERROR" and body["retryable"] is True
    assert _outcome(body) == NOT_APPLIED
    assert world.port.live[1].get("stack", []) == []
    assert len(world.registry.find(document_id).ledger.steps) == steps
    assert not world.registry.find(document_id).dirty


def test_a_reorder_whose_document_changed_as_it_began_changed_nothing(world: World) -> None:
    document_id = world.document()
    group = world.done("layer.create", world.layer_args(document_id, type="group"))["layer_id"]
    world.port.on_read.append(lambda: _moved(world))
    move = {"document_id": document_id, "layer_id": PAINT, "parent_id": group, "above_id": None}
    body = world.failure("layer.reorder", move)
    assert body["code"] == "INTERNAL_ERROR" and body["retryable"] is True
    assert _outcome(body) == NOT_APPLIED
    assert world.port._layer(1, PAINT)["parent_id"] == world.port._tree(1)["root_id"]


def test_a_stroke_whose_document_changed_as_it_began_changed_nothing(world: World) -> None:
    document_id = world.document()
    before = bytes(world.port.buffers[PAINT])
    world.port.on_read.append(lambda: _moved(world))
    body = world.failure("paint.stroke", world.stroke_args(document_id))
    assert body["code"] == "INTERNAL_ERROR" and body["retryable"] is True
    assert _outcome(body) == NOT_APPLIED
    assert bytes(world.port.buffers[PAINT]) == before


def test_a_mask_whose_document_changed_as_it_began_changed_nothing(world: World) -> None:
    document_id = world.document()
    _painted(world)
    args = world.layer_args(document_id, type="transparency_mask", parent_id=PAINT, coverage="all")
    world.port.on_read.append(lambda: _moved(world))
    body = world.failure("layer.create", args)
    assert body["code"] == "INTERNAL_ERROR" and body["retryable"] is True
    assert _outcome(body) == NOT_APPLIED
    assert all(node["type"] != "transparencymask" for node in world.port._tree(1)["nodes"])


def test_a_layer_created_while_the_document_changed_changed_nothing(world: World) -> None:
    # A paint layer's create reads no pixels, so the frame's own tree read is the first wait.
    document_id = world.document()
    real, seen = world.port.tree, []

    def counting(document: Any) -> dict[str, Any]:
        seen.append(document)
        if len(seen) == 2:
            _moved(world)
        return real(document)

    world.port.tree = counting  # type: ignore[method-assign]
    body = world.failure("layer.create", world.layer_args(document_id))
    assert body["code"] == "INTERNAL_ERROR" and body["retryable"] is True
    assert _outcome(body) == NOT_APPLIED
    assert world.port.live[1].get("stack", []) == []


def test_a_transform_refused_or_raised_before_krita_moved_is_not_applied(world: World) -> None:
    document_id = world.document()
    _painted(world)
    held = {**_reshape(document_id, {"type": "rotate", "degrees": 30}), "layer_id": BASE}
    assert _outcome(world.failure("layer.transform", held)) == NOT_APPLIED
    world.port.fail["transform_node"] = BridgeError("INTERNAL_ERROR", "Krita did not take it.")
    body = world.failure(
        "layer.transform", _reshape(document_id, {"type": "rotate", "degrees": 30})
    )
    assert body["details"]["rollback_verified"] is True
    assert _outcome(body) == NOT_APPLIED


def test_a_translate_krita_refused_between_its_steps_is_not_applied(world: World) -> None:
    document_id = world.document()
    world.port.fail["set_transform"] = BridgeError("INTERNAL_ERROR", "Krita did not take it.")
    body = world.failure("layer.transform", world.translate_args(document_id, [3, 0]))
    assert body["details"]["rolled_back"] is True and body["details"]["rollback_verified"] is True
    assert _outcome(body) == NOT_APPLIED
    assert all(node["type"] != "transformmask" for node in world.port._tree(1)["nodes"])


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


def test_a_duplicate_passes_its_three_markers(world: World) -> None:
    saved = world.done("document.duplicate", world.save_args(world.document(), "hero-b.kra"))
    world.done("document.save_finish", world.finish_args(saved))
    args = {"document_id": saved["document_id"], "save_id": saved["save_id"]}
    opened = world.done("document.duplicate_open", args)
    assert opened["path"] == saved["path"] and opened["new_document_id"] != saved["document_id"]


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


@pytest.mark.parametrize(
    "op", ["layer.duplicate", "layer.reorder", "layer.remove", "layer.transform"]
)
def test_a_layer_op_refused_before_its_marker(world: World, op: str) -> None:
    document_id = world.document()
    args = {
        "layer.duplicate": {"document_id": document_id, "layer_id": layer_id(1, 9), "name": "x"},
        "layer.reorder": {
            "document_id": document_id,
            "layer_id": BASE,
            "parent_id": world.port._tree(1)["root_id"],
            "above_id": None,
        },
        "layer.remove": {"document_id": document_id, "layer_id": BASE, "verify": "full"},
        "layer.transform": {**world.translate_args(document_id, [1, 0]), "layer_id": BASE},
    }[op]
    assert _outcome(world.failure(op, args)) == NOT_APPLIED


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
    assert body["retryable"] is False


def test_a_finish_refused_for_its_lease_changed_nothing_and_runs_again(world: World) -> None:
    # Retryable at the finish alone, so its derived id runs once the holder asks.
    document_id = world.document()
    saved = world.done("document.save", world.save_args(document_id))
    body = world.failure("document.save_finish", world.finish_args(saved), B)
    assert body["code"] == "DOCUMENT_IN_USE" and body["retryable"] is True
    assert _outcome(body) == NOT_APPLIED and body["details"]["holder_pid"] == A["pid"]
    assert Path(saved["written"]).exists() and not (world.saves / "hero-r02.kra").exists()
    world.done("document.save_finish", world.finish_args(saved))
    assert (world.saves / "hero-r02.kra").exists()


def test_a_duplicate_refused_for_its_format_changed_nothing(world: World) -> None:
    body = world.failure("document.duplicate", world.save_args(world.document(), "hero-b.ora"))
    assert body["code"] == "UNSUPPORTED_CAPABILITY" and _outcome(body) == NOT_APPLIED
    assert not world.saves.exists()


def test_a_duplicate_open_refused_at_job_start_runs_again_under_its_id(world: World) -> None:
    # Sent under an id derived from the duplicate's, it must run once the dialog is closed.
    saved = world.done("document.duplicate", world.save_args(world.document(), "hero-b.kra"))
    world.done("document.save_finish", world.finish_args(saved))
    args = {"document_id": saved["document_id"], "save_id": saved["save_id"]}
    world.port.refuse = BridgeError("KRITA_MODAL_DIALOG", "A dialog is open.", True)
    world.jobs.submit("op-open", "req-open", "document.duplicate_open", args, A)
    world.jobs.drain()
    refused = world.jobs.wait("op-open", 0)
    assert refused is not None and refused["status"] == "error"
    assert refused["error"]["retryable"] is True and _outcome(refused["error"]) == NOT_APPLIED
    world.port.refuse = None
    world.jobs.submit("op-open", "req-open", "document.duplicate_open", args, A)
    world.jobs.drain()
    again = world.jobs.wait("op-open", 0)
    assert again is not None and again["status"] == "done"


# Each op, past its marker: only a verified cleanup or rollback proves it changed nothing.


def test_a_duplicate_open_that_closed_its_branch_states_it_and_keeps_the_file(
    world: World,
) -> None:
    # Its own statement; the server never lets it stand for the duplicate as a whole.
    saved = world.done("document.duplicate", world.save_args(world.document(), "hero-b.kra"))
    world.done("document.save_finish", world.finish_args(saved))
    args = {"document_id": saved["document_id"], "save_id": saved["save_id"]}
    world.port.fail["tree"] = BridgeError("IO_ERROR", "tree failed")
    body = world.failure("document.duplicate_open", args)
    del world.port.fail["tree"]
    assert _outcome(body) == NOT_APPLIED and body["details"]["rollback_verified"] is True
    assert (world.saves / "hero-b.kra").exists()


def test_a_duplicate_open_that_failed_past_its_marker_never_runs_again(world: World) -> None:
    # Only a retryable refusal reruns a derived id; this failure is the answer for good.
    saved = world.done("document.duplicate", world.save_args(world.document(), "hero-b.kra"))
    world.done("document.save_finish", world.finish_args(saved))
    args = {"document_id": saved["document_id"], "save_id": saved["save_id"]}
    world.port.fail["tree"] = BridgeError("IO_ERROR", "tree failed")
    world.jobs.submit("op-open", "req-open", "document.duplicate_open", args, A)
    world.jobs.drain()
    del world.port.fail["tree"]
    opened = len(world.port.opened)
    world.jobs.submit("op-open", "req-open", "document.duplicate_open", args, A)
    world.jobs.drain()
    again = world.jobs.wait("op-open", 0)
    assert again is not None and again["status"] == "error"
    assert len(world.port.opened) == opened


def test_a_duplicate_open_that_keeps_its_branch_is_uncertain(world: World) -> None:
    saved = world.done("document.duplicate", world.save_args(world.document(), "hero-b.kra"))
    world.done("document.save_finish", world.finish_args(saved))
    args = {"document_id": saved["document_id"], "save_id": saved["save_id"]}
    world.port.close_works = False
    world.port.fail["tree"] = BridgeError("IO_ERROR", "tree failed")
    body = world.failure("document.duplicate_open", args)
    del world.port.fail["tree"]
    kept = world.registry.find(body["details"]["document_id"])
    assert _outcome(body) == UNCERTAIN and kept.unsafe and kept.owned


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
    # Its file is gone, yet removing it cannot move the document back: nothing is verified.
    assert _outcome(body) == UNCERTAIN and body["details"]["rollback_verified"] is False
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


@pytest.mark.parametrize(
    ("raised", "unsafe"),
    [(BridgeError("INTERNAL_ERROR", "No."), False), (RuntimeError("Krita raised."), True)],
    ids=["its-own-error", "anything-else"],
)
def test_a_selection_that_raised_past_its_marker_is_unsafe_unless_it_said_why(
    world: World, raised: BaseException, unsafe: bool
) -> None:
    document_id = world.document()
    world.port.fail["set_selection"] = raised
    body = world.failure("selection.set", world.selection_args(document_id, "all"))
    handle = world.registry.find(document_id)
    assert _outcome(body) == UNCERTAIN and handle.unsafe is unsafe
    assert handle.ledger.undo_available() == 0


@pytest.mark.parametrize("where", ["global", "local"])
def test_k46_moving_the_active_node_off_a_selection_mask_is_no_change(
    world: World, where: str
) -> None:
    # Like the brush, the current node is window state the reads need, set before the marker.
    document_id = world.document()
    tree = world.port._tree(1)
    parent = tree["root_id"] if where == "global" else BASE
    world.port.mask(1, parent)
    world.done("paint.stroke", world.stroke_args(document_id))
    world.port.mask(1, parent)
    world.port.brush_drift = {"size_px": 99}
    body = world.failure("paint.stroke", world.stroke_args(document_id))
    assert body["code"] == "INTERNAL_ERROR" and _outcome(body) == NOT_APPLIED
    assert tree["active_id"] == (PAINT if where == "global" else BASE)


def test_the_fake_lets_only_k46_s_activation_pass_before_a_marker(world: World) -> None:
    document_id = world.document()
    world.port.mask(1, BASE)
    document = world.registry.find(document_id).document
    world.port.bring_forward(document)
    world.port.marker = Call("op-x", "req-x", A)
    try:
        world.port.activate(document, BASE)
        world.port.mask(1, BASE)
        with pytest.raises(AssertionError):
            world.port.activate(document, PAINT)
    finally:
        world.port.marker = None


def test_a_layer_krita_refused_is_confirmed_not_applied(world: World) -> None:
    document_id = world.document()
    world.port.fail["create_layer"] = BridgeError("INTERNAL_ERROR", "Krita did not add the layer.")
    body = world.failure("layer.create", world.layer_args(document_id))
    assert body["details"]["rolled_back"] is False and body["details"]["rollback_verified"] is True
    assert _outcome(body) == NOT_APPLIED


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


def test_a_reorder_krita_refused_between_its_steps_is_not_applied(world: World) -> None:
    document_id = world.document()
    group = world.done("layer.create", world.layer_args(document_id, type="group"))["layer_id"]
    world.port.fail["attach"] = BridgeError("INTERNAL_ERROR", "Krita did not add the layer.")
    move = {"document_id": document_id, "layer_id": PAINT, "parent_id": group, "above_id": None}
    body = world.failure("layer.reorder", move)
    assert body["details"]["rolled_back"] is True and body["details"]["rollback_verified"] is True
    assert _outcome(body) == NOT_APPLIED


def test_a_removal_that_could_not_be_undone_is_uncertain(world: World) -> None:
    document_id = world.document()
    world.port.fail["remove_node_after"] = RuntimeError("libkis failed")
    world.port.undo_works = False
    removal = {"document_id": document_id, "layer_id": PAINT, "verify": "full"}
    body = world.failure("layer.remove", removal)
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
    allowed = bytearray(WIDTH * HEIGHT)
    for row in range(40, 80):
        allowed[row * WIDTH + 20 : row * WIDTH + 80] = b"\xff" * 60
    world.registry.find(document_id).allowed_mask = bytes(allowed)
    world.port.stray = [{"x": 100, "y": 100, "width": 4, "height": 4}]
    args = world.stroke_args(document_id, verify="full")
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


def test_an_unnamed_step_krita_did_not_take_stays_retryable(world: World) -> None:
    # A translate's params step has no label, and Krita keeps Redo enabled with nothing to redo,
    # so its text names no step either: only the state tells a step it did not take from one it
    # moved for someone else.
    document_id = world.document()
    _painted(world)
    world.done("layer.transform", world.translate_args(document_id, [3, 0]))
    handle = world.registry.find(document_id)
    handle.dirty = False
    world.port.undo_works = False
    # A first translate's two steps move together, so both are asked for.
    whole = {"document_id": document_id, "action": "undo", "steps": 2}
    body = world.failure("history.step", whole)
    assert body["retryable"] is True and _outcome(body) == NOT_APPLIED
    assert handle.ledger.undo_available() > 0 and not handle.unsafe


def test_a_step_of_the_same_name_not_the_bridges_stops_history_without_a_retry(
    world: World,
) -> None:
    # A step named as the bridge's, made over another layer: the undo moved it, the witness
    # showed the bridge's stroke still there, so history stops rather than ask for a retry.
    document_id = world.document()
    world.done("paint.stroke", world.stroke_args(document_id))
    handle = world.registry.find(document_id)
    before = world.port._state(1)
    world.port.buffers[BASE][0:4] = bytes([1, 2, 3, 255])
    world.port._push(1, history.LABELS["paint.stroke"][0], before)
    body = world.failure("history.step", world.history_args(document_id))
    assert body["code"] == "INVALID_ARGUMENT" and body["retryable"] is False
    assert handle.ledger.undo_available() == 0 and not handle.unsafe


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
    assert body["details"]["rollback_verified"] is False


def test_a_save_whose_read_raised_and_stayed_open_is_no_clean_rollback(world: World) -> None:
    document_id = world.document()
    world.port.close_works = False
    refused = BridgeError("BUSY", "Retry.", True)
    world.port.on_open.append(lambda: world.port.fail.update(composite=refused))
    body = world.failure("document.save", world.save_args(document_id))
    del world.port.fail["composite"]
    assert body["details"]["rollback_verified"] is False and body["retryable"] is False
    assert _outcome(body) == UNCERTAIN


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
    # Every raise whose retryable flag is true or computed, by position or by keyword; a
    # computed one is named so, since only its own test says when it is true.
    found = []
    for path in sorted(PLUGIN.rglob("*.py")):
        where = path.relative_to(PLUGIN).as_posix()
        if where == "bridge_core/errors.py":
            # The constructor and error() pass the flag through.
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not _makes_an_error(node.func):
                continue
            flag = node.args[2] if len(node.args) >= 3 else None
            for keyword in node.keywords:
                if keyword.arg == "retryable":
                    flag = keyword.value
            if flag is None or (isinstance(flag, ast.Constant) and not flag.value):
                continue
            code = ast.literal_eval(node.args[0])
            computed = "" if isinstance(flag, ast.Constant) else " (computed)"
            found.append((where, code + computed))
    return found


def _makes_an_error(func: ast.expr) -> bool:
    # BridgeError however it is reached, and errors.error by name; never a logger's error().
    if isinstance(func, ast.Name):
        return func.id in ("BridgeError", "error")
    return isinstance(func, ast.Attribute) and func.attr == "BridgeError"


def test_every_retryable_raise_is_one_this_file_answers_for() -> None:
    assert _retryable_raises() == RETRYABLE


def test_a_name_collision_is_retryable_and_changed_nothing(world: World) -> None:
    world.work.mkdir()
    taken = world.work / files.copy_name("hero.kra", NOW)
    taken.write_bytes(b"someone's work")
    ops = opening.handlers(world.registry, world.port, world.data, now=lambda: NOW)
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


def test_a_second_save_inherits_the_folder_the_first_one_made(world: World) -> None:
    saved = world.saved()
    again = world.done("document.save", world.save_args(saved["document_id"], "other.kra"))
    assert not os.path.lexists(saved["written"]) and world.saves.is_dir()
    args = world.finish_args(again, merged_sha256="0" * 64)
    body = world.failure("document.save_finish", args)
    assert _outcome(body) == NOT_APPLIED and not world.saves.exists()


def test_a_hidden_file_that_stays_after_placing_is_logged(
    world: World, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    saved = world.saved()
    caplog.set_level(logging.WARNING, logger=log.NAME)
    logging.getLogger(log.NAME).propagate = True
    monkeypatch.setattr(files, "remove", lambda path: False)
    finished = world.done("document.save_finish", world.finish_args(saved))
    assert finished["dirty_cleared"] is True
    assert any("hidden file stayed" in record.getMessage() for record in caplog.records)


@pytest.mark.parametrize("deeper", [False, True], ids=["itself", "above it"])
def test_a_file_in_the_folders_path_is_an_ordinary_refusal(world: World, deeper: bool) -> None:
    (world.art / "taken").write_bytes(b"a file")
    folder = world.art / "taken"
    args = world.open_args(working_dir=str(folder / "work" if deeper else folder))
    body = world.failure("document.open", args)
    assert body["code"] == "IO_ERROR" and _outcome(body) == NOT_APPLIED
    assert (world.art / "taken").read_bytes() == b"a file"


def test_a_save_under_a_file_is_an_ordinary_refusal(world: World) -> None:
    (world.art / "taken").write_bytes(b"a file")
    args = {"document_id": world.document(), "path": str(world.art / "taken" / "hero.kra")}
    body = world.failure("document.save", args)
    assert body["code"] == "IO_ERROR" and _outcome(body) == NOT_APPLIED


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
