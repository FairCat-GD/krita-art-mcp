from typing import Any

from .errors import BridgeError, exact
from .history import DONE, LABELS, UNDO, in_front, move
from .jobs import Call, Handler
from .ledger import Step, fingerprint, node_states
from .opening import LAYER_ID
from .port import DocumentsPort
from .registry import Handle, Registry

CREATE_FIELDS = {"document_id", "parent_id", "above_id", "type", "name"}
# The layer types Phase 1 creates, as Node.type() names them; masks arrive in Phase 2.
KINDS = {"paint": "paintlayer", "group": "grouplayer"}


def handlers(registry: Registry, port: DocumentsPort) -> dict[str, Handler]:
    def create(handle: Handle, args: dict[str, Any], call: Call) -> dict[str, Any]:
        document = handle.document
        parent_id, above_id = args["parent_id"], args["above_id"]
        before = port.tree(document)
        _placement(before, parent_id, above_id)
        start = fingerprint(port, document)
        was = handle.before_change()
        try:
            layer_id = port.create_layer(
                document, parent_id, above_id, KINDS[args["type"]], args["name"]
            )
            after = port.tree(document)
            # Adding a layer leaves the selection alone, so its hash is not read again.
            end = (node_states(after), start[1])
        except BaseException:
            # Krita may hold a step the ledger cannot name; history stops below it.
            handle.ledger.seal()
            raise
        step = Step("layer.create", call.operation_id, LABELS["layer.create"], start, end)
        handle.ledger.push(step, port.undo_limit())
        problem = misplaced(before, after, layer_id, args, handle.protected)
        if problem is not None:
            _roll_back(handle, step, was, problem)
        return {
            "document_id": handle.document_id,
            "layer_id": layer_id,
            "parent_id": args["parent_id"],
            "above_id": above_id,
            "type": args["type"],
            "name": args["name"],
            "protected": False,
            "undo_steps": 1,
        }

    def _roll_back(handle: Handle, step: Step, was: bool, problem: BridgeError) -> None:
        # Invariant 5: native undo, confirmed, or the document is unsafe.
        with in_front(port, handle.document):
            outcome, seen, _ = move(port, handle, step, UNDO)
        if outcome == DONE:
            handle.ledger.rolled_back()
            handle.dirty = was
            problem.body["details"]["rolled_back"] = True
            raise problem
        handle.unsafe = True
        details = {**problem.body["details"], **seen, "rolled_back": False}
        message = "A layer Krita added wrongly could not be undone; the document is unsafe."
        raise BridgeError("ROLLBACK_FAILED", message, False, details)

    guarded = registry.guarded(create)

    def create_layer(args: dict[str, Any], call: Call) -> dict[str, Any]:
        exact(args, CREATE_FIELDS)
        if args["type"] not in KINDS:
            raise BridgeError("INVALID_ARGUMENT", "type is paint or group in Phase 1.")
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
