import os
from pathlib import Path
from typing import Any

from . import files, nodes, paths, roots
from .errors import BridgeError, exact, no_arguments
from .history import in_front
from .jobs import Call, Handler
from .pixels import check_rect
from .port import DocumentsPort
from .registry import Handle, Registry

EXPORT_FIELDS = {"document_id", "target_path"}
MASK_FIELDS = {"document_id", "layer_id", "rect"}
ACTIVATE_FIELDS = {"document_id", "node_id"}
TIMING_FIELDS = {"document_id", "trials"}
MAX_TRIALS = 20


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
            exported = port.export_kra(handle.document, target)
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

    return {
        "harness.export_kra": export_kra,
        "harness.select_mask": select_mask,
        "harness.front_document": front_document,
        "harness.activate": activate,
        "harness.undo_labels": undo_labels,
        "harness.label_timing": label_timing,
    }
