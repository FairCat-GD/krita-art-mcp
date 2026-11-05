from pathlib import Path
from typing import Any

from . import mutation, verification
from .errors import BridgeError, exact
from .history import LABELS
from .jobs import Call, Handler
from .opening import LAYER_ID
from .port import DocumentsPort
from .protection import MASK, refuse_held_line
from .registry import Handle, Registry

CREATE_FIELDS = {"document_id", "parent_id", "above_id", "type", "name", "coverage"}
# The node types an agent creates, as Node.type() names them.
KINDS = {"paint": "paintlayer", "group": "grouplayer", "transparency_mask": MASK}
COVERAGES = ("all", "none", "selection")


def handlers(registry: Registry, port: DocumentsPort, data: Path) -> dict[str, Handler]:
    def create(handle: Handle, args: dict[str, Any], call: Call) -> dict[str, Any]:
        document = handle.document
        parent_id, above_id, coverage = args["parent_id"], args["above_id"], args["coverage"]
        before = port.tree(document)
        is_mask = args["type"] == "transparency_mask"
        if is_mask:
            _mask_placement(before, parent_id, above_id, handle.protected)
        else:
            _placement(before, parent_id, above_id)
        reads, rect, expected = None, None, b""
        if is_mask:
            info = port.describe(document)
            size = info["size_px"]
            # Where the mask can show: its layer's own pixels, which no mask moves.
            rect = verification.scope(verification.REGION, before, parent_id, size)
            area = rect["width"] * rect["height"]
            if coverage == "selection":
                if port.selection_bounds(document) is None:
                    details: dict[str, Any] = {"field": "coverage"}
                    message = "There is no selection to start the mask from; set one first."
                    raise BridgeError("INVALID_ARGUMENT", message, False, details)
                found = port.selection_rect(document, rect) if area else b""
                expected = b"" if found is None else bytes(found)
            else:
                expected = (b"\xff" if coverage == "all" else b"\x00") * area
            effects = port.effects(document, True)
            # No verify to ask for: a spreading node widens the read to the canvas instead.
            mode = (
                verification.FULL
                if verification.reach(before, effects, parent_id)
                else verification.REGION
            )
            scope = verification.scope(mode, before, parent_id, size)
            reads = mutation.verifiable(handle, info, effects, mode, scope)
        frame = mutation.Mutation(
            port,
            handle,
            call,
            "layer.create",
            (LABELS["layer.create"],),
            reads,
            data,
            {"parent_id": parent_id},
        )
        if reads is not None:
            frame.read()

        def change(steps: mutation.Steps) -> tuple[str, dict[str, Any]]:
            if is_mask:
                layer_id = port.create_mask(document, parent_id, above_id, args["name"], coverage)
                port.refresh(document)
            else:
                layer_id = port.create_layer(
                    document, parent_id, above_id, KINDS[args["type"]], args["name"]
                )
            after = port.tree(document)
            steps.push(steps.of(after))
            return layer_id, after

        def judge(applied: mutation.Applied) -> None:
            layer_id, after = applied.value
            problem = misplaced(before, after, layer_id, args, handle.protected)
            if problem is not None:
                raise problem
            if applied.verdict is not None and applied.verdict.leaked:
                message = (
                    "The mask changed the composite where protection forbids it (outside the "
                    "allowed mask, or its alpha under preserve_composite_alpha)."
                )
                raise BridgeError("PROTECTED_REGION_CHANGED", message)
            if rect is not None and expected:
                [found] = port.layer_rects(document, layer_id, [rect])
                if bytes(found) != expected:
                    details = {"layer_id": layer_id, "coverage": coverage}
                    message = "Krita's mask does not hold the coverage asked for."
                    raise BridgeError("INTERNAL_ERROR", message, False, details)

        def back() -> bool:
            return mutation.watched(port.tree(document)) == mutation.watched(before)

        applied = frame.run(change, judge, back)
        layer_id, _ = applied.value
        return {
            "document_id": handle.document_id,
            "layer_id": layer_id,
            "parent_id": args["parent_id"],
            "above_id": above_id,
            "type": args["type"],
            "name": args["name"],
            "coverage": coverage,
            "protected": False,
            "undo_steps": len(frame.labels),
            "verification": frame.files(applied),
        }

    guarded = registry.guarded(create)

    def create_layer(args: dict[str, Any], call: Call) -> dict[str, Any]:
        exact(args, CREATE_FIELDS)
        if args["type"] not in KINDS:
            raise BridgeError("INVALID_ARGUMENT", "type is paint, group or transparency_mask.")
        if (args["type"] == "transparency_mask") != (args["coverage"] is not None):
            message = "coverage is given for a transparency mask, and only for one."
            raise BridgeError("INVALID_ARGUMENT", message, False, {"field": "coverage"})
        if args["coverage"] is not None and args["coverage"] not in COVERAGES:
            raise BridgeError("INVALID_ARGUMENT", "coverage is all, none or selection.")
        for field in ("parent_id", "name"):
            if not isinstance(args[field], str) or not args[field]:
                raise BridgeError("INVALID_ARGUMENT", f"{field} is a non-empty string.")
        if args["above_id"] is not None and (
            not isinstance(args["above_id"], str) or not LAYER_ID.match(args["above_id"])
        ):
            raise BridgeError("INVALID_ARGUMENT", "above_id is a layer id or null.")
        return guarded(args, call)

    return {"layer.create": create_layer}


