import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from mcp import Client

from krita_art_mcp import masks
from krita_art_mcp.bridge_client import BridgeClient, Done
from krita_art_mcp.probe import fixtures, previews, saving
from krita_art_mcp.probe.common import (
    add_layer,
    brush_args,
    brush_colour,
    by_name,
    capture,
    capture_composite,
    close,
    guard,
    harness_call,
    history_args,
    inspect_data,
    line_points,
    open_args,
    open_working,
    protect,
    select,
    stroke_args,
    turned,
)
from krita_art_mcp.probe.report import Report, code, differs, sheet_cell, tool
from krita_art_mcp.tools.saving import file_sha256

TOOL = "krita_paint_stroke"
FOLDER = "acceptance"
DETAIL_RGB = (240, 240, 60)
# A small repair whose line runs past both sides of its selection.
REPAIR = {"x": 60, "y": 30, "width": 40, "height": 30}
REPAIR_LINE = (50.0, 45.0, 110.0, 45.0)
REPAIR_BRUSH_PX = 6
# A stroke's half width, and the antialiased row on each side of it.
REPAIR_REACH_PX = REPAIR_BRUSH_PX // 2 + 1
# The allowed region, and a selection 1 px inside it: a polygon selection is antialiased and the
# allowed mask binary, so a selection on the mask's own edge paints pixels the mask forbids.
DIAMOND = [[80.0, 8.0], [140.0, 48.0], [80.0, 88.0], [20.0, 48.0]]
INSET = [[80.0, 9.2], [138.2, 48.0], [80.0, 86.8], [21.8, 48.0]]
EDGE = (70.0, 6.0, 140.0, 52.0)
BOUNDARY_BRUSH_PX = 24
BATCH = ((20.0, 20.0, 140.0, 24.0), (20.0, 44.0, 140.0, 48.0), (20.0, 68.0, 140.0, 72.0))
ROUND_TRIP_MASKS = ("transform_mask", "filter_mask")


@dataclass(frozen=True)
class Fixture:
    name: str
    size: tuple[int, int]
    stack: tuple[fixtures.Layer, ...]


@dataclass(frozen=True)
class Detail:
    fixture: Fixture
    base: str
    # Across the silhouette's edge: the rim is where alpha can move.
    allowed: dict[str, int]
    line: tuple[float, float, float, float]


@dataclass(frozen=True)
class Preview:
    fixture: Fixture
    recipes: tuple[dict[str, Any], ...]
    cells: tuple[list[int], ...]
    selection: dict[str, int]
    line: tuple[float, float, float, float]
    units: dict[str, Any] = field(default_factory=dict)


SPRITE = Fixture("sprite", (fixtures.SPRITE_WIDTH, fixtures.SPRITE_HEIGHT), fixtures.sprite_stack())
ICON = Fixture("icon", (fixtures.ICON_SIDE, fixtures.ICON_SIDE), fixtures.icon_stack())
DETAILS = (
    Detail(
        SPRITE,
        "probe hull",
        {"x": 80, "y": 40, "width": 36, "height": 16},
        (84.0, 48.0, 112.0, 48.0),
    ),
    Detail(
        ICON,
        "probe badge",
        {"x": 200, "y": 118, "width": 40, "height": 20},
        (204.0, 128.0, 236.0, 128.0),
    ),
)
PREVIEWS = (
    Preview(
        SPRITE,
        previews.GAME,
        # 128 x 0.36875 = 47.2 and 96 x 0.36875 = 35.4; 1.8 gives 28.8 and 21.6.
        ([47, 35], [29, 22]),
        {"x": 30, "y": 24, "width": 70, "height": 44},
        (40.0, 30.0, 90.0, 60.0),
        {
            "export_pixels_per_unit": previews.EXPORT_PER_UNIT,
            "master_to_export_scale": 0.5,
        },
    ),
    Preview(
        ICON,
        previews.ICONS[:2],
        ([128, 128], [256, 256]),
        {"x": 64, "y": 64, "width": 128, "height": 128},
        (72.0, 80.0, 184.0, 176.0),
    ),
)


