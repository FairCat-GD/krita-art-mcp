import hashlib
import logging
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from . import log, nodes, paths, transfer
from .errors import BridgeError
from .inspection import check_shown_frame
from .pixels import MAX_READ_PIXELS
from .port import DocumentsPort
from .registry import Handle

REGION = "region"
FULL = "full"
MODES = (REGION, FULL)
# The largest scope whose before and after images go to the server; it holds an equal bound
# (verification.IMAGE_PIXELS).
MAX_IMAGE_PIXELS = 2048 * 2048
# The checks take the scope in bands of this many pixels: whole-buffer work, bounded memory.
BAND_PIXELS = 1 << 20

# The bits of the flags byte each pixel of the scope gets.
CHANGED = 1
OUTSIDE = 2
ALPHA = 4

# Nodes whose effect on the composite stays inside their own pixels' bounds.
BOUNDED = {"paintlayer", "grouplayer", "transparencymask", "selectionmask"}
# Nodes that spread a change spatially, by the reason a refusal names.
SPREADING = {
    "filtermask": "filter_mask",
    "filterlayer": "filter_layer",
    "transformmask": "transform_mask",
    "colorizemask": "colorize_mask",
}
# Krita composites these past a layer's own extent (kis_layer_projection_plane.cpp).
SPREADING_BLENDS = {"copy", "destination-in", "destination-atop"}


def _table(mark: Callable[[int], int]) -> bytes:
    return bytes(mark(value) for value in range(256))


_MARK_CHANGED = _table(lambda value: CHANGED if value else 0)
_MARK_ALPHA = _table(lambda value: ALPHA if value else 0)
# The allowed mask is 0 or 255.
_MARK_OUTSIDE = _table(lambda value: 0 if value else OUTSIDE)
_IS_CHANGED = _table(lambda value: 1 if value & CHANGED else 0)
_IS_LEAK = _table(lambda value: 1 if value & (CHANGED | OUTSIDE) == CHANGED | OUTSIDE else 0)
_IS_ALPHA = _table(lambda value: 1 if value & ALPHA else 0)


class Reading:
    # A scope's composite (B, G, R, A), and the target's pixels and layer hashes when asked for.
    def __init__(
        self,
        rect: dict[str, int],
        composite: Any,
        target: Any | None = None,
        hashes: dict[str, str] | None = None,
        target_id: str | None = None,
        rects: dict[str, dict[str, int]] | None = None,
        kept: tuple[str, Any] | None = None,
    ) -> None:
        self.rect = rect
        self.composite = composite
        self.target = target
        self.hashes = hashes or {}
        self.target_id = target_id
        # A layer's own rect where it is read over other than the scope.
        self.rects = rects or {}
        # The first hashed layer whose hash was not the expected one, with its pixels.
        self.kept = kept


class Verdict:
    def __init__(
        self,
        flags: bytes,
        changed_px: int,
        changed_outside_px: int,
        alpha_changed_px: int,
        changed_bounds_px: dict[str, int] | None,
        protected_changed: list[str],
        preserve_alpha: bool,
    ) -> None:
        self.flags = flags
        self.changed_px = changed_px
        self.changed_outside_px = changed_outside_px
        self.alpha_changed_px = alpha_changed_px
        self.changed_bounds_px = changed_bounds_px
        self.protected_changed = protected_changed
        self.preserve_alpha = preserve_alpha

    @property
    def leaked(self) -> bool:
        return bool(
            self.changed_outside_px
            or (self.preserve_alpha and self.alpha_changed_px)
            or self.protected_changed
        )

    def counts(self) -> dict[str, Any]:
        return {
            "changed_px": self.changed_px,
            "changed_outside_px": self.changed_outside_px,
            "alpha_changed_px": self.alpha_changed_px,
            "changed_bounds_px": self.changed_bounds_px,
        }


