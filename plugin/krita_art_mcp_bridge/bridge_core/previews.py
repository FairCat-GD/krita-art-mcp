from pathlib import Path
from typing import Any

from . import files, paths, reopening, transfer
from .errors import BridgeError, exact
from .inspection import check_frame, check_shown_frame
from .jobs import Call, Handler
from .pixels import (
    MAX_READ_PIXELS,
    check_read_space,
    check_rect,
    check_target,
    inside,
    read_rects,
)
from .port import DocumentsPort
from .registry import Handle, Registry

PREVIEW_FIELDS = {"sources", "render"}
SOURCE_FIELDS = {
    "document_id",
    "frame",
    "target",
    "layer_id",
    "rect",
    "baseline_id",
    "read_baseline",
    "overlays",
}
OVERLAYS = ("selection", "allowed_mask")
# The server holds equal copies.
MAX_SOURCES = 8
# What one preview reads: a whole 8192 x 8192 master beside its as_opened baseline.
MAX_PREVIEW_PIXELS = 2 * MAX_READ_PIXELS


def handlers(registry: Registry, port: DocumentsPort, data: Path) -> dict[str, Handler]:
    def preview(args: dict[str, Any], call: Call) -> dict[str, Any]:
        # A read: no lease, and the view is touched only when K46 demands it.
        exact(args, PREVIEW_FIELDS)
        sources = [_source(source) for source in _list(args["sources"])]
        if not isinstance(args["render"], dict):
            raise BridgeError("INVALID_ARGUMENT", "render is an object.")
        registry.refuse_at_job_start()
        found = []
        cropped = whole = 0
        for source in sources:
            handle = registry.find(source["document_id"])
            info = port.describe(handle.document)
            check_shown_frame(info)
            width, height = info["size_px"]
            rect = source["rect"] or {"x": 0, "y": 0, "width": width, "height": height}
            inside(rect, info["size_px"])
            if source["baseline_id"] is not None and source["baseline_id"] != handle.baseline_id:
                owned = {"document_id": handle.document_id, "baseline_id": handle.baseline_id}
                message = "baseline_id is not this document's as_opened baseline."
                raise BridgeError("INVALID_ARGUMENT", message, False, owned)
            cropped += rect["width"] * rect["height"]
            whole += width * height if source["read_baseline"] else 0
            found.append((source, handle, info, rect))
        if cropped + whole > MAX_PREVIEW_PIXELS:
            raise _too_many(cropped, whole)
        written: list[dict[str, Any]] = []
        try:
            read = [_read(written, *entry, call) for entry in found]
        except BaseException:
            for spec in written:
                transfer.remove(spec)
            raise
        # Echoed, so the server's receipt depends on this outcome alone.
        return {"sources": read, "render": args["render"]}

    def _read(
        written: list[dict[str, Any]],
        source: dict[str, Any],
        handle: Handle,
        info: dict[str, Any],
        rect: dict[str, int],
        call: Call,
    ) -> dict[str, Any]:
        folder = paths.transfer_dir(data)

        def keep(pixels: Any, width: int, height: int, fmt: str) -> dict[str, Any]:
            spec = transfer.write(folder, pixels, width, height, fmt)
            written.append(spec)
            return spec

        width, height = rect["width"], rect["height"]
        target, layer_id = source["target"], source["layer_id"]
        [pixels], profile = read_rects(port, handle, info, target, layer_id, [rect])
        result: dict[str, Any] = {
            "document_id": handle.document_id,
            "target": target,
            "layer_id": layer_id,
            "rect": rect,
            "canvas_px": info["size_px"],
            "profile_id": profile,
            "pixels": keep(pixels, width, height, "BGRA8"),
            "baseline": None,
            "overlays": {},
        }
        if source["baseline_id"] is not None:
            spec = None
            if source["read_baseline"]:
                canvas_w, canvas_h = info["size_px"]
                spec = keep(_as_opened(handle, info, call), canvas_w, canvas_h, "BGRA8")
            result["baseline"] = {"baseline_id": handle.baseline_id, "pixels": spec}
        for name in source["overlays"]:
            mask = _overlay(port, name, handle, info, rect)
            result["overlays"][name] = None if mask is None else keep(mask, width, height, "A8")
        return result

    def _as_opened(handle: Handle, info: dict[str, Any], call: Call) -> Any:
        # The file Krita opened holds the document as it was opened: no save overwrites it.
        if handle.path is None or handle.source_sha256 is None:
            raise BridgeError("INTERNAL_ERROR", "The document has no file to read its baseline.")
        if not files.unchanged(handle.path, handle.source_sha256):
            details = {"document_id": handle.document_id, "path": handle.path}
            message = "The file this document was opened from has changed; its baseline is gone."
            raise BridgeError("SOURCE_HASH_MISMATCH", message, False, details)

        def read(document: Any) -> Any:
            opened = port.describe(document)
            check_shown_frame(opened)
            check_read_space(opened)
            if opened["size_px"] != info["size_px"]:
                details = {"file_px": opened["size_px"], "canvas_px": info["size_px"]}
                message = "The file opens at another size than the document."
                raise BridgeError("INTERNAL_ERROR", message, False, details)
            return port.composite(document)

        message = "Krita kept open the file read for the baseline; close it with discard."
        return reopening.read_file(registry, port, handle.path, call.client, read, message)

    return {"preview.read": preview}


