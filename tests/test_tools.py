import ast
import asyncio
import inspect
import json
import textwrap
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from mcp import Client
from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, ImageContent

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


def _completed(arguments: dict[str, Any], *_: Any) -> CallToolResult:
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
            "krita_document_save",
            "krita_history_step",
            "krita_layer_create",
            "krita_layer_update",
            "krita_operation_cancel",
            "krita_operation_get",
            "krita_paint_fill",
            "krita_paint_stroke",
            "krita_preview_render",
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


def _hints(read_only: bool, destructive: bool) -> dict[str, bool]:
    return {
        "readOnlyHint": read_only,
        "destructiveHint": destructive,
        "idempotentHint": True,
        "openWorldHint": False,
    }


# Each tool's worst permitted behaviour: a read, an addition, or a change to what is there.
READ, ADDS, CHANGES = _hints(True, False), _hints(False, False), _hints(False, True)
HINTS = {
    "krita_capture": READ,
    "krita_document_close": CHANGES,
    "krita_document_create": ADDS,
    "krita_document_inspect": READ,
    "krita_document_list": READ,
    "krita_document_open": ADDS,
    "krita_document_save": ADDS,
    "krita_history_step": CHANGES,
    "krita_layer_create": CHANGES,
    "krita_layer_update": CHANGES,
    "krita_operation_cancel": CHANGES,
    "krita_operation_get": READ,
    "krita_paint_fill": CHANGES,
    "krita_paint_stroke": CHANGES,
    "krita_preview_render": READ,
    "krita_protection_set": ADDS,
    "krita_resource_list": READ,
    "krita_sample": READ,
    "krita_selection_set": CHANGES,
    "krita_server_info": READ,
}


def test_every_tool_keeps_its_hints() -> None:
    assert {name: schemas.load(name)["annotations"] for name in tools.BUILT_TOOLS} == HINTS


def test_arguments_reach_the_tool_exactly_as_sent() -> None:
    received: list[dict[str, Any]] = []

    def record(arguments: dict[str, Any], *_: Any) -> CallToolResult:
        received.append(arguments)
        return envelope.failure("INTERNAL_ERROR")

    # Any tool's schema shows the passthrough; this one takes a single string.
    server = MCPServer("exact", tools=[tools.build("krita_operation_get", record)])
    _call(server, {"operation_id": "[1, 2]"}, "krita_operation_get")
    assert received == [{"operation_id": "[1, 2]"}]


def test_an_unknown_field_is_an_invalid_argument_envelope() -> None:
    ran: list[dict[str, Any]] = []

    def run(arguments: dict[str, Any], *_: Any) -> CallToolResult:
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


def test_an_argument_error_names_every_problem_in_one_answer() -> None:
    server = MCPServer("every", tools=[tools.build("krita_capture", _completed)])
    arguments = {
        "document_id": "doc-1",
        "target": "composite",
        "rect": {"x": 0, "y": 0, "width": 512, "height": 512},
        "scale": 1,
        "filter": "nearest",
    }
    result = _call(server, arguments, "krita_capture")
    error = result.structured_content["error"]
    assert error["code"] == "INVALID_ARGUMENT"
    assert [problem["path"] for problem in error["details"]["errors"]] == ["", "", ""]
    assert error["details"]["omitted"] == 0
    for field in ("source", "layer_id", "document_id"):
        assert field in error["message"] and field in result.content[0].text


def test_more_problems_than_the_report_holds_are_counted() -> None:
    server = MCPServer("many", tools=[tools.build("krita_sample", _completed)])
    example = schemas.load("krita_sample")["example"]["input"]
    wide = "x" * 1000
    result = _call(server, {**example, "points": [[wide, wide]] * 4096}, "krita_sample")
    error = result.structured_content["error"]
    assert error["code"] == "INVALID_ARGUMENT"
    assert len(error["details"]["errors"]) == tools.MAX_REPORTED_PROBLEMS
    # Both members of every point, and the list's own length.
    assert error["details"]["omitted"] == 2 * 4096 + 1 - tools.MAX_REPORTED_PROBLEMS
    assert error["message"].endswith(f"; and {error['details']['omitted']} more")
    assert tools._size(result) < envelope.MAX_RESULT_BYTES


