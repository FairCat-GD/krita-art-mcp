import functools
from pathlib import Path
from typing import Any

from . import masks, paths, transfer
from .errors import BridgeError, exact, integer
from .history import LABELS
from .jobs import Call, Handler
from .ledger import Step, fingerprint, fingerprint_of, selection_state
from .pixels import paint_layer
from .port import DocumentsPort
from .rects import inside
from .registry import Handle, Registry

SELECTION_FIELDS = {
    "document_id",
    "combine",
    "shape",
    "grow_px",
    "shrink_px",
    "feather_px",
    "invert",
}
COMBINES = ("replace", "add", "subtract", "intersect")
MODIFIERS = ("grow_px", "shrink_px", "feather_px")
# Krita's grow, shrink and feather take whole pixels; the server holds an equal bound.
MAX_MODIFIER_PX = 256


def recipe(
    shape: dict[str, Any],
    args: dict[str, Any],
    rect: dict[str, int] | None,
    mask: bytes | None,
) -> list[tuple[Any, ...]]:
    # The steps the adapter runs, in this order: the shape, grow, shrink, feather, invert, then
    # the combine with the current selection, whose result is committed in one undo step.
    if shape["kind"] == "none":
        return [("clear",)]
    if shape["kind"] == "layer_alpha":
        steps: list[tuple[Any, ...]] = [("layer_alpha", shape["layer_id"])]
    elif shape["kind"] == "all":
        steps = [("all", rect)]
    else:
        steps = [("mask", rect, mask)]
    for field, name in zip(MODIFIERS, ("grow", "shrink", "feather"), strict=True):
        if args[field]:
            steps.append((name, args[field]))
    if args["invert"]:
        steps.append(("invert",))
    steps.append(("combine", args["combine"]))
    return steps


def handlers(registry: Registry, port: DocumentsPort, data: Path) -> dict[str, Handler]:
    def select(
        handle: Handle, args: dict[str, Any], call: Call, mask: bytes | None
    ) -> dict[str, Any]:
        document, shape = handle.document, args["shape"]
        size = port.describe(document)["size_px"]
        rect = None
        if shape["kind"] == "mask":
            masks.source(data, shape, "mask_uri")
            rect = masks.box(shape)
            inside(rect, size, "shape")
        elif shape["kind"] == "layer_alpha":
            paint_layer(port.tree(document), shape["layer_id"])
        elif shape["kind"] == "all":
            rect = {"x": 0, "y": 0, "width": size[0], "height": size[1]}
        selected = port.selection_bounds(document) is not None
        if args["combine"] in ("subtract", "intersect") and not selected:
            details = {"combine": args["combine"]}
            message = f"There is no selection to {args['combine']} with; use replace."
            raise BridgeError("INVALID_ARGUMENT", message, False, details)
        if shape["kind"] == "none" and not selected:
            # A successful guarded call dirties the document; Krita gets nothing.
            call.mark()
            handle.before_change()
            return {"document_id": handle.document_id, "selection": None, "undo_steps": 0}
        [label] = LABELS["selection.clear" if shape["kind"] == "none" else "selection.set"]
        start = fingerprint(port, document)
        call.mark()
        handle.before_change()
        try:
            port.set_selection(document, recipe(shape, args, rect, mask))
            state = selection_state(port, document, size)
            end = fingerprint_of(port.tree(document), state)
        except BridgeError:
            handle.ledger.seal()
            raise
        except BaseException:
            # Krita may hold a selection nothing confirmed, as in the frame.
            handle.lost()
            raise
        step = Step("selection.set", call.operation_id, label, start, end)
        handle.ledger.push(step, port.undo_limit())
        selection = None
        if state is not None:
            bounds, pixels = state
            spec = None
            if bounds["width"] > 0:
                folder = paths.transfer_dir(data)
                spec = transfer.write(folder, pixels, bounds["width"], bounds["height"], "A8")
            selection = {
                # Equal selections share an id: the fingerprint's hash of bounds and bytes.
                "selection_id": f"sel-{(end[1] or '')[:16]}",
                "bounds_px": bounds,
                "selected_pixels": len(pixels) - pixels.count(0),
                "pixels": spec,
            }
        return {"document_id": handle.document_id, "selection": selection, "undo_steps": 1}

    def set_selection(args: dict[str, Any], call: Call) -> dict[str, Any]:
        exact(args, SELECTION_FIELDS)
        shape = _check(args)
        # Taken before any other refusal, so no refused call leaves its mask behind.
        mask = masks.take(data, shape, call.request_id) if shape["kind"] == "mask" else None
        return registry.guarded(functools.partial(select, mask=mask))(args, call)

    return {"selection.set": set_selection}


def _check(args: dict[str, Any]) -> dict[str, Any]:
    if args["combine"] not in COMBINES:
        raise BridgeError("INVALID_ARGUMENT", f"combine is one of {', '.join(COMBINES)}.")
    for field in MODIFIERS:
        value = args[field]
        if not integer(value) or not 0 <= value <= MAX_MODIFIER_PX:
            message = f"{field} is a whole number of pixels from 0 to {MAX_MODIFIER_PX}."
            raise BridgeError("INVALID_ARGUMENT", message)
    if not isinstance(args["invert"], bool):
        raise BridgeError("INVALID_ARGUMENT", "invert is true or false.")
    shape = args["shape"]
    kind = shape.get("kind") if isinstance(shape, dict) else None
    if kind == "mask":
        masks.check({key: value for key, value in shape.items() if key != "kind"}, "shape")
    elif kind == "layer_alpha":
        if set(shape) != {"kind", "layer_id"} or not isinstance(shape["layer_id"], str):
            raise BridgeError("INVALID_ARGUMENT", "A layer_alpha shape names one layer.")
    elif kind not in ("all", "none") or set(shape) != {"kind"}:
        raise BridgeError("INVALID_ARGUMENT", "shape is a mask, layer_alpha, all or none.")
    if kind == "none" and (
        args["combine"] != "replace" or args["invert"] or any(args[f] for f in MODIFIERS)
    ):
        message = "Clearing the selection takes combine replace and no modifiers."
        raise BridgeError("INVALID_ARGUMENT", message)
    return dict(shape)
