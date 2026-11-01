import functools
import logging
import threading
from collections import Counter
from collections.abc import Callable
from typing import Any

from jsonschema import Draft202012Validator, ValidationError
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.tools import Tool
from mcp.server.mcpserver.utilities.func_metadata import ArgModelBase, FuncMetadata
from mcp.types import CallToolResult, ImageContent, ToolAnnotations

from krita_art_mcp import envelope, schemas
from krita_art_mcp.bridge_client import BridgeClient
from krita_art_mcp.envelope import MAX_RESULT_BYTES
from krita_art_mcp.journal import Journal
from krita_art_mcp.paths import Places
from krita_art_mcp.tools import (
    changes,
    documents,
    observe,
    operations,
    painting,
    pixels,
    preview,
    saving,
)
from krita_art_mcp.tools.dispatch import ToolCall

# An answer holds each problem three times, and stays well under Claude Code's 25,000 tokens (C4).
MAX_REPORTED_PROBLEMS = 50
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
    "krita_document_save": saving.document_save,
    "krita_resource_list": observe.resource_list,
    "krita_capture": pixels.capture,
    "krita_sample": pixels.sample,
    "krita_layer_create": changes.layer_create,
    "krita_layer_update": changes.layer_update,
    "krita_selection_set": changes.selection_set,
    "krita_protection_set": changes.protection_set,
    "krita_history_step": changes.history_step,
    "krita_paint_stroke": painting.paint_stroke,
    "krita_preview_render": preview.preview_render,
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
    outputs = schemas.output_validator(name)

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
    problems = list(inputs.iter_errors(arguments))
    if problems:
        result = _invalid(problems)
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


def _invalid(problems: list[ValidationError]) -> CallToolResult:
    # One answer names every problem, so an agent fixes them together.
    reported = [
        {"path": _pointer(problem), "message": _said(problem)} for problem in _fair_share(problems)
    ]
    omitted = len(problems) - len(reported)
    parts = [f"{problem['path'] or '/'}: {problem['message']}" for problem in reported]
    parts += [f"and {omitted} more"] if omitted else []
    details = {"errors": reported, "omitted": omitted}
    return envelope.failure("INVALID_ARGUMENT", "; ".join(parts), details=details)


def _fair_share(problems: list[ValidationError]) -> list[ValidationError]:
    # Over the cap fields take turns, so one field's repeated mistake leaves room for another's.
    turns: Counter[Any] = Counter()

    def turn(problem: ValidationError) -> int:
        field = next(iter(problem.absolute_path), None)
        turns[field] += 1
        return turns[field]

    ordered = sorted(problems, key=_position)
    return sorted(sorted(ordered, key=turn)[:MAX_REPORTED_PROBLEMS], key=_position)


def _position(problem: ValidationError) -> tuple[tuple[bool, Any], ...]:
    # Array indices in number order, which a sort on the pointer would not give.
    return tuple((isinstance(part, str), part) for part in problem.absolute_path)


def _said(problem: ValidationError) -> str:
    # A field a rule forbids is `{"not": {}}`, whose own message explains nothing.
    if problem.validator == "not" and problem.validator_value == {}:
        return "not allowed with these arguments"
    return _short(problem.message)


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
    size = _size(result)
    if size >= MAX_RESULT_BYTES:
        return f"the result is {size} bytes, over the {MAX_RESULT_BYTES}-byte limit"
    return None


def _size(result: CallToolResult) -> int:
    # The whole dump's length, but an image's base64 is measured, so only mcp ever dumps it.
    images = [item for item in result.content if isinstance(item, ImageContent)]
    content = [
        item.model_copy(update={"data": ""}) if isinstance(item, ImageContent) else item
        for item in result.content
    ]
    light = result.model_copy(update={"content": content})
    dumped = light.model_dump_json(by_alias=True, exclude_none=True).encode("utf-8")
    return len(dumped) + sum(len(image.data) for image in images)


def _short(message: str) -> str:
    return message if len(message) <= MAX_MESSAGE_CHARS else message[: MAX_MESSAGE_CHARS - 1] + "…"


def _pointer(problem: ValidationError) -> str:
    return "".join(f"/{part}" for part in problem.absolute_path)
