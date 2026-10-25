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

# The diff image's long edge at most (PDD Part 4).
DIFF_PX = 1024
# The bits of the plugin's flags byte per pixel; the plugin holds equal values.
CHANGED = 1
OUTSIDE = 2
ALPHA = 4
OFFENDING = (255, 32, 64, 255)
# How far the unchanged scope fades toward white, so the offending pixels stand out.
FADE = 0.35
COUNTS = ("changed_px", "changed_bounds_px", "changed_outside_px", "alpha_changed_px")

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


def receipt(
    places: Places, operation_id: str, sent: dict[str, Any], today: datetime.date
) -> dict[str, Any]:
    # A verified change: the counts as the plugin made them, and the scope before and after as
    # PNGs, each found before it is made so a rebuild finds it; null when another server took
    # its pixels first, or when it could not be made, which never undoes the change.
    images = {}
    for name in ("before", "after"):
        kept = _kept(places, operation_id, f".{name}.png", today, [sent.get(name)], _colour)
        images[name] = None if kept is None else artifact(*kept)
    _discard(places, sent)
    return {
        "mode": sent["mode"],
        "rect": sent["rect"],
        **{key: sent[key] for key in COUNTS},
        **images,
    }


def failure(
    places: Places, operation_id: str, sent: dict[str, Any], today: datetime.date
) -> dict[str, Any]:
    # A refused change: the counts, and the offending pixels as one small image over a faded
    # copy of the scope as it was.
    preserve = bool(sent.get("preserve_composite_alpha"))

    def draw(flags: Pixels, before: Pixels | None) -> Image.Image:
        return diff_image(flags, before, preserve)

    kept = _kept(
        places, operation_id, ".diff.png", today, [sent.get("diff"), sent.get("before")], draw
    )
    _discard(places, sent)
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
    try:
        imaging.write(target, png)
    except OSError:
        log.exception("the %s of %s was not written", suffix, operation_id)
        return None
    imaging.sweep(places.captures_dir, today)
    return target, png


def _colour(pixels: Pixels) -> Image.Image:
    return Image.fromarray(np.ascontiguousarray(pixels))


def diff_image(flags: Pixels, before: Pixels | None, preserve: bool) -> Image.Image:
    # Offending pixels in red over the scope faded toward white, at most DIFF_PX on the long
    # edge; a block keeps red if any pixel in it offends, so none vanishes when shrunk.
    marks = flags[..., 0]
    offending = (marks & (CHANGED | OUTSIDE)) == CHANGED | OUTSIDE
    if preserve:
        offending |= (marks & ALPHA) != 0
    height, width = marks.shape
    if before is None:
        grey = np.full((height, width), 255.0)
    else:
        alpha = before[..., 3:4] / 255.0
        over_white = before[..., :3] * alpha + 255.0 * (1 - alpha)
        grey = over_white @ np.array([0.299, 0.587, 0.114])
    faded = 255.0 - (255.0 - grey) * FADE
    step = max(1, math.ceil(max(width, height) / DIFF_PX))
    size = (math.ceil(width / step), math.ceil(height / step))
    back = Image.fromarray(np.rint(faded).astype(np.uint8)).resize(size, Image.Resampling.BOX)
    padded = np.zeros((size[1] * step, size[0] * step), dtype=bool)
    padded[:height, :width] = offending
    hit = padded.reshape(size[1], step, size[0], step).any(axis=(1, 3))
    image = np.dstack([np.asarray(back)] * 3 + [np.full((size[1], size[0]), 255, np.uint8)])
    image[hit] = OFFENDING
    return Image.fromarray(image)


def _discard(places: Places, sent: dict[str, Any]) -> None:
    # Only once every PNG exists, so no rebuild ever lacks what it needs.
    for name in ("before", "after", "diff"):
        spec = sent.get(name)
        if spec is not None:
            try:
                transfer.discard(places.transfer_dir, spec)
            except (transfer.TransferError, OSError):
                log.exception("a verification file was not removed")