async def run(
    report: Report,
    a: Client,
    client: BridgeClient,
    harness: Path,
    presets: dict[str, dict[str, Any] | None],
) -> None:
    folder = harness / FOLDER
    folder.mkdir(exist_ok=True)
    hard, soft, scatter = presets["hard"], presets["soft"], presets["scatter"]
    assert hard is not None
    paint = folder / "paint.ora"
    fixtures.write_ora(paint, fixtures.paint_stack(), fixtures.PAINT_WIDTH, fixtures.PAINT_HEIGHT)
    for fixture in (SPRITE, ICON):
        fixtures.write_ora(_path(folder, fixture), fixture.stack, *fixture.size)
    await _repair(report, a, client, paint, harness, hard)
    for detail in DETAILS:
        await _detail(report, a, folder, harness, hard, detail)
    for role, preset in (("soft", soft), ("scatter", scatter)):
        await _boundary(report, a, paint, harness, role, preset)
    await _batch(report, a, paint, harness, hard)
    for preview in PREVIEWS:
        await _previews(report, a, folder, harness, hard, preview)
    await _round_trip(report, a, client, folder, harness, hard)


def _path(folder: Path, fixture: Fixture) -> Path:
    return folder / f"{fixture.name}.ora"


def _whole(size: tuple[int, int]) -> dict[str, int]:
    return {"x": 0, "y": 0, "width": size[0], "height": size[1]}


async def _repair(
    report: Report,
    a: Client,
    client: BridgeClient,
    source: Path,
    harness: Path,
    hard: dict[str, Any],
) -> None:
    name = "exercise 1: a selected repair lands on the same pixels, at the requested place, at two "
    name += "zoom and pan settings"
    opened = await open_working(a, source, harness, FOLDER)
    document_id = opened.get("document_id")
    if opened.get("status") != "completed" or not document_id:
        report.check(name, False, str(opened.get("error")))
        return
    size = (fixtures.PAINT_WIDTH, fixtures.PAINT_HEIGHT)
    try:
        layer_id = await add_layer(a, document_id, opened["data"]["root_layer_id"], "repair")
        selected = await select(a, document_id, {"type": "rect", "rect": REPAIR})
        read = harness_call(client, "harness.view", document_id=document_id, view=None)
        if layer_id is None or selected.get("status") != "completed" or not isinstance(read, Done):
            report.check(name, False, f"{code(selected)}, {read}")
            return
        first_view = read.result["view"]
        brush = brush_args(hard, size_px=REPAIR_BRUSH_PX)
        points = line_points(*REPAIR_LINE, 16)
        painted, receipts, views = [], [], []
        try:
            for view in (None, turned(first_view)):
                if view is not None:
                    moved = harness_call(client, "harness.view", document_id=document_id, view=view)
                    views.append(moved.result["view"] if isinstance(moved, Done) else None)
                done = await tool(a, TOOL, stroke_args(document_id, layer_id, brush, points))
                receipts.append(done)
                painted.append(await capture(a, document_id, _whole(size), "layer", layer_id))
                await tool(a, "krita_history_step", history_args(document_id, "undo"))
        finally:
            harness_call(client, "harness.view", document_id=document_id, view=first_view)
        report.check(name, *_repair_verdict(painted, receipts, first_view, views))
        await _pressure(report, a, document_id, layer_id, painted[0], size, hard)
    finally:
        await close(a, document_id)


def _repair_verdict(
    painted: list[np.ndarray | None],
    receipts: list[dict[str, Any]],
    first_view: dict[str, Any],
    views: list[dict[str, Any] | None],
) -> tuple[bool, str]:
    if views[0] is None or views[0] == first_view:
        return False, f"the view did not move: {first_view} then {views[0]}"
    first, second = painted
    if first is None or second is None:
        return False, f"nothing captured: {[code(done) for done in receipts]}"
    if first.tobytes() != second.tobytes():
        return False, f"the two views differ: {differs(second, first)}"
    rows, columns = np.nonzero(first[..., 3])
    if not len(rows):
        return False, "the stroke painted nothing"
    box = [int(columns.min()), int(columns.max()), int(rows.min()), int(rows.max())]
    right, bottom = REPAIR["x"] + REPAIR["width"] - 1, REPAIR["y"] + REPAIR["height"] - 1
    centre = int(REPAIR_LINE[1])
    placed = (
        box[:2] == [REPAIR["x"], right]
        and box[2] >= max(REPAIR["y"], centre - REPAIR_REACH_PX)
        and box[3] <= min(bottom, centre + REPAIR_REACH_PX)
    )
    effective = ((receipts[0].get("data") or {}).get("effective_brush") or {}).get("size_px")
    digest = hashlib.sha256(first.tobytes()).hexdigest()[:12]
    return placed and effective == REPAIR_BRUSH_PX, f"x and y bounds {box}, {digest}"


