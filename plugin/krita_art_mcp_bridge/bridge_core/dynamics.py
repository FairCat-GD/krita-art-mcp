import itertools
import math
import xml.etree.ElementTree as ElementTree
from typing import Any

from .errors import BridgeError, exact, number

# A stroke's size and opacity along its arc length, through Krita's Distance sensor (K51).
OPTIONS = (("size", "Size"), ("opacity", "Opacity"))
KNOT_FIELDS = {"at", "value"}
MIN_KNOTS, MAX_KNOTS = 2, 16
# Knots closer than this along the stroke would sit on one point of Krita's curve.
MIN_GAP = 0.001
# The sensor's length is a whole number of pixels (K51), so a shorter stroke has no curve.
MIN_LENGTH_PX = 1.0
# Flatness, in pixels, below which a cubic's length is its chord and control polygon's mean.
FLAT_PX = 0.01
MAX_DEPTH = 16
DISTANCE = "distance"


def check(dynamics: Any, brush: dict[str, Any], path: dict[str, Any]) -> None:
    # The server holds the same rules.
    if dynamics is None:
        return
    if not isinstance(dynamics, dict):
        _refuse("dynamics is an object or null.", "dynamics")
    exact(dynamics, {key for key, _ in OPTIONS})
    if all(dynamics[key] is None for key, _ in OPTIONS):
        _refuse("dynamics names size, opacity or both.", "dynamics")
    for key, _ in OPTIONS:
        if dynamics[key] is not None:
            _check_knots(dynamics[key], f"dynamics.{key}")
    if brush["preset_sha256"] is None:
        message = "dynamics edits the preset for one stroke, so it needs brush.preset_sha256."
        _refuse(message, "brush.preset_sha256")
    if brush["mask"] is not None:
        _refuse("dynamics paints colour on a paint layer, never mask paint.", "dynamics")
    if arc_length(path) < MIN_LENGTH_PX:
        _refuse(f"dynamics needs a stroke at least {MIN_LENGTH_PX:g} px long.", "dynamics")


def _check_knots(knots: Any, field: str) -> None:
    if not isinstance(knots, list) or not MIN_KNOTS <= len(knots) <= MAX_KNOTS:
        _refuse(f"{field} holds {MIN_KNOTS} to {MAX_KNOTS} knots.", field)
    for knot in knots:
        if not isinstance(knot, dict) or set(knot) != KNOT_FIELDS:
            _refuse(f"Each knot of {field} is {{at, value}}.", field)
        if not all(number(knot[key]) and 0 <= knot[key] <= 1 for key in KNOT_FIELDS):
            _refuse(f"A knot's at and value are 0 to 1, in {field}.", field)
    at = [knot["at"] for knot in knots]
    if at[0] != 0 or at[-1] != 1:
        _refuse(f"{field} starts at 0 and ends at 1.", field)
    if any(later - earlier < MIN_GAP for earlier, later in itertools.pairwise(at)):
        _refuse(f"{field}'s at values rise by at least {MIN_GAP:g} from knot to knot.", field)


def _refuse(message: str, field: str) -> None:
    raise BridgeError("INVALID_ARGUMENT", message, False, {"field": field})


def arc_length(path: dict[str, Any]) -> float:
    total, (x, y) = 0.0, path["start"]
    for segment in path["segments"]:
        if len(segment) == 2:
            total += math.hypot(segment[0] - x, segment[1] - y)
        else:
            total += _cubic((x, y), segment[0:2], segment[2:4], segment[4:6], 0)
        x, y = segment[-2], segment[-1]
    return total


def _cubic(p0: Any, p1: Any, p2: Any, p3: Any, depth: int) -> float:
    chord = math.dist(p0, p3)
    polygon = math.dist(p0, p1) + math.dist(p1, p2) + math.dist(p2, p3)
    if polygon - chord <= FLAT_PX or depth >= MAX_DEPTH:
        return (chord + polygon) / 2
    a, b, c = _mid(p0, p1), _mid(p1, p2), _mid(p2, p3)
    d, e = _mid(a, b), _mid(b, c)
    f = _mid(d, e)
    return _cubic(p0, a, d, f, depth + 1) + _cubic(f, e, c, p3, depth + 1)


def _mid(p: Any, q: Any) -> tuple[float, float]:
    return (p[0] + q[0]) / 2, (p[1] + q[1]) / 2


def origin_offset(path: dict[str, Any]) -> float:
    # A scripted stroke's Distance sensor counts the first dab's distance from the canvas
    # origin (K51), so every later dab reads that much further along.
    return math.hypot(path["start"][0], path["start"][1])


