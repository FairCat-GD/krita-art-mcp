import logging
import math
from pathlib import Path
from typing import Any

from . import log, mutation, verification
from .errors import BridgeError, exact
from .history import LABELS, in_front
from .jobs import Call, Handler
from .nodes import found
from .opening import LAYER_ID
from .port import DocumentsPort
from .protection import MASK, refuse_held, refuse_held_line
from .registry import Handle, Registry
from .resources import BLEND_MODES

UPDATE_FIELDS = {"document_id", "layer_id", "properties", "verify"}
FLAGS = ("visible", "locked", "alpha_locked", "inherit_alpha")
PROPERTIES = {"name", "opacity", "blend_mode", "active", *FLAGS}
# The properties that change the composite, so each change of one is checked pixel by pixel.
APPEARANCE = {"visible", "opacity", "blend_mode", "inherit_alpha"}
# What a transparency mask takes: shown or not, and its name.
MASK_PROPERTIES = {"name", "visible"}


def handlers(registry: Registry, port: DocumentsPort, data: Path) -> dict[str, Handler]:
    def update(handle: Handle, args: dict[str, Any], call: Call) -> dict[str, Any]:
        document, layer_id, mode = handle.document, args["layer_id"], args["verify"]
        tree = port.tree(document)
        target = _target(tree, layer_id, handle.protected, args["properties"])
        wanted = _in_krita_terms(args["properties"])
        changes = {key: value for key, value in wanted.items() if key != "active"}
        changes = {key: value for key, value in changes.items() if target[key] != value}
        # The values the change overwrote, which a rollback writes back.
        old: dict[str, Any] = {}
        undoable: list[str] = []
        result = None
        final = tree
        if set(wanted) == {"active"}:
            # Only which layer the owner sees selected changes.
            handle.touched()
        else:
            reads = None
            if APPEARANCE & set(changes):
                info = port.describe(document)
                effects = port.effects(document, mode == verification.REGION)
                if mode == verification.REGION:
                    verification.refuse_reach(
                        tree, effects, layer_id, "this change past the layer's bounds"
                    )
                rect = verification.scope(mode, tree, layer_id, info["size_px"])
                reads = mutation.verifiable(handle, info, effects, mode, rect)
            labels = LABELS["layer.update"] if "blend_mode" in changes else ()
            frame = mutation.Mutation(
                port, handle, call, "layer.update", labels, reads, data, {"layer_id": layer_id}
            )
            if reads is not None:
                frame.read()

            def change(steps: mutation.Steps) -> dict[str, Any]:
                if "blend_mode" in changes:
                    old["blend_mode"] = target["blend_mode"]
                    port.set_blend(document, layer_id, changes["blend_mode"])
                    steps.push(steps.of(port.tree(document)))
                rest = {key: value for key, value in changes.items() if key != "blend_mode"}
                if rest:
                    old.update({key: target[key] for key in rest})
                    port.set_properties(document, layer_id, rest)
                if reads is not None:
                    port.refresh(document)
                changed = port.tree(document)
                moved = _moved(tree, changed, layer_id, changes)
                if moved:
                    details: dict[str, Any] = {"layer_ids": moved}
                    message = "Krita changed more than the asked properties."
                    raise BridgeError("INTERNAL_ERROR", message, False, details)
                return changed

            def judge(applied: mutation.Applied) -> None:
                if applied.verdict is not None and applied.verdict.leaked:
                    raise _leak()

            def back() -> bool:
                return mutation.watched(port.tree(document)) == mutation.watched(tree)

            def compensate() -> bool:
                # Property writes are no undo step (K22), so they are written back.
                rest = {key: value for key, value in old.items() if key != "blend_mode"}
                if rest:
                    port.set_properties(document, layer_id, rest)
                return bool(rest)

            applied = frame.run(change, judge, back, compensate, tree, bool(changes))
            final = applied.value
            undoable = ["blend_mode"] if applied.steps.pushed else []
            result = frame.files(applied)
        if args["properties"].get("active"):
            try:
                with in_front(port, document):
                    call.mark()
                    port.activate(document, layer_id)
            except BridgeError:
                if not old:
                    raise
                # Reported as it is: a verified change never fails over the selected layer.
                logging.getLogger(log.NAME).exception("the layer was not made active")
            final = port.tree(document)
        node = next(node for node in final["nodes"] if node["id"] == layer_id)
        return {
            "document_id": handle.document_id,
            "layer_id": layer_id,
            "effective_properties": {
                key: _reported(key, node, final) for key in args["properties"]
            },
            "undoable": undoable,
            "undo_steps": len(undoable),
            "verification": result,
        }

    guarded = registry.guarded(update)

    def layer_update(args: dict[str, Any], call: Call) -> dict[str, Any]:
        exact(args, UPDATE_FIELDS)
        if not isinstance(args["layer_id"], str) or not LAYER_ID.match(args["layer_id"]):
            raise BridgeError("INVALID_ARGUMENT", "layer_id is a layer id.")
        _check_properties(args["properties"])
        if args["verify"] not in verification.MODES:
            raise BridgeError("INVALID_ARGUMENT", "verify is region or full.")
        return guarded(args, call)

    return {"layer.update": layer_update}


