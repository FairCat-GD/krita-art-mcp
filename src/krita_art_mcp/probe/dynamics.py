import itertools
import math
from pathlib import Path
from typing import Any

import numpy as np
from jsonschema import Draft202012Validator
from mcp import Client

from krita_art_mcp import schemas, strokes
from krita_art_mcp.bridge_client import BridgeClient, Done
from krita_art_mcp.probe import fixtures
from krita_art_mcp.probe.common import (
    add_layer,
    brush_args,
    capture,
    close,
    harness_call,
    line_points,
    open_working,
    protect,
    stroke_args,
)
from krita_art_mcp.probe.pixels import brushes
from krita_art_mcp.probe.report import Report, code, tool

TOOL = "krita_paint_stroke"
WIDTH, HEIGHT = 640, 320
WHOLE = {"x": 0, "y": 0, "width": WIDTH, "height": HEIGHT}
SIZE = 40
OUTPUT = Draft202012Validator(schemas.load(TOOL)["outputSchema"])


def _knots(*pairs: tuple[float, float]) -> list[dict[str, float]]:
    return [{"at": at, "value": value} for at, value in pairs]


ENDS = _knots((0, 0.1), (0.5, 1), (1, 0.1))
PINCH = _knots((0, 1), (0.5, 0.2), (1, 1))
RAMP = _knots((0, 0.1), (1, 1))
# Every stroke starts well away from the canvas origin, where a scripted stroke's Distance sensor
# starts counting (K51): were Krita to stop doing so, these tapers would land elsewhere.
SHORT = (100.0, 60.0, 180.0)
LONG = (60.0, 160.0, 580.0)
REFERENCE = (160.0, 160.0, 480.0)
CENTRE, RADIUS = (320.0, 300.0), 110.0


def _arc(count: int = 13) -> list[dict[str, float]]:
    points = []
    for index in range(count):
        theta = math.pi * (1 - index / (count - 1))
        x = CENTRE[0] + RADIUS * math.cos(theta)
        points.append({"x": x, "y": CENTRE[1] - RADIUS * math.sin(theta)})
    return points


def _line(spec: tuple[float, float, float], count: int = 9) -> list[dict[str, Any]]:
    x0, y, x1 = spec
    return line_points(x0, y, x1, y, count)


def _value(knots: list[dict[str, float]], at: float) -> float:
    for earlier, later in itertools.pairwise(knots):
        if earlier["at"] <= at <= later["at"]:
            share = (at - earlier["at"]) / (later["at"] - earlier["at"])
            return earlier["value"] + share * (later["value"] - earlier["value"])
    return knots[-1]["value"]


def _widths(pixels: np.ndarray, spec: tuple[float, float, float], ts: list[float]) -> list[int]:
    # The widest column within 2 px of each point: a dab's centre may sit beside it.
    x0, _, x1 = spec
    alpha = pixels[..., 3]
    found = []
    for at in ts:
        x = round(x0 + (x1 - x0) * at)
        columns = range(max(0, x - 2), min(WIDTH, x + 3))
        found.append(int(max((alpha[:, column] > 0).sum() for column in columns)))
    return found


def _arc_widths(pixels: np.ndarray, ts: list[float]) -> list[float]:
    # Across the arc, along its radius, a quarter pixel at a time.
    alpha = pixels[..., 3]
    found = []
    for at in ts:
        best = 0
        for step in (-2, -1, 0, 1, 2):
            theta = math.pi * (1 - at) + step / RADIUS
            count = 0
            for k in range(-SIZE * 4, SIZE * 4 + 1):
                r = RADIUS + k * 0.25
                x = round(CENTRE[0] + r * math.cos(theta))
                y = round(CENTRE[1] - r * math.sin(theta))
                if 0 <= x < WIDTH and 0 <= y < HEIGHT and alpha[y, x] > 0:
                    count += 1
            best = max(best, count)
        found.append(best / 4)
    return found


def _alpha(pixels: np.ndarray, spec: tuple[float, float, float], ts: list[float]) -> list[int]:
    x0, y, x1 = spec
    row = round(y)
    found = []
    for at in ts:
        x = min(max(round(x0 + (x1 - x0) * at), 2), WIDTH - 3)
        found.append(int(np.median(pixels[row - 1 : row + 2, x - 2 : x + 3, 3])))
    return found


def _near(found: float, expected: float) -> bool:
    return abs(found - expected) <= max(2.0, 0.15 * expected)


