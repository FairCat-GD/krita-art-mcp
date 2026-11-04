import copy
from pathlib import Path
from typing import Any

import pytest
from bridge_core import documents, painting, resources
from fake_krita import FILL_ORDER, fake_node, layer_id, preset_xml
from paint_world import BASE, BASE_PIXEL, GROUP, HEIGHT, LABEL, ORANGE, PAINT, WIDTH, World, box

RECT: dict[str, Any] = {"kind": "rect", "rect": box(40, 50, 20, 10)}
# R: the rect grown by the fill's margin; R': R grown by 32, clipped to the canvas.
REGION = box(38, 48, 24, 14)
RING = box(6, 16, 88, 78)


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


def fill_args(document_id: str, **changes: Any) -> dict[str, Any]:
    style = {
        "color": [1, 0.5, 0, 1],
        "opacity": 1,
        "blend_mode": "normal",
        "alpha_lock": False,
        **changes.pop("fill", {}),
    }
    found = {
        "document_id": document_id,
        "layer_id": PAINT,
        "verify": "region",
        "shape": copy.deepcopy(RECT),
        "fill": style,
    }
    found.update(changes)
    return found


def fill(world: World, document_id: str, **changes: Any) -> dict[str, Any]:
    return world.run("paint.fill", fill_args(document_id, **changes))


def refused(world: World, document_id: str, **changes: Any) -> dict[str, Any]:
    return world.refused("paint.fill", fill_args(document_id, **changes))


def select(world: World, bounds: dict[str, int]) -> None:
    world.port.live[1]["selection"] = (bounds, bytes([255]) * (bounds["width"] * bounds["height"]))


# A fill.


def test_a_fill_is_painted_verified_over_r_and_reported(world: World) -> None:
    document_id, handle = world.document()
    done = fill(world, document_id)
    assert done["fill_id"].startswith("op-") and done["layer_id"] == PAINT
    assert (done["shape"], done["shape_bounds_px"]) == ("rect", RECT["rect"])
    assert done["effective_fill"] == {
        "preset_id": painting.FILL_PRESET,
        "color": {"space": "srgb", "rgba": [1, 0.5, 0, 1]},
        "opacity": 1,
        "blend_mode": "normal",
        "alpha_lock": False,
        "antialias": True,
    }
    assert done["changed_bounds_px"] == done["layer_bounds_px"] == RECT["rect"]
    assert (done["undo_label"], done["undo_steps"], done["protected_pixels_changed"]) == (
        LABEL,
        1,
        0,
    )
    assert done["history_sealed"] is False and done["verification"]["mode"] == "region"
    assert done["verification"]["rect"] == REGION
    [step] = handle.ledger.steps
    assert (step.op, step.label, step.region) == ("paint.fill", LABEL, RECT["rect"])
    assert world.port.brush_order == list(FILL_ORDER)
    brush = world.port.brush_now
    assert (brush["preset"], brush["flow"], brush["eraser"]) == (
        painting.FILL_PRESET_NAME,
        1.0,
        False,
    )
    assert world.pixels(PAINT, RECT["rect"]) == ORANGE * 200
    assert world.port.shapes == [RECT]


@pytest.mark.parametrize(
    ("shape", "bounds"),
    [
        ({"kind": "ellipse", "rect": box(40, 50, 20, 10)}, box(40, 50, 20, 10)),
        ({"kind": "polygon", "points": [[40.5, 50], [60, 52.5], [45, 59.5]]}, box(40, 50, 20, 10)),
        (
            {
                "kind": "path",
                "start": [40, 50],
                "segments": [
                    [50, 48, 55, 48, 60, 50],
                    [60, 55, 50, 60, 45, 58],
                    [42, 56, 40, 52, 40, 50],
                ],
            },
            box(40, 48, 20, 11),
        ),
    ],
    ids=["ellipse", "polygon", "path"],
)
def test_each_shape_is_sent_as_given_and_reported_by_its_box(
    world: World, shape: dict[str, Any], bounds: dict[str, int]
) -> None:
    document_id, _ = world.document()
    done = fill(world, document_id, shape=shape)
    assert (done["shape"], done["shape_bounds_px"]) == (shape["kind"], bounds)
    assert world.port.shapes == [shape] and done["changed_bounds_px"] == bounds


def test_a_selection_fill_paints_the_selection_s_bounds(world: World) -> None:
    document_id, _ = world.document()
    select(world, box(30, 20, 40, 30))
    done = fill(world, document_id, shape={"kind": "selection"})
    assert (done["shape"], done["shape_bounds_px"]) == ("selection", box(30, 20, 40, 30))
    assert world.port.shapes == [{"kind": "rect", "rect": box(30, 20, 40, 30)}]


