import hashlib
import math
import os
import statistics
import time
import uuid
from pathlib import Path
from typing import Any

import numpy as np
from mcp import Client

from krita_art_mcp.bridge_client import BridgeClient, Done
from krita_art_mcp.journal import Journal
from krita_art_mcp.probe import (
    acceptance,
    edges,
    filling,
    fixtures,
    modified,
    previews,
    saving,
    transparency,
)
from krita_art_mcp.probe.common import (
    add_layer,
    brush_args,
    brush_colour,
    by_name,
    capture,
    capture_composite,
    close,
    finished,
    guard,
    harness_call,
    history_args,
    krita_rss_kb,
    line_points,
    megabytes,
    open_args,
    open_working,
    protect,
    select,
    stroke_args,
    turned,
)
from krita_art_mcp.probe.pixels import brushes
from krita_art_mcp.probe.report import Report, code, differs, sheet_cell, tool

TOOL = "krita_paint_stroke"
LABEL = "Scripted Brush Stroke"
# Stock presets by name, the first Krita lists winning: a hard round tip, a soft one, and one
# that scatters its dabs.
HARD = ("b) Basic-2 Opacity", "d) Ink-3 Gpen")
SOFT = ("b) Airbrush Soft",)
SCATTER = ("y) Texture Spray", "v) Texture Impressionism")
# A stock image tip far from square (7 x 32 px), against R's margin, which takes an image tip to
# fit a size x size square; its canvas leaves room for a tip sized by its narrow side.
TALL = ("y) Texture Wood Fiber",)
TIP_CANVAS_PX = 480
TIP_BRUSH_PX = 60
# N-06's colours, #A7C284 among them, in red, green and blue bytes.
COLOURS = (
    (167, 194, 132),
    (255, 0, 0),
    (0, 255, 0),
    (0, 0, 255),
    (255, 255, 255),
    (0, 0, 0),
    (127, 127, 127),
    (200, 60, 90),
    (30, 110, 200),
    (240, 160, 30),
)
# N-01's and N-09's budgets, and the strokes they time: 200-point S-curves in a 400 x 400 area.
BENCHMARKS = (
    {"name": "N-01", "size": 2000, "layers": 20, "budget_s": 1.5},
    {"name": "N-09", "size": 8192, "layers": 30, "budget_s": 3.0},
)
STROKES = 20
LONG_STROKES = 3
POINTS = 200
BRUSH_PX = 40
AREA_PX = 400
# What counts as the journal's cost biting, over a heavy week of strokes.
WEEK_STROKES = 7 * 2000
LOOKUP_BUDGET_S = 1.0
JOURNAL_BUDGET_BYTES = 100 * 1024 * 1024
LOOKUPS = 5
# How long an open of the 8k master may run past the server's wait before the probe gives up.
OPEN_LIMIT_S = 600.0


def _s_curve(x: float, y: float) -> list[dict[str, Any]]:
    # About 600 px long inside a 400 x 400 square whose corner is (x, y).
    return [
        {
            "x": x + AREA_PX * index / (POINTS - 1),
            "y": y + AREA_PX / 2 + 150 * math.sin(2 * math.pi * index / (POINTS - 1)),
        }
        for index in range(POINTS)
    ]


def _pick(found: list[dict[str, Any]], names: tuple[str, ...]) -> dict[str, Any] | None:
    by = {entry["name"]: entry for entry in found if entry["sha256"]}
    return next((by[name] for name in names if name in by), None)


