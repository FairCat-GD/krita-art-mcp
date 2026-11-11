from collections.abc import Collection
from pathlib import Path
from typing import Any

from . import mutation, nodes, verification
from .errors import BridgeError, exact
from .history import LABELS, MAX_STEPS
from .jobs import Call, Handler
from .opening import LAYER_ID
from .port import DocumentsPort
from .protection import MASK, refuse_held, refuse_held_line
from .registry import Handle, Registry
from .translations import TRANSFORM_MASK

CREATE_FIELDS = {"document_id", "parent_id", "above_id", "type", "name", "coverage"}
DUPLICATE_FIELDS = {"document_id", "layer_id", "name"}
REORDER_FIELDS = {"document_id", "layer_id", "parent_id", "above_id"}
REMOVE_FIELDS = {"document_id", "layer_id", "verify"}
# The node types an agent creates, as Node.type() names them.
KINDS = {"paint": "paintlayer", "group": "grouplayer", "transparency_mask": MASK}
COVERAGES = ("all", "none", "selection")
# A layer's name, as the schemas bound it.
MAX_NAME = 256


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
            LABELS["layer.create"],
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

    def duplicate(handle: Handle, args: dict[str, Any], call: Call) -> dict[str, Any]:
        # A hidden copy above its source: the composite cannot change, and a protected source
        # stays as it is (decision 13).
        document, layer_id, name = handle.document, args["layer_id"], args["name"]
        before = port.tree(document)
        source = _layer(before, layer_id, "duplicate")
        _refuse_transform_mask(before, layer_id)
        info = port.describe(document)
        effects = port.effects(document, True)
        # No verify to ask for: a spreading node widens the read to the canvas instead.
        mode = (
            verification.FULL
            if verification.reach(before, effects, layer_id)
            else verification.REGION
        )
        scope = verification.scope(mode, before, layer_id, info["size_px"])
        reads = mutation.verifiable(handle, info, effects, mode, scope)
        frame = mutation.Mutation(
            port,
            handle,
            call,
            "layer.duplicate",
            LABELS["layer.duplicate"],
            reads,
            data,
            {"layer_id": layer_id},
        )
        frame.read()

        def change(steps: mutation.Steps) -> tuple[str, dict[str, Any]]:
            copy = port.duplicate_node(document, layer_id, name)
            copy_id = port.attach(document, copy, source["parent_id"], layer_id)
            port.refresh(document)
            after = port.tree(document)
            steps.push(steps.of(after))
            return copy_id, after

        def judge(applied: mutation.Applied) -> dict[str, str]:
            copy_id, after = applied.value
            id_map = copied(before, after, layer_id, copy_id, name)
            verdict = applied.verdict
            assert verdict is not None
            if verdict.leaked:
                raise _leak("copy")
            if verdict.changed_px:
                details = {"layer_id": copy_id, "changed_px": verdict.changed_px}
                message = "The copy, which is hidden, changed the composite."
                raise BridgeError("INTERNAL_ERROR", message, False, details)
            return id_map

        def back() -> bool:
            return mutation.watched(port.tree(document)) == mutation.watched(before)

        applied = frame.run(change, judge, back, tree=before)
        copy_id, _ = applied.value
        return {
            "document_id": handle.document_id,
            "layer_id": copy_id,
            "derived_from": layer_id,
            "parent_id": source["parent_id"],
            "above_id": layer_id,
            "name": name,
            "visible": False,
            "id_map": applied.checked,
            "protected": False,
            "undo_steps": len(frame.labels),
            "verification": frame.files(applied),
        }

    def reorder(handle: Handle, args: dict[str, Any], call: Call) -> dict[str, Any]:
        # A remove, then each node added back: Krita's remove takes every node of the subtree
        # off its parent (K52). Each step is pushed before the next is taken, so a rollback
        # never has more than one to find.
        document, layer_id = handle.document, args["layer_id"]
        parent_id, above_id = args["parent_id"], args["above_id"]
        before = port.tree(document)
        node = _layer(before, layer_id, "reorder")
        refuse_held(before, layer_id, handle.protected)
        _placement(before, parent_id, above_id)
        moving = nodes.subtree(before, layer_id)
        if parent_id in moving:
            details: dict[str, Any] = {"layer_id": layer_id, "parent_id": parent_id}
            message = "A group cannot go inside itself."
            raise BridgeError("INVALID_ARGUMENT", message, False, details)
        effects = port.effects(document, True)
        _refuse_clone_source(effects, moving)
        # One step for the remove and one for each node added back, all within one history
        # call and Krita's undo stack, or no history call or rollback could take them whole.
        reach = min(MAX_STEPS, port.undo_limit())
        if 1 + len(moving) > reach:
            details = {
                "layer_id": layer_id,
                "reason": "too_many_nodes",
                "undo_steps": 1 + len(moving),
                "max_steps": reach,
            }
            message = (
                f"Moving these {len(moving)} nodes takes {1 + len(moving)} undo steps, more than "
                f"the {reach} history can take back at once; move fewer at a time."
            )
            raise BridgeError("UNSUPPORTED_CAPABILITY", message, False, details)
        below = nodes.children(before)
        expected = moved_order(below, layer_id, parent_id, above_id)
        result = {
            "document_id": handle.document_id,
            "layer_id": layer_id,
            "parent_id": parent_id,
            "above_id": above_id,
            "effective_order": expected,
        }
        if node["parent_id"] == parent_id and below.get(parent_id) == expected:
            # A successful guarded call dirties the document; Krita gets nothing.
            call.mark()
            handle.before_change()
            return {**result, "undo_steps": 0, "verification": None}
        info = port.describe(document)
        scope = verification.scope(verification.FULL, before, layer_id, info["size_px"])
        reads = mutation.verifiable(handle, info, effects, verification.FULL, scope)
        [remove, add] = LABELS["layer.reorder"]
        frame = mutation.Mutation(
            port,
            handle,
            call,
            "layer.reorder",
            (remove, *(add for _ in moving)),
            reads,
            data,
            {"layer_id": layer_id},
        )
        frame.read()
        places = _places(before, moving, parent_id, above_id)

        def change(steps: mutation.Steps) -> dict[str, Any]:
            # Each step's state from the tree's shape alone, a walk far cheaper than the tree.
            detached = port.remove_node(document, layer_id)
            steps.push(steps.of(port.structure(document)))
            for one in moving:
                port.attach(document, detached[one], *places[one])
                steps.push(steps.of(port.structure(document)))
            port.refresh(document)
            return port.tree(document)

        def judge(applied: mutation.Applied) -> None:
            problem = relocated(before, applied.value, layer_id, parent_id, expected)
            if problem is not None:
                raise problem
            assert applied.verdict is not None
            if applied.verdict.leaked:
                raise _leak("move")

        def back() -> bool:
            return mutation.watched(port.tree(document)) == mutation.watched(before)

        applied = frame.run(change, judge, back, tree=before)
        return {**result, "undo_steps": len(frame.labels), "verification": frame.files(applied)}

    def remove(handle: Handle, args: dict[str, Any], call: Call) -> dict[str, Any]:
        document, layer_id, mode = handle.document, args["layer_id"], args["verify"]
        before = port.tree(document)
        node = nodes.found(before, layer_id, "remove")
        if node["type"] == MASK:
            refuse_held_line(before, layer_id, handle.protected, "mask")
        elif node["type"].endswith("mask"):
            details: dict[str, Any] = {"layer_id": layer_id, "layer_type": node["type"]}
            message = "krita_layer_remove removes layers, groups and transparency masks."
            raise BridgeError("INVALID_ARGUMENT", message, False, details)
        else:
            refuse_held(before, layer_id, handle.protected)
        effects = port.effects(document, True)
        gone = nodes.subtree(before, layer_id)
        _refuse_clone_source(effects, gone)
        left = [
            one
            for one in nodes.children(before).get(before["root_id"], [])
            if one not in gone and not _kind(before, one).endswith("mask")
        ]
        if not left:
            details = {"layer_id": layer_id}
            message = "A document keeps at least one layer."
            raise BridgeError("INVALID_ARGUMENT", message, False, details)
        info = port.describe(document)
        if mode == verification.REGION:
            verification.refuse_reach(before, effects, layer_id, "this removal past its bounds")
        scope = verification.scope(mode, before, layer_id, info["size_px"])
        reads = mutation.verifiable(handle, info, effects, mode, scope)
        frame = mutation.Mutation(
            port,
            handle,
            call,
            "layer.remove",
            LABELS["layer.remove"],
            reads,
            data,
            {"layer_id": layer_id},
        )
        frame.read()

        def change(steps: mutation.Steps) -> dict[str, Any]:
            port.remove_node(document, layer_id)
            port.refresh(document)
            after = port.tree(document)
            steps.push(steps.of(after))
            return after

        def judge(applied: mutation.Applied) -> None:
            problem = removed(before, applied.value, gone)
            if problem is not None:
                raise problem
            assert applied.verdict is not None
            if applied.verdict.leaked:
                raise _leak("removal")

        def back() -> bool:
            return mutation.watched(port.tree(document)) == mutation.watched(before)

        applied = frame.run(change, judge, back, tree=before)
        return {
            "document_id": handle.document_id,
            "layer_id": layer_id,
            "removed": gone,
            "undo_steps": len(frame.labels),
            "verification": frame.files(applied),
        }

    guarded = registry.guarded(create)
    guarded_duplicate = registry.guarded(duplicate)
    guarded_reorder = registry.guarded(reorder)
    guarded_remove = registry.guarded(remove)

    def layer_duplicate(args: dict[str, Any], call: Call) -> dict[str, Any]:
        exact(args, DUPLICATE_FIELDS)
        _check_id(args["layer_id"], "layer_id")
        _check_name(args["name"])
        return guarded_duplicate(args, call)

    def layer_reorder(args: dict[str, Any], call: Call) -> dict[str, Any]:
        exact(args, REORDER_FIELDS)
        _check_id(args["layer_id"], "layer_id")
        if not isinstance(args["parent_id"], str) or not args["parent_id"]:
            raise BridgeError("INVALID_ARGUMENT", "parent_id is a non-empty string.")
        if args["above_id"] is not None:
            _check_id(args["above_id"], "above_id")
        reorder_rules(args["layer_id"], args["parent_id"], args["above_id"])
        return guarded_reorder(args, call)

    def layer_remove(args: dict[str, Any], call: Call) -> dict[str, Any]:
        exact(args, REMOVE_FIELDS)
        _check_id(args["layer_id"], "layer_id")
        if args["verify"] not in verification.MODES:
            raise BridgeError("INVALID_ARGUMENT", "verify is region or full.")
        return guarded_remove(args, call)

    def create_layer(args: dict[str, Any], call: Call) -> dict[str, Any]:
        exact(args, CREATE_FIELDS)
        if args["type"] not in KINDS:
            raise BridgeError("INVALID_ARGUMENT", "type is paint, group or transparency_mask.")
        if (args["type"] == "transparency_mask") != (args["coverage"] is not None):
            message = "coverage is given for a transparency mask, and only for one."
            raise BridgeError("INVALID_ARGUMENT", message, False, {"field": "coverage"})
        if args["coverage"] is not None and args["coverage"] not in COVERAGES:
            raise BridgeError("INVALID_ARGUMENT", "coverage is all, none or selection.")
        if not isinstance(args["parent_id"], str) or not args["parent_id"]:
            raise BridgeError("INVALID_ARGUMENT", "parent_id is a non-empty string.")
        _check_name(args["name"])
        if args["above_id"] is not None and (
            not isinstance(args["above_id"], str) or not LAYER_ID.match(args["above_id"])
        ):
            raise BridgeError("INVALID_ARGUMENT", "above_id is a layer id or null.")
        return guarded(args, call)

    return {
        "layer.create": create_layer,
        "layer.duplicate": layer_duplicate,
        "layer.reorder": layer_reorder,
        "layer.remove": layer_remove,
    }


