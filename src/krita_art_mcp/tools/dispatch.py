import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from mcp.types import CallToolResult, TextContent

from krita_art_mcp import envelope, journal
from krita_art_mcp.bridge_client import BeforeSend, BridgeClient, Done, Failed, Outcome, Pending
from krita_art_mcp.errors import error_body
from krita_art_mcp.journal import Journal, JournalError
from krita_art_mcp.paths import Places

log = logging.getLogger(__name__)

Receipt = Callable[[Outcome], CallToolResult]


@dataclass(frozen=True)
class ToolCall:
    bridge: BridgeClient
    journal: Journal
    places: Places
    # The MCP client's own name, from its initialize request, for the journal.
    client_name: str | None = None


def args_sha256(tool: str, arguments: dict[str, Any]) -> str:
    canonical = json.dumps(
        {"tool": tool, "arguments": arguments},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def outcome_of(outcome: Done | Failed) -> str:
    if isinstance(outcome, Done):
        return journal.RECEIPT
    error = outcome.error
    # Neither says whether the call ran, so the attempt stays unsettled.
    if error["details"].get("outcome") in ("uncertain", "unregistered"):
        return journal.UNKNOWN
    if not outcome.submitted:
        return journal.NOT_SENT
    if error["code"] == "REQUEST_ID_CONFLICT":
        return journal.CONFLICT
    # The bridge marks retryable only what changed nothing.
    return journal.NO_EFFECT if error["retryable"] else journal.RECEIPT


def stored(result: CallToolResult) -> dict[str, Any]:
    text = result.content[0].text if isinstance(result.content[0], TextContent) else ""
    return {"structured": result.structured_content, "text": text, "is_error": result.is_error}


def restored(record: dict[str, Any]) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=record["text"])],
        structured_content=record["structured"],
        is_error=record["is_error"],
    )


def journaled(
    call: ToolCall,
    tool: str,
    arguments: dict[str, Any],
    request_id: str,
    send: Callable[[BeforeSend], Outcome],
    receipt: Receipt,
    precheck: Callable[[], CallToolResult | None] | None = None,
) -> CallToolResult:
    # Invariant 9: journaled before it is sent; a retry returns the receipt, and a call that
    # reached a Krita session which has since ended is never sent again.
    digest = args_sha256(tool, arguments)
    try:
        prior = call.journal.lookup(request_id)
    except (JournalError, OSError) as problem:
        return envelope.failure("INTERNAL_ERROR", f"The journal could not be read: {problem}")
    if prior is not None:
        bound = prior.binding()
        if bound is not None and bound != (tool, digest):
            details = {"request_id": request_id, "tool": bound[0]}
            return envelope.failure("REQUEST_ID_CONFLICT", details=details)
        if prior.receipt is not None:
            return restored(prior.receipt)
    # A check whose answer can change between attempts, such as the roots, is skipped while an
    # attempt is unsettled: the bridge answers that one before its handler runs again.
    if precheck is not None and (prior is None or not prior.unsettled()):
        refused = precheck()
        if refused is not None:
            return refused
    sent: dict[str, str] = {}

    def before_send(session_id: str, operation_id: str) -> Failed | None:
        lost = None if prior is None else prior.unknown_elsewhere(session_id)
        if lost is not None:
            return _uncertain(lost.operation_id)
        try:
            call.journal.dispatched(
                client=call.client_name,
                request_id=request_id,
                operation_id=operation_id,
                tool=tool,
                args_sha256=digest,
                session_id=session_id,
                args=arguments,
            )
        except OSError as problem:
            message = f"The journal could not be written, so nothing was sent: {problem}"
            return Failed(error_body("INTERNAL_ERROR", message, retryable=True))
        sent.update(session_id=session_id, operation_id=operation_id)
        return None

    outcome = send(before_send)
    result = receipt(outcome)
    if sent and not isinstance(outcome, Pending):
        record(
            call,
            tool,
            request_id,
            digest,
            sent["session_id"],
            sent["operation_id"],
            outcome,
            result,
        )
    return result


def record(
    call: ToolCall,
    tool: str,
    request_id: str,
    digest: str,
    session_id: str,
    operation_id: str | None,
    outcome: Done | Failed,
    result: CallToolResult,
) -> None:
    try:
        call.journal.finished(
            client=call.client_name,
            request_id=request_id,
            operation_id=operation_id,
            tool=tool,
            args_sha256=digest,
            session_id=session_id,
            outcome=outcome_of(outcome),
            result=stored(result),
            bridge_operation_id=outcome.operation_id,
        )
    except OSError:
        # The call is done either way; a retry will find its dispatched line and ask the bridge.
        log.exception("the journal's finished line for %s was not written", request_id)


def _uncertain(operation_id: str) -> Failed:
    message = (
        "This request_id was sent to a Krita session that has ended without saying whether it "
        "ran, so it is never sent again. Inspect the document, then use a new request_id."
    )
    details = {"outcome": "uncertain", "operation_id": operation_id}
    return Failed(error_body("INTERNAL_ERROR", message, retryable=False, details=details))


def from_outcome(
    outcome: Outcome,
    data: Callable[[dict[str, Any]], dict[str, Any]],
    text: Callable[[dict[str, Any]], str],
    document_id: Callable[[dict[str, Any]], str | None] = lambda result: None,
) -> CallToolResult:
    # A receipt depends only on the operation's outcome, so krita_operation_get can rebuild it.
    if isinstance(outcome, Pending):
        return envelope.pending(outcome.status, outcome.operation_id)
    if isinstance(outcome, Failed):
        failed_on = outcome.error["details"].get("document_id")
        return envelope.failed(
            outcome.error,
            document_id=failed_on if isinstance(failed_on, str) else None,
            operation_id=outcome.operation_id,
        )
    result = outcome.result
    return envelope.completed(
        data(result),
        text(result),
        document_id=document_id(result),
        operation_id=outcome.operation_id,
    )
