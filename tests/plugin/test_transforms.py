import hashlib
import itertools
import json
import os
from pathlib import Path
from typing import Any

import pytest
from bridge_core import documents, harness, history, ledger, nodes, translations
from bridge_core.errors import BridgeError
from bridge_core.jobs import Call
from bridge_core.layers import drift
from bridge_core.registry import Handle, Registry
from fake_krita import FRESH_TRANSFORM, UNREAD, FakePort, fake_node, layer_id

A: dict[str, Any] = {"pid": 101, "started_at": "Sun Oct 25 10:00:00 2026"}
CREATE = {
    "name": "stack",
    "size_px": [8, 4],
    "color_model": "RGBA",
    "depth": "U8",
    "profile_id": documents.SRGB_PROFILE,
    "background": "transparent",
}
BASE, PAINT, GROUP, INNER, HELD, LOOSE, GUARD, LOCKED = (layer_id(1, index) for index in range(8))
ROOT = "root-1"
OP = "layer.transform"
TRANSFORM = "transformmask"
# The params a rotation by Krita's transform tool would leave: no translate's.
ROTATED = FRESH_TRANSFORM.replace('<aZ value="0"', '<aZ value="0.5"')


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

    def run(self, op: str, args: dict[str, Any]) -> dict[str, Any]:
        number = next(self.ids)
        return self.ops[op](args, Call(f"op-{number:032x}", f"req-{number}", A))

    def refused(self, op: str, args: dict[str, Any]) -> dict[str, Any]:
        with pytest.raises(BridgeError) as raised:
            self.run(op, args)
        body: dict[str, Any] = raised.value.body
        return body

    def document(self) -> tuple[str, Handle]:
        # Bottom first: a protected base, a paint layer, a group holding one, a protected group
        # holding an unprotected layer, and a group holding a protected layer; the composite is
        # drawn from the tree, each layer moved by its and its groups' transform masks.
        document_id = self.run("document.create", CREATE)["document_id"]
        handle = self.registry.find(document_id)
        tree = self.port._tree(1)
        tree["nodes"] = [
            fake_node(1, 0, "base", ROOT, 0, bounds_px=_box(0, 0, 8, 4)),
            fake_node(1, 1, "paint", ROOT, 1, bounds_px=_box(1, 1, 2, 2)),
            fake_node(1, 2, "group", ROOT, 2, type="grouplayer"),
            fake_node(1, 3, "inner", GROUP, 0, bounds_px=_box(5, 0, 2, 2)),
            fake_node(1, 4, "held", ROOT, 3, type="grouplayer"),
            fake_node(1, 5, "loose", HELD, 0, bounds_px=_box(0, 3, 2, 1)),
            fake_node(1, 6, "guard", ROOT, 4, type="grouplayer"),
            fake_node(1, 7, "locked", GUARD, 0, bounds_px=_box(7, 3, 1, 1)),
        ]
        tree["active_id"] = PAINT
        for index, layer in enumerate((BASE, PAINT, INNER, LOOSE, LOCKED)):
            self.port.layer_pixels[layer] = bytes([30 * index + 5, 40, 90, 255])
        handle.protected = {BASE, HELD, LOCKED}
        self.port.render[1] = self.render
        return document_id, handle

    def render(self, tree: dict[str, Any]) -> bytes:
        found = {node["id"]: node for node in tree["nodes"]}
        below = nodes.children(tree)
        out = bytearray(bytes(4) * 32)

        def shift(node_id: str) -> tuple[int, int]:
            # Every transform mask on the node, then on each group holding it.
            x = y = 0
            current = node_id
            while current in found:
                for child in tree["nodes"]:
                    if child["parent_id"] == current and child["type"] == TRANSFORM:
                        moved = self.port.translation_of(1, child["id"]) or (0, 0)
                        x, y = x + moved[0], y + moved[1]
                current = found[current]["parent_id"]
            return x, y

        def draw(node_id: str, shown: bool) -> None:
            node = found[node_id]
            shown = shown and node["visible"]
            if shown and node["type"] == "paintlayer":
                box = node["bounds_px"]
                dx, dy = shift(node_id)
                pixel = self.port.layer_pixels.get(node_id, UNREAD)
                for y in range(box["y"] + dy, box["y"] + dy + box["height"]):
                    for x in range(box["x"] + dx, box["x"] + dx + box["width"]):
                        if 0 <= x < 8 and 0 <= y < 4:
                            out[(y * 8 + x) * 4 : (y * 8 + x) * 4 + 4] = pixel
            for child in below.get(node_id, []):
                draw(child, shown)

        for child in below.get(tree["root_id"], []):
            draw(child, True)
        return bytes(out)

    def tree(self) -> dict[str, Any]:
        found: dict[str, Any] = self.port.tree(self.port.documents()[0])
        return found

    def masks(self, layer: str) -> list[dict[str, Any]]:
        return [
            node
            for node in self.tree()["nodes"]
            if node["parent_id"] == layer and node["type"] == TRANSFORM
        ]

    def composite(self) -> bytes:
        self.port.refresh(self.port.documents()[0])
        found: bytes = self.port.composite(self.port.documents()[0])
        return found

    def pixel(self, x: int, y: int) -> bytes:
        return self.composite()[(y * 8 + x) * 4 : (y * 8 + x) * 4 + 4]

    def stack(self) -> list[str]:
        return [entry["label"] for entry in self.port.live[1].get("stack", [])]

    def allow(self, document_id: str, rect: dict[str, int]) -> None:
        handle = self.registry.find(document_id)
        data = b"\xff" * (rect["width"] * rect["height"])
        folder = self.data / "transfer"
        folder.mkdir(exist_ok=True)
        digest = hashlib.sha256(data).hexdigest()
        request_id = f"req-protect-{next(self.ids)}"
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
            "preserve_composite_alpha": False,
            "preserve_canvas": False,
        }
        call = Call(f"op-{next(self.ids):032x}", request_id, A)
        self.ops["protection.set"](args, call)

    def add_mask(self, layer: str, xml: str | None = None, **changes: Any) -> str:
        # A transform mask already in the document, as a file or an earlier session left it.
        tree = self.port._tree(1)
        order = sum(1 for node in tree["nodes"] if node["parent_id"] == layer)
        mask = fake_node(1, 40 + len(tree["nodes"]), "mask", layer, order, type=TRANSFORM)
        tree["nodes"].append({**mask, **changes})
        if xml is not None:
            self.port.transforms[(1, mask["id"])] = xml
        mask_id: str = mask["id"]
        return mask_id

    def history(self, document_id: str, action: str, steps: int) -> dict[str, Any]:
        args = {"document_id": document_id, "action": action, "steps": steps}
        return self.run("history.step", args)


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