async def run(report: Report, a: Client, b: Client, client: BridgeClient, harness: Path) -> None:
    harness = Path(os.path.realpath(harness))
    folder = harness / "painting"
    folder.mkdir(exist_ok=True)
    found = await brushes(a) or []
    presets = {"hard": _pick(found, HARD), "soft": _pick(found, SOFT)}
    presets["scatter"] = _pick(found, SCATTER)
    presets["tall"] = _pick(found, TALL)
    presets["fill"] = _pick(found, filling.FILL)
    hard = presets["hard"]
    if not report.check("a hard round stock preset is listed", hard is not None):
        return
    assert hard is not None
    paint, rim = folder / "paint.ora", folder / "rim.ora"
    fixtures.write_ora(paint, fixtures.paint_stack(), fixtures.PAINT_WIDTH, fixtures.PAINT_HEIGHT)
    fixtures.write_ora(rim, fixtures.rim_stack())
    await _capabilities(report, a)
    opened = await open_working(a, paint, harness, "painting")
    document_id = opened.get("document_id")
    if opened.get("status") != "completed" or not document_id:
        report.check("the paint checks' working copy opens", False, str(opened.get("error")))
        return
    used = [entry["id"] for entry in presets.values() if entry is not None]
    saved = harness_call(
        client, "harness.brush_state", document_id=document_id, action="read", preset_ids=used
    )
    try:
        data = opened["data"]
        root = data["root_layer_id"]
        base = by_name(data["layers"])["probe base"]["id"]
        with report.timed("paint"):
            await _colours(report, a, document_id, root, hard)
            await _one_step(report, a, b, client, document_id, root, hard)
            await _view(report, a, client, document_id, root, hard)
            await _witness(report, a, client, document_id, root, hard)
            await _tall_tip(report, a, folder, harness, presets["tall"])
            await _beside(report, a, folder, harness, hard)
            await _refusals(report, a, client, paint, harness, document_id, root, base, hard)
            await _masks(report, a, client, paint, harness, presets)
            await _rim(report, a, rim, harness, hard)
            await edges.run(report, a, folder, harness, hard)
            await filling.run(report, a, client, paint, harness, presets)
            await transparency.run(report, a, client, paint, harness, presets)
        with report.timed("benchmark"):
            for spec in BENCHMARKS:
                await _benchmark(report, a, client, harness, folder, spec, hard)
        # Inside the window whose brush state this function writes back.
        with report.timed("save"):
            await saving.run(report, a, client, harness, hard)
            await modified.run(report, a, client, harness, hard)
        with report.timed("acceptance"):
            await acceptance.run(report, a, client, harness, presets)
    finally:
        if isinstance(saved, Done):
            put_back = harness_call(
                client,
                "harness.brush_state",
                document_id=document_id,
                action="write",
                state=saved.result["state"],
            )
            again = harness_call(
                client,
                "harness.brush_state",
                document_id=document_id,
                action="read",
                preset_ids=used,
            )
            now = again.result["state"] if isinstance(again, Done) else None
            report.check(
                "the window's brush state is written back after the paint checks, as it was read",
                isinstance(put_back, Done) and now == saved.result["state"],
                "" if now == saved.result["state"] else f"{saved.result['state']} became {now}",
            )
        else:
            report.check("the window's brush state is read before painting", False, str(saved))
        await close(a, document_id)


async def _capabilities(report: Report, a: Client) -> None:
    data = (await tool(a, "krita_server_info", {})).get("data") or {}
    matrix = data.get("capabilities") or {}
    built = ("stroke.native_brush", "stroke.smoothing", "selection.enforced")
    report.check(
        "the capability matrix marks native strokes, smoothing and the selection supported "
        "since 0.9.0, and per-point input not",
        all(
            (matrix.get(name) or {}).get("supported") is True
            and (matrix.get(name) or {}).get("since") == "0.9.0"
            for name in built
        )
        and (matrix.get("stroke.per_point_input") or {}).get("supported") is False,
        ", ".join(f"{name} {(matrix.get(name) or {}).get('supported')}" for name in built),
    )


async def _colours(
    report: Report, a: Client, document_id: str, root: str, hard: dict[str, Any]
) -> None:
    layer_id = await add_layer(a, document_id, root, "colours")
    if layer_id is None:
        report.check("N-06's layer is added", False)
        return
    colours = [brush_colour(rgb) for rgb in COLOURS]
    problems = await _paint_colours(a, document_id, layer_id, hard, colours, 20, 60)
    centres = [[8 + index * 15, 40] for index in range(len(COLOURS))]
    on_layer, wrong = await _sampled(a, document_id, "layer", layer_id, centres)
    _, in_composite = await _sampled(a, document_id, "composite", None, centres)
    problems += wrong + in_composite
    report.check(
        "H6 / N-06: a hard round brush at opacity 1 paints 10 colours, #A7C284 among them, "
        "exactly at the stroke centre, on the layer and in the composite",
        not problems,
        "; ".join(problems[:4]),
    )
    # Each sample's color painted back as it came, 40 px below its source, inside the canvas.
    again = [sample.get("color") for sample in on_layer]
    back = [
        f"#{bytes(rgb).hex().upper()}: color {given}"
        for rgb, given in zip(COLOURS, again, strict=False)
        if given != brush_colour(rgb)
    ]
    if len(again) == len(COLOURS) and not back:
        back = await _paint_colours(a, document_id, layer_id, hard, again, 70, 90)
        _, wrong = await _sampled(
            a, document_id, "layer", layer_id, [[x, y + 40] for x, y in centres]
        )
        back += wrong
    report.check(
        "H6: each sampled color is the brush colour painted, and painted back unchanged it "
        "samples as the same bytes",
        len(again) == len(COLOURS) and not back,
        "; ".join(back[:4]) or f"{len(again)} samples",
    )


async def _paint_colours(
    a: Client,
    document_id: str,
    layer_id: str,
    hard: dict[str, Any],
    colours: list[Any],
    top: int,
    bottom: int,
) -> list[str]:
    # One vertical stroke per colour, 15 px apart.
    problems = []
    for index, (rgb, colour) in enumerate(zip(COLOURS, colours, strict=True)):
        x = 8 + index * 15
        brush = brush_args(hard, size_px=10, color=colour)
        done = await tool(
            a, TOOL, stroke_args(document_id, layer_id, brush, line_points(x, top, x, bottom))
        )
        if done.get("status") != "completed":
            problems.append(f"#{bytes(rgb).hex().upper()}: {code(done)}")
    return problems


