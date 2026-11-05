import copy
import hashlib
from pathlib import Path
from typing import Any

import pytest
from bridge_core import history, verification
from fake_krita import MASK, fake_node, layer_id
from paint_world import BASE, GROUP, HEIGHT, PAINT, WIDTH, World, box

# The paint layer's rect, filled first so a mask has something to show or hide.
PAINTED = box(40, 50, 20, 10)
INSIDE = box(44, 52, 6, 4)


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


def fill_args(document_id: str, layer: str, **style: Any) -> dict[str, Any]:
    return {
        "document_id": document_id,
        "layer_id": layer,
        "verify": "region",
        "shape": {"kind": "rect", "rect": dict(style.pop("rect", PAINTED))},
        "fill": {
            "color": None,
            "mask": None,
            "opacity": 1,
            "blend_mode": "normal",
            "alpha_lock": False,
            **style,
        },
    }


def painted(world: World) -> tuple[str, Any]:
    document_id, handle = world.document()
    world.run("paint.fill", fill_args(document_id, PAINT, color=[1, 0.5, 0, 1]))
    return document_id, handle


def create_args(document_id: str, coverage: str | None, **changes: Any) -> dict[str, Any]:
    return {
        "document_id": document_id,
        "parent_id": PAINT,
        "above_id": None,
        "type": "transparency_mask",
        "name": "mask",
        "coverage": coverage,
        **changes,
    }


def masked(world: World, document_id: str, coverage: str = "all") -> str:
    made = world.run("layer.create", create_args(document_id, coverage))
    return str(made["layer_id"])


def alpha(world: World, rect: dict[str, int]) -> set[int]:
    handle = world.registry.sync()[0]
    [found] = world.port.composite_rects(handle.document, [rect])
    return set(found[3::4])


def select(world: World, value: int, rect: dict[str, int] = PAINTED) -> None:
    world.port.live[1]["selection"] = (
        dict(rect),
        bytes([value]) * (rect["width"] * rect["height"]),
    )


# The create.


@pytest.mark.parametrize(
    ("coverage", "byte", "shown"),
    [("all", 255, {255}), ("none", 0, {0}), ("selection", 128, {128})],
)
def test_a_mask_starts_from_its_coverage_in_one_undo_step(
    world: World, coverage: str, byte: int, shown: set[int]
) -> None:
    document_id, handle = painted(world)
    select(world, 128)
    steps = len(handle.ledger.steps)
    made = world.run("layer.create", create_args(document_id, coverage))
    mask = made["layer_id"]
    assert (made["type"], made["coverage"], made["parent_id"]) == (
        "transparency_mask",
        coverage,
        PAINT,
    )
    assert world.pixels(mask, PAINTED) == bytes([byte]) * (20 * 10)
    assert alpha(world, PAINTED) == shown
    assert made["verification"]["mode"] == "region"
    assert len(handle.ledger.steps) == steps + 1 and made["undo_steps"] == 1
    node = next(node for node in world.port._tree(1)["nodes"] if node["id"] == mask)
    assert (node["type"], node["parent_id"]) == (MASK, PAINT)


def test_a_selection_coverage_needs_a_selection(world: World) -> None:
    document_id, _ = painted(world)
    before = copy.deepcopy(world.port._tree(1))
    body = world.refused("layer.create", create_args(document_id, "selection"))
    assert (body["code"], body["details"]["field"]) == ("INVALID_ARGUMENT", "coverage")
    assert world.port._tree(1) == before


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"parent_id": GROUP}, "INVALID_ARGUMENT"),
        ({"parent_id": BASE}, "LOCKED_TARGET"),
        ({"above_id": layer_id(1, 8)}, "INVALID_ARGUMENT"),
        ({"coverage": None}, "INVALID_ARGUMENT"),
        ({"coverage": "most"}, "INVALID_ARGUMENT"),
        ({"type": "paint", "parent_id": "root-1"}, "INVALID_ARGUMENT"),
    ],
    ids=[
        "group-parent",
        "protected-parent",
        "above-a-selection-mask",
        "no-coverage",
        "bad",
        "on-paint",
    ],
)
def test_a_mask_is_refused_before_any_change(
    world: World, changes: dict[str, Any], code: str
) -> None:
    document_id, _ = painted(world)
    # A selection mask on the layer: a child of it, but no transparency mask.
    world.port._tree(1)["nodes"].append(fake_node(1, 8, "local", PAINT, 0, type="selectionmask"))
    before = copy.deepcopy(world.port._tree(1))
    body = world.refused("layer.create", {**create_args(document_id, "all"), **changes})
    assert body["code"] == code
    assert world.port._tree(1) == before