@pytest.mark.parametrize(
    ("bounds", "clipped"),
    [
        (box(150, 100, 80, 40), box(150, 100, 50, 20)),
        (box(0, 0, WIDTH + 48, HEIGHT + 20), box(0, 0, WIDTH, HEIGHT)),
    ],
    ids=["past the corner", "an inverted selection's bounds"],
)
def test_a_selection_past_the_canvas_is_filled_over_its_part_on_it(
    world: World, bounds: dict[str, int], clipped: dict[str, int]
) -> None:
    document_id, _ = world.document()
    select(world, bounds)
    done = fill(world, document_id, shape={"kind": "selection"}, verify="full")
    assert done["shape_bounds_px"] == clipped
    assert world.port.shapes == [{"kind": "rect", "rect": clipped}]


@pytest.mark.parametrize("bounds", [None, box(WIDTH, 0, 10, 10)], ids=["none", "off the canvas"])
def test_a_selection_fill_with_nothing_selected_on_the_canvas_is_refused(
    world: World, bounds: dict[str, int] | None
) -> None:
    document_id, handle = world.document()
    if bounds is not None:
        select(world, bounds)
    body = refused(world, document_id, shape={"kind": "selection"})
    assert (body["code"], body["details"]) == ("INVALID_ARGUMENT", {"field": "shape"})
    assert "fill" not in world.port.calls and world.port.brush_order == []
    assert not handle.dirty


# Refusals.


def test_refusals_come_in_their_order_and_change_nothing(world: World) -> None:
    document_id, handle = world.document()
    tree = world.port._tree(1)
    tree["nodes"].append(fake_node(1, 5, "blur", tree["root_id"], 4, type="filterlayer"))
    world.port.cumulative = True
    world.port.live[1]["space"] = ("RGBA", "U16", documents.SRGB_PROFILE)
    world.resources.stock = None
    stock = {"name": painting.FILL_PRESET_NAME, "file": painting.FILL_PRESET}
    changes: dict[str, Any] = {
        "layer_id": BASE,
        "shape": {"kind": "rect", "rect": box(190, 0, 20, 4)},
    }
    expected = [
        "COLOR_PROFILE_MISMATCH",
        "LOCKED_TARGET",
        "INVALID_ARGUMENT",
        "UNSUPPORTED_CAPABILITY",
        "UNSUPPORTED_CAPABILITY",
        "UNSUPPORTED_CAPABILITY",
    ]
    found = []
    for fix in range(len(expected)):
        body = refused(world, document_id, **copy.deepcopy(changes))
        found.append(body["code"])
        if fix == 0:
            del world.port.live[1]["space"]
        elif fix == 1:
            del changes["layer_id"]
        elif fix == 2:
            assert body["details"]["bounds_px"] == box(190, 0, 20, 4)
            del changes["shape"]
        elif fix == 3:
            assert body["details"] == {"preset_id": painting.FILL_PRESET}
            world.resources.stock = stock
        elif fix == 4:
            assert body["details"]["reason"] == "cumulative_undo"
            world.port.cumulative = False
        else:
            assert body["details"]["reasons"] == [
                {"reason": "filter_layer", "node_id": layer_id(1, 5)}
            ]
    assert found == expected
    assert world.port.brush_order == [] and "fill" not in world.port.calls
    assert not handle.dirty and fill(world, document_id, verify="full")["undo_steps"] == 1


@pytest.mark.parametrize(
    ("node", "words"),
    [(GROUP, "Only paint layers take fills"), (layer_id(1, 99), "No layer has that id.")],
    ids=["a group", "no layer"],
)
def test_a_target_that_is_no_paint_layer_is_refused_in_the_fill_s_words(
    world: World, node: str, words: str
) -> None:
    document_id, _ = world.document()
    assert words in refused(world, document_id, layer_id=node)["message"]


def test_a_local_selection_mask_is_refused_in_the_fill_s_words(world: World) -> None:
    document_id, _ = world.document()
    tree = world.port._tree(1)
    tree["nodes"].append(fake_node(1, 6, "mask", PAINT, 0, type="selectionmask"))
    body = refused(world, document_id)
    assert body["code"] == "LAYER_HAS_LOCAL_SELECTION" and "confine the fill" in body["message"]


