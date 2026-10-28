import os
from pathlib import Path
from typing import Any

from . import files, nodes, paths, roots
from .errors import BridgeError, exact, no_arguments, number
from .history import in_front
from .jobs import Call, Handler
from .pixels import check_rect
from .port import DocumentsPort
from .registry import Handle, Registry

EXPORT_FIELDS = {"document_id", "target_path"}
MASK_FIELDS = {"document_id", "layer_id", "rect"}
ACTIVATE_FIELDS = {"document_id", "node_id"}
TIMING_FIELDS = {"document_id", "trials"}
NODE_FIELDS = {"document_id", "kind", "layer_id"}
# The nodes that spread a change past a layer's bounds (decision 20), as add_node makes them.
NODE_KINDS = ("filter_layer", "filter_mask", "transform_mask", "clone_layer")
MAX_TRIALS = 20
VIEW_FIELDS = {"document_id", "view"}
VIEW_KEYS = {"zoom", "rotation_deg", "pan_px"}
BRUSH_READ_FIELDS = {"document_id", "action", "preset_ids"}
BRUSH_WRITE_FIELDS = {"document_id", "action", "state"}
MAX_PRESETS = 100


def require_inside_harness(data: Path, path: Any, field: str) -> str:
    # Harness ops build fixtures only in the harness's own folder (decision 20).
    real = roots.resolve(path, field)
    if not roots.inside(real, [os.path.realpath(paths.harness_dir(data))]):
        details = {"field": field}
        message = f"Harness ops work only in the harness folder; {field} is outside it."
        raise BridgeError("PATH_NOT_ALLOWED", message, False, details)
    return real


