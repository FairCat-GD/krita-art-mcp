import json
import math

import numpy as np
import pytest

from krita_art_mcp import colour

# sRGB to CIE L*a*b* (D65), tolerance 0.05.
FIXTURES = [
    ((255, 255, 255), (100.00, 0.00, 0.00)),
    ((128, 128, 128), (53.59, 0.00, 0.00)),
    ((255, 0, 0), (53.24, 80.09, 67.20)),
    ((167, 194, 132), (75.12, -19.96, 28.26)),
]


@pytest.mark.parametrize(("rgb", "expected"), FIXTURES)
def test_the_colour_fixtures_convert_within_tolerance(
    rgb: tuple[int, int, int], expected: tuple[float, float, float]
) -> None:
    found = colour.lab(rgb)
    assert np.abs(found - np.array(expected)).max() <= 0.05, found


def test_the_fixture_green_has_chroma_34_6() -> None:
    chroma = colour.lch(colour.lab((167, 194, 132)))[1]
    assert abs(chroma - 34.6) <= 0.05


def test_hue_runs_from_0_to_360_degrees() -> None:
    assert colour.lch(colour.lab((255, 0, 0)))[2] == pytest.approx(40.0, abs=0.05)
    # b* is negative here, so atan2 alone would give a negative angle.
    assert colour.lch(colour.lab((10, 120, 220)))[2] == pytest.approx(280.12, abs=0.05)


def test_hex_is_uppercase_and_rounds_half_up() -> None:
    assert colour.hex_of([167, 194, 132]) == "#A7C284"
    # 126.5 becomes 127, where Python's round() gives 126.
    assert colour.hex_of([126.5, 0.4999, 254.5]) == "#7F00FF"


def _square(rgba: tuple[int, int, int, int], size: int) -> np.ndarray:
    square = np.zeros((size, size, 4), dtype=np.uint8)
    square[...] = rgba
    return square


def test_radius_0_gives_the_stored_integers() -> None:
    found = colour.disc(_square((167, 194, 132, 255), 1), (5, 6), (5, 6), 0, True)
    assert found["pixel_count"] == 1
    assert found["rgba"] == [167, 194, 132, 255]
    assert all(isinstance(value, int) for value in found["rgba"])
    assert found["hex"] == "#A7C284"
    assert found["stdev_l"] == 0
    assert abs(found["lch"][1] - 34.6) <= 0.05


def test_a_disc_counts_the_pixels_within_the_radius() -> None:
    found = colour.disc(_square((10, 120, 220, 255), 7), (27, 41), (30, 44), 3, True)
    # Offsets with dx² + dy² ≤ 9.
    assert found["pixel_count"] == 29
    assert found["rgba"] == [10, 120, 220, 255]
    assert found["stdev_l"] == 0


def test_a_disc_mean_is_weighted_by_alpha() -> None:
    square = np.zeros((1, 3, 4), dtype=np.uint8)
    square[0, 0] = (200, 0, 0, 255)
    square[0, 1] = (0, 0, 200, 51)
    square[0, 2] = (90, 90, 90, 0)
    found = colour.disc(square, (0, 0), (1, 0), 1, True)
    assert found["pixel_count"] == 3
    # The transparent pixel's colour does not count; its alpha does.
    weight = 255 + 51
    assert found["rgba"][0] == pytest.approx(round(200 * 255 / weight, 4))
    assert found["rgba"][2] == pytest.approx(round(200 * 51 / weight, 4))
    assert found["rgba"][3] == pytest.approx(round(306 / 3, 4))
    lightness = colour.lab(np.array([[200, 0, 0], [0, 0, 200]]))[:, 0]
    centre = (lightness[0] * 255 + lightness[1] * 51) / weight
    spread = math.sqrt(
        (255 * (lightness[0] - centre) ** 2 + 51 * (lightness[1] - centre) ** 2) / weight
    )
    assert found["stdev_l"] == pytest.approx(round(spread, 4))


def test_a_disc_at_the_edge_holds_only_the_canvas() -> None:
    # The square was read clipped to the canvas, so the disc is too.
    found = colour.disc(_square((1, 2, 3, 255), 3), (0, 45), (0, 47), 2, True)
    assert found["pixel_count"] == 6


def test_a_fully_transparent_disc_has_no_colour_and_no_nan() -> None:
    found = colour.disc(_square((40, 50, 60, 0), 3), (0, 0), (1, 1), 1, True)
    assert found["rgba"] == [40, 50, 60, 0]
    assert (found["hex"], found["lab"], found["lch"], found["stdev_l"]) == (None,) * 4
    one = colour.disc(_square((40, 50, 60, 0), 1), (0, 0), (0, 0), 0, True)
    assert one["rgba"] == [40, 50, 60, 0] and one["lab"] is None
    json.dumps(found, allow_nan=False)


def test_a_grey_has_no_hue_and_no_negative_zero() -> None:
    found = colour.disc(_square((128, 128, 128, 255), 1), (0, 0), (0, 0), 0, True)
    assert found["lch"][1:] == [0, 0]
    assert "-0" not in json.dumps(found)


def test_outside_srgb_there_is_no_colour_maths_but_the_bytes_and_hex_stay() -> None:
    found = colour.disc(_square((167, 194, 132, 255), 1), (0, 0), (0, 0), 0, False)
    assert found["rgba"] == [167, 194, 132, 255] and found["hex"] == "#A7C284"
    assert (found["lab"], found["lch"], found["stdev_l"]) == (None, None, None)
