import copy
import logging
import math
from pathlib import Path
from typing import Any

import pytest
from bridge_core import brushes, documents, painting, resources
from bridge_core.bridge import Bridge
from bridge_core.errors import BridgeError
from fake_krita import (
    BRUSH_ORDER,
    SCATTERED,
    fake_node,
    layer_id,
    preset_xml,
)
from paint_world import (
    BASE,
    BASE_PIXEL,
    FAR,
    HEIGHT,
    LABEL,
    ORANGE,
    PAINT,
    WIDTH,
    A,
    World,
    box,
)

PACKAGE = Path(__file__).resolve().parents[2] / "plugin" / "krita_art_mcp_bridge"


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


def _spec_bytes(spec: dict[str, Any]) -> bytes:
    return Path(spec["path"]).read_bytes()


# R for the default stroke: the path (40..50, 60) grown by 32, and the ring by another 32.
REGION = box(8, 28, 74, 64)
RING = box(0, 0, 114, 120)
# The default stroke's dabs: radius 5 around (40, 60) and (50, 60).
DABS = box(35, 55, 20, 10)


# A stroke.


def test_a_stroke_on_a_document_behind_announces_with_its_view_in_front(world: World) -> None:
    document_id, handle = world.document()
    world.port.front_key = 99
    world.stroke(document_id)
    assert world.port.announced == [(handle.document.key, handle.document.key)]


def test_a_refused_stroke_announces_nothing(world: World) -> None:
    document_id, _ = world.document()
    assert world.stroke_refused(document_id, layer_id=layer_id(1, 99))["code"]
    assert world.port.announced == []


def test_a_stroke_is_painted_verified_over_r_and_reported(world: World) -> None:
    document_id, handle = world.document()
    done = world.stroke(document_id)
    assert done["stroke_id"] == f"op-{2:032x}"
    assert (done["layer_id"], done["accepted_points"]) == (PAINT, 2)
    assert done["changed_bounds_px"] == DABS
    assert (done["undo_label"], done["undo_steps"], done["protected_pixels_changed"]) == (
        LABEL,
        1,
        0,
    )
    assert done["history_sealed"] is False
    effective = done["effective_brush"]
    assert (
        effective["preset_sha256"] == resources.fingerprint(world.resources.xmls["Basic Round"])[1]
    )
    assert (effective["engine"], effective["spacing"], effective["antialias"]) == (
        "paintbrush",
        0.1,
        True,
    )
    assert effective["color"] == {"space": "srgb", "rgba": [1, 0.5, 0, 1]}
    assert effective["reach"] == {"tip": "round", "scatter": 0.0, "margin_px": 32.0}
    checked = done["verification"]
    assert (checked["mode"], checked["rect"]) == ("region", REGION)
    assert checked["changed_bounds_px"] == DABS and checked["changed_outside_px"] == 0
    assert world.pixels(PAINT, box(40, 60, 1, 1)) == ORANGE
    assert world.port._tree(1)["nodes"][1]["bounds_px"] == DABS
    [step] = handle.ledger.steps
    assert (step.op, step.label, step.region) == ("paint.stroke", LABEL, DABS)
    assert step.before == step.after and step.witness is not None
    assert (step.witness[0], step.witness[1]) == (PAINT, DABS)
    assert handle.dirty and not handle.unsafe


def test_history_undoes_and_redoes_a_stroke_by_its_witness(world: World) -> None:
    document_id, _ = world.document()
    world.stroke(document_id)
    undone = world.history(document_id, "undo")
    assert undone["verified"] and world.pixels(PAINT, box(40, 60, 1, 1)) == bytes(4)
    assert undone["region_px"] == DABS
    redone = world.history(document_id, "redo")
    assert redone["verified"] and world.pixels(PAINT, box(40, 60, 1, 1)) == ORANGE


def test_the_target_is_read_over_the_ring_and_protected_layers_over_their_meeting(
    world: World,
) -> None:
    document_id, _ = world.document()
    world.layer_reads.clear()
    world.stroke(document_id)
    read = {layer for layer, _ in world.layer_reads}
    # The far layer does not meet R: its bounds hold it, and it is never read.
    assert read == {PAINT, BASE}
    assert {rect for layer, rect in map(_frozen, world.layer_reads) if layer == PAINT} == {
        _frozen((PAINT, RING))[1]
    }
    assert {rect for layer, rect in map(_frozen, world.layer_reads) if layer == BASE} == {
        _frozen((BASE, REGION))[1]
    }


def _frozen(read: tuple[str, dict[str, int]]) -> tuple[str, tuple[int, ...]]:
    layer, rect = read
    return layer, (rect["x"], rect["y"], rect["width"], rect["height"])


def test_full_scope_reads_the_canvas_the_target_s_old_bounds_and_every_protected_layer(
    world: World,
) -> None:
    document_id, _ = world.document()
    world.port._tree(1)["nodes"][1]["bounds_px"] = box(150, 100, 60, 30)
    world.layer_reads.clear()
    done = world.stroke(document_id, verify="full")
    assert done["verification"]["rect"] == box(0, 0, WIDTH, HEIGHT)
    target = {_frozen(read)[1] for read in world.layer_reads if read[0] == PAINT}
    # Old bounds and R' together, clipped to the canvas.
    assert target == {(0, 0, WIDTH, HEIGHT)}
    assert {read[0] for read in world.layer_reads} == {PAINT, BASE, FAR}
    # Each protected layer over its own bounds within the scope.
    assert {_frozen(read)[1] for read in world.layer_reads if read[0] == FAR} == {(180, 0, 20, 10)}


# Refusals before any change, in order.


