import hashlib
import math
from pathlib import Path
from typing import Any

from . import mutation, nodes, verification
from .errors import BridgeError, exact, integer, number
from .history import LABELS, refuse_cumulative
from .jobs import Call
from .layers import drift, refuse_clone_source
from .ledger import Witness
from .pixels import MAX_READ_PIXELS
from .port import DocumentsPort
from .protection import line, refuse_held
from .rects import union
from .registry import Handle
from .translations import TRANSFORM_MASK

SCALE, ROTATE, SHEAR = "scale", "rotate", "shear"
KINDS = (SCALE, ROTATE, SHEAR)
FIELDS = {
    SCALE: {"type", "size_px", "filter"},
    ROTATE: {"type", "degrees"},
    SHEAR: {"type", "degrees"},
}
# Krita's resampling filters by id (K54); scaleNode takes any other name as Bicubic, silently.
FILTERS = (
    "BSpline",
    "Bell",
    "Bicubic",
    "Bilinear",
    "Hermite",
    "Lanczos3",
    "Mitchell",
    "NearestNeighbor",
)
# The filter Krita fixes for a rotate and a shear (kis_image.cc).
FIXED = {ROTATE: "Bicubic", SHEAR: "Bilinear"}
MAX_SIZE = 16384
MAX_TURN = 360
MAX_SHEAR = 45
MAX_NODES = 50
# All the witness rects together, each read up to three times: 16 Mpx read and hashed in about
# 0.04 s on 5.3.4.1, so this stays seconds inside the server's wait.
MAX_TOTAL_PIXELS = 4 * MAX_READ_PIXELS
# The node types a transform takes, and holds, as Node.type() names them.
TAKES = {"paintlayer", "grouplayer"}
# A filter reaches at most this many source pixels past an edge (Lanczos3), and a few more
# for rounding: the witness reads this far past where the operation takes a layer.
REACH = 3
SLACK = 4


def rules(operation: dict[str, Any]) -> None:
    # Argument rules for scale, rotate and shear, held on the server too (decision 10).
    kind = operation["type"]
    exact(operation, FIELDS[kind])
    if kind == SCALE:
        size = operation["size_px"]
        if (
            not isinstance(size, list)
            or len(size) != 2
            or not all(integer(value) and 1 <= value <= MAX_SIZE for value in size)
        ):
            message = f"size_px is [width, height], whole pixels from 1 to {MAX_SIZE}."
            raise BridgeError("INVALID_ARGUMENT", message, False, _field("size_px"))
        if operation["filter"] not in FILTERS:
            message = f"filter is one of {', '.join(FILTERS)}."
            raise BridgeError("INVALID_ARGUMENT", message, False, _field("filter"))
        return
    degrees = operation["degrees"]
    if kind == ROTATE:
        if not number(degrees) or not -MAX_TURN < degrees < MAX_TURN or degrees == 0:
            message = f"degrees is a number between -{MAX_TURN} and {MAX_TURN}, not 0."
            raise BridgeError("INVALID_ARGUMENT", message, False, _field("degrees"))
        return
    if (
        not isinstance(degrees, list)
        or len(degrees) != 2
        or not all(number(value) and -MAX_SHEAR <= value <= MAX_SHEAR for value in degrees)
        or degrees == [0, 0]
    ):
        message = f"degrees is [x, y], each from -{MAX_SHEAR} to {MAX_SHEAR}, not both 0."
        raise BridgeError("INVALID_ARGUMENT", message, False, _field("degrees"))


