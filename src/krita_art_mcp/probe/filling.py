import time
from pathlib import Path
from typing import Any

import numpy as np
from jsonschema import Draft202012Validator
from mcp import Client

from krita_art_mcp import schemas
from krita_art_mcp.bridge_client import BridgeClient, Done
from krita_art_mcp.probe import fixtures
from krita_art_mcp.probe.common import (
    add_layer,
    brush_args,
    brush_colour,
    capture,
    capture_composite,
    close,
    guard,
    harness_call,
    history_args,
    line_points,
    open_working,
    protect,
    stroke_args,
)
from krita_art_mcp.probe.report import Report, code, differs, tool

TOOL = "krita_paint_fill"
LABEL = "Scripted Brush Stroke"
# The build-up stock preset every fill activates.
FILL = ("c) Pencil-3 Large 4B",)
WIDTH, HEIGHT = fixtures.PAINT_WIDTH, fixtures.PAINT_HEIGHT
WHOLE = {"x": 0, "y": 0, "width": WIDTH, "height": HEIGHT}
AMBER, RED = (200, 120, 40), (230, 60, 30)
POLYGON = {
    "type": "polygon",
    "points": [[30.5, 10.25], [110.75, 12.5], [108.25, 70.5], [32, 68.75]],
}
OUTPUT = Draft202012Validator(schemas.load(TOOL)["outputSchema"])


def fill_args(
    document_id: str,
    layer_id: str,
    shape: dict[str, Any],
    rgb: tuple[int, int, int] = RED,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "guard": guard(document_id),
        "layer_id": layer_id,
        "shape": shape,
        "color": brush_colour(rgb),
        "opacity": 1,
        **extra,
    }


def _rect(x: int, y: int, width: int, height: int, kind: str = "rect") -> dict[str, Any]:
    return {"type": kind, "rect": {"x": x, "y": y, "width": width, "height": height}}


async def _layer(a: Client, document_id: str, layer_id: str) -> np.ndarray | None:
    return await capture(a, document_id, WHOLE, "layer", layer_id)


async def run(
    report: Report,
    a: Client,
    client: BridgeClient,
    paint: Path,
    harness: Path,
    presets: dict[str, Any],
) -> None:
    await _capability(report, a)
    if not report.check(
        "the fill's stock preset c) Pencil-3 Large 4B is listed", presets["fill"] is not None
    ):
        return
    opened = await open_working(a, paint, harness, "filling")
    document_id = opened.get("document_id")
    if opened.get("status") != "completed" or not document_id:
        report.check("the fill checks' working copy opens", False, str(opened.get("error")))
        return
    try:
        data = opened["data"]
        root = data["root_layer_id"]
        await _feathered(report, a, client, document_id, root)
        await _blends(report, a, document_id, root)
        await _alpha_lock(report, a, document_id, root)
        await _presets(report, a, document_id, root, presets)
        await _edges(report, a, document_id, root)
        await _leak(report, a, document_id, root, data["layers"])
    finally:
        await close(a, document_id)


async def _capability(report: Report, a: Client) -> None:
    data = (await tool(a, "krita_server_info", {})).get("data") or {}
    entry = (data.get("capabilities") or {}).get("paint.fill") or {}
    report.check(
        "the capability matrix marks paint.fill supported since 0.21.0",
        entry.get("supported") is True and entry.get("since") == "0.21.0",
        str(entry),
    )


async def _feathered(
    report: Report, a: Client, client: BridgeClient, document_id: str, root: str
) -> None:
    layer = await add_layer(a, document_id, root, "fill feather")
    if layer is None:
        report.check("the feathered fill's layer is added", False)
        return
    selected = await tool(
        a,
        "krita_selection_set",
        {
            "guard": guard(document_id),
            "combine": "replace",
            "shape": _rect(40, 20, 60, 40),
            "feather_px": 6,
            "invert": False,
        },
    )
    started = time.perf_counter()
    done = await tool(a, TOOL, fill_args(document_id, layer, POLYGON))
    took = time.perf_counter() - started
    selection = await capture(a, document_id, WHOLE, "selection")
    after = await _layer(a, document_id, layer)
    worst = (
        None
        if selection is None or after is None
        else int(np.abs(after[..., 3].astype(int) - selection.astype(int)).max())
    )
    report.check(
        "a polygon fill under a feathered selection takes the selection's coverage as its alpha, "
        "and nothing outside it",
        selected.get("status") == "completed" and done.get("status") == "completed" and worst == 0,
        f"{code(done) or 'filled'}, alpha against coverage off by {worst}",
    )
    report.measured("a polygon fill's call, 160 x 96 canvas, region scope", f"{took:.3f} s")
    labels = harness_call(client, "harness.undo_labels", document_id=document_id)
    undo = labels.result.get("undo") if isinstance(labels, Done) else None
    undone = await tool(a, "krita_history_step", history_args(document_id, "undo"))
    empty = await _layer(a, document_id, layer)
    # Cleared after the undo, so the fill is Krita's top step when its label is read.
    await tool(
        a,
        "krita_selection_set",
        {
            "guard": guard(document_id),
            "combine": "replace",
            "shape": {"type": "none"},
            "feather_px": 0,
            "invert": False,
        },
    )
    report.check(
        "one fill is one undo step, labelled Scripted Brush Stroke, and one undo takes it back",
        (done.get("data") or {}).get("undo_steps") == 1
        and undo == LABEL
        and (undone.get("data") or {}).get("steps_applied") == 1
        and empty is not None
        and not empty.any(),
        f"Krita's undo {undo!r}, {code(undone) or 'undone'}",
    )