def test_refusals_come_in_their_order_and_change_nothing(world: World) -> None:
    document_id, handle = world.document()
    tree = world.port._tree(1)
    tree["nodes"].append(fake_node(1, 5, "blur", tree["root_id"], 4, type="filterlayer"))
    world.port.cumulative = True
    world.port.live[1]["space"] = ("RGBA", "U16", documents.SRGB_PROFILE)
    changes: dict[str, Any] = {
        "layer_id": BASE,
        "path": {"start": [-6, 60], "segments": [[50, 60]]},
        "brush": {"preset_id": "basic-rond.kpp", "preset_sha256": "0" * 64},
    }
    expected = [
        "COLOR_PROFILE_MISMATCH",
        "LOCKED_TARGET",
        "INVALID_ARGUMENT",
        "INVALID_ARGUMENT",
        "RESOURCE_HASH_MISMATCH",
        "UNSUPPORTED_CAPABILITY",
        "UNSUPPORTED_CAPABILITY",
    ]
    found = []
    for fix in range(len(expected)):
        body = world.stroke_refused(document_id, **copy.deepcopy(changes))
        found.append(body["code"])
        if fix == 0:
            del world.port.live[1]["space"]
        elif fix == 1:
            assert body["details"] == {"layer_id": BASE}
            del changes["layer_id"]
        elif fix == 2:
            assert body["details"]["point_index"] == 0
            del changes["path"]
        elif fix == 3:
            assert body["details"]["nearest"][0] == "basic-round.kpp"
            assert len(body["details"]["nearest"]) == 5
            changes["brush"]["preset_id"] = "basic-round.kpp"
        elif fix == 4:
            del changes["brush"]
        elif fix == 5:
            assert body["details"]["reason"] == "cumulative_undo"
            world.port.cumulative = False
        else:
            assert body["details"]["reasons"] == [
                {"reason": "filter_layer", "node_id": layer_id(1, 5)}
            ]
    assert found == expected
    assert world.port.brush_order == [] and "paint" not in world.port.calls
    assert not handle.dirty and world.stroke(document_id, verify="full")["undo_steps"] == 1


@pytest.mark.parametrize(
    ("node", "code"),
    [
        ({"type": "grouplayer"}, "LAYER_NOT_PAINTABLE"),
        ({"type": "filllayer"}, "LAYER_NOT_PAINTABLE"),
        ({"depth": "U16"}, "COLOR_PROFILE_MISMATCH"),
    ],
)
def test_a_target_that_is_not_an_rgba_u8_paint_layer_is_refused(
    world: World, node: dict[str, Any], code: str
) -> None:
    document_id, handle = world.document()
    world.port._tree(1)["nodes"][1].update(node)
    assert world.stroke_refused(document_id)["code"] == code
    assert world.port.brush_order == [] and not handle.dirty


def test_an_unknown_layer_and_any_local_selection_mask_are_refused(world: World) -> None:
    document_id, _ = world.document()
    body = world.stroke_refused(document_id, layer_id=layer_id(1, 99))
    assert body["code"] == "LAYER_NOT_FOUND"
    mask = world.port.mask(1, PAINT)
    # Any mask, active or not: libkis does not say which one is.
    world.port._tree(1)["active_id"] = PAINT
    body = world.stroke_refused(document_id)
    assert body["code"] == "LAYER_HAS_LOCAL_SELECTION" and body["details"]["mask_ids"] == [mask]


def test_a_preset_whose_xml_krita_cannot_write_is_refused(world: World) -> None:
    document_id, _ = world.document()
    body = world.stroke_refused(document_id, brush={"preset_id": "broken.kpp"})
    assert body["code"] == "INVALID_ARGUMENT" and world.port.brush_order == []


def test_a_matching_preset_hash_passes(world: World) -> None:
    document_id, _ = world.document()
    digest = resources.fingerprint(world.resources.xmls["Basic Round"])[1]
    done = world.stroke(document_id, brush={"preset_sha256": digest})
    assert done["effective_brush"]["preset_sha256"] == digest


@pytest.mark.parametrize(
    "changes",
    [
        {"accepted_points": 0},
        {"accepted_points": 4097},
        {"accepted_points": True},
        {"verify": "partial"},
        {"layer_id": "paint"},
        {"brush": {"size_px": 0.5}},
        {"brush": {"size_px": 1001}},
        {"brush": {"size_px": float("inf")}},
        {"brush": {"opacity": 1.5}},
        {"brush": {"flow": -0.1}},
        {"brush": {"color": [1, 0, 0]}},
        {"brush": {"color": [1, 0, 0, 0.5]}},
        {"brush": {"color": [2, 0, 0, 1]}},
        {"brush": {"eraser": True, "alpha_lock": True}},
        {"brush": {"eraser": 1}},
        {"brush": {"blend_mode": "dissolve"}},
        {"brush": {"rotation_deg": float("nan")}},
        {"brush": {"preset_sha256": "ABC"}},
        {"brush": {"preset_id": ""}},
        {"brush": {"spacing": 0.1}},
        {"path": {"start": [40, 60], "segments": []}},
        {"path": {"start": [40, 60], "segments": [[1, 2, 3]]}},
        {"path": {"start": [40, 60], "segments": [[50, True]]}},
        {"path": {"start": [40, float("nan")], "segments": [[50, 60]]}},
        {"path": {"start": [40, 60], "segments": [[50, 60]] * 4096}},
        {"path": {"start": [40, 60]}},
    ],
)
def test_malformed_arguments_are_refused(world: World, changes: dict[str, Any]) -> None:
    document_id, _ = world.document()
    body = world.refused("paint.stroke", world.args(document_id, **changes))
    assert body["code"] == "INVALID_ARGUMENT"


def test_unknown_or_missing_fields_are_refused(world: World) -> None:
    document_id, _ = world.document()
    args = world.args(document_id)
    del args["accepted_points"]
    assert world.refused("paint.stroke", args)["code"] == "INVALID_ARGUMENT"
    args = world.args(document_id)
    del args["brush"]["rotation_deg"]
    assert world.refused("paint.stroke", args)["code"] == "INVALID_ARGUMENT"


# The canvas check takes on-curve points only.


def test_control_points_may_lie_anywhere_but_on_curve_points_may_not(world: World) -> None:
    document_id, _ = world.document()
    curve = {"start": [40, 60], "segments": [[-500, -500, 900, 900, 60, 60]]}
    world.stroke(document_id, path=curve)
    # Exactly half the brush off the canvas still touches it.
    edge = {"start": [-5, 60], "segments": [[WIDTH + 5, HEIGHT + 5]]}
    world.stroke(document_id, path=edge, verify="full")
    off = {"start": [40, 60], "segments": [[60, 60], [WIDTH + 5.5, 60]]}
    body = world.stroke_refused(document_id, path=off)
    assert body["code"] == "INVALID_ARGUMENT" and body["details"]["point_index"] == 2


def test_r_grows_by_the_control_points_too(world: World) -> None:
    document_id, _ = world.document()
    curve = {"start": [40, 60], "segments": [[30, 50, 70, 50, 60, 60]]}
    done = world.stroke(document_id, path=curve)
    assert done["verification"]["rect"] == box(0, 18, 102, 74)


# The brush.