async def _sampled(
    a: Client, document_id: str, target: str, layer_id: str | None, centres: list[list[int]]
) -> tuple[list[dict[str, Any]], list[str]]:
    # The samples at each colour's centre, and what differs from the colour painted there.
    sampled = await tool(
        a,
        "krita_sample",
        {
            "source": {"document_id": document_id, "frame": 0},
            "target": target,
            "layer_id": layer_id,
            "points": centres,
        },
    )
    samples = (sampled.get("data") or {}).get("samples") or []
    problems = [
        f"{target} #{bytes(rgb).hex().upper()}: {sample['rgba_255']}"
        for rgb, sample in zip(COLOURS, samples, strict=False)
        if sample["rgba_255"] != [*rgb, 255]
    ]
    if len(samples) != len(COLOURS):
        problems.append(f"{target}: {code(sampled)}")
    return samples, problems


async def _one_step(
    report: Report,
    a: Client,
    b: Client,
    client: BridgeClient,
    document_id: str,
    root: str,
    hard: dict[str, Any],
) -> None:
    layer_id = await add_layer(a, document_id, root, "undo")
    if layer_id is None:
        report.check("the undo check's layer is added", False)
        return
    width, height = fixtures.PAINT_WIDTH, fixtures.PAINT_HEIGHT
    before = await capture_composite(a, document_id, width, height)
    request_id = str(uuid.uuid4())
    arguments = stroke_args(
        document_id, layer_id, brush_args(hard), line_points(20, 70, 140, 80), request_id
    )
    first = await tool(a, TOOL, arguments)
    again = await tool(a, TOOL, arguments)
    from_b = await tool(b, TOOL, arguments)
    painted = await capture_composite(a, document_id, width, height)
    stroke_ids = {(content.get("data") or {}).get("stroke_id") for content in (first, from_b)}
    report.check(
        "a retried stroke returns the original receipt, from both servers, and paints nothing more",
        first.get("status") == "completed"
        and again == first
        and len(stroke_ids) == 1
        and from_b.get("status") == "completed",
        f"{code(first)}, again {again == first}, b {code(from_b) or stroke_ids}",
    )
    labels = harness_call(client, "harness.undo_labels", document_id=document_id)
    undo_label = labels.result.get("undo") if isinstance(labels, Done) else None
    undone = await tool(a, "krita_history_step", history_args(document_id, "undo"))
    after = await capture_composite(a, document_id, width, height)
    report.check(
        "one stroke is one undo step, named Scripted Brush Stroke: one history undo puts the "
        "composite back as it was",
        (first.get("data") or {}).get("undo_steps") == 1
        and undo_label == LABEL
        and (undone.get("data") or {}).get("steps_applied") == 1
        and bool(differs(painted, before))
        and not differs(after, before),
        f"label {undo_label!r}, {code(undone)}, composite {differs(after, before) or 'as before'}",
    )


async def _view(
    report: Report,
    a: Client,
    client: BridgeClient,
    document_id: str,
    root: str,
    hard: dict[str, Any],
) -> None:
    layer_id = await add_layer(a, document_id, root, "view")
    if layer_id is None:
        report.check("N-07's layer is added", False)
        return
    read = harness_call(client, "harness.view", document_id=document_id, view=None)
    if not isinstance(read, Done):
        report.check("harness.view reads the view", False, str(read))
        return
    first_view = read.result["view"]
    points = line_points(15, 15, 145, 85, 24)
    rect = {"x": 0, "y": 0, "width": fixtures.PAINT_WIDTH, "height": fixtures.PAINT_HEIGHT}
    hashes, views = [], []
    try:
        for view in (None, turned(first_view)):
            if view is not None:
                moved = harness_call(client, "harness.view", document_id=document_id, view=view)
                views.append(moved.result["view"] if isinstance(moved, Done) else str(moved))
            done = await tool(a, TOOL, stroke_args(document_id, layer_id, brush_args(hard), points))
            pixels = await capture(a, document_id, rect, "layer", layer_id)
            hashes.append(None if pixels is None else hashlib.sha256(pixels.tobytes()).hexdigest())
            if done.get("status") == "completed":
                await tool(a, "krita_history_step", history_args(document_id, "undo"))
    finally:
        harness_call(client, "harness.view", document_id=document_id, view=first_view)
    report.check(
        "N-07: one stroke lands on the same layer pixels at two zoom, rotation and pan settings",
        len(hashes) == 2 and hashes[0] is not None and hashes[0] == hashes[1],
        f"views {first_view} then {views}",
    )


