import uuid
from pathlib import Path
from typing import Any

import numpy as np
from mcp import Client

from krita_art_mcp.probe import fixtures
from krita_art_mcp.probe.common import (
    add_layer,
    brush_args,
    brush_colour,
    by_name,
    capture,
    close,
    finished,
    history_args,
    inspect_data,
    line_points,
    open_args,
    open_working,
    protect,
    select,
    stroke_args,
)
from krita_art_mcp.probe.report import Report, code, differs, tool
from krita_art_mcp.probe.saving import SAVE_LIMIT_S, save_args

TOOL = "krita_paint_stroke"
WIDTH, HEIGHT = 120, 90
CANVAS = {"x": 0, "y": 0, "width": WIDTH, "height": HEIGHT}
BRUSH_PX = 12
# Inside the half-brush tolerance, so each path is accepted and its dabs overhang.
PAST = 4
# Beyond a whole dab at a corner, so the stroke leaves the canvas as it found it.
OUTSIDE_PX = 40
MASTER_SIDE = 1254
MASTER_BRUSH_PX = 20
MASTER_POINTS = ((372, -8), (376, 4), (398, 28), (401, 55), (418, 78))
BASE_RGB = (60, 120, 180)
PAINT_RGB = (230, 60, 30)

Ends = tuple[tuple[float, float], tuple[float, float]]


def _strokes() -> dict[str, Ends]:
    right, bottom = WIDTH + PAST, HEIGHT + PAST
    return {
        "top": ((50, -PAST), (70, -PAST)),
        "bottom": ((50, bottom), (70, bottom)),
        "left": ((-PAST, 35), (-PAST, 55)),
        "right": ((right, 35), (right, 55)),
        "top left": ((-PAST, -PAST), (8, 8)),
        "top right": ((right, -PAST), (WIDTH - 8, 8)),
        "bottom left": ((-PAST, bottom), (8, HEIGHT - 8)),
        "bottom right": ((right, bottom), (WIDTH - 8, HEIGHT - 8)),
    }


def _bounds(pixels: np.ndarray) -> dict[str, int] | None:
    # Where a layer captured from empty holds anything: each changed byte, as the receipt counts.
    found = np.any(pixels != 0, axis=2)
    rows, columns = np.flatnonzero(found.any(axis=1)), np.flatnonzero(found.any(axis=0))
    if rows.size == 0:
        return None
    left, top = int(columns[0]), int(rows[0])
    return {
        "x": left,
        "y": top,
        "width": int(columns[-1]) + 1 - left,
        "height": int(rows[-1]) + 1 - top,
    }


def _inside(rect: dict[str, int], outer: dict[str, int]) -> bool:
    return (
        outer["x"] <= rect["x"]
        and outer["y"] <= rect["y"]
        and rect["x"] + rect["width"] <= outer["x"] + outer["width"]
        and rect["y"] + rect["height"] <= outer["y"] + outer["height"]
    )


def _selection(ends: Ends) -> dict[str, int]:
    # The canvas around the stroke, narrower than its dabs, so the selection is what stops them.
    (x0, y0), (x1, y1) = ends
    least = 2 * PAST
    left = min(max(0, int(min(x0, x1)) - PAST), WIDTH - least)
    top = min(max(0, int(min(y0, y1)) - PAST), HEIGHT - least)
    right = max(min(WIDTH, int(max(x0, x1)) + least), least)
    bottom = max(min(HEIGHT, int(max(y0, y1)) + least), least)
    return {"x": left, "y": top, "width": right - left, "height": bottom - top}


def _overhangs(name: str, bounds: dict[str, int] | None) -> bool:
    if bounds is None:
        return False
    sides = {
        "top": bounds["y"] < 0,
        "bottom": bounds["y"] + bounds["height"] > HEIGHT,
        "left": bounds["x"] < 0,
        "right": bounds["x"] + bounds["width"] > WIDTH,
    }
    return all(past for side, past in sides.items() if side in name)


async def run(report: Report, a: Client, folder: Path, harness: Path, hard: dict[str, Any]) -> None:
    await _failing_request(report, a, folder, harness, hard)
    source = folder / "edges.ora"
    layers = (fixtures.Layer("probe edge base", fixtures.rect(WIDTH, HEIGHT, BASE_RGB)),)
    fixtures.write_ora(source, layers, WIDTH, HEIGHT)
    opened = await open_working(a, source, harness, "painting")
    document_id = opened.get("document_id")
    if opened.get("status") != "completed" or not document_id:
        report.check("the edges' working copy opens", False, str(opened.get("error")))
        return
    try:
        data = opened["data"]
        base = by_name(data["layers"])["probe edge base"]["id"]
        protected = await protect(a, document_id, data["layers"], None, preserve_alpha=True)
        layer = await add_layer(a, document_id, data["root_layer_id"], "edge")
        if layer is None or protected.get("status") != "completed":
            report.check("the edges' layer and protection are set", False, str(code(protected)))
            return
        brush = brush_args(hard, size_px=BRUSH_PX, color=brush_colour(PAINT_RGB))
        for verify in ("region", "full"):
            for selected in (False, True):
                await _each_edge(report, a, document_id, base, layer, brush, verify, selected)
        wide = brush_args(hard, size_px=OUTSIDE_PX, color=brush_colour(PAINT_RGB))
        await _outside(report, a, document_id, layer, wide)
        arguments = await _old_overhang(report, a, document_id, layer, brush)
        await _replay(report, a, document_id, arguments)
        await _reopened(report, a, document_id, folder)
    finally:
        await close(a, document_id)


