import ast
import asyncio
import inspect
import textwrap
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from mcp import Client
from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult

from krita_art_mcp import baselines, envelope, schemas, server, tools
from krita_art_mcp.bridge_client import BridgeClient
from krita_art_mcp.journal import Journal
from krita_art_mcp.paths import Places
from krita_art_mcp.server import build_server
from krita_art_mcp.tools import operations

INFO_DATA: dict[str, Any] = schemas.load("krita_server_info")["example"]["structuredContent"][
    "data"
]


def _call(server: MCPServer, arguments: dict[str, Any], name: str = "krita_server_info") -> Any:
    async def call() -> CallToolResult:
        async with Client(server) as mcp:
            return await mcp.call_tool(name, arguments)

    return asyncio.run(call())


def _server(run: tools.Run) -> MCPServer:
    return MCPServer("tools-test", tools=[tools.build("krita_server_info", run)])


def _completed(arguments: dict[str, Any], client_name: str | None = None) -> CallToolResult:
    return envelope.completed(INFO_DATA, "ok")


def test_only_built_tools_are_registered_with_their_contract_schemas(tmp_path: Path) -> None:
    async def listed() -> list[Any]:
        journal, places = Journal(tmp_path / "journal"), Places.under(tmp_path, tmp_path)
        client = BridgeClient(bridge_file=tmp_path / "bridge.json")
        async with Client(build_server(client, journal, places)) as mcp:
            return list((await mcp.list_tools()).tools)

    registered = asyncio.run(listed())
    assert (
        sorted(tool.name for tool in registered)
        == tools.BUILT_TOOLS
        == [
            "krita_capture",
            "krita_document_close",
            "krita_document_create",
            "krita_document_inspect",
            "krita_document_list",
            "krita_document_open",
            "krita_history_step",
            "krita_layer_create",
            "krita_layer_update",
            "krita_operation_cancel",
            "krita_operation_get",
            "krita_paint_stroke",
            "krita_protection_set",
            "krita_resource_list",
            "krita_sample",
            "krita_selection_set",
            "krita_server_info",
        ]
    )
    for tool in registered:
        spec = schemas.load(tool.name)
        assert tool.input_schema == spec["inputSchema"]
        assert tool.output_schema == spec["outputSchema"]
        assert tool.description == spec["description"]
        assert tool.annotations is not None
        assert tool.annotations.model_dump(by_alias=True, exclude_none=True) == spec["annotations"]


def test_arguments_reach_the_tool_exactly_as_sent() -> None:
    received: list[dict[str, Any]] = []

    def record(arguments: dict[str, Any], client_name: str | None = None) -> CallToolResult:
        received.append(arguments)
        return envelope.failure("INTERNAL_ERROR")

    # Any tool's schema shows the passthrough; this one takes a single string.
    server = MCPServer("exact", tools=[tools.build("krita_operation_get", record)])
    _call(server, {"operation_id": "[1, 2]"}, "krita_operation_get")
    assert received == [{"operation_id": "[1, 2]"}]


def test_an_unknown_field_is_an_invalid_argument_envelope() -> None:
    ran: list[dict[str, Any]] = []

    def run(arguments: dict[str, Any], client_name: str | None = None) -> CallToolResult:
        ran.append(arguments)
        return _completed(arguments)

    result = _call(_server(run), {"stray": "[1, 2]", "_hidden": {"x": None}})
    assert ran == []
    assert result.is_error is True
    content = result.structured_content
    assert content["status"] == "failed"
    assert content["error"]["code"] == "INVALID_ARGUMENT"
    assert "stray" in content["error"]["message"] and "_hidden" in content["error"]["message"]
    assert result.content[0].text.startswith("INVALID_ARGUMENT: ")


def test_a_huge_invalid_argument_gets_a_short_message() -> None:
    server = MCPServer("short", tools=[tools.build("krita_operation_get", _completed)])
    result = _call(server, {"operation_id": list(range(100_000))}, "krita_operation_get")
    error = result.structured_content["error"]
    assert error["code"] == "INVALID_ARGUMENT"
    assert len(error["message"]) <= 220
    assert all(len(problem["message"]) <= 200 for problem in error["details"]["errors"])


def test_a_raising_tool_returns_internal_error() -> None:
    def run(arguments: dict[str, Any], client_name: str | None = None) -> CallToolResult:
        raise RuntimeError("boom")

    result = _call(_server(run), {})
    assert result.is_error is True
    assert result.structured_content["error"]["code"] == "INTERNAL_ERROR"


def test_a_result_that_breaks_its_schema_becomes_internal_error() -> None:
    def run(arguments: dict[str, Any], client_name: str | None = None) -> CallToolResult:
        return envelope.completed({"krita_version": "5.3.4"}, "incomplete data")

    result = _call(_server(run), {})
    assert result.is_error is True
    error = result.structured_content["error"]
    assert error["code"] == "INTERNAL_ERROR"
    assert "output schema" in error["details"]["reason"]


def test_a_result_over_6_mb_becomes_internal_error() -> None:
    def run(arguments: dict[str, Any], client_name: str | None = None) -> CallToolResult:
        result = _completed(arguments)
        result.content[0].text = "x" * (6 * 1024 * 1024)  # type: ignore[union-attr]
        return result

    result = _call(_server(run), {})
    assert result.is_error is True
    assert "byte limit" in result.structured_content["error"]["details"]["reason"]


def test_calls_from_one_server_process_run_one_at_a_time() -> None:
    active = 0
    overlaps = 0
    guard = threading.Lock()

    def run(arguments: dict[str, Any], client_name: str | None = None) -> CallToolResult:
        nonlocal active, overlaps
        with guard:
            active += 1
            overlaps += active > 1
        time.sleep(0.05)
        with guard:
            active -= 1
        return _completed(arguments)

    async def concurrent() -> list[CallToolResult]:
        async with Client(_server(run)) as mcp:
            calls = [mcp.call_tool("krita_server_info", {}) for _ in range(4)]
            return list(await asyncio.gather(*calls))

    results = asyncio.run(concurrent())
    assert [result.is_error for result in results] == [False] * 4
    assert overlaps == 0


def _ops_sent(function: Callable[..., Any]) -> set[str]:
    tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
    return {
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "call"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    }


def test_every_op_a_tool_sends_has_that_tools_receipt() -> None:
    # krita_operation_get rebuilds a call's receipt from its op alone.
    sent = {name: _ops_sent(function) for name, function in tools.TOOLS.items()}
    for name, ops in sent.items():
        for op in ops:
            known = operations.RECEIPTS.get(op)
            assert known is not None and known.tool == name, (name, op)
    assert set(operations.RECEIPTS) == set().union(*sent.values())


def test_the_baseline_sweep_takes_its_turn_with_the_tool_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    held: list[bool] = []
    monkeypatch.setattr(
        server,
        "BridgeClient",
        lambda **options: BridgeClient(bridge_file=tmp_path / "b", **options),
    )
    monkeypatch.setattr(
        baselines, "sweep", lambda client, folder: held.append(tools.CALLS.locked())
    )
    server._sweep_baselines(Places.under(tmp_path, tmp_path))
    assert held == [True]
    assert not tools.CALLS.locked()
