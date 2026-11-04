from typing import Any

import pytest
from bridge_core import shapes
from bridge_core.errors import BridgeError


def _refused(shape: Any) -> dict[str, Any]:
    with pytest.raises(BridgeError) as raised:
        shapes.check(shape)
    body: dict[str, Any] = raised.value.body
    return body


def _closed(points: list[list[float]]) -> dict[str, Any]:
    # The server's closed Catmull-Rom, as the bridge receives it.
    count = len(points)
    segments = []
    for i in range(count):
        p0, p1, p2, p3 = points[i - 1], points[i], points[(i + 1) % count], points[(i + 2) % count]
        c1 = [p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6]
        c2 = [p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6]
        segments.append([*c1, *c2, *p2])
    return {"kind": "path", "start": list(points[0]), "segments": segments}


RECT = {"kind": "rect", "rect": {"x": 4, "y": 6, "width": 10, "height": 8}}
TRIANGLE = {"kind": "polygon", "points": [[1.5, 2], [20, 2.25], [10, 15.75]]}


@pytest.mark.parametrize(
    "shape",
    [
        {"kind": "selection"},
        RECT,
        {**RECT, "kind": "ellipse"},
        TRIANGLE,
        _closed([[10, 10], [30, 12], [25, 30]]),
    ],
    ids=["selection", "rect", "ellipse", "polygon", "path"],
)
def test_every_kind_is_taken_as_sent(shape: dict[str, Any]) -> None:
    shapes.check(shape)


@pytest.mark.parametrize(
    "shape",
    [
        None,
        {"kind": "circle"},
        {"kind": "selection", "rect": RECT["rect"]},
        {"kind": "rect", "rect": {"x": 1, "y": 1, "width": 0, "height": 4}},
        {"kind": "rect", "rect": {"x": 1.5, "y": 1, "width": 2, "height": 4}},
        {"kind": "rect", "rect": {"x": 1, "y": 1, "width": 2}},
        {"kind": "polygon", "points": [[0, 0], [1, 1]]},
        {"kind": "polygon", "points": [[0, 0], [1, 1], [2]]},
        {"kind": "polygon", "points": [[0, 0], [1, 1], [2, float("nan")]]},
        {"kind": "polygon", "points": [[0, 0], [1, 0], [0, 1]] * 1366},
        {"kind": "path", "start": [0, 0], "segments": [[1, 1], [2, 0], [0, 2]]},
        {"kind": "path", "start": [0], "segments": [[0, 0, 1, 1, 2, 0]] * 3},
    ],
    ids=[
        "not an object",
        "an unknown kind",
        "a field another kind takes",
        "a rect with no width",
        "a rect off whole pixels",
        "a rect missing a field",
        "two points",
        "a short point",
        "a point not finite",
        "4098 points",
        "line segments in a path",
        "a short start",
    ],
)
def test_a_malformed_shape_is_refused(shape: Any) -> None:
    assert _refused(shape)["code"] == "INVALID_ARGUMENT"


@pytest.mark.parametrize(
    "shape",
    [
        {"kind": "polygon", "points": [[5, 5], [5, 5], [5, 5]]},
        {"kind": "polygon", "points": [[0, 0], [10, 10], [4, 4], [20, 20]]},
        # Collinear points the server's division by 6 leaves a rounding off the line.
        _closed([[0, 0], [3, 1], [6, 2], [9.3, 3.1]]),
    ],
    ids=["one point thrice", "on one line", "a path through one line"],
)
def test_a_shape_with_no_area_is_refused(shape: dict[str, Any]) -> None:
    body = _refused(shape)
    assert (body["code"], body["message"]) == ("INVALID_ARGUMENT", "The shape encloses no area.")


def test_boxes_are_as_drawn() -> None:
    assert shapes.box(RECT) == (4, 6, 14, 14)
    assert shapes.box({**RECT, "kind": "ellipse"}) == (4, 6, 14, 14)
    assert shapes.box(TRIANGLE) == (1.5, 2, 20, 15.75)
    assert shapes.aligned(shapes.box(TRIANGLE)) == {"x": 1, "y": 2, "width": 19, "height": 14}


def test_a_curve_s_box_is_its_extrema_not_its_control_points() -> None:
    # The control points rise to y -2; the curve between them turns at y 1.
    arch = {
        "kind": "path",
        "start": [10, 10],
        "segments": [[20, -2, 30, -2, 40, 10], [40, 20, 10, 20, 10, 10], [10, 10, 10, 10, 10, 10]],
    }
    left, top, right, bottom = shapes.box(arch)
    assert (left, right) == (10, 40) and top == pytest.approx(1.0) and bottom == pytest.approx(17.5)
    assert shapes.on_canvas(arch, [50, 30])[1] == pytest.approx(1.0)


@pytest.mark.parametrize(
    "shape",
    [
        {"kind": "rect", "rect": {"x": 45, "y": 0, "width": 6, "height": 4}},
        {"kind": "ellipse", "rect": {"x": 0, "y": 28, "width": 6, "height": 4}},
        {"kind": "polygon", "points": [[-0.5, 1], [10, 1], [5, 9]]},
        {
            "kind": "path",
            "start": [10, 10],
            "segments": [[20, -8, 30, -8, 40, 10], [40, 20, 10, 20, 10, 10], [10] * 6],
        },
    ],
    ids=["rect", "ellipse", "polygon", "a curve that bulges out"],
)
def test_a_shape_off_the_canvas_is_refused_never_clipped(shape: dict[str, Any]) -> None:
    with pytest.raises(BridgeError) as raised:
        shapes.on_canvas(shape, [50, 30])
    body = raised.value.body
    assert body["code"] == "INVALID_ARGUMENT"
    assert body["details"]["canvas_px"] == [50, 30] and body["details"]["field"] == "shape"
    assert ("bulges" in body["message"]) == (shape["kind"] == "path")


def test_a_shape_on_the_canvas_edge_is_inside() -> None:
    shape = {"kind": "polygon", "points": [[0, 0], [50, 0], [50, 30]]}
    assert shapes.on_canvas(shape, [50, 30]) == (0, 0, 50, 30)