def _check_properties(properties: Any) -> None:
    if not isinstance(properties, dict) or not properties or not set(properties) <= PROPERTIES:
        message = f"properties sets one or more of {', '.join(sorted(PROPERTIES))}."
        raise BridgeError("INVALID_ARGUMENT", message)
    for key, value in properties.items():
        if key == "name":
            good = isinstance(value, str) and bool(value)
        elif key == "opacity":
            good = (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
                and 0 <= value <= 1
            )
        elif key == "blend_mode":
            good = value in {mode for mode, _ in BLEND_MODES}
        elif key == "active":
            good = value is True
        else:
            good = isinstance(value, bool)
        if not good:
            raise BridgeError("INVALID_ARGUMENT", f"properties.{key} is malformed.")


def _in_krita_terms(properties: dict[str, Any]) -> dict[str, Any]:
    # Opacity is 0-255 in Krita; the effective value is reported back.
    wanted = dict(properties)
    if "opacity" in wanted:
        wanted["opacity"] = int(wanted["opacity"] * 255 + 0.5)
    return wanted


def _target(
    tree: dict[str, Any], layer_id: str, protected: set[str], properties: dict[str, Any]
) -> dict[str, Any]:
    node = found(tree, layer_id, "change")
    if node["type"] == MASK:
        refused = sorted(set(properties) - MASK_PROPERTIES)
        if refused:
            details = {"layer_id": layer_id, "layer_type": "transparency_mask", "fields": refused}
            message = "A transparency mask takes name and visible only."
            raise BridgeError("INVALID_ARGUMENT", message, False, details)
        refuse_held_line(tree, layer_id, protected, "mask")
        return node
    if node["type"].endswith("mask"):
        details = {"layer_id": layer_id, "layer_type": node["type"]}
        message = "krita_layer_update changes layers and transparency masks, not other masks."
        raise BridgeError("INVALID_ARGUMENT", message, False, details)
    refuse_held(tree, layer_id, protected)
    if "alpha_locked" in properties and node["type"] != "paintlayer":
        details = {"layer_id": layer_id, "layer_type": node["type"]}
        message = "alpha_locked applies to paint layers only."
        raise BridgeError("INVALID_ARGUMENT", message, False, details)
    return node


def _leak() -> BridgeError:
    # The counts go in details.verification.
    message = (
        "The change reached the composite where protection forbids it "
        "(outside the allowed mask, or its alpha under preserve_composite_alpha)."
    )
    return BridgeError("PROTECTED_REGION_CHANGED", message)


def _moved(
    before: dict[str, Any], after: dict[str, Any], layer_id: str, changes: dict[str, Any]
) -> list[str]:
    # The ids whose watched fields differ from what the change should leave.
    old, new = mutation.watched(before), mutation.watched(after)
    if set(old) != set(new):
        return sorted(set(old) ^ set(new))
    expected = {**old[layer_id], **changes}
    moved = [node_id for node_id in old if node_id != layer_id and old[node_id] != new[node_id]]
    if new[layer_id] != expected:
        moved.append(layer_id)
    return sorted(moved)


def _reported(key: str, node: dict[str, Any], tree: dict[str, Any]) -> Any:
    if key == "opacity":
        return node["opacity"] / 255
    if key == "active":
        return tree["active_id"] == node["id"]
    return node[key]
