from typing import Any, Protocol

from .errors import BridgeError, no_arguments
from .jobs import Call, Handler
from .registry import NEW, Handle, Registry, never

# The only colour space Phase 1 creates; the server holds an equal copy.
COLOR_MODEL = "RGBA"
DEPTH = "U8"
SRGB_PROFILE = "sRGB-elle-V2-srgbtrc.icc"
CREATE_FIELDS = {"name", "size_px", "color_model", "depth", "profile_id", "background"}
CLOSE_FIELDS = {"document_id", "dirty_policy"}


class DocumentsPort(Protocol):
    def documents(self) -> list[Any]: ...

    def refusal(self) -> BridgeError | None: ...

    # Creates, gives the document a view at once, and waits; cleans up after its own failure.
    def create(self, name: str, width: int, height: int) -> Any: ...

    def describe(self, document: Any) -> dict[str, Any]: ...

    # The root's id, then each child as {id, type, opacity, alpha_at_origin}.
    def layers(self, document: Any) -> tuple[str, list[dict[str, Any]]]: ...

    # Waits, clears the modified flag so Krita never asks to save, then closes.
    def close(self, document: Any) -> bool: ...


def handlers(registry: Registry, port: DocumentsPort) -> dict[str, Handler]:
    def create(args: dict[str, Any], call: Call) -> dict[str, Any]:
        width, height = _create_args(args)
        registry.refuse_at_job_start()
        document = port.create(args["name"], width, height)
        try:
            info = port.describe(document)
            root_id, children = port.layers(document)
            _check_created(info, children, width, height)
        except BaseException:
            port.close(document)
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

    def close(handle: Handle, args: dict[str, Any], call: Call) -> dict[str, Any]:
        if handle.dirty and args["dirty_policy"] == "refuse":
            message = "The document has changes since its last verified save."
            raise BridgeError("DOCUMENT_DIRTY", message, False, {"document_id": handle.document_id})
        closed = port.close(handle.document)
        still_open = any(h is handle for h in registry.sync())
        if not closed or still_open:
            failure = {"document_id": handle.document_id, "close_returned": closed}
            raise BridgeError("INTERNAL_ERROR", "Krita did not close the document.", False, failure)
        registry.remove(handle)
        return {"document_id": handle.document_id, "closed": True, "baseline_untouched": None}

    guarded_close = registry.guarded(close, dirties=never, writes=False, allow_unsafe=True)

    def close_document(args: dict[str, Any], call: Call) -> dict[str, Any]:
        _exact(args, CLOSE_FIELDS)
        if args["dirty_policy"] not in ("refuse", "discard"):
            raise BridgeError("INVALID_ARGUMENT", "dirty_policy is refuse or discard.")
        return guarded_close(args, call)

    return {
        "document.create": create,
        "document.list": list_documents,
        "document.close": close_document,
    }


def _exact(args: dict[str, Any], fields: set[str]) -> None:
    if set(args) != fields:
        details = {"expected": sorted(fields), "given": sorted(args)}
        raise BridgeError("INVALID_ARGUMENT", "The op's arguments are wrong.", False, details)


def _create_args(args: dict[str, Any]) -> tuple[int, int]:
    # The server checks these too; Krita aborts on a colour space it cannot find.
    _exact(args, CREATE_FIELDS)
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
        and layer["alpha_at_origin"] == 0
    )
    if space != (COLOR_MODEL, DEPTH, SRGB_PROFILE) or info["size_px"] != [width, height]:
        details = {"color_space": list(space), "size_px": info["size_px"]}
        raise BridgeError("INTERNAL_ERROR", "Krita made another document.", False, details)
    if not transparent:
        details = {"layers": children}
        message = "The new document has no single transparent paint layer."
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
