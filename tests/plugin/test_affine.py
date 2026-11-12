import hashlib
import itertools
import json
import os
from pathlib import Path
from typing import Any

import pytest
from bridge_core import affine, documents, harness, history, nodes, transforms
from bridge_core.errors import BridgeError
from bridge_core.jobs import Call
from bridge_core.registry import Handle, Registry
from fake_krita import FakePort, crop, fake_node, layer_id

A: dict[str, Any] = {"pid": 101, "started_at": "Sun Oct 25 10:00:00 2026"}
WIDTH, HEIGHT = 16, 12
CREATE = {
    "name": "stack",
    "size_px": [WIDTH, HEIGHT],
    "color_model": "RGBA",
    "depth": "U8",
    "profile_id": documents.SRGB_PROFILE,
    "background": "transparent",
}
BASE, PAINT, GROUP, INNER, SHADE, HELD, LOOSE, GUARD, LOCKED = (
    layer_id(1, index) for index in range(9)
)
ROOT = "root-1"
OP = "layer.transform"
RED, GREEN, BLUE, GREY = (
    bytes([60, 40, 220, 255]),
    bytes([90, 200, 40, 255]),
    bytes([220, 60, 40, 255]),
    bytes([128, 128, 128, 255]),
)


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
        # Bottom first: a protected base under the whole canvas, a marked paint layer, a group
        # holding a layer and a hidden one, a protected group holding a free layer, and a group
        # holding a protected layer.
        document_id = self.run("document.create", CREATE)["document_id"]
        handle = self.registry.find(document_id)
        tree = self.port._tree(1)
        tree["nodes"] = [
            fake_node(1, 0, "base", ROOT, 0),
            fake_node(1, 1, "paint", ROOT, 1),
            fake_node(1, 2, "group", ROOT, 2, type="grouplayer"),
            fake_node(1, 3, "inner", GROUP, 0),
            fake_node(1, 4, "shade", GROUP, 1, visible=False),
            fake_node(1, 5, "held", ROOT, 3, type="grouplayer"),
            fake_node(1, 6, "loose", HELD, 0),
            fake_node(1, 7, "guard", ROOT, 4, type="grouplayer"),
            fake_node(1, 8, "locked", GUARD, 0),
        ]
        tree["active_id"] = PAINT
        self.port.paintable(1)
        self.paint(BASE, _box(0, 0, WIDTH, HEIGHT), GREY)
        self.paint(PAINT, _box(2, 2, 4, 2), RED)
        self.paint(PAINT, _box(2, 2, 1, 1), BLUE)
        self.paint(INNER, _box(9, 6, 2, 2), GREEN)
        self.paint(SHADE, _box(12, 8, 1, 1), BLUE)
        self.paint(LOOSE, _box(1, 9, 2, 1), GREEN)
        self.paint(LOCKED, _box(14, 10, 1, 1), RED)
        self.groups()
        handle.protected = {BASE, HELD, LOCKED}
        self.port.render[1] = self.render
        self.port.refresh(self.port.documents()[0])
        return document_id, handle

    def paint(self, layer: str, box: dict[str, int], pixel: bytes) -> None:
        buffer = self.port.buffers[layer]
        for y in range(box["y"], box["y"] + box["height"]):
            for x in range(box["x"], box["x"] + box["width"]):
                buffer[(y * WIDTH + x) * 4 : (y * WIDTH + x) * 4 + 4] = pixel
        node = self.port._layer(1, layer)
        node["bounds_px"] = _opaque(bytes(buffer))

    def groups(self) -> None:
        # A group's bounds are its shown layers', as Krita's projection reads them.
        tree = self.port._tree(1)
        found = {node["id"]: node for node in tree["nodes"]}
        below = nodes.children(tree)
        for node in tree["nodes"]:
            if node["type"] == "grouplayer":
                held = below.get(node["id"], [])
                node["bounds_px"] = _union(
                    [found[one]["bounds_px"] for one in held if found[one]["visible"]]
                )

    def render(self, tree: dict[str, Any]) -> bytes:
        found = {node["id"]: node for node in tree["nodes"]}
        below = nodes.children(tree)
        out = bytearray(WIDTH * HEIGHT * 4)

        def draw(node_id: str, shown: bool) -> None:
            node = found[node_id]
            shown = shown and node["visible"]
            if shown and node["type"] == "paintlayer":
                buffer = self.port.buffers.get(node_id)
                if buffer is not None:
                    for index in range(WIDTH * HEIGHT):
                        if buffer[index * 4 + 3]:
                            out[index * 4 : index * 4 + 4] = buffer[index * 4 : index * 4 + 4]
            for child in below.get(node_id, []):
                draw(child, shown)

        for child in below.get(tree["root_id"], []):
            draw(child, True)
        return bytes(out)

    def tree(self) -> dict[str, Any]:
        found: dict[str, Any] = self.port.tree(self.port.documents()[0])
        return found

    def node(self, layer: str) -> dict[str, Any]:
        return next(node for node in self.tree()["nodes"] if node["id"] == layer)

    def composite(self) -> bytes:
        self.port.refresh(self.port.documents()[0])
        found: bytes = self.port.composite(self.port.documents()[0])
        return found

    def own(self, layer: str) -> bytes:
        return bytes(self.port.buffers[layer])

    def stack(self) -> list[str]:
        return [entry["label"] for entry in self.port.live[1].get("stack", [])]

    def index(self) -> int:
        found: int = self.port.live[1].get("index", 0)
        return found

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
        self.ops["protection.set"](args, Call(f"op-{next(self.ids):032x}", request_id, A))

    def history(self, document_id: str, action: str, steps: int = 1) -> dict[str, Any]:
        return self.run(
            "history.step", {"document_id": document_id, "action": action, "steps": steps}
        )


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


