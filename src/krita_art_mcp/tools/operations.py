import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from mcp.types import CallToolResult

from krita_art_mcp import envelope, journal, schemas
from krita_art_mcp.bridge_client import BeforeSend, Done, Failed, Outcome
from krita_art_mcp.errors import APPLIED, NOT_APPLIED, OUTCOMES, UNCERTAIN
from krita_art_mcp.journal import Finished, JournalError
from krita_art_mcp.paths import Places
from krita_art_mcp.tools import (
    branching,
    changes,
    documents,
    observe,
    painting,
    pixels,
    preview,
    saving,
)
from krita_art_mcp.tools.dispatch import (
    Receipt,
    ToolCall,
    contract_problem,
    failed_receipt,
    identity,
    journaled,
    raw_receipt,
    record,
)

log = logging.getLogger(__name__)

Resolver = Callable[[Places, Outcome], Outcome]
# What a poll sends after an op, with the budget left: a save's second half.
Finisher = Callable[[ToolCall, Outcome, float], Outcome]


@dataclass(frozen=True)
class Known:
    tool: str
    receipt: Receipt
    # For an op whose result names files the server keeps, reads or removes before the receipt.
    resolve: Resolver | None = None
    finish: Finisher | None = None


# Each bridge op an agent can be handed an operation_id for, with its tool's receipt.
RECEIPTS: dict[str, Known] = {
    "server_info": Known("krita_server_info", observe.server_info_receipt),
    "document.list": Known("krita_document_list", documents.list_receipt),
    "document.create": Known("krita_document_create", documents.create_receipt),
    "document.open": Known("krita_document_open", documents.open_receipt),
    "document.inspect": Known("krita_document_inspect", documents.inspect_receipt),
    "document.close": Known(
        "krita_document_close", documents.close_receipt, documents.resolve_close
    ),
    "resource.list": Known("krita_resource_list", observe.resource_receipt),
    "capture.read": Known("krita_capture", pixels.capture_receipt, pixels.resolve_capture),
    "sample.read": Known("krita_sample", pixels.sample_receipt, pixels.resolve_sample),
    "layer.create": Known("krita_layer_create", changes.layer_receipt, changes.resolve_update),
    "layer.update": Known("krita_layer_update", changes.update_receipt, changes.resolve_update),
    "layer.duplicate": Known(
        "krita_layer_duplicate", changes.duplicate_receipt, changes.resolve_update
    ),
    "layer.reorder": Known("krita_layer_reorder", changes.reorder_receipt, changes.resolve_update),
    "layer.remove": Known("krita_layer_remove", changes.remove_receipt, changes.resolve_update),
    "selection.set": Known(
        "krita_selection_set", changes.selection_receipt, changes.resolve_selection
    ),
    "protection.set": Known("krita_protection_set", changes.protection_receipt),
    "history.step": Known("krita_history_step", changes.history_receipt, changes.resolve_history),
    "paint.stroke": Known("krita_paint_stroke", painting.paint_receipt, changes.resolve_update),
    "paint.fill": Known("krita_paint_fill", painting.fill_receipt, changes.resolve_update),
    "preview.read": Known("krita_preview_render", preview.preview_receipt, preview.resolve_preview),
    "document.save": Known("krita_document_save", saving.save_receipt, finish=saving.poll_finish),
    "document.duplicate": Known(
        "krita_document_duplicate", branching.duplicate_receipt, finish=branching.poll_duplicate
    ),
}