def test_a_protected_group_around_the_layer_refuses_a_mask(world: World) -> None:
    document_id, handle = painted(world)
    tree = world.port._tree(1)
    inner = fake_node(1, 9, "inner", GROUP, 0)
    tree["nodes"].append(inner)
    handle.protected.add(GROUP)
    body = world.refused("layer.create", create_args(document_id, "all", parent_id=inner["id"]))
    assert (body["code"], body["details"]["protected_layer_ids"]) == ("LOCKED_TARGET", [GROUP])


def test_a_mask_that_hides_past_the_allowed_mask_is_undone(world: World) -> None:
    document_id, handle = painted(world)
    world.allow(document_id, box(0, 0, 10, 10))
    ids = {node["id"] for node in world.port._tree(1)["nodes"]}
    body = world.refused("layer.create", create_args(document_id, "none"))
    assert body["code"] == "PROTECTED_REGION_CHANGED"
    assert body["details"]["rollback_verified"] is True
    assert {node["id"] for node in world.port._tree(1)["nodes"]} == ids
    assert alpha(world, PAINTED) == {255} and not handle.unsafe


def test_a_mask_krita_fills_wrongly_is_undone(world: World) -> None:
    document_id, _ = painted(world)
    made = world.port.create_mask

    def wrong(document: Any, parent: str, above: Any, name: str, coverage: str) -> str:
        found = made(document, parent, above, name, coverage)
        world.port.buffers[found][0] = 7
        world.port.buffers[found][(50 * WIDTH) + 41] = 7
        return found

    world.port.create_mask = wrong  # type: ignore[method-assign,assignment]
    body = world.refused("layer.create", create_args(document_id, "all"))
    assert (body["code"], body["details"]["rollback_verified"]) == ("INTERNAL_ERROR", True)
    assert MASK not in {node["type"] for node in world.port._tree(1)["nodes"]}


# Mask paint.


@pytest.mark.parametrize(
    ("start", "paint", "opacity", "byte"),
    [
        ("none", "reveal", 1, 255),
        ("none", "reveal", 0.5, 128),
        ("all", "hide", 1, 0),
        ("all", "hide", 0.5, 128),
    ],
)
def test_a_fill_reveals_or_hides_by_its_opacity(
    world: World, start: str, paint: str, opacity: float, byte: int
) -> None:
    document_id, _ = painted(world)
    mask = masked(world, document_id, start)
    done = world.run(
        "paint.fill", fill_args(document_id, mask, mask=paint, opacity=opacity, rect=INSIDE)
    )
    assert world.pixels(mask, INSIDE) == bytes([byte]) * (6 * 4)
    assert done["effective_fill"]["mask"] == paint and done["effective_fill"]["color"] is None
    assert done["changed_bounds_px"] == INSIDE
    # A mask's bounds are its layer's.
    assert done["layer_bounds_px"] == PAINTED


def test_a_mask_step_is_witnessed_one_byte_a_pixel_and_moves_in_history(world: World) -> None:
    document_id, handle = painted(world)
    mask = masked(world, document_id, "all")
    world.run("paint.fill", fill_args(document_id, mask, mask="hide", rect=INSIDE))
    step = handle.ledger.steps[-1]
    assert step.witness is not None and step.witness[:2] == (mask, INSIDE)
    world.history(document_id, history.UNDO)
    assert world.pixels(mask, INSIDE) == b"\xff" * 24
    world.history(document_id, history.REDO)
    assert world.pixels(mask, INSIDE) == b"\x00" * 24