async def _pressure(
    report: Report,
    a: Client,
    document_id: str,
    layer_id: str,
    flat: np.ndarray | None,
    size: tuple[int, int],
    hard: dict[str, Any],
) -> None:
    brush = brush_args(hard, size_px=REPAIR_BRUSH_PX)
    points = [{**point, "pressure": 0.4} for point in line_points(*REPAIR_LINE, 16)]
    refused = await tool(a, TOOL, stroke_args(document_id, layer_id, brush, points))
    fields = ((refused.get("error") or {}).get("details") or {}).get("fields")
    arguments = stroke_args(document_id, layer_id, brush, points, input_fallback="flat")
    done = await tool(a, TOOL, arguments)
    pixels = await capture(a, document_id, _whole(size), "layer", layer_id)
    applied = (done.get("data") or {}).get("input_applied")
    report.check(
        "exercise 1: per-point pressure is refused by name, and input_fallback flat reports "
        "itself and paints as a flat stroke does",
        code(refused) == "UNSUPPORTED_CAPABILITY"
        and fields == ["pressure"]
        and applied == "flat"
        and not differs(pixels, flat),
        f"{code(refused)} {fields}, applied {applied}, {differs(pixels, flat) or 'same pixels'}",
    )


def _outside(rect: dict[str, int], shape: tuple[int, ...]) -> np.ndarray:
    mask = np.ones(shape[:2], dtype=bool)
    mask[rect["y"] : rect["y"] + rect["height"], rect["x"] : rect["x"] + rect["width"]] = False
    return mask


async def _detail(
    report: Report,
    a: Client,
    folder: Path,
    harness: Path,
    hard: dict[str, Any],
    case: Detail,
) -> None:
    name = f"exercise 2, the {case.fixture.name}: a detail on a new layer keeps every accepted "
    name += "layer, the exterior and every alpha byte"
    source = _path(folder, case.fixture)
    accepted = file_sha256(source)
    opened = await open_working(a, source, harness, FOLDER)
    document_id = opened.get("document_id")
    if opened.get("status") != "completed" or not document_id:
        report.check(name, False, str(opened.get("error")))
        return
    whole = _whole(case.fixture.size)
    try:
        data = opened["data"]
        layers = data["layers"]
        base = by_name(layers)[case.base]["id"]
        protected = await protect(
            a, document_id, layers, {"rect": case.allowed}, preserve_alpha=True
        )
        detail = await add_layer(a, document_id, data["root_layer_id"], "detail")
        if detail is None or protected.get("status") != "completed":
            report.check(name, False, str(code(protected)))
            return
        clipped = {
            "guard": guard(document_id),
            "layer_id": detail,
            "properties": {"inherit_alpha": True},
        }
        await tool(a, "krita_layer_update", clipped)
        await select(a, document_id, {"type": "rect", "rect": case.allowed})
        before = await capture(a, document_id, whole)
        kept = {
            layer["name"]: await capture(a, document_id, whole, "layer", layer["id"])
            for layer in layers
        }
        brush = brush_args(hard, size_px=8, color=brush_colour(DETAIL_RGB))
        points = line_points(*case.line)
        done = await tool(a, TOOL, stroke_args(document_id, detail, brush, points))
        after = await capture(a, document_id, whole)
        problems = _detail_problems(done, before, after, case.allowed)
        for layer in layers:
            now = await capture(a, document_id, whole, "layer", layer["id"])
            problems += _pixel_problems(kept[layer["name"]], now, layer["name"])
        problems += ["the source's file changed"] * (file_sha256(source) != accepted)
        report.check(name, not problems, "; ".join(problems))
        await _refused(report, a, document_id, base, case, brush, after)
    finally:
        await close(a, document_id)


