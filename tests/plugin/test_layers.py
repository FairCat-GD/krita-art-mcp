import hashlib
import itertools
import json
import os
from pathlib import Path
from typing import Any

import pytest
from bridge_core import documents, harness, history, ledger, nodes
from bridge_core.errors import BridgeError
from bridge_core.jobs import Call
from bridge_core.registry import Handle, Registry
from fake_krita import UNREAD, FakePort, fake_node, layer_id

A: dict[str, Any] = {"pid": 101, "started_at": "Sun Oct 25 10:00:00 2026"}
CREATE = {
    "name": "stack",
    "size_px": [8, 4],
    "color_model": "RGBA",
    "depth": "U8",
    "profile_id": documents.SRGB_PROFILE,
    "background": "transparent",
}
BASE, LEFT, RIGHT, GROUP, INNER, HELD, LOCKED = (layer_id(1, index) for index in range(7))
ROOT = "root-1"


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
        # Shows hidden layers too, as a Krita that ignored a hide would.
        self.leaky = False

    def run(self, op: str, args: dict[str, Any]) -> dict[str, Any]:
        number = next(self.ids)
        return self.ops[op](args, Call(f"op-{number:032x}", f"req-{number}", A))

    def refused(self, op: str, args: dict[str, Any]) -> dict[str, Any]:
        with pytest.raises(BridgeError) as raised:
            self.run(op, args)
        body: dict[str, Any] = raised.value.body
        return body

    def document(self) -> tuple[str, Handle]:
        # Bottom first: a protected base, two editable layers, a group holding one, and a group
        # holding a protected layer; the composite is drawn from the tree.
        document_id = self.run("document.create", CREATE)["document_id"]
        handle = self.registry.find(document_id)
        tree = self.port._tree(1)
        tree["nodes"] = [
            fake_node(1, 0, "base", ROOT, 0, bounds_px=_box(0, 0, 8, 4)),
            fake_node(1, 1, "left", ROOT, 1, bounds_px=_box(0, 0, 3, 4)),
            fake_node(1, 2, "right", ROOT, 2, bounds_px=_box(5, 0, 3, 4)),
            fake_node(1, 3, "group", ROOT, 3, type="grouplayer"),
            fake_node(1, 4, "inner", GROUP, 0, bounds_px=_box(2, 1, 4, 2)),
            fake_node(1, 5, "held", ROOT, 4, type="grouplayer"),
            fake_node(1, 6, "locked", HELD, 0, bounds_px=_box(0, 3, 8, 1)),
        ]
        tree["active_id"] = LEFT
        for index, layer in enumerate((BASE, LEFT, RIGHT, LOCKED, LOCKED, INNER)):
            self.port.layer_pixels[layer] = bytes([10 * index + 5, 40, 90, 255])
        handle.protected = {BASE, LOCKED}
        self.port.render[1] = self.render
        return document_id, handle

    def render(self, tree: dict[str, Any]) -> bytes:
        found = {node["id"]: node for node in tree["nodes"]}
        below = nodes.children(tree)
        out = bytearray(bytes(4) * 32)

        def draw(node_id: str, shown: bool) -> None:
            node = found[node_id]
            shown = shown and (node["visible"] or self.leaky)
            if shown and node["type"] == "paintlayer":
                box = node["bounds_px"]
                pixel = self.port.layer_pixels.get(node_id, UNREAD)
                for y in range(box["y"], box["y"] + box["height"]):
                    for x in range(box["x"], box["x"] + box["width"]):
                        out[(y * 8 + x) * 4 : (y * 8 + x) * 4 + 4] = pixel
            for child in below.get(node_id, []):
                draw(child, shown)

        for child in below.get(tree["root_id"], []):
            draw(child, True)
        return bytes(out)

    def tree(self) -> dict[str, Any]:
        found: dict[str, Any] = self.port.tree(self.port.documents()[0])
        return found

    def kids(self, parent_id: str = ROOT) -> list[str]:
        return nodes.children(self.tree()).get(parent_id, [])

    def composite(self) -> bytes:
        self.port.refresh(self.port.documents()[0])
        found: bytes = self.port.composite(self.port.documents()[0])
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
        call = Call(f"op-{next(self.ids):032x}", request_id, A)
        self.ops["protection.set"](args, call)

    def mask(self, document_id: str, layer: str = INNER) -> str:
        args = {
            "document_id": document_id,
            "parent_id": layer,
            "above_id": None,
            "type": "transparency_mask",
            "name": "soft",
            "coverage": "all",
        }
        made: str = self.run("layer.create", args)["layer_id"]
        return made

    def history(self, document_id: str, action: str, steps: int) -> dict[str, Any]:
        args = {"document_id": document_id, "action": action, "steps": steps}
        return self.run("history.step", args)


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