def test_a_stroke_hides_on_a_mask(world: World) -> None:
    document_id, _ = painted(world)
    mask = masked(world, document_id, "all")
    brush = {"color": None, "mask": "hide"}
    path = {"start": [44, 55], "segments": [[54, 55]]}
    done = world.stroke(document_id, layer_id=mask, brush=brush, path=path)
    assert done["effective_brush"]["mask"] == "hide" and done["effective_brush"]["color"] is None
    assert 0 in set(world.pixels(mask, done["changed_bounds_px"]))
    assert world.port.brush_now["color"] == [0.0, 0.0, 0.0, 1.0]


@pytest.mark.parametrize(
    ("target", "style", "field"),
    [
        ("mask", {"color": [1, 0.5, 0, 1]}, None),
        ("paint", {"mask": "reveal"}, None),
        ("mask", {"mask": "reveal", "blend_mode": "multiply"}, "fill.mask"),
        ("mask", {"mask": "reveal", "alpha_lock": True}, "fill.mask"),
        ("mask", {}, "fill.color"),
        ("mask", {"mask": "show"}, None),
    ],
    ids=["colour-on-a-mask", "mask-on-a-layer", "blend", "alpha-lock", "neither", "bad-mode"],
)
def test_mask_paint_that_does_not_fit_is_refused(
    world: World, target: str, style: dict[str, Any], field: str | None
) -> None:
    document_id, _ = painted(world)
    mask = masked(world, document_id, "all")
    layer = mask if target == "mask" else PAINT
    body = world.refused("paint.fill", fill_args(document_id, layer, **style))
    assert body["code"] == "INVALID_ARGUMENT"
    if field is not None:
        assert body["details"]["field"] == field


def test_a_protected_layer_under_a_mask_refuses_its_paint(world: World) -> None:
    document_id, handle = painted(world)
    mask = masked(world, document_id, "all")
    handle.protected.add(PAINT)
    body = world.refused("paint.fill", fill_args(document_id, mask, mask="hide"))
    assert (body["code"], body["details"]["protected_layer_ids"]) == ("LOCKED_TARGET", [PAINT])


def test_a_preset_krita_cannot_paint_a_mask_with_is_refused(world: World) -> None:
    document_id, _ = painted(world)
    mask = masked(world, document_id, "all")
    world.port.ability[mask] = "MYPAINTBRUSH_UNPAINTABLE"
    body = world.stroke_refused(document_id, layer_id=mask, brush={"color": None, "mask": "hide"})
    assert body["code"] == "LAYER_NOT_PAINTABLE"


def test_a_hide_past_the_allowed_mask_is_undone(world: World) -> None:
    document_id, handle = painted(world)
    mask = masked(world, document_id, "all")
    world.allow(document_id, box(0, 0, 50, HEIGHT))
    body = world.refused("paint.fill", fill_args(document_id, mask, mask="hide"))
    assert (body["code"], body["details"]["rollback_verified"]) == (
        "PROTECTED_REGION_CHANGED",
        True,
    )
    assert world.pixels(mask, PAINTED) == b"\xff" * 200 and not handle.unsafe


# Show, hide and name a mask.


def test_a_mask_can_be_shown_hidden_and_named(world: World) -> None:
    document_id, _ = painted(world)
    mask = masked(world, document_id, "none")
    args = {"document_id": document_id, "layer_id": mask, "verify": "region"}
    off = world.run("layer.update", {**args, "properties": {"visible": False, "name": "veil"}})
    assert off["effective_properties"] == {"visible": False, "name": "veil"}
    assert off["verification"]["changed_px"] == 200 and alpha(world, PAINTED) == {255}
    world.run("layer.update", {**args, "properties": {"visible": True}})
    assert alpha(world, PAINTED) == {0}


