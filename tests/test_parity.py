import hashlib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from bridge_core import documents
from parity import refused_alike
from worlds import World, running_world

from krita_art_mcp import roots
from krita_art_mcp.tools import branching, changes, painting, pixels, saving
from krita_art_mcp.tools import documents as documents_tools
from krita_art_mcp.tools.observe import LIMITS

ACCEPTED = b"accepted art"
CREATE = {
    "name": "sketch",
    "size_px": [64, 32],
    "color_model": "RGBA",
    "depth": "U8",
    "profile_id": documents.SRGB_PROFILE,
    "background": "transparent",
}
A_LAYER = "00000000-0000-4000-8000-000000000001"


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    with running_world(tmp_path) as running:
        yield running


def _art(world: World) -> Path:
    art = world.tmp_path / "art"
    (art / "accepted").mkdir(parents=True, exist_ok=True)
    roots.save(world.data / "config.json", [str(art)])
    return art


def _open(world: World, name: str = "hero.kra", **changes_: Any) -> dict[str, Any]:
    art = _art(world)
    source = art / "accepted" / name
    source.write_bytes(ACCEPTED)
    return {
        "source_path": str(source),
        "source_sha256": hashlib.sha256(ACCEPTED).hexdigest(),
        "mode": "working_copy",
        "working_dir": str(art / "work"),
        "request_id": "req-open",
        **changes_,
    }


def _document(world: World) -> str:
    created = world.server().content("krita_document_create", {**CREATE, "request_id": "req-new"})
    return str(created["document_id"])


@pytest.mark.parametrize(
    ("name", "changes_"),
    [
        ("hero.psd", {}),
        ("hero.ora", {"editable_layer_ids": [A_LAYER]}),
        ("hero.kra", {"editable_layer_names": ["rim"]}),
    ],
    ids=["another format", "ids for an ORA", "names for a KRA"],
)
def test_both_sides_hold_the_open_rules(
    world: World, monkeypatch: pytest.MonkeyPatch, name: str, changes_: dict[str, Any]
) -> None:
    arguments = _open(world, name, **changes_)
    rule = (documents_tools, "_open_rules")
    refused_alike(world, monkeypatch, "krita_document_open", arguments, rule)
    assert world.port.opened == []


@pytest.mark.parametrize("through", ["itself", "a link"])
def test_both_sides_keep_the_working_dir_out_of_the_sources_folder(
    world: World, monkeypatch: pytest.MonkeyPatch, through: str
) -> None:
    art = _art(world)
    folder = art / "accepted"
    if through == "a link":
        (art / "link").symlink_to(folder)
        folder = art / "link"
    arguments = _open(world, working_dir=str(folder))
    rule = (documents_tools, "_working_dir_rule")
    refused = refused_alike(world, monkeypatch, "krita_document_open", arguments, rule)
    assert refused["details"]["field"] == "working_dir"
    assert world.port.opened == [] and sorted(path.name for path in art.iterdir()) == sorted(
        ["accepted"] + (["link"] if through == "a link" else [])
    )


@pytest.mark.parametrize(
    "modifier",
    [{"grow_px": 2}, {"shrink_px": 2}, {"feather_px": 2}, {"invert": True}, {"combine": "add"}],
    ids=["grow", "shrink", "feather", "invert", "combine"],
)
def test_both_sides_clear_a_selection_with_no_modifiers(
    world: World, monkeypatch: pytest.MonkeyPatch, modifier: dict[str, Any]
) -> None:
    document_id = _document(world)
    arguments = {
        "guard": {"document_id": document_id, "request_id": "req-clear"},
        "combine": "replace",
        "shape": {"type": "none"},
        "feather_px": 0,
        "invert": False,
        **modifier,
    }
    rule = (changes, "_clear_rules")
    refused_alike(world, monkeypatch, "krita_selection_set", arguments, rule)
    assert world.port.recipes == []


@pytest.mark.parametrize(
    "changes_", [{"depth": "U16"}, {"profile_id": "sRGB-elle-V2-g10.icc"}], ids=["depth", "profile"]
)
def test_both_sides_create_only_u8_srgb(
    world: World, monkeypatch: pytest.MonkeyPatch, changes_: dict[str, Any]
) -> None:
    arguments = {**CREATE, **changes_, "request_id": "req-create"}
    rule = (documents_tools, "_create_rules")
    refused_alike(world, monkeypatch, "krita_document_create", arguments, rule)
    assert world.port.created == 0