def _too_many(cropped: int, whole: int) -> BridgeError:
    # A baseline is read over its whole canvas, so a crop cannot shrink that part.
    details = {
        "crop_pixels": cropped,
        "baseline_pixels": whole,
        "max_preview_pixels": MAX_PREVIEW_PIXELS,
    }
    if whole > MAX_PREVIEW_PIXELS:
        message = "These baselines are too large to read in one preview; leave out baseline_id."
    else:
        message = "The preview reads too many pixels at once; give crop_rects or fewer sources."
    return BridgeError("INVALID_ARGUMENT", message, False, details)


def _overlay(
    port: DocumentsPort, name: str, handle: Handle, info: dict[str, Any], rect: dict[str, int]
) -> Any:
    # One byte per pixel over the rect, or None when there is nothing to outline.
    if name == "selection":
        return port.selection_rect(handle.document, rect)
    mask = handle.allowed_mask
    if mask is None:
        return None
    width = info["size_px"][0]
    left, right = rect["x"], rect["x"] + rect["width"]
    return b"".join(
        mask[row * width + left : row * width + right]
        for row in range(rect["y"], rect["y"] + rect["height"])
    )


def _list(sources: Any) -> list[Any]:
    if not isinstance(sources, list) or not 1 <= len(sources) <= MAX_SOURCES:
        raise BridgeError("INVALID_ARGUMENT", f"sources is a list of 1 to {MAX_SOURCES}.")
    return sources


def _source(source: Any) -> dict[str, Any]:
    # The server checks these too; the plugin trusts no caller.
    if not isinstance(source, dict):
        raise BridgeError("INVALID_ARGUMENT", "Each source is an object.")
    exact(source, SOURCE_FIELDS)
    check_frame(source["frame"])
    target = check_target(source, ("composite", "layer"))
    rect = None if source["rect"] is None else check_rect(source["rect"])
    baseline_id, read_baseline, overlays = (
        source["baseline_id"],
        source["read_baseline"],
        source["overlays"],
    )
    if baseline_id is not None and (not isinstance(baseline_id, str) or target != "composite"):
        message = "baseline_id names the as_opened composite, for target composite only."
        raise BridgeError("INVALID_ARGUMENT", message)
    if not isinstance(read_baseline, bool) or (read_baseline and baseline_id is None):
        raise BridgeError("INVALID_ARGUMENT", "read_baseline is a boolean, true only with one.")
    if (
        not isinstance(overlays, list)
        or len(set(overlays)) != len(overlays)
        or not all(name in OVERLAYS for name in overlays)
    ):
        raise BridgeError("INVALID_ARGUMENT", f"overlays are distinct, of {', '.join(OVERLAYS)}.")
    return {**source, "target": target, "rect": rect}
