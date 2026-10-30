import hashlib
import io
import math
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from krita_art_mcp import roots
from krita_art_mcp.errors import error_body
from krita_art_mcp.transfer import Pixels

# Each pixel is sampled at 4 x 4 sub-pixel centres (4x supersampling).
SUB = 4
SAMPLES = SUB * SUB
# Rows rasterised at once, so a box of 8192 columns never holds more than a band in memory.
BAND_ROWS = 64

Inside = Callable[[NDArray[np.float64], NDArray[np.float64]], NDArray[np.bool_]]


class MaskError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.body = error_body(code, message, details=details)


class Mask:
    # Values over a box of the canvas, the box's top-left being origin.
    def __init__(self, pixels: Pixels, origin: tuple[int, int], source: str | None = None) -> None:
        self.pixels = pixels
        self.origin = origin
        # The realpath of the PNG it came from, which the plugin checks against the roots too.
        self.source = source


def rect(box: dict[str, int], limit: int) -> Mask:
    _bounded(box["width"], box["height"], limit)
    pixels = np.full((box["height"], box["width"]), 255, dtype=np.uint8)
    return Mask(pixels, (box["x"], box["y"]))


def ellipse(box: dict[str, int], limit: int) -> Mask:
    _bounded(box["width"], box["height"], limit)
    cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    rx, ry = box["width"] / 2, box["height"] / 2

    def inside(xs: NDArray[np.float64], ys: NDArray[np.float64]) -> NDArray[np.bool_]:
        within: NDArray[np.bool_] = ((xs[None, :] - cx) / rx) ** 2 + (
            (ys[:, None] - cy) / ry
        ) ** 2 <= 1
        return within

    counts = _coverage(box["x"], box["y"], box["width"], box["height"], inside)
    return Mask(_values(counts, False), (box["x"], box["y"]))


def polygon(points: Sequence[Sequence[float]], limit: int, binary: bool = False) -> Mask:
    # Even-odd: a sample is inside when a ray to its left crosses the outline an odd number of
    # times. Edges are half-open in y, so a vertex is never counted twice.
    xs = np.array([point[0] for point in points], dtype=np.float64)
    ys = np.array([point[1] for point in points], dtype=np.float64)
    left, top = math.floor(xs.min()), math.floor(ys.min())
    width, height = math.ceil(xs.max()) - left, math.ceil(ys.max()) - top
    if width < 1 or height < 1:
        raise MaskError("INVALID_ARGUMENT", "The polygon encloses no area.")
    _bounded(width, height, limit)
    x0, y0, x1, y1 = xs, ys, np.roll(xs, -1), np.roll(ys, -1)
    sloped = y0 != y1
    x0, y0, x1, y1 = x0[sloped], y0[sloped], x1[sloped], y1[sloped]
    counts = np.zeros((height, width), dtype=np.uint8)
    columns = width * SUB
    for band in range(0, height, BAND_ROWS):
        rows = min(BAND_ROWS, height - band)
        centres = top + band + (np.arange(rows * SUB) + 0.5) / SUB
        crossing = ((y0 <= centres[:, None]) & (centres[:, None] < y1)) | (
            (y1 <= centres[:, None]) & (centres[:, None] < y0)
        )
        row, edge = np.nonzero(crossing)
        at = x0[edge] + (centres[row] - y0[edge]) * (x1[edge] - x0[edge]) / (y1[edge] - y0[edge])
        # Samples from this column on lie to the right of the crossing.
        start = np.clip(np.floor((at - left) * SUB - 0.5).astype(np.int64) + 1, 0, columns)
        toggles = np.zeros((rows * SUB, columns + 1), dtype=np.uint8)
        np.add.at(toggles, (row, start), 1)
        inside = np.bitwise_xor.accumulate(toggles[:, :columns] & 1, axis=1).astype(bool)
        counts[band : band + rows] = inside.reshape(rows, SUB, width, SUB).sum(axis=(1, 3))
    return Mask(_values(counts, binary), (left, top))


def from_png(
    uri: str, sha256: str, allowed: list[str], limit: int, binary: bool, field: str
) -> Mask:
    # An agent's 8-bit single-channel PNG inside a root, by its exact bytes (invariant 3).
    real = roots.resolve(uri)
    if real is None:
        raise MaskError("INVALID_ARGUMENT", f"{field} must be an absolute path.", {"field": field})
    if not roots.inside(real, allowed):
        raise MaskError(
            "PATH_NOT_ALLOWED", f"{field} is outside every allowed root.", {"field": field}
        )
    try:
        data = Path(real).read_bytes()
    except OSError as problem:
        raise MaskError(
            "IO_ERROR", f"{field} cannot be read: {problem}", {"field": field}
        ) from None
    if hashlib.sha256(data).hexdigest() != sha256:
        details: dict[str, Any] = {"field": field, "sha256": sha256}
        raise MaskError("RESOURCE_HASH_MISMATCH", f"{field} differs from its SHA-256.", details)
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format != "PNG" or image.mode != "L":
                details = {"field": field, "format": image.format, "mode": image.mode}
                message = f"{field} must be an 8-bit single-channel (mode L) PNG."
                raise MaskError("INVALID_ARGUMENT", message, details)
            _bounded(image.width, image.height, limit)
            pixels = np.array(image, dtype=np.uint8)
    except (OSError, Image.DecompressionBombError, ValueError):
        raise MaskError(
            "INVALID_ARGUMENT", f"{field} is not a readable PNG.", {"field": field}
        ) from None
    if binary and np.any((pixels != 0) & (pixels != 255)):
        raise MaskError("INVALID_ARGUMENT", f"{field} must hold only 0 and 255.", {"field": field})
    return Mask(pixels, (0, 0), real)


def _bounded(width: int, height: int, limit: int) -> None:
    # Before anything is allocated: the server does not know the canvas, the plugin does.
    if width * height > limit:
        details = {"pixels": width * height, "limit": limit}
        message = f"The mask covers {width * height} px, over capture_source_pixels ({limit})."
        raise MaskError("INVALID_ARGUMENT", message, details)


def _coverage(left: float, top: float, width: int, height: int, inside: Inside) -> Pixels:
    counts = np.zeros((height, width), dtype=np.uint8)
    xs = left + (np.arange(width * SUB) + 0.5) / SUB
    for band in range(0, height, BAND_ROWS):
        rows = min(BAND_ROWS, height - band)
        ys = top + band + (np.arange(rows * SUB) + 0.5) / SUB
        hits = inside(xs, ys)
        counts[band : band + rows] = hits.reshape(rows, SUB, width, SUB).sum(axis=(1, 3))
    return counts


def _values(counts: Pixels, binary: bool) -> Pixels:
    # Antialiased by the share of samples inside, rounded half up; a binary mask allows a pixel
    # at least half covered.
    if binary:
        return np.where(counts * 2 >= SAMPLES, 255, 0).astype(np.uint8)
    values: Pixels = ((counts.astype(np.uint16) * 255 + SAMPLES // 2) // SAMPLES).astype(np.uint8)
    return values
