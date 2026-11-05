import math
from pathlib import Path
from typing import Any

from . import nodes, paths, transfer
from .errors import BridgeError, exact, integer
from .inspection import TYPES, check_frame, check_shown_frame
from .jobs import Call, Handler
from .port import DocumentsPort
from .rects import inside
from .registry import Handle, Registry

CAPTURE_FIELDS = {"document_id", "frame", "target", "layer_id", "rect", "render"}
SAMPLE_FIELDS = {"document_id", "frame", "target", "layer_id", "points", "radius"}
RECT_FIELDS = {"x", "y", "width", "height"}
# The largest area one read covers; the server holds an equal copy (capture_source_pixels).
MAX_READ_PIXELS = 8192 * 8192
MAX_POINTS = 256
MAX_RADIUS = 64
# Reads hand over 8-bit RGBA bytes; other spaces would pass the byte count and lie.
READ_SPACE = ("RGBA", "U8")


def handlers(registry: Registry, port: DocumentsPort, data: Path) -> dict[str, Handler]:
    def capture(args: dict[str, Any], call: Call) -> dict[str, Any]:
        # A read: no lease, and the view is touched only when K46 demands it.
        exact(args, CAPTURE_FIELDS)
        check_frame(args["frame"])
        target = check_target(args, ("composite", "layer", "selection", "mask"))
        rect = check_rect(args["rect"])
        if not isinstance(args["render"], dict):
            raise BridgeError("INVALID_ARGUMENT", "render is an object.")
        if rect["width"] * rect["height"] > MAX_READ_PIXELS:
            details = {"max_read_pixels": MAX_READ_PIXELS}
            raise BridgeError(
                "INVALID_ARGUMENT", "The rect is too large to read; tile it.", False, details
            )
        registry.refuse_at_job_start()
        handle = registry.find(args["document_id"])
        info = port.describe(handle.document)
        check_shown_frame(info)
        inside(rect, info["size_px"], "rect")
        width, height = rect["width"], rect["height"]
        if target == "selection":
            pixels = port.selection_rect(handle.document, rect)
            if pixels is None:
                message = "The document has no selection, so painting is unconfined."
                missing = {"document_id": handle.document_id}
                raise BridgeError("INVALID_ARGUMENT", message, False, missing)
            profile = None
            spec = transfer.write(paths.transfer_dir(data), pixels, width, height, "A8")
        elif target == "mask":
            transparency_mask(port.tree(handle.document), args["layer_id"])
            [pixels] = port.layer_rects(handle.document, args["layer_id"], [rect])
            profile = None
            spec = transfer.write(paths.transfer_dir(data), pixels, width, height, "A8")
        else:
            [pixels], profile = read_rects(port, handle, info, target, args["layer_id"], [rect])
            spec = transfer.write(paths.transfer_dir(data), pixels, width, height, "BGRA8")
        return {
            "document_id": handle.document_id,
            "target": target,
            "layer_id": args["layer_id"],
            "rect": rect,
            "profile_id": profile,
            "pixels": spec,
            # Echoed, so the server's receipt depends on this outcome alone.
            "render": args["render"],
        }

    def sample(args: dict[str, Any], call: Call) -> dict[str, Any]:
        exact(args, SAMPLE_FIELDS)
        check_frame(args["frame"])
        target = check_target(args, ("composite", "layer"))
        points = _points(args["points"])
        radius = _radius(args["radius"])
        registry.refuse_at_job_start()
        handle = registry.find(args["document_id"])
        info = port.describe(handle.document)
        check_shown_frame(info)
        width, height = info["size_px"]
        outside = [point for point in points if point[0] >= width or point[1] >= height]
        if outside:
            details = {"points": outside, "canvas_px": [width, height]}
            raise BridgeError(
                "INVALID_ARGUMENT", "A point lies outside the canvas.", False, details
            )
        squares = [_square(point, radius, width, height) for point in points]
        buffers, profile = read_rects(port, handle, info, target, args["layer_id"], squares)
        total = sum(square["width"] * square["height"] for square in squares)
        # Every point's square in one row, so one file carries them all.
        spec = transfer.write(paths.transfer_dir(data), b"".join(buffers), total, 1, "BGRA8")
        return {
            "document_id": handle.document_id,
            "target": target,
            "layer_id": args["layer_id"],
            "profile_id": profile,
            "points": points,
            "radius": radius,
            "squares": squares,
            "pixels": spec,
        }

    return {"capture.read": capture, "sample.read": sample}