@pytest.mark.parametrize("properties", [{"opacity": 0.5}, {"blend_mode": "multiply"}])
def test_a_mask_takes_no_other_property(world: World, properties: dict[str, Any]) -> None:
    document_id, _ = painted(world)
    mask = masked(world, document_id, "all")
    args = {"document_id": document_id, "layer_id": mask, "properties": properties}
    body = world.refused("layer.update", {**args, "verify": "region"})
    assert (body["code"], body["details"]["fields"]) == ("INVALID_ARGUMENT", sorted(properties))


def test_a_protected_layer_keeps_its_mask_as_it_is(world: World) -> None:
    document_id, handle = painted(world)
    mask = masked(world, document_id, "none")
    handle.protected.add(PAINT)
    args = {"document_id": document_id, "layer_id": mask, "verify": "region"}
    body = world.refused("layer.update", {**args, "properties": {"visible": False}})
    assert body["code"] == "LOCKED_TARGET" and alpha(world, PAINTED) == {0}


# Reads.


def capture_args(document_id: str, target: str, layer: str) -> dict[str, Any]:
    return {
        "document_id": document_id,
        "frame": 0,
        "target": target,
        "layer_id": layer,
        "rect": dict(PAINTED),
        "render": {},
    }


def test_a_mask_is_captured_alone_one_byte_a_pixel(world: World) -> None:
    document_id, _ = painted(world)
    select(world, 64)
    mask = masked(world, document_id, "selection")
    read = world.run("capture.read", capture_args(document_id, "mask", mask))
    spec = read["pixels"]
    assert (spec["format"], read["profile_id"]) == ("A8", None)
    assert Path(spec["path"]).read_bytes() == bytes([64]) * 200


def test_a_layer_read_of_a_mask_points_to_the_mask_target_and_back(world: World) -> None:
    document_id, _ = painted(world)
    mask = masked(world, document_id, "all")
    layer = world.refused("capture.read", capture_args(document_id, "layer", mask))
    assert layer["code"] == "UNSUPPORTED_CAPABILITY" and 'target "mask"' in layer["message"]
    wrong = world.refused("capture.read", capture_args(document_id, "mask", PAINT))
    assert (wrong["code"], wrong["details"]["layer_type"]) == ("INVALID_ARGUMENT", "paint")


def test_a_mask_reaches_as_far_as_its_layer_does(world: World) -> None:
    document_id, _ = painted(world)
    mask = masked(world, document_id, "all")
    tree = world.port.tree(world.registry.sync()[0].document)
    effects = {"styled": [], "clones": {}, "animated": False}
    assert verification.reach(tree, effects, mask) == []
    next(node for node in tree["nodes"] if node["id"] == PAINT)["blend_mode"] = "destination-in"
    found = verification.reach(tree, effects, mask)
    assert found == [{"reason": "blend_mode", "node_id": PAINT}]


def test_a_mask_in_an_opened_file_is_protected(world: World) -> None:
    document_id, _ = world.harness_document()
    layer = layer_id(1, 1)
    world.port.paintable(1)
    world.run("paint.fill", fill_args(document_id, layer, color=[1, 0.5, 0, 1]))
    made = world.run("layer.create", create_args(document_id, "all", parent_id=layer))
    target = world.data / "harness" / "masked.kra"
    world.run("harness.export_kra", {"document_id": document_id, "target_path": str(target)})
    args = {
        "source_path": str(target),
        "source_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "mode": "working_copy",
        "working_dir": str(world.data / "harness" / "again"),
        "editable_layer_ids": [layer],
        "editable_layer_names": None,
    }
    (world.data / "harness" / "again").mkdir()
    exported = next(saved for path, saved in world.port.saved.items() if path.endswith(".kra"))
    opening = world.port.open

    def reopen(path: str) -> Any:
        # The working copy reads back as the export it copies.
        world.port.saved[path] = exported
        return opening(path)

    world.port.open = reopen  # type: ignore[method-assign]
    opened = world.run("document.open", args)
    handle = world.registry.find(opened["document_id"])
    assert made["layer_id"] in handle.protected and layer not in handle.protected
    body = world.refused(
        "paint.fill", fill_args(opened["document_id"], made["layer_id"], mask="hide")
    )
    assert body["code"] == "LOCKED_TARGET"