def _refusal(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    server = MCPServer("refused", tools=[tools.build(tool_name, _completed)])
    return dict(_call(server, arguments, tool_name).structured_content["error"])


def _example(tool_name: str, *without: str) -> dict[str, Any]:
    example = schemas.load(tool_name)["example"]["input"]
    return {field: value for field, value in example.items() if field not in without}


def test_a_repeated_mistake_leaves_room_for_another_field() -> None:
    bad = {"points": [["a", "b"]] * 256, "source": {"document_id": "doc-1"}}
    error = _refusal("krita_sample", {**_example("krita_sample"), **bad})
    assert "/source" in [problem["path"] for problem in error["details"]["errors"]]
    assert "frame" in error["message"]


def test_problems_read_in_number_order() -> None:
    arguments = {**_example("krita_sample"), "points": [["a", "b"]] * 20}
    paths = [
        problem["path"] for problem in _refusal("krita_sample", arguments)["details"]["errors"]
    ]
    assert paths[:6] == [f"/points/{index}/{member}" for index in range(3) for member in range(2)]
    assert paths[-1] == "/points/19/1"


@pytest.mark.parametrize(
    ("tool_name", "arguments", "paths"),
    [
        ("krita_capture", _example("krita_capture", "target"), [""]),
        ("krita_sample", _example("krita_sample", "target"), [""]),
        ("krita_document_open", _example("krita_document_open", "mode", "working_dir"), [""]),
    ],
)
def test_a_missing_field_brings_no_false_problem_with_it(
    tool_name: str, arguments: dict[str, Any], paths: list[str]
) -> None:
    errors = _refusal(tool_name, arguments)["details"]["errors"]
    assert [problem["path"] for problem in errors] == paths


def test_a_source_with_no_target_has_one_problem() -> None:
    example = _example("krita_preview_render")
    source = {"document_id": "doc-1", "frame": 0}
    errors = _refusal("krita_preview_render", {**example, "sources": [source]})["details"]["errors"]
    assert [problem["path"] for problem in errors] == ["/sources/0"]


def test_a_forbidden_field_is_refused_in_plain_words() -> None:
    arguments = {**_example("krita_document_open"), "mode": "read_only"}
    error = _refusal("krita_document_open", arguments)
    assert error["message"] == "/working_dir: not allowed with these arguments"


def test_the_largest_report_stays_well_under_claude_codes_token_limit() -> None:
    server = MCPServer("large", tools=[tools.build("krita_sample", _completed)])
    wide = "x" * 1000
    arguments = {**_example("krita_sample"), "points": [[wide, wide]] * 4096}
    result = _call(server, arguments, "krita_sample")
    answer = json.dumps(result.structured_content) + result.content[0].text
    # 25,000 tokens at a pessimistic 2 bytes each.
    assert len(answer) < 50_000


# mcp's parser reads NaN, Infinity and 1e400 as floats, and a long literal as an int.
NOT_FINITE = [float("nan"), float("inf"), float("-inf"), float("1e400"), 10**400]


def _with_a_number(value: Any, number: Any) -> tuple[Any, str]:
    # The example with its first number replaced, or with a field added when it has none.
    def swap(node: Any, path: str) -> tuple[Any, str | None]:
        if isinstance(node, int | float) and not isinstance(node, bool):
            return number, path
        if isinstance(node, dict | list):
            items = node.items() if isinstance(node, dict) else enumerate(node)
            for key, item in items:
                swapped, found = swap(item, f"{path}/{key}")
                if found is not None:
                    copy = dict(node) if isinstance(node, dict) else list(node)
                    copy[key] = swapped
                    return copy, found
        return node, None

    swapped, path = swap(value, "")
    return (swapped, path) if path is not None else ({**value, "number": number}, "/number")


@pytest.mark.parametrize("tool_name", schemas.tool_names())
@pytest.mark.parametrize("number", NOT_FINITE, ids=["nan", "inf", "-inf", "1e400", "10**400"])
def test_every_tool_refuses_a_number_that_is_not_finite(tool_name: str, number: Any) -> None:
    ran: list[dict[str, Any]] = []

    def run(arguments: dict[str, Any], *_: Any) -> CallToolResult:
        ran.append(arguments)
        return _completed(arguments)

    arguments, path = _with_a_number(schemas.load(tool_name)["example"]["input"], number)
    result = tools.build(tool_name, run).fn(arguments, None)
    error = result.structured_content["error"]
    assert error["code"] == "INVALID_ARGUMENT" and ran == []
    assert {"path": path, "message": "not a finite number"} in error["details"]["errors"]


@pytest.mark.parametrize(
    ("field", "number"),
    [("opacity", float("inf")), ("size_px", float("nan")), ("size_px", 10**400)],
)
def test_a_number_that_is_not_finite_is_one_problem(field: str, number: Any) -> None:
    arguments = _example("krita_paint_stroke")
    arguments["brush"] = {**arguments["brush"], field: number}
    # Called directly: the in-memory client would carry NaN and Infinity as null.
    result = tools.build("krita_paint_stroke", _completed).fn(arguments, None)
    errors = result.structured_content["error"]["details"]["errors"]
    assert errors == [{"path": f"/brush/{field}", "message": "not a finite number"}]


def test_a_raising_tool_returns_internal_error() -> None:
    def run(arguments: dict[str, Any], *_: Any) -> CallToolResult:
        raise RuntimeError("boom")

    result = _call(_server(run), {})
    assert result.is_error is True
    assert result.structured_content["error"]["code"] == "INTERNAL_ERROR"


def test_a_result_that_breaks_its_schema_becomes_internal_error() -> None:
    def run(arguments: dict[str, Any], *_: Any) -> CallToolResult:
        return envelope.completed({"krita_version": "5.3.4"}, "incomplete data")

    result = _call(_server(run), {})
    assert result.is_error is True
    error = result.structured_content["error"]
    assert error["code"] == "INTERNAL_ERROR"
    assert "output schema" in error["details"]["reason"]


def test_a_result_over_6_mb_becomes_internal_error() -> None:
    def run(arguments: dict[str, Any], *_: Any) -> CallToolResult:
        result = _completed(arguments)
        result.content[0].text = "x" * (6 * 1024 * 1024)  # type: ignore[union-attr]
        return result

    result = _call(_server(run), {})
    assert result.is_error is True
    assert "byte limit" in result.structured_content["error"]["details"]["reason"]


def test_a_results_size_is_its_whole_dump_with_the_image_only_measured() -> None:
    result = envelope.completed({"note": 'café "quoted"\n'}, "A line with an é.")
    result.content.append(
        ImageContent.model_validate(
            {
                "type": "image",
                "data": "QUJD" * 1000,
                "mimeType": "image/png",
                "_meta": {"codex/imageDetail": "original"},
            }
        )
    )
    whole = result.model_dump_json(by_alias=True, exclude_none=True).encode("utf-8")
    assert tools._size(result) == len(whole)


def test_calls_from_one_server_process_run_one_at_a_time() -> None:
    active = 0
    overlaps = 0
    guard = threading.Lock()

    def run(arguments: dict[str, Any], *_: Any) -> CallToolResult:
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