def test_both_sides_save_only_kra_and_ora(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    document_id = _document(world)
    target = _art(world) / "revisions" / "hero.png"
    arguments = {
        "guard": {"document_id": document_id, "request_id": "req-save"},
        "path": str(target),
        "overwrite": False,
        "verify_reopen": True,
    }
    rule = (saving, "_save_rules")
    refused_alike(world, monkeypatch, "krita_document_save", arguments, rule)
    assert not target.parent.exists()


@pytest.mark.parametrize("name", ["hero.ora", "hero.png"])
def test_both_sides_duplicate_only_kra(
    world: World, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    document_id = _document(world)
    target = _art(world) / "branches" / name
    arguments = {
        "guard": {"document_id": document_id, "request_id": "req-dup"},
        "path": str(target),
    }
    plugin = refused_alike(
        world, monkeypatch, "krita_document_duplicate", arguments, (branching, "_duplicate_rules")
    )
    assert plugin["details"]["formats"] == [".kra"] and not target.parent.exists()


def test_both_sides_bound_a_capture_s_area(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    document_id = _document(world)
    side = 8192
    assert side * (side + 1) > LIMITS["capture_source_pixels"]
    arguments = {
        "source": {"document_id": document_id, "frame": 0},
        "target": "composite",
        "layer_id": None,
        "rect": {"x": 0, "y": 0, "width": side, "height": side + 1},
        "scale": 1,
        "filter": "nearest",
    }
    rule = (pixels, "_capture_rules")
    refused_alike(world, monkeypatch, "krita_capture", arguments, rule)


@pytest.mark.parametrize(
    "fields",
    [
        {"color": {"space": "srgb", "rgba": [0.8, 0.2, 0.4, 0.5]}},
        {"shape": {"type": "polygon", "points": [[0, 0], [10, 10], [4, 4]]}},
        {"shape": {"type": "path", "points": [[0, 0], [3, 1], [6, 2], [9.3, 3.1]]}},
    ],
    ids=["a colour with alpha", "a flat polygon", "a flat path"],
)
def test_both_sides_hold_the_fill_rules(
    world: World, monkeypatch: pytest.MonkeyPatch, fields: dict[str, Any]
) -> None:
    document_id = _document(world)
    arguments = {
        "guard": {"document_id": document_id, "request_id": "req-fill"},
        "layer_id": "00000000-0000-4000-8000-000000000002",
        "shape": {"type": "rect", "rect": {"x": 1, "y": 1, "width": 4, "height": 4}},
        "color": {"space": "srgb", "rgba": [0.8, 0.2, 0.4, 1]},
        "opacity": 1,
        **fields,
    }
    refused_alike(world, monkeypatch, "krita_paint_fill", arguments, (painting, "_fill_rules"))


def test_both_sides_want_a_colour_or_mask_paint(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    document_id = _document(world)
    fill = {
        "guard": {"document_id": document_id, "request_id": "req-fill"},
        "layer_id": A_LAYER,
        "shape": {"type": "rect", "rect": {"x": 1, "y": 1, "width": 4, "height": 4}},
        "opacity": 1,
    }
    refused_alike(world, monkeypatch, "krita_paint_fill", fill, (painting, "_fill_rules"))
    brush = {"preset_id": "basic-round.kpp", "size_px": 4, "opacity": 1, "flow": 1, "eraser": False}
    stroke = {
        "guard": {"document_id": document_id, "request_id": "req-stroke"},
        "layer_id": A_LAYER,
        "brush": brush,
        "points": [{"x": 1, "y": 1}, {"x": 9, "y": 1}],
    }
    refused_alike(world, monkeypatch, "krita_paint_stroke", stroke, (painting, "_brush_rules"))


def test_both_sides_want_a_stroke_s_colour_opaque(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    document_id = _document(world)
    stroke = _stroke(document_id, color={"space": "srgb", "rgba": [0.8, 0.2, 0.4, 0.5]})
    refused_alike(world, monkeypatch, "krita_paint_stroke", stroke, (painting, "_brush_rules"))


COLOUR = {"space": "srgb", "rgba": [0.8, 0.2, 0.4, 1]}
STROKE_BRUSH = ("inputSchema", "properties", "brush", "dependentSchemas")
FILL = ("inputSchema", "dependentSchemas")


@pytest.mark.parametrize(
    ("paint", "cut"),
    [
        ({"color": COLOUR, "mask": "reveal"}, "color"),
        ({"mask": "reveal", "blend_mode": "multiply"}, "mask"),
        ({"mask": "reveal", "alpha_lock": True}, "mask"),
    ],
    ids=["colour-and-mask", "mask-with-a-blend", "mask-with-alpha-lock"],
)
@pytest.mark.parametrize("tool", ["krita_paint_stroke", "krita_paint_fill"])
def test_both_sides_hold_what_mask_paint_takes(
    world: World, monkeypatch: pytest.MonkeyPatch, tool: str, paint: dict[str, Any], cut: str
) -> None:
    # The schema refuses a blend or alpha lock by its presence; the plugin, which gets the
    # server's defaults, refuses any value that does something.
    document_id = _document(world)
    path: tuple[str, ...]
    if tool == "krita_paint_stroke":
        arguments = _stroke(document_id, **{"color": None, **paint})
        path = (*STROKE_BRUSH, cut)
    else:
        arguments = _fill(document_id, **paint)
        path = (*FILL, cut)
    refused_alike(world, monkeypatch, tool, arguments, schema=path)


def test_both_sides_give_coverage_to_a_mask_alone(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    document_id = _document(world)
    arguments = {
        "guard": {"document_id": document_id, "request_id": "req-layer"},
        # The plugin reads the coverage before any id, so these need only be well formed.
        "parent_id": A_LAYER,
        "above_id": None,
        "type": "paint",
        "name": "flat",
        "coverage": "all",
    }
    path = ("inputSchema", "dependentSchemas", "type")
    refused = refused_alike(world, monkeypatch, "krita_layer_create", arguments, schema=path)
    assert refused["details"]["field"] == "coverage"


def test_both_sides_give_a_working_dir_to_a_working_copy_alone(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    arguments = _open(world, mode="read_only")
    path = ("inputSchema", "dependentSchemas", "mode")
    refused_alike(world, monkeypatch, "krita_document_open", arguments, schema=path)
    assert world.port.opened == []


def test_both_sides_refuse_a_nearly_flat_closed_curve(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    # From a seeded search: its points lie on one line to 1e-9, its control points do not.
    points = [
        [27.013786811462, 6.693029212093],
        [34.193283113747, 12.794430413475],
        [25.591661617824, 5.484454683674],
        [23.195680188611, 3.448261145016],
        [34.083412529148, 12.701058331805],
    ]
    arguments = _fill(document_id=_document(world), color=COLOUR)
    arguments["shape"] = {"type": "path", "points": points}
    refused_alike(world, monkeypatch, "krita_paint_fill", arguments, (painting, "_fill_rules"))


TAPER = [{"at": 0, "value": 0.2}, {"at": 1, "value": 1}]


@pytest.mark.parametrize(
    ("dynamics", "brush"),
    [
        ({"size": [{"at": 0.2, "value": 1}, {"at": 1, "value": 1}]}, {}),
        (
            {"opacity": [{"at": 0, "value": 1}, {"at": 0.0004, "value": 1}, {"at": 1, "value": 1}]},
            {},
        ),
        ({"size": TAPER}, {"preset_sha256": None}),
        ({"size": TAPER}, {"color": None, "mask": "reveal"}),
    ],
    ids=["knots-start", "knots-apart", "no-sha", "mask-paint"],
)
def test_both_sides_hold_a_taper_s_rules(
    world: World,
    monkeypatch: pytest.MonkeyPatch,
    dynamics: dict[str, Any],
    brush: dict[str, Any],
) -> None:
    arguments = _stroke(_document(world), **{"preset_sha256": "e" * 64, **brush})
    if arguments["brush"]["preset_sha256"] is None:
        del arguments["brush"]["preset_sha256"]
    arguments["dynamics"] = dynamics
    refused_alike(
        world, monkeypatch, "krita_paint_stroke", arguments, (painting, "_dynamics_rules")
    )


def test_both_sides_want_a_taper_at_least_a_pixel_long(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    arguments = _stroke(_document(world), preset_sha256="e" * 64)
    arguments["points"] = [{"x": 1, "y": 1}, {"x": 1.8, "y": 1}]
    arguments["dynamics"] = {"size": TAPER}
    rule = (painting, "_dynamics_length")
    refused = refused_alike(world, monkeypatch, "krita_paint_stroke", arguments, rule)
    assert refused["details"]["field"] == "dynamics"


def _stroke(document_id: str, **brush: Any) -> dict[str, Any]:
    found = {"preset_id": "basic-round.kpp", "size_px": 4, "opacity": 1, "flow": 1}
    found.update(eraser=False, color=COLOUR)
    found.update(brush)
    if found["color"] is None:
        del found["color"]
    return {
        "guard": {"document_id": document_id, "request_id": "req-stroke"},
        "layer_id": A_LAYER,
        "brush": found,
        "points": [{"x": 1, "y": 1}, {"x": 9, "y": 1}],
    }


def _fill(document_id: str, **paint: Any) -> dict[str, Any]:
    return {
        "guard": {"document_id": document_id, "request_id": "req-fill"},
        "layer_id": A_LAYER,
        "shape": {"type": "rect", "rect": {"x": 1, "y": 1, "width": 4, "height": 4}},
        "opacity": 1,
        **paint,
    }


@pytest.mark.parametrize(
    ("place", "field"),
    [({"parent_id": A_LAYER, "above_id": None}, "parent_id"), ({"above_id": A_LAYER}, "above_id")],
    ids=["inside_itself", "above_itself"],
)
def test_both_sides_refuse_a_layer_moved_inside_or_above_itself(
    world: World, monkeypatch: pytest.MonkeyPatch, place: dict[str, Any], field: str
) -> None:
    arguments = {
        "guard": {"document_id": _document(world), "request_id": "req-move"},
        "layer_id": A_LAYER,
        "parent_id": "root-1",
        "above_id": None,
        **place,
    }
    rule = (changes, "reorder_rules")
    refused = refused_alike(world, monkeypatch, "krita_layer_reorder", arguments, rule)
    assert refused["details"]["field"] == field


def _translate(world: World, by: list[Any]) -> dict[str, Any]:
    return {
        "guard": {"document_id": _document(world), "request_id": "req-translate"},
        "layer_id": A_LAYER,
        "operation": {"type": "translate", "by_px": by},
    }


def test_both_sides_refuse_a_translate_that_moves_nothing(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    rule = (changes, "transform_rules")
    arguments = _translate(world, [0, 0])
    refused = refused_alike(world, monkeypatch, "krita_layer_transform", arguments, rule)
    assert refused["details"]["field"] == "by_px"


def test_both_sides_refuse_a_translate_past_its_range(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = ("inputSchema", "properties", "operation", "oneOf", 0, "properties", "by_px", "items")
    arguments = _translate(world, [16385, 0])
    refused = refused_alike(
        world, monkeypatch, "krita_layer_transform", arguments, schema=(*path, "maximum")
    )
    assert refused["details"]["field"] == "by_px"


def _reshape(world: World, operation: dict[str, Any]) -> dict[str, Any]:
    return {
        "guard": {"document_id": _document(world), "request_id": "req-reshape"},
        "layer_id": A_LAYER,
        "operation": operation,
    }


@pytest.mark.parametrize(
    ("operation", "field"),
    [
        ({"type": "rotate", "degrees": 0}, "degrees"),
        ({"type": "shear", "degrees": [0, 0]}, "degrees"),
    ],
)
def test_both_sides_refuse_a_turn_or_shear_of_nothing(
    world: World, monkeypatch: pytest.MonkeyPatch, operation: dict[str, Any], field: str
) -> None:
    rule = (changes, "transform_rules")
    arguments = _reshape(world, operation)
    refused = refused_alike(world, monkeypatch, "krita_layer_transform", arguments, rule)
    assert refused["details"]["field"] == field


OPERATION = ("inputSchema", "properties", "operation", "oneOf")


@pytest.mark.parametrize(
    ("operation", "cut", "field"),
    [
        (
            {"type": "scale", "size_px": [0, 4], "filter": "Bicubic"},
            (1, "properties", "size_px", "items", "minimum"),
            "size_px",
        ),
        (
            {"type": "scale", "size_px": [16385, 4], "filter": "Bicubic"},
            (1, "properties", "size_px", "items", "maximum"),
            "size_px",
        ),
        (
            {"type": "scale", "size_px": [4.5, 4], "filter": "Bicubic"},
            (1, "properties", "size_px", "items", "type"),
            "size_px",
        ),
        (
            {"type": "scale", "size_px": [4, 4, 4], "filter": "Bicubic"},
            (1, "properties", "size_px", "maxItems"),
            "size_px",
        ),
        (
            {"type": "scale", "size_px": [4, 4], "filter": "Box"},
            (1, "properties", "filter", "enum"),
            "filter",
        ),
        (
            {"type": "rotate", "degrees": 360},
            (2, "properties", "degrees", "exclusiveMaximum"),
            "degrees",
        ),
        (
            {"type": "rotate", "degrees": -360},
            (2, "properties", "degrees", "exclusiveMinimum"),
            "degrees",
        ),
        (
            {"type": "shear", "degrees": [46, 0]},
            (3, "properties", "degrees", "items", "maximum"),
            "degrees",
        ),
        (
            {"type": "shear", "degrees": [0, -46]},
            (3, "properties", "degrees", "items", "minimum"),
            "degrees",
        ),
        ({"type": "shear", "degrees": [10]}, (3, "properties", "degrees", "minItems"), "degrees"),
    ],
)
def test_both_sides_refuse_a_scale_rotate_or_shear_past_its_schema(
    world: World,
    monkeypatch: pytest.MonkeyPatch,
    operation: dict[str, Any],
    cut: tuple[Any, ...],
    field: str,
) -> None:
    arguments = _reshape(world, operation)
    refused = refused_alike(
        world, monkeypatch, "krita_layer_transform", arguments, schema=(*OPERATION, *cut)
    )
    assert refused["details"]["field"] == field


@pytest.mark.parametrize(
    ("operation", "cut"),
    [
        ({"type": "warp"}, ("inputSchema", "properties", "operation", "oneOf")),
        (
            {"type": "rotate", "degrees": 10, "filter": "Bicubic"},
            (*OPERATION, 2, "additionalProperties"),
        ),
        (
            {"type": "shear", "degrees": [10, 0], "filter": "Bilinear"},
            (*OPERATION, 3, "additionalProperties"),
        ),
        (
            {"type": "scale", "size_px": [4, 4], "filter": "Bicubic", "degrees": 1},
            (*OPERATION, 1, "additionalProperties"),
        ),
    ],
)
def test_both_sides_refuse_an_operation_of_another_type_or_field(
    world: World, monkeypatch: pytest.MonkeyPatch, operation: dict[str, Any], cut: tuple[Any, ...]
) -> None:
    arguments = _reshape(world, operation)
    refused = refused_alike(world, monkeypatch, "krita_layer_transform", arguments, schema=cut)
    assert refused["code"] == "INVALID_ARGUMENT"


def test_both_sides_refuse_a_copy_with_no_name(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    arguments = {
        "guard": {"document_id": _document(world), "request_id": "req-copy"},
        "layer_id": A_LAYER,
        "name": "",
    }
    path = ("inputSchema", "properties", "name", "minLength")
    refused_alike(world, monkeypatch, "krita_layer_duplicate", arguments, schema=path)


def test_both_sides_take_region_or_full_for_a_removal(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    arguments = {
        "guard": {"document_id": _document(world), "request_id": "req-remove"},
        "layer_id": A_LAYER,
        "verify": "everywhere",
    }
    path = ("inputSchema", "properties", "verify", "enum")
    refused_alike(world, monkeypatch, "krita_layer_remove", arguments, schema=path)


@pytest.mark.parametrize("tool", ["krita_layer_duplicate", "krita_layer_create"])
def test_both_sides_bound_a_layers_name(
    world: World, monkeypatch: pytest.MonkeyPatch, tool: str
) -> None:
    guard = {"document_id": _document(world), "request_id": "req-name"}
    arguments: dict[str, Any] = (
        {"guard": guard, "layer_id": A_LAYER, "name": "n" * 257}
        if tool == "krita_layer_duplicate"
        else {
            "guard": guard,
            "parent_id": "root-1",
            "above_id": None,
            "type": "paint",
            "name": "n" * 257,
        }
    )
    path = ("inputSchema", "properties", "name", "maxLength")
    refused = refused_alike(world, monkeypatch, tool, arguments, schema=path)
    assert refused["details"]["field"] == "name"