def _placement(tree: dict[str, Any], parent_id: str, above_id: str | None) -> None:
    # The root or a group holds layers; a protected group may take a new child.
    nodes = {node["id"]: node for node in tree["nodes"]}
    if parent_id != tree["root_id"]:
        parent = nodes.get(parent_id)
        if parent is None:
            details = {"layer_id": parent_id}
            raise BridgeError("LAYER_NOT_FOUND", "No layer has that id.", False, details)
        if parent["type"] != "grouplayer":
            details = {"parent_id": parent_id, "layer_type": parent["type"]}
            message = "A new layer goes in the root or in a group."
            raise BridgeError("INVALID_ARGUMENT", message, False, details)
    if above_id is not None:
        above = nodes.get(above_id)
        if above is None:
            details = {"layer_id": above_id}
            raise BridgeError("LAYER_NOT_FOUND", "No layer has that id.", False, details)
        if above["parent_id"] != parent_id or above["type"].endswith("mask"):
            details = {"above_id": above_id, "parent_id": parent_id}
            message = "above_id must be a layer directly inside parent_id."
            raise BridgeError("INVALID_ARGUMENT", message, False, details)


def _mask_placement(
    tree: dict[str, Any], parent_id: str, above_id: str | None, protected: set[str]
) -> None:
    # A transparency mask goes on a paint layer, among its masks, and the layer and every group
    # holding it must be unprotected (decision 14).
    nodes = {node["id"]: node for node in tree["nodes"]}
    parent = nodes.get(parent_id)
    if parent is None:
        details: dict[str, Any] = {"layer_id": parent_id}
        raise BridgeError("LAYER_NOT_FOUND", "No layer has that id.", False, details)
    if parent["type"] != "paintlayer":
        details = {"parent_id": parent_id, "layer_type": parent["type"]}
        message = "A transparency mask goes on a paint layer."
        raise BridgeError("INVALID_ARGUMENT", message, False, details)
    if above_id is not None:
        above = nodes.get(above_id)
        if above is None:
            details = {"layer_id": above_id}
            raise BridgeError("LAYER_NOT_FOUND", "No layer has that id.", False, details)
        if above["parent_id"] != parent_id or above["type"] != MASK:
            details = {"above_id": above_id, "parent_id": parent_id}
            message = "above_id must be a transparency mask directly on parent_id."
            raise BridgeError("INVALID_ARGUMENT", message, False, details)
    refuse_held_line(tree, parent_id, protected, "mask's layer")


def misplaced(
    before: dict[str, Any],
    after: dict[str, Any],
    layer_id: str,
    args: dict[str, Any],
    protected: set[str],
) -> BridgeError | None:
    # The new layer is where it was asked for, and nothing protected or its parent changed.
    old = {node["id"]: node for node in before["nodes"]}
    new = {node["id"]: node for node in after["nodes"]}
    added = sorted(set(new) - set(old))
    made = new.get(layer_id)
    if (
        added != [layer_id]
        or made is None
        or set(old) - set(new)
        or (made["parent_id"], made["type"], made["name"])
        != (args["parent_id"], KINDS[args["type"]], args["name"])
        or not _placed(new, made, args["above_id"])
    ):
        details = {"layer_id": layer_id, "added": added}
        return BridgeError("INTERNAL_ERROR", "Krita placed the layer elsewhere.", False, details)
    watched = sorted((protected | {args["parent_id"]}) & set(old))
    moved = [node_id for node_id in watched if _settled(old[node_id]) != _settled(new[node_id])]
    if moved:
        details = {"layer_ids": moved}
        message = "Adding the layer changed a protected layer's properties."
        return BridgeError("LOCKED_TARGET", message, False, details)
    return None


def _placed(nodes: dict[str, Any], made: dict[str, Any], above_id: str | None) -> bool:
    # Directly above above_id, or on top of the parent's children when it is null, as Krita's
    # addChildNode places it.
    if above_id is not None:
        above = nodes.get(above_id)
        return above is not None and made["order"] == above["order"] + 1
    others = [
        node["order"]
        for node in nodes.values()
        if node["parent_id"] == made["parent_id"] and node["id"] != made["id"]
    ]
    return all(made["order"] > order for order in others)


def _settled(node: dict[str, Any]) -> dict[str, Any]:
    # A sibling added below moves the others up; that is not a change.
    return {key: value for key, value in node.items() if key != "order"}
