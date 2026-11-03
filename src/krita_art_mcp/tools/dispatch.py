import hashlib
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import best_match
from mcp.types import CallToolResult, TextContent

from krita_art_mcp import envelope, journal
from krita_art_mcp.bridge_client import BeforeSend, BridgeClient, Done, Failed, Outcome, Pending
from krita_art_mcp.errors import APPLIED, UNCERTAIN, UNREGISTERED, error_body
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
    # When the call reached the server, on the monotonic clock.
    started: float = field(default_factory=time.monotonic)


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
    if error["details"].get("outcome") in (UNCERTAIN, UNREGISTERED):
        return journal.UNKNOWN
    if error["details"].get("outcome") == APPLIED:
        return journal.RECEIPT
    if not outcome.submitted:
        return journal.NOT_SENT
    if error["code"] == "REQUEST_ID_CONFLICT":
        return journal.CONFLICT
    # The bridge marks retryable only what changed nothing.
    return journal.NO_EFFECT if error["retryable"] else journal.RECEIPT


def contract_problem(validator: Draft202012Validator, content: Any) -> str | None:
    # Where and which rule, never jsonschema's message: that quotes the whole instance.
    found = best_match(validator.iter_errors(content))
    if found is None:
        return None
    return f"{found.json_path} breaks its {found.validator} rule"


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

    outcome: Outcome | None = None
    try:
        outcome = send(before_send)
        result = receipt(outcome)
    except Exception:
        # With nothing sent, the catch-all's answer is true: the call changed nothing.
        if not sent:
            raise
        log.exception("%s raised after it was sent", tool)
        outcome, result = _after_send(outcome, sent["operation_id"])
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
            elapsed_ms=round((time.monotonic() - call.started) * 1000),
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
    elapsed_ms: int | None,
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
            elapsed_ms=elapsed_ms,
        )
    except Exception:
        # The call is done either way; a retry will find its dispatched line and ask the bridge.
        log.exception("the journal's finished line for %s was not written", request_id)


def _after_send(outcome: Outcome | None, operation_id: str) -> tuple[Done | Failed, CallToolResult]:
    # A raise past dispatch keeps the call's identity, and only the bridge's done says it applied.
    if isinstance(outcome, Done):
        return outcome, raw_receipt(outcome)
    if isinstance(outcome, Failed):
        return outcome, failed_receipt(outcome)
    message = "The server raised after sending the call; whether the call ran is unknown."
    details = {"outcome": UNCERTAIN, "operation_id": operation_id}
    error = error_body("INTERNAL_ERROR", message, retryable=False, details=details)
    lost = Failed(error, operation_id, submitted=True)
    return lost, failed_receipt(lost)


def identity(content: dict[str, Any], field: str) -> str | None:
    # An id as the envelope may carry it, from content nothing has validated.
    found = content.get(field)
    return found if isinstance(found, str) and found else None


def raw_receipt(outcome: Done) -> CallToolResult:
    # What the bridge said, unshaped: a receipt that cannot be built loses none of it.
    return envelope.completed(
        outcome.result,
        f"Operation {outcome.operation_id} finished; its receipt could not be built.",
        document_id=identity(outcome.result, "document_id"),
        operation_id=outcome.operation_id,
    )


def failed_receipt(outcome: Failed) -> CallToolResult:
    return envelope.failed(
        outcome.error,
        document_id=identity(outcome.error["details"], "document_id"),
        operation_id=outcome.operation_id,
    )


def failed_after(outcome: Done, error: dict[str, Any]) -> Failed:
    # The server's part of a finished op failed: the failure keeps the op's identity.
    return Failed(
        error,
        outcome.operation_id,
        submitted=True,
        op=outcome.op,
        request_id=outcome.request_id,
        session_id=outcome.session_id,
    )


def applied_failure(outcome: Done, code: str, message: str) -> Failed:
    # The op finished and only the server's part of it did not: never retryable.
    details: dict[str, Any] = {"outcome": APPLIED}
    document_id = identity(outcome.result, "document_id")
    if document_id is not None:
        details["document_id"] = document_id
    return failed_after(outcome, error_body(code, message, retryable=False, details=details))


def _uncertain(operation_id: str) -> Failed:
    message = (
        "This request_id was sent to a Krita session that has ended without saying whether it "
        "ran, so it is never sent again. Inspect the document, then use a new request_id."
    )
    details = {"outcome": UNCERTAIN, "operation_id": operation_id}
    error = error_body("INTERNAL_ERROR", message, retryable=False, details=details)
    return Failed(error, operation_id)


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
        return failed_receipt(outcome)
    result = outcome.result
    return envelope.completed(
        data(result),
        text(result),
        document_id=document_id(result),
        operation_id=outcome.operation_id,
    )