def reorder_rules(layer_id: str, parent_id: str, above_id: str | None) -> None:
    # Argument rules, held on the server too (decision 10).
    if layer_id == parent_id:
        message = "A layer cannot go inside itself."
        raise BridgeError("INVALID_ARGUMENT", message, False, {"field": "parent_id"})
    if layer_id == above_id:
        message = "A layer cannot go above itself."
        raise BridgeError("INVALID_ARGUMENT", message, False, {"field": "above_id"})


def _check_name(value: Any) -> None:
    if not isinstance(value, str) or not 1 <= len(value) <= MAX_NAME:
        message = f"name is a string of 1 to {MAX_NAME} characters."
        raise BridgeError("INVALID_ARGUMENT", message, False, {"field": "name"})


def _check_id(value: Any, field: str) -> None:
    if not isinstance(value, str) or not LAYER_ID.match(value):
        raise BridgeError("INVALID_ARGUMENT", f"{field} is a layer id.", False, {"field": field})


def _layer(tree: dict[str, Any], layer_id: str, verb: str) -> dict[str, Any]:
    # A layer or a group; a mask goes with its layer.
    node = nodes.found(tree, layer_id, verb)
    if node["type"].endswith("mask"):
        details = {"layer_id": layer_id, "layer_type": node["type"]}
        message = f"krita_layer_{verb} takes layers and groups; a mask goes with its layer."
        raise BridgeError("INVALID_ARGUMENT", message, False, details)
    return node


