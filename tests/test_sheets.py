import math
from typing import Any

import numpy as np
import pytest
from PIL import Image

from krita_art_mcp import imaging, sheets

SRGB = "sRGB-elle-V2-srgbtrc.icc"
RIVER = {"space": "srgb", "rgba": [0.2, 0.4, 0.6, 1]}


def _source(
    width: int = 650,
    height: int = 490,
    x: int = 0,
    y: int = 0,
    *,
    baseline: str | None = None,
    anchor: tuple[float, float] | None = None,
    units: float | None = 4,
    master: float | None = 0.5,
) -> sheets.Source:
    rect = {"x": x, "y": y, "width": width, "height": height}
    return sheets.Source(
        document_id="doc-1",
        target="composite",
        layer_id=None,
        baseline_id=baseline,
        profile_id=SRGB,
        rect=rect,
        anchor=anchor or (x + width / 2, y + height / 2),
        export_pixels_per_unit=units,
        master_to_export_scale=master,
    )


def _world(per_unit: float, **changes: Any) -> dict[str, Any]:
    return {"id": f"game-{per_unit}", "target_pixels_per_unit": per_unit, **changes}


def _icon(width: int, height: int, **changes: Any) -> dict[str, Any]:
    return {"id": f"icon-{width}", "target_size_px": [width, height], **changes}


def _arguments(recipes: list[dict[str, Any]], count: int = 1, **changes: Any) -> dict[str, Any]:
    return {
        "recipes": recipes,
        "filter": "lanczos",
        "sources": [{} for _ in range(count)],
        "overlays": [],
        "backgrounds": ["transparent"],
        **changes,
    }


def _art(height: int, width: int, seed: int = 1, opaque: bool = True) -> np.ndarray:
    pixels = np.random.default_rng(seed).integers(0, 256, (height, width, 4), dtype=np.uint8)
    if opaque:
        pixels[..., 3] = 255
    return pixels


def _cell(sheet: sheets.Sheet, column: int = 0, row: int = 0) -> np.ndarray:
    data = sheet.data
    x, y = data["columns"][column]["x_px"], data["rows"][row]["y_px"]
    width, height = data["cell_px"]
    return np.asarray(sheet.image.convert("RGBA"))[y : y + height, x : x + width]


def _apply(transform: list[int | float], point: tuple[float, float]) -> tuple[float, float]:
    m00, m01, m02, m10, m11, m12 = transform
    return m00 * point[0] + m01 * point[1] + m02, m10 * point[0] + m11 * point[1] + m12


@pytest.mark.parametrize(
    ("per_unit", "size"),
    [(2.95, (240, 181)), (1.8, (146, 110))],
    ids=["2.95", "1.8"],
)
def test_a_world_unit_scale_is_target_over_export_times_master(
    per_unit: float, size: tuple[int, int]
) -> None:
    # The first game's recipes on a 2x master: 2.95 / 4 x 0.5 and 1.8 / 4 x 0.5.
    scale, got = sheets.scaled(_world(per_unit), _source(), 0)
    assert scale == pytest.approx(per_unit / 4 * 0.5) and got == size


def test_sides_round_half_up_never_to_even() -> None:
    # 10 x 0.25 = 2.5 rounds up to 3, where round() would give 2.
    _, size = sheets.scaled(_world(1), _source(10, 2, units=4, master=1), 0)
    assert size == (3, 1)


@pytest.mark.parametrize("missing", ["units", "master"])
def test_a_world_unit_recipe_needs_both_units_for_every_source(missing: str) -> None:
    source = _source(**{missing: None})  # type: ignore[arg-type]
    with pytest.raises(sheets.Refused) as refused:
        sheets.scaled(_world(2.95), source, 3)
    assert refused.value.code == "INVALID_ARGUMENT"
    assert refused.value.details == {"source": 3, "recipe_id": "game-2.95"}


def test_an_exact_size_recipe_fits_its_box_and_centres_the_image() -> None:
    wide = sheets.layout(_icon(128, 128), [_source(512, 384)], ["transparent"], [], False)
    assert wide.placed[0].size == (128, 96) and wide.placed[0].offset == (0, 16)
    assert wide.cell == (128, 128) and wide.placed[0].scale == 0.25
    tall = sheets.layout(_icon(128, 128), [_source(384, 512)], ["transparent"], [], False)
    assert tall.placed[0].size == (96, 128) and tall.placed[0].offset == (16, 0)
    # 512 x 100 fits as 128 x 25, its offset 51.5 rounded half up.
    thin = sheets.layout(_icon(128, 128), [_source(512, 100)], ["transparent"], [], False)
    assert thin.placed[0].size == (128, 25) and thin.placed[0].offset == (0, 52)


