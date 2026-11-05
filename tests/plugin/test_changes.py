import hashlib
import itertools
import json
import os
from pathlib import Path
from typing import Any

import pytest
from bridge_core import (
    closing,
    documents,
    harness,
    history,
    nodes,
    protection,
    selections,
    transfer,
)
from bridge_core.errors import BridgeError
from bridge_core.jobs import Call
from bridge_core.ledger import Ledger, Step, fingerprint
from bridge_core.registry import Handle, Registry
from fake_krita import FakeDocument, FakePort, fake_node, layer_id

A: dict[str, Any] = {"pid": 101, "started_at": "Sat Oct 24 10:00:00 2026"}
CREATE = {
    "name": "sketch",
    "size_px": [8, 4],
    "color_model": "RGBA",
    "depth": "U8",
    "profile_id": documents.SRGB_PROFILE,
    "background": "transparent",
}
NO_MODIFIERS = {"grow_px": 0, "shrink_px": 0, "feather_px": 0, "invert": False}


class World:
    def __init__(self, tmp: Path) -> None:
        self.data = tmp / "data"
        self.art = tmp / "art"
        (self.data / "harness").mkdir(parents=True)
        self.art.mkdir()
        roots = {"v": 1, "roots": [os.path.realpath(self.art)]}
        (self.data / "config.json").write_text(json.dumps(roots))
        self.port = FakePort()
        self.registry = Registry(self.port, lambda client: True)
        self.ops = {
            **documents.handlers(self.registry, self.port, self.data),
            **harness.handlers(self.registry, self.port, self.data),
        }
        self.ids = itertools.count(1)

    def run(self, op: str, args: dict[str, Any], request_id: str = "") -> dict[str, Any]:
        number = next(self.ids)
        call = Call(f"op-{number}", request_id or f"req-{number}", A)
        return self.ops[op](args, call)

    def refused(self, op: str, args: dict[str, Any], request_id: str = "") -> dict[str, Any]:
        with pytest.raises(BridgeError) as raised:
            self.run(op, args, request_id)
        body: dict[str, Any] = raised.value.body
        return body

    def created(self) -> tuple[str, Handle]:
        document_id = self.run("document.create", CREATE)["document_id"]
        handle = self.registry.find(document_id)
        # A group with one layer inside, both protected, over the created layer.
        key = handle.document.key
        tree = self.port._tree(key)
        root = tree["root_id"]
        group = fake_node(key, 1, "group", root, 1, type="grouplayer")
        inner = fake_node(key, 2, "inner", group["id"], 0)
        tree["nodes"] += [group, inner]
        handle.protected = {group["id"], inner["id"]}
        return document_id, handle

    def layer(self, document_id: str, **changes: Any) -> dict[str, Any]:
        handle = self.registry.find(document_id)
        args = {
            "document_id": document_id,
            "parent_id": self.port._tree(handle.document.key)["root_id"],
            "above_id": None,
            "type": "paint",
            "coverage": None,
            "name": "repair",
            **changes,
        }
        return self.run("layer.create", args)

    def mask(self, data: bytes, width: int, height: int, request_id: str) -> dict[str, Any]:
        folder = self.data / "transfer"
        folder.mkdir(exist_ok=True)
        digest = hashlib.sha256(data).hexdigest()
        key = hashlib.sha256(request_id.encode()).hexdigest()[:16]
        path = folder / f"mask-{key}-{digest}.a8"
        path.write_bytes(data)
        return {"path": str(path), "size_px": [width, height], "format": "A8", "sha256": digest}

    def select(
        self,
        document_id: str,
        shape: dict[str, Any],
        combine: str = "replace",
        request_id: str = "",
        **modifiers: Any,
    ) -> dict[str, Any]:
        args = {
            "document_id": document_id,
            "combine": combine,
            "shape": shape,
            **NO_MODIFIERS,
            **modifiers,
        }
        return self.run("selection.set", args, request_id)

    def rect_shape(
        self, request_id: str, x: int, y: int, width: int, height: int, value: int = 255
    ) -> dict[str, Any]:
        spec = self.mask(bytes([value]) * (width * height), width, height, request_id)
        return {"kind": "mask", "origin_px": [x, y], "mask": spec, "source_path": None}

    def history(self, document_id: str, action: str, steps: int = 1) -> dict[str, Any]:
        return self.run(
            "history.step", {"document_id": document_id, "action": action, "steps": steps}
        )

    def protect(self, document_id: str, **changes: Any) -> dict[str, Any]:
        handle = self.registry.find(document_id)
        request_id = changes.pop("request_id", "")
        args = {
            "document_id": document_id,
            "protected_layer_ids": sorted(handle.protected),
            "allowed_change_mask": None,
            "preserve_composite_alpha": False,
            "preserve_canvas": False,
            **changes,
        }
        return self.run("protection.set", args, request_id)

    def selection_canvas(self, handle: Handle) -> bytes | None:
        return self.port.selection_rect(handle.document, {"x": 0, "y": 0, "width": 8, "height": 4})

    def transfers(self) -> list[str]:
        folder = self.data / "transfer"
        return sorted(entry.name for entry in folder.iterdir()) if folder.exists() else []


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


def _ids(world: World, handle: Handle) -> list[str]:
    return [node["id"] for node in world.port._tree(handle.document.key)["nodes"]]


# The ledger.


def _step(name: str) -> Step:
    return Step(name, f"op-{name}", "Add Layer", ((), None), (((name, "normal"),), None))


def test_a_push_deletes_the_redo_tail_and_the_redos_it_allowed() -> None:
    ledger = Ledger()
    for name in "abc":
        ledger.push(_step(name), 30)
    ledger.undone()
    ledger.undone()
    assert (ledger.applied, ledger.redo, ledger.undo_available()) == (1, 2, 1)
    ledger.push(_step("d"), 30)
    assert [step.op for step in ledger.steps] == ["a", "d"]
    assert (ledger.applied, ledger.redo) == (2, 0)