def _kind(tree: dict[str, Any], node_id: str) -> str:
    kind: str = next(node["type"] for node in tree["nodes"] if node["id"] == node_id)
    return kind


def _refuse_clone_source(effects: dict[str, Any], inside: list[str]) -> None:
    # Krita turns a removed layer's clones into paint layers (K52), and a move starts with a
    # remove. A clone whose source Krita does not name may show one of these nodes.
    clones = sorted(
        clone_id
        for clone_id, source_id in effects["clones"].items()
        if source_id is None or source_id in inside
    )
    if clones:
        details = {"layer_id": inside[0], "reason": "clone_source", "clone_ids": clones}
        message = (
            "A clone layer shows this layer, and Krita turns such clones into paint layers when "
            "their source is removed or moved, so this is refused."
        )
        raise BridgeError("UNSUPPORTED_CAPABILITY", message, False, details)


def _refuse_transform_mask(tree: dict[str, Any], layer_id: str) -> None:
    # Undoing the attach of a copied transform mask crashes Krita in its cache rebuild (K53), and
    # a rollback undoes that attach.
    kinds = {node["id"]: node["type"] for node in tree["nodes"]}
    copied = [one for one in nodes.subtree(tree, layer_id) if kinds[one] == TRANSFORM_MASK]
    if copied:
        details = {"layer_id": layer_id, "reason": "transform_mask", "transform_mask_ids": copied}
        message = (
            "The layer holds a transform mask, and undoing a copy of one crashes Krita, so it is "
            "not copied; copy a layer before translating it."
        )
        raise BridgeError("UNSUPPORTED_CAPABILITY", message, False, details)


