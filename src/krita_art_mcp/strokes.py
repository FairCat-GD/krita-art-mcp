from typing import Any

Point = tuple[float, float]


def path(points: list[dict[str, Any]], smooth: str) -> dict[str, Any]:
    # The bridge's path: lines through the points, or uniform Catmull-Rom as exact cubics.
    xy = [(point["x"], point["y"]) for point in points]
    start = xy[0]
    if smooth == "catmull_rom" and len(xy) >= 3:
        return {"start": list(start), "segments": catmull_rom(xy)}
    return {"start": list(start), "segments": [list(point) for point in xy[1:]]}


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
