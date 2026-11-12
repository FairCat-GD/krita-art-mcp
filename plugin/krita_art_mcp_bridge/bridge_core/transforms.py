from pathlib import Path
from typing import Any

from . import affine, mutation, nodes, verification
from .errors import BridgeError, exact, integer
from .history import LABELS, refuse_cumulative
from .jobs import Call, Handler
from .layers import drift
from .opening import LAYER_ID
from .port import DocumentsPort
from .protection import line
from .registry import Handle, Registry
from .translations import MAX_TRANSLATE, TRANSFORM_MASK, translate_xml

TRANSFORM_FIELDS = {"document_id", "layer_id", "operation"}
OPERATION_FIELDS = {"type", "by_px"}
TRANSLATE = "translate"
# The node types a translate takes, as Node.type() names them.
TAKES = {"paintlayer", "grouplayer"}
MASK_NAME = "Translate"


def transform_rules(operation: Any) -> None:
    # Argument rules, held on the server too (decision 10).
    if not isinstance(operation, dict):
        raise BridgeError("INVALID_ARGUMENT", "operation is an object.", False, _field())
    kind = operation.get("type")
    if kind in affine.KINDS:
        affine.rules(operation)
        return
    if kind != TRANSLATE:
        message = "operation.type is translate, scale, rotate or shear."
        raise BridgeError("INVALID_ARGUMENT", message, False, _field())
    exact(operation, OPERATION_FIELDS)
    by = operation["by_px"]
    if (
        not isinstance(by, list)
        or len(by) != 2
        or not all(integer(value) and abs(value) <= MAX_TRANSLATE for value in by)
    ):
        message = f"by_px is [x, y], whole pixels from -{MAX_TRANSLATE} to {MAX_TRANSLATE}."
        raise BridgeError("INVALID_ARGUMENT", message, False, _field("by_px"))
    if by == [0, 0]:
        message = "by_px [0, 0] moves nothing."
        raise BridgeError("INVALID_ARGUMENT", message, False, _field("by_px"))


def handlers(registry: Registry, port: DocumentsPort, data: Path) -> dict[str, Handler]:
    def translate(handle: Handle, args: dict[str, Any], call: Call) -> dict[str, Any]:
        # A transform mask on top of the layer's masks holds the move, so the layer's own pixels
        # never change; Krita's undo takes back its attach and each params change.
        document, layer_id = handle.document, args["layer_id"]
        by = args["operation"]["by_px"]
        first = port.tree(document)
        node = nodes.found(first, layer_id, "translate")
        if node["type"] not in TAKES:
            details: dict[str, Any] = {"layer_id": layer_id, "layer_type": node["type"]}
            message = "krita_layer_transform takes paint layers and groups."
            raise BridgeError("INVALID_ARGUMENT", message, False, details)
        _refuse_held(first, layer_id, handle.protected)
        mask_id, was = _own_mask(first, layer_id)
        total = [was[0] + by[0], was[1] + by[1]]
        if not all(abs(value) <= MAX_TRANSLATE for value in total):
            details = {"layer_id": layer_id, "translation_px": list(was), "by_px": by}
            message = (
                f"The layer's whole translation would pass {MAX_TRANSLATE} px on an axis; it "
                f"stands at {list(was)}."
            )
            raise BridgeError("INVALID_ARGUMENT", message, False, details)
        refuse_cumulative(port, "translation")
        info = port.describe(document)
        size = info["size_px"]
        scope = verification.scope(verification.FULL, first, layer_id, size)
        effects = port.effects(document, False)
        reads = mutation.verifiable(handle, info, effects, verification.FULL, scope)
        labels = LABELS["layer.transform"]
        frame = mutation.Mutation(
            port,
            handle,
            call,
            "layer.transform",
            labels if mask_id is None else labels[1:],
            reads,
            data,
            {"layer_id": layer_id},
        )
        frame.read()
        # Read once Krita is idle, so a change it was still applying is not taken for this one.
        before = port.tree(document)
        if mutation.watched(before) != mutation.watched(first):
            details = {"layer_id": layer_id}
            message = "The document changed as the call began; nothing was changed. Retry."
            raise BridgeError("INTERNAL_ERROR", message, True, details)
        xml = translate_xml(total[0], total[1])

        def change(steps: mutation.Steps) -> tuple[str, dict[str, Any]]:
            target = mask_id
            if target is None:
                made = port.create_transform(document, MASK_NAME)
                target = port.attach(document, made, layer_id, None)
                steps.push(steps.of(port.structure(document)))
            port.set_transform(document, target, xml)
            port.refresh(document)
            after = port.tree(document)
            state = steps.of(after)
            # A step is pushed only once its state is seen to move, so a rollback never undoes
            # another unnamed step (a selection's, or an earlier translate's) in its place.
            held = next(node for node in after["nodes"] if node["id"] == target)["translation_px"]
            if state == steps.state or held != total:
                details = {"layer_id": layer_id, "transform_mask_id": target}
                message = "Krita did not take the translation as sent."
                raise BridgeError("INTERNAL_ERROR", message, False, details)
            steps.push(state)
            return target, after

        def judge(applied: mutation.Applied) -> None:
            target, after = applied.value
            problem = translated(before, after, layer_id, target, mask_id is None)
            if problem is not None:
                raise problem
            assert applied.verdict is not None
            if applied.verdict.leaked:
                message = (
                    "The translate changed the composite where protection forbids it (outside the "
                    "allowed mask, or its alpha under preserve_composite_alpha)."
                )
                raise BridgeError("PROTECTED_REGION_CHANGED", message)

        def back() -> bool:
            return mutation.watched(port.tree(document)) == mutation.watched(before)

        applied = frame.run(change, judge, back)
        target, _ = applied.value
        return {
            "document_id": handle.document_id,
            "layer_id": layer_id,
            "transform_mask_id": target,
            "created_mask": mask_id is None,
            "by_px": list(by),
            "translation_px": total,
            "undo_steps": len(frame.labels),
            "verification": frame.files(applied),
        }

    def transform(handle: Handle, args: dict[str, Any], call: Call) -> dict[str, Any]:
        if args["operation"]["type"] == TRANSLATE:
            return translate(handle, args, call)
        return affine.run(port, handle, args, call, data)

    guarded = registry.guarded(transform)

    def layer_transform(args: dict[str, Any], call: Call) -> dict[str, Any]:
        exact(args, TRANSFORM_FIELDS)
        if not isinstance(args["layer_id"], str) or not LAYER_ID.match(args["layer_id"]):
            message = "layer_id is a layer id."
            raise BridgeError("INVALID_ARGUMENT", message, False, _field("layer_id"))
        transform_rules(args["operation"])
        return guarded(args, call)

    return {"layer.transform": layer_transform}


