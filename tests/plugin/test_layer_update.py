import hashlib
import itertools
import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from bridge_core import documents, harness, history, verification
from bridge_core.errors import BridgeError
from bridge_core.jobs import Call
from bridge_core.registry import Handle, Registry
from fake_krita import FakePort, fake_node, layer_id

A: dict[str, Any] = {"pid": 101, "started_at": "Sun Oct 25 10:00:00 2026"}
CREATE = {
    "name": "sketch",
    "size_px": [8, 4],
    "color_model": "RGBA",
    "depth": "U8",
    "profile_id": documents.SRGB_PROFILE,
    "background": "transparent",
}
BASE, PAINT, GROUP, INNER, FREE = (layer_id(1, index) for index in range(5))


def _box(x: int, y: int, width: int, height: int) -> dict[str, int]:
    return {"x": x, "y": y, "width": width, "height": height}


class World:
    def __init__(self, tmp: Path) -> None:
        self.data = tmp / "data"
        (self.data / "harness").mkdir(parents=True)
        (tmp / "art").mkdir()
        roots = {"v": 1, "roots": [os.path.realpath(tmp / "art")]}
        (self.data / "config.json").write_text(json.dumps(roots))
        self.port = FakePort()
        self.registry = Registry(self.port, lambda client: True)
        self.ops = {
            **documents.handlers(self.registry, self.port, self.data),
            **harness.handlers(self.registry, self.port, self.data),
        }
        self.ids = itertools.count(1)
        # Bumps one pixel at every redraw, so a restore can never be confirmed.
        self.drift: Iterator[int] | None = None

    def run(self, op: str, args: dict[str, Any], request_id: str = "") -> dict[str, Any]:
        number = next(self.ids)
        call = Call(f"op-{number:032x}", request_id or f"req-{number}", A)
        return self.ops[op](args, call)

    def refused(self, op: str, args: dict[str, Any], request_id: str = "") -> dict[str, Any]:
        with pytest.raises(BridgeError) as raised:
            self.run(op, args, request_id)
        body: dict[str, Any] = raised.value.body
        return body

    def document(self) -> tuple[str, Handle]:
        # A protected base, an editable paint layer over it, a group holding a protected layer,
        # and an empty editable group; the composite is rendered from the tree.
        document_id = self.run("document.create", CREATE)["document_id"]
        handle = self.registry.find(document_id)
        tree = self.port._tree(1)
        root = tree["root_id"]
        tree["nodes"] = [
            fake_node(1, 0, "base", root, 0, bounds_px=_box(0, 0, 6, 4)),
            fake_node(1, 1, "paint", root, 1, bounds_px=_box(0, 0, 4, 4)),
            fake_node(1, 2, "group", root, 2, type="grouplayer"),
            fake_node(1, 3, "inner", GROUP, 0),
            fake_node(1, 4, "free", root, 3, type="grouplayer"),
        ]
        tree["active_id"] = BASE
        handle.protected = {BASE, INNER}
        self.port.render[1] = self.render
        return document_id, handle

    def render(self, tree: dict[str, Any]) -> bytes:
        nodes = {node["name"]: node for node in tree["nodes"]}
        base, paint = nodes["base"], nodes.get("paint") or nodes["renamed"]
        box = paint["bounds_px"]
        out = bytearray()
        for y in range(4):
            for x in range(8):
                alpha = 255 if x < 6 else 0
                pixel = [base["opacity"] // 2, 20, 30, alpha]
                inside = box["x"] <= x < box["x"] + box["width"]
                if paint["visible"] and inside and box["y"] <= y < box["y"] + box["height"]:
                    pixel = [
                        paint["opacity"],
                        len(paint["blend_mode"]),
                        40 + paint["inherit_alpha"],
                        alpha if paint["inherit_alpha"] else 255,
                    ]
                out += bytes(pixel)
        if self.drift is not None:
            out[0] = next(self.drift) % 256
        return bytes(out)

    def paint(self) -> dict[str, Any]:
        found: dict[str, Any] = self.port._tree(1)["nodes"][1]
        return found

    def update(
        self, document_id: str, layer: str = PAINT, verify: str = "region", **properties: Any
    ) -> dict[str, Any]:
        args = {
            "document_id": document_id,
            "layer_id": layer,
            "properties": properties,
            "verify": verify,
        }
        return self.run("layer.update", args)

    def update_refused(
        self, document_id: str, layer: str = PAINT, verify: str = "region", **properties: Any
    ) -> dict[str, Any]:
        args = {
            "document_id": document_id,
            "layer_id": layer,
            "properties": properties,
            "verify": verify,
        }
        return self.refused("layer.update", args)

    def allow(self, document_id: str, rect: dict[str, int] | None, preserve: bool = False) -> None:
        handle = self.registry.find(document_id)
        value = None
        request_id = f"req-protect-{next(self.ids)}"
        if rect is not None:
            data = b"\xff" * (rect["width"] * rect["height"])
            folder = self.data / "transfer"
            folder.mkdir(exist_ok=True)
            digest = hashlib.sha256(data).hexdigest()
            key = hashlib.sha256(request_id.encode()).hexdigest()[:16]
            path = folder / f"mask-{key}-{digest}.a8"
            path.write_bytes(data)
            spec = {
                "path": str(path),
                "size_px": [rect["width"], rect["height"]],
                "format": "A8",
                "sha256": digest,
            }
            value = {"origin_px": [rect["x"], rect["y"]], "mask": spec, "source_path": None}
        args = {
            "document_id": document_id,
            "protected_layer_ids": sorted(handle.protected),
            "allowed_change_mask": value,
            "preserve_composite_alpha": preserve,
            "preserve_canvas": False,
        }
        self.run("protection.set", args, request_id)


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


def _spec_bytes(spec: dict[str, Any]) -> bytes:
    return Path(spec["path"]).read_bytes()


# What a change does.


def test_a_property_is_set_reported_and_verified_over_the_layer(world: World) -> None:
    document_id, handle = world.document()
    done = world.update(document_id, opacity=0.5)
    assert done["effective_properties"] == {"opacity": 128 / 255}
    assert (done["undoable"], done["undo_steps"]) == ([], 0)
    checked = done["verification"]
    assert (checked["mode"], checked["rect"]) == ("region", _box(0, 0, 4, 4))
    assert (checked["changed_px"], checked["changed_outside_px"]) == (16, 0)
    assert checked["changed_bounds_px"] == _box(0, 0, 4, 4)
    assert checked["diff"] is None
    assert _spec_bytes(checked["after"])[:4] == bytes([128, 6, 40, 255])
    assert _spec_bytes(checked["before"])[:4] == bytes([255, 6, 40, 255])
    assert world.paint()["opacity"] == 128 and handle.dirty


@pytest.mark.parametrize(("given", "applied"), [(0.5, 128), (0.002, 1), (1, 255), (0, 0)])
def test_opacity_rounds_half_up_to_krita_s_0_to_255(
    world: World, given: float, applied: int
) -> None:
    document_id, _ = world.document()
    done = world.update(document_id, opacity=given)
    assert world.paint()["opacity"] == applied
    assert done["effective_properties"]["opacity"] == applied / 255


def test_a_blend_change_is_one_undo_step_history_can_take_back(world: World) -> None:
    document_id, handle = world.document()
    done = world.update(document_id, blend_mode="multiply", opacity=0.5)
    assert (done["undoable"], done["undo_steps"]) == (["blend_mode"], 1)
    [step] = handle.ledger.steps
    assert (step.op, step.label) == ("layer.update", history.LABELS["layer.update"])
    assert step.region == _box(0, 0, 4, 4)
    assert step.before != step.after
    undone = world.run("history.step", {"document_id": document_id, "action": "undo", "steps": 1})
    assert undone["verified"] and world.paint()["blend_mode"] == "normal"
    # Only the blend is history's: opacity stays where the call put it.
    assert world.paint()["opacity"] == 128
    world.run("history.step", {"document_id": document_id, "action": "redo", "steps": 1})
    assert world.paint()["blend_mode"] == "multiply"


def test_a_blend_change_made_in_krita_is_told_from_the_bridges_by_state(world: World) -> None:
    document_id, handle = world.document()
    world.update(document_id, blend_mode="multiply")
    # The owner changes another layer's blend by hand: Krita names it the same.
    world.port.set_blend(handle.document, FREE, "screen")
    body = world.refused("history.step", {"document_id": document_id, "action": "undo", "steps": 1})
    assert body["code"] == "INVALID_ARGUMENT"
    assert world.port._tree(1)["nodes"][4]["blend_mode"] == "screen"


def test_only_making_a_layer_active_leaves_the_document_clean(world: World) -> None:
    document_id, handle = world.document()
    world.port.calls.clear()
    done = world.update(document_id, active=True)
    assert done["effective_properties"] == {"active": True}
    assert world.port._tree(1)["active_id"] == PAINT
    assert done["verification"] is None and not handle.dirty
    assert handle.changed_at is not None and "refresh" not in world.port.calls
    world.update(document_id, active=True, name="renamed")
    assert handle.dirty


@pytest.mark.parametrize(
    "properties", [{"name": "renamed"}, {"locked": True}, {"alpha_locked": True}]
)
def test_a_property_that_leaves_the_composite_alone_reads_nothing(
    world: World, properties: dict[str, Any]
) -> None:
    document_id, handle = world.document()
    world.port.calls.clear()
    done = world.update(document_id, **properties)
    assert done["verification"] is None and done["effective_properties"] == properties
    assert "read" not in world.port.calls and "refresh" not in world.port.calls
    assert handle.dirty


def test_an_unchanged_value_writes_nothing_and_still_counts_as_a_change(world: World) -> None:
    document_id, handle = world.document()
    world.port.calls.clear()
    done = world.update(document_id, opacity=1, visible=True)
    assert done["verification"] is None and done["undo_steps"] == 0
    assert "properties" not in world.port.calls and handle.dirty


@pytest.mark.parametrize(
    ("properties", "reads"),
    [
        ({"name": "renamed"}, 2),
        ({"blend_mode": "multiply"}, 3),
        ({"blend_mode": "multiply", "name": "renamed"}, 3),
        ({"blend_mode": "multiply", "active": True}, 4),
    ],
)
def test_an_update_reads_the_tree_once_per_phase(
    world: World, monkeypatch: pytest.MonkeyPatch, properties: dict[str, Any], reads: int
) -> None:
    document_id, _ = world.document()
    real = world.port.tree
    seen: list[Any] = []

    def counting(document: Any) -> dict[str, Any]:
        seen.append(document)
        return real(document)

    monkeypatch.setattr(world.port, "tree", counting)
    world.update(document_id, **properties)
    # Each composite read checks the tree for K46 on its own, before and after an appearance.
    appearance = 2 if "blend_mode" in properties else 0
    assert len(seen) == reads + appearance


def test_a_blend_change_is_checked_for_what_the_recompose_moved(world: World) -> None:
    document_id, _ = world.document()
    real = world.port.refresh
    refreshes: list[Any] = []

    def moving(document: Any) -> None:
        real(document)
        refreshes.append(document)
        # The first recompose comes before the change, the second after it.
        if len(refreshes) == 2:
            world.port._tree(1)["nodes"][-1]["offset_px"] = [5, 5]

    world.port.refresh = moving  # type: ignore[method-assign]
    body = world.update_refused(document_id, blend_mode="multiply")
    assert body["code"] == "ROLLBACK_FAILED" and body["details"]["cause"] == "INTERNAL_ERROR"
    assert body["details"]["layer_ids"]


# Refusals, before anything changes.


@pytest.mark.parametrize(
    ("layer", "properties", "code"),
    [
        (BASE, {"opacity": 0.5}, "LOCKED_TARGET"),
        (GROUP, {"visible": False}, "LOCKED_TARGET"),
        (GROUP, {"active": True}, "LOCKED_TARGET"),
        (FREE, {"alpha_locked": True}, "INVALID_ARGUMENT"),
        (layer_id(1, 99), {"opacity": 0.5}, "LAYER_NOT_FOUND"),
        ("root-1", {"opacity": 0.5}, "INVALID_ARGUMENT"),
    ],
)
def test_a_target_agents_may_not_change_is_refused(
    world: World, layer: str, properties: dict[str, Any], code: str
) -> None:
    document_id, handle = world.document()
    world.port.calls.clear()
    assert world.update_refused(document_id, layer, **properties)["code"] == code
    assert not handle.dirty and "properties" not in world.port.calls


def test_a_mask_and_the_root_are_not_layers_to_change(world: World) -> None:
    document_id, _ = world.document()
    mask = world.port.mask(1, PAINT)
    assert world.update_refused(document_id, mask, opacity=0.5)["code"] == "INVALID_ARGUMENT"
    tree = world.port._tree(1)
    tree["root_id"] = layer_id(1, 50)
    for node in tree["nodes"]:
        if node["parent_id"] == "root-1":
            node["parent_id"] = layer_id(1, 50)
    body = world.update_refused(document_id, layer_id(1, 50), opacity=0.5)
    assert body["code"] == "INVALID_ARGUMENT"


@pytest.mark.parametrize(
    ("properties", "verify"),
    [
        ({}, "region"),
        ({"colour": 1}, "region"),
        ({"opacity": 1.5}, "region"),
        ({"opacity": True}, "region"),
        ({"opacity": float("nan")}, "region"),
        ({"blend_mode": "dissolve"}, "region"),
        ({"active": False}, "region"),
        ({"name": ""}, "region"),
        ({"visible": 1}, "region"),
        ({"opacity": 0.5}, "partial"),
    ],
)
def test_malformed_arguments_are_refused(
    world: World, properties: dict[str, Any], verify: str
) -> None:
    document_id, _ = world.document()
    body = world.update_refused(document_id, PAINT, verify, **properties)
    assert body["code"] == "INVALID_ARGUMENT"


def test_a_spreading_node_refuses_region_before_any_change_and_full_passes(world: World) -> None:
    document_id, handle = world.document()
    tree = world.port._tree(1)
    tree["nodes"].append(fake_node(1, 5, "blur", tree["root_id"], 4, type="filterlayer"))
    world.port.calls.clear()
    body = world.update_refused(document_id, opacity=0.5)
    assert body["code"] == "UNSUPPORTED_CAPABILITY"
    assert body["details"]["reasons"] == [{"reason": "filter_layer", "node_id": layer_id(1, 5)}]
    assert not handle.dirty and "properties" not in world.port.calls
    done = world.update(document_id, PAINT, "full", opacity=0.5)
    assert done["verification"]["rect"] == _box(0, 0, 8, 4)


def test_full_scope_reads_no_layer_styles_or_clones(world: World) -> None:
    document_id, _ = world.document()
    world.port.reach[1] = {"styled": [PAINT], "clones": {}, "animated": False}
    world.port.calls.clear()
    world.update(document_id, PAINT, "full", opacity=0.5)
    assert "effects False" in world.port.calls and "effects True" not in world.port.calls


def test_an_animated_document_is_refused_in_either_mode(world: World) -> None:
    document_id, handle = world.document()
    world.port.reach[1] = {"styled": [], "clones": {}, "animated": True}
    for verify in ("region", "full"):
        body = world.update_refused(document_id, PAINT, verify, opacity=0.5)
        assert body["code"] == "UNSUPPORTED_CAPABILITY"
    assert not handle.dirty and world.paint()["opacity"] == 255


# Rollbacks.


def test_a_leak_is_restored_confirmed_and_refused(world: World) -> None:
    document_id, handle = world.document()
    world.allow(document_id, _box(0, 0, 2, 4))
    body = world.update_refused(document_id, opacity=0.5)
    assert (body["code"], body["retryable"]) == ("PROTECTED_REGION_CHANGED", False)
    details = body["details"]
    assert (details["rolled_back"], details["rollback_verified"]) == (True, True)
    checked = details["verification"]
    assert (checked["changed_px"], checked["changed_outside_px"]) == (16, 8)
    # The counts have one home.
    assert "changed_outside_px" not in details and "alpha_changed_px" not in details
    assert checked["after"] is None and checked["before"] is not None
    flags = _spec_bytes(checked["diff"])
    assert flags.count(verification.CHANGED | verification.OUTSIDE) == 8
    assert world.paint()["opacity"] == 255
    assert not handle.dirty and not handle.unsafe


def test_an_alpha_change_is_refused_under_preserve_composite_alpha(world: World) -> None:
    # The recolour recipe: a hidden layer spilling past the silhouette shows only with
    # inherit_alpha on.
    document_id, _ = world.document()
    world.paint().update(bounds_px=_box(4, 0, 4, 4), visible=False)
    world.allow(document_id, None, preserve=True)
    body = world.update_refused(document_id, visible=True)
    assert body["code"] == "PROTECTED_REGION_CHANGED"
    assert body["details"]["verification"]["alpha_changed_px"] == 8
    assert world.paint()["visible"] is False
    done = world.update(document_id, visible=True, inherit_alpha=True)
    checked = done["verification"]
    assert (checked["changed_px"], checked["alpha_changed_px"]) == (16, 0)


def test_a_leaking_blend_change_is_undone_natively_and_never_redone(world: World) -> None:
    document_id, handle = world.document()
    world.allow(document_id, _box(0, 0, 2, 4))
    body = world.update_refused(document_id, blend_mode="multiply")
    assert body["details"]["rollback_verified"] is True
    assert world.paint()["blend_mode"] == "normal" and handle.ledger.steps == []
    # Krita keeps the undone step as a redo (K43); history never offers it.
    assert world.port.undo_labels(handle.document)[1] == history.LABELS["layer.update"]
    redo = world.refused("history.step", {"document_id": document_id, "action": "redo", "steps": 1})
    assert redo["code"] == "INVALID_ARGUMENT"


def test_a_restore_that_cannot_be_confirmed_marks_the_document_unsafe(world: World) -> None:
    document_id, handle = world.document()
    world.allow(document_id, _box(0, 0, 2, 4))
    world.drift = itertools.count()
    body = world.update_refused(document_id, opacity=0.5)
    assert body["code"] == "ROLLBACK_FAILED"
    assert body["details"]["cause"] == "PROTECTED_REGION_CHANGED"
    assert (body["details"]["rolled_back"], body["details"]["rollback_verified"]) == (True, False)
    assert handle.unsafe and handle.dirty
    world.drift = None
    assert world.update_refused(document_id, opacity=1)["code"] == "DOCUMENT_UNSAFE"


def test_a_blend_undo_krita_does_not_take_marks_the_document_unsafe(world: World) -> None:
    document_id, handle = world.document()
    world.allow(document_id, _box(0, 0, 2, 4))
    world.port.undo_works = False
    body = world.update_refused(document_id, blend_mode="multiply", opacity=0.5)
    assert body["code"] == "ROLLBACK_FAILED"
    assert body["details"]["rolled_back"] is False and handle.unsafe


@pytest.mark.parametrize(
    ("raised", "code"),
    [
        (RuntimeError("Krita raised"), "INTERNAL_ERROR"),
        (BridgeError("IO_ERROR", "a retryable failure", True), "IO_ERROR"),
    ],
)
def test_a_change_that_raises_is_restored_and_never_retryable(
    world: World, raised: BaseException, code: str
) -> None:
    document_id, handle = world.document()
    calls = itertools.count()

    def once(tree: dict[str, Any]) -> None:
        if next(calls) == 0:
            raise raised

    world.port.on_properties.append(once)
    body = world.update_refused(document_id, opacity=0.5, visible=False)
    assert (body["code"], body["retryable"]) == (code, False)
    assert (body["details"]["rolled_back"], body["details"]["rollback_verified"]) == (True, True)
    assert (world.paint()["opacity"], world.paint()["visible"]) == (255, True)
    assert not handle.dirty and not handle.unsafe


def test_a_rollback_that_raises_marks_the_document_unsafe(world: World) -> None:
    document_id, handle = world.document()

    def always(tree: dict[str, Any]) -> None:
        raise RuntimeError("Krita raised")

    world.port.on_properties.append(always)
    body = world.update_refused(document_id, opacity=0.5)
    assert body["code"] == "ROLLBACK_FAILED" and body["details"]["cause"] == "INTERNAL_ERROR"
    assert handle.unsafe and handle.dirty


@pytest.mark.parametrize(
    ("step", "raised"),
    [
        ("set_properties", KeyboardInterrupt()),
        ("set_properties", SystemExit()),
        ("set_blend", KeyboardInterrupt()),
    ],
)
def test_an_interrupt_mid_change_seals_history_and_marks_the_document_unsafe(
    world: World, step: str, raised: BaseException
) -> None:
    document_id, handle = world.document()
    world.update(document_id, blend_mode="multiply")
    world.port.fail[step] = raised
    with pytest.raises(type(raised)):
        world.update(document_id, opacity=0.5, blend_mode="screen")
    assert handle.unsafe and handle.dirty and handle.ledger.undo_available() == 0
    del world.port.fail[step]
    assert world.update_refused(document_id, opacity=1)["code"] == "DOCUMENT_UNSAFE"


def test_an_interrupt_in_an_update_that_writes_nothing_leaves_the_document_safe(
    world: World,
) -> None:
    document_id, handle = world.document()
    tree, reads = world.port.tree, itertools.count(1)

    def read(document: Any) -> dict[str, Any]:
        # The second read is the one after the (absent) write.
        if next(reads) == 2:
            raise KeyboardInterrupt
        return tree(document)

    world.port.tree = read  # type: ignore[method-assign]
    with pytest.raises(KeyboardInterrupt):
        world.update(document_id, active=True)
    assert not handle.unsafe and handle.ledger.undo_available() == handle.ledger.applied


def test_an_interrupt_in_the_rollback_marks_the_document_unsafe(world: World) -> None:
    document_id, handle = world.document()
    world.allow(document_id, _box(0, 0, 2, 4))
    calls = itertools.count()

    def restore_interrupted(tree: dict[str, Any]) -> None:
        if next(calls) == 1:
            raise KeyboardInterrupt

    world.port.on_properties.append(restore_interrupted)
    with pytest.raises(KeyboardInterrupt):
        world.update(document_id, opacity=0.5)
    assert handle.unsafe and handle.dirty


def test_a_value_krita_applied_otherwise_is_rolled_back(world: World) -> None:
    document_id, handle = world.document()

    def adjusted(tree: dict[str, Any]) -> None:
        if tree["nodes"][1]["opacity"] == 128:
            tree["nodes"][1]["opacity"] = 127

    world.port.on_properties.append(adjusted)
    body = world.update_refused(document_id, opacity=0.5)
    assert body["code"] == "INTERNAL_ERROR" and body["details"]["layer_ids"] == [PAINT]
    assert body["details"]["rollback_verified"] is True
    assert world.paint()["opacity"] == 255 and not handle.dirty


# Reads.


def test_the_projection_is_refreshed_before_the_first_read_and_after_the_change(
    world: World,
) -> None:
    document_id, _ = world.document()
    world.paint().update(bounds_px=_box(0, 0, 2, 4))
    world.allow(document_id, _box(0, 0, 2, 4))
    world.port.composite_rects(world.registry.find(document_id).document, [_box(0, 0, 8, 4)])
    # A write elsewhere that Krita has not drawn yet (K42) is not this change's leak.
    world.port._tree(1)["nodes"][0]["opacity"] = 100
    world.port.calls.clear()
    world.update(document_id, opacity=0.5)
    calls = [call for call in world.port.calls if call in ("refresh", "read", "properties")]
    assert calls == ["refresh", "read", "properties", "refresh", "read"]


def test_an_empty_layer_reads_nothing_and_changes_nothing(world: World) -> None:
    document_id, _ = world.document()
    world.paint().update(bounds_px=_box(0, 0, 0, 0))
    world.port.calls.clear()
    checked = world.update(document_id, opacity=0.5)["verification"]
    assert checked["rect"] == _box(0, 0, 0, 0) and checked["changed_px"] == 0
    assert (checked["before"], checked["after"]) == (None, None)
    assert "read" not in world.port.calls


def test_reads_take_a_layer_in_place_of_an_active_selection_mask(world: World) -> None:
    document_id, _ = world.document()
    world.port.mask(1, PAINT)
    world.port.calls.clear()
    world.update(document_id, opacity=0.5)
    assert world.port.calls.index("activate") < world.port.calls.index("read")
    assert not world.port.is_masked(1)


def test_a_scope_over_the_image_bound_still_reports_its_counts(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    document_id, _ = world.document()
    monkeypatch.setattr(verification, "MAX_IMAGE_PIXELS", 4)
    checked = world.update(document_id, opacity=0.5)["verification"]
    assert (checked["before"], checked["after"], checked["changed_px"]) == (None, None, 16)


def test_a_failed_activation_never_fails_a_verified_change(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    document_id, _ = world.document()

    def refuse(document: Any, node_id: str) -> None:
        raise BridgeError("INTERNAL_ERROR", "Krita did not activate it.")

    monkeypatch.setattr(world.port, "activate", refuse)
    done = world.update(document_id, opacity=0.5, active=True)
    assert done["effective_properties"] == {"opacity": 128 / 255, "active": False}
    assert world.update_refused(document_id, active=True)["code"] == "INTERNAL_ERROR"


# The harness's fixtures.


def _harness_document(world: World) -> str:
    source = world.data / "harness" / "fixture.ora"
    source.write_bytes(b"ora")
    args = {
        "source_path": str(source),
        "source_sha256": hashlib.sha256(b"ora").hexdigest(),
        "mode": "working_copy",
        "working_dir": str(world.data / "harness" / "work"),
        "editable_layer_ids": None,
        "editable_layer_names": None,
    }
    (world.data / "harness" / "work").mkdir()
    return str(world.run("document.open", args)["document_id"])


def test_the_harness_adds_each_spreading_node_and_seals_history(world: World) -> None:
    document_id = _harness_document(world)
    handle = world.registry.find(document_id)
    target = layer_id(1, 0)
    handle.protected = set()
    layer = {
        "document_id": document_id,
        "parent_id": "root-1",
        "above_id": None,
        "type": "paint",
        "coverage": None,
        "name": "repair",
    }
    world.run("layer.create", layer)
    assert handle.ledger.undo_available() == 1
    made = {}
    for kind in harness.NODE_KINDS:
        added = world.run(
            "harness.add_node", {"document_id": document_id, "kind": kind, "layer_id": target}
        )
        made[kind] = added["node_id"]
    nodes = {node["id"]: node for node in world.port._tree(1)["nodes"]}
    assert nodes[made["filter_layer"]]["parent_id"] == nodes[target]["parent_id"]
    assert nodes[made["filter_layer"]]["order"] == nodes[target]["order"] + 1
    assert nodes[made["filter_mask"]]["parent_id"] == target
    assert nodes[made["transform_mask"]]["type"] == "transformmask"
    assert handle.ledger.undo_available() == 0 and handle.changed_at is not None
    body = world.update_refused(document_id, target, opacity=0.5)
    reasons = {entry["reason"] for entry in body["details"]["reasons"]}
    assert reasons == {"filter_layer", "filter_mask", "transform_mask", "clone_layer"}


def test_the_harness_adds_nodes_only_to_its_own_documents(world: World) -> None:
    document_id = _harness_document(world)
    args = {"document_id": document_id, "kind": "blur", "layer_id": layer_id(1, 0)}
    assert world.refused("harness.add_node", args)["code"] == "INVALID_ARGUMENT"
    created = world.run("document.create", CREATE)["document_id"]
    args = {"document_id": created, "kind": "filter_layer", "layer_id": PAINT}
    assert world.refused("harness.add_node", args)["code"] == "PATH_NOT_ALLOWED"