def _translate(document_id: str, layer: str, by: Any) -> dict[str, Any]:
    return {
        "document_id": document_id,
        "layer_id": layer,
        "operation": {"type": "translate", "by_px": by},
    }


def _watched(tree: dict[str, Any]) -> dict[str, Any]:
    return {node["id"]: {**node, "bounds_px": None} for node in tree["nodes"]}


def _untouched(world: World, handle: Handle) -> None:
    # A refusal changed nothing: no step, no dirt, no mask.
    assert world.port.live[1].get("stack", []) == [] and not handle.dirty
    assert all(node["type"] != TRANSFORM for node in world.tree()["nodes"])


# The params.


def test_a_translate_writes_params_its_parse_reads_back() -> None:
    xml = translations.translate_xml(12, -4)
    assert translations.translation(xml) == (12, -4)
    assert translations.translation(FRESH_TRANSFORM) == (0, 0)


def test_the_parse_reads_krita_order_doctype_and_negative_zero() -> None:
    # Krita writes the attributes in a hash order that changes between sessions (measured).
    krita = (
        "<!DOCTYPE transform_params>\n<transform_params>\n"
        ' <main id="tooltransformparams"/>\n <data mode="0">\n  <free_transform>\n'
        '   <transformedCenter type="pointf" y="-4" x="12"/>\n'
        '   <originalCenter y="-0" type="pointf" x="0"/>\n'
        '   <rotationCenterOffset x="0" type="pointf" y="0"/>\n'
        '   <transformAroundRotationCenter type="value" value="0"/>\n'
        '   <aX value="0" type="value"/>\n   <aY type="value" value="0"/>\n'
        '   <aZ value="0" type="value"/>\n'
        '   <cameraPos z="1024" type="vector3d" x="0" y="0"/>\n'
        '   <scaleX value="1" type="value"/>\n   <scaleY type="value" value="1"/>\n'
        '   <shearX value="0" type="value"/>\n   <shearY value="0" type="value"/>\n'
        '   <boundsRotation value="0" type="value"/>\n'
        '   <keepAspectRatio type="value" value="0"/>\n'
        '   <flattenedPerspectiveTransform m33="1" m21="0" m22="1" m23="0" m11="1" m12="0"'
        ' m13="0" type="transform" m31="0" m32="0"/>\n'
        '   <filterId value="Bicubic" type="value"/>\n'
        "  </free_transform>\n </data>\n</transform_params>\n"
    )
    assert translations.translation(krita) == (12, -4)