def _detail_problems(
    done: dict[str, Any],
    before: np.ndarray | None,
    after: np.ndarray | None,
    allowed: dict[str, int],
) -> list[str]:
    if done.get("status") != "completed" or before is None or after is None:
        return [f"the stroke answered {code(done)}"]
    data = done.get("data") or {}
    checked = data.get("verification") or {}
    problems = []
    if (
        checked.get("changed_outside_px") != 0
        or checked.get("alpha_changed_px") != 0
        or data.get("protected_pixels_changed") != 0
    ):
        problems.append(f"the receipt says {checked}")
    outside = _outside(allowed, before.shape)
    if not np.array_equal(before[outside], after[outside]):
        problems.append("the exterior moved")
    if not np.array_equal(before[..., 3], after[..., 3]):
        problems.append("an alpha byte moved")
    if np.array_equal(before, after):
        problems.append("the detail painted nothing")
    return problems


async def _refused(
    report: Report,
    a: Client,
    document_id: str,
    base: str,
    case: Detail,
    brush: dict[str, Any],
    painted: np.ndarray | None,
) -> None:
    stroke = await tool(a, TOOL, stroke_args(document_id, base, brush, line_points(*case.line)))
    change = {"guard": guard(document_id), "layer_id": base, "properties": {"opacity": 0.5}}
    update = await tool(a, "krita_layer_update", change)
    after = await capture(a, document_id, _whole(case.fixture.size))
    report.check(
        f"exercise 2, the {case.fixture.name}: a stroke and a property change on the protected "
        "base are LOCKED_TARGET, and the composite stays",
        code(stroke) == code(update) == "LOCKED_TARGET" and not differs(after, painted),
        f"{code(stroke)}, {code(update)}",
    )


def _allowed_canvas(points: list[list[float]], size: tuple[int, int]) -> np.ndarray:
    # The binary mask the server sends the plugin, over the whole canvas.
    mask = masks.polygon(points, size[0] * size[1], binary=True)
    canvas = np.zeros((size[1], size[0]), dtype=bool)
    x, y = mask.origin
    height, width = mask.pixels.shape
    canvas[y : y + height, x : x + width] = mask.pixels == 255
    return canvas


async def _boundary(
    report: Report,
    a: Client,
    source: Path,
    harness: Path,
    role: str,
    preset: dict[str, Any] | None,
) -> None:
    name = f"exercise 3, {role} brush beside a boundary: no change outside the allowed polygon, "
    name += "and a stroke that leaks is rolled back and confirmed"
    if preset is None:
        report.check(name, False, "no such stock preset is listed")
        return
    opened = await open_working(a, source, harness, FOLDER)
    document_id = opened.get("document_id")
    if opened.get("status") != "completed" or not document_id:
        report.check(name, False, str(opened.get("error")))
        return
    size = (fixtures.PAINT_WIDTH, fixtures.PAINT_HEIGHT)
    try:
        data = opened["data"]
        layer_id = await add_layer(a, document_id, data["root_layer_id"], "boundary")
        protected = await protect(a, document_id, data["layers"], {"polygon": DIAMOND})
        if layer_id is None or protected.get("status") != "completed":
            report.check(name, False, str(code(protected)))
            return
        brush = brush_args(preset, size_px=BOUNDARY_BRUSH_PX)
        points = line_points(*EDGE)
        await select(a, document_id, {"type": "polygon", "points": INSET})
        before = await capture(a, document_id, _whole(size))
        kept = await tool(a, TOOL, stroke_args(document_id, layer_id, brush, points))
        after = await capture(a, document_id, _whole(size))
        await select(a, document_id, {"type": "none"})
        leaked = await tool(a, TOOL, stroke_args(document_id, layer_id, brush, points))
        last = await capture(a, document_id, _whole(size))
        details = (leaked.get("error") or {}).get("details") or {}
        outside = (kept.get("data") or {}).get("verification", {}).get("changed_outside_px")
        moved = None
        if before is not None and after is not None:
            away = ~_allowed_canvas(DIAMOND, size)
            moved = int(np.any(before[away] != after[away], axis=-1).sum())
        report.check(
            name,
            kept.get("status") == "completed"
            and outside == 0
            and moved == 0
            and bool(differs(after, before))
            and code(leaked) == "PROTECTED_REGION_CHANGED"
            and details.get("rollback_verified") is True
            and not differs(last, after),
            f"kept {code(kept) or outside}, {moved} px moved outside, leaked {code(leaked)}, "
            f"confirmed {details.get('rollback_verified')}, composite "
            f"{differs(last, after) or 'as before'}",
        )
    finally:
        await close(a, document_id)