def run(
    port: DocumentsPort, handle: Handle, args: dict[str, Any], call: Call, data: Path
) -> dict[str, Any]:
    # Krita resamples the layer and everything in it in one native step (K54); the witness is
    # the first of its paint layers that moved, read over a rect fixed before the change.
    document, layer_id, operation = handle.document, args["layer_id"], args["operation"]
    kind = operation["type"]
    first = port.tree(document)
    node = nodes.found(first, layer_id, "transform")
    if node["type"] not in TAKES:
        details: dict[str, Any] = {"layer_id": layer_id, "layer_type": node["type"]}
        message = "krita_layer_transform takes paint layers and groups."
        raise BridgeError("INVALID_ARGUMENT", message, False, details)
    refuse_held(first, layer_id, handle.protected)
    inside = nodes.subtree(first, layer_id)
    _refuse_kinds(first, layer_id, inside)
    info = port.describe(document)
    effects = port.effects(document, True)
    styled = sorted(set(effects["styled"]) & set(inside))
    if styled:
        details = {"layer_id": layer_id, "reason": "layer_style", "layer_ids": styled}
        message = "A layer style would not follow the transform, so a styled layer is refused."
        raise BridgeError("UNSUPPORTED_CAPABILITY", message, False, details)
    refuse_clone_source(effects, inside, "moves such clones when their source is transformed")
    refuse_cumulative(port, "transform")
    if kind == SCALE and operation["filter"] not in port.filter_strategies():
        details = {"layer_id": layer_id, "reason": "filter", "filter": operation["filter"]}
        message = "This Krita has no such filter."
        raise BridgeError("UNSUPPORTED_CAPABILITY", message, False, details)
    size = info["size_px"]
    canvas = verification.scope(verification.FULL, first, layer_id, size)
    reads = mutation.verifiable(handle, info, effects, verification.FULL, canvas)
    frame = mutation.Mutation(
        port,
        handle,
        call,
        "layer.transform",
        LABELS[f"layer.transform.{kind}"],
        reads,
        data,
        {"layer_id": layer_id},
        "transform",
    )
    frame.read()
    # Read once Krita is idle, so a change it was still applying is not taken for this one.
    before = port.tree(document)
    moved = mutation.watched(before) != mutation.watched(first)
    if moved or _bounds(before, inside) != _bounds(first, inside):
        details = {"layer_id": layer_id}
        message = "The document changed as the call began; nothing was changed. Retry."
        raise BridgeError("INTERNAL_ERROR", message, True, details)
    # The bounds Krita scales and pivots on, read once it is idle.
    bounds = next(one for one in before["nodes"] if one["id"] == layer_id)["bounds_px"]
    if bounds["width"] <= 0 or bounds["height"] <= 0:
        details = {"layer_id": layer_id, "reason": "empty"}
        message = "The layer shows nothing, so it has no bounds to transform about."
        raise BridgeError("INVALID_ARGUMENT", message, False, details)
    _refuse_no_change(operation, bounds, layer_id)
    pivot = [bounds["x"] + bounds["width"] / 2, bounds["y"] + bounds["height"] / 2]
    devices = [
        one for one in before["nodes"] if one["id"] in inside and one["type"] == "paintlayer"
    ]
    rects = _rects(devices, operation, bounds, pivot, layer_id)
    kept = [Kept(port, document, one, rects[one["id"]]) for one in devices]
    loose = {one: {"offset_px"} for one in inside}

    def change(steps: mutation.Steps) -> dict[str, Any]:
        port.transform_node(document, layer_id, operation, pivot)
        port.refresh(document)
        after: dict[str, Any] = port.tree(document)
        return after

    def witness_of() -> Witness | None:
        for device in kept:
            found = device.moved(port, document)
            if found is not None:
                return found
        return None

    def judge(applied: mutation.Applied) -> None:
        after = applied.value
        verdict = applied.verdict
        assert verdict is not None
        moved = drift(before, after, (), loose)
        if _ids(after) != _ids(before) or moved:
            details = {"layer_id": layer_id, "layer_ids": moved}
            raise BridgeError(
                "INTERNAL_ERROR", "Krita changed the document otherwise.", False, details
            )
        now = {one["id"]: one["bounds_px"] for one in after["nodes"]}
        escaped = sorted(device.node_id for device in kept if not device.holds(now[device.node_id]))
        if escaped:
            details = {"layer_id": layer_id, "layer_ids": escaped}
            message = "Krita took a layer's pixels past where the transform could follow them."
            raise BridgeError("INTERNAL_ERROR", message, False, details)
        if applied.steps.sealed:
            if verdict.changed_px:
                details = {"layer_id": layer_id}
                message = "The composite changed, yet none of the layer's own pixels did."
                raise BridgeError("INTERNAL_ERROR", message, False, details)
            details = {"layer_id": layer_id, "reason": "no_change"}
            message = "The transform changed no pixel."
            raise BridgeError("INVALID_ARGUMENT", message, False, details)
        if verdict.leaked:
            message = (
                "The transform changed the composite where protection forbids it (outside the "
                "allowed mask, or its alpha under preserve_composite_alpha)."
            )
            raise BridgeError("PROTECTED_REGION_CHANGED", message)

    def back() -> bool:
        now = port.tree(document)
        if _ids(now) != _ids(before) or drift(before, now, (), loose):
            return False
        found = {one["id"]: one["bounds_px"] for one in now["nodes"]}
        return all(device.held(port, document, found.get(device.node_id)) for device in kept)

    applied = frame.run(change, judge, back, tree=before, witness_of=witness_of)
    after = next(one for one in applied.value["nodes"] if one["id"] == layer_id)
    result: dict[str, Any] = {
        "document_id": handle.document_id,
        "layer_id": layer_id,
        "type": kind,
    }
    if kind == SCALE:
        result["size_px"] = list(operation["size_px"])
    else:
        result["degrees"] = operation["degrees"]
    result.update(
        {
            "filter": operation["filter"] if kind == SCALE else FIXED[kind],
            "pivot_px": pivot,
            "bounds_before_px": bounds,
            "bounds_after_px": after["bounds_px"],
            "undo_steps": len(frame.labels),
            "verification": frame.files(applied),
        }
    )
    return result


