from typing import Any

from mcp.types import CallToolResult, TextContent

from krita_art_mcp.errors import API_VERSION, error_body

# Every message stays under Codex's 8 MiB line limit, with room to spare (C5).
MAX_RESULT_BYTES = 6 * 1024 * 1024


def structured(
    status: str,
    *,
    data: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
    document_id: str | None = None,
    operation_id: str | None = None,
) -> dict[str, Any]:
    # `revision` stays in the envelope, always null, until revisions arrive in Phase 3.
    return {
        "api_version": API_VERSION,
        "status": status,
        "document_id": document_id,
        "revision": None,
        "operation_id": operation_id,
        "data": data,
        "error": error,
    }


def _result(text: str, content: dict[str, Any], is_error: bool) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=text)],
        structured_content=content,
        is_error=is_error,
    )


def completed(
    data: dict[str, Any],
    text: str,
    *,
    document_id: str | None = None,
    operation_id: str | None = None,
) -> CallToolResult:
    content = structured("completed", data=data, document_id=document_id, operation_id=operation_id)
    return _result(text, content, False)


def pending(status: str, operation_id: str, *, document_id: str | None = None) -> CallToolResult:
    text = f"Krita is still busy with this call ({status}, operation {operation_id})."
    content = structured(status, document_id=document_id, operation_id=operation_id)
    return _result(text, content, False)


def failed(
    error: dict[str, Any],
    *,
    document_id: str | None = None,
    operation_id: str | None = None,
) -> CallToolResult:
    status = "cancelled" if error["code"] == "CANCELLED" else "failed"
    content = structured(status, error=error, document_id=document_id, operation_id=operation_id)
    return _result(f"{error['code']}: {error['message']}", content, True)


def failure(
    code: str,
    message: str | None = None,
    *,
    retryable: bool | None = None,
    details: dict[str, Any] | None = None,
) -> CallToolResult:
    return failed(error_body(code, message, retryable=retryable, details=details))