async def _batch(
    report: Report, a: Client, source: Path, harness: Path, hard: dict[str, Any]
) -> None:
    name = "exercise 4: undo, redo and undo of a batch of strokes each land on the exact composite"
    opened = await open_working(a, source, harness, FOLDER)
    document_id = opened.get("document_id")
    if opened.get("status") != "completed" or not document_id:
        report.check(name, False, str(opened.get("error")))
        return
    width, height = fixtures.PAINT_WIDTH, fixtures.PAINT_HEIGHT
    steps = len(BATCH)

    async def composite() -> np.ndarray | None:
        return await capture_composite(a, document_id, width, height)

    try:
        layer_id = await add_layer(a, document_id, opened["data"]["root_layer_id"], "batch")
        if layer_id is None:
            report.check(name, False, "no layer")
            return
        start = await composite()
        brush = brush_args(hard, size_px=6)
        asked = [stroke_args(document_id, layer_id, brush, line_points(*line)) for line in BATCH]
        receipts = [await tool(a, TOOL, arguments) for arguments in asked]
        painted = await composite()
        undone = await tool(a, "krita_history_step", history_args(document_id, "undo", steps))
        cleared = await composite()
        redone = await tool(a, "krita_history_step", history_args(document_id, "redo", steps))
        repainted = await composite()
        await tool(a, "krita_history_step", history_args(document_id, "undo", steps))
        empty = await composite()
        applied = [(step.get("data") or {}).get("steps_applied") for step in (undone, redone)]
        report.check(
            name,
            all(done.get("status") == "completed" for done in receipts)
            and bool(differs(painted, start))
            and applied == [steps, steps]
            and not differs(cleared, start)
            and not differs(repainted, painted)
            and not differs(empty, start),
            f"applied {applied}, undone {differs(cleared, start) or 'exact'}, redone "
            f"{differs(repainted, painted) or 'exact'}",
        )
        retried = [await tool(a, TOOL, arguments) for arguments in asked]
        still = await composite()
        report.check(
            "exercise 4: retrying completed strokes returns their receipts and paints nothing, "
            "even after they were undone",
            retried == receipts and not differs(still, start),
            differs(still, start) or f"{len(retried)} receipts",
        )
    finally:
        await close(a, document_id)


async def _previews(
    report: Report, a: Client, folder: Path, harness: Path, hard: dict[str, Any], case: Preview
) -> None:
    name = f"exercise 5, the {case.fixture.name}: explicit recipes render at their exact sizes, "
    name += "fresh after a stroke, with the overlay in the marked sheet only"
    opened = await open_working(a, _path(folder, case.fixture), harness, FOLDER)
    document_id = opened.get("document_id")
    if opened.get("status") != "completed" or not document_id:
        report.check(name, False, str(opened.get("error")))
        return
    try:
        layer_id = await add_layer(a, document_id, opened["data"]["root_layer_id"], "preview")
        ask = previews.arguments([previews.source(document_id)], case.recipes, **case.units)
        first = await tool(a, previews.TOOL, ask)
        await select(a, document_id, {"type": "rect", "rect": case.selection})
        brush = brush_args(hard, size_px=12, color=brush_colour(DETAIL_RGB))
        points = line_points(*case.line)
        done = await tool(a, TOOL, stroke_args(document_id, layer_id or "", brush, points))
        plain = await tool(a, previews.TOOL, ask)
        marked = await tool(a, previews.TOOL, {**ask, "overlays": ["selection"]})
        sheets = [
            (render.get("data") or {}).get("sheets") or [] for render in (first, plain, marked)
        ]
        problems = [] if done.get("status") == "completed" else [f"stroke {code(done)}"]
        if [len(found) for found in sheets] != [len(case.recipes)] * 3:
            problems.append(f"{[len(found) for found in sheets]} sheets")
        else:
            problems += _preview_problems(sheets, case.cells)
        report.check(name, not problems, "; ".join(problems))
    finally:
        await close(a, document_id)