def test_the_brush_is_set_in_k3_s_order_and_the_blend_survives_the_preset(world: World) -> None:
    document_id, _ = world.document()
    done = world.stroke(document_id, brush={"blend_mode": "multiply", "rotation_deg": 30})
    assert tuple(world.port.brush_order) == BRUSH_ORDER
    assert world.port.brush_now["preset"] == "Basic Round"
    assert done["effective_brush"]["blend_mode"] == "multiply"
    assert done["effective_brush"]["rotation_deg"] == 30


def test_every_field_is_set_on_every_call(world: World) -> None:
    document_id, _ = world.document()
    world.port.brush_now["eraser"] = True
    world.stroke(document_id)
    assert world.port.brush_now["eraser"] is False
    assert world.port.brush_order == list(BRUSH_ORDER)


def test_values_krita_adjusts_are_reported_as_it_holds_them(world: World) -> None:
    document_id, _ = world.document()
    world.port.adjust = {"size_px": 9.5, "opacity": 0.99, "color": [1, 0.5, 0.01, 1]}
    effective = world.stroke(document_id)["effective_brush"]
    assert (effective["size_px"], effective["opacity"]) == (9.5, 0.99)
    assert effective["color"]["rgba"] == [1, 0.5, 0.01, 1]


@pytest.mark.parametrize("field", ["preset", "blend_mode", "eraser", "alpha_lock"])
def test_a_brush_field_krita_did_not_take_refuses_before_any_change(
    world: World, field: str
) -> None:
    document_id, handle = world.document()
    world.port.brush_now.update(preset="Hard Round", blend_mode="screen", alpha_lock=True)
    world.port.brush_now["eraser"] = True
    world.port.ignore_brush = {field}
    body = world.stroke_refused(document_id, brush={"blend_mode": "multiply"})
    assert body["code"] == "INTERNAL_ERROR" and field in body["details"]["fields"]
    assert "paint" not in world.port.calls and not handle.dirty


def test_a_brush_changed_after_it_was_set_refuses_before_any_change(world: World) -> None:
    document_id, handle = world.document()
    world.port.brush_drift = {"size_px": 11.0}
    body = world.stroke_refused(document_id)
    assert body["code"] == "INTERNAL_ERROR"
    assert "paint" not in world.port.calls and not handle.dirty and handle.ledger.steps == []


def test_paint_ability_is_asked_after_the_brush_with_the_view_in_front(world: World) -> None:
    document_id, handle = world.document()
    world.port.front_key = 99
    world.port.ability[PAINT] = "CLONE"
    world.port.calls.clear()
    body = world.stroke_refused(document_id)
    assert body["code"] == "LAYER_NOT_PAINTABLE" and body["details"]["paint_ability"] == "CLONE"
    assert world.port.brush_order and world.port.calls.index("forward") < world.port.calls.index(
        "ability"
    )
    assert world.port.calls[-1] == "restore" and not handle.dirty


# The reach.


def _auto(mask: str) -> str:
    return f'<Brush type="auto_brush" spacing="0.05"><MaskGenerator type="{mask}"/></Brush>'


@pytest.mark.parametrize(
    ("xml", "tip", "spacing", "scatter", "reasons"),
    [
        (preset_xml("a"), "round", 0.1, 0.0, []),
        (preset_xml("a", brush=_auto("rect")), "square", 0.05, 0.0, []),
        (preset_xml("a", brush='<Brush type="gbr_brush" spacing="1"/>'), "image", 1.0, 0.0, []),
        (preset_xml("a", brush=_auto("gauss")), None, 0.05, 0.0, ["brush_tip"]),
        (preset_xml("a", brush='<Brush spacing="1"/>'), None, 1.0, 0.0, ["brush_tip"]),
        (preset_xml("a", brush="<Brush"), None, None, 0.0, ["brush_tip"]),
        (preset_xml("a", brush=""), None, None, 0.0, ["brush_tip"]),
        (preset_xml("a", scatter=SCATTERED), "round", 0.1, 2.0, []),
        (
            preset_xml("a", scatter={**SCATTERED, "Scattering/AxisX": "false"}),
            "round",
            0.1,
            0.0,
            [],
        ),
        (preset_xml("a", scatter={**SCATTERED, "Scattering/AxisY": "true"}), "round", 0.1, 2.0, []),
        (preset_xml("a", scatter={}), "round", 0.1, None, ["brush_scatter"]),
        (
            preset_xml("a", scatter={k: v for k, v in SCATTERED.items() if k != "ScatterValue"}),
            "round",
            0.1,
            None,
            ["brush_scatter"],
        ),
        (
            preset_xml(
                "a", scatter={k: v for k, v in SCATTERED.items() if k != "Scattering/AxisY"}
            ),
            "round",
            0.1,
            None,
            ["brush_scatter"],
        ),
        (
            preset_xml("a", scatter={**SCATTERED, "ScatterValue": "6"}),
            "round",
            0.1,
            None,
            ["brush_scatter"],
        ),
        (preset_xml("a", scatter={"PressureScatter": "false"}), "round", 0.1, 0.0, []),
        (preset_xml("a", engine="colorsmudge"), "round", 0.1, 0.0, ["brush_engine"]),
        ("", None, None, None, ["brush_engine", "brush_tip", "brush_scatter"]),
    ],
)
def test_the_reach_is_parsed_from_the_preset_and_fails_closed(
    xml: str, tip: str | None, spacing: float | None, scatter: float | None, reasons: list[str]
) -> None:
    found = brushes.brush_reach(xml)
    assert (found["tip"], found["spacing"], found["scatter"], found["reasons"]) == (
        tip,
        spacing,
        scatter,
        reasons,
    )


def test_the_margin_is_set_by_the_tip_and_the_scatter() -> None:
    assert brushes.margin_px(10, "round", 0) == 32
    assert brushes.margin_px(100, "round", 0) == 52
    assert brushes.margin_px(100, "square", 0) == pytest.approx(100 * math.sqrt(2) / 2 + 2)
    # A rotated image tip's mask is up to sqrt(2) times its size, and scatter scales with it.
    assert brushes.margin_px(100, "image", 1) == pytest.approx(100 * 3 * math.sqrt(2) / 2 + 2)
    assert brushes.margin_px(20, "round", 2) == 52