def _duplicate(document_id: str, layer: str, name: str = "trial") -> dict[str, Any]:
    return {"document_id": document_id, "layer_id": layer, "name": name}


def _reorder(document_id: str, layer: str, parent: str, above: str | None) -> dict[str, Any]:
    return {"document_id": document_id, "layer_id": layer, "parent_id": parent, "above_id": above}


def _remove(document_id: str, layer: str, verify: str = "region") -> dict[str, Any]:
    return {"document_id": document_id, "layer_id": layer, "verify": verify}


@pytest.mark.parametrize(
    "op",
    ["layer.duplicate", "layer.reorder", "layer.remove"],
)
def test_the_root_is_no_layer_to_change(world: World, op: str) -> None:
    document_id, handle = world.document()
    # Krita's root has a layer id like any node.
    root = layer_id(1, 999)
    tree = world.port._tree(1)
    for node in tree["nodes"]:
        if node["parent_id"] == ROOT:
            node["parent_id"] = root
    tree["root_id"] = root
    args = {
        "layer.duplicate": _duplicate(document_id, root),
        "layer.reorder": _reorder(document_id, root, GROUP, None),
        "layer.remove": _remove(document_id, root),
    }[op]
    body = world.refused(op, args)
    assert body["code"] == "INVALID_ARGUMENT" and body["details"] == {"layer_id": root}
    assert not handle.dirty


def _clean(world: World, handle: Handle, before: dict[str, Any]) -> None:
    # A rollback put the tree back, and left nothing on the ledger.
    assert world.tree()["nodes"] == before["nodes"] or _watched(world.tree()) == _watched(before)
    assert not handle.unsafe and handle.ledger.steps == [] and handle.ledger.applied == 0


def _watched(tree: dict[str, Any]) -> dict[str, Any]:
    return {node["id"]: {**node, "bounds_px": None} for node in tree["nodes"]}


# The fingerprint.


def test_the_fingerprint_sees_a_move_but_not_the_global_selection_mask(world: World) -> None:
    world.document()
    tree = world.tree()
    moved = {
        **tree,
        "nodes": [
            {**node, "parent_id": GROUP, "order": 1} if node["id"] == RIGHT else node
            for node in tree["nodes"]
        ],
    }
    assert ledger.node_states(moved) != ledger.node_states(tree)
    # The global selection's mask under the root, below every layer, shifts no rank.
    masked = {
        **tree,
        "nodes": [
            *({**node, "order": node["order"] + 1} for node in tree["nodes"]),
            fake_node(1, 800, "Selection Mask", ROOT, 0, type="selectionmask"),
        ],
    }
    assert ledger.node_states(masked) == ledger.node_states(tree)