class Tapers:
    def __init__(self, a: Client, document_id: str, root: str, preset: dict[str, Any]) -> None:
        self.a, self.document_id, self.root, self.preset = a, document_id, root, preset
        self.receipts: list[dict[str, Any]] = []

    async def paint(
        self, name: str, points: list[dict[str, Any]], smooth: str = "none", **changes: Any
    ) -> np.ndarray | None:
        layer = await add_layer(self.a, self.document_id, self.root, f"dynamics {name}")
        if layer is None:
            return None
        size, opacity = changes.pop("size_px", SIZE), changes.pop("opacity", 1)
        brush = brush_args(self.preset, size_px=size, opacity=opacity)
        arguments = stroke_args(self.document_id, layer, brush, points, smooth=smooth, **changes)
        content = await tool(self.a, TOOL, arguments)
        if content.get("status") != "completed":
            return None
        if "dynamics" in changes:
            self.receipts.append({"content": content, "points": points, "smooth": smooth})
        return await capture(self.a, self.document_id, WHOLE, "layer", layer)


async def run(
    report: Report,
    a: Client,
    client: BridgeClient,
    folder: Path,
    harness: Path,
    preset: dict[str, Any] | None,
) -> None:
    await _capability(report, a)
    if preset is None:
        report.check("the taper checks' hard round stock preset is listed", False)
        return
    source = folder / "dynamics.ora"
    base = fixtures.Layer("probe base", fixtures.rect(WIDTH, HEIGHT, (210, 200, 180)))
    fixtures.write_ora(source, (base,), WIDTH, HEIGHT)
    opened = await open_working(a, source, harness, "dynamics")
    document_id = opened.get("document_id")
    if opened.get("status") != "completed" or not document_id:
        report.check("the taper checks' working copy opens", False, str(opened.get("error")))
        return
    try:
        data = opened["data"]
        before = await _preset_state(a, client, document_id, preset)
        tapers = Tapers(a, document_id, data["root_layer_id"], preset)
        await _widths_and_alpha(report, tapers)
        _receipts(report, tapers)
        after = await _preset_state(a, client, document_id, preset)
        report.check(
            "after the tapers, their preset's listed hash and dirty flag are as before",
            before == after and before[1] is not None,
            f"{before} became {after}",
        )
        await _refusals(report, a, document_id, data["root_layer_id"], preset)
        await _leak(report, a, client, tapers, data["layers"], before)
    finally:
        await close(a, document_id)


async def _capability(report: Report, a: Client) -> None:
    data = (await tool(a, "krita_server_info", {})).get("data") or {}
    entry = (data.get("capabilities") or {}).get("stroke.dynamics") or {}
    report.check(
        "the capability matrix marks stroke.dynamics supported since 0.24.0",
        entry.get("supported") is True and entry.get("since") == "0.24.0",
        str(entry),
    )


async def _preset_state(
    a: Client, client: BridgeClient, document_id: str, preset: dict[str, Any]
) -> tuple[str | None, bool | None]:
    listed = {entry["id"]: entry for entry in await brushes(a) or []}
    read = harness_call(
        client, "harness.preset_dirty", document_id=document_id, preset_ids=[preset["id"]]
    )
    dirty = read.result["dirty"].get(preset["id"]) if isinstance(read, Done) else None
    return (listed.get(preset["id"]) or {}).get("sha256"), dirty


async def _widths_and_alpha(report: Report, tapers: Tapers) -> None:
    reference = _line(REFERENCE)
    sizes = {}
    for value in (0.1, 0.2, 0.55, 1.0):
        pixels = await tapers.paint(f"size {value:g}", reference, size_px=SIZE * value)
        sizes[value] = None if pixels is None else _widths(pixels, REFERENCE, [0.5])[0]
    alphas = {}
    for value in (0.1, 0.55, 1.0):
        pixels = await tapers.paint(f"opacity {value:g}", reference, opacity=value)
        alphas[value] = None if pixels is None else _alpha(pixels, REFERENCE, [0.5])[0]
    ts = [0, 0.25, 0.5, 0.75, 1]
    ends = {"size": ENDS}
    long = await tapers.paint("ends long", _line(LONG), dynamics=ends)
    curved = await tapers.paint("ends curved", _arc(), "catmull_rom", dynamics=ends)
    short = await tapers.paint("ends short", _line(SHORT, 5), dynamics=ends)
    pinch = await tapers.paint("pinch", _line(LONG), dynamics={"size": PINCH})
    ramp = await tapers.paint("opacity ramp", _line(LONG), dynamics={"opacity": RAMP})
    found: dict[str, Any] = {
        "long": None if long is None else _widths(long, LONG, ts),
        "curved": None if curved is None else _arc_widths(curved, ts),
        "short": None if short is None else _widths(short, SHORT, [0, 0.5, 1]),
        "pinch": None if pinch is None else _widths(pinch, LONG, [0, 0.5, 1]),
        "ramp": None if ramp is None else _alpha(ramp, LONG, [0, 0.5, 1]),
    }
    expected = [sizes.get(round(_value(ENDS, at), 2)) for at in ts]
    followed = all(
        found[kind] is not None
        and all(
            want is not None and _near(got, want)
            for got, want in zip(found[kind], expected, strict=True)
        )
        for kind in ("long", "curved")
    )
    short_widths = found["short"]
    narrows = (
        short_widths is not None and max(short_widths[0], short_widths[2]) <= 0.4 * short_widths[1]
    )
    report.check(
        "a taper's width follows its knots along a long and a curved stroke, and narrows a short "
        "one at both ends",
        followed and narrows,
        f"long {found['long']}, curved {found['curved']}, short {short_widths}, against {expected}",
    )
    pinched = found["pinch"]
    thin, full = sizes[0.2], sizes[1.0]
    report.check(
        "an interior knot pinches a stroke to its value",
        pinched is not None
        and thin is not None
        and full is not None
        and _near(pinched[1], thin)
        and _near(pinched[0], full)
        and _near(pinched[2], full),
        f"{pinched} against {thin} and {full}",
    )
    ramp_alpha = found["ramp"]
    wanted = [alphas[0.1], alphas[0.55], alphas[1.0]]
    report.check(
        "an opacity taper's alpha follows its knots",
        ramp_alpha is not None
        and all(
            want is not None and abs(got - want) <= 10
            for got, want in zip(ramp_alpha, wanted, strict=True)
        ),
        f"{ramp_alpha} against {wanted}",
    )