@pytest.mark.parametrize(
    ("preset", "size", "margin"),
    [
        ("hard-square.kpp", 100, 100 * math.sqrt(2) / 2 + 2),
        ("bristles.kpp", 60, 60 * math.sqrt(2) / 2 + 2),
        ("scatter.kpp", 20, 52),
        ("hard-round.kpp", 100, 52),
    ],
)
def test_r_grows_by_the_effective_brush_s_margin(
    world: World, preset: str, size: float, margin: float
) -> None:
    document_id, _ = world.document()
    done = world.stroke(document_id, brush={"preset_id": preset, "size_px": size})
    assert done["effective_brush"]["reach"]["margin_px"] == pytest.approx(margin)
    left, right = math.floor(40 - margin), math.ceil(50 + margin)
    top, bottom = math.floor(60 - margin), math.ceil(60 + margin)
    expected = box(max(0, left), max(0, top), min(WIDTH, right) - max(0, left), 0)
    expected["height"] = min(HEIGHT, bottom) - max(0, top)
    assert done["verification"]["rect"] == expected


def test_r_comes_from_the_size_krita_holds(world: World) -> None:
    document_id, _ = world.document()
    world.port.adjust = {"size_px": 100.0}
    done = world.stroke(document_id, brush={"size_px": 10})
    assert done["effective_brush"]["reach"]["margin_px"] == 52


@pytest.mark.parametrize(
    ("preset", "reason"),
    [
        ("smudge.kpp", "brush_engine"),
        ("no-scatter-keys.kpp", "brush_scatter"),
        ("airbrush-soft.kpp", "brush_engine"),
    ],
)
def test_a_reach_that_cannot_be_named_refuses_region_and_full_paints(
    world: World, preset: str, reason: str
) -> None:
    document_id, handle = world.document()
    body = world.stroke_refused(document_id, brush={"preset_id": preset})
    assert body["code"] == "UNSUPPORTED_CAPABILITY"
    assert {"reason": reason} in body["details"]["reasons"]
    assert "paint" not in world.port.calls and not handle.dirty
    done = world.stroke(document_id, brush={"preset_id": preset}, verify="full")
    assert done["verification"]["mode"] == "full"


def test_full_scope_widens_an_unnamed_reach(world: World) -> None:
    document_id, _ = world.document()
    done = world.stroke(
        document_id, brush={"preset_id": "airbrush-soft.kpp", "size_px": 10}, verify="full"
    )
    reach = done["effective_brush"]["reach"]
    assert reach == {
        "tip": "unknown",
        "scatter": brushes.MAX_SCATTER,
        "margin_px": pytest.approx(10 * (math.sqrt(2) / 2) * 11 + 2),
    }
    assert done["effective_brush"]["engine"] == "airbrush"


def test_the_reach_is_read_from_the_preset_krita_holds_after_the_brush(world: World) -> None:
    document_id, _ = world.document()
    # Krita's current preset is dirty: its XML now scatters, unlike the listed one.
    world.port.preset_xml["Basic Round"] = preset_xml("Basic Round", scatter=SCATTERED)
    done = world.stroke(document_id)
    assert done["effective_brush"]["reach"]["scatter"] == 2.0


# The allowed mask.


def test_a_stroke_wholly_outside_the_allowed_mask_is_refused_before_painting(
    world: World,
) -> None:
    document_id, handle = world.document()
    world.allow(document_id, box(150, 0, 50, 20))
    body = world.stroke_refused(document_id)
    assert body["code"] == "OUTSIDE_ALLOWED_MASK" and body["details"]["region_px"] == REGION
    assert "paint" not in world.port.calls and not handle.dirty
    # Full scope still asks about R alone.
    assert world.stroke_refused(document_id, verify="full")["code"] == "OUTSIDE_ALLOWED_MASK"


# Each check, and its rollback on the ledger.


def test_a_leak_is_undone_on_the_ledger_confirmed_and_refused(world: World) -> None:
    document_id, handle = world.document()
    world.allow(document_id, box(0, 0, 45, HEIGHT))
    body = world.stroke_refused(document_id)
    assert (body["code"], body["retryable"]) == ("PROTECTED_REGION_CHANGED", False)
    details = body["details"]
    assert (details["rolled_back"], details["rollback_verified"]) == (True, True)
    assert (details["protected_layer_ids"], details["protected_pixels_changed"]) == ([], 0)
    assert details["target_outside_reach"] is False
    checked = details["verification"]
    assert (checked["changed_px"], checked["changed_outside_px"]) == (200, 100)
    assert checked["after"] is None and checked["diff"] is not None
    assert world.pixels(PAINT, DABS) == bytes(4 * 200)
    assert world.port._tree(1)["nodes"][1]["bounds_px"] == box(0, 0, 0, 0)
    assert handle.ledger.steps == [] and not handle.dirty and not handle.unsafe
    # K43: Krita keeps the undone stroke as a redo, and history never offers it.
    assert world.port.undo_labels(handle.document)[1] == LABEL
    assert world.history_refused(document_id, "redo")["code"] == "INVALID_ARGUMENT"


def test_an_alpha_change_is_refused_under_preserve_composite_alpha(world: World) -> None:
    document_id, _ = world.document()
    canvas = world.port.canvas[1]
    assert isinstance(canvas, bytearray)
    canvas[3::4] = bytes(WIDTH * HEIGHT)
    world.allow(document_id, box(0, 0, WIDTH, HEIGHT), preserve=True)
    body = world.stroke_refused(document_id)
    assert body["code"] == "PROTECTED_REGION_CHANGED"
    assert body["details"]["verification"]["alpha_changed_px"] == 200


def test_a_protected_layer_s_changed_pixels_are_counted_and_undone(world: World) -> None:
    document_id, _ = world.document()

    def touch(key: int) -> None:
        start = (60 * WIDTH + 40) * 4
        world.port.buffers[BASE][start : start + 12] = bytes(12)

    world.port.on_paint.append(touch)
    body = world.stroke_refused(document_id)
    details = body["details"]
    assert body["code"] == "PROTECTED_REGION_CHANGED"
    assert (details["protected_layer_ids"], details["protected_pixels_changed"]) == ([BASE], 3)
    assert details["rollback_verified"] is True
    assert world.pixels(BASE, box(40, 60, 3, 1)) == BASE_PIXEL * 3