class Kept:
    # A paint layer's bounds, and a digest read over where it is and goes: never padded (K54).
    def __init__(
        self, port: DocumentsPort, document: Any, node: dict[str, Any], rect: dict[str, int] | None
    ) -> None:
        self.node_id: str = node["id"]
        self.bounds: dict[str, int] = node["bounds_px"]
        self.rect = rect
        self.digest = None if rect is None else self.read(port, document)

    def read(self, port: DocumentsPort, document: Any) -> str:
        assert self.rect is not None
        [buffer] = port.layer_rects(document, self.node_id, [self.rect])
        return _sha(memoryview(buffer).cast("B"))

    def moved(self, port: DocumentsPort, document: Any) -> Witness | None:
        # The witness over the rect, when the layer's bytes there are not as they were.
        if self.rect is None or self.digest is None:
            return None
        after = self.read(port, document)
        if after == self.digest:
            return None
        return self.node_id, self.rect, self.digest, after

    def holds(self, now: dict[str, int]) -> bool:
        # The layer's bounds after the change lie inside the rect, or it is still empty.
        if self.rect is None:
            return not _area(now)
        return not _area(now) or union([now, self.rect]) == self.rect

    def held(self, port: DocumentsPort, document: Any, now: dict[str, int] | None) -> bool:
        # The layer is as it was: the same bounds, and the same bytes over the rect.
        if now != self.bounds:
            return False
        return self.rect is None or self.read(port, document) == self.digest


def keeps_size(bounds: dict[str, int], degrees: list[float]) -> bool:
    # Krita's own test before a shear (kis_image.cc shearImpl): the bounds mapped by its shear,
    # x then y, and rounded as QTransform::mapRect rounds them, keep their size, so Krita
    # changes nothing and pushes no step.
    shear_x = math.tan(degrees[0] * (math.pi / 180.0))
    shear_y = math.tan(degrees[1] * (math.pi / 180.0))
    x, y, width, height = bounds["x"], bounds["y"], bounds["width"], bounds["height"]
    corners = ((x, y), (x + width, y), (x + width, y + height), (x, y + height))
    xs = [cx + shear_x * cy for cx, cy in corners]
    ys = [shear_y * cx + (1.0 + shear_x * shear_y) * cy for cx, cy in corners]
    mapped = (
        _round(max(xs)) - _round(min(xs)),
        _round(max(ys)) - _round(min(ys)),
    )
    return mapped == (width, height)


def mapped(
    rect: dict[str, int], operation: dict[str, Any], target: dict[str, int], pivot: list[float]
) -> dict[str, int]:
    # Where the operation takes a rect about the pivot, as Krita turns, shears and scales
    # (K54), widened past any filter's reach.
    kind = operation["type"]
    reach = REACH
    if kind == SCALE:
        scale_x = operation["size_px"][0] / target["width"]
        scale_y = operation["size_px"][1] / target["height"]
        reach = math.ceil(REACH * max(1.0, scale_x, scale_y))

        def point(x: float, y: float) -> tuple[float, float]:
            return scale_x * x, scale_y * y

    elif kind == ROTATE:
        turn = math.radians(operation["degrees"])
        cos, sin = math.cos(turn), math.sin(turn)

        def point(x: float, y: float) -> tuple[float, float]:
            return x * cos - y * sin, x * sin + y * cos

    else:
        shear_x = math.tan(math.radians(operation["degrees"][0]))
        shear_y = math.tan(math.radians(operation["degrees"][1]))

        def point(x: float, y: float) -> tuple[float, float]:
            return x + shear_x * y, shear_y * x + (1.0 + shear_x * shear_y) * y

    xs, ys = [], []
    for cx in (rect["x"], rect["x"] + rect["width"]):
        for cy in (rect["y"], rect["y"] + rect["height"]):
            mx, my = point(cx - pivot[0], cy - pivot[1])
            xs.append(mx + pivot[0])
            ys.append(my + pivot[1])
    pad = reach + SLACK
    left, top = math.floor(min(xs)) - pad, math.floor(min(ys)) - pad
    right, bottom = math.ceil(max(xs)) + pad, math.ceil(max(ys)) + pad
    return {"x": left, "y": top, "width": right - left, "height": bottom - top}


