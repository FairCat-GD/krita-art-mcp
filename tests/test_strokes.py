import pytest

from krita_art_mcp import strokes


def _points(*xy: tuple[float, float]) -> list[dict[str, float]]:
    return [{"x": x, "y": y} for x, y in xy]


def test_catmull_rom_is_exact_cubics_through_every_point() -> None:
    # Multiples of 6 keep every sixth exact, so the controls compare with ==.
    path = strokes.path(_points((0, 0), (6, 12), (18, 6), (24, 24)), "catmull_rom")
    assert path == {
        "start": [0, 0],
        "segments": [
            [1, 2, 3, 11, 6, 12],
            [9, 13, 15, 4, 18, 6],
            [21, 8, 23, 21, 24, 24],
        ],
    }


def test_the_cubics_share_a_tangent_at_each_inner_point() -> None:
    path = strokes.path(_points((0, 0), (6, 12), (18, 6), (24, 24)), "catmull_rom")
    for before, after in zip(path["segments"], path["segments"][1:], strict=False):
        joint = before[4:6]
        assert [joint[k] - before[2 + k] for k in (0, 1)] == [after[k] - joint[k] for k in (0, 1)]


def test_smooth_none_draws_lines() -> None:
    path = strokes.path(_points((0, 0), (6, 12), (18, 6)), "none")
    assert path == {"start": [0, 0], "segments": [[6, 12], [18, 6]]}


def test_two_points_draw_a_line_even_when_smoothed() -> None:
    path = strokes.path(_points((1.5, 2.5), (7.5, 3.5)), "catmull_rom")
    assert path == {"start": [1.5, 2.5], "segments": [[7.5, 3.5]]}


def test_a_closed_curve_passes_through_every_point_and_closes() -> None:
    # Each point's neighbours wrap round: the first segment's lead-in is the last point.
    points = [(0.0, 0.0), (12.0, 6.0), (6.0, 18.0)]
    path = strokes.closed_catmull_rom(points)
    assert path == {
        "start": [0.0, 0.0],
        "segments": [
            [1.0, -2.0, 11.0, 3.0, 12.0, 6.0],
            [13.0, 9.0, 8.0, 19.0, 6.0, 18.0],
            [4.0, 17.0, -1.0, 2.0, 0.0, 0.0],
        ],
    }


def test_a_closed_curve_is_smooth_at_every_point_the_start_included() -> None:
    path = strokes.closed_catmull_rom([(0.0, 0.0), (12.0, 6.0), (6.0, 18.0), (-6.0, 12.0)])
    segments = path["segments"]
    for before, after in zip(segments, segments[1:] + segments[:1], strict=True):
        joint = before[4:6]
        assert [joint[k] - before[2 + k] for k in (0, 1)] == [after[k] - joint[k] for k in (0, 1)]


@pytest.mark.parametrize(
    ("points", "flat"),
    [
        ([[0, 0], [10, 10], [4, 4]], True),
        ([[5, 5], [5, 5], [5, 5]], True),
        ([[0, 0], [3, 1], [6, 2], [9.3, 3.1]], True),
        ([[0, 0], [10, 0], [10, 0.5]], False),
    ],
    ids=["on one line", "one point", "on one line, inexact", "a thin triangle"],
)
def test_collinear_points_enclose_no_area(points: list[list[float]], flat: bool) -> None:
    assert strokes.collinear(points) is flat
