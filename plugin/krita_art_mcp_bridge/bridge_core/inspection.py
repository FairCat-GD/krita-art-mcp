from typing import Any

from .errors import BridgeError, exact, integer
from .jobs import Call, Handler
from .ledger import selection_state
from .port import DocumentsPort
from .registry import Handle, Registry

INSPECT_FIELDS = {"document_id", "frame"}
# Krita's node types in the contract's words; any other type passes through as Krita names it.
TYPES = {
    "paintlayer": "paint",
    "grouplayer": "group",
    "filelayer": "file",
    "filterlayer": "filter",
    "filllayer": "fill",
    "clonelayer": "clone",
    "vectorlayer": "vector",
    "transparencymask": "transparency_mask",
    "filtermask": "filter_mask",
    "transformmask": "transform_mask",
    "selectionmask": "selection_mask",
    "colorizemask": "colorize_mask",
}


def check_frame(frame: Any) -> None:
    if not integer(frame) or frame < 0:
        raise BridgeError("INVALID_ARGUMENT", "frame is an integer of 0 or more.")
    if frame != 0:
        details = {"frame": frame, "supported": [0]}
        message = "Phase 1 reads frame 0 only; animation arrives in Phase 5."
        raise BridgeError("UNSUPPORTED_CAPABILITY", message, False, details)


def check_shown_frame(info: dict[str, Any]) -> None:
    # Krita reads the frame on screen, and the owner's timeline is never moved. Only an animated
    # document shows other pixels away from frame 0.
    if info["animated"] and info["current_time"] != 0:
        details = {"current_time": info["current_time"], "supported": [0]}
        message = "The document is showing another frame; Phase 1 reads frame 0 only."
        raise BridgeError("UNSUPPORTED_CAPABILITY", message, False, details)


def layer_entries(tree: dict[str, Any], protected: set[str]) -> list[dict[str, Any]]:
    return [
        {
            "id": node["id"],
            "parent_id": node["parent_id"],
            "name": node["name"],
            "type": TYPES.get(node["type"], node["type"]),
            "order": node["order"],
            "visible": node["visible"],
            "opacity": node["opacity"] / 255,
            "blend_mode": node["blend_mode"],
            "locked": node["locked"],
            "alpha_locked": node["alpha_locked"],
            "inherit_alpha": node["inherit_alpha"],
            "offset_px": node["offset_px"],
            "bounds_px": node["bounds_px"],
            "color_model": node["color_model"],
            "depth": node["depth"],
            "profile_id": node["profile_id"],
            "protected": node["id"] in protected,
            "translation_px": node["translation_px"],
        }
        for node in tree["nodes"]
    ]


def protected_ids(handle: Handle, tree: dict[str, Any]) -> set[str]:
    # Agents may change nothing in a document the owner opened.
    if not handle.owned:
        return {node["id"] for node in tree["nodes"]}
    return handle.protected


def handlers(registry: Registry, port: DocumentsPort) -> dict[str, Handler]:
    def inspect(args: dict[str, Any], call: Call) -> dict[str, Any]:
        # A read: no lease, and the owner's view and active node are left alone.
        exact(args, INSPECT_FIELDS)
        check_frame(args["frame"])
        registry.refuse_at_job_start()
        handle = registry.find(args["document_id"])
        info = port.describe(handle.document)
        tree = port.tree(handle.document)
        return {
            "document_id": handle.document_id,
            "mode": handle.mode,
            "path": info["path"],
            "source_path": handle.source_path,
            "baseline_id": handle.baseline_id,
            "canvas_px": info["size_px"],
            "frame": 0,
            "color_model": info["color_model"],
            "depth": info["depth"],
            "profile_id": info["profile_id"],
            "dirty": handle.dirty,
            "krita_modified": info["modified"],
            "unsafe": handle.unsafe,
            "root_layer_id": tree["root_id"],
            "active_layer_id": tree["active_id"],
            "layers": layer_entries(tree, protected_ids(handle, tree)),
            "selection": _selection(port, handle, info["size_px"]),
            "protection": {
                "allowed_change_mask": handle.allowed_summary,
                "preserve_composite_alpha": handle.preserve_composite_alpha,
                "preserve_canvas": handle.preserve_canvas,
            },
            "history": {
                "undo_available": handle.ledger.undo_available(),
                "redo_available": handle.ledger.redo,
            },
        }

    return {"document.inspect": inspect}


def _selection(port: DocumentsPort, handle: Handle, size: list[int]) -> dict[str, Any] | None:
    found = selection_state(port, handle.document, size)
    if found is None:
        return None
    bounds, pixels = found
    expected = bounds["width"] * bounds["height"]
    if len(pixels) != expected:
        details = {"bytes": len(pixels), "expected": expected}
        message = "Krita returned a buffer of the wrong size."
        raise BridgeError("INTERNAL_ERROR", message, False, details)
    return {
        "bounds_px": bounds,
        "selected_pixels": expected - pixels.count(0),
        "coverage_px": sum(pixels) / 255,
    }
