import asyncio
import hashlib
import json
import math
import os
import statistics
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

import numpy as np
from mcp import Client
from PIL import Image

from krita_art_mcp import paths
from krita_art_mcp.bridge_client import BridgeClient, Done
from krita_art_mcp.journal import Journal
from krita_art_mcp.probe import fixtures
from krita_art_mcp.probe.changes import by_name, guard, history_args
from krita_art_mcp.probe.opening import open_args
from krita_art_mcp.probe.pixels import brushes
from krita_art_mcp.probe.report import Report, close, code, differs, tool

TOOL = "krita_paint_stroke"
LABEL = "Scripted Brush Stroke"
# Stock presets by name, the first Krita lists winning: a hard round tip, a soft one, and one
# that scatters its dabs.
HARD = ("b) Basic-2 Opacity", "d) Ink-3 Gpen")
SOFT = ("b) Airbrush Soft",)
SCATTER = ("y) Texture Spray", "v) Texture Impressionism")
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
# Decision 6's budgets, and decision 1's strokes: 200-point S-curves in a 400 x 400 area.
BENCHMARKS = (
    {"name": "N-01", "size": 2000, "layers": 20, "budget_s": 1.5},
    {"name": "N-09", "size": 8192, "layers": 30, "budget_s": 3.0},
)
STROKES = 20
LONG_STROKES = 3
POINTS = 200
BRUSH_PX = 40
AREA_PX = 400
# F3's rule (decision 3): a heavy week, and what counts as biting.
WEEK_STROKES = 7 * 2000
LOOKUP_BUDGET_S = 1.0
JOURNAL_BUDGET_BYTES = 100 * 1024 * 1024
# How long an open of the 8k master may run past the server's wait before the probe gives up.
OPEN_LIMIT_S = 600.0


def _colour(rgb: tuple[int, int, int]) -> dict[str, Any]:
    return {"space": "srgb", "rgba": [channel / 255 for channel in rgb] + [1]}


def _brush(preset: dict[str, Any], **changes: Any) -> dict[str, Any]:
    return {
        "preset_id": preset["id"],
        "preset_sha256": preset["sha256"],
        "size_px": 12,
        "opacity": 1,
        "flow": 1,
        "color": _colour((200, 60, 90)),
        "eraser": False,
        **changes,
    }


def _stroke(
    document_id: str,
    layer_id: str,
    brush: dict[str, Any],
    points: list[dict[str, Any]],
    request_id: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "guard": guard(document_id, request_id),
        "layer_id": layer_id,
        "brush": brush,
        "points": points,
        **extra,
    }


