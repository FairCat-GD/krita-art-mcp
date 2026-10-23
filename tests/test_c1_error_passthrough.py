import asyncio
from typing import Any

from jsonschema import Draft202012Validator
from mcp import Client
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.tools import Tool
from mcp.server.mcpserver.utilities.func_metadata import ArgModelBase, FuncMetadata
from mcp.types import CallToolResult, TextContent

from krita_art_mcp import schemas

BUSY_ENVELOPE: dict[str, Any] = {
    "api_version": "0.1.0",
    "status": "failed",
    "document_id": "doc-1",
    "revision": None,
    "operation_id": None,
    "data": None,
    "error": {
        "code": "BUSY",
        "message": "Document has another active operation.",
        "retryable": True,
        "details": {"retry_after_ms": 500, "writes_performed": False},
    },
}
ERROR_TEXT = "BUSY: Document has another active operation."


class _NoArguments(ArgModelBase):
    pass


def _error_server(spec: dict[str, Any]) -> MCPServer:
    def fail() -> CallToolResult:
        return CallToolResult(
            is_error=True,
            content=[TextContent(type="text", text=ERROR_TEXT)],
            structured_content=BUSY_ENVELOPE,
        )

    # Hand-built metadata publishes the contract's own JSON Schemas.
    tool = Tool(
        fn=fail,
        name=spec["name"],
        title=None,
        description=spec["description"],
        parameters=spec["inputSchema"],
        fn_metadata=FuncMetadata(arg_model=_NoArguments, output_schema=spec["outputSchema"]),
        is_async=False,
        context_kwarg=None,
        annotations=None,
    )
    return MCPServer("c1-check", tools=[tool])


def test_error_result_reaches_the_client_unchanged() -> None:
    spec = schemas.load("krita_server_info")
    assert list(Draft202012Validator(spec["outputSchema"]).iter_errors(BUSY_ENVELOPE)) == []

    async def call() -> tuple[Any, CallToolResult]:
        async with Client(_error_server(spec)) as client:
            listed = (await client.list_tools()).tools
            return listed, await client.call_tool(spec["name"], {})

    listed, result = asyncio.run(call())
    assert [tool.output_schema for tool in listed] == [spec["outputSchema"]]
    assert result.is_error is True
    assert result.content == [TextContent(type="text", text=ERROR_TEXT)]
    assert result.structured_content == BUSY_ENVELOPE
