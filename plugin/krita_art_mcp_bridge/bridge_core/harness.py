import os
from pathlib import Path
from typing import Any

from . import files, paths, roots
from .errors import BridgeError, exact
from .jobs import Call, Handler
from .port import DocumentsPort
from .registry import Registry

EXPORT_FIELDS = {"document_id", "target_path"}


def require_inside_harness(data: Path, path: Any, field: str) -> str:
    # Harness ops build fixtures only in the harness's own folder (decision 20).
    real = roots.resolve(path, field)
    if not roots.inside(real, [os.path.realpath(paths.harness_dir(data))]):
        details = {"field": field}
        message = f"Harness ops work only in the harness folder; {field} is outside it."
        raise BridgeError("PATH_NOT_ALLOWED", message, False, details)
    return real


def handlers(registry: Registry, port: DocumentsPort, data: Path) -> dict[str, Handler]:
    def export_kra(args: dict[str, Any], call: Call) -> dict[str, Any]:
        # A KRA fixture, written by Krita's own exporter. It changes nothing in the document,
        # so it takes no lease.
        exact(args, EXPORT_FIELDS)
        registry.refuse_at_job_start()
        handle = registry.find(args["document_id"])
        if not handle.owned or handle.path is None:
            message = "Harness ops take only documents the bridge opened."
            raise BridgeError("PATH_NOT_ALLOWED", message, False, {"field": "document_id"})
        require_inside_harness(data, handle.path, "document_id")
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

    return {"harness.export_kra": export_kra}