def reach(tree: dict[str, Any], effects: dict[str, Any], target_id: str) -> list[dict[str, str]]:
    # Every node that could carry the target's change past its bounds, where a region read misses.
    by_id = {node["id"]: node for node in tree["nodes"]}
    children: dict[str, list[dict[str, Any]]] = {}
    for node in tree["nodes"]:
        children.setdefault(node["parent_id"], []).append(node)
    path = [by_id[target_id]]
    while path[-1]["parent_id"] in by_id:
        path.append(by_id[path[-1]["parent_id"]])
    styled = set(effects["styled"])
    found: list[dict[str, str]] = []

    def note(reason: str, node_id: str) -> None:
        entry = {"reason": reason, "node_id": node_id}
        if entry not in found:
            found.append(entry)

    def own(node: dict[str, Any]) -> None:
        kind = node["type"]
        if kind in SPREADING:
            note(SPREADING[kind], node["id"])
        elif kind not in BOUNDED:
            note("layer_type", node["id"])
        if node["id"] in styled:
            note("layer_style", node["id"])

    for node in _subtree(children, path[0]):
        own(node)
        # Only a changed layer's own blend spreads; an ancestor's works pixel by pixel.
        if not node["type"].endswith("mask") and node["blend_mode"] in SPREADING_BLENDS:
            note("blend_mode", node["id"])
    for ancestor in path[1:]:
        own(ancestor)
        for child in children.get(ancestor["id"], []):
            if child["type"].endswith("mask"):
                own(child)
    # A filter layer inside a pass-through group above still filters what lies below the group.
    for node in path:
        for sibling in children.get(node["parent_id"], []):
            if sibling["order"] > node["order"]:
                for inner in _subtree(children, sibling):
                    if inner["type"] == "filterlayer":
                        note("filter_layer", inner["id"])
    reached = {node["id"] for node in path}
    for clone_id, source_id in sorted(effects["clones"].items()):
        if source_id is None or source_id in reached:
            note("clone_layer", clone_id)
    return found


def _subtree(
    children: dict[str, list[dict[str, Any]]], node: dict[str, Any]
) -> list[dict[str, Any]]:
    found, pending = [], [node]
    while pending:
        current = pending.pop()
        found.append(current)
        pending.extend(children.get(current["id"], []))
    return found


def scope(mode: str, tree: dict[str, Any], target_id: str, size: list[int]) -> dict[str, int]:
    # The target's and its descendants' exact bounds, clipped to the canvas; full is the canvas.
    if mode == FULL:
        return {"x": 0, "y": 0, "width": size[0], "height": size[1]}
    children: dict[str, list[dict[str, Any]]] = {}
    for node in tree["nodes"]:
        children.setdefault(node["parent_id"], []).append(node)
    target = next(node for node in tree["nodes"] if node["id"] == target_id)
    boxes = [
        node["bounds_px"]
        for node in _subtree(children, target)
        if node["bounds_px"]["width"] > 0 and node["bounds_px"]["height"] > 0
    ]
    if not boxes:
        return {"x": 0, "y": 0, "width": 0, "height": 0}
    left = max(0, min(box["x"] for box in boxes))
    top = max(0, min(box["y"] for box in boxes))
    right = min(size[0], max(box["x"] + box["width"] for box in boxes))
    bottom = min(size[1], max(box["y"] + box["height"] for box in boxes))
    if right <= left or bottom <= top:
        return {"x": 0, "y": 0, "width": 0, "height": 0}
    return {"x": left, "y": top, "width": right - left, "height": bottom - top}


def refuse_unverifiable(
    info: dict[str, Any], effects: dict[str, Any], rect: dict[str, int]
) -> None:
    # Before any change: nothing the reads cannot see is changed.
    check_shown_frame(info)
    if effects["animated"]:
        details: dict[str, Any] = {"reason": "animated", "supported": [0]}
        message = (
            "The document is animated: a layer property changes every frame, and Phase 1 "
            "verifies frame 0 only. Animation arrives in Phase 5."
        )
        raise BridgeError("UNSUPPORTED_CAPABILITY", message, False, details)
    if rect["width"] * rect["height"] > MAX_READ_PIXELS:
        details = {"reason": "too_large", "rect": rect, "max_read_pixels": MAX_READ_PIXELS}
        message = "The change's scope is larger than one read; Phase 1 cannot verify it."
        raise BridgeError("UNSUPPORTED_CAPABILITY", message, False, details)


