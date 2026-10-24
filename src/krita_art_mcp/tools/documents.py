import os
from dataclasses import replace
from typing import Any

import numpy as np
from mcp.types import CallToolResult

from krita_art_mcp import baselines, envelope, roots, transfer
from krita_art_mcp.bridge_client import BeforeSend, Done, Failed, Outcome
from krita_art_mcp.errors import error_body
from krita_art_mcp.paths import Places
from krita_art_mcp.tools.dispatch import ToolCall, from_outcome, journaled

# The only colour space Phase 1 creates; the plugin holds an equal copy.
SRGB_PROFILE = "sRGB-elle-V2-srgbtrc.icc"
DEPTH = "U8"


def document_list(call: ToolCall, arguments: dict[str, Any]) -> CallToolResult:
    return list_receipt(call.bridge.call("document.list"))


def list_receipt(outcome: Outcome) -> CallToolResult:
    def text(result: dict[str, Any]) -> str:
        count = len(result["documents"])
        return f"{count} open document{'' if count == 1 else 's'}."

    return from_outcome(outcome, lambda result: {"documents": result["documents"]}, text)


def document_create(call: ToolCall, arguments: dict[str, Any]) -> CallToolResult:
    # The schema admits these, and Phase 1 cannot make them.
    if arguments["depth"] != DEPTH or arguments["profile_id"] != SRGB_PROFILE:
        details = {"supported": {"depth": DEPTH, "profile_id": SRGB_PROFILE}}
        message = "Phase 1 creates RGBA / U8 / sRGB documents only."
        return envelope.failure("UNSUPPORTED_CAPABILITY", message, details=details)
    op_args = {key: value for key, value in arguments.items() if key != "request_id"}
    request_id = arguments["request_id"]

    def send(before_send: BeforeSend) -> Outcome:
        return call.bridge.call(
            "document.create", op_args, request_id=request_id, before_send=before_send
        )

    return journaled(call, "krita_document_create", arguments, request_id, send, create_receipt)


def create_receipt(outcome: Outcome) -> CallToolResult:
    def data(result: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in result.items() if key != "document_id"}

    def text(result: dict[str, Any]) -> str:
        width, height = result["canvas_px"]
        return f"Created {result['document_id']}, {width} x {height} px."

    return from_outcome(outcome, data, text, lambda result: result["document_id"])


def document_close(call: ToolCall, arguments: dict[str, Any]) -> CallToolResult:
    guard = arguments["guard"]
    op_args = {"document_id": guard["document_id"], "dirty_policy": arguments["dirty_policy"]}

    def send(before_send: BeforeSend) -> Outcome:
        outcome = call.bridge.call(
            "document.close", op_args, request_id=guard["request_id"], before_send=before_send
        )
        return resolve_close(call.places, outcome)

    return journaled(
        call, "krita_document_close", arguments, guard["request_id"], send, close_receipt
    )


def close_receipt(outcome: Outcome) -> CallToolResult:
    def data(result: dict[str, Any]) -> dict[str, Any]:
        return {"closed": result["closed"], "baseline_untouched": result["baseline_untouched"]}

    return from_outcome(
        outcome, data, lambda result: f"Closed {result['document_id']}.", lambda r: r["document_id"]
    )


OPEN_FIELDS = (
    "source_path",
    "source_sha256",
    "mode",
    "working_dir",
    "editable_layer_ids",
    "editable_layer_names",
)
OPEN_DATA = (
    "mode",
    "working_copy",
    "path",
    "source_path",
    "source_sha256",
    "baseline_id",
    "canvas_px",
    "color_model",
    "depth",
    "profile_id",
    "root_layer_id",
    "active_layer_id",
    "layers",
)
FORMATS = (".kra", ".ora", ".png")


def document_open(call: ToolCall, arguments: dict[str, Any]) -> CallToolResult:
    refused = _open_rules(arguments)
    if refused is not None:
        return refused
    op_args = {field: arguments.get(field) for field in OPEN_FIELDS}
    request_id = arguments["request_id"]

    def precheck() -> CallToolResult | None:
        return _open_roots(call.places, arguments)

    def send(before_send: BeforeSend) -> Outcome:
        outcome = call.bridge.call(
            "document.open", op_args, request_id=request_id, before_send=before_send
        )
        return resolve_open(call.places, outcome)

    return journaled(
        call, "krita_document_open", arguments, request_id, send, open_receipt, precheck
    )


def resolve_open(places: Places, outcome: Outcome) -> Outcome:
    # The as_opened composite is kept before the receipt, wherever the outcome arrives.
    if isinstance(outcome, Done):
        baselines.adopt(places, outcome.result.get("baseline_id"), outcome.result.get("baseline"))
    return outcome