def test_an_anchor_that_pushes_an_image_out_of_its_box_is_refused_never_clipped() -> None:
    corner = _source(512, 512, anchor=(0, 0))
    with pytest.raises(sheets.Refused) as refused:
        sheets.layout(_icon(128, 128), [corner], ["transparent"], [], False)
    assert refused.value.code == "INVALID_ARGUMENT"
    assert refused.value.details == {"source": 0, "recipe_id": "icon-128"}


def test_the_cell_transform_maps_the_crop_onto_its_image_exactly() -> None:
    source = _source(650, 490, 50, 20)
    for recipe in (_world(2.95), _world(1.8), _icon(128, 128), _world(2.95, integer_zoom=3)):
        found = sheets.layout(recipe, [source], ["transparent"], [], False)
        placed, zoom = found.placed[0], found.zoom
        transform = sheets.document_to_cell(source, placed, zoom)
        left, top = _apply(transform, (50, 20))
        right, bottom = _apply(transform, (700, 510))
        assert (left, top) == pytest.approx((placed.offset[0] * zoom, placed.offset[1] * zoom))
        assert (right - left, bottom - top) == pytest.approx(
            (placed.size[0] * zoom, placed.size[1] * zoom)
        )


def test_siblings_of_other_sizes_meet_at_their_anchors() -> None:
    hero = _source(650, 490, anchor=(325, 470))
    sibling = _source(300, 200, 10, 10, anchor=(160, 205), master=1)
    found = sheets.layout(_world(2.95), [hero, sibling], ["transparent"], [], False)
    met = [
        _apply(sheets.document_to_cell(source, placed, 1), source.anchor)
        for source, placed in zip([hero, sibling], found.placed, strict=True)
    ]
    # Each lands within half a pixel of one shared whole-pixel point, in [C - 0.5, C + 0.5).
    shared = {tuple(math.floor(value + 0.5) for value in point) for point in met}
    assert len(shared) == 1
    # The cell holds both images whole.
    for placed in found.placed:
        assert all(placed.offset[a] + placed.size[a] <= found.cell[a] for a in (0, 1))


def test_a_cell_is_the_native_crop_resampled_once_with_the_filter() -> None:
    art = _art(490, 650)
    [sheet] = sheets.render(_arguments([_world(2.95)]), [_source()], {(0, "current"): art}, {})
    expected = np.asarray(Image.fromarray(art).resize((240, 181), Image.Resampling.LANCZOS))
    assert (_cell(sheet) == expected).all()
    assert sheet.data["columns"][0]["filter"] == "lanczos"


def test_a_native_size_cell_keeps_the_crops_bytes_and_applies_no_filter() -> None:
    art = _art(4, 8, opaque=False)
    source = _source(8, 4, units=4, master=1)
    [sheet] = sheets.render(_arguments([_world(4)]), [source], {(0, "current"): art}, {})
    assert (_cell(sheet) == art).all() and sheet.data["columns"][0]["filter"] is None
    assert sheet.image.mode == "RGBA"


def test_integer_zoom_replicates_the_game_size_cell_and_scales_its_transform() -> None:
    art = _art(490, 650)
    crops = {(0, "current"): art}
    [plain] = sheets.render(_arguments([_world(1.8)]), [_source()], crops, {})
    [zoomed] = sheets.render(_arguments([_world(1.8, integer_zoom=3)]), [_source()], crops, {})
    replicated = np.repeat(np.repeat(_cell(plain), 3, axis=0), 3, axis=1)
    assert (_cell(zoomed) == replicated).all()
    assert zoomed.data["cell_px"] == [146 * 3, 110 * 3]
    plain_t = plain.data["columns"][0]["document_to_cell"]
    zoomed_t = zoomed.data["columns"][0]["document_to_cell"]
    assert zoomed_t == pytest.approx([3 * value for value in plain_t])


def test_columns_put_the_document_as_opened_before_now_and_rows_follow_the_treatments() -> None:
    sources = [_source(baseline="baseline-0123456789ab"), _source()]
    tints = [{"id": "dusk", "multiply": [1, 0.8, 0.7], "add": [0, 0, 0]}]
    found = sheets.layout(_world(1.8), sources, [RIVER, "checker"], tints, True)
    assert found.columns == [(0, "as_opened"), (0, "current"), (1, "current")]
    assert [(row.background, row.tint, row.greyscale) for row in found.rows] == [
        (RIVER, None, False),
        (RIVER, None, True),
        (RIVER, tints[0], False),
        (RIVER, tints[0], True),
        ("checker", None, False),
        ("checker", None, True),
        ("checker", tints[0], False),
        ("checker", tints[0], True),
    ]
    gutter = sheets.GUTTER_PX
    assert found.size == (gutter + 3 * (146 + gutter), gutter + 8 * (110 + gutter))