async def _witness(
    report: Report,
    a: Client,
    client: BridgeClient,
    document_id: str,
    root: str,
    hard: dict[str, Any],
) -> None:
    layer_id = await add_layer(a, document_id, root, "witness")
    if layer_id is None:
        report.check("the witness check's layer is added", False)
        return
    # Two strokes, so the step under the one undone by hand has the same label: only the
    # pixels tell them apart.
    first = await tool(
        a, TOOL, stroke_args(document_id, layer_id, brush_args(hard), line_points(20, 30, 140, 30))
    )
    done = await tool(
        a, TOOL, stroke_args(document_id, layer_id, brush_args(hard), line_points(20, 60, 140, 60))
    )
    by_hand = harness_call(client, "harness.undo", document_id=document_id)
    under = by_hand.result.get("undo") if isinstance(by_hand, Done) else None
    refused = await tool(a, "krita_history_step", history_args(document_id, "undo"))
    report.check(
        "a stroke undone in Krita by hand stops history, though the stroke under it has the same "
        "label: its step no longer shows its pixels",
        first.get("status") == done.get("status") == "completed"
        and under == LABEL
        and code(refused) == "INVALID_ARGUMENT",
        f"{code(done)}, Krita's undo now {under!r}, history {code(refused)}",
    )


async def _tall_tip(
    report: Report, a: Client, folder: Path, harness: Path, tall: dict[str, Any] | None
) -> None:
    # Full scope, so nothing refuses a stroke that reaches past R: on an empty layer the
    # receipt's changed bounds are the stroke's whole extent.
    name = "a markedly non-square image tip's reach against R's margin"
    if tall is None:
        report.measured(name, f"none of {', '.join(TALL)} is listed")
        return
    source = folder / "tip.ora"
    base = fixtures.Layer("probe base", fixtures.rect(TIP_CANVAS_PX, TIP_CANVAS_PX, (30, 110, 200)))
    fixtures.write_ora(source, (base,), TIP_CANVAS_PX, TIP_CANVAS_PX)
    opened = await open_working(a, source, harness, "painting")
    document_id = opened.get("document_id")
    if opened.get("status") != "completed" or not document_id:
        report.measured(name, f"its document did not open: {code(opened)}")
        return
    middle = TIP_CANVAS_PX / 2
    lines = {
        "horizontal": line_points(middle - 80, middle, middle + 80, middle),
        "vertical": line_points(middle, middle - 80, middle, middle + 80),
        "diagonal": line_points(middle - 60, middle - 60, middle + 60, middle + 60),
    }
    found, margins = [], set()
    try:
        root = opened["data"]["root_layer_id"]
        for label, points in lines.items():
            layer_id = await add_layer(a, document_id, root, f"tip {label}")
            brush = brush_args(tall, size_px=TIP_BRUSH_PX)
            arguments = stroke_args(document_id, layer_id or "", brush, points, verify="full")
            data = (await tool(a, TOOL, arguments)).get("data") or {}
            if not data.get("changed_bounds_px"):
                found.append(f"{label}: not painted")
                continue
            margin = data["effective_brush"]["reach"]["margin_px"]
            margins.add(margin)
            past = _past(points, data["changed_bounds_px"])
            inside = "inside R" if past <= margin else f"past R by {past - margin:.0f} px"
            found.append(f"{label} {past:.0f} px ({past / TIP_BRUSH_PX:.2f} x size, {inside})")
    finally:
        await close(a, document_id)
    report.measured(
        name,
        f"{tall['name']} at {TIP_BRUSH_PX} px, margin "
        f"{', '.join(f'{margin:.1f}' for margin in sorted(margins)) or '-'} px; reached past the "
        f"path {'; '.join(found)}",
    )


async def _beside(
    report: Report, a: Client, folder: Path, harness: Path, hard: dict[str, Any]
) -> None:
    # The baseline is read after the stroke, so only the working copy's file can hold it.
    name = "a baseline rendered beside the current state after a stroke is the document as opened"
    source = folder / "beside.ora"
    fixtures.write_ora(source, fixtures.paint_stack(), fixtures.PAINT_WIDTH, fixtures.PAINT_HEIGHT)
    opened = await open_working(a, source, harness, "painting")
    document_id = opened.get("document_id")
    if opened.get("status") != "completed" or not document_id:
        report.check(name, False, str(opened.get("error")))
        return
    try:
        data = opened["data"]
        units = {"export_pixels_per_unit": previews.EXPORT_PER_UNIT, "master_to_export_scale": 0.5}
        alone = previews.arguments([previews.source(document_id)], previews.GAME[:1], **units)
        before = await tool(a, previews.TOOL, alone)
        layer_id = await add_layer(a, document_id, data["root_layer_id"], "beside")
        line = line_points(20, 48, fixtures.PAINT_WIDTH - 20, 48)
        painted = await tool(
            a, TOOL, stroke_args(document_id, layer_id or "", brush_args(hard), line)
        )
        paired = previews.source(document_id, baseline_id=data["baseline_id"])
        after = await tool(
            a, previews.TOOL, previews.arguments([paired], previews.GAME[:1], **units)
        )
        sheets = [(r.get("data") or {}).get("sheets") or [None] for r in (before, after)]
        was, now = sheets[0][0], sheets[1][0]
        if was is None or now is None or painted.get("status") != "completed":
            report.check(name, False, f"{code(before)}, {code(painted)}, {code(after)}")
            return
        as_opened, current = sheet_cell(now, 0), sheet_cell(now, 1)
        problem = differs(as_opened, sheet_cell(was, 0))
        changed = int((current != as_opened).any(axis=-1).sum())
        report.check(
            name,
            not problem and changed > 0,
            problem or f"the stroke changed {changed} of the current cell's pixels",
        )
    finally:
        await close(a, document_id)