def test_only_the_first_changed_protected_layer_is_counted(world: World) -> None:
    document_id, handle = world.document()
    tree = world.port._tree(1)
    tree["nodes"].append(fake_node(1, 6, "rim", tree["root_id"], 5, bounds_px=box(0, 0, 60, 60)))
    rim = layer_id(1, 6)
    handle.protected.add(rim)
    world.port.paintable(1, BASE_PIXEL)

    def touch(key: int) -> None:
        world.port.buffers[BASE][0:8] = bytes(8)
        start = (40 * WIDTH + 40) * 4
        world.port.buffers[rim][start : start + 4] = bytes(4)

    world.port.on_paint.append(touch)
    body = world.stroke_refused(document_id, verify="full")
    details = body["details"]
    assert details["protected_layer_ids"] == sorted([BASE, rim])
    # The base comes first in the tree, and only its pixels are held and counted.
    assert details["protected_pixels_changed"] == 2


def test_a_protected_layer_s_bounds_are_checked_where_its_pixels_are_not_read(
    world: World,
) -> None:
    document_id, handle = world.document()

    def grow(key: int) -> None:
        world.port._tree(1)["nodes"][2]["bounds_px"] = box(170, 0, 30, 10)

    world.port.on_paint.append(grow)
    body = world.stroke_refused(document_id)
    assert body["code"] == "PROTECTED_REGION_CHANGED"
    assert body["details"]["protected_layer_ids"] == [FAR]
    assert FAR not in {layer for layer, _ in world.layer_reads}
    assert body["details"]["rollback_verified"] is True and not handle.unsafe


def test_a_stroke_past_r_inside_the_ring_is_undone(world: World) -> None:
    document_id, _ = world.document()
    world.port.stray = [box(85, 60, 2, 2)]
    body = world.stroke_refused(document_id)
    assert body["code"] == "PROTECTED_REGION_CHANGED"
    assert body["details"]["target_outside_reach"] is True
    assert body["details"]["rollback_verified"] is True
    assert world.pixels(PAINT, box(85, 60, 1, 1)) == bytes(4)


def test_a_stroke_past_r_inside_the_old_bounds_is_caught_by_the_ring(world: World) -> None:
    document_id, _ = world.document()
    world.port._tree(1)["nodes"][1]["bounds_px"] = box(0, 0, WIDTH, HEIGHT)
    world.port.stray = [box(4, 4, 2, 2)]
    body = world.stroke_refused(document_id)
    assert body["details"]["target_outside_reach"] is True


def test_target_bounds_grown_past_the_ring_are_undone(world: World) -> None:
    document_id, _ = world.document()
    # Off the canvas, so no read sees it; Krita's bounds are not clipped.
    world.port.stray = [box(-60, 60, 2, 2)]
    body = world.stroke_refused(document_id)
    assert body["details"]["target_outside_reach"] is True
    assert world.port._tree(1)["nodes"][1]["bounds_px"] == box(0, 0, 0, 0)


def test_full_scope_does_not_hold_the_target_to_r(world: World) -> None:
    document_id, handle = world.document()
    world.port.stray = [box(85, 60, 2, 2)]
    done = world.stroke(document_id, verify="full")
    assert done["changed_bounds_px"] == box(35, 55, 52, 10)
    assert not handle.unsafe and len(handle.ledger.steps) == 1


def test_full_scope_widens_the_changed_bounds_by_what_it_painted_past_the_read(
    world: World,
) -> None:
    document_id, handle = world.document()
    # Past R' on the canvas, and off it: neither is read. The first grows the changed bounds, and
    # only the layer's own bounds show the second.
    world.port.stray = [box(150, 60, 2, 2), box(-60, 60, 2, 2)]
    done = world.stroke(document_id, verify="full")
    assert done["changed_bounds_px"] == box(0, 55, 152, 10)
    assert done["layer_bounds_px"] == box(-60, 55, 212, 10)
    # The witness stays the diff over what was read.
    witness = handle.ledger.steps[-1].witness
    assert witness is not None and witness[1] == DABS


EDGES = {
    "top": ([100, -4], [110, -4]),
    "bottom": ([100, 124], [110, 124]),
    "left": ([-4, 60], [-4, 70]),
    "right": ([204, 60], [204, 70]),
    "top left": ([-4, -4], [-2, -2]),
    "top right": ([204, -4], [202, -2]),
    "bottom left": ([-4, 124], [-2, 122]),
    "bottom right": ([204, 124], [202, 122]),
}


def _dabs(start: list[int], end: list[int]) -> dict[str, int]:
    # What the fake paints with the default 10 px brush, unclipped.
    left, right = min(start[0], end[0]) - 5, max(start[0], end[0]) + 5
    top, bottom = min(start[1], end[1]) - 5, max(start[1], end[1]) + 5
    return box(left, top, right - left, bottom - top)


@pytest.mark.parametrize("verify", ["region", "full"])
@pytest.mark.parametrize("ends", EDGES.values(), ids=EDGES)
def test_a_stroke_past_an_edge_reports_the_canvas_and_the_layer_apart(
    world: World, ends: tuple[list[int], list[int]], verify: str
) -> None:
    document_id, _ = world.document()
    start, end = ends
    done = world.stroke(document_id, verify=verify, path={"start": start, "segments": [end]})
    assert done["layer_bounds_px"] == _dabs(start, end)
    assert done["changed_bounds_px"] == painting._clip(_dabs(start, end), [WIDTH, HEIGHT])


def test_a_layer_that_already_overhangs_does_not_trip_a_stroke_far_from_it(world: World) -> None:
    document_id, _ = world.document()
    world.port._tree(1)["nodes"][1]["bounds_px"] = box(-30, -20, 60, 50)
    done = world.stroke(document_id, verify="full")
    assert done["changed_bounds_px"] == DABS
    assert done["layer_bounds_px"] == box(-30, -20, 85, 85)


@pytest.mark.parametrize("verify", ["region", "full"])
def test_a_stroke_wholly_past_the_canvas_changes_nothing_on_it(world: World, verify: str) -> None:
    document_id, _ = world.document()
    path = {"start": [-5, 40], "segments": [[-5, 60]]}
    done = world.stroke(document_id, verify=verify, path=path)
    assert done["changed_bounds_px"] is None and done["history_sealed"] is True
    assert done["layer_bounds_px"] == box(-10, 35, 10, 30)
    assert done["verification"]["changed_px"] == 0


def test_an_undo_takes_the_overhang_back(world: World) -> None:
    document_id, _ = world.document()
    empty = world.port._tree(1)["nodes"][1]["bounds_px"]
    world.stroke(document_id, path={"start": [-4, 60], "segments": [[-4, 70]]}, verify="full")
    assert world.port._tree(1)["nodes"][1]["bounds_px"] != empty
    assert world.history(document_id, "undo")["steps_applied"] == 1
    assert world.port._tree(1)["nodes"][1]["bounds_px"] == empty


