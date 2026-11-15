from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import files, roots, verification
from .errors import BridgeError, exact
from .inspection import layer_entries
from .jobs import Call, Handler
from .opening import Made, new_baseline_id, opened
from .port import DocumentsPort
from .protection import summary
from .registry import Handle, Registry
from .saving import Placed

OPEN_FIELDS = {"document_id", "save_id"}


def handlers(
    registry: Registry,
    port: DocumentsPort,
    data: Path,
    new_id: Callable[[], str] = new_baseline_id,
) -> dict[str, Handler]:
    def open_branch(source: Handle, args: dict[str, Any], call: Call) -> dict[str, Any]:
        # Only a file this bridge's own finish put in place opens here, never a path a caller
        # names: the duplicate is opened directly, not copied.
        placed = source.branches.get(args["save_id"])
        if not isinstance(placed, Placed):
            details = {"document_id": source.document_id, "save_id": args["save_id"]}
            message = "No duplicate of this document waits to open under that save_id."
            raise BridgeError("INVALID_ARGUMENT", message, False, details)
        path = roots.check(data, placed.path, "path")
        if not files.unchanged(path, placed.sha256, placed.stat):
            details = {"document_id": source.document_id, "path": path}
            message = "The duplicate's file changed after it was put in place."
            raise BridgeError("SOURCE_HASH_MISMATCH", message, False, details)
        inherited = placed.inherited
        size = inherited.size_px
        verification.check_mask_size(inherited.allowed_mask, size)
        verification.check_mask_size(source.allowed_mask, size)
        untouched = None
        if source.source_path is not None and source.source_sha256 is not None:
            untouched = files.unchanged(
                source.source_path, source.source_sha256, source.source_stat
            )
        modified = port.describe(source.document)["modified"]
        made = Made()
        try:
            document, info, tree = opened(port, made, path, call)
            if info["size_px"] != size:
                details = {"file_px": info["size_px"], "canvas_px": size}
                message = "The duplicate opens at another size than its source was saved at."
                raise BridgeError("INTERNAL_ERROR", message, False, details)
            # The tighter of what the save found and what the source holds now: protection only
            # tightens, but it drops a protected node that has gone from the source.
            ids = {node["id"] for node in tree["nodes"]}
            protected = (inherited.protected | source.protected) & ids
            mask = _both(inherited.allowed_mask, source.allowed_mask)
            alpha = inherited.preserve_composite_alpha or source.preserve_composite_alpha
            canvas = inherited.preserve_canvas or source.preserve_canvas
            allowed = None if mask is None else summary(mask, size[0])
            baseline_id = new_id()
            # Registered last, so nothing can fail once the registry holds the document.
            handle = registry.add(document, source.mode, call.client)
        except BaseException as raised:
            made.undo(registry, port, source.mode, call, raised)
            raise
        handle.path = path
        handle.opened_sha256 = placed.sha256
        handle.source_path = source.source_path
        handle.source_sha256 = source.source_sha256
        handle.source_stat = source.source_stat
        handle.baseline_id = baseline_id
        handle.protected = protected
        handle.allowed_mask = mask
        handle.allowed_summary = allowed
        handle.preserve_composite_alpha = alpha
        handle.preserve_canvas = canvas
        del source.branches[args["save_id"]]
        return {
            "document_id": source.document_id,
            "new_document_id": handle.document_id,
            "path": path,
            "sha256": placed.sha256,
            "reopened_verified": True,
            "recompose": placed.recompose,
            "baseline_id": baseline_id,
            "baseline_untouched": untouched,
            "source_dirty": source.dirty,
            "source_krita_modified": modified,
            "mode": handle.mode,
            "source_path": handle.source_path,
            "source_sha256": handle.source_sha256,
            "canvas_px": list(size),
            "root_layer_id": tree["root_id"],
            "active_layer_id": tree["active_id"],
            "layers": layer_entries(tree, protected),
            "protection": {
                "allowed_change_mask": allowed,
                "preserve_composite_alpha": alpha,
                "preserve_canvas": canvas,
            },
        }

    # Like the save's finish: the step after a placed file, run again under its own id when
    # refused retryably.
    guarded = registry.guarded(open_branch, allow_unsafe=True, lease_retryable=True)

    def duplicate_open(args: dict[str, Any], call: Call) -> dict[str, Any]:
        exact(args, OPEN_FIELDS)
        if not isinstance(args["save_id"], str):
            raise BridgeError("INVALID_ARGUMENT", "save_id is text.")
        return guarded(args, call)

    return {"document.duplicate_open": duplicate_open}


def _both(first: bytes | None, second: bytes | None) -> bytes | None:
    # Each pixel allowed by both masks; None allows the whole canvas.
    if first is None:
        return second
    if second is None:
        return first
    joined = int.from_bytes(first, "big") & int.from_bytes(second, "big")
    return joined.to_bytes(len(first), "big")