@pytest.mark.parametrize(
    "xml",
    [
        ROTATED,
        FRESH_TRANSFORM.replace('mode="0"', 'mode="1"'),
        FRESH_TRANSFORM.replace("tooltransformparams", "otherparams"),
        translations.translate_xml(0, 0).replace(
            'x="0" y="0" type="pointf" /><origin', 'x="0.5" y="0" type="pointf" /><origin'
        ),
        FRESH_TRANSFORM.replace("<filterId", "<extra /><filterId"),
        FRESH_TRANSFORM.replace('<scaleX value="1"', '<scaleX value="2"'),
        translations.translate_xml(16385, 0),
        translations.translate_xml(0, 0).replace(
            'x="0" y="0" type="pointf" /><origin', 'x="inf" y="0" type="pointf" /><origin'
        ),
        translations.translate_xml(0, 0).replace(
            'x="0" y="0" type="pointf" /><origin', 'x="nan" y="0" type="pointf" /><origin'
        ),
        "<!DOCTYPE a [<!ENTITY e 'x'>]><a>&e;</a>",
        "not xml",
    ],
    ids=[
        "rotated",
        "mode",
        "params",
        "half",
        "extra",
        "scaled",
        "far",
        "infinite",
        "nan",
        "entity",
        "broken",
    ],
)
def test_the_parse_reads_no_other_params(xml: str) -> None:
    assert translations.translation(xml) is None


# Refusals, each before any change.


@pytest.mark.parametrize(
    "layer, code",
    [
        (layer_id(1, 99), "LAYER_NOT_FOUND"),
        (BASE, "LOCKED_TARGET"),
        (GUARD, "LOCKED_TARGET"),
        (LOOSE, "LOCKED_TARGET"),
    ],
    ids=["unknown", "protected", "holds_protected", "in_protected_group"],
)
def test_a_translate_is_refused_for_what_it_may_not_move(
    world: World, layer: str, code: str
) -> None:
    document_id, handle = world.document()
    body = world.refused(OP, _translate(document_id, layer, [1, 0]))
    assert body["code"] == code
    if code == "LOCKED_TARGET":
        assert body["details"]["protected_layer_ids"]
    _untouched(world, handle)


def test_the_root_is_not_translated(world: World) -> None:
    document_id, _ = world.document()
    root = layer_id(1, 999)
    tree = world.port._tree(1)
    for node in tree["nodes"]:
        if node["parent_id"] == ROOT:
            node["parent_id"] = root
    tree["root_id"] = root
    body = world.refused(OP, _translate(document_id, root, [1, 0]))
    assert body["code"] == "INVALID_ARGUMENT" and body["details"] == {"layer_id": root}


