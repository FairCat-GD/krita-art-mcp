import os
from pathlib import Path
from typing import Any

from . import files, paths, roots
from .errors import BridgeError, exact, no_arguments
from .jobs import Call, Handler
from .pixels import check_rect
from .port import DocumentsPort
from .registry import Handle, Registry

EXPORT_FIELDS = {"document_id", "target_path"}
MASK_FIELDS = {"document_id", "layer_id", "rect"}


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
        port.prepare_read(handle.document)
        if not port.export_kra(handle.document, target):
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
        overlay = port.add_active_mask(handle.document, args["layer_id"], rect)
        return {"document_id": handle.document_id, "overlay_seen": overlay}

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
    }