def _past(points: list[dict[str, Any]], bounds: dict[str, int]) -> float:
    # How far the changed bounds reach past the path's box, on the side they reach furthest.
    xs = [float(point["x"]) for point in points]
    ys = [float(point["y"]) for point in points]
    return max(
        min(xs) - bounds["x"],
        bounds["x"] + bounds["width"] - max(xs),
        min(ys) - bounds["y"],
        bounds["y"] + bounds["height"] - max(ys),
    )


async def _refusals(
    report: Report,
    a: Client,
    client: BridgeClient,
    paint: Path,
    harness: Path,
    document_id: str,
    root: str,
    base: str,
    hard: dict[str, Any],
) -> None:
    layer_id = await add_layer(a, document_id, root, "refusals")
    group = await tool(
        a,
        "krita_layer_create",
        {
            "guard": guard(document_id),
            "parent_id": root,
            "above_id": None,
            "type": "group",
            "name": "krita-art-mcp probe group",
        },
    )
    group_id = (group.get("data") or {}).get("layer_id")
    if layer_id is None or group_id is None:
        report.check("the refusal checks' layers are added", False)
        return
    line = line_points(30, 30, 90, 40)
    pressed = [{**point, "pressure": 0.5} for point in line]
    unknown = {**hard, "id": "krita-art-mcp probe missing.kpp"}
    cases = {
        "a protected layer": (
            stroke_args(document_id, base, brush_args(hard), line),
            "LOCKED_TARGET",
        ),
        "a group": (
            stroke_args(document_id, group_id, brush_args(hard), line),
            "LAYER_NOT_PAINTABLE",
        ),
        "a point past the canvas": (
            stroke_args(document_id, layer_id, brush_args(hard), line_points(-40, 30, 90, 40)),
            "INVALID_ARGUMENT",
        ),
        "pressure without input_fallback": (
            stroke_args(document_id, layer_id, brush_args(hard), pressed),
            "UNSUPPORTED_CAPABILITY",
        ),
        "an unknown preset": (
            stroke_args(document_id, layer_id, brush_args(unknown), line),
            "INVALID_ARGUMENT",
        ),
        "a preset whose settings differ": (
            stroke_args(document_id, layer_id, brush_args(hard, preset_sha256="0" * 64), line),
            "RESOURCE_HASH_MISMATCH",
        ),
        "the eraser with alpha lock": (
            stroke_args(
                document_id, layer_id, brush_args(hard, eraser=True, alpha_lock=True), line
            ),
            "INVALID_ARGUMENT",
        ),
        "the eraser": (
            stroke_args(document_id, layer_id, brush_args(hard, eraser=True), line),
            "INVALID_ARGUMENT",
        ),
        "a single point": (
            stroke_args(document_id, layer_id, brush_args(hard), line[:1]),
            "UNSUPPORTED_CAPABILITY",
        ),
        "smooth stabilizer": (
            stroke_args(document_id, layer_id, brush_args(hard), line, smooth="stabilizer"),
            "INVALID_ARGUMENT",
        ),
    }
    found = {name: code(await tool(a, TOOL, arguments)) for name, (arguments, _) in cases.items()}
    wrong = [
        f"{name}: {found[name]}" for name, (_, wanted) in cases.items() if found[name] != wanted
    ]
    report.check(
        "paint_stroke refuses a protected layer, a group, a point past the canvas, pressure "
        "without input_fallback, an unknown or changed preset, eraser with alpha lock, the "
        "eraser, a single point and the stabilizer, each with its code",
        not wrong,
        "; ".join(wrong),
    )
    flat = await tool(
        a,
        TOOL,
        stroke_args(document_id, layer_id, brush_args(hard), pressed, input_fallback="flat"),
    )
    smooth = await tool(
        a, TOOL, stroke_args(document_id, layer_id, brush_args(hard), line, smooth="catmull_rom")
    )
    report.check(
        "input_fallback flat paints the pressed points at pressure 1, and catmull_rom smoothing "
        "paints",
        (flat.get("data") or {}).get("input_applied") == "flat"
        and smooth.get("status") == "completed",
        f"{code(flat) or 'flat'}, {code(smooth) or 'smoothed'}",
    )
    spread = harness_call(
        client, "harness.add_node", document_id=document_id, kind="filter_layer", layer_id=layer_id
    )
    region = await tool(a, TOOL, stroke_args(document_id, layer_id, brush_args(hard), line))
    full = await tool(
        a, TOOL, stroke_args(document_id, layer_id, brush_args(hard), line, verify="full")
    )
    reasons = ((region.get("error") or {}).get("details") or {}).get("reasons") or []
    report.check(
        "a filter layer above the target refuses region scope, naming it, and verify full paints",
        isinstance(spread, Done)
        and code(region) == "UNSUPPORTED_CAPABILITY"
        and any(entry.get("reason") == "filter_layer" for entry in reasons)
        and full.get("status") == "completed",
        f"region {code(region)}, full {code(full) or 'completed'}",
    )
    masked = harness_call(
        client,
        "harness.select_mask",
        document_id=document_id,
        layer_id=layer_id,
        rect={"x": 10, "y": 10, "width": 40, "height": 40},
    )
    local = await tool(
        a, TOOL, stroke_args(document_id, layer_id, brush_args(hard), line, verify="full")
    )
    report.check(
        "a layer with a local selection mask is LAYER_HAS_LOCAL_SELECTION",
        isinstance(masked, Done) and code(local) == "LAYER_HAS_LOCAL_SELECTION",
        str(code(local)),
    )
    read_only = await tool(a, "krita_document_open", open_args(paint, "read_only"))
    read_id = read_only.get("document_id")
    if read_id:
        try:
            layers = by_name((read_only.get("data") or {}).get("layers") or [])
            refused = await tool(
                a, TOOL, stroke_args(read_id, layers["probe base"]["id"], brush_args(hard), line)
            )
        finally:
            await close(a, read_id)
        report.check(
            "a read-only document refuses a stroke with DOCUMENT_READ_ONLY",
            code(refused) == "DOCUMENT_READ_ONLY",
            str(code(refused)),
        )
    else:
        report.check("the read-only copy opens", False, str(read_only.get("error")))


