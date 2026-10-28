from pathlib import Path
from typing import Any

from . import (
    files,
    history,
    inspection,
    layer_update,
    layers,
    opening,
    pixels,
    previews,
    protection,
    selections,
)
from .closing import settle_s, settled_close
from .errors import BridgeError, exact, no_arguments
from .jobs import Call, Handler
from .port import DocumentsPort
from .registry import NEW, Handle, Registry

# The only colour space Phase 1 creates; the server holds an equal copy.
COLOR_MODEL = "RGBA"
DEPTH = "U8"
SRGB_PROFILE = "sRGB-elle-V2-srgbtrc.icc"
CREATE_FIELDS = {"name", "size_px", "color_model", "depth", "profile_id", "background"}
CLOSE_FIELDS = {"document_id", "dirty_policy"}


def handlers(registry: Registry, port: DocumentsPort, data: Path) -> dict[str, Handler]:
    def create(args: dict[str, Any], call: Call) -> dict[str, Any]:
        width, height = _create_args(args)
        registry.refuse_at_job_start()
        document = port.create(args["name"], width, height)
        try:
            info = port.describe(document)
            root_id, children = port.layers(document)
            _check_created(info, children, width, height)
        except BaseException as raised:
            kept = registry.discard(document, settled_close(port), NEW, call.client)
            if kept is not None and isinstance(raised, BridgeError):
                raised.body["details"]["document_id"] = kept
            raise
        handle = registry.add(document, NEW, call.client)
        return {
            "document_id": handle.document_id,
            "canvas_px": [width, height],
            "root_layer_id": root_id,
            "initial_layer_id": children[0]["id"],
            "profile_id": info["profile_id"],
            "mode": handle.mode,
        }

    def list_documents(args: dict[str, Any], call: Call) -> dict[str, Any]:
        no_arguments(args)
        return {"documents": [_entry(handle, port) for handle in registry.sync()]}

    def baselines(args: dict[str, Any], call: Call) -> dict[str, Any]:
        # The server keeps the baselines; it sweeps those whose document is gone.
        no_arguments(args)
        return {"baseline_ids": [h.baseline_id for h in registry.sync() if h.baseline_id]}

    def close(handle: Handle, args: dict[str, Any], call: Call) -> dict[str, Any]:
        if handle.dirty and args["dirty_policy"] == "refuse":
            message = "The document has changes since its last verified save."
            raise BridgeError("DOCUMENT_DIRTY", message, False, {"document_id": handle.document_id})
        untouched = None
        if handle.source_path is not None and handle.source_sha256 is not None:
            untouched = files.unchanged(handle.source_path, handle.source_sha256)
        closed = port.close(handle.document, settle_s(handle, port.front() == handle.document))
        still_open = any(h is handle for h in registry.sync())
        if not closed or still_open:
            failure = {"document_id": handle.document_id, "close_returned": closed}
            raise BridgeError("INTERNAL_ERROR", "Krita did not close the document.", False, failure)
        registry.remove(handle)
        return {
            "document_id": handle.document_id,
            "closed": True,
            "baseline_untouched": untouched,
            "baseline_id": handle.baseline_id,
        }

    guarded_close = registry.guarded(close, writes=False, allow_unsafe=True)

    def close_document(args: dict[str, Any], call: Call) -> dict[str, Any]:
        exact(args, CLOSE_FIELDS)
        if args["dirty_policy"] not in ("refuse", "discard"):
            raise BridgeError("INVALID_ARGUMENT", "dirty_policy is refuse or discard.")
        return guarded_close(args, call)

    return {
        "document.create": create,
        "document.list": list_documents,
        "document.baselines": baselines,
        "document.close": close_document,
        **opening.handlers(registry, port, data),
        **inspection.handlers(registry, port, data),
        **pixels.handlers(registry, port, data),
        **previews.handlers(registry, port, data),
        **layers.handlers(registry, port),
        **layer_update.handlers(registry, port, data),
        **selections.handlers(registry, port, data),
        **protection.handlers(registry, port, data),
        **history.handlers(registry, port, data),
    }


def _create_args(args: dict[str, Any]) -> tuple[int, int]:
    # The server checks these too; Krita aborts on a colour space it cannot find.
    exact(args, CREATE_FIELDS)
    size = args["size_px"]
    if (
        not isinstance(args["name"], str)
        or not args["name"]
        or not isinstance(size, list)
        or len(size) != 2
        or any(isinstance(side, bool) or not isinstance(side, int) or side < 1 for side in size)
    ):
        raise BridgeError("INVALID_ARGUMENT", "name and size_px are malformed.")
    wanted = (args["color_model"], args["depth"], args["profile_id"], args["background"])
    if wanted != (COLOR_MODEL, DEPTH, SRGB_PROFILE, "transparent"):
        details = {"supported": [COLOR_MODEL, DEPTH, SRGB_PROFILE, "transparent"]}
        message = "Phase 1 creates RGBA / U8 / sRGB documents with a transparent background."
        raise BridgeError("UNSUPPORTED_CAPABILITY", message, False, details)
    return size[0], size[1]


def _check_created(
    info: dict[str, Any], children: list[dict[str, Any]], width: int, height: int
) -> None:
    space = (info["color_model"], info["depth"], info["profile_id"])
    layer = children[0] if len(children) == 1 else None
    transparent = (
        layer is not None
        and layer["type"] == "paintlayer"
        and layer["opacity"] == 255
        and layer["active"] is True
        and layer["alpha_at_origin"] == 0
    )
    if space != (COLOR_MODEL, DEPTH, SRGB_PROFILE) or info["size_px"] != [width, height]:
        details = {"color_space": list(space), "size_px": info["size_px"]}
        raise BridgeError("INTERNAL_ERROR", "Krita made another document.", False, details)
    if not transparent:
        details = {"layers": children}
        message = "The new document has no single, active, transparent paint layer."
        raise BridgeError("INTERNAL_ERROR", message, False, details)


def _entry(handle: Handle, port: DocumentsPort) -> dict[str, Any]:
    info = port.describe(handle.document)
    return {
        "document_id": handle.document_id,
        "name": info["name"],
        "path": info["path"],
        "size_px": info["size_px"],
        "color_model": info["color_model"],
        "depth": info["depth"],
        "profile_id": info["profile_id"],
        "dirty": handle.dirty,
        "mode": handle.mode,
    }