async def _failing_request(
    report: Report, a: Client, folder: Path, harness: Path, hard: dict[str, Any]
) -> None:
    # The geometry of a stroke that once applied and lost its receipt, on an opaque master.
    source = folder / "edges-master.ora"
    side = MASTER_SIDE
    layers = (fixtures.Layer("probe master", fixtures.rect(side, side, BASE_RGB)),)
    fixtures.write_ora(source, layers, side, side)
    opened = await open_working(a, source, harness, "painting")
    document_id = opened.get("document_id")
    if opened.get("status") != "completed" or not document_id:
        report.check("the master's working copy opens", False, str(opened.get("error")))
        return
    try:
        data = opened["data"]
        layer = await add_layer(a, document_id, data["root_layer_id"], "master")
        if layer is None:
            report.check("the master's layer is added", False)
            return
        whole = {"x": 0, "y": 0, "width": side, "height": side}
        brush = brush_args(hard, size_px=MASTER_BRUSH_PX, color=brush_colour(PAINT_RGB))
        points = [{"x": x, "y": y} for x, y in MASTER_POINTS]
        arguments = stroke_args(
            document_id, layer, brush, points, verify="full", smooth="catmull_rom"
        )
        before = await capture(a, document_id, whole)
        done = await tool(a, TOOL, arguments)
        after = await capture(a, document_id, whole)
        painted = await capture(a, document_id, whole, "layer", layer)
        receipt = done.get("data") or {}
        truth = None if painted is None else _bounds(painted)
        overhang = receipt.get("layer_bounds_px") or {}
        same_alpha = (
            before is not None
            and after is not None
            and np.array_equal(before[..., 3], after[..., 3])
        )
        report.check(
            "the stroke that once lost its receipt completes, with the true change in "
            "changed_bounds_px and the overhang in layer_bounds_px, alpha unchanged",
            done.get("status") == "completed"
            and receipt.get("changed_bounds_px") == truth
            and overhang.get("y", 0) < 0
            and same_alpha,
            f"{code(done) or 'completed'}, changed {receipt.get('changed_bounds_px')}, true "
            f"{truth}, layer {overhang}",
        )
        operation = {"operation_id": done.get("operation_id")}
        got = (await tool(a, "krita_operation_get", operation)).get("data") or {}
        report.check(
            "krita_operation_get says that stroke applied, with a valid receipt",
            (got.get("outcome"), got.get("receipt_valid")) == ("applied", True)
            and got.get("receipt") == done,
            f"{got.get('outcome')}, valid {got.get('receipt_valid')}",
        )
    finally:
        await close(a, document_id)


async def _each_edge(
    report: Report,
    a: Client,
    document_id: str,
    base: str,
    layer: str,
    brush: dict[str, Any],
    verify: str,
    selected: bool,
) -> None:
    problems = []
    for name, ends in _strokes().items():
        problem = await _past_edge(a, document_id, base, layer, brush, name, ends, verify, selected)
        if problem:
            problems.append(f"{name}: {problem}")
    how = "under a selection" if selected else "with no selection"
    report.check(
        f"{verify} scope, {how}: a stroke past each edge and corner reports the canvas's true "
        "change and the layer's overhang, and keeps alpha and the protected base, and its undo "
        "restores the composite",
        not problems,
        "; ".join(problems),
    )


async def _past_edge(
    a: Client,
    document_id: str,
    base: str,
    layer: str,
    brush: dict[str, Any],
    name: str,
    ends: Ends,
    verify: str,
    selected: bool,
) -> str:
    area = _selection(ends)
    if selected:
        chosen = await select(a, document_id, {"type": "rect", "rect": area})
        if chosen.get("status") != "completed":
            return f"the selection {area}: {code(chosen)}"
    (x0, y0), (x1, y1) = ends
    points = line_points(x0, y0, x1, y1)
    before = await capture(a, document_id, CANVAS)
    under = await capture(a, document_id, CANVAS, "layer", base)
    done = await tool(a, TOOL, stroke_args(document_id, layer, brush, points, verify=verify))
    after = await capture(a, document_id, CANVAS)
    still = await capture(a, document_id, CANVAS, "layer", base)
    painted = await capture(a, document_id, CANVAS, "layer", layer)
    undone = await tool(a, "krita_history_step", history_args(document_id, "undo"))
    back = await capture(a, document_id, CANVAS)
    if selected:
        await select(a, document_id, {"type": "none"})
    if done.get("status") != "completed":
        return str(code(done))
    data = done["data"]
    changed = data["changed_bounds_px"]
    truth = None if painted is None else _bounds(painted)
    if before is None or after is None or changed != truth or changed is None:
        return f"changed {changed}, true {truth}"
    if not _inside(changed, CANVAS):
        return f"changed {changed} leaves the canvas"
    # Alpha, not every byte: Krita can write colour under alpha 0 beyond a selection.
    visible = None if painted is None else _bounds(painted[..., 3:])
    if selected and (visible is None or not _inside(visible, area)):
        return f"the paint {visible} leaves {area}"
    if not selected and not _overhangs(name, data["layer_bounds_px"]):
        return f"the layer's bounds {data['layer_bounds_px']} show no overhang"
    if data["protected_pixels_changed"] != 0 or differs(still, under):
        return f"the base changed: {differs(still, under)}"
    if not np.array_equal(before[..., 3], after[..., 3]):
        return "alpha changed"
    if undone.get("status") != "completed" or differs(back, before):
        return f"undo: {code(undone)} {differs(back, before)}"
    return ""