def _opaque(buffer: bytes) -> dict[str, int]:
    xs = [i % WIDTH for i in range(WIDTH * HEIGHT) if buffer[i * 4 + 3]]
    ys = [i // WIDTH for i in range(WIDTH * HEIGHT) if buffer[i * 4 + 3]]
    if not xs:
        return _box(0, 0, 0, 0)
    return _box(min(xs), min(ys), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1)


def _union(boxes: list[dict[str, int]]) -> dict[str, int]:
    found = [box for box in boxes if box["width"] > 0 and box["height"] > 0]
    if not found:
        return _box(0, 0, 0, 0)
    left, top = min(b["x"] for b in found), min(b["y"] for b in found)
    right = max(b["x"] + b["width"] for b in found)
    bottom = max(b["y"] + b["height"] for b in found)
    return _box(left, top, right - left, bottom - top)


def _args(document_id: str, layer: str, operation: dict[str, Any]) -> dict[str, Any]:
    return {"document_id": document_id, "layer_id": layer, "operation": operation}


SCALE = {"type": "scale", "size_px": [8, 4], "filter": "Bicubic"}
ROTATE = {"type": "rotate", "degrees": 90}
SHEAR = {"type": "shear", "degrees": [30, 0]}


def _untouched(world: World, handle: Handle, before: bytes) -> None:
    # A refusal changed nothing: no step, no dirt, no pixel.
    assert world.stack() == [] and not handle.dirty
    assert world.port.reshaped == []
    assert world.composite() == before


# The arguments.


@pytest.mark.parametrize(
    "operation",
    [
        {"type": "scale", "size_px": [1, 16384], "filter": "NearestNeighbor"},
        {"type": "rotate", "degrees": -359.5},
        {"type": "rotate", "degrees": 0.25},
        {"type": "shear", "degrees": [45, -45]},
        {"type": "shear", "degrees": [0, 0.5]},
    ],
)
def test_each_operation_takes_its_own_arguments(operation: dict[str, Any]) -> None:
    transforms.transform_rules(operation)


@pytest.mark.parametrize(
    ("operation", "field"),
    [
        ({"type": "scale", "size_px": [0, 4], "filter": "Bicubic"}, "size_px"),
        ({"type": "scale", "size_px": [16385, 4], "filter": "Bicubic"}, "size_px"),
        ({"type": "scale", "size_px": [4.0, 4], "filter": "Bicubic"}, "size_px"),
        ({"type": "scale", "size_px": [4], "filter": "Bicubic"}, "size_px"),
        ({"type": "scale", "size_px": [4, 4], "filter": "Box"}, "filter"),
        ({"type": "rotate", "degrees": 0}, "degrees"),
        ({"type": "rotate", "degrees": 360}, "degrees"),
        ({"type": "rotate", "degrees": -360}, "degrees"),
        ({"type": "rotate", "degrees": True}, "degrees"),
        ({"type": "rotate", "degrees": float("nan")}, "degrees"),
        ({"type": "shear", "degrees": [0, 0]}, "degrees"),
        ({"type": "shear", "degrees": [46, 0]}, "degrees"),
        ({"type": "shear", "degrees": [0, -45.5]}, "degrees"),
        ({"type": "shear", "degrees": 10}, "degrees"),
    ],
)
def test_each_operation_refuses_what_is_off(operation: dict[str, Any], field: str) -> None:
    with pytest.raises(BridgeError) as raised:
        transforms.transform_rules(operation)
    assert raised.value.body["code"] == "INVALID_ARGUMENT"
    assert raised.value.body["details"] == {"field": field}


@pytest.mark.parametrize(
    "operation",
    [
        {"type": "scale", "size_px": [4, 4]},
        {"type": "scale", "size_px": [4, 4], "filter": "Bicubic", "degrees": 1},
        {"type": "rotate", "degrees": 10, "filter": "Bicubic"},
        {"type": "shear", "degrees": [10, 0], "filter": "Bilinear"},
        {"type": "warp"},
        {"type": "warp", "by_px": [1, 0]},
        {"degrees": 10},
    ],
)
def test_an_operation_with_other_fields_or_type_is_refused(operation: dict[str, Any]) -> None:
    with pytest.raises(BridgeError) as raised:
        transforms.transform_rules(operation)
    assert raised.value.body["code"] == "INVALID_ARGUMENT"


def test_the_filters_are_krita_s_own_eight() -> None:
    # As Krita.filterStrategies() listed them on 5.3.4.1 (K54).
    assert set(affine.FILTERS) == {
        "BSpline",
        "Bell",
        "Bicubic",
        "Bilinear",
        "Hermite",
        "Lanczos3",
        "Mitchell",
        "NearestNeighbor",
    }


# Krita's own arithmetic.


@pytest.mark.parametrize(
    ("degrees", "keeps"),
    [([0.5, 0], True), ([1, 0], False), ([-1, 0], False), ([0, 0.6], True), ([0, 1.2], False)],
)
def test_the_shear_test_matches_what_krita_did(degrees: list[float], keeps: bool) -> None:
    # A 16 x 10 layer at (20, 20): Krita pushed no step exactly where this says the size keeps.
    assert affine.keeps_size(_box(20, 20, 16, 10), degrees) is keeps


def test_the_shear_test_shears_x_then_y() -> None:
    # On a 12 x 8 layer at (8, 8), Krita changed this shear (the probe's marked layer), which a
    # shear without the cross term, or y first, would keep.
    assert affine.keeps_size(_box(8, 8, 12, 8), [-4, 3.6]) is False


def test_the_read_bound_holds_where_the_operation_takes_a_rect() -> None:
    rect, pivot = _box(10, 10, 20, 10), [20.0, 15.0]
    scaled = affine.mapped(rect, {"type": "scale", "size_px": [40, 20]}, rect, pivot)
    assert scaled["x"] <= 0 and scaled["x"] + scaled["width"] >= 40
    turned = affine.mapped(rect, {"type": "rotate", "degrees": 90}, rect, pivot)
    assert turned["y"] <= 5 and turned["y"] + turned["height"] >= 25
    sheared = affine.mapped(rect, {"type": "shear", "degrees": [45, 0]}, rect, pivot)
    assert sheared["x"] <= 5 and sheared["x"] + sheared["width"] >= 35


# Refusals before the marker.


def test_the_root_and_an_unknown_id_are_not_transformed(world: World) -> None:
    document_id, handle = world.document()
    before = world.composite()
    assert world.refused(OP, _args(document_id, ROOT, SCALE))["code"] == "INVALID_ARGUMENT"
    unknown = world.refused(OP, _args(document_id, layer_id(1, 99), SCALE))
    assert unknown["code"] == "LAYER_NOT_FOUND"
    _untouched(world, handle, before)


def test_a_protected_layer_or_one_holding_one_is_refused(world: World) -> None:
    document_id, handle = world.document()
    before = world.composite()
    for target in (BASE, GUARD):
        body = world.refused(OP, _args(document_id, target, ROTATE))
        assert body["code"] == "LOCKED_TARGET"
    _untouched(world, handle, before)


def test_a_layer_in_a_protected_group_is_transformed(world: World) -> None:
    # Its pixels change, as a stroke's would; the composite judges it.
    document_id, _ = world.document()
    done = world.run(
        OP, _args(document_id, LOOSE, {"type": "scale", "size_px": [4, 2], "filter": "Bilinear"})
    )
    assert done["bounds_after_px"] != done["bounds_before_px"]


@pytest.mark.parametrize(
    ("kind", "reason"),
    [
        ("transparencymask", "node_type"),
        ("vectorlayer", "node_type"),
        ("transformmask", "transform_mask"),
    ],
)
def test_a_layer_holding_another_kind_is_refused(world: World, kind: str, reason: str) -> None:
    document_id, handle = world.document()
    before = world.composite()
    tree = world.port._tree(1)
    tree["nodes"].append(
        fake_node(1, 30, "other", INNER if "mask" in kind else GROUP, 2, type=kind)
    )
    body = world.refused(OP, _args(document_id, GROUP, SCALE))
    assert body["code"] == "UNSUPPORTED_CAPABILITY" and body["details"]["reason"] == reason
    _untouched(world, handle, before)


def test_a_layer_in_a_translated_group_is_refused(world: World) -> None:
    document_id, handle = world.document()
    before = world.composite()
    tree = world.port._tree(1)
    tree["nodes"].append(fake_node(1, 30, "Translate", GROUP, 2, type="transformmask"))
    body = world.refused(OP, _args(document_id, INNER, ROTATE))
    assert body["details"]["reason"] == "transform_mask"
    assert body["details"]["transform_mask_ids"] == [layer_id(1, 30)]
    _untouched(world, handle, before)


@pytest.mark.parametrize("flag", ["locked", "alpha_locked"])
def test_a_locked_layer_is_refused(world: World, flag: str) -> None:
    document_id, handle = world.document()
    before = world.composite()
    world.port._layer(1, INNER)[flag] = True
    body = world.refused(OP, _args(document_id, GROUP, ROTATE))
    assert body["code"] == "INVALID_ARGUMENT"
    assert body["details"] == {"layer_id": GROUP, "reason": flag, "layer_ids": [INNER]}
    _untouched(world, handle, before)


def test_a_styled_layer_or_a_clone_source_is_refused(world: World) -> None:
    document_id, handle = world.document()
    before = world.composite()
    world.port.reach[1] = {"styled": [INNER], "clones": {}, "animated": False}
    styled = world.refused(OP, _args(document_id, GROUP, ROTATE))
    assert styled["details"]["reason"] == "layer_style"
    world.port.reach[1] = {"styled": [], "clones": {layer_id(1, 40): PAINT}, "animated": False}
    cloned = world.refused(OP, _args(document_id, PAINT, ROTATE))
    assert cloned["details"] == {
        "layer_id": PAINT,
        "reason": "clone_source",
        "clone_ids": [layer_id(1, 40)],
    }
    assert "transformed" in cloned["message"]
    _untouched(world, handle, before)


def test_an_empty_layer_or_a_change_of_nothing_is_refused(world: World) -> None:
    document_id, handle = world.document()
    before = world.composite()
    world.port._layer(1, PAINT)["bounds_px"] = _box(0, 0, 0, 0)
    assert world.refused(OP, _args(document_id, PAINT, ROTATE))["details"]["reason"] == "empty"
    world.port._layer(1, PAINT)["bounds_px"] = _box(2, 2, 4, 2)
    same = {"type": "scale", "size_px": [4, 2], "filter": "Bicubic"}
    assert world.refused(OP, _args(document_id, PAINT, same))["details"]["reason"] == "no_change"
    tiny = {"type": "shear", "degrees": [0.5, 0]}
    body = world.refused(OP, _args(document_id, PAINT, tiny))
    assert body["code"] == "INVALID_ARGUMENT" and body["details"]["reason"] == "no_change"
    _untouched(world, handle, before)


def test_cumulative_undo_and_a_filter_krita_lacks_are_refused(world: World) -> None:
    document_id, handle = world.document()
    before = world.composite()
    world.port.cumulative = True
    assert (
        world.refused(OP, _args(document_id, PAINT, ROTATE))["details"]["reason"]
        == "cumulative_undo"
    )
    world.port.cumulative = False
    world.port.filters = ["Bicubic"]
    lacking = {"type": "scale", "size_px": [8, 4], "filter": "Lanczos3"}
    body = world.refused(OP, _args(document_id, PAINT, lacking))
    assert body["details"] == {"layer_id": PAINT, "reason": "filter", "filter": "Lanczos3"}
    _untouched(world, handle, before)


def test_a_group_of_too_many_layers_or_too_large_a_read_is_refused(world: World) -> None:
    document_id, handle = world.document()
    before = world.composite()
    tree = world.port._tree(1)
    for index in range(affine.MAX_NODES):
        tree["nodes"].append(fake_node(1, 100 + index, f"many {index}", GROUP, 10 + index))
    body = world.refused(OP, _args(document_id, GROUP, ROTATE))
    assert body["details"]["reason"] == "too_many_nodes"
    del tree["nodes"][-affine.MAX_NODES :]
    huge = {"type": "scale", "size_px": [16384, 16384], "filter": "Bicubic"}
    assert world.refused(OP, _args(document_id, PAINT, huge))["details"]["reason"] == "too_large"
    _untouched(world, handle, before)


def test_an_animated_document_refuses_a_transform(world: World) -> None:
    document_id, handle = world.document()
    before = world.composite()
    world.port.reach[1] = {"styled": [], "clones": {}, "animated": True}
    assert world.refused(OP, _args(document_id, PAINT, ROTATE))["details"]["reason"] == "animated"
    _untouched(world, handle, before)


# The change.


def test_a_scale_resamples_the_layer_about_its_centre_in_one_witnessed_step(world: World) -> None:
    document_id, handle = world.document()
    old = world.own(PAINT)
    done = world.run(OP, _args(document_id, PAINT, SCALE))
    assert done == {
        "document_id": document_id,
        "layer_id": PAINT,
        "type": "scale",
        "size_px": [8, 4],
        "filter": "Bicubic",
        "pivot_px": [4.0, 3.0],
        "bounds_before_px": _box(2, 2, 4, 2),
        "bounds_after_px": _box(0, 1, 8, 4),
        "undo_steps": 1,
        "verification": done["verification"],
    }
    assert done["verification"]["mode"] == "full"
    assert world.port.reshaped == [SCALE]
    assert world.stack() == ["Scale Layer"]
    [step] = handle.ledger.steps
    assert (step.op, step.label) == (OP, "Scale Layer")
    # The witness reads where the layer was and where the scale takes it, past a filter's reach.
    rect = affine.mapped(_box(2, 2, 4, 2), SCALE, _box(2, 2, 4, 2), [4.0, 3.0])
    assert step.witness is not None and step.witness[:2] == (PAINT, rect)
    assert step.witness[2] == hashlib.sha256(crop(old, WIDTH, rect, 4)).hexdigest()
    assert step.witness[3] == hashlib.sha256(crop(world.own(PAINT), WIDTH, rect, 4)).hexdigest()
    assert step.region is not None and handle.dirty


@pytest.mark.parametrize("operation", [ROTATE, SHEAR])
def test_a_rotate_or_shear_may_move_the_layers_offset(
    world: World, operation: dict[str, Any]
) -> None:
    # Krita moves the offset on these (K54); the drift check allows it on the target's nodes.
    document_id, handle = world.document()
    done = world.run(OP, _args(document_id, GROUP, operation))
    assert done["type"] == operation["type"] and done["degrees"] == operation["degrees"]
    assert done["filter"] == affine.FIXED[operation["type"]]
    assert world.node(INNER)["offset_px"] != [0, 0]
    assert world.stack() == [history.LABELS[f"layer.transform.{operation['type']}"][0]]
    assert handle.ledger.steps[0].witness is not None


def test_a_group_turns_every_layer_in_it_about_the_group_s_centre(world: World) -> None:
    document_id, _ = world.document()
    group = world.node(GROUP)["bounds_px"]
    done = world.run(OP, _args(document_id, GROUP, {"type": "rotate", "degrees": 180}))
    assert done["pivot_px"] == [group["x"] + group["width"] / 2, group["y"] + group["height"] / 2]
    # The hidden layer turns too, about the shown layers' centre.
    assert world.node(SHADE)["bounds_px"] == _box(7, 5, 1, 1)


def test_the_witness_is_the_first_layer_that_moved(world: World) -> None:
    # Turned half way round its centre, a layer symmetric about it does not change, so the
    # witness is the next one.
    document_id, handle = world.document()
    world.paint(INNER, _box(9, 6, 2, 2), bytes(4))
    world.paint(INNER, _box(10, 6, 4, 4), GREEN)
    world.paint(SHADE, _box(12, 8, 1, 1), bytes(4))
    world.paint(SHADE, _box(10, 6, 1, 1), BLUE)
    world.port._layer(1, SHADE)["visible"] = True
    world.groups()
    world.port.refresh(world.port.documents()[0])
    before = world.own(INNER)
    world.run(OP, _args(document_id, GROUP, {"type": "rotate", "degrees": 180}))
    assert world.own(INNER) == before
    [step] = handle.ledger.steps
    assert step.witness is not None and step.witness[0] == SHADE


def test_a_step_that_moves_only_offsets_is_refused_and_confirmed(world: World) -> None:
    # A half turn of symmetric paint: Krita pushes a step that changes no pixel; history stops
    # below it, and the document is as it was.
    document_id, handle = world.document()
    before = world.composite()
    world.port.reshape_inert = True
    body = world.refused(OP, _args(document_id, PAINT, ROTATE))
    assert body["code"] == "INVALID_ARGUMENT" and body["details"]["reason"] == "no_change"
    details = body["details"]
    assert details["rolled_back"] is False and details["rollback_verified"] is True
    assert details["history_sealed"] is True
    assert world.stack() == ["Rotate Layer"] and handle.ledger.steps == []
    assert world.composite() == before and not handle.unsafe and not handle.dirty


def test_a_leak_is_undone_and_confirmed(world: World) -> None:
    document_id, handle = world.document()
    before, own = world.composite(), world.own(PAINT)
    world.allow(document_id, _box(0, 0, 8, 6))
    body = world.refused(
        OP, _args(document_id, PAINT, {"type": "scale", "size_px": [12, 4], "filter": "Bicubic"})
    )
    assert body["code"] == "PROTECTED_REGION_CHANGED"
    details = body["details"]
    assert details["rolled_back"] is True and details["rollback_verified"] is True
    assert details["history_sealed"] is False
    assert world.composite() == before and world.own(PAINT) == own
    assert world.index() == 0 and not handle.unsafe and not handle.dirty


def test_a_raise_before_krita_moves_changes_nothing(world: World) -> None:
    document_id, handle = world.document()
    before = world.composite()
    world.port.fail["transform_node"] = RuntimeError("before")
    body = world.refused(OP, _args(document_id, PAINT, ROTATE))
    assert body["code"] == "INTERNAL_ERROR"
    assert body["details"]["rolled_back"] is False and body["details"]["rollback_verified"] is True
    assert world.composite() == before and not handle.unsafe


def test_a_raise_after_krita_moved_undoes_the_step_by_its_witness(world: World) -> None:
    # The step was never pushed: it is found by its label, state and the first layer that moved.
    document_id, handle = world.document()
    before, own = world.composite(), world.own(INNER)
    world.port.fail["transform_node_after"] = RuntimeError("after")
    body = world.refused(OP, _args(document_id, GROUP, SHEAR))
    details = body["details"]
    assert details["rolled_back"] is True and details["rollback_verified"] is True
    assert details["history_sealed"] is True
    assert world.composite() == before and world.own(INNER) == own
    assert world.node(INNER)["offset_px"] == [0, 0] and world.index() == 0
    assert not handle.unsafe


def test_a_raise_in_the_rollback_leaves_the_document_unsafe(world: World) -> None:
    document_id, handle = world.document()
    world.allow(document_id, _box(0, 0, 8, 6))
    reads = {"count": 0}

    def failing() -> None:
        reads["count"] += 1
        # The before-read, the after-read, then the rollback's re-read.
        if reads["count"] == 3:
            raise RuntimeError("the re-read")

    world.port.on_read.append(failing)
    body = world.refused(
        OP, _args(document_id, PAINT, {"type": "scale", "size_px": [12, 4], "filter": "Bicubic"})
    )
    assert body["code"] == "ROLLBACK_FAILED" and handle.unsafe


# History.


def test_history_undoes_and_redoes_a_transform_by_its_witness(world: World) -> None:
    document_id, _ = world.document()
    before, own = world.composite(), world.own(PAINT)
    world.run(OP, _args(document_id, PAINT, SCALE))
    after = world.own(PAINT)
    undone = world.history(document_id, "undo")
    assert undone["verified"] is True and undone["steps"] == [
        {"op": OP, "operation_id": undone["steps"][0]["operation_id"]}
    ]
    assert world.own(PAINT) == own and world.composite() == before
    redone = world.history(document_id, "redo")
    assert redone["verified"] is True and world.own(PAINT) == after


def test_an_owner_step_of_the_same_name_stops_history_without_a_retry(world: World) -> None:
    # Krita's own Layer > Transform menu names its steps as the bridge's do: a move that undid
    # the owner's and could not confirm it is put back, and history stops there for good.
    document_id, handle = world.document()
    world.run(OP, _args(document_id, PAINT, ROTATE))
    before = world.port._state(1)
    world.paint(INNER, _box(9, 6, 2, 2), BLUE)
    world.port._push(1, "Rotate Layer", before)
    body = world.refused("history.step", {"document_id": document_id, "action": "undo", "steps": 1})
    assert body["code"] == "INVALID_ARGUMENT" and body["retryable"] is False
    assert handle.ledger.undo_available() == 0
    assert world.stack() == ["Rotate Layer", "Rotate Layer"] and world.index() == 2
    assert not handle.unsafe


def test_a_layer_whose_bounds_moved_as_the_call_began_is_refused_for_a_retry(world: World) -> None:
    document_id, handle = world.document()
    before = world.composite()
    node = world.port._layer(1, PAINT)

    def grown() -> None:
        node["bounds_px"] = _box(2, 2, 5, 2)

    world.port.on_read.append(grown)
    body = world.refused(OP, _args(document_id, PAINT, ROTATE))
    assert body["code"] == "INTERNAL_ERROR" and body["retryable"] is True
    assert world.stack() == [] and world.port.reshaped == [] and not handle.dirty
    world.port.on_read.clear()
    assert world.composite() == before


def test_a_composite_change_no_layer_shows_cannot_be_confirmed(world: World) -> None:
    # Krita pushed a step and the composite moved, yet none of the layer's own pixels did: the
    # change cannot be told, so the document is unsafe.
    document_id, handle = world.document()
    world.port.reshape_inert = True
    drawn = world.render

    def stray(tree: dict[str, Any]) -> bytes:
        out = bytearray(drawn(tree))
        if world.port.reshaped:
            out[0:4] = BLUE
        return bytes(out)

    world.port.render[1] = stray
    body = world.refused(OP, _args(document_id, PAINT, ROTATE))
    assert body["code"] == "ROLLBACK_FAILED" and body["details"]["cause"] == "INTERNAL_ERROR"
    assert handle.unsafe


def test_a_raise_after_krita_turned_a_hidden_layer_is_undone_by_its_witness(world: World) -> None:
    # The composite shows nothing of it, and a half turn keeps its bounds, so only the layer's
    # own pixels tell the step was made.
    document_id, handle = world.document()
    world.port._layer(1, PAINT)["visible"] = False
    world.port.refresh(world.port.documents()[0])
    own = world.own(PAINT)
    world.port.fail["transform_node_after"] = RuntimeError("after")
    body = world.refused(OP, _args(document_id, PAINT, {"type": "rotate", "degrees": 180}))
    details = body["details"]
    assert details["rolled_back"] is True and details["rollback_verified"] is True
    assert world.node(PAINT)["bounds_px"] == _box(2, 2, 4, 2)
    assert world.own(PAINT) == own and world.index() == 0 and not handle.unsafe


def test_colour_under_alpha_0_past_a_layer_s_bounds_is_read_and_put_back(world: World) -> None:
    # A resample leaves colour under alpha 0 outside a layer's exact bounds (K54): the witness
    # reads it rather than taking it for the layer's default.
    document_id, handle = world.document()
    world.port.buffers[PAINT][(1 * WIDTH + 1) * 4 : (1 * WIDTH + 1) * 4 + 4] = bytes(
        [40, 60, 220, 0]
    )
    assert world.node(PAINT)["bounds_px"] == _box(2, 2, 4, 2)
    own = world.own(PAINT)
    world.allow(document_id, _box(0, 0, 8, 6))
    leaking = {"type": "scale", "size_px": [12, 4], "filter": "Bicubic"}
    body = world.refused(OP, _args(document_id, PAINT, leaking))
    details = body["details"]
    assert body["code"] == "PROTECTED_REGION_CHANGED"
    assert details["rolled_back"] is True and details["rollback_verified"] is True
    assert world.own(PAINT) == own and not handle.unsafe


def test_pixels_past_the_witness_rect_are_refused_and_undone(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Krita took the layer further than the bridge reads, so the change is undone, by what the
    # rect did see.
    document_id, handle = world.document()
    own = world.own(PAINT)
    monkeypatch.setattr(affine, "REACH", 0)
    monkeypatch.setattr(affine, "SLACK", -2)
    body = world.refused(OP, _args(document_id, PAINT, SCALE))
    details = body["details"]
    assert body["code"] == "INTERNAL_ERROR" and details["layer_ids"] == [PAINT]
    assert details["rolled_back"] is True and details["rollback_verified"] is True
    assert world.own(PAINT) == own and world.index() == 0 and not handle.unsafe


def test_a_layer_read_empty_before_krita_was_idle_is_refused_for_a_retry(world: World) -> None:
    # The first read is not waited for, so what it says of the bounds is never refused on.
    document_id, handle = world.document()
    node = world.port._layer(1, PAINT)
    node["bounds_px"] = _box(0, 0, 0, 0)

    def settled() -> None:
        node["bounds_px"] = _box(2, 2, 4, 2)

    world.port.on_read.append(settled)
    body = world.refused(OP, _args(document_id, PAINT, ROTATE))
    assert body["code"] == "INTERNAL_ERROR" and body["retryable"] is True
    assert world.port.reshaped == [] and not handle.dirty


def test_layers_whose_reads_pass_the_total_together_are_refused(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    document_id, handle = world.document()
    group = world.node(GROUP)["bounds_px"]
    pivot = [group["x"] + group["width"] / 2, group["y"] + group["height"] / 2]
    areas = []
    for layer in (INNER, SHADE):
        old = world.node(layer)["bounds_px"]
        rect = _union([old, affine.mapped(old, ROTATE, group, pivot)])
        areas.append(rect["width"] * rect["height"])
    # Each fits alone; together they pass.
    monkeypatch.setattr(affine, "MAX_TOTAL_PIXELS", sum(areas) - 1)
    assert max(areas) <= affine.MAX_TOTAL_PIXELS
    body = world.refused(OP, _args(document_id, GROUP, ROTATE))
    assert body["details"]["reason"] == "too_large"
    assert body["details"]["max_total_pixels"] == affine.MAX_TOTAL_PIXELS
    assert world.port.reshaped == [] and not handle.dirty