def allowed_rows(handle: Handle, size: list[int], rect: dict[str, int]) -> bytes | None:
    # The allowed mask over the scope, one byte per pixel; None allows everything.
    mask = handle.allowed_mask
    if mask is None:
        return None
    width = size[0]
    if len(mask) != width * size[1]:
        details = {"canvas_px": size}
        message = "The canvas changed size since the allowed mask was set; reopen the document."
        raise BridgeError("INVALID_ARGUMENT", message, False, details)
    return b"".join(
        mask[row * width + rect["x"] : row * width + rect["x"] + rect["width"]]
        for row in range(rect["y"], rect["y"] + rect["height"])
    )


def read(
    port: DocumentsPort,
    document: Any,
    rect: dict[str, int],
    target_id: str | None = None,
    hashed: Iterable[str] = (),
    rects: dict[str, dict[str, int]] | None = None,
    expected: dict[str, str] | None = None,
) -> Reading:
    # Each layer over its own rect in rects, or the scope's; expected keeps the pixels of the
    # first hashed layer whose hash differs from it.
    rects = rects or {}
    if _empty(rect) and not rects:
        return Reading(rect, b"")
    composite: Any = b""
    if not _empty(rect):
        # K46: a selection mask's overlay would enter the composite.
        with nodes.unmasked_view(port, document):
            [composite] = port.composite_rects(document, [rect])
        composite = _bytes(composite)
    target = None
    if target_id is not None:
        target = _layer(port, document, target_id, rects.get(target_id, rect))
    hashes = {}
    kept = None
    for layer_id in hashed:
        # One layer's buffer at a time.
        pixels = _layer(port, document, layer_id, rects.get(layer_id, rect))
        hashes[layer_id] = hashlib.sha256(pixels).hexdigest()
        if kept is None and expected is not None and expected.get(layer_id) != hashes[layer_id]:
            kept = (layer_id, pixels)
    return Reading(rect, composite, target, hashes, target_id, rects, kept)


def again(port: DocumentsPort, document: Any, reading: Reading) -> Reading:
    # The same reads as before, nothing kept.
    hashed = list(reading.hashes)
    return read(port, document, reading.rect, reading.target_id, hashed, reading.rects)


def _empty(rect: dict[str, int]) -> bool:
    return rect["width"] <= 0 or rect["height"] <= 0


def _layer(port: DocumentsPort, document: Any, layer_id: str, rect: dict[str, int]) -> Any:
    if _empty(rect):
        return memoryview(b"")
    [pixels] = port.layer_rects(document, layer_id, [rect])
    return _bytes(pixels)


def _bytes(buffer: Any) -> memoryview:
    # Krita's own array, viewed as bytes, never copied.
    return memoryview(buffer).cast("B")


def changes(old: Any, new: Any, rect: dict[str, int]) -> tuple[int, dict[str, int] | None]:
    # How many BGRA pixels differ between two reads of one rect, and the canvas rect around them.
    pixels = 0 if _empty(rect) else rect["width"] * rect["height"]
    marked = bytearray(pixels)
    for start in range(0, pixels, BAND_PIXELS):
        stop = min(pixels, start + BAND_PIXELS)
        changed = 0
        for channel in range(4):
            changed |= _int(old[start * 4 + channel : stop * 4 : 4]) ^ _int(
                new[start * 4 + channel : stop * 4 : 4]
            )
        marked[start:stop] = changed.to_bytes(stop - start, "little").translate(_MARK_CHANGED)
    return marked.count(CHANGED), _bounds(marked, rect)


def crop(buffer: Any, outer: dict[str, int], inner: dict[str, int]) -> bytes:
    # The BGRA rows of inner, a rect inside outer, from a read of outer.
    width, left = outer["width"] * 4, (inner["x"] - outer["x"]) * 4
    top = inner["y"] - outer["y"]
    return b"".join(
        buffer[(top + row) * width + left : (top + row) * width + left + inner["width"] * 4]
        for row in range(inner["height"])
    )