async def _masks(
    report: Report,
    a: Client,
    client: BridgeClient,
    paint: Path,
    harness: Path,
    presets: dict[str, Any],
) -> None:
    # N-08 / H8 on a copy of its own, since protection only tightens.
    opened = await open_working(a, paint, harness, "painting")
    document_id = opened.get("document_id")
    if opened.get("status") != "completed" or not document_id:
        report.check("N-08's working copy opens", False, str(opened.get("error")))
        return
    width, height = fixtures.PAINT_WIDTH, fixtures.PAINT_HEIGHT
    allowed = {"x": 40, "y": 24, "width": 60, "height": 40}
    try:
        data = opened["data"]
        layer_id = await add_layer(a, document_id, data["root_layer_id"], "mask")
        protected = await protect(a, document_id, data["layers"], {"rect": allowed})
        if layer_id is None or protected.get("status") != "completed":
            report.check("N-08's layer and protection are set", False, str(code(protected)))
            return
        edge = line_points(100, 30, 100, 58)
        for role in ("soft", "scatter"):
            preset = presets[role]
            if preset is None:
                report.check(f"N-08: a {role} stock preset is listed", False)
                continue
            brush = brush_args(preset, size_px=24)
            await select(a, document_id, {"type": "rect", "rect": allowed})
            kept = {
                mode: await tool(
                    a, TOOL, stroke_args(document_id, layer_id, brush, edge, verify=mode)
                )
                for mode in ("region", "full")
            }
            outside = {
                mode: ((content.get("data") or {}).get("verification") or {}).get(
                    "changed_outside_px"
                )
                for mode, content in kept.items()
            }
            await select(a, document_id, {"type": "none"})
            before = await capture_composite(a, document_id, width, height)
            leaked = {
                mode: await tool(
                    a, TOOL, stroke_args(document_id, layer_id, brush, edge, verify=mode)
                )
                for mode in ("region", "full")
            }
            if role == "soft":
                await _k43(report, a, client, document_id)
            after = await capture_composite(a, document_id, width, height)
            confirmed = {
                mode: ((content.get("error") or {}).get("details") or {}).get("rollback_verified")
                for mode, content in leaked.items()
            }
            report.check(
                f"N-08 / H8, {role} preset: beside a binary selection no pixel changes outside "
                "it in region and full scope; without it the leak is rolled back and confirmed "
                "in both",
                all(content.get("status") == "completed" for content in kept.values())
                and set(outside.values()) == {0}
                and all(code(content) == "PROTECTED_REGION_CHANGED" for content in leaked.values())
                and set(confirmed.values()) == {True}
                and not differs(after, before),
                f"kept {outside}, leaked {[code(c) for c in leaked.values()]}, "
                f"confirmed {confirmed}, composite {differs(after, before) or 'as before'}",
            )
        hard = presets["hard"]
        away = await tool(
            a,
            TOOL,
            stroke_args(document_id, layer_id, brush_args(hard), line_points(145, 85, 155, 90)),
        )
        report.check(
            "a stroke wholly outside the allowed mask is refused before painting with "
            "OUTSIDE_ALLOWED_MASK",
            code(away) == "OUTSIDE_ALLOWED_MASK",
            str(code(away)),
        )
    finally:
        await close(a, document_id)