@pytest.mark.parametrize("kind", ["transparencymask", "filterlayer", "clonelayer"])
def test_only_paint_layers_and_groups_are_translated(world: World, kind: str) -> None:
    document_id, handle = world.document()
    tree = world.port._tree(1)
    node = fake_node(1, 30, "other", ROOT, 5, type=kind)
    tree["nodes"].append(node)
    body = world.refused(OP, _translate(document_id, node["id"], [1, 0]))
    assert body["code"] == "INVALID_ARGUMENT" and body["details"]["layer_type"] == kind
    _untouched(world, handle)


@pytest.mark.parametrize("two", [False, True], ids=["foreign", "two"])
def test_a_layer_whose_transform_mask_no_translate_made_is_refused(world: World, two: bool) -> None:
    document_id, handle = world.document()
    if two:
        world.add_mask(PAINT)
        world.add_mask(PAINT)
    else:
        world.add_mask(PAINT, ROTATED)
    stack = world.stack()
    body = world.refused(OP, _translate(document_id, PAINT, [1, 0]))
    assert body["code"] == "UNSUPPORTED_CAPABILITY"
    assert body["details"]["reason"] == "transform_mask"
    assert world.stack() == stack and not handle.dirty


def test_a_hidden_translate_mask_is_refused(world: World) -> None:
    document_id, _ = world.document()
    world.add_mask(PAINT, translations.translate_xml(2, 0), visible=False)
    body = world.refused(OP, _translate(document_id, PAINT, [1, 0]))
    assert body["code"] == "UNSUPPORTED_CAPABILITY"
    assert body["details"]["reason"] == "hidden_transform_mask"


def test_a_whole_translation_past_its_bound_is_refused(world: World) -> None:
    document_id, handle = world.document()
    world.add_mask(PAINT, translations.translate_xml(16000, 0))
    body = world.refused(OP, _translate(document_id, PAINT, [400, 0]))
    assert body["code"] == "INVALID_ARGUMENT" and body["details"]["translation_px"] == [16000, 0]
    assert not handle.dirty


def test_cumulative_undo_refuses_a_translate(world: World) -> None:
    document_id, handle = world.document()
    world.port.cumulative = True
    body = world.refused(OP, _translate(document_id, PAINT, [1, 0]))
    assert body["code"] == "UNSUPPORTED_CAPABILITY"
    assert body["details"]["reason"] == "cumulative_undo"
    _untouched(world, handle)


def test_an_animated_document_refuses_a_translate(world: World) -> None:
    document_id, handle = world.document()
    world.port.reach[1] = {"styled": [], "clones": {}, "animated": True}
    body = world.refused(OP, _translate(document_id, PAINT, [1, 0]))
    assert body["code"] == "UNSUPPORTED_CAPABILITY" and body["details"]["reason"] == "animated"
    _untouched(world, handle)


@pytest.mark.parametrize(
    "operation",
    [
        {"type": "translate", "by_px": [0, 0]},
        {"type": "translate", "by_px": [1.5, 0]},
        {"type": "translate", "by_px": [16385, 0]},
        {"type": "translate", "by_px": [1]},
        {"type": "translate", "by_px": [True, 0]},
        {"type": "scale", "by_px": [1, 0]},
        {"type": "translate", "by_px": [1, 0], "extra": 1},
        [1, 0],
    ],
)
def test_a_translates_arguments_are_checked(world: World, operation: Any) -> None:
    document_id, handle = world.document()
    args = {"document_id": document_id, "layer_id": PAINT, "operation": operation}
    assert world.refused(OP, args)["code"] == "INVALID_ARGUMENT"
    _untouched(world, handle)


# Translating.