async def _blends(report: Report, a: Client, document_id: str, root: str) -> None:
    layer = await add_layer(a, document_id, root, "fill blend")
    if layer is None:
        report.check("the blend fill's layer is added", False)
        return
    base = await tool(a, TOOL, fill_args(document_id, layer, _rect(10, 10, 40, 30), AMBER))
    multiplied = await tool(
        a, TOOL, fill_args(document_id, layer, _rect(20, 15, 20, 20), RED, blend_mode="multiply")
    )
    half = await tool(
        a, TOOL, fill_args(document_id, layer, _rect(60, 10, 20, 20), RED, opacity=0.5)
    )
    found = await _layer(a, document_id, layer)
    product = [round(x * y / 255) for x, y in zip(AMBER, RED, strict=True)]
    centre = None if found is None else found[25, 30].tolist()
    faded = None if found is None else found[20, 70].tolist()
    report.check(
        "a fill applies its blend and opacity: multiply over amber gives the product, opacity "
        "0.5 gives alpha 128",
        all(content.get("status") == "completed" for content in (base, multiplied, half))
        and centre is not None
        and all(abs(got - want) <= 1 for got, want in zip(centre[:3], product, strict=True))
        and centre[3] == 255
        and faded is not None
        and faded[:3] == list(RED)
        and faded[3] in (127, 128),
        f"multiply {centre} against {product}, half {faded}",
    )


async def _alpha_lock(report: Report, a: Client, document_id: str, root: str) -> None:
    layer = await add_layer(a, document_id, root, "fill silhouette")
    if layer is None:
        report.check("the alpha lock's layer is added", False)
        return
    shape = await tool(
        a, TOOL, fill_args(document_id, layer, _rect(90, 20, 40, 40, "ellipse"), AMBER)
    )
    before = await _layer(a, document_id, layer)
    locked = await tool(
        a, TOOL, fill_args(document_id, layer, _rect(80, 10, 60, 60), RED, alpha_lock=True)
    )
    after = await _layer(a, document_id, layer)
    kept = (
        before is not None and after is not None and np.array_equal(before[..., 3], after[..., 3])
    )
    inside = None if after is None else after[after[..., 3] > 0][:, :3]
    report.check(
        "a fill with alpha lock keeps every alpha byte of a silhouette and recolours inside it",
        shape.get("status") == "completed"
        and locked.get("status") == "completed"
        and kept
        and inside is not None
        and inside.size > 0
        and bool((inside == np.array(RED)).all()),
        f"{code(locked) or 'filled'}, alpha {'kept' if kept else 'changed'}",
    )


async def _presets(
    report: Report, a: Client, document_id: str, root: str, presets: dict[str, Any]
) -> None:
    # Whatever preset was current, a fill paints the same bytes: it activates its own.
    layer = await add_layer(a, document_id, root, "fill presets")
    scratch = await add_layer(a, document_id, root, "fill scratch")
    second = presets["soft"] or presets["scatter"]
    if layer is None or scratch is None or second is None:
        report.check("the preset check's layers and second preset are there", False)
        return
    found, failed = [], []
    for preset in (presets["hard"], second):
        stroke = stroke_args(document_id, scratch, brush_args(preset), line_points(5, 85, 30, 90))
        stroked = await tool(a, "krita_paint_stroke", stroke)
        filled = await tool(a, TOOL, fill_args(document_id, layer, POLYGON))
        found.append(await _layer(a, document_id, layer))
        undone = await tool(a, "krita_history_step", history_args(document_id, "undo", 2))
        failed += [one for one in (code(stroked), code(filled), code(undone)) if one]
    report.check(
        "the same fill after a stroke with a second preset paints equal bytes, colour under "
        "alpha 0 included",
        not failed and found[0] is not None and not differs(found[1], found[0]),
        ", ".join(failed) or differs(found[1], found[0]) or "equal",
    )


