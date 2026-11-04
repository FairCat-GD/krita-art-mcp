import math
from typing import Any

Point = tuple[float, float]
# Below this share of the two edges' lengths, a cross product is rounding, not area; the plugin
# holds the same bound.
COLLINEAR = 1e-9


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