def test_a_first_translate_adds_its_mask_on_top_in_two_steps(world: World) -> None:
    document_id, handle = world.document()
    own = bytes(world.port._buffers(1).get(PAINT, b""))
    world.add_mask(PAINT, None, type="transparencymask")
    assert world.pixel(1, 1) != world.pixel(4, 2)
    shown = world.pixel(1, 1)
    receipt = world.run(OP, _translate(document_id, PAINT, [3, 1]))
    [mask] = world.masks(PAINT)
    assert receipt["transform_mask_id"] == mask["id"] and receipt["created_mask"] is True
    assert (receipt["by_px"], receipt["translation_px"]) == ([3, 1], [3, 1])
    assert receipt["undo_steps"] == 2 and world.stack() == [history.ADD, ""]
    # On top of the layer's masks, named, shown, and nothing else changed.
    kids = nodes.children(world.tree())[PAINT]
    assert kids[-1] == mask["id"] and mask["name"] == "Translate" and mask["visible"]
    assert world.port.translation_of(1, mask["id"]) == (3, 1)
    assert world.pixel(4, 2) == shown and world.pixel(1, 1) != shown
    assert bytes(world.port._buffers(1).get(PAINT, b"")) == own
    steps = handle.ledger.steps
    assert [step.label for step in steps] == [history.ADD, ""]
    assert steps[0].operation_id == steps[1].operation_id
    assert receipt["verification"]["changed_px"] > 0


def test_a_second_translate_moves_the_same_mask_in_one_step(world: World) -> None:
    document_id, _ = world.document()
    first = world.run(OP, _translate(document_id, PAINT, [3, 1]))
    second = world.run(OP, _translate(document_id, PAINT, [-1, 1]))
    assert second["transform_mask_id"] == first["transform_mask_id"]
    assert second["created_mask"] is False and second["undo_steps"] == 1
    assert second["translation_px"] == [2, 2]
    assert world.stack() == [history.ADD, "", ""] and len(world.masks(PAINT)) == 1


def test_a_group_is_translated_with_everything_inside_it(world: World) -> None:
    document_id, _ = world.document()
    shown = world.pixel(5, 0)
    receipt = world.run(OP, _translate(document_id, GROUP, [-2, 1]))
    assert receipt["created_mask"] is True and world.pixel(3, 1) == shown
    assert [node["id"] for node in world.masks(GROUP)] == [receipt["transform_mask_id"]]


def test_a_translate_mask_from_a_file_is_moved_on(world: World) -> None:
    document_id, _ = world.document()
    mask = world.add_mask(PAINT, translations.translate_xml(2, 0))
    receipt = world.run(OP, _translate(document_id, PAINT, [1, 0]))
    assert receipt["transform_mask_id"] == mask and receipt["translation_px"] == [3, 0]


# Leaks and raises, each undone and confirmed.


def test_a_leaking_first_translate_is_undone_in_both_steps(world: World) -> None:
    document_id, handle = world.document()
    world.allow(document_id, _box(0, 0, 4, 4))
    before, composite = world.tree(), world.composite()
    body = world.refused(OP, _translate(document_id, PAINT, [4, 0]))
    details = body["details"]
    assert body["code"] == "PROTECTED_REGION_CHANGED"
    assert (details["rolled_back"], details["rollback_verified"]) == (True, True)
    assert details["history_sealed"] is False and details["verification"]["changed_px"] > 0
    assert _watched(world.tree()) == _watched(before) and world.composite() == composite
    assert handle.ledger.steps == [] and not handle.unsafe and not handle.dirty
    assert world.port.undo_labels(handle.document) == (None, history.ADD)


def test_a_leaking_move_of_an_existing_mask_puts_its_params_back(world: World) -> None:
    document_id, handle = world.document()
    first = world.run(OP, _translate(document_id, PAINT, [1, 0]))
    world.allow(document_id, _box(0, 0, 4, 4))
    composite = world.composite()
    body = world.refused(OP, _translate(document_id, PAINT, [4, 0]))
    assert body["code"] == "PROTECTED_REGION_CHANGED" and body["details"]["rollback_verified"]
    assert world.port.translation_of(1, first["transform_mask_id"]) == (1, 0)
    assert world.composite() == composite and not handle.unsafe