def _line(x0: float, y0: float, x1: float, y1: float, count: int = 8) -> list[dict[str, Any]]:
    return [
        {"x": x0 + (x1 - x0) * index / (count - 1), "y": y0 + (y1 - y0) * index / (count - 1)}
        for index in range(count)
    ]


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
    report.measured(
        "the stock presets the paint checks use",
        ", ".join(f"{role}: {(entry or {}).get('name')}" for role, entry in presets.items()),
    )
    hard = presets["hard"]
    if not report.check("a hard round stock preset is listed", hard is not None):
        return
    assert hard is not None
    paint, rim = folder / "paint.ora", folder / "rim.ora"
    fixtures.write_ora(paint, fixtures.paint_stack(), fixtures.PAINT_WIDTH, fixtures.PAINT_HEIGHT)
    fixtures.write_ora(rim, fixtures.rim_stack())
    await _capabilities(report, a)
    opened = await _open(a, paint, harness)
    document_id = opened.get("document_id")
    if opened.get("status") != "completed" or not document_id:
        report.check("the paint checks' working copy opens", False, str(opened.get("error")))
        return
    used = [entry["id"] for entry in presets.values() if entry is not None]
    saved = _harness(
        client, "harness.brush_state", document_id=document_id, action="read", preset_ids=used
    )
    try:
        data = opened["data"]
        root = data["root_layer_id"]
        base = by_name(data["layers"])["probe base"]["id"]
        await _colours(report, a, document_id, root, hard)
        await _one_step(report, a, b, client, document_id, root, hard)
        await _view(report, a, client, document_id, root, hard)
        await _witness(report, a, client, document_id, root, hard)
        await _refusals(report, a, client, paint, harness, document_id, root, base, hard)
        await _masks(report, a, client, paint, harness, presets)
        await _rim(report, a, rim, harness, hard)
        for spec in BENCHMARKS:
            await _benchmark(report, a, client, harness, folder, spec, hard)
    finally:
        if isinstance(saved, Done):
            put_back = _harness(
                client,
                "harness.brush_state",
                document_id=document_id,
                action="write",
                state=saved.result["state"],
            )
            again = _harness(
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


def _harness(client: BridgeClient, op: str, **args: Any) -> Any:
    return client.call(op, args, request_id=str(uuid.uuid4()))


async def _open(a: Client, source: Path, harness: Path, **extra: Any) -> dict[str, Any]:
    work = harness / "work" / "painting"
    return await tool(a, "krita_document_open", open_args(source, "working_copy", work, **extra))


async def _layer(a: Client, document_id: str, root: str, name: str) -> str | None:
    arguments = {
        "guard": guard(document_id),
        "parent_id": root,
        "above_id": None,
        "type": "paint",
        "name": f"krita-art-mcp probe {name}",
    }
    made = await tool(a, "krita_layer_create", arguments)
    layer_id: str | None = (made.get("data") or {}).get("layer_id")
    return layer_id


async def _composite(a: Client, document_id: str, width: int, height: int) -> np.ndarray | None:
    return await _capture(a, document_id, "composite", None, (0, 0, width, height))


async def _capture(
    a: Client,
    document_id: str,
    target: str,
    layer_id: str | None,
    box: tuple[int, int, int, int],
) -> np.ndarray | None:
    arguments = {
        "source": {"document_id": document_id, "frame": 0},
        "target": target,
        "layer_id": layer_id,
        "rect": {"x": box[0], "y": box[1], "width": box[2], "height": box[3]},
        "scale": 1,
        "filter": "nearest",
    }
    data = (await tool(a, "krita_capture", arguments)).get("data") or {}
    if "image" not in data:
        return None
    with Image.open(data["image"]["path"]) as image:
        return np.asarray(image.convert("RGBA"))


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
    layer_id = await _layer(a, document_id, root, "colours")
    if layer_id is None:
        report.check("N-06's layer is added", False)
        return
    centres, problems = [], []
    for index, rgb in enumerate(COLOURS):
        x = 8 + index * 15
        brush = _brush(hard, size_px=10, color=_colour(rgb))
        done = await tool(a, TOOL, _stroke(document_id, layer_id, brush, _line(x, 20, x, 60)))
        if done.get("status") != "completed":
            problems.append(f"#{bytes(rgb).hex().upper()}: {code(done)}")
        centres.append([x, 40])
    for target, chosen in (("layer", layer_id), ("composite", None)):
        sampled = await tool(
            a,
            "krita_sample",
            {
                "source": {"document_id": document_id, "frame": 0},
                "target": target,
                "layer_id": chosen,
                "points": centres,
            },
        )
        samples = (sampled.get("data") or {}).get("samples") or []
        for rgb, sample in zip(COLOURS, samples, strict=False):
            if sample["rgba"] != [*rgb, 255]:
                problems.append(f"{target} #{bytes(rgb).hex().upper()}: {sample['rgba']}")
        if len(samples) != len(COLOURS):
            problems.append(f"{target}: {code(sampled)}")
    report.check(
        "H6 / N-06: a hard round brush at opacity 1 paints 10 colours, #A7C284 among them, "
        "exactly at the stroke centre, on the layer and in the composite",
        not problems,
        "; ".join(problems[:4]),
    )


async def _one_step(
    report: Report,
    a: Client,
    b: Client,
    client: BridgeClient,
    document_id: str,
    root: str,
    hard: dict[str, Any],
) -> None:
    layer_id = await _layer(a, document_id, root, "undo")
    if layer_id is None:
        report.check("the undo check's layer is added", False)
        return
    width, height = fixtures.PAINT_WIDTH, fixtures.PAINT_HEIGHT
    before = await _composite(a, document_id, width, height)
    request_id = str(uuid.uuid4())
    arguments = _stroke(document_id, layer_id, _brush(hard), _line(20, 70, 140, 80), request_id)
    first = await tool(a, TOOL, arguments)
    again = await tool(a, TOOL, arguments)
    from_b = await tool(b, TOOL, arguments)
    painted = await _composite(a, document_id, width, height)
    stroke_ids = {(content.get("data") or {}).get("stroke_id") for content in (first, from_b)}
    report.check(
        "a retried stroke returns the original receipt, from both servers, and paints nothing more",
        first.get("status") == "completed"
        and again == first
        and len(stroke_ids) == 1
        and from_b.get("status") == "completed",
        f"{code(first)}, again {again == first}, b {code(from_b) or stroke_ids}",
    )
    labels = _harness(client, "harness.undo_labels", document_id=document_id)
    undo_label = labels.result.get("undo") if isinstance(labels, Done) else None
    undone = await tool(a, "krita_history_step", history_args(document_id, "undo"))
    after = await _composite(a, document_id, width, height)
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
    layer_id = await _layer(a, document_id, root, "view")
    if layer_id is None:
        report.check("N-07's layer is added", False)
        return
    read = _harness(client, "harness.view", document_id=document_id, view=None)
    if not isinstance(read, Done):
        report.check("harness.view reads the view", False, str(read))
        return
    first_view = read.result["view"]
    points = _line(15, 15, 145, 85, 24)
    box = (0, 0, fixtures.PAINT_WIDTH, fixtures.PAINT_HEIGHT)
    hashes, views = [], []
    try:
        for view in (None, _turned(first_view)):
            if view is not None:
                moved = _harness(client, "harness.view", document_id=document_id, view=view)
                views.append(moved.result["view"] if isinstance(moved, Done) else str(moved))
            done = await tool(a, TOOL, _stroke(document_id, layer_id, _brush(hard), points))
            pixels = await _capture(a, document_id, "layer", layer_id, box)
            hashes.append(None if pixels is None else hashlib.sha256(pixels.tobytes()).hexdigest())
            if done.get("status") == "completed":
                await tool(a, "krita_history_step", history_args(document_id, "undo"))
    finally:
        _harness(client, "harness.view", document_id=document_id, view=first_view)
    report.check(
        "N-07: one stroke lands on the same layer pixels at two zoom, rotation and pan settings",
        len(hashes) == 2 and hashes[0] is not None and hashes[0] == hashes[1],
        f"views {first_view} then {views}",
    )


def _turned(view: dict[str, Any]) -> dict[str, Any]:
    turned: dict[str, Any] = {"zoom": view["zoom"] * 2.5, "rotation_deg": 30.0}
    if view.get("pan_px") is not None:
        turned["pan_px"] = [view["pan_px"][0] + 40, view["pan_px"][1] + 25]
    return turned


async def _witness(
    report: Report,
    a: Client,
    client: BridgeClient,
    document_id: str,
    root: str,
    hard: dict[str, Any],
) -> None:
    layer_id = await _layer(a, document_id, root, "witness")
    if layer_id is None:
        report.check("the witness check's layer is added", False)
        return
    # Two strokes, so the step under the one undone by hand has the same label: only the
    # pixels tell them apart.
    first = await tool(
        a, TOOL, _stroke(document_id, layer_id, _brush(hard), _line(20, 30, 140, 30))
    )
    done = await tool(a, TOOL, _stroke(document_id, layer_id, _brush(hard), _line(20, 60, 140, 60)))
    by_hand = _harness(client, "harness.undo", document_id=document_id)
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
    layer_id = await _layer(a, document_id, root, "refusals")
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
    line = _line(30, 30, 90, 40)
    pressed = [{**point, "pressure": 0.5} for point in line]
    unknown = {**hard, "id": "krita-art-mcp probe missing.kpp"}
    cases = {
        "a protected layer": (_stroke(document_id, base, _brush(hard), line), "LOCKED_TARGET"),
        "a group": (_stroke(document_id, group_id, _brush(hard), line), "LAYER_NOT_PAINTABLE"),
        "a point past the canvas": (
            _stroke(document_id, layer_id, _brush(hard), _line(-40, 30, 90, 40)),
            "INVALID_ARGUMENT",
        ),
        "pressure without input_fallback": (
            _stroke(document_id, layer_id, _brush(hard), pressed),
            "UNSUPPORTED_CAPABILITY",
        ),
        "an unknown preset": (
            _stroke(document_id, layer_id, _brush(unknown), line),
            "INVALID_ARGUMENT",
        ),
        "a preset whose settings differ": (
            _stroke(document_id, layer_id, _brush(hard, preset_sha256="0" * 64), line),
            "RESOURCE_HASH_MISMATCH",
        ),
        "the eraser with alpha lock": (
            _stroke(document_id, layer_id, _brush(hard, eraser=True, alpha_lock=True), line),
            "INVALID_ARGUMENT",
        ),
        "the eraser": (
            _stroke(document_id, layer_id, _brush(hard, eraser=True), line),
            "UNSUPPORTED_CAPABILITY",
        ),
        "a single point": (
            _stroke(document_id, layer_id, _brush(hard), line[:1]),
            "UNSUPPORTED_CAPABILITY",
        ),
        "smooth stabilizer": (
            _stroke(document_id, layer_id, _brush(hard), line, smooth="stabilizer"),
            "UNSUPPORTED_CAPABILITY",
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
        a, TOOL, _stroke(document_id, layer_id, _brush(hard), pressed, input_fallback="flat")
    )
    smooth = await tool(
        a, TOOL, _stroke(document_id, layer_id, _brush(hard), line, smooth="catmull_rom")
    )
    report.check(
        "input_fallback flat paints the pressed points at pressure 1, and catmull_rom smoothing "
        "paints",
        (flat.get("data") or {}).get("input_applied") == "flat"
        and smooth.get("status") == "completed",
        f"{code(flat) or 'flat'}, {code(smooth) or 'smoothed'}",
    )
    spread = _harness(
        client, "harness.add_node", document_id=document_id, kind="filter_layer", layer_id=layer_id
    )
    region = await tool(a, TOOL, _stroke(document_id, layer_id, _brush(hard), line))
    full = await tool(a, TOOL, _stroke(document_id, layer_id, _brush(hard), line, verify="full"))
    reasons = ((region.get("error") or {}).get("details") or {}).get("reasons") or []
    report.check(
        "a filter layer above the target refuses region scope, naming it, and verify full paints",
        isinstance(spread, Done)
        and code(region) == "UNSUPPORTED_CAPABILITY"
        and any(entry.get("reason") == "filter_layer" for entry in reasons)
        and full.get("status") == "completed",
        f"region {code(region)}, full {code(full) or 'completed'}",
    )
    masked = _harness(
        client,
        "harness.select_mask",
        document_id=document_id,
        layer_id=layer_id,
        rect={"x": 10, "y": 10, "width": 40, "height": 40},
    )
    local = await tool(a, TOOL, _stroke(document_id, layer_id, _brush(hard), line, verify="full"))
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
                a, TOOL, _stroke(read_id, layers["probe base"]["id"], _brush(hard), line)
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
    opened = await _open(a, paint, harness)
    document_id = opened.get("document_id")
    if opened.get("status") != "completed" or not document_id:
        report.check("N-08's working copy opens", False, str(opened.get("error")))
        return
    width, height = fixtures.PAINT_WIDTH, fixtures.PAINT_HEIGHT
    allowed = {"x": 40, "y": 24, "width": 60, "height": 40}
    try:
        data = opened["data"]
        layer_id = await _layer(a, document_id, data["root_layer_id"], "mask")
        protected = await tool(
            a,
            "krita_protection_set",
            {
                "guard": guard(document_id),
                "protected_layer_ids": [layer["id"] for layer in data["layers"]],
                "allowed_change_mask": {"rect": allowed},
                "preserve_composite_alpha": False,
                "preserve_canvas": False,
            },
        )
        if layer_id is None or protected.get("status") != "completed":
            report.check("N-08's layer and protection are set", False, str(code(protected)))
            return
        edge = _line(100, 30, 100, 58)
        for role in ("soft", "scatter"):
            preset = presets[role]
            if preset is None:
                report.check(f"N-08: a {role} stock preset is listed", False)
                continue
            brush = _brush(preset, size_px=24)
            await _select(a, document_id, {"type": "rect", "rect": allowed})
            kept = {
                mode: await tool(a, TOOL, _stroke(document_id, layer_id, brush, edge, verify=mode))
                for mode in ("region", "full")
            }
            outside = {
                mode: ((content.get("data") or {}).get("verification") or {}).get(
                    "changed_outside_px"
                )
                for mode, content in kept.items()
            }
            await _select(a, document_id, {"type": "none"})
            before = await _composite(a, document_id, width, height)
            leaked = {
                mode: await tool(a, TOOL, _stroke(document_id, layer_id, brush, edge, verify=mode))
                for mode in ("region", "full")
            }
            if role == "soft":
                await _k43(report, a, client, document_id)
            after = await _composite(a, document_id, width, height)
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
            a, TOOL, _stroke(document_id, layer_id, _brush(hard), _line(145, 85, 155, 90))
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
    labels = _harness(client, "harness.undo_labels", document_id=document_id)
    offered = labels.result.get("redo") if isinstance(labels, Done) else None
    redo = await tool(a, "krita_history_step", history_args(document_id, "redo"))
    report.check(
        "K43: Krita offers the redo of a rolled-back stroke, and history refuses it",
        offered == LABEL and code(redo) == "INVALID_ARGUMENT",
        f"Krita's redo {offered!r}, history {code(redo)}",
    )


async def _select(a: Client, document_id: str, shape: dict[str, Any]) -> None:
    await tool(
        a,
        "krita_selection_set",
        {
            "guard": guard(document_id),
            "combine": "replace",
            "shape": shape,
            "feather_px": 0,
            "invert": False,
        },
    )


async def _rim(report: Report, a: Client, rim: Path, harness: Path, hard: dict[str, Any]) -> None:
    opened = await _open(a, rim, harness)
    document_id = opened.get("document_id")
    if opened.get("status") != "completed" or not document_id:
        report.check("the rim's working copy opens", False, str(opened.get("error")))
        return
    try:
        data = opened["data"]
        layers = data["layers"]
        protect = await tool(
            a,
            "krita_protection_set",
            {
                "guard": guard(document_id),
                "protected_layer_ids": [layer["id"] for layer in layers],
                "allowed_change_mask": None,
                "preserve_composite_alpha": True,
                "preserve_canvas": False,
            },
        )
        clipped = await _layer(a, document_id, data["root_layer_id"], "rim clip")
        plain = await _layer(a, document_id, data["root_layer_id"], "rim plain")
        if clipped is None or plain is None or protect.get("status") != "completed":
            report.check("the rim's layers and protection are set", False, str(code(protect)))
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
        brush = _brush(hard, size_px=8, color=_colour((230, 60, 30)))
        across = _line(8, 24, 56, 24)
        before = await _composite(a, document_id, fixtures.WIDTH, fixtures.HEIGHT)
        kept = await tool(a, TOOL, _stroke(document_id, clipped, brush, across))
        after = await _composite(a, document_id, fixtures.WIDTH, fixtures.HEIGHT)
        same_alpha = (
            before is not None
            and after is not None
            and np.array_equal(before[..., 3], after[..., 3])
        )
        checked = (kept.get("data") or {}).get("verification") or {}
        refused = await tool(a, TOOL, _stroke(document_id, plain, brush, across))
        details = (refused.get("error") or {}).get("details") or {}
        again = await _composite(a, document_id, fixtures.WIDTH, fixtures.HEIGHT)
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


def _krita_rss_kb() -> int | None:
    try:
        pid = json.loads(paths.bridge_file().read_text(encoding="utf-8"))["pid"]
        out = subprocess.run(
            ["ps", "-o", "rss=", "-p", str(int(pid))],
            capture_output=True,
            text=True,
            check=True,
            stdin=subprocess.DEVNULL,
        ).stdout
        return int(out.strip())
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError):
        return None


def _megabytes(kilobytes: int | None) -> str:
    return "unread" if kilobytes is None else f"{kilobytes / 1024:.0f} MB"


def _size(folder: Path) -> int:
    if not folder.is_dir():
        return 0
    return sum(entry.stat().st_size for entry in folder.rglob("*") if entry.is_file())


async def _finished(a: Client, content: dict[str, Any], limit_s: float) -> dict[str, Any]:
    # A call that ran past the server's wait is followed to its receipt.
    deadline = time.monotonic() + limit_s
    while content.get("status") in ("queued", "running") and time.monotonic() < deadline:
        await asyncio.sleep(1.0)
        got = await tool(a, "krita_operation_get", {"operation_id": content["operation_id"]})
        receipt = (got.get("data") or {}).get("receipt")
        if receipt is not None:
            return dict(receipt)
    return content


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
    held, rss_before = _size(baselines), _krita_rss_kb()
    started = time.perf_counter()
    opened = await _finished(a, await _open(a, source, harness), OPEN_LIMIT_S)
    opened_s = time.perf_counter() - started
    document_id = opened.get("document_id")
    report.measured(
        f"{name}: opening the {size} x {size} master with {spec['layers']} layers",
        f"{opened_s:.1f} s, baseline {(_size(baselines) - held) / 1e6:.0f} MB on disk, Krita "
        f"{_megabytes(rss_before)} before and {_megabytes(_krita_rss_kb())} after",
    )
    if opened.get("status") != "completed" or not document_id:
        report.check(f"{name}'s master opens", False, str(opened.get("error")))
        return
    try:
        data = opened["data"]
        layer_id = await _layer(a, document_id, data["root_layer_id"], "bench")
        if layer_id is None:
            report.check(f"{name}'s layer is added", False)
            return
        journal = harness / "server-a" / "journal"
        logged, rss = _lines_size(journal), _krita_rss_kb()
        brush = _brush(hard, size_px=BRUSH_PX)
        took, scopes, failures = [], [], []
        for index in range(STROKES):
            points = _s_curve(corner + index * 3, corner + index * 3)
            started = time.perf_counter()
            done = await tool(a, TOOL, _stroke(document_id, layer_id, brush, points))
            took.append(time.perf_counter() - started)
            if done.get("status") != "completed":
                failures.append(f"stroke {index}: {code(done) or done.get('status')}")
            rect = ((done.get("data") or {}).get("verification") or {}).get("rect") or {}
            scopes.append(f"{rect.get('width')}x{rect.get('height')}")
        p95 = statistics.quantiles(took, n=20)[18]
        report.check(
            f"{name}: {STROKES} strokes of {POINTS} points with a {BRUSH_PX} px brush on a "
            f"{size} x {size} master with {spec['layers']} protected layers, p95 under "
            f"{spec['budget_s']} s",
            not failures and p95 < spec["budget_s"],
            f"p95 {p95:.2f} s, mean {statistics.mean(took):.2f} s, max {max(took):.2f} s, "
            f"R {scopes[0]}; " + "; ".join(failures[:3]),
        )
        long_took = []
        for index in range(LONG_STROKES):
            points = _line(40 + index * 9, 40, size - 40, size - 40 - index * 9, POINTS)
            started = time.perf_counter()
            done = await _finished(
                a, await tool(a, TOOL, _stroke(document_id, layer_id, brush, points)), 120.0
            )
            long_took.append(f"{time.perf_counter() - started:.2f} s {code(done) or ''}".strip())
        report.measured(f"{name}: corner-to-corner strokes, not gated", ", ".join(long_took))
        if name == "N-01":
            _retention(report, client, rss)
            _journal(report, journal, logged, STROKES + LONG_STROKES)
    finally:
        await close(a, document_id)


def _retention(report: Report, client: BridgeClient, rss_before: int | None) -> None:
    held = _harness(client, "probe.retention")
    counts = held.result if isinstance(held, Done) else str(held)
    report.measured(
        "F2: Krita's memory across N-01, and what the bridge holds after it",
        f"{_megabytes(rss_before)} before, {_megabytes(_krita_rss_kb())} after; {counts}",
    )


def _journal(report: Report, journal: Path, before: int, strokes: int) -> None:
    # The lines a lookup decodes, apart from the argument files it never reads.
    size = _lines_size(journal)
    started = time.perf_counter()
    Journal(journal).lookup(str(uuid.uuid4()))
    lookup_s = time.perf_counter() - started
    per_stroke = (size - before) / strokes if strokes else 0.0
    week = per_stroke * WEEK_STROKES
    week_s = lookup_s * week / size if size else 0.0
    bites = week_s > LOOKUP_BUDGET_S or week > JOURNAL_BUDGET_BYTES
    held = _size(journal / "args")
    report.measured(
        "F3: the journal after N-01, and a heavy week extrapolated (decision 3)",
        f"lines {size / 1e6:.2f} MB, {per_stroke / 1e3:.1f} KB per stroke, argument files "
        f"{held / 1e6:.2f} MB, a fresh first lookup {lookup_s * 1000:.0f} ms; a week of "
        f"{WEEK_STROKES} strokes: {week / 1e6:.0f} MB of lines and {week_s:.2f} s, so it "
        f"{'bites' if bites else 'does not bite'}",
    )


def _lines_size(journal: Path) -> int:
    return sum(path.stat().st_size for path in journal.glob("*.jsonl"))
