import math
from typing import Any

Point = tuple[float, float]
# Below this share of the two edges' lengths, a cross product is rounding, not area; the plugin
# holds the same bound.
COLLINEAR = 1e-9
# Flatness, in pixels, below which a cubic's length is its chord and control polygon's mean; the
# plugin measures the same way.
FLAT_PX = 0.01
MAX_DEPTH = 16


def path(points: list[dict[str, Any]], smooth: str) -> dict[str, Any]:
    # The bridge's path: lines through the points, or uniform Catmull-Rom as exact cubics.
    xy = [(point["x"], point["y"]) for point in points]
    start = xy[0]
    if smooth == "catmull_rom" and len(xy) >= 3:
        return {"start": list(start), "segments": catmull_rom(xy)}
    return {"start": list(start), "segments": [list(point) for point in xy[1:]]}


def closed_catmull_rom(xy: list[Point]) -> dict[str, Any]:
    # A closed curve through every point: as catmull_rom, with each point's neighbours wrapping
    # round, and a last segment back to the start.
    count = len(xy)
    segments = []
    for i in range(count):
        p0, p1, p2, p3 = xy[i - 1], xy[i], xy[(i + 1) % count], xy[(i + 2) % count]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        segments.append([*c1, *c2, *p2])
    return {"start": list(xy[0]), "segments": segments}


def catmull_rom(xy: list[Point]) -> list[list[float]]:
    # Each segment p1 -> p2 is the cubic with c1 = p1 + (p2 - p0)/6 and c2 = p2 - (p3 - p1)/6;
    # the end points stand in for the neighbours they lack.
    last = len(xy) - 1
    segments = []
    for i in range(last):
        p0, p1, p2, p3 = xy[max(i - 1, 0)], xy[i], xy[i + 1], xy[min(i + 2, last)]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        segments.append([*c1, *c2, *p2])
    return segments


def collinear(points: list[list[float]]) -> bool:
    # Whether every point lies on one line through the first, so the shape encloses no area.
    x0, y0 = points[0]
    far = max(points, key=lambda point: math.hypot(point[0] - x0, point[1] - y0))
    ax, ay = far[0] - x0, far[1] - y0
    reach = math.hypot(ax, ay)
    if reach == 0:
        return True
    return all(
        abs(ax * (y - y0) - ay * (x - x0)) <= COLLINEAR * reach * math.hypot(x - x0, y - y0)
        for x, y in points
    )


def arc_length(path: dict[str, Any]) -> float:
    total, (x, y) = 0.0, path["start"]
    for segment in path["segments"]:
        if len(segment) == 2:
            total += math.hypot(segment[0] - x, segment[1] - y)
        else:
            p1, p2, p3 = segment[0:2], segment[2:4], segment[4:6]
            total += _cubic_length((x, y), p1, p2, p3, 0)
        x, y = segment[-2], segment[-1]
    return total


def _cubic_length(p0: Any, p1: Any, p2: Any, p3: Any, depth: int) -> float:
    chord = math.dist(p0, p3)
    polygon = math.dist(p0, p1) + math.dist(p1, p2) + math.dist(p2, p3)
    if polygon - chord <= FLAT_PX or depth >= MAX_DEPTH:
        return float((chord + polygon) / 2)
    a, b, c = _mid(p0, p1), _mid(p1, p2), _mid(p2, p3)
    d, e = _mid(a, b), _mid(b, c)
    f = _mid(d, e)
    return _cubic_length(p0, a, d, f, depth + 1) + _cubic_length(f, e, c, p3, depth + 1)


def _mid(p: Any, q: Any) -> Point:
    return (p[0] + q[0]) / 2, (p[1] + q[1]) / 2