def _preview_problems(
    sheets: list[list[dict[str, Any]]], cells: tuple[list[int], ...]
) -> list[str]:
    problems = []
    for was, now, drawn, want in zip(*sheets, cells, strict=True):
        recipe = was["recipe_id"]
        if [was["cell_px"], now["cell_px"], drawn["cell_px"]] != [want] * 3:
            problems.append(f"{recipe}: cell {now['cell_px']}, not {want}")
        if not differs(sheet_cell(now, 0), sheet_cell(was, 0)):
            problems.append(f"{recipe}: the render after the stroke is stale")
        if drawn.get("clean_image") is None:
            problems.append(f"{recipe}: no clean sheet")
            continue
        clean = sheet_cell(drawn, 0, clean=True)
        if differs(clean, sheet_cell(now, 0)):
            problems.append(f"{recipe}: the clean sheet is not the plain one")
        if not differs(sheet_cell(drawn, 0), clean):
            problems.append(f"{recipe}: no overlay was drawn")
    return problems


async def _round_trip(
    report: Report,
    a: Client,
    client: BridgeClient,
    folder: Path,
    harness: Path,
    hard: dict[str, Any],
) -> None:
    name = "exercise 6: a saved .kra, closed and reopened, keeps layers, masks, visibility, "
    name += "profile, pixels and the selection"
    source = folder / "round-trip.ora"
    fixtures.write_ora(source, fixtures.probe_stack())
    opened = await open_working(a, source, harness, FOLDER)
    document_id = opened.get("document_id")
    if opened.get("status") != "completed" or not document_id:
        report.check(name, False, str(opened.get("error")))
        return
    data = opened["data"]
    whole = _whole((fixtures.WIDTH, fixtures.HEIGHT))
    target = folder / "round-trip.kra"
    try:
        layer_id = await add_layer(a, document_id, data["root_layer_id"], "kept")
        brush = brush_args(hard, size_px=4)
        points = line_points(6, 6, 30, 20)
        done = await tool(a, TOOL, stroke_args(document_id, layer_id or "", brush, points))
        layers = by_name(data["layers"])
        for kind, host in zip(ROUND_TRIP_MASKS, ("probe base", "probe shape"), strict=True):
            harness_call(
                client,
                "harness.add_node",
                document_id=document_id,
                kind=kind,
                layer_id=layers[host]["id"],
            )
        await select(
            a, document_id, {"type": "rect", "rect": {"x": 4, "y": 4, "width": 40, "height": 30}}
        )
        live = await inspect_data(a, document_id)
        composite = await capture(a, document_id, whole)
        selection = await capture(a, document_id, whole, "selection")
        paints = [layer for layer in live.get("layers", []) if layer["type"] == "paint"]
        pixels = {
            layer["id"]: await capture(a, document_id, whole, "layer", layer["id"])
            for layer in paints
        }
        saved = await saving.save(a, document_id, target)
        closed = await close(a, document_id, "refuse")
    finally:
        await close(a, document_id)
    if done.get("status") != "completed" or (closed.get("data") or {}).get("closed") is not True:
        report.check(name, False, f"{code(done)}, {code(saved)}, {code(closed)}")
        return
    reopened = await tool(a, "krita_document_open", open_args(target, "read_only"))
    again = reopened.get("document_id")
    if reopened.get("status") != "completed" or not again:
        report.check(name, False, str(reopened.get("error")))
        return
    try:
        back = await inspect_data(a, again)
        problems = saving.kra_differences(live, back)
        for key in ("canvas_px", "profile_id", "color_model", "depth", "selection"):
            if live.get(key) != back.get(key):
                problems.append(f"{key}: {live.get(key)} became {back.get(key)}")
        found = {layer["type"] for layer in back.get("layers", [])}
        problems += [f"no {kind}" for kind in ROUND_TRIP_MASKS if kind not in found]
        if by_name(back.get("layers", [])).get("probe hidden", {}).get("visible") is not False:
            problems.append("the hidden layer came back visible")
        problems += _pixel_problems(
            composite, await capture(a, again, whole), "the composite"
        ) + _pixel_problems(selection, await capture(a, again, whole, "selection"), "the selection")
        for layer in paints:
            now = await capture(a, again, whole, "layer", layer["id"])
            problems += _pixel_problems(pixels[layer["id"]], now, layer["name"])
        report.check(name, not problems, "; ".join(problems[:5]) or f"{len(back['layers'])} layers")
    finally:
        await close(a, again)


def _pixel_problems(was: np.ndarray | None, now: np.ndarray | None, what: str) -> list[str]:
    if was is None or now is None:
        return [f"{what}: nothing to compare"]
    return [f"{what}: {differs(now, was)}"] if not np.array_equal(was, now) else []