def test_a_cleared_selection_with_a_layer_above_its_mask_undoes_and_redoes(world: World) -> None:
    document_id, handle = world.document()
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
    args = {
        "document_id": document_id,
        "parent_id": ROOT,
        "above_id": None,
        "type": "paint",
        "name": "top",
        "coverage": None,
    }
    world.run("layer.create", args)
    world.run("selection.set", {**selection, "shape": {"kind": "none"}})
    assert world.history(document_id, "undo", 1)["verified"] is True
    assert world.port.selection_bounds(handle.document) is not None
    assert world.history(document_id, "redo", 1)["verified"] is True
    assert world.port.selection_bounds(handle.document) is None


# The fake's undo of a node command keeps what was written since (K22).


def test_undoing_an_add_keeps_a_property_written_since(world: World) -> None:
    document_id, handle = world.document()
    made = world.run("layer.create", {
        "document_id": document_id,
        "parent_id": ROOT,
        "above_id": None,
        "type": "paint",
        "name": "kept",
        "coverage": None,
    })["layer_id"]  # fmt: skip
    world.port.set_properties(handle.document, made, {"opacity": 10})
    world.port.undo(handle.document)
    assert made not in world.kids()
    world.port.redo(handle.document)
    assert next(n for n in world.tree()["nodes"] if n["id"] == made)["opacity"] == 10


# Duplicate.


def test_a_protected_layer_is_copied_hidden_above_it(world: World) -> None:
    document_id, handle = world.document()
    composite = world.composite()
    result = world.run("layer.duplicate", _duplicate(document_id, BASE))
    copy = result["layer_id"]
    assert result == {
        "document_id": document_id,
        "layer_id": copy,
        "derived_from": BASE,
        "parent_id": ROOT,
        "above_id": BASE,
        "name": "trial",
        "visible": False,
        "id_map": {BASE: copy},
        "protected": False,
        "undo_steps": 1,
        "verification": result["verification"],
    }
    assert result["verification"]["mode"] == "region" and result["verification"]["changed_px"] == 0
    assert world.kids()[:2] == [BASE, copy] and copy not in handle.protected
    assert world.composite() == composite
    [step] = handle.ledger.steps
    assert (step.op, step.label) == ("layer.duplicate", history.ADD)


def test_a_group_copy_maps_every_node_and_copies_the_masks_coverage(world: World) -> None:
    document_id, handle = world.document()
    mask = world.mask(document_id)
    result = world.run("layer.duplicate", _duplicate(document_id, GROUP, "group trial"))
    id_map = result["id_map"]
    assert list(id_map) == [GROUP, INNER, mask] and len(set(id_map.values())) == 3
    copied = {node["id"]: node for node in world.tree()["nodes"]}
    assert [copied[id_map[one]]["name"] for one in (GROUP, INNER, mask)] == [
        "group trial",
        "inner",
        "soft",
    ]
    assert copied[id_map[INNER]]["parent_id"] == id_map[GROUP]
    assert world.port.buffers[id_map[mask]] == world.port.buffers[mask]
    assert not set(id_map.values()) & handle.protected


def test_a_copy_krita_showed_is_rolled_back(world: World) -> None:
    document_id, handle = world.document()
    before = world.tree()
    world.port.copy_visible = True
    body = world.refused("layer.duplicate", _duplicate(document_id, LEFT))
    assert body["code"] == "INTERNAL_ERROR"
    assert (body["details"]["rolled_back"], body["details"]["rollback_verified"]) == (True, True)
    _clean(world, handle, before)


def _recoloured(world: World) -> None:
    # The copy shows in a colour of its own, so a Krita that drew it hidden changes the composite.
    world.leaky = True

    def recolour(tree: dict[str, Any], node: dict[str, Any]) -> None:
        world.port.layer_pixels[node["id"]] = bytes([1, 2, 3, 255])

    world.port.on_layer.append(recolour)


def test_a_hidden_copy_that_changed_the_composite_is_rolled_back(world: World) -> None:
    document_id, handle = world.document()
    before = world.tree()
    _recoloured(world)
    body = world.refused("layer.duplicate", _duplicate(document_id, LEFT))
    # The left layer shows 7 of its 12 pixels; the inner and locked layers cover the rest.
    assert body["code"] == "INTERNAL_ERROR" and body["details"]["changed_px"] == 7
    assert (body["details"]["rolled_back"], body["details"]["rollback_verified"]) == (True, True)
    _clean(world, handle, before)


