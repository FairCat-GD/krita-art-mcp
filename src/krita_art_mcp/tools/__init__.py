import functools
import logging
import threading
from collections.abc import Callable
from typing import Any

from jsonschema import Draft202012Validator, ValidationError
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.tools import Tool
from mcp.server.mcpserver.utilities.func_metadata import ArgModelBase, FuncMetadata
from mcp.types import CallToolResult, ToolAnnotations

from krita_art_mcp import envelope, schemas
from krita_art_mcp.bridge_client import BridgeClient
from krita_art_mcp.envelope import MAX_RESULT_BYTES
from krita_art_mcp.journal import Journal
from krita_art_mcp.paths import Places
from krita_art_mcp.tools import changes, documents, observe, operations, pixels
from krita_art_mcp.tools.dispatch import ToolCall

MAX_REPORTED_PROBLEMS = 20
# jsonschema quotes the offending value, which may be a 4096-point array.
MAX_MESSAGE_CHARS = 200

ToolFunction = Callable[[ToolCall, dict[str, Any]], CallToolResult]
# The arguments, and the MCP client's name for the journal.
Run = Callable[[dict[str, Any], str | None], CallToolResult]

# A tool is registered only once it is built and tested (invariant 10).
TOOLS: dict[str, ToolFunction] = {
    "krita_server_info": observe.server_info,
    "krita_document_list": documents.document_list,
    "krita_document_open": documents.document_open,
    "krita_document_create": documents.document_create,
    "krita_document_inspect": documents.document_inspect,
    "krita_document_close": documents.document_close,
    "krita_resource_list": observe.resource_list,
    "krita_capture": pixels.capture,
    "krita_sample": pixels.sample,
    "krita_layer_create": changes.layer_create,
    "krita_layer_update": changes.layer_update,
    "krita_selection_set": changes.selection_set,
    "krita_protection_set": changes.protection_set,
    "krita_history_step": changes.history_step,
    "krita_operation_get": operations.operation_get,
    "krita_operation_cancel": operations.operation_cancel,
}
BUILT_TOOLS = sorted(TOOLS)

log = logging.getLogger(__name__)
# Each server process serialises its own calls (PDD Part 8); mcp would run them concurrently.
CALLS = threading.Lock()


class _NoFields(ArgModelBase):
    pass


class ExactArguments(FuncMetadata):
    # Pydantic would drop or coerce what the contract's JSON Schema must judge, so the tool
    # receives the client's arguments untouched.
    def validate_arguments(self, arguments_to_validate: dict[str, Any]) -> dict[str, Any]:
        return {"arguments": arguments_to_validate}


def build_all(bridge: BridgeClient, journal: Journal, places: Places) -> list[Tool]:
    return [
        build(name, functools.partial(_bound, tool, bridge, journal, places))
        for name, tool in TOOLS.items()
    ]


def _bound(
    tool: ToolFunction,
    bridge: BridgeClient,
    journal: Journal,
    places: Places,
    arguments: dict[str, Any],
    client_name: str | None,
) -> CallToolResult:
    return tool(ToolCall(bridge, journal, places, client_name), arguments)


def build(name: str, run: Run) -> Tool:
    spec = schemas.load(name)
    inputs = Draft202012Validator(spec["inputSchema"])
    outputs = Draft202012Validator(spec["outputSchema"])

    # Sync on purpose: mcp runs it on a worker thread, so a 45 s bridge wait never stalls stdio.
    def call(arguments: dict[str, Any], ctx: Context) -> CallToolResult:
        client_name = _client_name(ctx)
        with CALLS:
            return _checked(name, arguments, client_name, run, inputs, outputs)

    return Tool(
        fn=call,
        name=name,
        title=None,
        description=spec["description"],
        parameters=spec["inputSchema"],
        fn_metadata=ExactArguments(arg_model=_NoFields, output_schema=spec["outputSchema"]),
        is_async=False,
        context_kwarg="ctx",
        annotations=ToolAnnotations(**spec["annotations"]),
    )


def _checked(
    name: str,
    arguments: dict[str, Any],
    client_name: str | None,
    run: Run,
    inputs: Draft202012Validator,
    outputs: Draft202012Validator,
) -> CallToolResult:
    # Errors are returned, never raised: a raise reaches the client as a bare
    # "Error executing tool", without the envelope.
    problems = sorted(inputs.iter_errors(arguments), key=_pointer)
    if problems:
        result = envelope.failure(
            "INVALID_ARGUMENT",
            f"{_pointer(problems[0]) or '/'}: {_short(problems[0].message)}",
            details={
                "errors": [
                    {"path": _pointer(problem), "message": _short(problem.message)}
                    for problem in problems[:MAX_REPORTED_PROBLEMS]
                ]
            },
        )
    else:
        try:
            result = run(arguments, client_name)
        except Exception:
            log.exception("%s raised", name)
            result = envelope.failure("INTERNAL_ERROR")
    problem = _result_problem(result, outputs)
    if problem is None:
        return result
    log.error("%s returned a result that breaks its contract: %s", name, problem)
    return envelope.failure("INTERNAL_ERROR", details={"reason": problem})


def _client_name(ctx: Any) -> str | None:
    # Optional on newer protocol versions, so a missing name is simply not recorded.
    try:
        params = ctx.session.client_params
    except Exception:
        return None
    return None if params is None else str(params.client_info.name)


def _result_problem(result: CallToolResult, outputs: Draft202012Validator) -> str | None:
    first = next(iter(outputs.iter_errors(result.structured_content)), None)
    if first is not None:
        return f"the result does not match its output schema: {first.message}"
    size = len(result.model_dump_json(by_alias=True, exclude_none=True).encode("utf-8"))
    if size >= MAX_RESULT_BYTES:
        return f"the result is {size} bytes, over the {MAX_RESULT_BYTES}-byte limit"
    return None


def _short(message: str) -> str:
    return message if len(message) <= MAX_MESSAGE_CHARS else message[: MAX_MESSAGE_CHARS - 1] + "…"


def _pointer(problem: ValidationError) -> str:
    return "".join(f"/{part}" for part in problem.absolute_path)
