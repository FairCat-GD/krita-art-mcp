import datetime
import hashlib
import logging
import math
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from krita_art_mcp import imaging, transfer
from krita_art_mcp.paths import Places
from krita_art_mcp.transfer import Pixels

log = logging.getLogger(__name__)

# The diff image's long edge at most.
DIFF_PX = 1024
# The bits of the plugin's flags byte per pixel; the plugin holds equal values.
CHANGED = 1
OUTSIDE = 2
ALPHA = 4
OFFENDING = (255, 32, 64, 255)
# How far the unchanged scope fades toward white, so the offending pixels stand out.
FADE = 0.35
COUNTS = ("changed_px", "changed_bounds_px", "changed_outside_px", "alpha_changed_px")
# The largest scope whose before and after the receipt keeps as PNGs; the plugin holds an equal
# bound (MAX_IMAGE_PIXELS).
IMAGE_PIXELS = 2048 * 2048

Kept = tuple[Path, bytes]


def artifact(path: Path, png: bytes) -> dict[str, Any]:
    return {
        "uri": str(path),
        "path": str(path),
        "mime_type": "image/png",
        "sha256": hashlib.sha256(png).hexdigest(),
        "size_bytes": len(png),
        "retention_days": imaging.RETENTION_DAYS,
    }


def keep(
    places: Places,
    operation_id: str,
    suffix: str,
    today: datetime.date,
    specs: list[Any],
    draw: Callable[..., Image.Image],
) -> Kept | None:
    # An op's pixels as captures/<day>/<operation_id><suffix>, found before made so a rebuild
    # finds it; None when another server took them first. Raises OSError if it cannot be written.
    found = imaging.find(places.captures_dir, operation_id, suffix)
    if found is not None:
        return found, found.read_bytes()
    if specs[0] is None:
        return None
    try:
        pixels = [
            None if spec is None else transfer.take(places.transfer_dir, spec) for spec in specs
        ]
    except transfer.TransferError:
        again = imaging.find(places.captures_dir, operation_id, suffix)
        if again is not None:
            return again, again.read_bytes()
        log.warning("the %s of %s was not kept: its pixels were taken", suffix, operation_id)
        return None
    png = imaging.encode(draw(*pixels))
    target = imaging.folder_for(places.captures_dir, today) / f"{operation_id}{suffix}"
    imaging.write(target, png)
    imaging.sweep(places.captures_dir, today)
    return target, png


def image_of(pixels: Pixels) -> Image.Image:
    grey = pixels.shape[2] == 1
    return Image.fromarray(np.ascontiguousarray(pixels[..., 0] if grey else pixels))


def receipt(
    places: Places, operation_id: str, sent: dict[str, Any], today: datetime.date
) -> dict[str, Any]:
    # A passing change: the plugin's counts and the scope before and after as PNGs.
    images = {}
    for name in ("before", "after"):
        kept = _kept(places, operation_id, f".{name}.png", today, [sent.get(name)], image_of)
        images[name] = None if kept is None else artifact(*kept)
    return {
        "mode": sent["mode"],
        "rect": sent["rect"],
        **{key: sent[key] for key in COUNTS},
        **images,
    }


def failure(
    places: Places, operation_id: str, sent: dict[str, Any], today: datetime.date
) -> dict[str, Any]:
    # A refused change: the plugin's counts and an image of the offending pixels.
    preserve = bool(sent.get("preserve_composite_alpha"))

    def draw(flags: Pixels, before: Pixels | None) -> Image.Image:
        return diff_image(flags, before, preserve)

    specs = [sent.get("diff"), sent.get("before")]
    kept = _kept(places, operation_id, ".diff.png", today, specs, draw)
    return {
        "mode": sent["mode"],
        "rect": sent["rect"],
        **{key: sent[key] for key in COUNTS},
        "diff": None if kept is None else artifact(*kept),
    }


def _kept(
    places: Places,
    operation_id: str,
    suffix: str,
    today: datetime.date,
    specs: list[Any],
    draw: Callable[..., Image.Image],
) -> Kept | None:
    # A PNG that cannot be written is left out, and its pixels stay for a later rebuild.
    try:
        kept = keep(places, operation_id, suffix, today, specs, draw)
    except OSError:
        log.exception("the %s of %s was not written", suffix, operation_id)
        return None
    for spec in specs:
        discard(places, spec)
    return kept


def diff_image(flags: Pixels, before: Pixels | None, preserve: bool) -> Image.Image:
    # Offending pixels red over the scope faded toward white, at most DIFF_PX long; a block that
    # holds one offending pixel stays red when shrunk.
    marks = flags[..., 0]
    offending = (marks & (CHANGED | OUTSIDE)) == CHANGED | OUTSIDE
    if preserve:
        offending |= (marks & ALPHA) != 0
    height, width = marks.shape
    step = max(1, math.ceil(max(width, height) / DIFF_PX))
    size = (math.ceil(width / step), math.ceil(height / step))
    if before is None:
        grey = Image.new("L", size, 255)
    else:
        # 8-bit work at the scope's size; the float fade runs on the shrunk image only.
        white = Image.new("RGBA", (width, height), (255, 255, 255, 255))
        over = Image.alpha_composite(white, Image.fromarray(np.ascontiguousarray(before)))
        grey = over.convert("L").resize(size, Image.Resampling.BOX)
    faded = np.rint(255.0 - (255.0 - np.asarray(grey, dtype=np.float64)) * FADE).astype(np.uint8)
    padded = np.zeros((size[1] * step, size[0] * step), dtype=bool)
    padded[:height, :width] = offending
    hit = padded.reshape(size[1], step, size[0], step).any(axis=(1, 3))
    image = np.dstack([faded] * 3 + [np.full((size[1], size[0]), 255, np.uint8)])
    image[hit] = OFFENDING
    return Image.fromarray(image)


def discard(places: Places, spec: Any) -> None:
    if spec is None:
        return
    try:
        transfer.discard(places.transfer_dir, spec)
    except (transfer.TransferError, OSError):
        log.exception("a transfer file was not removed")