def read_rects(
    port: DocumentsPort,
    handle: Handle,
    info: dict[str, Any],
    target: str,
    layer_id: Any,
    rects: list[dict[str, int]],
) -> tuple[list[Any], str]:
    if target == "layer":
        node = paint_layer(port.tree(handle.document), layer_id)
        return port.layer_rects(handle.document, layer_id, rects), node["profile_id"]
    check_read_space(info)
    # K46: a selection mask's overlay would enter the read, and an owner's document is never
    # changed, not even its active node.
    if not handle.owned and port.mask_active(handle.document):
        details = {"document_id": handle.document_id, "reason": "selection_mask_active"}
        message = (
            "A selection mask is active in this document, and its overlay would enter the "
            "read; ask the owner to select a layer."
        )
        raise BridgeError("DOCUMENT_READ_ONLY", message, False, details)
    with nodes.unmasked_view(port, handle.document):
        buffers = port.composite_rects(handle.document, rects)
    return buffers, info["profile_id"]


def check_read_space(info: dict[str, Any]) -> None:
    if (info["color_model"], info["depth"]) != READ_SPACE:
        details = {key: info[key] for key in ("color_model", "depth", "profile_id")}
        message = "Phase 1 reads RGBA / U8 documents only."
        raise BridgeError("COLOR_PROFILE_MISMATCH", message, False, details)


def check_rect(rect: Any) -> dict[str, int]:
    if (
        not isinstance(rect, dict)
        or set(rect) != RECT_FIELDS
        or not all(integer(rect[key]) for key in RECT_FIELDS)
        or rect["x"] < 0
        or rect["y"] < 0
        or rect["width"] < 1
        or rect["height"] < 1
    ):
        raise BridgeError("INVALID_ARGUMENT", "rect is {x, y, width, height} in whole pixels.")
    return {key: rect[key] for key in ("x", "y", "width", "height")}


def check_target(args: dict[str, Any], targets: tuple[str, ...]) -> str:
    target, layer_id = args["target"], args["layer_id"]
    if target not in targets:
        raise BridgeError("INVALID_ARGUMENT", f"target is one of {', '.join(targets)}.")
    if (target in ("layer", "mask")) != (isinstance(layer_id, str) and bool(layer_id)):
        message = "layer_id names a node for target layer or mask only."
        raise BridgeError("INVALID_ARGUMENT", message)
    return str(target)


def paint_layer(tree: dict[str, Any], layer_id: str) -> dict[str, Any]:
    node: dict[str, Any] | None = next((n for n in tree["nodes"] if n["id"] == layer_id), None)
    if node is None:
        raise BridgeError("LAYER_NOT_FOUND", "No layer has that id.", False, {"layer_id": layer_id})
    # A group has no pixels of its own, and a mask is one channel.
    if node["type"] != "paintlayer":
        kind = TYPES.get(node["type"], node["type"])
        details = {"layer_id": layer_id, "layer_type": kind}
        message = f"Layer reads take paint layers; this layer is a {kind}."
        if node["type"] == "transparencymask":
            message += ' Capture it with target "mask".'
        raise BridgeError("UNSUPPORTED_CAPABILITY", message, False, details)
    if (node["color_model"], node["depth"]) != READ_SPACE:
        details = {key: node[key] for key in ("color_model", "depth", "profile_id")}
        details["layer_id"] = layer_id
        message = "Phase 1 reads RGBA / U8 layers only."
        raise BridgeError("COLOR_PROFILE_MISMATCH", message, False, details)
    return node


def transparency_mask(tree: dict[str, Any], layer_id: str) -> dict[str, Any]:
    node: dict[str, Any] | None = next((n for n in tree["nodes"] if n["id"] == layer_id), None)
    if node is None:
        raise BridgeError("LAYER_NOT_FOUND", "No layer has that id.", False, {"layer_id": layer_id})
    if node["type"] != "transparencymask":
        kind = TYPES.get(node["type"], node["type"])
        details = {"layer_id": layer_id, "layer_type": kind}
        message = f"target mask reads a transparency mask; this layer is a {kind}."
        raise BridgeError("INVALID_ARGUMENT", message, False, details)
    return node


def _points(points: Any) -> list[list[int]]:
    if (
        not isinstance(points, list)
        or not 1 <= len(points) <= MAX_POINTS
        or not all(
            isinstance(point, list)
            and len(point) == 2
            and all(integer(value) and value >= 0 for value in point)
            for point in points
        )
    ):
        raise BridgeError("INVALID_ARGUMENT", f"points is 1 to {MAX_POINTS} [x, y] pixel pairs.")
    return [[point[0], point[1]] for point in points]


def _radius(radius: Any) -> float:
    if (
        not isinstance(radius, (int, float))
        or isinstance(radius, bool)
        or not math.isfinite(radius)
        or not 0 <= radius <= MAX_RADIUS
    ):
        raise BridgeError("INVALID_ARGUMENT", f"radius is a number from 0 to {MAX_RADIUS}.")
    return radius


def _square(point: list[int], radius: float, width: int, height: int) -> dict[str, int]:
    # Every pixel the disc can reach, clipped to the canvas.
    reach = int(radius)
    left, top = max(0, point[0] - reach), max(0, point[1] - reach)
    right, bottom = min(width, point[0] + reach + 1), min(height, point[1] + reach + 1)
    return {"x": left, "y": top, "width": right - left, "height": bottom - top}