def sensor_length(arc: float, offset: float) -> int:
    return math.floor(arc + offset + 0.5)


def curve(knots: list[dict[str, Any]], arc: float, offset: float, length: int) -> str:
    # Krita's curve over the sensor's reading, every point a corner, so values run straight
    # between knots; the first dab reads 0 and takes the first knot's value.
    points = [(min(1.0, (knot["at"] * arc + offset) / length), knot["value"]) for knot in knots]
    if points[0][0] > 0:
        points.insert(0, (0.0, knots[0]["value"]))
    return "".join(f"{_number(x)},{_number(y)},is_corner;" for x, y in points)


def _number(value: float) -> str:
    return format(value, ".10g")


def sensor(knots: list[dict[str, Any]], arc: float, offset: float, length: int) -> str:
    return (
        f'<!DOCTYPE params>\n<params id="{DISTANCE}" periodic="0" length="{length}">'
        f"<curve>{curve(knots, arc, offset, length)}</curve></params>\n"
    )


def edited(xml: str, dynamics: dict[str, Any], path: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    # The preset's XML with each asked option driven by the Distance sensor alone, and what
    # the receipt says of it. Only the options' own params change: never the tip, ratio or
    # scatter, so no dab grows past size_px.
    arc, offset = arc_length(path), origin_offset(path)
    length = sensor_length(arc, offset)
    root = ElementTree.fromstring(xml)
    replaced: dict[str, list[str] | None] = {}
    raised = None
    for key, option in OPTIONS:
        knots = dynamics[key]
        if knots is None:
            replaced[key] = None
            continue
        replaced[key] = _sensors(root, option)
        _set(root, f"{option}Sensor", sensor(knots, arc, offset, length))
        _set(root, f"Pressure{option}", "true")
        _set(root, f"{option}UseCurve", "true")
        _set(root, f"{option}UseSameCurve", "false")
        if key == "size":
            strength = _float(_param(root, "SizeValue"))
            if strength is not None and strength < 1:
                raised = strength
            _set(root, "SizeValue", "1")
    applied = {
        "arc_length_px": arc,
        "origin_offset_px": offset,
        "sensor_length_px": length,
        "size": dynamics["size"],
        "opacity": dynamics["opacity"],
        "replaced": replaced,
        "raised_size_strength": raised,
    }
    return ElementTree.tostring(root, encoding="unicode"), applied


def took(xml: str, dynamics: dict[str, Any], path: dict[str, Any]) -> list[str]:
    # The options whose sensor Krita did not take as written.
    arc, offset = arc_length(path), origin_offset(path)
    length = sensor_length(arc, offset)
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError:
        return [key for key, _ in OPTIONS if dynamics[key] is not None]
    wrong = []
    for key, option in OPTIONS:
        knots = dynamics[key]
        if knots is None:
            continue
        held = _sensor(_param(root, f"{option}Sensor"))
        wanted = (DISTANCE, str(length), curve(knots, arc, offset, length))
        if (
            held != wanted
            or _param(root, f"{option}UseSameCurve") != "false"
            or _param(root, f"{option}UseCurve") != "true"
        ):
            wrong.append(key)
    return wrong


def _sensors(root: Any, option: str) -> list[str]:
    # The sensors the option drove the dab with: none when it was off or ignored its curve.
    if _param(root, f"Pressure{option}") == "false" or _param(root, f"{option}UseCurve") != "true":
        return []
    text = _param(root, f"{option}Sensor")
    try:
        element = ElementTree.fromstring(text or "")
    except ElementTree.ParseError:
        return []
    if element.get("id") == "sensorslist":
        return [child.get("id") or "" for child in element.findall("ChildSensor")]
    return [element.get("id") or ""]


def _sensor(text: str | None) -> tuple[str | None, str | None, str] | None:
    try:
        element = ElementTree.fromstring(text or "")
    except ElementTree.ParseError:
        return None
    return element.get("id"), element.get("length"), element.findtext("curve") or ""


def _param(root: Any, name: str) -> str | None:
    found = next((param for param in root.findall("param") if param.get("name") == name), None)
    return None if found is None else (found.text or "")


def _set(root: Any, name: str, value: str) -> None:
    found = next((param for param in root.findall("param") if param.get("name") == name), None)
    if found is None:
        found = ElementTree.SubElement(root, "param", {"name": name, "type": "string"})
    found.text = value


def _float(text: str | None) -> float | None:
    try:
        return None if text is None else float(text)
    except ValueError:
        return None