def test_a_layer_with_no_paint_reports_no_bounds(world: World) -> None:
    document_id, _ = world.document()
    world.port.brush_now["eraser"] = True
    done = world.stroke(document_id, brush={"eraser": True})
    assert done["layer_bounds_px"] is None and done["changed_bounds_px"] is None


def test_target_bounds_inside_the_unclipped_ring_pass(world: World) -> None:
    document_id, _ = world.document()
    edge = {"start": [2, 60], "segments": [[4, 60]]}
    done = world.stroke(document_id, path=edge)
    assert done["layer_bounds_px"]["x"] == -3
    assert done["changed_bounds_px"] == box(0, 55, 9, 10)


# Rollbacks off the ledger.


def test_a_stroke_that_raises_before_painting_is_confirmed_without_an_undo(world: World) -> None:
    document_id, handle = world.document()
    world.stroke(document_id)
    world.port.fail["paint_path"] = RuntimeError("Krita raised")
    world.port.calls.clear()
    body = world.stroke_refused(document_id, path={"start": [60, 60], "segments": [[70, 60]]})
    assert (body["code"], body["retryable"]) == ("INTERNAL_ERROR", False)
    details = body["details"]
    assert (details["rolled_back"], details["rollback_verified"]) == (False, True)
    assert "undo" not in world.port.calls
    # The earlier stroke is still there, and history stops above it.
    assert world.pixels(PAINT, box(40, 60, 1, 1)) == ORANGE
    assert handle.ledger.undo_available() == 0 and handle.dirty


def test_a_stroke_that_raises_after_painting_is_undone_by_its_witness(world: World) -> None:
    document_id, handle = world.document()
    world.port.fail["paint_path_after"] = RuntimeError("Krita raised")
    body = world.stroke_refused(document_id)
    details = body["details"]
    assert body["code"] == "INTERNAL_ERROR"
    assert (details["rolled_back"], details["rollback_verified"]) == (True, True)
    assert world.pixels(PAINT, DABS) == bytes(4 * 200)
    assert world.port.undo_labels(handle.document)[1] == LABEL
    assert handle.ledger.steps == [] and not handle.dirty
    assert world.history_refused(document_id, "redo")["code"] == "INVALID_ARGUMENT"


