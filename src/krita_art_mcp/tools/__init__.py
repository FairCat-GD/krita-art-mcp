import functools
import logging
import threading
from collections.abc import Callable
from typing import Any

from jsonschema import Draft202012Validator, ValidationError
from mcp.server.mcpserver.tools import Tool
from mcp.server.mcpserver.utilities.func_metadata import ArgModelBase, FuncMetadata
from mcp.types import CallToolResult, ToolAnnotations

from krita_art_mcp import envelope, schemas
from krita_art_mcp.bridge_client import BridgeClient
from krita_art_mcp.tools import observe

# Every message stays under Codex's 8 MiB line limit, with room to spare (C5).
MAX_RESULT_BYTES = 6 * 1024 * 1024
MAX_REPORTED_PROBLEMS = 20

ToolFunction = Callable[[BridgeClient, dict[str, Any]], CallToolResult]

# A tool is registered only once it is built and tested (invariant 10).
TOOLS: dict[str, ToolFunction] = {
    "krita_server_info": observe.server_info,
}
BUILT_TOOLS = sorted(TOOLS)

log = logging.getLogger(__name__)
# Each server process serialises its own calls (PDD Part 8); mcp would run them concurrently.
_CALLS = threading.Lock()


class _NoFields(ArgModelBase):
    pass


class ExactArguments(FuncMetadata):
    # Pydantic would drop or coerce what the contract's JSON Schema must judge, so the tool
    # receives the client's arguments untouched.
    def validate_arguments(self, arguments_to_validate: dict[str, Any]) -> dict[str, Any]:
        return {"arguments": arguments_to_validate}


def build_all(client: BridgeClient) -> list[Tool]:
    return [build(name, functools.partial(run, client)) for name, run in TOOLS.items()]


def build(name: str, run: Callable[[dict[str, Any]], CallToolResult]) -> Tool:
    spec = schemas.load(name)
    inputs = Draft202012Validator(spec["inputSchema"])
    outputs = Draft202012Validator(spec["outputSchema"])

    # Sync on purpose: mcp runs it on a worker thread, so a 45 s bridge wait never stalls stdio.
    def call(arguments: dict[str, Any]) -> CallToolResult:
        with _CALLS:
            return _checked(name, arguments, run, inputs, outputs)

    return Tool(
        fn=call,
        name=name,
        title=None,
        description=spec["description"],
        parameters=spec["inputSchema"],
        fn_metadata=ExactArguments(arg_model=_NoFields, output_schema=spec["outputSchema"]),
        is_async=False,
        context_kwarg=None,
        annotations=ToolAnnotations(**spec["annotations"]),
    )


def _checked(
    name: str,
    arguments: dict[str, Any],
    run: Callable[[dict[str, Any]], CallToolResult],
    inputs: Draft202012Validator,
    outputs: Draft202012Validator,
) -> CallToolResult:
    # Errors are returned, never raised: a raise reaches the client as a bare
    # "Error executing tool", without the envelope.
    problems = sorted(inputs.iter_errors(arguments), key=_pointer)
    if problems:
        result = envelope.failure(
            "INVALID_ARGUMENT",
            f"{_pointer(problems[0]) or '/'}: {problems[0].message}",
            details={
                "errors": [
                    {"path": _pointer(problem), "message": problem.message}
                    for problem in problems[:MAX_REPORTED_PROBLEMS]
                ]
            },
        )
    else:
        try:
            result = run(arguments)
        except Exception:
            log.exception("%s raised", name)
            result = envelope.failure("INTERNAL_ERROR")
    problem = _result_problem(result, outputs)
    if problem is None:
        return result
    log.error("%s returned a result that breaks its contract: %s", name, problem)
    return envelope.failure("INTERNAL_ERROR", details={"reason": problem})


def _result_problem(result: CallToolResult, outputs: Draft202012Validator) -> str | None:
    first = next(iter(outputs.iter_errors(result.structured_content)), None)
    if first is not None:
        return f"the result does not match its output schema: {first.message}"
    size = len(result.model_dump_json(by_alias=True, exclude_none=True).encode("utf-8"))
    if size >= MAX_RESULT_BYTES:
        return f"the result is {size} bytes, over the {MAX_RESULT_BYTES}-byte limit"
    return None


def _pointer(problem: ValidationError) -> str:
    return "".join(f"/{part}" for part in problem.absolute_path)