@pytest.mark.parametrize(
    "fail, rolled_back",
    [
        ("create_transform", False),
        ("attach_after", True),
        ("set_transform", True),
        ("set_transform_after", True),
    ],
    ids=["before_the_attach", "after_the_attach", "before_the_move", "after_the_move"],
)
def test_a_raise_around_either_step_is_undone_and_confirmed(
    world: World, fail: str, rolled_back: bool
) -> None:
    document_id, handle = world.document()
    before, composite = world.tree(), world.composite()
    world.port.fail[fail] = RuntimeError("libkis failed")
    body = world.refused(OP, _translate(document_id, PAINT, [1, 0]))
    details = body["details"]
    assert body["code"] == "INTERNAL_ERROR" and details["rollback_verified"] is True
    assert details["rolled_back"] is rolled_back
    # A step was named and never pushed, so Krita may hold it.
    assert details["history_sealed"] is True
    assert _watched(world.tree()) == _watched(before) and world.composite() == composite
    assert handle.ledger.steps == [] and not handle.unsafe and not handle.dirty


def test_a_translate_that_changed_another_node_is_rolled_back(world: World) -> None:
    document_id, handle = world.document()
    before = world.tree()

    def renamed(tree: dict[str, Any], node: dict[str, Any]) -> None:
        next(one for one in tree["nodes"] if one["id"] == INNER)["name"] = "moved by Krita"

    world.port.on_layer.append(renamed)
    body = world.refused(OP, _translate(document_id, PAINT, [1, 0]))
    details = body["details"]
    # The judge names the node; a rename is no undo step, so the rollback cannot confirm.
    assert body["code"] == "ROLLBACK_FAILED" and details["cause"] == "INTERNAL_ERROR"
    assert details["layer_ids"] == [INNER] and details["rollback_verified"] is False
    assert handle.unsafe and world.masks(PAINT) == []
    assert _watched(world.tree()) != _watched(before)


def test_params_krita_did_not_take_are_refused_with_the_attach_undone(world: World) -> None:
    document_id, handle = world.document()
    before = world.tree()
    world.port.transform_takes = False
    body = world.refused(OP, _translate(document_id, PAINT, [1, 0]))
    assert body["code"] == "INTERNAL_ERROR" and body["details"]["rollback_verified"] is True
    assert _watched(world.tree()) == _watched(before) and handle.ledger.steps == []


def test_a_move_that_left_the_params_as_they_were_is_never_pushed(world: World) -> None:
    # Krita pushed an unnamed step that changed nothing: no state confirms it, so it is never
    # pushed, and history stops below it.
    document_id, handle = world.document()
    first = world.run(OP, _translate(document_id, PAINT, [1, 0]))
    applied = handle.ledger.applied
    world.port.transform_inert = True
    body = world.refused(OP, _translate(document_id, PAINT, [1, 0]))
    details = body["details"]
    assert body["code"] == "INTERNAL_ERROR" and details["rollback_verified"] is True
    assert details["rolled_back"] is False and details["history_sealed"] is True
    assert handle.ledger.applied == applied and handle.ledger.floor == applied
    assert world.port.translation_of(1, first["transform_mask_id"]) == (1, 0)


def test_an_inert_move_above_a_new_mask_cannot_be_confirmed(world: World) -> None:
    # Krita's unnamed step sits above the attach, so the attach cannot be undone alone.
    document_id, handle = world.document()
    world.port.transform_inert = True
    body = world.refused(OP, _translate(document_id, PAINT, [1, 0]))
    assert body["code"] == "ROLLBACK_FAILED" and body["details"]["rollback_verified"] is False
    assert handle.unsafe


def test_an_inert_move_never_undoes_a_selections_unnamed_step(world: World) -> None:
    document_id, handle = world.document()
    world.run(OP, _translate(document_id, PAINT, [1, 0]))
    selection = {
        "document_id": document_id,
        "combine": "replace",
        "shape": {"kind": "all"},
        "grow_px": 0,
        "shrink_px": 0,
        "feather_px": 0,
        "invert": False,
    }
    world.run("selection.set", selection)
    world.port.transform_inert = True
    body = world.refused(OP, _translate(document_id, PAINT, [1, 0]))
    assert body["details"]["rollback_verified"] is True and body["details"]["rolled_back"] is False
    assert world.port.selection_bounds(handle.document) is not None
    assert world.stack()[-2:] == ["", ""] and not handle.unsafe