@pytest.mark.parametrize(
    "changes",
    [
        {"extra": 1},
        {"layer_id": "paint"},
        {"verify": "fast"},
        {"fill": {"color": [1, 0.5, 0, 0.5]}},
        {"fill": {"color": [1, 0.5, 2, 1]}},
        {"fill": {"opacity": 1.5}},
        {"fill": {"blend_mode": "glow"}},
        {"fill": {"alpha_lock": 1}},
        {"fill": {"flow": 1}},
        {"shape": {"kind": "polygon", "points": [[0, 0], [5, 5], [9, 9]]}},
        {"shape": {"kind": "circle"}},
    ],
    ids=[
        "an unknown field",
        "a layer id that is no id",
        "an unknown scope",
        "a colour with alpha",
        "a colour past 1",
        "an opacity past 1",
        "an unknown blend",
        "an alpha lock that is no bool",
        "a field the fill does not take",
        "a polygon with no area",
        "an unknown shape",
    ],
)
def test_malformed_arguments_are_refused_before_the_job(
    world: World, changes: dict[str, Any]
) -> None:
    document_id, handle = world.document()
    body = refused(world, document_id, **changes)
    assert body["code"] == "INVALID_ARGUMENT"
    assert world.port.calls == [] or "fill" not in world.port.calls
    assert not handle.dirty


def test_the_alpha_rule_reads_as_the_server_s(world: World) -> None:
    document_id, _ = world.document()
    body = refused(world, document_id, fill={"color": [1, 0.5, 0, 0.5]})
    assert body["message"] == "fill.color's alpha must be 1; opacity sets transparency."


@pytest.mark.parametrize(
    ("asked", "fields"),
    [
        ({"adjust": {"blend_mode": "normal"}, "fill": {"blend_mode": "multiply"}}, ["blend_mode"]),
        ({"ignore": {"alpha_lock"}, "fill": {"alpha_lock": True}}, ["alpha_lock"]),
        ({"adjust": {"preset": "Basic Round"}}, ["preset"]),
        ({"adjust": {"eraser": True}}, ["eraser"]),
    ],
    ids=["the blend", "the alpha lock", "the preset", "the eraser"],
)
def test_a_fill_krita_did_not_take_paints_nothing(
    world: World, asked: dict[str, Any], fields: list[str]
) -> None:
    document_id, handle = world.document()
    world.port.adjust = asked.get("adjust", {})
    world.port.ignore_brush = asked.get("ignore", set())
    body = refused(world, document_id, fill=asked.get("fill", {}))
    assert (body["code"], body["details"]["fields"]) == ("INTERNAL_ERROR", fields)
    assert "fill" not in world.port.calls and not handle.dirty


@pytest.mark.parametrize(
    ("params", "reasons"),
    [
        ({"PaintOpAction": "2"}, ["wash_mode"]),
        ({"PaintOpAction": "1", "MaskingBrush/Enabled": "true"}, ["masking_brush"]),
        ({}, ["wash_mode"]),
    ],
    ids=["wash mode", "a masking brush", "no paint action"],
)
def test_a_fill_preset_no_longer_as_krita_ships_it_is_refused(
    world: World, params: dict[str, str], reasons: list[str]
) -> None:
    document_id, handle = world.document()
    world.port.preset_xml[painting.FILL_PRESET_NAME] = preset_xml("changed", scatter=params)
    body = refused(world, document_id)
    assert (body["code"], body["details"]["reasons"]) == ("UNSUPPORTED_CAPABILITY", reasons)
    assert "fill" not in world.port.calls and not handle.dirty


def test_a_layer_krita_cannot_paint_is_refused(world: World) -> None:
    document_id, handle = world.document()
    world.port.front_key = 99
    world.port.ability[PAINT] = "UNPAINTABLE"
    world.port.calls.clear()
    body = refused(world, document_id)
    assert (body["code"], body["details"]["paint_ability"]) == (
        "LAYER_NOT_PAINTABLE",
        "UNPAINTABLE",
    )
    assert world.port.brush_order and world.port.calls.index("forward") < world.port.calls.index(
        "ability"
    )
    assert world.port.calls[-1] == "restore" and not handle.dirty


def test_a_fill_wholly_outside_the_allowed_mask_is_refused_before_painting(world: World) -> None:
    document_id, _ = world.document()
    world.allow(document_id, box(120, 60, 20, 20))
    for scope in ("region", "full"):
        body = refused(world, document_id, verify=scope)
        assert (body["code"], body["details"]["region_px"]) == ("OUTSIDE_ALLOWED_MASK", REGION)
        assert "fill's reach" in body["message"]
    assert "fill" not in world.port.calls


# The reach.


def test_the_target_is_read_over_r_prime_and_the_composite_over_r(world: World) -> None:
    document_id, _ = world.document()
    done = fill(world, document_id)
    assert world.layer_reads[0] == (PAINT, RING)
    assert done["verification"]["rect"] == REGION