def test_a_rollback_leaves_no_redo_of_the_step_it_undid() -> None:
    ledger = Ledger()
    ledger.push(_step("a"), 30)
    ledger.undone()
    ledger.redone()
    ledger.push(_step("b"), 30)
    ledger.rolled_back()
    assert ([step.op for step in ledger.steps], ledger.applied, ledger.redo) == (["a"], 1, 0)


def test_the_floor_and_krita_s_undo_limit_bound_what_can_be_undone() -> None:
    ledger = Ledger()
    for name in "abcde":
        ledger.push(_step(name), 3)
    # Krita kept the last three.
    assert ledger.undo_available() == 3
    ledger.undone()
    ledger.seal()
    assert (ledger.undo_available(), ledger.redo) == (0, 0)
    ledger.push(_step("f"), 3)
    assert ledger.undo_available() == 1


# K46: the node made active in place of a selection mask.


def _tree(active: str, *extra: dict[str, Any]) -> dict[str, Any]:
    nodes_ = [
        fake_node(1, 0, "base", "root", 0),
        fake_node(1, 1, "top", "root", 1),
        fake_node(1, 2, "local", layer_id(1, 0), 0, type="selectionmask"),
        fake_node(1, 3, "global", "root", 2, type="selectionmask"),
        *extra,
    ]
    return {"root_id": "root", "active_id": active, "nodes": nodes_}


def test_no_active_selection_mask_needs_no_change() -> None:
    assert nodes.unmasked(_tree(layer_id(1, 0))) is None


def test_a_local_mask_gives_way_to_its_layer() -> None:
    assert nodes.unmasked(_tree(layer_id(1, 2))) == layer_id(1, 0)


def test_the_global_selection_s_mask_gives_way_to_the_top_most_layer() -> None:
    assert nodes.unmasked(_tree(layer_id(1, 3))) == layer_id(1, 1)


def test_a_document_with_no_layer_to_activate_is_an_error() -> None:
    tree = {
        "root_id": "root",
        "active_id": "m",
        "nodes": [{"id": "m", "parent_id": "root", "type": "selectionmask", "order": 0}],
    }
    with pytest.raises(BridgeError) as raised:
        nodes.unmasked(tree)
    assert raised.value.body["code"] == "INTERNAL_ERROR"


def test_an_open_makes_a_layer_active_in_place_of_a_global_mask(world: World) -> None:
    source = world.art / "hero.ora"
    source.write_bytes(b"ora")
    world.port.files[str(source)] = {"names": ["base", "top"]}
    args = {
        "source_path": str(source),
        "source_sha256": hashlib.sha256(b"ora").hexdigest(),
        "mode": "read_only",
        "working_dir": None,
        "editable_layer_ids": None,
        "editable_layer_names": None,
    }
    opened_before = world.port.open
    root_masked: list[str] = []

    def open_masked(path: str) -> Any:
        document = opened_before(path)
        root_masked.append(world.port.mask(document.key, f"root-{document.key}"))
        return document

    world.port.open = open_masked  # type: ignore[method-assign]
    opened = world.run("document.open", args)
    assert opened["active_layer_id"] == layer_id(1, 1)
    assert not world.port.is_masked(1)


# layer.create.


def test_a_layer_is_created_where_asked_editable_and_dirty(world: World) -> None:
    document_id, handle = world.created()
    top = world.layer(document_id)
    assert top == {
        "document_id": document_id,
        "layer_id": top["layer_id"],
        "parent_id": "root-1",
        "above_id": None,
        "type": "paint",
        "coverage": None,
        "name": "repair",
        "protected": False,
        "undo_steps": 1,
        "verification": None,
    }
    # Null above_id puts the layer on top of the root's two children, as Krita does.
    over = world.layer(document_id, above_id=layer_id(1, 0), name="over")
    tree = world.port._tree(1)
    orders = {node["id"]: node["order"] for node in tree["nodes"]}
    assert orders[top["layer_id"]] == 3 and orders[over["layer_id"]] == 1
    assert orders[layer_id(1, 0)] == 0 and orders[layer_id(1, 1)] == 2
    assert handle.dirty and top["layer_id"] not in handle.protected
    assert [step.op for step in handle.ledger.steps] == ["layer.create", "layer.create"]
    assert handle.ledger.steps[0].label == history.LABELS["layer.create"]


def test_a_layer_may_go_inside_a_protected_group(world: World) -> None:
    document_id, handle = world.created()
    group = layer_id(1, 1)
    made = world.layer(document_id, parent_id=group, above_id=layer_id(1, 2), type="group")
    node = next(n for n in world.port._tree(1)["nodes"] if n["id"] == made["layer_id"])
    assert (node["parent_id"], node["type"], node["order"]) == (group, "grouplayer", 1)
    assert group in handle.protected


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"parent_id": layer_id(1, 0)}, "INVALID_ARGUMENT"),
        ({"parent_id": layer_id(9, 9)}, "LAYER_NOT_FOUND"),
        ({"above_id": layer_id(1, 2)}, "INVALID_ARGUMENT"),
        ({"above_id": layer_id(9, 9)}, "LAYER_NOT_FOUND"),
        ({"type": "transparency_mask"}, "INVALID_ARGUMENT"),
        ({"name": ""}, "INVALID_ARGUMENT"),
    ],
)
def test_a_layer_is_refused_where_it_cannot_go(
    world: World, changes: dict[str, Any], code: str
) -> None:
    document_id, handle = world.created()
    args = {
        "document_id": document_id,
        "parent_id": "root-1",
        "above_id": None,
        "type": "paint",
        "coverage": None,
        "name": "repair",
        **changes,
    }
    assert world.refused("layer.create", args)["code"] == code
    assert not handle.dirty and handle.ledger.steps == []


