from typing import Any

# The bridge protocol; the plugin holds an equal copy (`bridge_core.PROTOCOL`).
PROTOCOL = 1
# The tool contract's version, carried by every result envelope.
API_VERSION = "0.3.0"

# Whether a failure applied, in `details.outcome`; the plugin holds an equal copy.
APPLIED = "applied"
NOT_APPLIED = "not_applied"
UNCERTAIN = "uncertain"
UNREGISTERED = "unregistered"
OUTCOMES = (APPLIED, NOT_APPLIED, UNCERTAIN, UNREGISTERED)

# Each Phase 1 code with its default `retryable` and its one-line hint. The plugin holds an
# equal list of codes (`bridge_core.errors.CODES`).
CODES: dict[str, tuple[bool, str]] = {
    "INVALID_ARGUMENT": (False, "The arguments do not match the tool's schema or rules."),
    "UNSUPPORTED_CAPABILITY": (False, "This build or phase does not support that request."),
    "KRITA_NOT_RUNNING": (False, "Krita is not running with the bridge plugin."),
    "PROTOCOL_MISMATCH": (False, "Reinstall the plugin, then restart Krita."),
    "KRITA_MODAL_DIALOG": (True, "Close the dialog open in Krita, then retry."),
    "MULTIPLE_WINDOWS": (True, "Close Krita's extra windows, then retry."),
    "BUSY": (True, "Krita is busy; retry shortly."),
    "TIMEOUT": (False, "The operation exceeded its hard limit."),
    "CANCELLED": (True, "The operation was cancelled before it ran."),
    "REQUEST_ID_CONFLICT": (False, "That request_id was used with different arguments."),
    "DOCUMENT_NOT_FOUND": (False, "No open document has that id."),
    "LAYER_NOT_FOUND": (False, "The document has no layer with that id."),
    "LOCKED_TARGET": (False, "The target is protected or locked."),
    "LAYER_NOT_PAINTABLE": (False, "The target is not a paint layer."),
    "LAYER_HAS_LOCAL_SELECTION": (False, "The target layer has an active local selection."),
    "PROTECTED_REGION_CHANGED": (False, "The change reached protected pixels and was undone."),
    "OUTSIDE_ALLOWED_MASK": (False, "The stroke lies entirely outside the allowed mask."),
    "RESOURCE_HASH_MISMATCH": (False, "The resource differs from the hash given."),
    "SOURCE_HASH_MISMATCH": (False, "The source file differs from the hash given."),
    "COLOR_PROFILE_MISMATCH": (False, "The document is not 8-bit sRGB RGBA."),
    "DOCUMENT_DIRTY": (False, "The document has changes since its last verified save."),
    "DOCUMENT_UNSAFE": (False, "A rollback failed; reopen the document."),
    "DOCUMENT_READ_ONLY": (False, "The document is read-only to agents."),
    "DOCUMENT_IN_USE": (False, "Another server process holds this document's writer lease."),
    "SAVE_VERIFY_FAILED": (False, "The reopened save differs from the document."),
    "PATH_NOT_ALLOWED": (False, "The path is outside every allowed root."),
    "FILE_EXISTS": (False, "The target file exists; saves never overwrite."),
    "IO_ERROR": (False, "A disk or format error occurred."),
    "ROLLBACK_FAILED": (False, "The rollback could not be verified; the document is unsafe."),
    "INTERNAL_ERROR": (False, "An unexpected error occurred."),
}


def error_body(
    code: str,
    message: str | None = None,
    *,
    retryable: bool | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    default_retryable, hint = CODES[code]
    return {
        "code": code,
        "message": message or hint,
        "retryable": default_retryable if retryable is None else retryable,
        "details": details or {},
    }
