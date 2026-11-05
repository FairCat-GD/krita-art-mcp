import functools
import hashlib
from pathlib import Path
from typing import Any

from . import masks, verification
from .errors import BridgeError, exact
from .jobs import Call, Handler
from .opening import LAYER_ID
from .port import DocumentsPort
from .rects import inside
from .registry import Handle, Registry

PROTECTION_FIELDS = {
    "document_id",
    "protected_layer_ids",
    "allowed_change_mask",
    "preserve_composite_alpha",
    "preserve_canvas",
}
MAX_PROTECTED = 1024
# Krita's name for a transparency mask, the one mask an agent creates and paints.
MASK = "transparencymask"


def refuse_held_line(tree: dict[str, Any], node_id: str, protected: set[str], noun: str) -> None:
    # A mask changes how its layer shows without changing the layer's pixels, so the node, its
    # parent and every ancestor must be unprotected.
    nodes = {node["id"]: node for node in tree["nodes"]}
    held, current = [], node_id
    while current in nodes:
        if current in protected:
            held.append(current)
        current = nodes[current]["parent_id"]
    if held:
        details = {"layer_id": node_id, "protected_layer_ids": sorted(held)}
        message = f"The {noun}, its layer or a group holding it is protected."
        raise BridgeError("LOCKED_TARGET", message, False, details)


def loosened(current: bytes | None, new: bytes | None) -> int:
    # How many pixels the new allowed mask would allow that the current one does not; None
    # allows the whole canvas. Whole-buffer integer operations, never a loop per pixel.
    if current is None:
        return 0
    if new is None:
        return len(current) - current.count(b"\xff")
    extra = int.from_bytes(new, "big") & ~int.from_bytes(current, "big")
    return extra.bit_count() // 8


def summary(mask: bytes, width: int) -> dict[str, Any]:
    left, right, rows = width, 0, []
    for start in range(0, len(mask), width):
        first = mask.find(b"\xff", start, start + width)
        if first >= 0:
            rows.append(start // width)
            left = min(left, first - start)
            right = max(right, mask.rfind(b"\xff", start, start + width) - start + 1)
    bounds = {"x": 0, "y": 0, "width": 0, "height": 0}
    if rows:
        bounds = {"x": left, "y": rows[0], "width": right - left, "height": rows[-1] - rows[0] + 1}
    return {
        "sha256": hashlib.sha256(mask).hexdigest(),
        "bounds_px": bounds,
        "allowed_pixels": mask.count(b"\xff"),
    }


def handlers(registry: Registry, port: DocumentsPort, data: Path) -> dict[str, Handler]:
    def protect(
        handle: Handle, args: dict[str, Any], call: Call, mask: bytes | None
    ) -> dict[str, Any]:
        # Protection only tightens (invariant 4); it changes no pixels, so nothing is dirtied.
        ids = {node["id"] for node in port.tree(handle.document)["nodes"]}
        wanted = set(args["protected_layer_ids"])
        unknown = sorted(wanted - ids)
        if unknown:
            details: dict[str, Any] = {"missing": unknown}
            raise BridgeError("LAYER_NOT_FOUND", "No layer has that id.", False, details)
        dropped = sorted((handle.protected & ids) - wanted)
        if dropped:
            details = {"would_unprotect": dropped}
            message = (
                "protected_layer_ids must keep every protected layer: protection only tightens."
            )
            raise BridgeError("INVALID_ARGUMENT", message, False, details)
        flags = {
            "preserve_composite_alpha": handle.preserve_composite_alpha,
            "preserve_canvas": handle.preserve_canvas,
        }
        cleared = [name for name, on in flags.items() if on and not args[name]]
        if cleared:
            details = {"would_clear": cleared}
            message = "A preservation flag that is on stays on: protection only tightens."
            raise BridgeError("INVALID_ARGUMENT", message, False, details)
        size = port.describe(handle.document)["size_px"]
        new = None
        value = args["allowed_change_mask"]
        if value is not None and mask is not None:
            masks.source(data, value, "allowed_change_mask")
            rect = masks.box(value)
            inside(rect, size, "allowed_change_mask")
            # A PNG maps pixel for pixel onto the canvas, so it must be the canvas's size.
            if value["source_path"] is not None and [rect["width"], rect["height"]] != size:
                details = {"size_px": [rect["width"], rect["height"]], "canvas_px": size}
                message = "An allowed_change_mask PNG must be the canvas's size."
                raise BridgeError("INVALID_ARGUMENT", message, False, details)
            if mask.translate(None, b"\x00\xff"):
                message = "allowed_change_mask must hold only 0 and 255."
                raise BridgeError("INVALID_ARGUMENT", message)
            new = masks.on_canvas(mask, rect, size)
        current = handle.allowed_mask
        verification.check_mask_size(current, size)
        extra = loosened(current, new)
        if extra:
            details = {"loosened_px": extra}
            message = "The new allowed mask allows pixels the current one does not."
            raise BridgeError("INVALID_ARGUMENT", message, False, details)
        call.mark()
        # A protected node that has gone (a deselect removes the global selection's mask) is
        # dropped; every other one is in wanted.
        handle.protected = wanted
        handle.allowed_mask = new
        handle.allowed_summary = None if new is None else summary(new, size[0])
        handle.preserve_composite_alpha = args["preserve_composite_alpha"]
        handle.preserve_canvas = args["preserve_canvas"]
        # History never undoes a step made under the looser protection.
        handle.ledger.seal()
        return {
            "document_id": handle.document_id,
            "protected_layer_ids": sorted(wanted),
            "allowed_change_mask": handle.allowed_summary,
            "composite_outside_mask": "exact",
            "preserve_composite_alpha": handle.preserve_composite_alpha,
            "preserve_canvas": handle.preserve_canvas,
            "undo_steps": 0,
        }

    def protection_set(args: dict[str, Any], call: Call) -> dict[str, Any]:
        exact(args, PROTECTION_FIELDS)
        ids = args["protected_layer_ids"]
        if (
            not isinstance(ids, list)
            or len(ids) > MAX_PROTECTED
            or not all(isinstance(value, str) and LAYER_ID.match(value) for value in ids)
            or len(set(ids)) != len(ids)
        ):
            message = f"protected_layer_ids is a list of up to {MAX_PROTECTED} distinct layer ids."
            raise BridgeError("INVALID_ARGUMENT", message)
        for name in ("preserve_composite_alpha", "preserve_canvas"):
            if not isinstance(args[name], bool):
                raise BridgeError("INVALID_ARGUMENT", f"{name} is true or false.")
        value = args["allowed_change_mask"]
        mask = None
        if value is not None:
            masks.check(value, "allowed_change_mask")
            # Taken before any other refusal, so no refused call leaves its mask behind.
            mask = masks.take(data, value, call.request_id)
        return registry.guarded(functools.partial(protect, mask=mask))(args, call)

    return {"protection.set": protection_set}