def test_a_copy_that_reached_outside_the_allowed_mask_is_protected_region_changed(
    world: World,
) -> None:
    document_id, handle = world.document()
    world.allow(document_id, _box(4, 0, 4, 4))
    before = world.tree()
    _recoloured(world)
    body = world.refused("layer.duplicate", _duplicate(document_id, LEFT))
    assert body["code"] == "PROTECTED_REGION_CHANGED"
    assert body["details"]["verification"]["changed_outside_px"] == 7
    _clean(world, handle, before)


@pytest.mark.parametrize(
    ("layer", "code"),
    [
        (layer_id(1, 99), "LAYER_NOT_FOUND"),
    ],
    ids=["unknown"],
)
def test_a_duplicate_is_refused_for_what_is_no_layer(world: World, layer: str, code: str) -> None:
    document_id, handle = world.document()
    assert world.refused("layer.duplicate", _duplicate(document_id, layer))["code"] == code
    assert not handle.dirty and handle.ledger.steps == []


def test_a_mask_is_not_duplicated_alone(world: World) -> None:
    document_id, _ = world.document()
    mask = world.mask(document_id)
    body = world.refused("layer.duplicate", _duplicate(document_id, mask))
    assert (
        body["code"] == "INVALID_ARGUMENT" and body["details"]["layer_type"] == "transparencymask"
    )


@pytest.mark.parametrize(
    "changes",
    [{"layer_id": "not-an-id"}, {"name": ""}, {"name": 3}],
    ids=["layer_id", "empty_name", "name_type"],
)
def test_a_duplicates_arguments_are_checked(world: World, changes: dict[str, Any]) -> None:
    document_id, _ = world.document()
    body = world.refused("layer.duplicate", {**_duplicate(document_id, LEFT), **changes})
    assert body["code"] == "INVALID_ARGUMENT"


def test_a_raise_after_krita_attached_the_copy_is_undone(world: World) -> None:
    document_id, handle = world.document()
    before = world.tree()
    world.port.fail["attach_after"] = RuntimeError("libkis failed")
    body = world.refused("layer.duplicate", _duplicate(document_id, LEFT))
    details = body["details"]
    assert (details["rolled_back"], details["rollback_verified"]) == (True, True)
    assert details["history_sealed"] is True
    assert not handle.unsafe and _watched(world.tree()) == _watched(before)


# Reorder.


def test_a_layer_moves_into_a_group_in_two_steps(world: World) -> None:
    document_id, handle = world.document()
    result = world.run("layer.reorder", _reorder(document_id, RIGHT, GROUP, INNER))
    assert result == {
        "document_id": document_id,
        "layer_id": RIGHT,
        "parent_id": GROUP,
        "above_id": INNER,
        "effective_order": [INNER, RIGHT],
        "undo_steps": 2,
        "verification": result["verification"],
    }
    assert result["verification"]["mode"] == "full"
    assert world.kids() == [BASE, LEFT, GROUP, HELD] and world.kids(GROUP) == [INNER, RIGHT]
    steps = handle.ledger.steps
    assert [(step.op, step.label) for step in steps] == [
        ("layer.reorder", history.REMOVE),
        ("layer.reorder", history.ADD),
    ]
    assert steps[0].operation_id == steps[1].operation_id


