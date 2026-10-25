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


@pytest.mark.parametrize("smooth", ["none", "catmull_rom"])
def test_one_point_is_a_zero_length_line(smooth: str) -> None:
    assert strokes.path(_points((4.5, 5.5)), smooth) == {
        "start": [4.5, 5.5],
        "segments": [[4.5, 5.5]],
    }