def _refuse_kinds(tree: dict[str, Any], layer_id: str, inside: list[str]) -> None:
    found = {one["id"]: one for one in tree["nodes"]}
    # A transform mask's params would be remapped with the rest (K54), and one on a group
    # holding the layer recalculates around it.
    held = [one for one in line(found, layer_id) if one != layer_id]
    masks = sorted(
        one["id"]
        for one in tree["nodes"]
        if one["type"] == TRANSFORM_MASK and (one["id"] in inside or one["parent_id"] in held)
    )
    if masks:
        details: dict[str, Any] = {
            "layer_id": layer_id,
            "reason": "transform_mask",
            "transform_mask_ids": masks,
        }
        message = (
            "The layer holds a transform mask, or is in a translated group, so it is not "
            "transformed; scale, rotate or shear before translating."
        )
        raise BridgeError("UNSUPPORTED_CAPABILITY", message, False, details)
    other = sorted(one for one in inside if found[one]["type"] not in TAKES)
    if other:
        details = {
            "layer_id": layer_id,
            "reason": "node_type",
            "layer_ids": other,
            "layer_types": sorted({found[one]["type"] for one in other}),
        }
        message = "A transform takes only paint layers and groups, and the layer holds others."
        raise BridgeError("UNSUPPORTED_CAPABILITY", message, False, details)
    for flag in ("locked", "alpha_locked"):
        flagged = sorted(one for one in inside if found[one][flag])
        if flagged:
            details = {"layer_id": layer_id, "reason": flag, "layer_ids": flagged}
            noun = flag.replace("_", "-")
            message = f"A layer here is {noun}; unlock it with krita_layer_update first."
            raise BridgeError("INVALID_ARGUMENT", message, False, details)
    if len(inside) > MAX_NODES:
        details = {"layer_id": layer_id, "reason": "too_many_nodes", "max_nodes": MAX_NODES}
        message = f"A transform takes at most {MAX_NODES} layers and groups."
        raise BridgeError("UNSUPPORTED_CAPABILITY", message, False, details)


def _refuse_no_change(operation: dict[str, Any], bounds: dict[str, int], layer_id: str) -> None:
    kind = operation["type"]
    same = (kind == SCALE and operation["size_px"] == [bounds["width"], bounds["height"]]) or (
        kind == SHEAR and keeps_size(bounds, operation["degrees"])
    )
    if same:
        details = {"layer_id": layer_id, "reason": "no_change", "bounds_px": bounds}
        message = (
            "size_px is the layer's own size, so nothing would change."
            if kind == SCALE
            else "The shear is too small to move the layer's edge by a pixel, so Krita would "
            "change nothing."
        )
        raise BridgeError("INVALID_ARGUMENT", message, False, details)


def _rects(
    devices: list[dict[str, Any]],
    operation: dict[str, Any],
    bounds: dict[str, int],
    pivot: list[float],
    layer_id: str,
) -> dict[str, dict[str, int] | None]:
    # Each paint layer's witness rect, or None for an empty one, which stays empty.
    rects: dict[str, dict[str, int] | None] = {}
    total = 0
    for device in devices:
        old = device["bounds_px"]
        if not _area(old):
            rects[device["id"]] = None
            continue
        rect = union([old, mapped(old, operation, bounds, pivot)])
        assert rect is not None
        rects[device["id"]] = rect
        total += _area(rect)
        if _area(rect) > MAX_READ_PIXELS or total > MAX_TOTAL_PIXELS:
            details = {
                "layer_id": layer_id,
                "reason": "too_large",
                "rect": rect,
                "max_read_pixels": MAX_READ_PIXELS,
                "max_total_pixels": MAX_TOTAL_PIXELS,
            }
            message = "The transform's reads would pass one read; Phase 1 cannot verify it."
            raise BridgeError("UNSUPPORTED_CAPABILITY", message, False, details)
    return rects


def _bounds(tree: dict[str, Any], inside: list[str]) -> dict[str, Any]:
    return {one["id"]: one["bounds_px"] for one in tree["nodes"] if one["id"] in inside}


def _ids(tree: dict[str, Any]) -> set[str]:
    return {one["id"] for one in tree["nodes"]}


def _area(rect: dict[str, int] | None) -> int:
    if rect is None or rect["width"] <= 0 or rect["height"] <= 0:
        return 0
    return rect["width"] * rect["height"]


def _round(value: float) -> int:
    # Qt 5's qRound.
    if value >= 0.0:
        return int(value + 0.5)
    return int(value - float(int(value - 1)) + 0.5) + int(value - 1)


def _sha(data: Any) -> str:
    return hashlib.sha256(data).hexdigest()


def _field(name: str) -> dict[str, Any]:
    return {"field": name}