async def _k43(report: Report, a: Client, client: BridgeClient, document_id: str) -> None:
    # Straight after a rollback, before any other step deletes Krita's redo of it.
    labels = harness_call(client, "harness.undo_labels", document_id=document_id)
    offered = labels.result.get("redo") if isinstance(labels, Done) else None
    redo = await tool(a, "krita_history_step", history_args(document_id, "redo"))
    report.check(
        "K43: Krita offers the redo of a rolled-back stroke, and history refuses it",
        offered == LABEL and code(redo) == "INVALID_ARGUMENT",
        f"Krita's redo {offered!r}, history {code(redo)}",
    )


async def _rim(report: Report, a: Client, rim: Path, harness: Path, hard: dict[str, Any]) -> None:
    opened = await open_working(a, rim, harness, "painting")
    document_id = opened.get("document_id")
    if opened.get("status") != "completed" or not document_id:
        report.check("the rim's working copy opens", False, str(opened.get("error")))
        return
    try:
        data = opened["data"]
        layers = data["layers"]
        protected = await protect(a, document_id, layers, None, preserve_alpha=True)
        clipped = await add_layer(a, document_id, data["root_layer_id"], "rim clip")
        plain = await add_layer(a, document_id, data["root_layer_id"], "rim plain")
        if clipped is None or plain is None or protected.get("status") != "completed":
            report.check("the rim's layers and protection are set", False, str(code(protected)))
            return
        await tool(
            a,
            "krita_layer_update",
            {
                "guard": guard(document_id),
                "layer_id": clipped,
                "properties": {"inherit_alpha": True},
            },
        )
        brush = brush_args(hard, size_px=8, color=brush_colour((230, 60, 30)))
        across = line_points(8, 24, 56, 24)
        before = await capture_composite(a, document_id, fixtures.WIDTH, fixtures.HEIGHT)
        kept = await tool(a, TOOL, stroke_args(document_id, clipped, brush, across))
        after = await capture_composite(a, document_id, fixtures.WIDTH, fixtures.HEIGHT)
        same_alpha = (
            before is not None
            and after is not None
            and np.array_equal(before[..., 3], after[..., 3])
        )
        checked = (kept.get("data") or {}).get("verification") or {}
        refused = await tool(a, TOOL, stroke_args(document_id, plain, brush, across))
        details = (refused.get("error") or {}).get("details") or {}
        again = await capture_composite(a, document_id, fixtures.WIDTH, fixtures.HEIGHT)
        report.check(
            "the rim: a correction on an inherit_alpha layer keeps every alpha byte under "
            "preserve_composite_alpha; the same stroke on a normal layer is rolled back",
            kept.get("status") == "completed"
            and checked.get("alpha_changed_px") == 0
            and same_alpha
            and code(refused) == "PROTECTED_REGION_CHANGED"
            and details.get("rollback_verified") is True
            and not differs(again, after),
            f"{code(kept) or 'kept'}, alpha {'kept' if same_alpha else 'changed'}, "
            f"plain {code(refused)}, composite {differs(again, after) or 'as before'}",
        )
    finally:
        await close(a, document_id)


def _size(folder: Path) -> int:
    if not folder.is_dir():
        return 0
    return sum(entry.stat().st_size for entry in folder.rglob("*") if entry.is_file())


async def _benchmark(
    report: Report,
    a: Client,
    client: BridgeClient,
    harness: Path,
    folder: Path,
    spec: dict[str, Any],
    hard: dict[str, Any],
) -> None:
    name, size = spec["name"], spec["size"]
    corner = size // 2 - AREA_PX // 2
    area = {"x": corner, "y": corner, "width": AREA_PX, "height": AREA_PX}
    source = folder / f"{name.lower()}.ora"
    fixtures.write_sparse_ora(source, fixtures.benchmark_stack(spec["layers"], area), size, size)
    baselines = harness / "server-a" / "baselines"
    held, rss_before = _size(baselines), krita_rss_kb()
    started = time.perf_counter()
    opened = await finished(a, await open_working(a, source, harness, "painting"), OPEN_LIMIT_S)
    opened_s = time.perf_counter() - started
    document_id = opened.get("document_id")
    report.measured(
        f"{name}: opening the {size} x {size} master with {spec['layers']} layers",
        f"{opened_s:.1f} s, {(_size(baselines) - held) / 1e6:.0f} MB of baseline written (read "
        "lazily), Krita "
        f"{megabytes(rss_before)} before and {megabytes(krita_rss_kb())} after",
    )
    if opened.get("status") != "completed" or not document_id:
        report.check(f"{name}'s master opens", False, str(opened.get("error")))
        return
    try:
        data = opened["data"]
        layer_id = await add_layer(a, document_id, data["root_layer_id"], "bench")
        if layer_id is None:
            report.check(f"{name}'s layer is added", False)
            return
        journal = harness / "server-a" / "journal"
        logged, rss = _lines_size(journal), krita_rss_kb()
        brush = brush_args(hard, size_px=BRUSH_PX)
        took, scopes, failures = await _timed_strokes(a, document_id, layer_id, brush, corner)
        report.check(
            f"{name}: {STROKES} strokes of {POINTS} points with a {BRUSH_PX} px brush on a "
            f"{size} x {size} master with {spec['layers']} protected layers, p95 under "
            f"{spec['budget_s']} s",
            not failures and _p95(took) < spec["budget_s"],
            f"{_timing(took)}, R {scopes[0]}; " + "; ".join(failures[:3]),
        )
        long_took = []
        for index in range(LONG_STROKES):
            points = line_points(40 + index * 9, 40, size - 40, size - 40 - index * 9, POINTS)
            started = time.perf_counter()
            done = await finished(
                a, await tool(a, TOOL, stroke_args(document_id, layer_id, brush, points)), 120.0
            )
            long_took.append(f"{time.perf_counter() - started:.2f} s {code(done) or ''}".strip())
        report.measured(f"{name}: corner-to-corner strokes, not gated", ", ".join(long_took))
        if name == "N-01":
            _retention(report, client, rss)
            _journal(report, journal, logged, STROKES + LONG_STROKES)
        await _selected(report, a, document_id, layer_id, brush, corner, spec)
    finally:
        await close(a, document_id)