# History.


def test_history_moves_a_first_translates_two_steps_together(world: World) -> None:
    document_id, _ = world.document()
    shown = world.pixel(1, 1)
    receipt = world.run(OP, _translate(document_id, PAINT, [3, 1]))
    split = world.refused(
        "history.step", {"document_id": document_id, "action": "undo", "steps": 1}
    )
    assert split["code"] == "INVALID_ARGUMENT" and split["details"]["steps_needed"] == 2
    assert world.history(document_id, "undo", 2)["verified"] is True
    assert world.masks(PAINT) == [] and world.pixel(1, 1) == shown
    assert world.history(document_id, "redo", 2)["verified"] is True
    assert world.port.translation_of(1, receipt["transform_mask_id"]) == (3, 1)


def test_history_undoes_a_later_move_alone_and_tells_it_from_a_selection(world: World) -> None:
    document_id, handle = world.document()
    receipt = world.run(OP, _translate(document_id, PAINT, [3, 1]))
    selection = {
        "document_id": document_id,
        "combine": "replace",
        "shape": {"kind": "all"},
        "grow_px": 0,
        "shrink_px": 0,
        "feather_px": 0,
        "invert": False,
    }
    world.run("selection.set", selection)
    world.run(OP, _translate(document_id, PAINT, [1, 0]))
    assert world.history(document_id, "undo", 1)["verified"] is True
    assert world.port.translation_of(1, receipt["transform_mask_id"]) == (3, 1)
    assert world.port.selection_bounds(handle.document) is not None
    assert world.history(document_id, "undo", 1)["verified"] is True
    assert world.port.selection_bounds(handle.document) is None


# The fingerprint and the watched fields.


def test_the_fingerprint_and_drift_see_a_transform_masks_params(world: World) -> None:
    world.document()
    world.add_mask(PAINT, translations.translate_xml(1, 0))
    tree = world.tree()
    mask = next(node for node in tree["nodes"] if node["type"] == TRANSFORM)
    moved = {
        **tree,
        "nodes": [
            {**node, "translation_px": [2, 0]} if node["id"] == mask["id"] else node
            for node in tree["nodes"]
        ],
    }
    assert ledger.node_states(moved) != ledger.node_states(tree)
    assert drift(tree, moved) == [mask["id"]]
    assert drift(tree, moved, loose={mask["id"]: {"translation_px"}}) == []


def test_inspect_reports_each_translate_masks_translation(world: World) -> None:
    document_id, _ = world.document()
    receipt = world.run(OP, _translate(document_id, PAINT, [3, 1]))
    foreign = world.add_mask(INNER, ROTATED)
    found = world.run("document.inspect", {"document_id": document_id, "frame": 0})
    moved = {layer["id"]: layer["translation_px"] for layer in found["layers"]}
    assert moved[receipt["transform_mask_id"]] == [3, 1]
    assert moved[foreign] is None and moved[PAINT] is None


# A copy of a transform mask.


def test_a_layer_holding_a_transform_mask_is_not_copied(world: World) -> None:
    # Undoing the attach of a copied transform mask crashes Krita (K53).
    document_id, _ = world.document()
    world.run(OP, _translate(document_id, INNER, [1, 0]))
    stack = world.stack()
    for layer in (INNER, GROUP):
        args = {"document_id": document_id, "layer_id": layer, "name": "trial"}
        body = world.refused("layer.duplicate", args)
        assert body["code"] == "UNSUPPORTED_CAPABILITY"
        assert body["details"]["reason"] == "transform_mask"
    assert world.stack() == stack


def test_a_copy_made_before_a_translate_is_translated(world: World) -> None:
    document_id, _ = world.document()
    copy = world.run(
        "layer.duplicate", {"document_id": document_id, "layer_id": PAINT, "name": "trial"}
    )
    receipt = world.run(OP, _translate(document_id, copy["layer_id"], [2, 0]))
    assert receipt["created_mask"] is True and world.masks(PAINT) == []
