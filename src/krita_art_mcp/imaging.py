import datetime
import io
import logging
import math
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from krita_art_mcp import colour
from krita_art_mcp.envelope import MAX_RESULT_BYTES
from krita_art_mcp.transfer import Pixels

FILTERS = {
    "nearest": Image.Resampling.NEAREST,
    "box": Image.Resampling.BOX,
    "bilinear": Image.Resampling.BILINEAR,
    "bicubic": Image.Resampling.BICUBIC,
    "lanczos": Image.Resampling.LANCZOS,
}
DEFAULT_MAX_PX = 1600
PREVIEW_PX = 1600
CHECKER_CELL = 8
CHECKER = ((255, 255, 255), (204, 204, 204))
RETENTION_DAYS = 7
# A PNG this size still fits one result once base64 grows it by a third (C5).
INLINE_BYTES = (MAX_RESULT_BYTES - 64 * 1024) * 3 // 4
OPERATION_ID = re.compile(r"^op-[0-9a-f]{32}$")
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")

log = logging.getLogger(__name__)


class GeometryError(Exception):
    pass


@dataclass(frozen=True)
class Render:
    # How the crop becomes an image; the plugin echoes it, so a receipt needs nothing else.
    scale: float
    filter: str
    background: Any
    greyscale: bool
    max_px: int


def output_size(width: int, height: int, scale: float, max_px: int) -> tuple[int, int]:
    # Compared before converting, so no scale can overflow; nothing is clamped.
    if not math.isfinite(scale):
        raise GeometryError("scale is a finite number.")
    if max(width, height) * scale + 0.5 >= max_px + 1:
        message = (
            f"The image would be over max_px ({max_px} px) on its long edge; lower the scale, "
            "raise max_px (4096 at most), or capture tiles."
        )
        raise GeometryError(message)
    size = (colour.half_up(width * scale), colour.half_up(height * scale))
    if min(size) < 1:
        raise GeometryError("The image would be under 1 px on a side; raise the scale.")
    return size


def transform(rect: dict[str, int], size: tuple[int, int]) -> list[int | float]:
    # Document to image after rounding: the effective scale on each axis, then the offset.
    sx, sy = size[0] / rect["width"], size[1] / rect["height"]
    values = [sx, 0.0, -sx * rect["x"], 0.0, sy, -sy * rect["y"]]
    # Exact: whole numbers as integers, the rest unrounded.
    return [int(value) if value.is_integer() else value for value in values]


def render(pixels: Pixels, size: tuple[int, int], how: Render) -> tuple[Image.Image, str | None]:
    # The image and the filter actually applied. Resampled first (Pillow premultiplies RGBA),
    # then put on a background drawn at output size, so a checker stays visible at any scale.
    image = Image.fromarray(
        np.ascontiguousarray(pixels[..., 0] if pixels.shape[2] == 1 else pixels)
    )
    applied = filter_for(image.size, size, how)
    if applied is not None:
        image = image.resize(size, FILTERS[applied])
    backed = how.background not in (None, "transparent")
    if backed:
        image = Image.alpha_composite(_background(how.background, size), image)
    if how.greyscale:
        image = _greyscale(np.asarray(image))
    elif backed and image.getchannel("A").getextrema() == (255, 255):
        image = image.convert("RGB")
    return image, applied


def _background(background: Any, size: tuple[int, int]) -> Image.Image:
    if background == "checker":
        ys, xs = np.indices((size[1], size[0]))
        cells = ((xs // CHECKER_CELL + ys // CHECKER_CELL) % 2).astype(bool)
        pixels = np.where(cells[..., None], CHECKER[1], CHECKER[0]).astype(np.uint8)
        alpha = np.full((size[1], size[0], 1), 255, dtype=np.uint8)
        return Image.fromarray(np.concatenate([pixels, alpha], axis=-1))
    rgba = tuple(colour.half_up(channel * 255) for channel in background["rgba"])
    return Image.new("RGBA", size, rgba)


def _greyscale(pixels: Pixels) -> Image.Image:
    # CIE L*, so a grey value reads back as a sample's L* (value = L* x 2.55); alpha is kept.
    lightness = colour.lab(pixels[..., :3])[..., 0]
    grey = np.clip(np.floor(lightness * 255 / 100 + 0.5), 0, 255).astype(np.uint8)
    if pixels.shape[2] == 4 and (pixels[..., 3] != 255).any():
        return Image.fromarray(np.stack([grey, pixels[..., 3]], axis=-1))
    return Image.fromarray(grey)


def encode(image: Image.Image) -> bytes:
    stream = io.BytesIO()
    image.save(stream, "PNG")
    return stream.getvalue()


def preview(
    pixels: Pixels, rect: dict[str, int], size: tuple[int, int], how: Render
) -> tuple[bytes, tuple[int, int], str | None]:
    # Rendered from the native crop each time, never from a resampled image, and halved
    # until it fits inline.
    edge = PREVIEW_PX if max(size) > PREVIEW_PX else max(size) // 2
    while edge >= 1:
        factor = edge / max(rect["width"], rect["height"])
        small = (
            max(1, colour.half_up(rect["width"] * factor)),
            max(1, colour.half_up(rect["height"] * factor)),
        )
        image, applied = render(pixels, small, how)
        data = encode(image)
        if len(data) <= INLINE_BYTES:
            return data, small, applied
        edge //= 2
    raise GeometryError("No preview of this image fits inline.")


def find(captures: Path, operation_id: str, suffix: str) -> Path | None:
    if not captures.is_dir():
        return None
    for folder in sorted(captures.iterdir()):
        candidate = folder / f"{operation_id}{suffix}"
        if DAY.match(folder.name) and candidate.is_file():
            return candidate
    return None


def folder_for(captures: Path, today: datetime.date) -> Path:
    return captures / today.isoformat()


def write(target: Path, data: bytes) -> None:
    # Whole or not at all, private, and never over another file's name mid-write. mkdir gives
    # its mode to the last folder only, so captures/ and its day folder are made one by one.
    captures = target.parent.parent
    captures.parent.mkdir(parents=True, exist_ok=True)
    for folder in (captures, target.parent):
        folder.mkdir(mode=0o700, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=target.parent, prefix=".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        os.replace(temp, target)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise


def sweep(captures: Path, today: datetime.date) -> None:
    # Captures are kept 7 days; this never fails the capture that triggers it.
    oldest = today - datetime.timedelta(days=RETENTION_DAYS)
    try:
        folders = list(captures.iterdir())
    except OSError:
        log.exception("old captures were not swept")
        return
    for folder in folders:
        # One folder that only looks like a date never keeps the others.
        try:
            if DAY.match(folder.name) and datetime.date.fromisoformat(folder.name) < oldest:
                shutil.rmtree(folder, ignore_errors=True)
        except ValueError:
            log.warning("%s is not a date; it was left alone", folder.name)


def size_of(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        width, height = image.size
    return width, height


def filter_for(native: tuple[int, int], size: tuple[int, int], how: Render) -> str | None:
    # The filter render() applies, and receipts report: none when the size does not change.
    return None if size == native else how.filter