def test_a_layer_whose_creation_moved_a_protected_layer_is_rolled_back(world: World) -> None:
    document_id, handle = world.created()

    def fade(tree: dict[str, Any], node: dict[str, Any]) -> None:
        next(n for n in tree["nodes"] if n["id"] == layer_id(1, 2))["opacity"] = 10

    world.port.on_layer.append(fade)
    before = _ids(world, handle)
    body = world.refused(
        "layer.create",
        {
            "document_id": document_id,
            "parent_id": "root-1",
            "above_id": None,
            "type": "paint",
            "coverage": None,
            "name": "repair",
        },
    )
    assert body["code"] == "LOCKED_TARGET" and body["details"]["rolled_back"] is True
    assert body["details"]["layer_ids"] == [layer_id(1, 2)]
    assert _ids(world, handle) == before
    # The rollback is confirmed, so the document is as it was, and its redo is never offered.
    assert not handle.dirty and not handle.unsafe
    assert (handle.ledger.applied, handle.ledger.redo, handle.ledger.steps) == (0, 0, [])
    assert world.port.front_key == 1


def test_a_layer_krita_misplaced_is_rolled_back(world: World) -> None:
    document_id, _ = world.created()

    def misplace(tree: dict[str, Any], node: dict[str, Any]) -> None:
        node["order"] = 0

    world.port.on_layer.append(misplace)
    body = world.refused(
        "layer.create",
        {
            "document_id": document_id,
            "parent_id": "root-1",
            "above_id": None,
            "type": "paint",
            "coverage": None,
            "name": "repair",
        },
    )
    assert body["code"] == "INTERNAL_ERROR" and body["details"]["rolled_back"] is True


def test_a_rollback_that_cannot_be_confirmed_marks_the_document_unsafe(world: World) -> None:
    document_id, handle = world.created()
    world.port.on_layer.append(lambda tree, node: node.update(order=0))
    world.port.undo_works = False
    body = world.refused(
        "layer.create",
        {
            "document_id": document_id,
            "parent_id": "root-1",
            "above_id": None,
            "type": "paint",
            "coverage": None,
            "name": "repair",
        },
    )
    assert body["code"] == "ROLLBACK_FAILED" and handle.unsafe and handle.dirty
    assert world.refused("history.step", _undo(document_id))["code"] == "DOCUMENT_UNSAFE"


