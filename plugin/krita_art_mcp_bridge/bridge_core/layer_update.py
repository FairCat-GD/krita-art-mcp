import logging
import math
from pathlib import Path
from typing import Any

from . import log, verification
from .errors import BridgeError, exact
from .history import DONE, LABELS, UNDO, in_front, move, unconfirmed
from .jobs import Call, Handler
from .ledger import Step, fingerprint, node_states
from .opening import LAYER_ID
from .port import DocumentsPort
from .registry import Handle, Registry
from .resources import BLEND_MODES

UPDATE_FIELDS = {"document_id", "layer_id", "properties", "verify"}
FLAGS = ("visible", "locked", "alpha_locked", "inherit_alpha")
PROPERTIES = {"name", "opacity", "blend_mode", "active", *FLAGS}
# The properties that change the composite, so each change of one is checked pixel by pixel.
APPEARANCE = {"visible", "opacity", "blend_mode", "inherit_alpha"}
# What a property write leaves alone on every other node; bounds move with a group's projection.
WATCHED = (
    "name",
    "type",
    "parent_id",
    "order",
    "visible",
    "opacity",
    "blend_mode",
    "locked",
    "alpha_locked",
    "inherit_alpha",
    "offset_px",
)


def handlers(registry: Registry, port: DocumentsPort, data: Path) -> dict[str, Handler]:
    def update(handle: Handle, args: dict[str, Any], call: Call) -> dict[str, Any]:
        document, layer_id, mode = handle.document, args["layer_id"], args["verify"]
        tree = port.tree(document)
        target = _target(tree, layer_id, handle.protected, args["properties"])
        wanted = _in_krita_terms(args["properties"])
        changes = {key: value for key, value in wanted.items() if key != "active"}
        changes = {key: value for key, value in changes.items() if target[key] != value}
        rect, before, allowed = None, None, None
        if APPEARANCE & set(changes):
            info = port.describe(document)
            effects = port.effects(document, mode == verification.REGION)
            if mode == verification.REGION:
                verification.refuse_reach(
                    tree, effects, layer_id, "this change past the layer's bounds"
                )
            rect = verification.scope(mode, tree, layer_id, info["size_px"])
            verification.refuse_unverifiable(info, effects, rect)
            allowed = verification.allowed_rows(handle, info["size_px"], rect)
            # A projection left stale by a write elsewhere would read as this change.
            port.refresh(document)
            before = verification.read(port, document, rect)
        if set(wanted) == {"active"}:
            # Only which layer the owner sees selected changes (decision 27).
            was = handle.dirty
            handle.touched()
        else:
            was = handle.before_change()
        applied: dict[str, Any] = {}
        step: Step | None = None
        after, verdict = None, None
        problem: BridgeError | None = None
        # The tree as the change left it; tree stays the one the rollback must get back to.
        now: dict[str, Any] | None = None
        with unconfirmed(handle, bool(changes)):
            try:
                if "blend_mode" in changes:
                    applied["blend_mode"] = target["blend_mode"]
                    step, now = _blend(handle, tree, layer_id, changes["blend_mode"], call)
                rest = {key: value for key, value in changes.items() if key != "blend_mode"}
                if rest:
                    applied.update({key: target[key] for key in rest})
                    port.set_properties(document, layer_id, rest)
                    now = None
                if before is not None:
                    port.refresh(document)
                now = now or port.tree(document)
                moved = _moved(tree, now, layer_id, changes)
                if moved:
                    details: dict[str, Any] = {"layer_ids": moved}
                    message = "Krita changed more than the asked properties."
                    problem = BridgeError("INTERNAL_ERROR", message, False, details)
                elif before is not None and rect is not None:
                    after = verification.read(port, document, rect)
                    verdict = verification.check(
                        before, after, allowed, handle.preserve_composite_alpha
                    )
                    if verdict.leaked:
                        problem = _leak()
            except BridgeError as raised:
                problem = raised
            except Exception as raised:
                logging.getLogger(log.NAME).exception("layer.update raised mid-change")
                details = {"op": "layer.update", "raised": type(raised).__name__}
                message = "Krita raised during the change; see plugin.log."
                problem = BridgeError("INTERNAL_ERROR", message, False, details)
            if problem is not None:
                # Dropped first, so the re-read never holds two copies of the scope.
                after = None
                _roll_back(handle, args, tree, applied, step, before, rect, was, problem, verdict)
        if step is not None:
            step.region = None if verdict is None else verdict.changed_bounds_px
        result = None
        if before is not None and verdict is not None:
            result = verification.files(data, mode, before, after, verdict, False)
        if args["properties"].get("active"):
            try:
                with in_front(port, document):
                    port.activate(document, layer_id)
            except BridgeError:
                if not applied:
                    raise
                # Reported as it is: a verified change never fails over the selected layer.
                logging.getLogger(log.NAME).exception("the layer was not made active")
            now = None
        final = now or port.tree(document)
        node = next(node for node in final["nodes"] if node["id"] == layer_id)
        return {
            "document_id": handle.document_id,
            "layer_id": layer_id,
            "effective_properties": {
                key: _reported(key, node, final) for key in args["properties"]
            },
            "undoable": [] if step is None else ["blend_mode"],
            "undo_steps": 0 if step is None else 1,
            "verification": result,
        }

    def _blend(
        handle: Handle, tree: dict[str, Any], layer_id: str, mode: str, call: Call
    ) -> tuple[Step, dict[str, Any]]:
        start = fingerprint(port, handle.document, tree)
        try:
            port.set_blend(handle.document, layer_id, mode)
            after = port.tree(handle.document)
            # A blend change leaves the selection alone, so its hash is not read again.
            end = (node_states(after), start[1])
        except BaseException:
            # Krita may hold a step the ledger cannot name; history stops below it.
            handle.ledger.seal()
            raise
        step = Step("layer.update", call.operation_id, LABELS["layer.update"], start, end)
        handle.ledger.push(step, port.undo_limit())
        return step, after

    def _roll_back(
        handle: Handle,
        args: dict[str, Any],
        tree: dict[str, Any],
        applied: dict[str, Any],
        step: Step | None,
        before: verification.Reading | None,
        rect: dict[str, int] | None,
        was: bool,
        problem: BridgeError,
        verdict: verification.Verdict | None,
    ) -> None:
        # Invariant 5: undone, then confirmed by the scope and the tree, or the document is unsafe.
        rolled_back, confirmed = _restore(handle, args["layer_id"], tree, applied, step, before)
        details = {
            **problem.body["details"],
            "document_id": handle.document_id,
            "layer_id": args["layer_id"],
            "rolled_back": rolled_back,
            "rollback_verified": confirmed,
        }
        if verdict is not None and before is not None:
            details["verification"] = verification.files(
                data, args["verify"], before, None, verdict, True
            )
        if confirmed:
            handle.dirty = was
            # Never retryable: a retry under this request_id would make the change again.
            raise BridgeError(problem.body["code"], problem.body["message"], False, details)
        handle.unsafe = True
        details["cause"] = problem.body["code"]
        message = "The change could not be undone and confirmed; the document is unsafe. Reopen it."
        raise BridgeError("ROLLBACK_FAILED", message, False, details)

    def _restore(
        handle: Handle,
        layer_id: str,
        tree: dict[str, Any],
        applied: dict[str, Any],
        step: Step | None,
        before: verification.Reading | None,
    ) -> tuple[bool, bool]:
        # Whether the restore ran, and whether the document was confirmed as it was.
        document = handle.document
        try:
            undone = True
            if step is not None:
                with in_front(port, document):
                    outcome, _, _ = move(port, handle, step, UNDO, step.after)
                if outcome == DONE:
                    handle.ledger.rolled_back()
                else:
                    undone = False
            elif (
                "blend_mode" in applied
                and _node(port.tree(document), layer_id)["blend_mode"] != applied["blend_mode"]
            ):
                # The blend changed without a step the ledger holds; history is sealed already.
                port.set_blend(document, layer_id, applied["blend_mode"])
            rest = {key: value for key, value in applied.items() if key != "blend_mode"}
            if rest:
                port.set_properties(document, layer_id, rest)
            if APPEARANCE & set(applied):
                port.refresh(document)
            back = _watched(port.tree(document)) == _watched(tree)
            if before is not None:
                back = back and verification.same(
                    before, verification.read(port, document, before.rect)
                )
            return undone, undone and back
        except Exception:
            logging.getLogger(log.NAME).exception("layer.update's rollback raised")
            return False, False

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
    if layer_id == tree["root_id"]:
        details: dict[str, Any] = {"layer_id": layer_id}
        raise BridgeError("INVALID_ARGUMENT", "The root is not a layer to change.", False, details)
    nodes: dict[str, dict[str, Any]] = {node["id"]: node for node in tree["nodes"]}
    node = nodes.get(layer_id)
    if node is None:
        details = {"layer_id": layer_id}
        raise BridgeError("LAYER_NOT_FOUND", "No layer has that id.", False, details)
    if node["type"].endswith("mask"):
        details = {"layer_id": layer_id, "layer_type": node["type"]}
        message = "krita_layer_update changes layers; masks arrive in Phase 2."
        raise BridgeError("INVALID_ARGUMENT", message, False, details)
    held = sorted(
        node_id
        for node_id in protected
        if node_id in nodes and (node_id == layer_id or _inside(nodes, node_id, layer_id))
    )
    if held:
        details = {"layer_id": layer_id, "protected_layer_ids": held}
        message = "The layer is protected, or holds a protected layer."
        raise BridgeError("LOCKED_TARGET", message, False, details)
    if "alpha_locked" in properties and node["type"] != "paintlayer":
        details = {"layer_id": layer_id, "layer_type": node["type"]}
        message = "alpha_locked applies to paint layers only."
        raise BridgeError("INVALID_ARGUMENT", message, False, details)
    return node


def _inside(nodes: dict[str, Any], node_id: str, ancestor_id: str) -> bool:
    parent = nodes[node_id]["parent_id"]
    while parent in nodes:
        if parent == ancestor_id:
            return True
        parent = nodes[parent]["parent_id"]
    return False


def _leak() -> BridgeError:
    # The counts go in details.verification.
    message = (
        "The change reached the composite where protection forbids it "
        "(outside the allowed mask, or its alpha under preserve_composite_alpha)."
    )
    return BridgeError("PROTECTED_REGION_CHANGED", message)


def _node(tree: dict[str, Any], layer_id: str) -> dict[str, Any]:
    found: dict[str, Any] = next(node for node in tree["nodes"] if node["id"] == layer_id)
    return found


def _watched(tree: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {node["id"]: {key: node[key] for key in WATCHED} for node in tree["nodes"]}


def _moved(
    before: dict[str, Any], after: dict[str, Any], layer_id: str, changes: dict[str, Any]
) -> list[str]:
    # The ids whose watched fields differ from what the change should leave.
    old, new = _watched(before), _watched(after)
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