def translated(
    before: dict[str, Any], after: dict[str, Any], layer_id: str, mask_id: str, made: bool
) -> BridgeError | None:
    # Exactly the translate's own mask was added, on top of the layer's children, or changed;
    # nothing else moved.
    old_ids = {node["id"] for node in before["nodes"]}
    new = {node["id"]: node for node in after["nodes"]}
    added = sorted(set(new) - old_ids)
    mask = new.get(mask_id)
    siblings = [node["order"] for node in after["nodes"] if node["parent_id"] == layer_id]
    moved = drift(before, after, {mask_id} if made else (), {mask_id: {"translation_px"}})
    if (
        added != ([mask_id] if made else [])
        or old_ids - set(new)
        or mask is None
        or (mask["type"], mask["parent_id"], mask["visible"]) != (TRANSFORM_MASK, layer_id, True)
        or (made and mask["order"] != max(siblings))
        or moved
    ):
        details = {"layer_id": layer_id, "added": added, "layer_ids": moved}
        return BridgeError("INTERNAL_ERROR", "Krita moved the layer otherwise.", False, details)
    return None


def _own_mask(tree: dict[str, Any], layer_id: str) -> tuple[str | None, list[int]]:
    # The layer's one transform mask and its translation, when a translate made it and it shows.
    found = [
        node
        for node in tree["nodes"]
        if node["parent_id"] == layer_id and node["type"] == TRANSFORM_MASK
    ]
    if not found:
        return None, [0, 0]
    details: dict[str, Any] = {"layer_id": layer_id, "reason": "transform_mask"}
    if len(found) > 1:
        details["transform_mask_ids"] = [node["id"] for node in found]
        message = "The layer holds more than one transform mask, so a translate is refused."
        raise BridgeError("UNSUPPORTED_CAPABILITY", message, False, details)
    mask = found[0]
    details["transform_mask_ids"] = [mask["id"]]
    moved: list[int] | None = mask["translation_px"]
    if moved is None:
        message = (
            "The layer's transform mask holds a transform no translate made, so it is left "
            "alone and the translate is refused."
        )
        raise BridgeError("UNSUPPORTED_CAPABILITY", message, False, details)
    if not mask["visible"]:
        details["reason"] = "hidden_transform_mask"
        message = "The layer's translate mask is hidden, so a translate would show nothing."
        raise BridgeError("UNSUPPORTED_CAPABILITY", message, False, details)
    return mask["id"], moved


def _refuse_held(tree: dict[str, Any], layer_id: str, protected: set[str]) -> None:
    # The move shows in the layer, everything under it and every group holding it, so none of
    # them may be protected (decision 14's rule for a mask, with the layer's own rule).
    found = {node["id"]: node for node in tree["nodes"]}
    below = {one for one in protected if one in found and layer_id in line(found, one)}
    above = {one for one in line(found, layer_id) if one in protected}
    held = sorted(below | above)
    if held:
        details = {"layer_id": layer_id, "protected_layer_ids": held}
        message = "The layer is protected, holds a protected layer, or is in a protected group."
        raise BridgeError("LOCKED_TARGET", message, False, details)


def _field(name: str = "operation") -> dict[str, Any]:
    return {"field": name}
