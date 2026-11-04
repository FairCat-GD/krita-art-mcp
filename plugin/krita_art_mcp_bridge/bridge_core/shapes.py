import math
from typing import Any

from .errors import BridgeError, exact, integer, number

KINDS = ("selection", "rect", "ellipse", "polygon", "path")
MIN_POINTS, MAX_POINTS = 3, 4096
# Below this share of the two edges' lengths, a cross product is rounding, not area.
COLLINEAR = 1e-9

Box = tuple[float, float, float, float]


def check(shape: Any) -> None:
    # A fill's shape, exactly, before the job: the canvas is checked once the job knows it.
    kind = shape.get("kind") if isinstance(shape, dict) else None
    if kind not in KINDS:
        message = f"shape is one of {', '.join(KINDS)}."
        raise BridgeError("INVALID_ARGUMENT", message)
    if kind == "selection":
        exact(shape, {"kind"})
    elif kind in ("rect", "ellipse"):
        exact(shape, {"kind", "rect"})
        _check_rect(shape["rect"])
    elif kind == "polygon":
        exact(shape, {"kind", "points"})
        _check_list(shape["points"], 2, "shape.points holds 3 to 4096 [x, y] points.")
    else:
        exact(shape, {"kind", "start", "segments"})
        start, segments = shape["start"], shape["segments"]
        if not (isinstance(start, list) and len(start) == 2 and all(number(v) for v in start)):
            raise BridgeError("INVALID_ARGUMENT", "shape.start is [x, y].")
        message = "shape.segments holds 3 to 4096 cubics, [c1x, c1y, c2x, c2y, x, y]."
        _check_list(segments, 6, message)
    if kind in ("polygon", "path") and collinear(points(shape)):
        raise BridgeError("INVALID_ARGUMENT", "The shape encloses no area.")


def points(shape: dict[str, Any]) -> list[tuple[float, float]]:
    # Every point the shape is drawn through, a path's control points included.
    if shape["kind"] == "polygon":
        return [(x, y) for x, y in shape["points"]]
    found = [(shape["start"][0], shape["start"][1])]
    for c1x, c1y, c2x, c2y, x, y in shape["segments"]:
        found += [(c1x, c1y), (c2x, c2y), (x, y)]
    return found


def collinear(found: list[tuple[float, float]]) -> bool:
    x0, y0 = found[0]
    far = max(found, key=lambda point: math.hypot(point[0] - x0, point[1] - y0))
    ax, ay = far[0] - x0, far[1] - y0
    reach = math.hypot(ax, ay)
    if reach == 0:
        return True
    return all(
        abs(ax * (y - y0) - ay * (x - x0)) <= COLLINEAR * reach * math.hypot(x - x0, y - y0)
        for x, y in found
    )


def box(shape: dict[str, Any]) -> Box:
    # left, top, right, bottom, as drawn: a path's by its curves' extrema, not its control points.
    if shape["kind"] in ("rect", "ellipse"):
        rect = shape["rect"]
        return rect["x"], rect["y"], rect["x"] + rect["width"], rect["y"] + rect["height"]
    if shape["kind"] == "polygon":
        found = points(shape)
    else:
        found = [(shape["start"][0], shape["start"][1])]
        x0, y0 = shape["start"]
        for c1x, c1y, c2x, c2y, x, y in shape["segments"]:
            found += _extrema((x0, y0), (c1x, c1y), (c2x, c2y), (x, y))
            x0, y0 = x, y
    xs, ys = [x for x, _ in found], [y for _, y in found]
    return min(xs), min(ys), max(xs), max(ys)


def on_canvas(shape: dict[str, Any], size: list[int]) -> Box:
    # Off the canvas is refused, never clipped.
    left, top, right, bottom = drawn = box(shape)
    if left < 0 or top < 0 or right > size[0] or bottom > size[1]:
        details: dict[str, Any] = {
            "field": "shape",
            "bounds_px": aligned(drawn),
            "canvas_px": size,
        }
        message = "The shape reaches outside the canvas; a fill is never clipped."
        if shape["kind"] == "path":
            message += " A curve bulges past its points: move them in."
        raise BridgeError("INVALID_ARGUMENT", message, False, details)
    return drawn


def aligned(drawn: Box) -> dict[str, int]:
    # The whole pixels a box touches.
    left, top = math.floor(drawn[0]), math.floor(drawn[1])
    right, bottom = math.ceil(drawn[2]), math.ceil(drawn[3])
    return {"x": left, "y": top, "width": right - left, "height": bottom - top}


def _check_rect(rect: Any) -> None:
    if (
        not isinstance(rect, dict)
        or set(rect) != {"x", "y", "width", "height"}
        or not all(integer(value) for value in rect.values())
        or rect["width"] < 1
        or rect["height"] < 1
    ):
        raise BridgeError("INVALID_ARGUMENT", "shape.rect is {x, y, width, height}, whole px.")


def _check_list(values: Any, length: int, message: str) -> None:
    if (
        not isinstance(values, list)
        or not MIN_POINTS <= len(values) <= MAX_POINTS
        or not all(
            isinstance(value, list) and len(value) == length and all(number(v) for v in value)
            for value in values
        )
    ):
        raise BridgeError("INVALID_ARGUMENT", message)


def _extrema(
    p0: tuple[float, float],
    c1: tuple[float, float],
    c2: tuple[float, float],
    p3: tuple[float, float],
) -> list[tuple[float, float]]:
    # The cubic's end and every turning point inside it, where an axis' derivative is zero.
    found = [p3]
    for axis in (0, 1):
        d0, d1, d2 = c1[axis] - p0[axis], c2[axis] - c1[axis], p3[axis] - c2[axis]
        a, b, c = d0 - 2 * d1 + d2, 2 * (d1 - d0), d0
        for t in _roots(a, b, c):
            if 0 < t < 1:
                u = 1 - t
                found.append(
                    (
                        u**3 * p0[0] + 3 * u * u * t * c1[0] + 3 * u * t * t * c2[0] + t**3 * p3[0],
                        u**3 * p0[1] + 3 * u * u * t * c1[1] + 3 * u * t * t * c2[1] + t**3 * p3[1],
                    )
                )
    return found


def _roots(a: float, b: float, c: float) -> list[float]:
    # The stable form: the textbook one cancels when a is tiny, and misses a turning point.
    if a == 0:
        return [] if b == 0 else [-c / b]
    disc = b * b - 4 * a * c
    if disc < 0:
        return []
    q = -(b + math.copysign(math.sqrt(disc), b)) / 2
    return [q / a] if q == 0 else [q / a, c / q]