def test_a_group_moves_with_every_node_inside_it_added_back(world: World) -> None:
    document_id, handle = world.document()
    mask = world.mask(document_id)
    world.run("layer.reorder", _reorder(document_id, RIGHT, GROUP, INNER))
    result = world.run("layer.reorder", _reorder(document_id, GROUP, ROOT, BASE))
    # Krita's remove takes each node off its parent, so each comes back in its own step.
    assert result["undo_steps"] == 5
    assert world.kids() == [BASE, GROUP, LEFT, HELD]
    assert world.kids(GROUP) == [INNER, RIGHT] and world.kids(INNER) == [mask]
    assert [step.label for step in handle.ledger.steps[-5:]] == [history.REMOVE] + [history.ADD] * 4
    assert len({step.operation_id for step in handle.ledger.steps[-5:]}) == 1
    split = world.refused(
        "history.step", {"document_id": document_id, "action": "undo", "steps": 2}
    )
    assert split["details"]["steps_needed"] == 5
    world.history(document_id, "undo", 5)
    assert world.kids() == [BASE, LEFT, GROUP, HELD] and world.kids(GROUP) == [INNER, RIGHT]
    world.history(document_id, "redo", 5)
    assert world.kids() == [BASE, GROUP, LEFT, HELD] and world.kids(INNER) == [mask]


def test_a_raise_while_adding_back_a_child_is_undone_and_confirmed(world: World) -> None:
    document_id, handle = world.document()
    before = world.tree()
    original, calls = world.port.attach, []

    def failing(document: Any, node: Any, parent_id: str, above_id: str | None) -> str:
        calls.append(parent_id)
        if len(calls) == 2:
            raise RuntimeError("libkis failed")
        return original(document, node, parent_id, above_id)

    world.port.attach = failing  # type: ignore[method-assign]
    body = world.refused("layer.reorder", _reorder(document_id, GROUP, ROOT, BASE))
    details = body["details"]
    assert (details["rolled_back"], details["rollback_verified"]) == (True, True)
    assert not handle.unsafe and _watched(world.tree()) == _watched(before)
    assert handle.ledger.steps == []


def test_a_layer_moves_to_the_top_and_out_of_a_group(world: World) -> None:
    document_id, _ = world.document()
    world.run("layer.reorder", _reorder(document_id, INNER, ROOT, None))
    assert world.kids() == [BASE, LEFT, RIGHT, GROUP, HELD, INNER] and world.kids(GROUP) == []
    world.run("layer.reorder", _reorder(document_id, INNER, ROOT, BASE))
    assert world.kids() == [BASE, INNER, LEFT, RIGHT, GROUP, HELD]


def test_a_layer_already_in_place_moves_nothing(world: World) -> None:
    document_id, handle = world.document()
    calls = len(world.port.calls)
    result = world.run("layer.reorder", _reorder(document_id, LEFT, ROOT, BASE))
    assert (result["undo_steps"], result["verification"]) == (0, None)
    assert result["effective_order"] == [BASE, LEFT, RIGHT, GROUP, HELD]
    assert handle.dirty and handle.ledger.steps == []
    assert "undo" not in world.port.calls[calls:] and world.port.live[1].get("stack", []) == []


def test_a_leaking_move_is_undone_in_both_steps(world: World) -> None:
    document_id, handle = world.document()
    # Under the left layer, the inner one no longer shows where they overlap, at x 2.
    world.allow(document_id, _box(3, 0, 5, 4))
    before = world.tree()
    composite = world.composite()
    body = world.refused("layer.reorder", _reorder(document_id, INNER, ROOT, BASE))
    details = body["details"]
    assert body["code"] == "PROTECTED_REGION_CHANGED"
    assert (details["rolled_back"], details["rollback_verified"]) == (True, True)
    assert details["history_sealed"] is False
    _clean(world, handle, before)
    assert world.composite() == composite
    # Krita keeps both undone steps as redos (K43), which history refuses.
    assert world.port.undo_labels(handle.document) == (None, history.REMOVE)
    assert world.refused("history.step", {"document_id": document_id, "action": "redo", "steps": 1})