async def _timed_strokes(
    a: Client, document_id: str, layer_id: str, brush: dict[str, Any], corner: int
) -> tuple[list[float], list[str], list[str]]:
    took, scopes, failures = [], [], []
    for index in range(STROKES):
        points = _s_curve(corner + index * 3, corner + index * 3)
        started = time.perf_counter()
        done = await tool(a, TOOL, stroke_args(document_id, layer_id, brush, points))
        took.append(time.perf_counter() - started)
        if done.get("status") != "completed":
            failures.append(f"stroke {index}: {code(done) or done.get('status')}")
        rect = ((done.get("data") or {}).get("verification") or {}).get("rect") or {}
        scopes.append(f"{rect.get('width')}x{rect.get('height')}")
    return took, scopes, failures


def _p95(took: list[float]) -> float:
    return statistics.quantiles(took, n=20)[18]


def _timing(took: list[float]) -> str:
    return f"p95 {_p95(took):.2f} s, mean {statistics.mean(took):.2f} s, max {max(took):.2f} s"


async def _selected(
    report: Report,
    a: Client,
    document_id: str,
    layer_id: str,
    brush: dict[str, Any],
    corner: int,
    spec: dict[str, Any],
) -> None:
    # Every stroke fingerprints the selection, so a canvas-wide one is what that read costs most.
    budget = spec["budget_s"]
    name = f"{spec['name']} with a canvas-wide selection, p95 under {budget} s"
    selected = await select(a, document_id, {"type": "all"})
    if selected.get("status") != "completed":
        report.check(name, False, str(code(selected)))
        return
    took, _, failures = await _timed_strokes(a, document_id, layer_id, brush, corner)
    await select(a, document_id, {"type": "none"})
    report.check(
        name,
        not failures and _p95(took) < budget,
        f"{_timing(took)}; " + "; ".join(failures[:3]),
    )


def _retention(report: Report, client: BridgeClient, rss_before: int | None) -> None:
    held = harness_call(client, "harness.retention")
    counts = held.result if isinstance(held, Done) else str(held)
    report.measured(
        "Krita's memory across N-01, and what the bridge holds after it",
        f"{megabytes(rss_before)} before, {megabytes(krita_rss_kb())} after; {counts}",
    )


def _journal(report: Report, journal: Path, before: int, strokes: int) -> None:
    # The lines a lookup decodes, apart from the argument files it never reads.
    size = _lines_size(journal)
    # The fastest of a few: one read can carry a collection of this process's whole heap, and the
    # week scales what it measures.
    lookup_s = min(_lookup_s(journal) for _ in range(LOOKUPS))
    per_stroke = (size - before) / strokes if strokes else 0.0
    week = per_stroke * WEEK_STROKES
    week_s = lookup_s * week / size if size else 0.0
    bites = week_s > LOOKUP_BUDGET_S or week > JOURNAL_BUDGET_BYTES
    held = _size(journal / "args")
    report.measured(
        "the journal after N-01, and a heavy week extrapolated",
        f"lines {size / 1e6:.2f} MB, {per_stroke / 1e3:.1f} KB per stroke, argument files "
        f"{held / 1e6:.2f} MB, the fastest of {LOOKUPS} lookups {lookup_s * 1000:.0f} ms; "
        f"a week of {WEEK_STROKES} strokes: {week / 1e6:.0f} MB of lines and {week_s:.2f} s, so it "
        f"{'bites' if bites else 'does not bite'}",
    )


def _lookup_s(journal: Path) -> float:
    started = time.perf_counter()
    Journal(journal).lookup(str(uuid.uuid4()))
    return time.perf_counter() - started


def _lines_size(journal: Path) -> int:
    return sum(path.stat().st_size for path in journal.glob("*.jsonl"))
