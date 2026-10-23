from typing import Any

from mcp.types import CallToolResult

from krita_art_mcp import envelope
from krita_art_mcp.bridge_client import BeforeSend, Outcome
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
        return call.bridge.call(
            "document.close", op_args, request_id=guard["request_id"], before_send=before_send
        )

    return journaled(
        call, "krita_document_close", arguments, guard["request_id"], send, close_receipt
    )


def close_receipt(outcome: Outcome) -> CallToolResult:
    def data(result: dict[str, Any]) -> dict[str, Any]:
        return {"closed": result["closed"], "baseline_untouched": result["baseline_untouched"]}

    return from_outcome(
        outcome, data, lambda result: f"Closed {result['document_id']}.", lambda r: r["document_id"]
    )