async def _edges(report: Report, a: Client, document_id: str, root: str) -> None:
    layer = await add_layer(a, document_id, root, "fill edges")
    if layer is None:
        report.check("the edge fills' layer is added", False)
        return
    shapes = [
        _rect(0, 0, 12, 8),
        _rect(WIDTH - 12, 0, 12, 8),
        _rect(0, HEIGHT - 8, 12, 8),
        _rect(WIDTH - 12, HEIGHT - 8, 12, 8),
        _rect(0, 0, WIDTH, HEIGHT, "ellipse"),
    ]
    for scope in ("region", "full"):
        problems = []
        for shape in shapes:
            done = await tool(a, TOOL, fill_args(document_id, layer, shape, verify=scope))
            painted = await _layer(a, document_id, layer)
            data = done.get("data") or {}
            truth = None if painted is None else _bounds(painted)
            valid = not list(OUTPUT.iter_errors(done))
            await tool(a, "krita_history_step", history_args(document_id, "undo"))
            back = await _layer(a, document_id, layer)
            if not (
                done.get("status") == "completed"
                and valid
                and data.get("changed_bounds_px") == truth
                and data.get("layer_bounds_px") == truth
                and back is not None
                and not back.any()
            ):
                problems.append(f"{shape['type']} {shape['rect']}: {code(done)} {truth}")
        report.check(
            f"fills at each corner and over the whole canvas, {scope} scope: the receipt passes "
            "its schema, reports the true bounds on the canvas, and undoes",
            not problems,
            "; ".join(problems),
        )
    past = await tool(a, TOOL, fill_args(document_id, layer, _rect(WIDTH - 10, 0, 20, 8)))
    none = await tool(a, TOOL, fill_args(document_id, layer, {"type": "selection"}))
    outcomes = [((c.get("error") or {}).get("details") or {}).get("outcome") for c in (past, none)]
    report.check(
        "a shape past the canvas and a selection fill with no selection are refused, not applied",
        code(past) == code(none) == "INVALID_ARGUMENT" and outcomes == ["not_applied"] * 2,
        f"{code(past)}, {code(none)}, {outcomes}",
    )


async def _leak(
    report: Report, a: Client, document_id: str, root: str, layers: list[dict[str, Any]]
) -> None:
    # Last: protection only tightens.
    layer = await add_layer(a, document_id, root, "fill leak")
    allowed = {"x": 40, "y": 24, "width": 60, "height": 40}
    protected = await protect(a, document_id, layers, {"rect": allowed})
    if layer is None or protected.get("status") != "completed":
        report.check("the leak check's layer and protection are set", False, str(code(protected)))
        return
    before = await capture_composite(a, document_id, WIDTH, HEIGHT)
    across = {"type": "polygon", "points": [[30, 30], [90, 30], [90, 50], [30, 50]]}
    leaked = {
        scope: await tool(a, TOOL, fill_args(document_id, layer, across, verify=scope))
        for scope in ("region", "full")
    }
    after = await capture_composite(a, document_id, WIDTH, HEIGHT)
    confirmed = {
        scope: ((content.get("error") or {}).get("details") or {}).get("rollback_verified")
        for scope, content in leaked.items()
    }
    inset = await tool(a, TOOL, fill_args(document_id, layer, _rect(41, 25, 58, 38, "ellipse")))
    outside = ((inset.get("data") or {}).get("verification") or {}).get("changed_outside_px")
    report.check(
        "under a binary allowed mask a fill across its edge is rolled back and confirmed in both "
        "scopes; an ellipse a pixel inside it is kept",
        all(code(content) == "PROTECTED_REGION_CHANGED" for content in leaked.values())
        and set(confirmed.values()) == {True}
        and not differs(after, before)
        and inset.get("status") == "completed"
        and outside == 0,
        f"leaked {[code(c) for c in leaked.values()]}, confirmed {confirmed}, "
        f"composite {differs(after, before) or 'as before'}, inset {code(inset) or outside}",
    )


def _bounds(pixels: np.ndarray) -> dict[str, int] | None:
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
