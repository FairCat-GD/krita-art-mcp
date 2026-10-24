from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator
from mcp.types import CallToolResult

from krita_art_mcp import envelope, schemas
from krita_art_mcp.bridge_client import BeforeSend, Done, Failed, Outcome
from krita_art_mcp.journal import JournalError
from krita_art_mcp.paths import Places
from krita_art_mcp.tools import changes, documents, observe, pixels
from krita_art_mcp.tools.dispatch import Receipt, ToolCall, journaled, record

Resolver = Callable[[Places, Outcome], Outcome]


@dataclass(frozen=True)
class Known:
    tool: str
    receipt: Receipt
    # For an op whose result names files the server keeps, reads or removes before the receipt.
    resolve: Resolver | None = None


# Each bridge op an agent can be handed an operation_id for, with its tool's receipt.
RECEIPTS: dict[str, Known] = {
    "server_info": Known("krita_server_info", observe.server_info_receipt),
    "document.list": Known("krita_document_list", documents.list_receipt),
    "document.create": Known("krita_document_create", documents.create_receipt),
    "document.open": Known("krita_document_open", documents.open_receipt, documents.resolve_open),
    "document.inspect": Known(
        "krita_document_inspect", documents.inspect_receipt, documents.resolve_inspect
    ),
    "document.close": Known(
        "krita_document_close", documents.close_receipt, documents.resolve_close
    ),
    "resource.list": Known("krita_resource_list", observe.resource_receipt),
    "capture.read": Known("krita_capture", pixels.capture_receipt, pixels.resolve_capture),
    "sample.read": Known("krita_sample", pixels.sample_receipt, pixels.resolve_sample),
    "layer.create": Known("krita_layer_create", changes.layer_receipt),
    "selection.set": Known(
        "krita_selection_set", changes.selection_receipt, changes.resolve_selection
    ),
    "protection.set": Known("krita_protection_set", changes.protection_receipt),
    "history.step": Known("krita_history_step", changes.history_receipt, changes.resolve_history),
}


def operation_get(call: ToolCall, arguments: dict[str, Any]) -> CallToolResult:
    operation_id = arguments["operation_id"]
    try:
        sent_in = call.journal.session_of(operation_id)
    except (JournalError, OSError) as problem:
        return envelope.failure("INTERNAL_ERROR", f"The journal could not be read: {problem}")
    outcome = call.bridge.operation(operation_id, sent_in=sent_in)
    if isinstance(outcome, Failed) and outcome.op is None:
        # Not the operation's own outcome: the id is unknown, or Krita is gone.
        return envelope.failed(outcome.error, operation_id=operation_id)
    known = RECEIPTS.get(outcome.op or "")
    if outcome.op is not None and known is None:
        details = {"operation_id": operation_id, "op": outcome.op}
        message = "That operation belongs to no tool."
        return envelope.failure("INVALID_ARGUMENT", message, details=details)
    if isinstance(outcome, Done | Failed):
        changes.settle_masks(call.places, outcome.request_id)
    if known is not None and known.resolve is not None:
        outcome = known.resolve(call.places, outcome)
    tool = None if known is None else known.tool
    data: dict[str, Any] = {
        "operation_id": outcome.operation_id or operation_id,
        "tool": tool,
        "state": _state(outcome),
        "progress": None,
        "receipt": None,
    }
    if known is None or not isinstance(outcome, Done | Failed):
        text = f"Operation {data['operation_id']} is still {data['state']}."
        return envelope.completed(data, text, operation_id=data["operation_id"])
    receipt = known.receipt(outcome)
    mismatch = next(iter(_validator(known.tool).iter_errors(receipt.structured_content)), None)
    if mismatch is not None:
        reason = f"the receipt does not match {known.tool}'s output schema: {mismatch.message}"
        return envelope.failure("INTERNAL_ERROR", details={"reason": reason})
    data["receipt"] = receipt.structured_content
    _finish_journaled(call, outcome, receipt, operation_id)
    content = receipt.structured_content or {}
    text = f"Operation {data['operation_id']} ({tool}) {data['state']}."
    result = envelope.completed(
        data, text, document_id=content.get("document_id"), operation_id=data["operation_id"]
    )
    # The receipt's own line and any image it carries, as the call itself would have shown.
    result.content.extend(receipt.content)
    return result


def _state(outcome: Outcome) -> str:
    if isinstance(outcome, Done):
        return "completed"
    if isinstance(outcome, Failed):
        return "cancelled" if outcome.error["code"] == "CANCELLED" else "failed"
    return outcome.status


def _finish_journaled(
    call: ToolCall, outcome: Done | Failed, receipt: CallToolResult, operation_id: str
) -> None:
    # A call that came back running has no finished line yet; this is where it ends.
    if outcome.request_id is None or outcome.session_id is None:
        return
    try:
        prior = call.journal.lookup(outcome.request_id)
    except (JournalError, OSError):
        return
    # Only an attempt nothing has settled yet needs its end recorded.
    if prior is None or not prior.unknown_in(outcome.session_id):
        return
    bound = prior.binding()
    if bound is None:
        return
    tool, digest = bound
    record(
        call,
        tool,
        outcome.request_id,
        digest,
        outcome.session_id,
        operation_id,
        outcome,
        receipt,
    )


_VALIDATORS: dict[str, Draft202012Validator] = {}


def _validator(tool: str) -> Draft202012Validator:
    if tool not in _VALIDATORS:
        _VALIDATORS[tool] = Draft202012Validator(schemas.load(tool)["outputSchema"])
    return _VALIDATORS[tool]


def operation_cancel(call: ToolCall, arguments: dict[str, Any]) -> CallToolResult:
    operation_id = arguments["operation_id"]

    def send(before_send: BeforeSend) -> Outcome:
        outcome = call.bridge.cancel(operation_id, before_send=before_send)
        # A cancelled or finished operation takes no mask any more.
        if isinstance(outcome, Done) and outcome.result.get("status") in ("done", "error"):
            request_id = outcome.result.get("request_id")
            changes.settle_masks(call.places, request_id if isinstance(request_id, str) else None)
        return outcome

    return journaled(
        call, "krita_operation_cancel", arguments, arguments["request_id"], send, cancel_receipt
    )


def cancel_receipt(outcome: Outcome) -> CallToolResult:
    if not isinstance(outcome, Done):
        error = outcome.error if isinstance(outcome, Failed) else None
        if error is None:
            return envelope.failure("INTERNAL_ERROR", "The cancel came back pending.")
        return envelope.failed(error, operation_id=outcome.operation_id)
    reply = outcome.result
    operation_id = str(reply.get("operation_id") or outcome.operation_id)
    status = reply.get("status")
    if reply["cancelled"]:
        state = "cancelled"
    elif status in ("queued", "running"):
        # A running Krita call cannot be interrupted (operation.cancel_running is false).
        message = "That operation is already running in Krita and cannot be cancelled."
        details = {"operation_id": operation_id, "state": "running"}
        return envelope.failure("UNSUPPORTED_CAPABILITY", message, details=details)
    elif status == "done":
        state = "completed"
    else:
        error = reply.get("error") or {}
        state = "cancelled" if error.get("code") == "CANCELLED" else "failed"
    data = {"operation_id": operation_id, "state": state}
    return envelope.completed(
        data, f"Operation {operation_id} is {state}.", operation_id=operation_id
    )