def check(before: Reading, after: Reading, allowed: bytes | None, preserve_alpha: bool) -> Verdict:
    # One flags byte per pixel from whole-buffer operations per band, never a loop per pixel.
    rect = before.rect
    pixels = rect["width"] * rect["height"] if rect["width"] > 0 and rect["height"] > 0 else 0
    flags = bytearray(pixels)
    for start in range(0, pixels, BAND_PIXELS):
        stop = min(pixels, start + BAND_PIXELS)
        count = stop - start
        old = before.composite[start * 4 : stop * 4]
        new = after.composite[start * 4 : stop * 4]
        changed = 0
        for channel in range(4):
            changed |= _int(old[channel::4]) ^ _int(new[channel::4])
        alpha = _int(old[3::4]) ^ _int(new[3::4])
        marks = _int(changed.to_bytes(count, "little").translate(_MARK_CHANGED))
        marks |= _int(alpha.to_bytes(count, "little").translate(_MARK_ALPHA))
        if allowed is not None:
            marks |= _int(allowed[start:stop].translate(_MARK_OUTSIDE))
        flags[start:stop] = marks.to_bytes(count, "little")
    marked = flags.translate(_IS_CHANGED)
    protected = sorted(
        layer_id
        for layer_id, digest in before.hashes.items()
        if after.hashes.get(layer_id) != digest
    )
    return Verdict(
        bytes(flags),
        marked.count(1),
        flags.translate(_IS_LEAK).count(1),
        flags.translate(_IS_ALPHA).count(1),
        _bounds(marked, rect),
        protected,
        preserve_alpha,
    )


def _int(data: Any) -> int:
    return int.from_bytes(data, "little")


def _bounds(marked: bytearray, rect: dict[str, int]) -> dict[str, int] | None:
    # The canvas rect around the changed pixels, a row at a time; None when none changed.
    width = rect["width"]
    if not marked or width <= 0:
        return None
    left, right, rows = width, 0, []
    for start in range(0, len(marked), width):
        first = marked.find(1, start, start + width)
        if first >= 0:
            rows.append(start // width)
            left = min(left, first - start)
            right = max(right, marked.rfind(1, start, start + width) - start + 1)
    if not rows:
        return None
    return {
        "x": rect["x"] + left,
        "y": rect["y"] + rows[0],
        "width": right - left,
        "height": rows[-1] - rows[0] + 1,
    }


def same(before: Reading, again: Reading) -> bool:
    return (
        before.rect == again.rect
        and before.composite == again.composite
        and before.target == again.target
        and before.hashes == again.hashes
    )


def files(
    data: Path,
    mode: str,
    before: Reading,
    after: Reading | None,
    verdict: Verdict,
    failed: bool,
) -> dict[str, Any]:
    # After the verdict and any rollback; a file that cannot be written is left out.
    rect = before.rect
    pixels = rect["width"] * rect["height"] if rect["width"] > 0 and rect["height"] > 0 else 0
    folder = paths.transfer_dir(data)
    out: dict[str, Any] = {
        "mode": mode,
        "rect": rect,
        **verdict.counts(),
        "preserve_composite_alpha": verdict.preserve_alpha,
        "before": None,
        "after": None,
        "diff": None,
    }
    if pixels and pixels <= MAX_IMAGE_PIXELS:
        out["before"] = _write(folder, before.composite, rect, "BGRA8")
        if not failed and after is not None:
            out["after"] = _write(folder, after.composite, rect, "BGRA8")
    if failed and pixels:
        out["diff"] = _write(folder, verdict.flags, rect, "A8")
    return out


def _write(folder: Path, data: Any, rect: dict[str, int], fmt: str) -> dict[str, Any] | None:
    try:
        return transfer.write(folder, data, rect["width"], rect["height"], fmt)
    except BridgeError:
        logging.getLogger(log.NAME).exception("a verification file was not written")
        return None