def test_a_tint_applies_to_the_whole_cell_and_greyscale_comes_after() -> None:
    art = np.zeros((2, 4, 4), dtype=np.uint8)
    art[:, :2] = (200, 100, 50, 255)
    tint = {"id": "dusk", "multiply": [0.5, 1, 1], "add": [0, 0.1, 0]}
    arguments = _arguments(
        [_world(4)], backgrounds=[{"space": "srgb", "rgba": [0, 0, 1, 1]}], tints=[tint]
    )
    arguments["greyscale"] = True
    source = _source(4, 2, units=4, master=1)
    [sheet] = sheets.render(arguments, [source], {(0, "current"): art}, {})
    tinted = _cell(sheet, row=2)
    # The art and the background both take the tint; 125.5 and 25.5 round half up.
    assert tuple(tinted[0, 0]) == (100, 126, 50, 255)
    assert tuple(tinted[0, 3]) == (0, 26, 255, 255)
    grey = _cell(sheet, row=3)
    expected = imaging.lightness(tinted)
    assert (grey[..., 0] == expected).all() and (grey[..., 2] == expected).all()


def test_overlays_are_drawn_only_into_the_sheet_never_the_clean_sheet() -> None:
    art = _art(40, 60)
    mask = np.zeros((40, 60), dtype=np.uint8)
    mask[10:30, 20:40] = 255
    source = _source(60, 40, units=4, master=1)
    arguments = _arguments([_world(4)], overlays=["selection"])
    [sheet] = sheets.render(arguments, [source], {(0, "current"): art}, {0: {"selection": mask}})
    assert sheet.clean is not None
    drawn, clean = np.asarray(sheet.image), np.asarray(sheet.clean)
    changed = (drawn != clean).any(axis=-1)
    assert changed.any() and (drawn[changed][:, :3] == sheets.OVERLAY_RGB["selection"]).all()
    assert sheet.data["columns"][0]["overlays"] == ["selection"]
    # The edge only: the region's inside and the crop's own border stay as painted.
    cell = _cell(sheet)
    assert (cell[20, 30] == art[20, 30]).all() and (cell[0, 0] == art[0, 0]).all()
    assert (cell[10, 25, :3] == sheets.OVERLAY_RGB["selection"]).all()


def test_a_mask_with_nothing_to_outline_leaves_no_clean_sheet() -> None:
    whole = np.full((40, 60), 255, dtype=np.uint8)
    source = _source(60, 40, units=4, master=1)
    arguments = _arguments([_world(4)], overlays=["allowed_mask"])
    crops = {(0, "current"): _art(40, 60)}
    [sheet] = sheets.render(arguments, [source], crops, {0: {"allowed_mask": whole}})
    assert sheet.clean is None and sheet.data["columns"][0]["overlays"] == []


def test_a_sheet_over_its_long_edge_is_refused_never_shrunk() -> None:
    tints = [{"id": f"t{n}", "multiply": [1, 1, 1], "add": [0, 0, 0]} for n in range(4)]
    backgrounds = [RIVER, "checker", "transparent", RIVER]
    with pytest.raises(sheets.Refused) as refused:
        sheets.layout(_world(2.95), [_source()], backgrounds, tints, True)
    assert refused.value.code == "INVALID_ARGUMENT"
    assert refused.value.details["recipe_id"] == "game-2.95"


def test_an_anchor_outside_its_crop_is_refused() -> None:
    with pytest.raises(sheets.Refused):
        sheets.check_anchor(1, {"x": 10, "y": 10, "width": 20, "height": 20}, [5, 15])
    assert sheets.check_anchor(1, {"x": 10, "y": 10, "width": 20, "height": 20}, [30, 30]) == (
        30.0,
        30.0,
    )


def test_the_recipe_hash_names_everything_that_decides_a_sheet_but_its_pixels() -> None:
    arguments = _arguments([_world(2.95)])
    first = sheets.recipe_sha256(arguments["recipes"][0], arguments)
    assert first == sheets.recipe_sha256(dict(arguments["recipes"][0]), dict(arguments))
    other = {**arguments, "filter": "box"}
    assert sheets.recipe_sha256(arguments["recipes"][0], other) != first
