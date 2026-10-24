import hashlib
import io
import os
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from krita_art_mcp import masks

LIMIT = 8192 * 8192


def test_a_rect_is_exact() -> None:
    mask = masks.rect({"x": 3, "y": 2, "width": 4, "height": 2}, LIMIT)
    assert mask.origin == (3, 2) and mask.pixels.shape == (2, 4)
    assert (mask.pixels == 255).all()


def test_a_polygon_on_pixel_edges_is_the_rect_it_traces() -> None:
    square = masks.polygon([[2, 1], [6, 1], [6, 4], [2, 4]], LIMIT)
    assert square.origin == (2, 1) and square.pixels.shape == (3, 4)
    assert (square.pixels == 255).all()


def test_a_diagonal_edge_splits_its_pixel_by_the_share_of_samples_each_side() -> None:
    # A sample centre on the diagonal counts to the triangle it lies right of, so the two
    # triangles of one pixel share its 16 samples without counting any twice.
    below = masks.polygon([[0, 0], [1, 1], [0, 1]], LIMIT)
    above = masks.polygon([[0, 0], [1, 0], [1, 1]], LIMIT)
    assert below.pixels.tolist() == [[(10 * 255 + 8) // 16]]
    assert above.pixels.tolist() == [[(6 * 255 + 8) // 16]]
    assert below.pixels[0, 0] + above.pixels[0, 0] == 255
    # A binary mask allows a pixel at least half covered.
    assert masks.polygon([[0, 0], [1, 1], [0, 1]], LIMIT, binary=True).pixels.tolist() == [[255]]
    assert masks.polygon([[0, 0], [1, 0], [1, 1]], LIMIT, binary=True).pixels.tolist() == [[0]]


def test_a_polygon_is_filled_even_odd() -> None:
    # A frame drawn as one outline: the hole is outside.
    frame = [[0, 0], [6, 0], [6, 6], [0, 6], [0, 0], [2, 2], [2, 4], [4, 4], [4, 2], [2, 2]]
    mask = masks.polygon(frame, LIMIT)
    assert mask.pixels[0, 0] == 255 and mask.pixels[3, 3] == 0 and mask.pixels[1, 1] == 255


def test_an_ellipse_is_symmetric_with_its_area_and_soft_rim() -> None:
    mask = masks.ellipse({"x": 0, "y": 0, "width": 40, "height": 20}, LIMIT)
    pixels = mask.pixels.astype(float)
    assert np.array_equal(mask.pixels, mask.pixels[::-1, :])
    assert np.array_equal(mask.pixels, mask.pixels[:, ::-1])
    assert abs(pixels.sum() / 255 - np.pi * 20 * 10) < 4
    assert mask.pixels[10, 20] == 255 and mask.pixels[0, 0] == 0
    assert ((mask.pixels > 0) & (mask.pixels < 255)).any()


def _reference(points: list[list[float]], width: int, height: int) -> np.ndarray:
    # Even-odd at each of the 16 sample centres, one sample at a time.
    edges = list(zip(points, points[1:] + points[:1], strict=True))
    out = np.zeros((height, width), dtype=np.uint8)
    for row in range(height):
        for column in range(width):
            count = 0
            for j in range(4):
                for i in range(4):
                    x, y = column + (i + 0.5) / 4, row + (j + 0.5) / 4
                    crossings = 0
                    for (x0, y0), (x1, y1) in edges:
                        if (y0 <= y < y1) or (y1 <= y < y0):
                            if x0 + (y - y0) * (x1 - x0) / (y1 - y0) < x:
                                crossings += 1
                    count += crossings % 2
            out[row, column] = (count * 255 + 8) // 16
    return out


def test_bands_join_without_a_seam() -> None:
    tall = masks.ellipse({"x": 0, "y": 0, "width": 9, "height": 3 * masks.BAND_ROWS + 5}, LIMIT)
    assert np.array_equal(tall.pixels, tall.pixels[::-1, :])
    points: list[list[float]] = [[0, 0], [5, 0], [5, 2.5 * masks.BAND_ROWS], [2.5, 7.25]]
    slanted = masks.polygon(points, LIMIT)
    assert np.array_equal(slanted.pixels, _reference(points, 5, slanted.pixels.shape[0]))


@pytest.mark.parametrize(
    "make",
    [
        lambda: masks.rect({"x": 0, "y": 0, "width": 9000, "height": 9000}, LIMIT),
        lambda: masks.ellipse({"x": 0, "y": 0, "width": 9000, "height": 9000}, LIMIT),
        lambda: masks.polygon([[0, 0], [9000, 0], [0, 9000]], LIMIT),
    ],
)
def test_a_box_over_the_limit_is_refused_before_it_is_drawn(make: object) -> None:
    with pytest.raises(masks.MaskError) as refused:
        make()  # type: ignore[operator]
    assert refused.value.body["code"] == "INVALID_ARGUMENT"


def test_a_polygon_without_area_is_refused() -> None:
    with pytest.raises(masks.MaskError):
        masks.polygon([[1, 0], [1, 5], [1, 9]], LIMIT)


def _png(path: Path, pixels: np.ndarray, mode: str | None = None) -> str:
    image = Image.fromarray(pixels) if mode is None else Image.fromarray(pixels).convert(mode)
    stream = io.BytesIO()
    image.save(stream, "PNG")
    path.write_bytes(stream.getvalue())
    return hashlib.sha256(stream.getvalue()).hexdigest()


def test_a_png_inside_a_root_is_read_by_its_exact_bytes(tmp_path: Path) -> None:
    pixels = np.array([[0, 128], [255, 0]], dtype=np.uint8)
    sha = _png(tmp_path / "mask.png", pixels)
    real = os.path.realpath(tmp_path)
    mask = masks.from_png(str(tmp_path / "mask.png"), sha, [real], LIMIT, False, "mask_uri")
    assert np.array_equal(mask.pixels, pixels) and mask.source == f"{real}/mask.png"


@pytest.mark.parametrize(
    ("case", "code"),
    [
        ("outside", "PATH_NOT_ALLOWED"),
        ("relative", "INVALID_ARGUMENT"),
        ("missing", "IO_ERROR"),
        ("hash", "RESOURCE_HASH_MISMATCH"),
        ("rgba", "INVALID_ARGUMENT"),
        ("not png", "INVALID_ARGUMENT"),
        ("grey for an allowed mask", "INVALID_ARGUMENT"),
    ],
)
def test_a_png_is_refused_unless_it_is_exactly_what_was_named(
    tmp_path: Path, case: str, code: str
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    path = root / "mask.png"
    sha = _png(path, np.array([[0, 128]], dtype=np.uint8))
    binary = False
    uri = str(path)
    if case == "outside":
        uri = str(tmp_path / "elsewhere.png")
        _png(Path(uri), np.zeros((1, 1), dtype=np.uint8))
    elif case == "relative":
        uri = "mask.png"
    elif case == "missing":
        path.unlink()
    elif case == "hash":
        sha = "0" * 64
    elif case == "rgba":
        sha = _png(path, np.zeros((1, 2, 4), dtype=np.uint8))
    elif case == "not png":
        path.write_bytes(b"GIF89a")
        sha = hashlib.sha256(b"GIF89a").hexdigest()
    else:
        binary = True
    with pytest.raises(masks.MaskError) as refused:
        masks.from_png(uri, sha, [os.path.realpath(root)], LIMIT, binary, "mask_uri")
    assert refused.value.body["code"] == code