def test_a_create_krita_raised_in_after_adding_is_undone_and_history_sealed(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    document_id, handle = world.created()
    world.layer(document_id)
    before = _ids(world, handle)
    added = world.port.create_layer

    def raised_after(*args: Any) -> str:
        added(*args)
        raise RuntimeError("libkis failed")

    monkeypatch.setattr(world.port, "create_layer", raised_after)
    with pytest.raises(BridgeError) as raised:
        world.layer(document_id)
    body = raised.value.body
    assert body["code"] == "INTERNAL_ERROR" and body["retryable"] is False
    assert (body["details"]["rolled_back"], body["details"]["rollback_verified"]) == (True, True)
    # The step Krita pushed but the ledger never held is undone, and history stops below it.
    assert _ids(world, handle) == before and len(handle.ledger.steps) == 1
    assert world.port.undo_labels(handle.document) == ("Add Layer", "Add Layer")
    assert handle.dirty and not handle.unsafe and handle.ledger.undo_available() == 0


@pytest.mark.parametrize("whose", ["the owner's", "a read_only open"])
def test_a_read_only_document_refuses_every_new_mutation(world: World, whose: str) -> None:
    if whose == "the owner's":
        key = world.port.open_by_hand("their painting")
        [listed] = world.run("document.list", {})["documents"]
        document_id = listed["document_id"]
    else:
        source = world.art / "fixture.ora"
        source.write_bytes(b"ora")
        opened = world.run(
            "document.open",
            {
                "source_path": str(source),
                "source_sha256": hashlib.sha256(b"ora").hexdigest(),
                "mode": "read_only",
                "working_dir": None,
                "editable_layer_ids": None,
                "editable_layer_names": None,
            },
        )
        document_id, key = opened["document_id"], max(world.port.live)
    shape = world.rect_shape("req-shape", 0, 0, 1, 1)
    cases = [
        (
            "layer.create",
            {
                "document_id": document_id,
                "parent_id": f"root-{key}",
                "above_id": None,
                "type": "paint",
                "coverage": None,
                "name": "x",
            },
        ),
        (
            "selection.set",
            {"document_id": document_id, "combine": "replace", "shape": shape, **NO_MODIFIERS},
        ),
        (
            "protection.set",
            {
                "document_id": document_id,
                "protected_layer_ids": [],
                "allowed_change_mask": None,
                "preserve_composite_alpha": True,
                "preserve_canvas": False,
            },
        ),
        ("history.step", _undo(document_id)),
        (
            "layer.update",
            {
                "document_id": document_id,
                "layer_id": layer_id(key, 0),
                "properties": {"opacity": 0.5},
                "verify": "region",
            },
        ),
    ]
    for op, args in cases:
        assert world.refused(op, args, "req-shape")["code"] == "DOCUMENT_READ_ONLY"
    # The mask was taken before the refusal, so nothing is left behind.
    assert [name for name in world.transfers() if name.startswith("mask-")] == []


# selection.set.


def test_the_recipe_runs_the_shape_then_each_modifier_then_the_combine() -> None:
    shape: dict[str, Any] = {"kind": "mask", "origin_px": [1, 2], "mask": {}, "source_path": None}
    args = {"combine": "add", "grow_px": 2, "shrink_px": 1, "feather_px": 3, "invert": True}
    rect = {"x": 1, "y": 2, "width": 2, "height": 1}
    assert selections.recipe(shape, args, rect, b"\xff\xff") == [
        ("mask", rect, b"\xff\xff"),
        ("grow", 2),
        ("shrink", 1),
        ("feather", 3),
        ("invert",),
        ("combine", "add"),
    ]
    plain = {**args, "grow_px": 0, "shrink_px": 0, "feather_px": 0, "invert": False}
    assert selections.recipe({"kind": "all"}, plain, rect, None) == [
        ("all", rect),
        ("combine", "add"),
    ]
    assert selections.recipe({"kind": "none"}, plain, None, None) == [("clear",)]


def test_a_rect_selection_lands_and_crosses_as_a_transfer_file(world: World) -> None:
    document_id, handle = world.created()
    selected = world.select(document_id, world.rect_shape("req-a", 2, 1, 3, 2), request_id="req-a")
    assert selected["undo_steps"] == 1
    assert selected["selection"]["bounds_px"] == {"x": 2, "y": 1, "width": 3, "height": 2}
    assert Path(selected["selection"]["pixels"]["path"]).read_bytes() == b"\xff" * 6
    assert handle.dirty and handle.ledger.steps[-1].label == history.LABELS["selection.set"]
    # The mask was taken; only the readback waits for the server.
    assert world.transfers() == [Path(selected["selection"]["pixels"]["path"]).name]


def test_combine_adds_subtracts_and_intersects_with_the_current_selection(world: World) -> None:
    document_id, handle = world.created()
    world.select(document_id, world.rect_shape("req-a", 0, 0, 4, 4), request_id="req-a")
    world.select(document_id, world.rect_shape("req-b", 2, 0, 4, 4), "add", request_id="req-b")
    assert world.selection_canvas(handle) == (b"\xff" * 6 + b"\0" * 2) * 4
    world.select(document_id, world.rect_shape("req-c", 0, 0, 1, 4), "subtract", "req-c")
    assert world.selection_canvas(handle) == (b"\0" + b"\xff" * 5 + b"\0" * 2) * 4
    world.select(document_id, world.rect_shape("req-d", 4, 0, 4, 4), "intersect", "req-d")
    assert world.selection_canvas(handle) == (b"\0" * 4 + b"\xff" * 2 + b"\0" * 2) * 4


@pytest.mark.parametrize("combine", ["subtract", "intersect"])
def test_there_is_nothing_to_subtract_from_or_intersect_with(world: World, combine: str) -> None:
    document_id, handle = world.created()
    shape = world.rect_shape("req-a", 0, 0, 1, 1)
    args = {"document_id": document_id, "combine": combine, "shape": shape, **NO_MODIFIERS}
    assert world.refused("selection.set", args, "req-a")["code"] == "INVALID_ARGUMENT"
    assert world.transfers() == [] and not handle.dirty


def test_a_shape_off_the_canvas_is_refused_never_clipped(world: World) -> None:
    document_id, _ = world.created()
    shape = world.rect_shape("req-a", 6, 2, 3, 2)
    args = {"document_id": document_id, "combine": "replace", "shape": shape, **NO_MODIFIERS}
    body = world.refused("selection.set", args, "req-a")
    assert body["code"] == "INVALID_ARGUMENT" and body["details"]["canvas_px"] == [8, 4]
    assert world.transfers() == []


def test_a_mask_named_for_another_request_is_refused(world: World) -> None:
    document_id, _ = world.created()
    shape = world.rect_shape("req-other", 0, 0, 1, 1)
    args = {"document_id": document_id, "combine": "replace", "shape": shape, **NO_MODIFIERS}
    assert world.refused("selection.set", args, "req-mine")["code"] == "INVALID_ARGUMENT"


def test_a_raster_whose_file_is_outside_every_root_is_refused(world: World) -> None:
    document_id, _ = world.created()
    shape = {**world.rect_shape("req-a", 0, 0, 1, 1), "source_path": "/elsewhere/mask.png"}
    args = {"document_id": document_id, "combine": "replace", "shape": shape, **NO_MODIFIERS}
    assert world.refused("selection.set", args, "req-a")["code"] == "PATH_NOT_ALLOWED"


def test_none_clears_the_selection_in_one_undo_step(world: World) -> None:
    document_id, handle = world.created()
    world.select(document_id, world.rect_shape("req-a", 0, 0, 2, 2), request_id="req-a")
    cleared = world.select(document_id, {"kind": "none"})
    assert cleared == {"document_id": document_id, "selection": None, "undo_steps": 1}
    assert world.port.selection_bounds(handle.document) is None
    assert handle.ledger.steps[-1].label == history.LABELS["selection.clear"]


def test_none_with_no_selection_pushes_nothing_but_counts_as_a_change(world: World) -> None:
    document_id, handle = world.created()
    assert world.select(document_id, {"kind": "none"})["undo_steps"] == 0
    assert handle.ledger.steps == [] and world.port.recipes == [] and handle.dirty


def test_none_takes_no_modifiers(world: World) -> None:
    document_id, _ = world.created()
    args = {"document_id": document_id, "combine": "replace", "shape": {"kind": "none"}}
    assert world.refused("selection.set", {**args, **NO_MODIFIERS, "invert": True})["code"] == (
        "INVALID_ARGUMENT"
    )


def test_layer_alpha_and_all_select_through_krita(world: World) -> None:
    document_id, _ = world.created()
    world.select(document_id, {"kind": "layer_alpha", "layer_id": layer_id(1, 0)})
    world.select(document_id, {"kind": "all"})
    first, second = world.port.recipes
    assert first[0] == ("layer_alpha", layer_id(1, 0))
    assert second[0] == ("all", {"x": 0, "y": 0, "width": 8, "height": 4})
    group = {"kind": "layer_alpha", "layer_id": layer_id(1, 1)}
    args = {"document_id": document_id, "combine": "replace", "shape": group, **NO_MODIFIERS}
    assert world.refused("selection.set", args)["code"] == "UNSUPPORTED_CAPABILITY"


@pytest.mark.parametrize("field", ["grow_px", "shrink_px", "feather_px"])
def test_modifiers_are_whole_pixels_within_their_bound(world: World, field: str) -> None:
    document_id, _ = world.created()
    for value in (-1, 1.5, selections.MAX_MODIFIER_PX + 1, True):
        args = {
            "document_id": document_id,
            "combine": "replace",
            "shape": {"kind": "all"},
            **NO_MODIFIERS,
            field: value,
        }
        assert world.refused("selection.set", args)["code"] == "INVALID_ARGUMENT"


# protection.set.


def test_loosened_counts_the_pixels_a_new_mask_would_newly_allow() -> None:
    current = b"\xff\xff\0\0"
    assert protection.loosened(None, b"\0\0\0\0") == 0
    assert protection.loosened(None, None) == 0
    assert protection.loosened(current, None) == 2
    assert protection.loosened(current, b"\xff\0\0\0") == 0
    assert protection.loosened(current, b"\0\xff\xff\xff") == 2


def test_the_summary_names_the_allowed_box_and_count() -> None:
    mask = b"\0\0\0\0" + b"\0\xff\0\xff" + b"\0\0\xff\0"
    assert protection.summary(mask, 4) == {
        "sha256": hashlib.sha256(mask).hexdigest(),
        "bounds_px": {"x": 1, "y": 1, "width": 3, "height": 2},
        "allowed_pixels": 3,
    }
    assert protection.summary(b"\0" * 4, 2)["bounds_px"] == {
        "x": 0,
        "y": 0,
        "width": 0,
        "height": 0,
    }


def _mask_arg(
    world: World, request_id: str, x: int, y: int, width: int, height: int, value: int = 255
) -> dict[str, Any]:
    shape = world.rect_shape(request_id, x, y, width, height, value)
    return {key: shape[key] for key in ("origin_px", "mask", "source_path")}


def test_protection_tightens_sets_the_floor_and_dirties_nothing(world: World) -> None:
    document_id, handle = world.created()
    world.layer(document_id)
    mine = world.layer(document_id)["layer_id"]
    handle.dirty = False
    wanted = sorted(handle.protected | {mine})
    set_ = world.protect(
        document_id,
        protected_layer_ids=wanted,
        allowed_change_mask=_mask_arg(world, "req-p", 2, 1, 4, 2),
        preserve_composite_alpha=True,
        request_id="req-p",
    )
    assert set_["protected_layer_ids"] == wanted
    assert set_["allowed_change_mask"]["bounds_px"] == {"x": 2, "y": 1, "width": 4, "height": 2}
    assert set_["allowed_change_mask"]["allowed_pixels"] == 8
    assert (set_["preserve_composite_alpha"], set_["undo_steps"]) == (True, 0)
    assert handle.allowed_mask == (b"\0" * 8) + (b"\0\0" + b"\xff" * 4 + b"\0\0") * 2 + b"\0" * 8
    assert not handle.dirty and handle.ledger.undo_available() == 0
    body = world.refused("history.step", _undo(document_id))
    assert body["code"] == "INVALID_ARGUMENT" and body["details"]["undo_available"] == 0
    assert world.transfers() == []


def test_protection_never_loosens(world: World) -> None:
    document_id, handle = world.created()
    world.protect(
        document_id,
        allowed_change_mask=_mask_arg(world, "req-1", 2, 1, 4, 2),
        preserve_composite_alpha=True,
        request_id="req-1",
    )
    cases: dict[str, dict[str, Any]] = {
        "the whole canvas again": {"allowed_change_mask": None, "preserve_composite_alpha": True},
        "a wider mask": {
            "allowed_change_mask": _mask_arg(world, "req-2", 1, 1, 5, 2),
            "preserve_composite_alpha": True,
            "request_id": "req-2",
        },
        "a dropped layer": {
            "protected_layer_ids": [layer_id(1, 1)],
            "allowed_change_mask": _mask_arg(world, "req-3", 2, 1, 4, 2),
            "preserve_composite_alpha": True,
            "request_id": "req-3",
        },
        "a flag back off": {
            "allowed_change_mask": _mask_arg(world, "req-4", 2, 1, 4, 2),
            "request_id": "req-4",
        },
    }
    for name, changes in cases.items():
        request_id = changes.pop("request_id", "")
        handle_args = {
            "document_id": document_id,
            "protected_layer_ids": sorted(handle.protected),
            "allowed_change_mask": None,
            "preserve_composite_alpha": False,
            "preserve_canvas": False,
            **changes,
        }
        body = world.refused("protection.set", handle_args, request_id)
        assert body["code"] == "INVALID_ARGUMENT", name
    tighter = world.protect(
        document_id,
        allowed_change_mask=_mask_arg(world, "req-5", 3, 1, 2, 1),
        preserve_composite_alpha=True,
        preserve_canvas=True,
        request_id="req-5",
    )
    assert tighter["allowed_change_mask"]["allowed_pixels"] == 2
    assert world.transfers() == []


def test_protection_names_unknown_layers_and_refuses_a_mask_that_is_not_binary(
    world: World,
) -> None:
    document_id, _ = world.created()
    body = world.refused(
        "protection.set",
        {
            "document_id": document_id,
            "protected_layer_ids": [layer_id(1, 1), layer_id(1, 2), layer_id(7, 7)],
            "allowed_change_mask": None,
            "preserve_composite_alpha": False,
            "preserve_canvas": False,
        },
    )
    assert (body["code"], body["details"]["missing"]) == ("LAYER_NOT_FOUND", [layer_id(7, 7)])
    grey = _mask_arg(world, "req-g", 0, 0, 2, 2, value=128)
    body = world.refused(
        "protection.set",
        {
            "document_id": document_id,
            "protected_layer_ids": [layer_id(1, 1), layer_id(1, 2)],
            "allowed_change_mask": grey,
            "preserve_composite_alpha": False,
            "preserve_canvas": False,
        },
        "req-g",
    )
    assert body["code"] == "INVALID_ARGUMENT"


def test_inspect_reports_the_mask_summary_and_what_history_allows(world: World) -> None:
    document_id, _ = world.created()
    world.layer(document_id)
    seen = world.run("document.inspect", {"document_id": document_id, "frame": 0})
    assert seen["history"] == {"undo_available": 1, "redo_available": 0}
    assert seen["protection"]["allowed_change_mask"] is None
    world.protect(
        document_id, allowed_change_mask=_mask_arg(world, "req-p", 0, 0, 1, 1), request_id="req-p"
    )
    seen = world.run("document.inspect", {"document_id": document_id, "frame": 0})
    assert seen["protection"]["allowed_change_mask"]["allowed_pixels"] == 1
    assert seen["history"] == {"undo_available": 0, "redo_available": 0}


# history.step.


def _undo(document_id: str, steps: int = 1) -> dict[str, Any]:
    return {"document_id": document_id, "action": "undo", "steps": steps}


def test_undo_and_redo_move_exactly_the_bridges_steps(world: World) -> None:
    document_id, handle = world.created()
    start = _ids(world, handle)
    made = world.layer(document_id)
    world.select(document_id, world.rect_shape("req-a", 0, 0, 2, 2), request_id="req-a")
    owners = world.port.open_by_hand("their painting")
    undone = world.history(document_id, "undo", 2)
    assert (undone["steps_applied"], undone["verified"], undone["stopped"]) == (2, True, None)
    assert [step["op"] for step in undone["steps"]] == ["selection.set", "layer.create"]
    assert _ids(world, handle) == start and world.port.selection_bounds(handle.document) is None
    assert (undone["undo_available"], undone["redo_available"]) == (0, 2)
    assert undone["region_px"] is None and undone["pixels"] is None
    # The owner's view comes back.
    assert world.port.front_key == owners
    redone = world.history(document_id, "redo")
    assert redone["steps"] == [
        {"op": "layer.create", "operation_id": undone["steps"][1]["operation_id"]}
    ]
    assert made["layer_id"] in _ids(world, handle)


def test_undo_never_goes_below_the_floor_and_redo_only_what_history_undid(world: World) -> None:
    document_id, handle = world.created()
    world.layer(document_id)
    body = world.refused("history.step", _undo(document_id, 2))
    assert body["details"] == {"steps": 2, "undo_available": 1, "redo_available": 0}
    body = world.refused("history.step", {**_undo(document_id), "action": "redo"})
    assert body["code"] == "INVALID_ARGUMENT" and handle.ledger.applied == 1


def test_a_step_the_bridge_did_not_make_stops_history_unchanged(world: World) -> None:
    document_id, handle = world.created()
    world.layer(document_id)
    # The owner paints in the working copy.
    world.port._push(1, "Freehand Brush Stroke", world.port._state(1))
    before = _ids(world, handle)
    body = world.refused("history.step", _undo(document_id))
    assert body["code"] == "INVALID_ARGUMENT"
    assert (body["details"]["expected_label"], body["details"]["found_label"]) == (
        "Add Layer",
        "Freehand Brush Stroke",
    )
    assert _ids(world, handle) == before and handle.ledger.undo_available() == 0


def test_a_document_changed_outside_the_bridge_is_caught_by_its_state(world: World) -> None:
    document_id, _ = world.created()
    world.layer(document_id)
    world.port._tree(1)["nodes"].append(fake_node(1, 50, "by hand", "root-1", 9))
    assert world.refused("history.step", _undo(document_id))["code"] == "INVALID_ARGUMENT"


def test_history_stops_at_a_foreign_step_between_the_bridges(world: World) -> None:
    document_id, _ = world.created()
    world.layer(document_id)
    world.port._push(1, "Freehand Brush Stroke", world.port._state(1))
    world.layer(document_id)
    undone = world.history(document_id, "undo", 2)
    assert (undone["steps_applied"], undone["verified"]) == (1, False)
    assert undone["stopped"] == "not_the_bridges_step" and undone["undo_available"] == 0


def test_an_undo_krita_did_not_take_is_put_back_and_retryable(world: World) -> None:
    document_id, handle = world.created()
    world.layer(document_id)
    world.port.undo_works = False
    body = world.refused("history.step", _undo(document_id))
    assert (body["code"], body["retryable"]) == ("INTERNAL_ERROR", True)
    assert not handle.unsafe and handle.ledger.undo_available() == 1


def _undo_raising(world: World, on_press: int, raised: BaseException) -> None:
    undo, presses = world.port.undo, itertools.count(1)

    def pressed(document: Any) -> None:
        if next(presses) == on_press:
            raise raised
        undo(document)

    world.port.undo = pressed  # type: ignore[method-assign]


def test_a_step_that_raises_after_the_first_stops_history_and_the_document_is_unsafe(
    world: World,
) -> None:
    document_id, handle = world.created()
    world.layer(document_id)
    world.layer(document_id)
    _undo_raising(world, 2, RuntimeError("Krita raised"))
    undone = world.history(document_id, "undo", 2)
    assert (undone["steps_applied"], undone["verified"]) == (1, False)
    assert undone["stopped"] == "document_unsafe" and undone["undo_available"] == 0
    assert handle.unsafe and handle.dirty
    assert world.refused("history.step", _undo(document_id))["code"] == "DOCUMENT_UNSAFE"


def test_a_first_step_that_raises_is_refused_and_the_document_is_unsafe(world: World) -> None:
    document_id, handle = world.created()
    world.layer(document_id)
    _undo_raising(world, 1, RuntimeError("Krita raised"))
    body = world.refused("history.step", _undo(document_id))
    assert (body["code"], body["retryable"]) == ("INTERNAL_ERROR", False)
    assert body["details"]["raised"] == "RuntimeError"
    assert "raised once asked" in body["message"]
    assert handle.unsafe and handle.ledger.undo_available() == 0


def _labels_raising(world: World, on_read: int) -> None:
    labels, reads = world.port.undo_labels, itertools.count(1)

    def read(document: Any) -> tuple[str | None, str | None]:
        if next(reads) == on_read:
            raise RuntimeError("Krita raised")
        return labels(document)

    world.port.undo_labels = read  # type: ignore[method-assign]


def test_a_raise_before_krita_is_asked_to_move_leaves_the_document_as_it_was(
    world: World,
) -> None:
    document_id, handle = world.created()
    world.layer(document_id)
    _labels_raising(world, 1)
    body = world.refused("history.step", _undo(document_id))
    assert (body["code"], body["retryable"]) == ("INTERNAL_ERROR", True)
    assert "raised before the step" in body["message"]
    assert not handle.unsafe and handle.ledger.undo_available() == 1


def test_a_raise_before_the_second_step_stops_history_with_the_first_kept(world: World) -> None:
    document_id, handle = world.created()
    world.layer(document_id)
    world.layer(document_id)
    # Each step reads the labels before and after Krita moves.
    _labels_raising(world, 3)
    undone = world.history(document_id, "undo", 2)
    assert (undone["steps_applied"], undone["stopped"]) == (1, "unconfirmed")
    assert not handle.unsafe and handle.ledger.undo_available() == 1


def test_an_interrupt_mid_step_seals_history_and_marks_the_document_unsafe(world: World) -> None:
    document_id, handle = world.created()
    world.layer(document_id)
    _undo_raising(world, 1, KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        world.history(document_id, "undo")
    assert handle.unsafe and handle.ledger.undo_available() == 0


def test_a_step_lost_after_the_first_says_the_document_is_unsafe(world: World) -> None:
    document_id, handle = world.created()
    world.layer(document_id)
    world.layer(document_id)
    undo, presses = world.port.undo, itertools.count(1)

    def strays(document: Any) -> None:
        undo(document)
        if next(presses) == 2:
            # Krita moved, but not to the state the step left.
            world.port._tree(1)["nodes"].append(fake_node(1, 50, "stray", "root-1", 9))

    world.port.undo = strays  # type: ignore[method-assign]
    world.port.redo = lambda document: None  # type: ignore[method-assign]
    undone = world.history(document_id, "undo", 2)
    assert (undone["steps_applied"], undone["stopped"]) == (1, "document_unsafe")
    assert handle.unsafe and undone["undo_available"] == 0


def test_a_capture_that_cannot_be_written_leaves_the_receipt_true(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    document_id, handle = world.created()
    world.layer(document_id)
    world.layer(document_id)
    handle.ledger.steps[0].region = {"x": 1, "y": 0, "width": 2, "height": 2}

    def broken(*args: Any) -> dict[str, Any]:
        raise BridgeError("IO_ERROR", "the disk is full")

    monkeypatch.setattr(transfer, "write", broken)
    undone = world.history(document_id, "undo", 2)
    assert (undone["steps_applied"], undone["verified"], undone["stopped"]) == (2, True, None)
    assert undone["region_px"] == {"x": 1, "y": 0, "width": 2, "height": 2}
    assert undone["pixels"] is None and not handle.unsafe


def test_a_capture_that_cannot_be_read_leaves_the_receipt_true(world: World) -> None:
    document_id, handle = world.created()
    world.layer(document_id)
    handle.ledger.steps[0].region = {"x": 1, "y": 0, "width": 2, "height": 2}
    world.port.fail["composite"] = RuntimeError("Krita raised")
    undone = world.history(document_id, "undo")
    assert (undone["steps_applied"], undone["verified"]) == (1, True)
    assert undone["pixels"] is None and not handle.unsafe


def test_history_acts_on_its_own_document_in_front(world: World) -> None:
    first, _ = world.created()
    world.layer(first)
    second, _ = world.created()
    world.layer(second)
    assert world.port.front_key == 2
    world.history(first, "undo")
    assert len(world.port.live[1]["stack"]) == 1 and world.port.live[1]["index"] == 0
    assert world.port.live[2]["index"] == 1 and world.port.front_key == 2


@pytest.mark.parametrize(
    "changes", [{"steps": 0}, {"steps": 51}, {"steps": True}, {"action": "restore_checkpoint"}]
)
def test_history_takes_undo_or_redo_of_1_to_50_steps(world: World, changes: Any) -> None:
    document_id, _ = world.created()
    body = world.refused("history.step", {**_undo(document_id), **changes})
    # Refused by its arguments alone, before the ledger is asked.
    assert (body["code"], body["details"]) == ("INVALID_ARGUMENT", {})


# Harness ops.


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


def test_the_harness_activates_any_node_of_a_document_in_front(world: World) -> None:
    document_id = _harness_document(world)
    handle = world.registry.find(document_id)
    world.select(document_id, {"kind": "all"})
    mask = next(n for n in world.port._tree(1)["nodes"] if n["type"] == "selectionmask")
    made = world.run("harness.activate", {"document_id": document_id, "node_id": mask["id"]})
    assert made["active_id"] == mask["id"] and world.port.is_masked(1)
    world.created()
    body = world.refused("harness.activate", {"document_id": document_id, "node_id": mask["id"]})
    assert body["code"] == "INVALID_ARGUMENT"
    assert handle.ledger.undo_available() == 1


def test_harness_steps_the_ledger_cannot_name_seal_history(world: World) -> None:
    document_id = _harness_document(world)
    handle = world.registry.find(document_id)
    world.layer(document_id)
    timed = world.run("harness.label_timing", {"document_id": document_id, "trials": 2})
    assert timed["reads"] == ["Add Layer", "Add Layer"]
    assert handle.ledger.undo_available() == 0
    labels = world.run("harness.undo_labels", {"document_id": document_id})
    assert (labels["undo"], labels["redo"]) == ("Add Layer", None)
    world.layer(document_id)
    world.run(
        "harness.select_mask",
        {
            "document_id": document_id,
            "layer_id": layer_id(1, 0),
            "rect": {"x": 0, "y": 0, "width": 1, "height": 1},
        },
    )
    assert handle.ledger.undo_available() == 0


def test_a_fingerprint_ignores_the_global_selection_s_own_node(world: World) -> None:
    document_id, handle = world.created()
    before = fingerprint(world.port, handle.document)
    world.select(document_id, {"kind": "all"})
    after = fingerprint(world.port, handle.document)
    assert before[0] == after[0] and before[1] is None and after[1] is not None
    assert any(node["type"] == "selectionmask" for node in world.port._tree(1)["nodes"])
    assert FakeDocument(1) == handle.document


# Closing a just-changed document.


def test_a_document_behind_settles_only_moments_after_a_change(world: World) -> None:
    document_id, handle = world.created()
    assert closing.settle_s(handle, False) == 0.0
    world.select(document_id, {"kind": "all"})
    assert handle.changed_at is not None
    assert closing.settle_s(handle, False, handle.changed_at) == closing.SETTLE_S
    assert closing.settle_s(handle, False, handle.changed_at + 0.2) == pytest.approx(0.3)
    assert closing.settle_s(handle, False, handle.changed_at + 5) == 0.0
    # Whoever changed it, the document in front is the one Krita's layer docker shows.
    assert closing.settle_s(handle, True, handle.changed_at + 5) == closing.SETTLE_S


def test_a_close_settles_in_front_or_moments_after_a_change(world: World) -> None:
    document_id, _ = world.created()
    behind, behind_handle = world.created()
    world.select(behind, {"kind": "all"})
    assert world.port.front_key == 2
    world.run("document.close", {"document_id": document_id, "dirty_policy": "discard"})
    assert world.port.settled[-1] == 0.0
    world.run("document.close", {"document_id": behind, "dirty_policy": "discard"})
    assert world.port.settled[-1] == closing.SETTLE_S
    assert behind_handle.changed_at is not None


def test_harness_ops_that_change_nodes_count_as_changes(world: World) -> None:
    document_id = _harness_document(world)
    handle = world.registry.find(document_id)
    world.run(
        "harness.select_mask",
        {
            "document_id": document_id,
            "layer_id": layer_id(1, 0),
            "rect": {"x": 0, "y": 0, "width": 1, "height": 1},
        },
    )
    assert handle.changed_at is not None
    stamped = handle.changed_at
    world.run("harness.label_timing", {"document_id": document_id, "trials": 1})
    assert handle.changed_at > stamped
    stamped = handle.changed_at
    node = world.port._tree(1)["nodes"][0]["id"]
    world.run("harness.activate", {"document_id": document_id, "node_id": node})
    assert handle.changed_at > stamped


def test_a_failing_create_closes_its_document_with_a_settle(world: World) -> None:
    world.port.layer = {**world.port.layer, "opacity": 10}
    with pytest.raises(BridgeError):
        world.run("document.create", CREATE)
    assert world.port.settled == [closing.SETTLE_S]


def test_history_reads_the_composite_over_the_regions_its_steps_changed(world: World) -> None:
    # A stroke records the region it changes; layers and selections change none.
    document_id, handle = world.created()
    world.layer(document_id)
    world.layer(document_id)
    handle.ledger.steps[0].region = {"x": 1, "y": 0, "width": 2, "height": 2}
    handle.ledger.steps[1].region = {"x": 4, "y": 2, "width": 3, "height": 1}
    undone = world.history(document_id, "undo", 2)
    assert undone["region_px"] == {"x": 1, "y": 0, "width": 6, "height": 3}
    pixels = undone["pixels"]
    assert pixels["size_px"] == [6, 3] and pixels["format"] == "BGRA8"
    assert Path(pixels["path"]).stat().st_size == 6 * 3 * 4


def test_an_undo_krita_did_not_take_leaves_a_clean_document_clean(world: World) -> None:
    document_id, handle = world.created()
    world.layer(document_id)
    handle.dirty = False
    world.port.undo_works = False
    assert world.refused("history.step", _undo(document_id))["retryable"] is True
    assert not handle.dirty


def _counting_selection_reads(world: World) -> list[int]:
    reads = [0]
    bounds = world.port.selection_bounds

    def counted(document: Any) -> dict[str, int] | None:
        reads[0] += 1
        return bounds(document)

    world.port.selection_bounds = counted  # type: ignore[method-assign]
    return reads


def test_history_reads_the_selection_once_per_step_and_once_more(world: World) -> None:
    document_id, _ = world.created()
    for _ in range(3):
        world.layer(document_id)
    reads = _counting_selection_reads(world)
    assert world.history(document_id, "undo", 3)["steps_applied"] == 3
    assert reads[0] == 4


def test_a_layer_creation_reads_the_selection_once(world: World) -> None:
    document_id, _ = world.created()
    reads = _counting_selection_reads(world)
    world.layer(document_id)
    assert reads[0] == 1


def test_a_failing_open_closes_its_document_with_a_settle(world: World) -> None:
    source = world.art / "fixture.ora"
    source.write_bytes(b"ora")
    world.port.fail["show"] = BridgeError("INTERNAL_ERROR", "no view")
    args = {
        "source_path": str(source),
        "source_sha256": hashlib.sha256(b"ora").hexdigest(),
        "mode": "read_only",
        "working_dir": None,
        "editable_layer_ids": None,
        "editable_layer_names": None,
    }
    assert world.refused("document.open", args)["code"] == "INTERNAL_ERROR"
    assert world.port.settled == [closing.SETTLE_S]