def _leak(noun: str) -> BridgeError:
    # The counts go in details.verification.
    message = (
        f"The {noun} changed the composite where protection forbids it (outside the allowed "
        "mask, or its alpha under preserve_composite_alpha)."
    )
    return BridgeError("PROTECTED_REGION_CHANGED", message)


def _places(
    tree: dict[str, Any], moving: list[str], parent_id: str, above_id: str | None
) -> dict[str, tuple[str, str | None]]:
    # Where each node goes back: the moved one where it was asked, each node inside it on top
    # of its own parent, which is empty until its children come back, in child order.
    parents = {node["id"]: node["parent_id"] for node in tree["nodes"]}
    places: dict[str, tuple[str, str | None]] = {one: (parents[one], None) for one in moving}
    places[moving[0]] = (parent_id, above_id)
    return places


def moved_order(
    below: dict[str, list[str]], layer_id: str, parent_id: str, above_id: str | None
) -> list[str]:
    # The parent's children by rank once the node is there, bottom first: directly above
    # above_id, or on top, as addChildNode places it. below is nodes.children of the tree.
    kids = [one for one in below.get(parent_id, []) if one != layer_id]
    at = len(kids) if above_id is None else kids.index(above_id) + 1
    return [*kids[:at], layer_id, *kids[at:]]