def _receipts(report: Report, tapers: Tapers) -> None:
    problems = []
    for painted in tapers.receipts:
        content = painted["content"]
        if list(OUTPUT.iter_errors(content)):
            problems.append("schema")
            continue
        taper = content["data"]["effective_brush"]["dynamics"]
        path = strokes.path(painted["points"], painted["smooth"])
        arc = strokes.arc_length(path)
        offset = math.hypot(*path["start"])
        if taper["sensor_length_px"] != math.floor(arc + offset + 0.5):
            problems.append(f"length {taper['sensor_length_px']}")
    report.check(
        "each taper's receipt matches its schema and states the sensor length Krita took",
        len(tapers.receipts) == 5 and not problems,
        f"{len(tapers.receipts)} receipts, {problems}",
    )


async def _refusals(
    report: Report, a: Client, document_id: str, root: str, preset: dict[str, Any]
) -> None:
    listed = await brushes(a) or []
    other = next(
        (
            entry
            for entry in listed
            if entry["engine"] not in (None, "paintbrush") and entry["sha256"]
        ),
        None,
    )
    layer = await add_layer(a, document_id, root, "dynamics refused")
    if other is None or layer is None:
        report.check("a taper's refusals have another engine's preset and a layer", False)
        return
    taper = {"size": ENDS}
    engine = await tool(
        a, TOOL, stroke_args(document_id, layer, brush_args(other), _line(LONG), dynamics=taper)
    )
    masked = brush_args(preset, mask="reveal")
    del masked["color"]
    mask = await tool(a, TOOL, stroke_args(document_id, layer, masked, _line(LONG), dynamics=taper))
    report.check(
        "a taper is refused for another engine's preset, and for mask paint, before anything "
        "changes",
        code(engine) == "UNSUPPORTED_CAPABILITY"
        and ((engine.get("error") or {}).get("details") or {}).get("engine") == other["engine"]
        and ((engine.get("error") or {}).get("details") or {}).get("outcome") == "not_applied"
        and code(mask) == "INVALID_ARGUMENT"
        and mask.get("operation_id") is None,
        f"{other['engine']}: {code(engine)}, mask: {code(mask)}",
    )


async def _leak(
    report: Report,
    a: Client,
    client: BridgeClient,
    tapers: Tapers,
    layers: list[dict[str, Any]],
    before: tuple[str | None, bool | None],
) -> None:
    # Last: protection only tightens.
    allowed = {"x": 0, "y": 0, "width": WIDTH // 2, "height": HEIGHT}
    protected = await protect(tapers.a, tapers.document_id, layers, {"rect": allowed})
    layer = await add_layer(tapers.a, tapers.document_id, tapers.root, "dynamics leak")
    if layer is None or protected.get("status") != "completed":
        report.check("the taper leak's layer and protection are set", False, str(code(protected)))
        return
    brush = brush_args(tapers.preset, size_px=SIZE)
    arguments = stroke_args(tapers.document_id, layer, brush, _line(LONG), dynamics={"size": ENDS})
    leaked = await tool(a, TOOL, arguments)
    details = (leaked.get("error") or {}).get("details") or {}
    pixels = await capture(a, tapers.document_id, WHOLE, "layer", layer)
    after = await _preset_state(a, client, tapers.document_id, tapers.preset)
    report.check(
        "a taper across the allowed mask's edge is rolled back and confirmed, and its preset "
        "comes back as it was",
        code(leaked) == "PROTECTED_REGION_CHANGED"
        and details.get("rollback_verified") is True
        and pixels is not None
        and not pixels[..., 3].any()
        and after == before,
        f"{code(leaked)}, confirmed {details.get('rollback_verified')}, preset {after}",
    )