def test_a_push_that_raises_is_undone_by_its_witness(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    document_id, handle = world.document()

    def refuse(step: Any, limit: int) -> None:
        raise RuntimeError("the ledger raised")

    monkeypatch.setattr(handle.ledger, "push", refuse)
    body = world.stroke_refused(document_id)
    assert body["details"]["rolled_back"] is True and body["details"]["rollback_verified"]
    assert world.pixels(PAINT, DABS) == bytes(4 * 200)


def _paint_then(world: World, then: Any) -> None:
    paint = world.port.paint_path

    def painted(document: Any, layer: str, path: dict[str, Any]) -> None:
        paint(document, layer, path)
        then(document)
        raise RuntimeError("Krita raised")

    world.port.paint_path = painted  # type: ignore[assignment]


def test_a_raise_under_a_foreign_top_step_marks_the_document_unsafe(world: World) -> None:
    document_id, handle = world.document()
    _paint_then(world, lambda document: world.port._push(1, "Foreign", world.port._state(1)))
    body = world.stroke_refused(document_id)
    assert body["code"] == "ROLLBACK_FAILED" and body["details"]["cause"] == "INTERNAL_ERROR"
    assert body["details"]["rolled_back"] is False and handle.unsafe and handle.dirty
    assert world.port.undo_labels(handle.document)[0] == "Foreign"


def test_a_raise_under_another_stroke_marks_the_document_unsafe(world: World) -> None:
    document_id, handle = world.document()
    paint = world.port.paint_path

    def again(document: Any) -> None:
        world.port.brush_now["color"] = [0, 0, 1, 1]
        paint(document, PAINT, {"start": [45, 60], "segments": [[45, 60]]})

    _paint_then(world, again)
    body = world.stroke_refused(document_id)
    assert body["code"] == "ROLLBACK_FAILED" and handle.unsafe
    # The top stroke was undone, failed its witness, and was put back.
    assert world.pixels(PAINT, box(45, 60, 1, 1)) == bytes([255, 0, 0, 255])
    assert world.port.undo_labels(handle.document) == (LABEL, None)


def test_a_change_with_no_target_pixel_to_witness_marks_the_document_unsafe(
    world: World,
) -> None:
    document_id, handle = world.document()

    def protected(document: Any) -> None:
        start = (60 * WIDTH + 40) * 4
        world.port.buffers[BASE][start : start + 4] = bytes(4)

    world.port.brush_now["eraser"] = True
    _paint_then(world, protected)
    body = world.stroke_refused(document_id, brush={"eraser": True})
    assert body["code"] == "ROLLBACK_FAILED" and handle.unsafe
    assert body["details"]["rolled_back"] is False


def test_a_step_s_region_holds_the_target_s_diff_where_the_composite_kept(world: World) -> None:
    document_id, handle = world.document()
    world.stroke(document_id)
    # The fake's eraser leaves the composite alone, as a hidden layer's stroke would.
    done = world.stroke(document_id, brush={"eraser": True})
    assert done["verification"]["changed_bounds_px"] is None
    assert done["changed_bounds_px"] == DABS and handle.ledger.steps[-1].region == DABS


def test_an_empty_diff_seals_history_and_pushes_nothing(world: World) -> None:
    document_id, handle = world.document()
    world.stroke(document_id, path={"start": [150, 100], "segments": [[160, 100]]})
    assert handle.ledger.undo_available() == 1
    done = world.stroke(document_id, brush={"eraser": True})
    assert done["changed_bounds_px"] is None and done["undo_steps"] == 1
    # The receipt says history stops here, since nothing could confirm the step's undo.
    assert done["history_sealed"] is True
    assert len(handle.ledger.steps) == 1 and handle.ledger.undo_available() == 0
    assert world.port.undo_labels(handle.document)[0] == LABEL


@pytest.mark.parametrize(
    ("raised", "code"),
    [
        (RuntimeError("Krita raised"), "INTERNAL_ERROR"),
        (BridgeError("IO_ERROR", "a retryable failure", True), "IO_ERROR"),
        (BridgeError("LAYER_NOT_FOUND", "gone"), "LAYER_NOT_FOUND"),
    ],
)
def test_a_failure_after_the_first_change_is_never_retryable(
    world: World, raised: BaseException, code: str
) -> None:
    document_id, handle = world.document()
    world.port.fail["paint_path_after"] = raised
    body = world.stroke_refused(document_id)
    assert (body["code"], body["retryable"]) == (code, False)
    assert body["details"]["rollback_verified"] is True and not handle.dirty


def test_an_undo_krita_does_not_take_fails_the_rollback(world: World) -> None:
    document_id, handle = world.document()
    world.allow(document_id, box(0, 0, 45, HEIGHT))
    world.port.undo_works = False
    body = world.stroke_refused(document_id)
    assert body["code"] == "ROLLBACK_FAILED"
    assert body["details"]["cause"] == "PROTECTED_REGION_CHANGED"
    assert body["details"]["rolled_back"] is False and body["details"]["verification"]
    assert handle.unsafe and handle.dirty
    world.port.undo_works = True
    assert world.stroke_refused(document_id)["code"] == "DOCUMENT_UNSAFE"


def test_a_protected_change_whose_undo_fails_is_not_counted(world: World) -> None:
    document_id, _ = world.document()

    def touch(key: int) -> None:
        start = (60 * WIDTH + 40) * 4
        world.port.buffers[BASE][start : start + 12] = bytes(12)

    world.port.on_paint.append(touch)
    world.port.undo_works = False
    body = world.stroke_refused(document_id)
    details = body["details"]
    assert body["code"] == "ROLLBACK_FAILED"
    # Nothing was undone, so the layer's pixels now measure nothing.
    assert (details["protected_layer_ids"], details["protected_pixels_changed"]) == ([BASE], None)


def test_a_rollback_whose_reread_differs_fails(world: World) -> None:
    document_id, handle = world.document()
    world.allow(document_id, box(0, 0, 45, HEIGHT))
    undo = world.port.undo

    def drifting(document: Any) -> None:
        undo(document)
        canvas = world.port.canvas[1]
        assert isinstance(canvas, bytearray)
        canvas[(30 * WIDTH + 30) * 4] ^= 1

    world.port.undo = drifting  # type: ignore[method-assign]
    body = world.stroke_refused(document_id)
    assert body["code"] == "ROLLBACK_FAILED"
    assert (body["details"]["rolled_back"], body["details"]["rollback_verified"]) == (True, False)
    assert handle.unsafe


def test_a_protected_change_whose_undo_is_not_confirmed_is_not_counted(world: World) -> None:
    document_id, _ = world.document()

    def touch(key: int) -> None:
        start = (60 * WIDTH + 40) * 4
        world.port.buffers[BASE][start : start + 12] = bytes(12)

    undo = world.port.undo

    def drifting(document: Any) -> None:
        undo(document)
        canvas = world.port.canvas[1]
        assert isinstance(canvas, bytearray)
        canvas[(30 * WIDTH + 30) * 4] ^= 1

    world.port.on_paint.append(touch)
    world.port.undo = drifting  # type: ignore[method-assign]
    details = world.stroke_refused(document_id)["details"]
    assert (details["rolled_back"], details["rollback_verified"]) == (True, False)
    assert (details["protected_layer_ids"], details["protected_pixels_changed"]) == ([BASE], None)


def test_a_rollback_that_leaves_the_target_s_bounds_grown_fails(world: World) -> None:
    document_id, handle = world.document()
    world.allow(document_id, box(0, 0, 45, HEIGHT))
    undo = world.port.undo

    def kept_bounds(document: Any) -> None:
        undo(document)
        world.port._tree(1)["nodes"][1]["bounds_px"] = DABS

    world.port.undo = kept_bounds  # type: ignore[method-assign]
    body = world.stroke_refused(document_id)
    assert body["code"] == "ROLLBACK_FAILED" and handle.unsafe


def test_an_interrupt_after_the_first_change_marks_the_document_unsafe(world: World) -> None:
    document_id, handle = world.document()
    world.stroke(document_id)
    world.port.fail["paint_path"] = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        world.stroke(document_id)
    assert handle.unsafe and handle.ledger.undo_available() == 0


# History's witness.


def test_a_hand_undo_stops_history_at_the_stroke_it_took(world: World) -> None:
    document_id, handle = world.harness_document()
    world.stroke(document_id)
    world.stroke(document_id, path={"start": [120, 60], "segments": [[130, 60]]})
    handle.dirty = False
    undone = world.run("harness.undo", {"document_id": document_id})
    assert (undone["undo"], undone["redo"]) == (LABEL, LABEL)
    # An undo through the bridge changes the document, so closing with refuse must see it.
    assert handle.dirty
    assert handle.ledger.undo_available() == 2
    world.stroke(document_id, path={"start": [80, 20], "segments": [[90, 20]]})
    # The ledger names three strokes; Krita holds the first and the third.
    found = world.history(document_id, "undo", 3)
    assert (found["steps_applied"], found["stopped"]) == (1, "not_the_bridges_step")
    assert world.pixels(PAINT, box(40, 60, 1, 1)) == ORANGE
    assert handle.ledger.undo_available() == 0


def test_a_stroke_by_hand_on_top_is_not_the_bridges(world: World) -> None:
    document_id, handle = world.harness_document()
    world.stroke(document_id)
    world.port.brush_now["color"] = [0, 0, 1, 1]
    world.port.paint_path(handle.document, PAINT, {"start": [45, 60], "segments": [[45, 60]]})
    body = world.history_refused(document_id, "undo")
    assert body["code"] == "INVALID_ARGUMENT" and body["details"]["found_label"] == LABEL
    assert world.pixels(PAINT, box(45, 60, 1, 1)) == bytes([255, 0, 0, 255])
    assert handle.ledger.undo_available() == 0


def test_a_stroke_by_hand_between_the_bridges_stops_history_there(world: World) -> None:
    document_id, handle = world.harness_document()
    world.stroke(document_id)
    world.port.brush_now["color"] = [0, 0, 1, 1]
    world.port.paint_path(handle.document, PAINT, {"start": [45, 60], "segments": [[45, 60]]})
    world.stroke(document_id, path={"start": [120, 60], "segments": [[130, 60]]})
    found = world.history(document_id, "undo", 2)
    assert (found["steps_applied"], found["stopped"]) == (1, "not_the_bridges_step")


# The harness's ops.


def test_the_harness_reads_and_sets_the_view_of_its_document_in_front(world: World) -> None:
    document_id, _ = world.harness_document()
    read = world.run("harness.view", {"document_id": document_id, "view": None})
    assert read["view"] == {"zoom": 1.0, "rotation_deg": 0.0, "pan_px": [0, 0]}
    view = {"zoom": 2.5, "rotation_deg": 30, "pan_px": [10, -4]}
    assert world.run("harness.view", {"document_id": document_id, "view": view})["view"] == view
    for bad in ({}, {"zoom": 0}, {"pan_px": [1.5, 0]}, {"tilt": 1}, {"rotation_deg": math.inf}):
        body = world.refused("harness.view", {"document_id": document_id, "view": bad})
        assert body["code"] == "INVALID_ARGUMENT"
    world.port.front_key = None
    body = world.refused("harness.view", {"document_id": document_id, "view": None})
    assert body["code"] == "INVALID_ARGUMENT"


def test_the_harness_reads_and_writes_the_brush_state_back(world: World) -> None:
    document_id, _ = world.harness_document()
    args = {"document_id": document_id, "action": "read", "preset_ids": ["hard-round.kpp"]}
    state = world.run("harness.brush_state", args)["state"]
    assert set(state) == {"current", "presets"} and "preset_xml" not in state["current"]
    world.stroke(document_id, brush={"size_px": 40, "blend_mode": "screen"})
    world.port.preset_state["hard-round.kpp"] = {"size_px": 3.0}
    write = {"document_id": document_id, "action": "write", "state": state}
    assert world.run("harness.brush_state", write) == {"document_id": document_id}
    assert world.port.brush_now["size_px"] == 10.0
    assert world.port.brush_now["blend_mode"] == "normal"
    assert world.port.preset_state["hard-round.kpp"]["size_px"] == 10.0
    for bad in (
        {"document_id": document_id, "action": "read", "preset_ids": [""]},
        {"document_id": document_id, "action": "read", "preset_ids": "x"},
        {"document_id": document_id, "action": "read", "state": {}},
        {"document_id": document_id, "action": "write", "state": []},
        {"document_id": document_id, "action": "erase"},
    ):
        assert world.refused("harness.brush_state", bad)["code"] == "INVALID_ARGUMENT"


def test_the_harness_ops_take_only_its_own_documents(world: World) -> None:
    document_id, _ = world.document()
    for op, args in (
        ("harness.view", {"document_id": document_id, "view": None}),
        ("harness.brush_state", {"document_id": document_id, "action": "read", "preset_ids": []}),
        ("harness.undo", {"document_id": document_id}),
    ):
        assert world.refused(op, args)["code"] == "PATH_NOT_ALLOWED"


# What the bridge retains.


def test_harness_retention_counts_what_the_bridge_holds(tmp_path: Path) -> None:
    bridge = Bridge(
        data_dir=tmp_path / "data",
        package_dir=PACKAGE,
        facts={"krita_version": "5.3.4", "qt_major": 5},
        handlers={"echo": lambda args, call: {}},
        wake=lambda: None,
        on_main_thread=lambda: True,
        is_live_krita=lambda pid: False,
        log=logging.getLogger("painting-test"),
    )
    assert bridge.jobs.retention() == {"operations": 0, "requests": 0, "bound": 0}
    bridge.jobs.submit("op-1", "req-1", "echo", {}, A)
    bridge.jobs.submit("op-2", "req-1", "echo", {}, A)
    retention = bridge.jobs.submit("op-3", "req-3", "harness.retention", {}, A)
    bridge.drain()
    assert retention is not None
    assert retention.reply()["result"] == {"operations": 3, "requests": 2, "bound": 2}
    refused = bridge.jobs.submit("op-4", "req-4", "harness.retention", {"x": 1}, A)
    gone = bridge.jobs.submit("op-5", "req-5", "probe.retention", {}, A)
    bridge.drain()
    assert refused is not None and refused.reply()["error"]["code"] == "INVALID_ARGUMENT"
    assert gone is not None and "Unknown op" in gone.reply()["error"]["message"]


def test_a_preset_krita_fills_in_on_its_first_activation_keeps_its_listed_digest(
    world: World,
) -> None:
    document_id, _ = world.document()
    name = "Hard Round"
    listed = resources.fingerprint(world.resources.xmls[name])[1]
    real = world.port.set_brush
    filled = world.resources.xmls[name].replace(
        "</Preset>", '<param name="Filled">1</param></Preset>'
    )

    def first_load(document: Any, brush: dict[str, Any], preset: Any) -> dict[str, Any]:
        # Krita adds what the stored preset leaves out when it first loads it.
        world.resources.xmls[name] = filled
        return real(document, brush, preset)

    world.port.set_brush = first_load  # type: ignore[method-assign]
    brush = {"preset_id": "hard-round.kpp", "preset_sha256": listed}
    first = world.stroke(document_id, brush=brush)
    second = world.stroke(document_id, brush=brush)
    assert first["effective_brush"]["preset_sha256"] == listed
    assert second["effective_brush"]["preset_sha256"] == listed
    # The digest Krita lists now is taken too, and anything the owner changes is not.
    now = resources.fingerprint(filled)[1]
    assert world.stroke(document_id, brush={**brush, "preset_sha256": now})["layer_id"] == PAINT
    world.resources.xmls[name] = filled.replace('"Filled">1', '"Filled">2')
    refused = world.stroke_refused(document_id, brush=brush)
    assert refused["code"] == "RESOURCE_HASH_MISMATCH"


def test_a_stroke_walks_the_preset_list_once_and_reads_the_stored_preset_twice(
    world: World,
) -> None:
    document_id, _ = world.document()
    world.resources.calls.clear()
    world.stroke(document_id)
    assert world.resources.calls == ["preset", "preset_xml"]


def test_a_dirty_preset_the_view_holds_never_vouches_for_a_later_saved_change(
    world: World,
) -> None:
    document_id, _ = world.document()
    name = "Hard Round"
    listed = resources.fingerprint(world.resources.xmls[name])[1]
    tweaked = world.resources.xmls[name].replace(
        "</Preset>", '<param name="Tweak">1</param></Preset>'
    )
    world.port.preset_xml[name] = tweaked
    brush = {"preset_id": "hard-round.kpp", "preset_sha256": listed}
    assert world.stroke(document_id, brush=brush)["effective_brush"]["preset_sha256"] == listed
    # The owner saves the tweak, so the stored preset is no longer the one that was listed.
    world.resources.xmls[name] = tweaked
    assert world.stroke_refused(document_id, brush=brush)["code"] == "RESOURCE_HASH_MISMATCH"