def test_full_scope_reads_the_canvas_and_the_target_over_its_old_bounds_and_r_prime(
    world: World,
) -> None:
    document_id, _ = world.document()
    world.port._tree(1)["nodes"][1]["bounds_px"] = box(150, 100, 10, 10)
    done = fill(world, document_id, verify="full")
    assert done["verification"]["rect"] == box(0, 0, WIDTH, HEIGHT)
    assert world.layer_reads[0] == (PAINT, box(6, 16, 154, 94))


@pytest.mark.parametrize(
    "corner",
    [box(0, 0, 20, 10), box(WIDTH - 20, HEIGHT - 10, 20, 10)],
    ids=["top left", "bottom right"],
)
@pytest.mark.parametrize("scope", ["region", "full"])
def test_a_fill_at_an_edge_reports_bounds_on_the_canvas(
    world: World, corner: dict[str, int], scope: str
) -> None:
    document_id, _ = world.document()
    done = fill(world, document_id, shape={"kind": "rect", "rect": corner}, verify=scope)
    assert done["changed_bounds_px"] == done["layer_bounds_px"] == corner


# Leaks and rollbacks.


def test_a_fill_past_r_is_undone_in_region_scope_and_kept_in_full(world: World) -> None:
    document_id, handle = world.document()
    world.port.stray = [box(70, 50, 4, 4)]
    body = refused(world, document_id)
    assert body["code"] == "PROTECTED_REGION_CHANGED" and "The fill reached past" in body["message"]
    assert body["details"]["target_outside_reach"] is True
    assert (body["details"]["rolled_back"], body["details"]["rollback_verified"]) == (True, True)
    assert handle.ledger.steps == [] and world.pixels(PAINT, RECT["rect"]) == bytes(4) * 200
    done = fill(world, document_id, verify="full")
    assert done["changed_bounds_px"] == box(40, 50, 34, 10)


def test_a_fill_that_changes_a_protected_layer_is_undone(world: World) -> None:
    document_id, _ = world.document()

    def damage(key: int) -> None:
        world.port.buffers[BASE][0:4] = bytes([1, 2, 3, 255])

    world.port.on_paint.append(damage)
    body = refused(world, document_id, verify="full")
    assert (body["code"], body["details"]["protected_layer_ids"]) == (
        "PROTECTED_REGION_CHANGED",
        [BASE],
    )
    assert body["details"]["rollback_verified"] is True and body["retryable"] is False
    assert world.pixels(BASE, box(0, 0, 1, 1)) == BASE_PIXEL


def test_a_fill_that_changes_no_byte_seals_history(world: World) -> None:
    document_id, handle = world.document()
    world.port.buffers[PAINT] = bytearray(ORANGE * (WIDTH * HEIGHT))
    done = fill(world, document_id)
    assert (done["changed_bounds_px"], done["history_sealed"]) == (None, True)
    assert handle.ledger.steps == []


@pytest.mark.parametrize("step", ["fill_path", "fill_path_after"])
def test_a_raise_mid_fill_is_rolled_back_and_confirmed(world: World, step: str) -> None:
    document_id, handle = world.document()
    world.port.fail[step] = RuntimeError("Krita raised")
    body = refused(world, document_id)
    assert (body["code"], body["details"]["rollback_verified"]) == ("INTERNAL_ERROR", True)
    assert "during the fill" in body["message"]
    assert handle.ledger.steps == [] and not handle.unsafe
    assert world.pixels(PAINT, RECT["rect"]) == bytes(4) * 200


def test_a_fill_is_undone_and_redone_by_history(world: World) -> None:
    document_id, _ = world.document()
    fill(world, document_id)
    undone = world.history(document_id, "undo")
    assert undone["verified"] and undone["region_px"] == RECT["rect"]
    assert world.pixels(PAINT, RECT["rect"]) == bytes(4) * 200
    assert world.history(document_id, "redo")["verified"]
    assert world.pixels(PAINT, RECT["rect"]) == ORANGE * 200


def test_a_digest_the_fill_s_activation_moved_still_lets_a_stroke_name_the_preset(
    world: World,
) -> None:
    # Krita fills in a tip's defaults on a preset's first activation, which moves its digest.
    document_id, _ = world.document()
    name = painting.FILL_PRESET_NAME
    _, listed = resources.fingerprint(world.resources.xmls[name])
    real = world.port.set_fill

    def activated(*args: Any) -> dict[str, Any]:
        world.resources.xmls[name] = preset_xml(name, scatter={"PaintOpAction": "1", "x": "1"})
        return real(*args)

    world.port.set_fill = activated  # type: ignore[method-assign,assignment]
    fill(world, document_id)
    brush = {"preset_id": painting.FILL_PRESET, "preset_sha256": listed}
    done = world.run("paint.stroke", world.args(document_id, brush=brush, verify="full"))
    assert done["effective_brush"]["preset_sha256"] == listed