@pytest.mark.parametrize(
    "fail",
    ["remove_node", "remove_node_after", "attach", "attach_after"],
    ids=["before_the_remove", "after_the_remove", "before_the_add", "after_the_add"],
)
def test_a_raise_around_either_step_is_undone_and_confirmed(world: World, fail: str) -> None:
    document_id, handle = world.document()
    before = world.tree()
    world.port.fail[fail] = RuntimeError("libkis failed")
    body = world.refused("layer.reorder", _reorder(document_id, RIGHT, GROUP, INNER))
    details = body["details"]
    assert body["code"] == "INTERNAL_ERROR" and details["rollback_verified"] is True
    assert details["rolled_back"] is (fail != "remove_node")
    # A step was named and never pushed, so Krita may hold it.
    assert details["history_sealed"] is True
    assert not handle.unsafe and _watched(world.tree()) == _watched(before)
    assert handle.ledger.steps == [] and not handle.dirty


def test_a_move_krita_placed_elsewhere_is_rolled_back(world: World) -> None:
    document_id, handle = world.document()
    before = world.tree()

    def misplace(tree: dict[str, Any], node: dict[str, Any]) -> None:
        # Krita put it at the bottom of the group, under the inner layer.
        for other in tree["nodes"]:
            if other["parent_id"] == node["parent_id"] and other is not node:
                other["order"] += 1
        node["order"] = 0

    world.port.on_layer.append(misplace)
    body = world.refused("layer.reorder", _reorder(document_id, RIGHT, GROUP, INNER))
    assert body["code"] == "INTERNAL_ERROR" and body["details"]["layer_id"] == RIGHT
    assert (body["details"]["rolled_back"], body["details"]["rollback_verified"]) == (True, True)
    _clean(world, handle, before)


def test_a_reorder_that_could_not_be_undone_is_rollback_failed(world: World) -> None:
    document_id, handle = world.document()
    world.allow(document_id, _box(3, 0, 5, 4))
    world.port.undo_works = False
    body = world.refused("layer.reorder", _reorder(document_id, INNER, ROOT, BASE))
    assert body["code"] == "ROLLBACK_FAILED" and body["details"]["cause"] == (
        "PROTECTED_REGION_CHANGED"
    )
    assert handle.unsafe


@pytest.mark.parametrize(
    ("args", "code", "detail"),
    [
        ((BASE, ROOT, None), "LOCKED_TARGET", {"protected_layer_ids": [BASE]}),
        ((HELD, ROOT, None), "LOCKED_TARGET", {"protected_layer_ids": [LOCKED]}),
        ((LEFT, RIGHT, None), "INVALID_ARGUMENT", {"layer_type": "paintlayer"}),
        ((LEFT, GROUP, RIGHT), "INVALID_ARGUMENT", {"above_id": RIGHT}),
        ((LEFT, layer_id(1, 99), None), "LAYER_NOT_FOUND", {"layer_id": layer_id(1, 99)}),
    ],
    ids=[
        "protected",
        "holds_protected",
        "parent_not_a_group",
        "above_elsewhere",
        "no_parent",
    ],
)
def test_a_reorder_is_refused_where_it_cannot_go(
    world: World, args: tuple[str, str, str | None], code: str, detail: dict[str, Any]
) -> None:
    document_id, handle = world.document()
    body = world.refused("layer.reorder", _reorder(document_id, *args))
    assert body["code"] == code and detail.items() <= body["details"].items()
    assert not handle.dirty and handle.ledger.steps == []


def test_a_group_cannot_go_inside_itself(world: World) -> None:
    document_id, _ = world.document()
    args = {
        "document_id": document_id,
        "parent_id": GROUP,
        "above_id": None,
        "type": "group",
        "name": "nested",
        "coverage": None,
    }
    nested = world.run("layer.create", args)["layer_id"]
    body = world.refused("layer.reorder", _reorder(document_id, GROUP, nested, None))
    assert body["code"] == "INVALID_ARGUMENT" and body["details"]["parent_id"] == nested