def open_receipt(outcome: Outcome) -> CallToolResult:
    def data(result: dict[str, Any]) -> dict[str, Any]:
        return {key: result[key] for key in OPEN_DATA}

    def text(result: dict[str, Any]) -> str:
        width, height = result["canvas_px"]
        kind = "a working copy" if result["working_copy"] else "read-only"
        protected = sum(layer["protected"] for layer in result["layers"])
        return (
            f"Opened {result['document_id']}, {kind}, {width} x {height} px; "
            f"{protected} of {len(result['layers'])} layers protected."
        )

    return from_outcome(outcome, data, text, lambda result: result["document_id"])


def frame_refusal(frame: int) -> CallToolResult | None:
    # The plugin checks too; refusing here costs no trip to Krita.
    if frame == 0:
        return None
    details = {"frame": frame, "supported": [0]}
    message = "Phase 1 reads frame 0 only; animation arrives in Phase 5."
    return envelope.failure("UNSUPPORTED_CAPABILITY", message, details=details)


def document_inspect(call: ToolCall, arguments: dict[str, Any]) -> CallToolResult:
    refused = frame_refusal(arguments["frame"])
    if refused is not None:
        return refused
    op_args = {"document_id": arguments["document_id"], "frame": 0}
    return inspect_receipt(
        resolve_inspect(call.places, call.bridge.call("document.inspect", op_args))
    )


def resolve_inspect(places: Places, outcome: Outcome) -> Outcome:
    # The selection crosses as a transfer file; its numbers are counted here, with NumPy.
    if not isinstance(outcome, Done) or outcome.result.get("selection") is None:
        return outcome
    selection = outcome.result["selection"]
    try:
        if selection["pixels"] is None:
            selected, coverage = 0, 0.0
        else:
            values = transfer.take(places.transfer_dir, selection["pixels"])
            transfer.discard(places.transfer_dir, selection["pixels"])
            selected = int(np.count_nonzero(values))
            coverage = float(values.sum(dtype=np.uint64)) / 255
    except transfer.TransferError as problem:
        message = f"The selection could not be read ({problem}); inspect again."
        error = error_body("INTERNAL_ERROR", message, retryable=True)
        return Failed(error, outcome.operation_id, submitted=True, op=outcome.op)
    counted = {
        "bounds_px": selection["bounds_px"],
        "selected_pixels": selected,
        "coverage_px": coverage,
    }
    return replace(outcome, result={**outcome.result, "selection": counted})


def inspect_receipt(outcome: Outcome) -> CallToolResult:
    def data(result: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in result.items() if key != "document_id"}

    def text(result: dict[str, Any]) -> str:
        width, height = result["canvas_px"]
        return (
            f"{result['document_id']}: {width} x {height} px, {len(result['layers'])} layers, "
            f"{result['mode']}."
        )

    return from_outcome(outcome, data, text, lambda result: result["document_id"])


def resolve_close(places: Places, outcome: Outcome) -> Outcome:
    if isinstance(outcome, Done):
        baselines.remove(places, outcome.result.get("baseline_id"))
    return outcome


def _open_rules(arguments: dict[str, Any]) -> CallToolResult | None:
    # The plugin checks these too; they depend on the arguments alone.
    extension = os.path.splitext(arguments["source_path"])[1].lower()
    if extension not in FORMATS:
        details = {"formats": list(FORMATS)}
        message = "Phase 1 opens .kra, .ora and .png files."
        return envelope.failure("UNSUPPORTED_CAPABILITY", message, details=details)
    # The schema ties working_dir and the editable lists to the mode.
    ids = arguments.get("editable_layer_ids")
    names = arguments.get("editable_layer_names")
    if ids is not None and extension != ".kra":
        message = (
            "editable_layer_ids is for KRA, whose layer ids persist; use editable_layer_names."
        )
        return envelope.failure("INVALID_ARGUMENT", message)
    if names is not None and extension == ".kra":
        message = "editable_layer_names is for ORA and PNG; a KRA keeps its layer ids."
        return envelope.failure("INVALID_ARGUMENT", message)
    return None


def _open_roots(places: Places, arguments: dict[str, Any]) -> CallToolResult | None:
    # Invariant 3, on the server's side; the plugin checks again.
    try:
        allowed = roots.allowed(places.config_file, places.harness_dir)
    except roots.ConfigError as problem:
        return envelope.failure("INTERNAL_ERROR", str(problem))
    real: dict[str, str] = {}
    for field in ("source_path", "working_dir"):
        if field not in arguments:
            continue
        resolved = roots.resolve(arguments[field])
        if resolved is None:
            details = {"field": field}
            message = f"{field} must be an absolute path."
            return envelope.failure("INVALID_ARGUMENT", message, details=details)
        if not roots.inside(resolved, allowed):
            details = {"field": field}
            message = f"{field} is outside every allowed root."
            return envelope.failure("PATH_NOT_ALLOWED", message, details=details)
        real[field] = resolved
    if real.get("working_dir") == os.path.dirname(real["source_path"]):
        details = {"field": "working_dir"}
        message = "working_dir must not be the source's own folder."
        return envelope.failure("INVALID_ARGUMENT", message, details=details)
    return None
