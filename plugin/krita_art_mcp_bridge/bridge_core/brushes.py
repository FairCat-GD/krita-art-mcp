import math
import xml.etree.ElementTree as ElementTree
from typing import Any

ENGINE = "paintbrush"
ROUND = "round"
SQUARE = "square"
IMAGE = "image"
# How far past the path a dab reaches, in brush sizes, before scatter: rotation carries a square
# or an image tip's corner out to half its diagonal.
EXTENT = {ROUND: 0.5, SQUARE: math.sqrt(2) / 2, IMAGE: math.sqrt(2) / 2}
MIN_MARGIN_PX = 32
# Scatter strength runs 0 to 5 (K44).
MAX_SCATTER = 5.0
# The reasons a region stroke is refused when the reach cannot be named.
NO_ENGINE = "brush_engine"
NO_TIP = "brush_tip"
NO_SCATTER = "brush_scatter"


def brush_reach(xml: str) -> dict[str, Any]:
    # {engine, tip, spacing, scatter, reasons}: what bounds a stroke of this preset, read from
    # its XML; anything that cannot be named is None, with its reason listed.
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError:
        return _reach(None, None, None, None)
    params = {param.get("name"): param.text or "" for param in root.iter("param")}
    tip, spacing = _tip(params.get("brush_definition"))
    return _reach(root.get("paintopid") or None, tip, spacing, _scatter(params))


def margin_px(size: float, tip: str, scatter: float) -> float:
    return max(float(MIN_MARGIN_PX), size * (EXTENT[tip] + scatter))


def _reach(
    engine: str | None, tip: str | None, spacing: float | None, scatter: float | None
) -> dict[str, Any]:
    reasons = []
    if engine != ENGINE:
        reasons.append(NO_ENGINE)
    if tip is None:
        reasons.append(NO_TIP)
    if scatter is None:
        reasons.append(NO_SCATTER)
    return {
        "engine": engine,
        "tip": tip,
        "spacing": spacing,
        "scatter": scatter,
        "reasons": reasons,
    }


def _tip(definition: str | None) -> tuple[str | None, float | None]:
    # An auto brush with a circle mask is round, with a rect mask square; any other type is an
    # image.
    if not definition:
        return None, None
    try:
        brush = ElementTree.fromstring(definition)
    except ElementTree.ParseError:
        return None, None
    spacing = _number(brush.get("spacing"))
    kind = brush.get("type")
    if not kind:
        return None, spacing
    if kind != "auto_brush":
        return IMAGE, spacing
    mask = brush.find("MaskGenerator")
    shape = None if mask is None else mask.get("type")
    return {"circle": ROUND, "rect": SQUARE}.get(shape or ""), spacing


def _scatter(params: dict[Any, str]) -> float | None:
    # Scatter counts only when the option is on with an axis on (K44); a key missing is unknown.
    enabled = _flag(params.get("PressureScatter"))
    if enabled is False:
        return 0.0
    strength = _number(params.get("ScatterValue"))
    axes = [_flag(params.get(key)) for key in ("Scattering/AxisX", "Scattering/AxisY")]
    if enabled is None or strength is None or None in axes or not 0 <= strength <= MAX_SCATTER:
        return None
    return strength if True in axes else 0.0


def _flag(value: str | None) -> bool | None:
    return {"true": True, "1": True, "false": False, "0": False}.get((value or "").strip().lower())


def _number(value: str | None) -> float | None:
    try:
        number = float(value or "")
    except ValueError:
        return None
    return number if math.isfinite(number) else None