@pytest.mark.parametrize(
    ("args", "field"),
    [((LEFT, LEFT, None), "parent_id"), ((LEFT, ROOT, LEFT), "above_id")],
    ids=["inside_itself", "above_itself"],
)
def test_a_layer_cannot_go_inside_or_above_itself(
    world: World, args: tuple[str, str, str | None], field: str
) -> None:
    document_id, _ = world.document()
    body = world.refused("layer.reorder", _reorder(document_id, *args))
    assert body["code"] == "INVALID_ARGUMENT" and body["details"] == {"field": field}


def test_a_mask_is_not_moved(world: World) -> None:
    document_id, _ = world.document()
    mask = world.mask(document_id)
    body = world.refused("layer.reorder", _reorder(document_id, mask, ROOT, None))
    assert body["code"] == "INVALID_ARGUMENT"


@pytest.mark.parametrize("op", ["layer.reorder", "layer.remove"])
@pytest.mark.parametrize("source", [RIGHT, None], ids=["named", "unnamed"])
def test_a_clones_source_is_refused(world: World, op: str, source: str | None) -> None:
    document_id, handle = world.document()
    clone = layer_id(1, 50)
    world.port.reach[1] = {"styled": [], "clones": {clone: source}, "animated": False}
    args = (
        _reorder(document_id, RIGHT, GROUP, None)
        if op == "layer.reorder"
        else _remove(document_id, RIGHT, "full")
    )
    body = world.refused(op, args)
    assert body["code"] == "UNSUPPORTED_CAPABILITY"
    assert body["details"] == {"layer_id": RIGHT, "reason": "clone_source", "clone_ids": [clone]}
    assert not handle.dirty


def test_history_moves_a_reorders_two_steps_together(world: World) -> None:
    document_id, _ = world.document()
    world.run("layer.reorder", _reorder(document_id, RIGHT, GROUP, INNER))
    stack = list(world.port.live[1]["stack"])
    split = world.refused(
        "history.step", {"document_id": document_id, "action": "undo", "steps": 1}
    )
    assert split["code"] == "INVALID_ARGUMENT" and split["details"]["steps_needed"] == 2
    assert world.port.live[1]["stack"] == stack and world.port.live[1]["index"] == 2
    assert world.history(document_id, "undo", 2)["steps_applied"] == 2
    assert world.kids()[2] == RIGHT and world.kids(GROUP) == [INNER]
    split = world.refused(
        "history.step", {"document_id": document_id, "action": "redo", "steps": 1}
    )
    assert split["details"]["steps_needed"] == 2 and world.port.live[1]["index"] == 0
    assert world.history(document_id, "redo", 2)["verified"] is True
    assert world.kids(GROUP) == [INNER, RIGHT]


# Remove.


def test_a_layer_is_removed_in_one_step(world: World) -> None:
    document_id, handle = world.document()
    composite = world.composite()
    result = world.run("layer.remove", _remove(document_id, LEFT))
    assert result == {
        "document_id": document_id,
        "layer_id": LEFT,
        "removed": [LEFT],
        "undo_steps": 1,
        "verification": result["verification"],
    }
    assert result["verification"]["mode"] == "region"
    assert result["verification"]["changed_px"] == 7 and world.composite() != composite
    assert LEFT not in world.kids()
    [step] = handle.ledger.steps
    assert (step.op, step.label) == ("layer.remove", history.REMOVE)
    # Undone, the same layer comes back where it was.
    world.history(document_id, "undo", 1)
    assert world.kids() == [BASE, LEFT, RIGHT, GROUP, HELD] and world.composite() == composite


def test_a_group_goes_with_its_subtree(world: World) -> None:
    document_id, _ = world.document()
    mask = world.mask(document_id)
    result = world.run("layer.remove", _remove(document_id, GROUP))
    assert result["removed"] == [GROUP, INNER, mask]
    assert GROUP not in world.kids()