def drift(
    before: dict[str, Any],
    after: dict[str, Any],
    placed: Collection[str] = (),
    loose: dict[str, set[str]] | None = None,
    now: dict[str, list[str]] | None = None,
) -> list[str]:
    # Ids whose watched fields moved, beyond the fields loose allows, and parents whose children
    # changed their order; placed nodes' places are checked by the caller, and a node gone or
    # new by the caller too. now is nodes.children of after, when the caller has it.
    loose = loose or {}
    old, new = mutation.watched(before), mutation.watched(after)
    moved = {
        node_id
        for node_id, values in old.items()
        if node_id in new
        and any(
            values[key] != new[node_id][key]
            for key in values
            if key != "order" and key not in loose.get(node_id, set())
        )
    }
    was = nodes.children(before)
    now = nodes.children(after) if now is None else now
    for parent in set(was) | set(now):
        kept = [one for one in was.get(parent, []) if one not in placed and one in new]
        found = [one for one in now.get(parent, []) if one not in placed and one in old]
        if kept != found:
            moved.add(parent)
    return sorted(moved)


def copied(
    before: dict[str, Any], after: dict[str, Any], source_id: str, copy_id: str, name: str
) -> dict[str, str]:
    # The copy's subtree is all that was added, hidden and directly above its source, node for
    # node like the source's; nothing else moved. Returns each source id's copy.
    old_ids = {node["id"] for node in before["nodes"]}
    new_ids = {node["id"] for node in after["nodes"]}
    source = nodes.subtree(before, source_id)
    copy = nodes.subtree(after, copy_id) if copy_id in new_ids else []
    id_map = dict(zip(source, copy, strict=False))
    old, new = mutation.watched(before), mutation.watched(after)
    now = nodes.children(after)
    problem = (
        len(copy) != len(source)
        or new_ids - old_ids != set(copy)
        or old_ids - new_ids
        or new[copy_id]["parent_id"] != old[source_id]["parent_id"]
        or (new[copy_id]["name"], new[copy_id]["visible"]) != (name, False)
        or now[old[source_id]["parent_id"]].index(copy_id)
        != now[old[source_id]["parent_id"]].index(source_id) + 1
    )
    if not problem:
        for source_node, copy_node in id_map.items():
            mine, theirs = new[copy_node], old[source_node]
            skip = {"order", "parent_id"} | ({"name", "visible"} if copy_node == copy_id else set())
            if any(mine[key] != theirs[key] for key in mine if key not in skip):
                problem = True
            if copy_node != copy_id and mine["parent_id"] != id_map.get(theirs["parent_id"]):
                problem = True
    moved = drift(before, after, now=now)
    if problem or moved:
        details = {"layer_id": copy_id, "derived_from": source_id, "layer_ids": moved}
        message = "Krita's copy is not the source's, or not where it was asked for."
        raise BridgeError("INTERNAL_ERROR", message, False, details)
    return id_map


def relocated(
    before: dict[str, Any],
    after: dict[str, Any],
    layer_id: str,
    parent_id: str,
    expected: list[str],
) -> BridgeError | None:
    # The node is exactly where it was asked for, and nothing else moved.
    old_ids = {node["id"] for node in before["nodes"]}
    new_ids = {node["id"] for node in after["nodes"]}
    now = nodes.children(after)
    moved = drift(before, after, {layer_id}, {layer_id: {"parent_id"}}, now)
    if (
        old_ids != new_ids
        or mutation.watched(after)[layer_id]["parent_id"] != parent_id
        or now.get(parent_id) != expected
        or moved
    ):
        details = {
            "layer_id": layer_id,
            "added": sorted(new_ids - old_ids),
            "gone": sorted(old_ids - new_ids),
            "layer_ids": moved,
        }
        return BridgeError("INTERNAL_ERROR", "Krita moved the layer elsewhere.", False, details)
    return None


def removed(before: dict[str, Any], after: dict[str, Any], gone: list[str]) -> BridgeError | None:
    # Exactly the node and its subtree are gone, and nothing else moved.
    old_ids = {node["id"] for node in before["nodes"]}
    new_ids = {node["id"] for node in after["nodes"]}
    moved = drift(before, after)
    if new_ids != old_ids - set(gone) or moved:
        details = {
            "removed": sorted(old_ids - new_ids),
            "added": sorted(new_ids - old_ids),
            "layer_ids": moved,
        }
        message = "Krita removed other than the layer asked for."
        return BridgeError("INTERNAL_ERROR", message, False, details)
    return None


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