def operation_get(call: ToolCall, arguments: dict[str, Any]) -> CallToolResult:
    operation_id = arguments["operation_id"]
    started = time.monotonic()
    try:
        sent_in = call.journal.session_of(operation_id)
    except (JournalError, OSError) as problem:
        return envelope.failure("INTERNAL_ERROR", f"The journal could not be read: {problem}")
    outcome = call.bridge.operation(operation_id, sent_in=sent_in)
    if isinstance(outcome, Failed) and outcome.op is None:
        # Not the operation's own outcome: the id is unknown, or Krita is gone, and only a
        # finished line can still say what became of it.
        answered = _from_journal(call, operation_id)
        return answered or envelope.failed(outcome.error, operation_id=operation_id)
    known = RECEIPTS.get(outcome.op or "")
    if outcome.op is not None and known is None:
        details = {"operation_id": operation_id, "op": outcome.op}
        message = "That operation belongs to no tool."
        return envelope.failure("INVALID_ARGUMENT", message, details=details)
    if isinstance(outcome, Done | Failed):
        changes.settle_masks(call.places, outcome.request_id)
    if known is not None and known.finish is not None:
        outcome = known.finish(call, outcome, call.bridge.budget_s - (time.monotonic() - started))
    if known is not None and known.resolve is not None:
        outcome = known.resolve(call.places, outcome)
    tool = None if known is None else known.tool
    data: dict[str, Any] = {
        "operation_id": outcome.operation_id or operation_id,
        "tool": tool,
        "state": _state(outcome),
        "progress": None,
        "receipt": None,
        "outcome": None,
        "receipt_valid": None,
        "receipt_problem": None,
    }
    if known is None or not isinstance(outcome, Done | Failed):
        text = f"Operation {data['operation_id']} is still {data['state']}."
        return envelope.completed(data, text, operation_id=data["operation_id"])
    receipt = _receipt(known, outcome)
    content = receipt.structured_content or {}
    broken = contract_problem(schemas.output_validator(known.tool), content)
    data.update(
        receipt=content,
        outcome=_outcome_of(outcome),
        receipt_valid=broken is None,
        receipt_problem=broken,
    )
    _finish_journaled(call, outcome, receipt, operation_id)
    text = f"Operation {data['operation_id']} ({tool}) {data['state']}."
    result = envelope.completed(
        data, text, document_id=identity(content, "document_id"), operation_id=data["operation_id"]
    )
    # The receipt's own line and any image it carries, as the call itself would have shown.
    result.content.extend(receipt.content)
    return result


def _receipt(known: Known, outcome: Done | Failed) -> CallToolResult:
    # A receipt that raises is one more bad receipt: what the call did still stands.
    try:
        return known.receipt(outcome)
    except Exception:
        log.exception("the receipt of %s raised", outcome.operation_id)
        return raw_receipt(outcome) if isinstance(outcome, Done) else failed_receipt(outcome)


def _outcome_of(outcome: Done | Failed) -> str:
    if isinstance(outcome, Done):
        return APPLIED
    return said(outcome.error)


def said(error: Any) -> str:
    # What a failure's own details state, from data nothing has validated; unstated is uncertain.
    details = error.get("details") if isinstance(error, dict) else None
    found = details.get("outcome") if isinstance(details, dict) else None
    return found if found in OUTCOMES else UNCERTAIN


def _from_journal(call: ToolCall, operation_id: str) -> CallToolResult | None:
    # The answer once Krita has moved on. An outcome is read from the line, never assumed.
    try:
        line = call.journal.finished_line(operation_id)
    except (JournalError, OSError):
        return None
    if line is None:
        return None
    content = (line.result or {}).get("structured")
    if not isinstance(content, dict) or line.tool not in schemas.tool_names():
        return None
    state = content.get("status")
    state = state if state in ("completed", "failed", "cancelled") else "failed"
    problem = contract_problem(schemas.output_validator(line.tool), content)
    data = {
        "operation_id": operation_id,
        "tool": line.tool,
        "state": state,
        "progress": None,
        "receipt": content,
        "outcome": _journaled_outcome(line, state, content),
        "receipt_valid": problem is None,
        "receipt_problem": problem,
    }
    text = f"Operation {operation_id} ({line.tool}) {state}, from the journal."
    return envelope.completed(
        data, text, document_id=identity(content, "document_id"), operation_id=operation_id
    )


def _journaled_outcome(line: Finished, state: str, content: dict[str, Any]) -> str:
    if line.outcome == journal.UNKNOWN:
        return UNCERTAIN
    if line.outcome in (journal.NO_EFFECT, journal.NOT_SENT, journal.CONFLICT):
        return NOT_APPLIED
    return APPLIED if state == "completed" else said(content.get("error"))


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
        # No one call spans it: the poll's own time is not the tool's.
        elapsed_ms=None,
    )


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
