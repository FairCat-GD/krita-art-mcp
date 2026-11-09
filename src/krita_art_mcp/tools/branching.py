import os
import time
from dataclasses import replace
from typing import Any

from mcp.types import CallToolResult

from krita_art_mcp import envelope
from krita_art_mcp.bridge_client import BeforeSend, Done, Failed, Outcome, Pending
from krita_art_mcp.errors import UNCERTAIN
from krita_art_mcp.tools import saving
from krita_art_mcp.tools.dispatch import ToolCall, from_outcome, journaled
from krita_art_mcp.tools.documents import inside_roots

TOOL = "krita_document_duplicate"
NOUN = "duplicate"
# The plugin holds equal copies.
FORMATS = (".kra",)
FORMATS_MESSAGE = "A duplicate is a .kra file: only KRA keeps the layer ids protection names."
# What a poll from another process says when a step was never sent.
LEFT = "its file is not in place, or not open"
DUPLICATE_DATA = (
    "new_document_id",
    "path",
    "sha256",
    "reopened_verified",
    "baseline_id",
    "baseline_untouched",
    "source_dirty",
    "source_krita_modified",
    "mode",
    "source_path",
    "source_sha256",
    "canvas_px",
    "root_layer_id",
    "active_layer_id",
    "layers",
    "protection",
)


def document_duplicate(call: ToolCall, arguments: dict[str, Any]) -> CallToolResult:
    refused = _duplicate_rules(arguments)
    if refused is not None:
        return refused
    guard = arguments["guard"]
    op_args = {"document_id": guard["document_id"], "path": arguments["path"]}
    started = time.monotonic()

    def precheck() -> CallToolResult | None:
        refused = inside_roots(call.places, "path", arguments["path"])
        return refused if isinstance(refused, CallToolResult) else None

    def send(before_send: BeforeSend) -> Outcome:
        outcome = call.bridge.call(
            "document.duplicate", op_args, request_id=guard["request_id"], before_send=before_send
        )
        return finish_duplicate(call, outcome, call.bridge.budget_s - (time.monotonic() - started))

    return journaled(call, TOOL, arguments, guard["request_id"], send, duplicate_receipt, precheck)


def _duplicate_rules(arguments: dict[str, Any]) -> CallToolResult | None:
    # The plugin checks this too.
    extension = os.path.splitext(arguments["path"])[1].lower()
    if extension not in FORMATS:
        details = {"formats": list(FORMATS)}
        return envelope.failure("UNSUPPORTED_CAPABILITY", FORMATS_MESSAGE, details=details)
    return None


def finish_duplicate(call: ToolCall, outcome: Outcome, left_s: float) -> Outcome:
    # The duplicate's file is put in place as a save's is, then opened as a document of its
    # own; each step runs under an id derived from the duplicate's, so a retry or poll finds it.
    if not isinstance(outcome, Done) or outcome.request_id is None or outcome.operation_id is None:
        return outcome
    started = time.monotonic()
    finished = saving.finish_save(call, outcome, left_s, TOOL, NOUN)
    if not isinstance(finished, Done):
        return finished
    left = left_s - (time.monotonic() - started)
    args = {"document_id": finished.result["document_id"], "save_id": outcome.result["save_id"]}
    opened = call.bridge.call(
        "document.duplicate_open",
        args,
        request_id=f"{outcome.request_id}:open",
        budget_s=saving.finish_budget(call, left),
        operation_id=open_operation_id(outcome.operation_id),
    )
    return _as_duplicate(outcome, finished, opened)


def poll_duplicate(call: ToolCall, outcome: Outcome, left_s: float) -> Outcome:
    # Only the server process that made the call places and opens the duplicate; any other
    # reads what the bridge holds of each step.
    if not isinstance(outcome, Done) or outcome.request_id is None or outcome.operation_id is None:
        return outcome
    save_id = outcome.operation_id
    steps = (save_id, saving.finish_operation_id(save_id), open_operation_id(save_id))
    if any(call.bridge.made(one) for one in steps):
        return finish_duplicate(call, outcome, left_s)
    started = time.monotonic()
    finished = saving.read_finish(call, outcome, left_s, TOOL, NOUN)
    if finished is None:
        return saving.unfinished(outcome, TOOL, NOUN, LEFT)
    if not isinstance(finished, Done):
        return finished
    left = left_s - (time.monotonic() - started)
    found = call.bridge.operation(
        open_operation_id(save_id), budget_s=saving.finish_budget(call, left)
    )
    if saving.unknown(found):
        return saving.unfinished(outcome, TOOL, NOUN, LEFT)
    return _as_duplicate(outcome, finished, found, hint=False)


def _as_duplicate(save: Done, finished: Done, opened: Outcome, hint: bool = True) -> Outcome:
    if isinstance(opened, Pending):
        # Followed by the duplicate's own operation id, which finishes the same way.
        return Pending(opened.status, save.operation_id or opened.operation_id, save.op)
    # The receipt and the journal name the duplicate's own operation and request.
    operation_id, request_id, session_id = save.operation_id, save.request_id, save.session_id
    if isinstance(opened, Done):
        return replace(
            opened, operation_id=operation_id, request_id=request_id, session_id=session_id
        )
    return replace(
        opened,
        error=_open_error(save, finished, opened, hint),
        submitted=True,
        operation_id=operation_id,
        request_id=request_id,
        session_id=session_id,
    )


def _open_error(save: Done, finished: Done, opened: Failed, hint: bool) -> dict[str, Any]:
    # The file is in place whatever the open did, so its failure is never not_applied.
    error = opened.error
    path, sha256 = finished.result["path"], finished.result["sha256"]
    message = error["message"]
    # An open cancelled at Krita's quit never runs again: a retry meets a new Krita session.
    rerun = opened.submitted and error["retryable"] and error["code"] != "CANCELLED"
    if rerun and opened.session_id == save.session_id:
        if hint:
            message = f"{message} {saving.retry_hint(error['details'], TOOL, 'opens it')}"
    else:
        message = (
            f"{message} The duplicate is saved at {path}; krita_document_open opens it, with "
            "every layer protected."
        )
    details = {**error["details"], "outcome": UNCERTAIN, "path": path, "sha256": sha256}
    return {**error, "message": message, "retryable": False, "details": details}


def open_operation_id(save_id: str) -> str:
    return saving.derived_operation_id(save_id, "open")


def duplicate_receipt(outcome: Outcome) -> CallToolResult:
    if isinstance(outcome, Done) and "new_document_id" not in outcome.result:
        # Only the open's result describes a duplicate open as a document.
        return envelope.failure(
            "INTERNAL_ERROR",
            "The duplicate was not finished.",
            details={"outcome": UNCERTAIN},
            document_id=outcome.result.get("document_id"),
            operation_id=outcome.operation_id,
        )

    def data(result: dict[str, Any]) -> dict[str, Any]:
        return {key: result[key] for key in DUPLICATE_DATA}

    def text(result: dict[str, Any]) -> str:
        protected = sum(layer["protected"] for layer in result["layers"])
        return (
            f"Duplicated {result['document_id']} as {result['new_document_id']} at "
            f"{result['path']}, verified by reopening; {protected} of {len(result['layers'])} "
            "layers protected."
        )

    return from_outcome(outcome, data, text, lambda result: result["document_id"])