def handlers(registry: Registry, port: DocumentsPort, data: Path) -> dict[str, Handler]:
    def fixture(document_id: Any) -> Handle:
        registry.refuse_at_job_start()
        handle = registry.find(document_id)
        if not handle.owned or handle.path is None:
            message = "Harness ops take only documents the bridge opened."
            raise BridgeError("PATH_NOT_ALLOWED", message, False, {"field": "document_id"})
        require_inside_harness(data, handle.path, "document_id")
        return handle

    def export_kra(args: dict[str, Any], call: Call) -> dict[str, Any]:
        # A KRA fixture, written by Krita's own exporter. It changes nothing in the document,
        # so it takes no lease.
        exact(args, EXPORT_FIELDS)
        handle = fixture(args["document_id"])
        target = require_inside_harness(data, args["target_path"], "target_path")
        if not target.lower().endswith(".kra"):
            raise BridgeError("INVALID_ARGUMENT", "target_path must end in .kra.")
        if os.path.lexists(target):
            raise BridgeError("FILE_EXISTS", "target_path exists; nothing is overwritten.")
        with nodes.unmasked_view(port, handle.document):
            exported = port.export(handle.document, target)
        if not exported:
            message = "Krita did not export; an autosave may hold the document. Retry."
            raise BridgeError("BUSY", message, True)
        return {"target_path": target, "sha256": files.sha256_of(target)}

    def select_mask(args: dict[str, Any], call: Call) -> dict[str, Any]:
        # The K46 fixture: an active local selection mask. Like the export it takes no lease;
        # it builds a fixture, so it bypasses protection and leaves dirty alone.
        exact(args, MASK_FIELDS)
        handle = fixture(args["document_id"])
        rect = check_rect(args["rect"])
        if not isinstance(args["layer_id"], str):
            raise BridgeError("INVALID_ARGUMENT", "layer_id names a layer.")
        # setActiveNode acts only on the document in front.
        if port.front() != handle.document:
            raise BridgeError("INVALID_ARGUMENT", "The document must be in front.")
        try:
            overlay = port.add_active_mask(handle.document, args["layer_id"], rect)
        finally:
            # Adding the mask pushed an undo step the ledger cannot name.
            handle.ledger.seal()
            handle.touched()
        return {"document_id": handle.document_id, "overlay_seen": overlay}

    def activate(args: dict[str, Any], call: Call) -> dict[str, Any]:
        # The K46 fixture for any node, the global selection's mask included; no lease.
        exact(args, ACTIVATE_FIELDS)
        handle = fixture(args["document_id"])
        if not isinstance(args["node_id"], str):
            raise BridgeError("INVALID_ARGUMENT", "node_id names a node.")
        if port.front() != handle.document:
            raise BridgeError("INVALID_ARGUMENT", "The document must be in front.")
        handle.touched()
        port.activate(handle.document, args["node_id"])
        return {
            "document_id": handle.document_id,
            "active_id": port.tree(handle.document)["active_id"],
        }

    def undo_labels(args: dict[str, Any], call: Call) -> dict[str, Any]:
        exact(args, {"document_id"})
        handle = fixture(args["document_id"])
        with in_front(port, handle.document):
            undo, redo = port.undo_labels(handle.document)
            actions = port.undo_actions(handle.document)
        return {"document_id": handle.document_id, "undo": undo, "redo": redo, "actions": actions}

    def label_timing(args: dict[str, Any], call: Call) -> dict[str, Any]:
        # Whether the Undo label names a step pushed in the same job, straight after the wait
        # and once posted events are through.
        exact(args, TIMING_FIELDS)
        handle = fixture(args["document_id"])
        trials = args["trials"]
        if not isinstance(trials, int) or isinstance(trials, bool) or not 1 <= trials <= MAX_TRIALS:
            raise BridgeError("INVALID_ARGUMENT", f"trials is from 1 to {MAX_TRIALS}.")
        try:
            with in_front(port, handle.document):
                reads = port.label_timing(handle.document, trials)
        finally:
            handle.ledger.seal()
            handle.touched()
        return {"document_id": handle.document_id, "reads": reads}

    def add_node(args: dict[str, Any], call: Call) -> dict[str, Any]:
        # A fixture for the reach of a change; no lease, no dirt, and no pixel written.
        exact(args, NODE_FIELDS)
        handle = fixture(args["document_id"])
        if args["kind"] not in NODE_KINDS:
            raise BridgeError("INVALID_ARGUMENT", f"kind is one of {', '.join(NODE_KINDS)}.")
        if not isinstance(args["layer_id"], str):
            raise BridgeError("INVALID_ARGUMENT", "layer_id names a layer.")
        try:
            node_id, changed = port.add_fixture_node(
                handle.document, args["kind"], args["layer_id"]
            )
        finally:
            # Adding the node pushed an undo step the ledger cannot name.
            handle.ledger.seal()
            handle.touched()
        return {"document_id": handle.document_id, "node_id": node_id, "composite_changed": changed}

    def front_document(args: dict[str, Any], call: Call) -> dict[str, Any]:
        # Which harness document is in front; never names one of the owner's.
        no_arguments(args)
        front = port.front()
        folder = os.path.realpath(paths.harness_dir(data))
        for handle in registry.sync():
            if (
                front is not None
                and handle.document == front
                and handle.owned
                and handle.path is not None
                and roots.inside(os.path.realpath(handle.path), [folder])
            ):
                return {"document_id": handle.document_id}
        return {"document_id": None}

    def view(args: dict[str, Any], call: Call) -> dict[str, Any]:
        # Reads or sets the zoom, rotation and pan of a harness document's view; no lease.
        exact(args, VIEW_FIELDS)
        handle = fixture(args["document_id"])
        wanted = args["view"]
        if wanted is not None:
            _check_view(wanted)
        if port.front() != handle.document:
            raise BridgeError("INVALID_ARGUMENT", "The document must be in front.")
        if wanted is None:
            return {"document_id": handle.document_id, "view": port.view_state(handle.document)}
        return {"document_id": handle.document_id, "view": port.set_view(handle.document, wanted)}

    def brush_state(args: dict[str, Any], call: Call) -> dict[str, Any]:
        # The window's brush and the named presets' values, read before a run and written back
        # after it, since the brush is the owner's too (K3).
        action = args.get("action")
        if action == "read":
            exact(args, BRUSH_READ_FIELDS)
            ids = args["preset_ids"]
            if (
                not isinstance(ids, list)
                or len(ids) > MAX_PRESETS
                or not all(isinstance(one, str) and one for one in ids)
            ):
                message = f"preset_ids is up to {MAX_PRESETS} preset ids."
                raise BridgeError("INVALID_ARGUMENT", message)
            handle = fixture(args["document_id"])
            state = port.brush_state(handle.document, list(ids))
            return {"document_id": handle.document_id, "state": state}
        if action == "write":
            exact(args, BRUSH_WRITE_FIELDS)
            if not isinstance(args["state"], dict):
                raise BridgeError("INVALID_ARGUMENT", "state is what a read returned.")
            handle = fixture(args["document_id"])
            port.set_brush_state(handle.document, args["state"])
            return {"document_id": handle.document_id}
        raise BridgeError("INVALID_ARGUMENT", "action is read or write.")

    def undo(args: dict[str, Any], call: Call) -> dict[str, Any]:
        # Krita's own Undo, as a hand would press it: the ledger is left for history to catch.
        exact(args, {"document_id"})
        handle = fixture(args["document_id"])
        # The document changes through the bridge, so it is dirty, as after any op that changes it.
        handle.before_change()
        with in_front(port, handle.document):
            port.undo(handle.document)
            undo_label, redo_label = port.undo_labels(handle.document)
        return {"document_id": handle.document_id, "undo": undo_label, "redo": redo_label}

    return {
        "harness.export_kra": export_kra,
        "harness.select_mask": select_mask,
        "harness.front_document": front_document,
        "harness.activate": activate,
        "harness.undo_labels": undo_labels,
        "harness.label_timing": label_timing,
        "harness.add_node": add_node,
        "harness.view": view,
        "harness.brush_state": brush_state,
        "harness.undo": undo,
    }


def _check_view(view: Any) -> None:
    if not isinstance(view, dict) or not view or not set(view) <= VIEW_KEYS:
        message = f"view sets one or more of {', '.join(sorted(VIEW_KEYS))}, or is null."
        raise BridgeError("INVALID_ARGUMENT", message)
    good = True
    if "zoom" in view:
        good = number(view["zoom"]) and view["zoom"] > 0
    if "rotation_deg" in view:
        good = good and number(view["rotation_deg"])
    if "pan_px" in view:
        pan = view["pan_px"]
        good = (
            good
            and isinstance(pan, list)
            and len(pan) == 2
            and all(isinstance(value, int) and not isinstance(value, bool) for value in pan)
        )
    if not good:
        raise BridgeError("INVALID_ARGUMENT", "view is malformed.")