async def _outside(
    report: Report, a: Client, document_id: str, layer: str, brush: dict[str, Any]
) -> None:
    # Clear of the corner by more than a dab, in both scopes.
    half = OUTSIDE_PX / 2
    points = [{"x": -half, "y": -half}, {"x": -half, "y": -half + 2}]
    problems = []
    for verify in ("region", "full"):
        before = await capture(a, document_id, CANVAS)
        done = await tool(a, TOOL, stroke_args(document_id, layer, brush, points, verify=verify))
        after = await capture(a, document_id, CANVAS)
        data = done.get("data") or {}
        if done.get("status") != "completed":
            problems.append(f"{verify}: {code(done)}")
        elif data["changed_bounds_px"] is not None or data["history_sealed"] is not True:
            problems.append(f"{verify}: {data['changed_bounds_px']}, {data['history_sealed']}")
        elif differs(after, before):
            problems.append(f"{verify}: {differs(after, before)}")
    report.check(
        "a stroke wholly past the canvas reports no change and seals history, in both scopes",
        not problems,
        "; ".join(problems),
    )


async def _old_overhang(
    report: Report, a: Client, document_id: str, layer: str, brush: dict[str, Any]
) -> dict[str, Any]:
    # The layer holds the paint the last check left off the canvas.
    far = line_points(40, 40, 70, 50)
    arguments = stroke_args(document_id, layer, brush, far, str(uuid.uuid4()), verify="full")
    done = await tool(a, TOOL, arguments)
    painted = await capture(a, document_id, CANVAS, "layer", layer)
    data = done.get("data") or {}
    truth = None if painted is None else _bounds(painted)
    bounds = data.get("layer_bounds_px") or {}
    report.check(
        "a full-scope stroke far from the edge, on a layer with old overhang, completes and "
        "reports what it changed",
        done.get("status") == "completed"
        and data.get("changed_bounds_px") == truth
        and bounds.get("x", 0) < 0,
        f"{code(done) or 'completed'}, changed {data.get('changed_bounds_px')}, true {truth}, "
        f"layer {bounds}",
    )
    return arguments


async def _replay(report: Report, a: Client, document_id: str, arguments: dict[str, Any]) -> None:
    first_history = (await inspect_data(a, document_id)).get("history")
    before = await capture(a, document_id, CANVAS)
    done = await tool(a, TOOL, arguments)
    again = await tool(a, TOOL, arguments)
    after = await capture(a, document_id, CANVAS)
    history = (await inspect_data(a, document_id)).get("history")
    report.check(
        "the same request sent again returns its receipt and paints nothing",
        done == again and not differs(after, before) and history == first_history,
        differs(after, before) or f"history {first_history} became {history}",
    )


async def _reopened(report: Report, a: Client, document_id: str, folder: Path) -> None:
    target = folder / "overhang.kra"
    arguments = save_args(document_id, target)
    saved = await finished(a, await tool(a, "krita_document_save", arguments), SAVE_LIMIT_S)
    opened = await tool(a, "krita_document_open", open_args(target, "read_only"))
    copy_id = opened.get("document_id")
    if saved.get("status") != "completed" or not copy_id:
        details = (saved.get("error") or {}).get("details")
        report.check("a KRA with overhang saves and reopens", False, f"{code(saved)}: {details}")
        return
    try:
        live = {node["id"]: node for node in (await inspect_data(a, document_id))["layers"]}
        back = {node["id"]: node for node in (await inspect_data(a, copy_id))["layers"]}
        moved = [
            node_id
            for node_id, node in live.items()
            if back.get(node_id, {}).get("bounds_px") != node["bounds_px"]
        ]
        pixels = differs(await capture(a, copy_id, CANVAS), await capture(a, document_id, CANVAS))
        report.check(
            "a KRA with overhang saves, reopens equal, and keeps every layer's bounds",
            not moved and not pixels,
            f"moved {moved}, {pixels or 'composite equal'}",
        )
    finally:
        await close(a, copy_id)