def test_a_transparency_mask_is_removed_unless_its_line_is_held(world: World) -> None:
    document_id, handle = world.document()
    mask = world.mask(document_id)
    handle.protected.add(GROUP)
    body = world.refused("layer.remove", _remove(document_id, mask))
    assert body["code"] == "LOCKED_TARGET" and body["details"]["protected_layer_ids"] == [GROUP]
    handle.protected.discard(GROUP)
    assert world.run("layer.remove", _remove(document_id, mask))["removed"] == [mask]


@pytest.mark.parametrize(
    ("layer", "code"),
    [(BASE, "LOCKED_TARGET"), (HELD, "LOCKED_TARGET")],
    ids=["protected", "holds_protected"],
)
def test_a_remove_is_refused_for_what_is_protected(world: World, layer: str, code: str) -> None:
    document_id, handle = world.document()
    assert world.refused("layer.remove", _remove(document_id, layer))["code"] == code
    assert not handle.dirty and handle.ledger.steps == []


def test_a_selection_mask_is_not_removed(world: World) -> None:
    document_id, _ = world.document()
    mask = world.port.mask(1, LEFT)
    world.port._tree(1)["active_id"] = LEFT
    body = world.refused("layer.remove", _remove(document_id, mask))
    assert body["code"] == "INVALID_ARGUMENT" and body["details"]["layer_type"] == "selectionmask"


def test_the_last_layer_stays(world: World) -> None:
    document_id = world.run("document.create", CREATE)["document_id"]
    only = world.port._tree(1)["nodes"][0]["id"]
    body = world.refused("layer.remove", _remove(document_id, only, "full"))
    assert body["code"] == "INVALID_ARGUMENT" and body["details"] == {"layer_id": only}


def test_a_remove_past_a_filter_layer_needs_full_scope(world: World) -> None:
    document_id, _ = world.document()
    tree = world.port._tree(1)
    tree["nodes"].append(fake_node(1, 60, "blur", ROOT, 5, type="filterlayer"))
    body = world.refused("layer.remove", _remove(document_id, LEFT))
    assert body["code"] == "UNSUPPORTED_CAPABILITY"
    assert body["details"]["reasons"][0]["reason"] == "filter_layer"
    assert world.run("layer.remove", _remove(document_id, LEFT, "full"))["removed"] == [LEFT]


def test_a_leaking_removal_is_rolled_back(world: World) -> None:
    document_id, handle = world.document()
    world.allow(document_id, _box(4, 0, 4, 4))
    before = world.tree()
    body = world.refused("layer.remove", _remove(document_id, LEFT))
    assert body["code"] == "PROTECTED_REGION_CHANGED"
    assert (body["details"]["rolled_back"], body["details"]["rollback_verified"]) == (True, True)
    _clean(world, handle, before)


def test_a_raise_after_krita_removed_is_undone(world: World) -> None:
    document_id, handle = world.document()
    before = world.tree()
    world.port.fail["remove_node_after"] = RuntimeError("libkis failed")
    body = world.refused("layer.remove", _remove(document_id, LEFT))
    assert (body["details"]["rolled_back"], body["details"]["rollback_verified"]) == (True, True)
    assert not handle.unsafe and _watched(world.tree()) == _watched(before)


def test_a_removal_that_changed_another_layer_is_caught(world: World) -> None:
    document_id, handle = world.document()
    original = world.port.remove_node

    def wider(document: Any, layer: str) -> Any:
        taken = original(document, layer)
        world.port._tree(1)["nodes"][0]["name"] = "renamed"
        return taken

    world.port.remove_node = wider  # type: ignore[method-assign,assignment]
    body = world.refused("layer.remove", _remove(document_id, LEFT))
    # Krita's undo does not take back a name (K22), so nothing confirms the document.
    assert body["code"] == "ROLLBACK_FAILED" and body["details"]["cause"] == "INTERNAL_ERROR"
    assert body["details"]["layer_ids"] == [BASE] and handle.unsafe
