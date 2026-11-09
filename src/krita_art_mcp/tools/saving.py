import hashlib
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from mcp.types import CallToolResult

from krita_art_mcp import envelope, imaging, roots
from krita_art_mcp.bridge_client import BeforeSend, Done, Failed, Outcome, Pending
from krita_art_mcp.errors import NOT_APPLIED, UNCERTAIN, error_body
from krita_art_mcp.paths import Places
from krita_art_mcp.tools.dispatch import ToolCall, from_outcome, journaled
from krita_art_mcp.tools.documents import inside_roots

TOOL = "krita_document_save"


@dataclass(frozen=True)
class Caller:
    # The tool a finish answers for, as its messages name it.
    tool: str
    noun: str


SAVE = Caller(TOOL, "save")
FORMATS = (".kra", ".ora")
SAVE_DATA = (
    "path",
    "sha256",
    "reopened_verified",
    "layers_preserved",
    "baseline_untouched",
    "composite_preserved",
    "expected_losses",
    "dirty",
    "krita_modified",
    "document_path",
)
# What the finish may wait when the save used the whole budget; it is next in Krita's queue.
MIN_FINISH_S = 5.0
CHUNK = 1 << 20


def document_save(call: ToolCall, arguments: dict[str, Any]) -> CallToolResult:
    refused = _save_rules(arguments)
    if refused is not None:
        return refused
    guard = arguments["guard"]
    op_args = {"document_id": guard["document_id"], "path": arguments["path"]}
    started = time.monotonic()

    def precheck() -> CallToolResult | None:
        refused = inside_roots(call.places, "path", arguments["path"])
        return refused if isinstance(refused, CallToolResult) else None

    def send(before_send: BeforeSend) -> Outcome:
        outcome = call.bridge.call(
            "document.save", op_args, request_id=guard["request_id"], before_send=before_send
        )
        return finish_save(call, outcome, call.bridge.budget_s - (time.monotonic() - started))

    return journaled(call, TOOL, arguments, guard["request_id"], send, save_receipt, precheck)


def _save_rules(arguments: dict[str, Any]) -> CallToolResult | None:
    # The plugin checks this too.
    extension = os.path.splitext(arguments["path"])[1].lower()
    if extension not in FORMATS:
        details = {"formats": list(FORMATS)}
        message = "Phase 1 saves .kra and .ora files; PNG export arrives in Phase 4."
        return envelope.failure("UNSUPPORTED_CAPABILITY", message, details=details)
    return None


def finish_save(call: ToolCall, outcome: Outcome, left_s: float, caller: Caller = SAVE) -> Outcome:
    # A save's second half: its mergedimage.png is checked here, then the plugin puts the file
    # in place, or removes it. Retries and polls send the same finish, which the bridge dedups.
    if not isinstance(outcome, Done) or outcome.request_id is None or outcome.operation_id is None:
        return outcome
    result = outcome.result
    merged, problem = _merged(call.places, result)
    args = {
        "document_id": result["document_id"],
        "save_id": result["save_id"],
        "merged_sha256": merged,
        "merged_problem": problem,
    }
    # Under the id derived from the save's, a finish that already ran answers with its own
    # outcome, even when the file it moved or removed makes these arguments differ.
    finished = call.bridge.call(
        "document.save_finish",
        args,
        request_id=f"{outcome.request_id}:finish",
        budget_s=finish_budget(call, left_s),
        operation_id=finish_operation_id(outcome.operation_id),
    )
    return as_save(outcome, finished, caller)


def poll_finish(call: ToolCall, outcome: Outcome, left_s: float) -> Outcome:
    # A poll finishes a save only in the server process that made the call; any other only
    # reads what the bridge holds of the finish.
    if not isinstance(outcome, Done) or outcome.request_id is None or outcome.operation_id is None:
        return outcome
    finish_id = finish_operation_id(outcome.operation_id)
    if call.bridge.made(outcome.operation_id) or call.bridge.made(finish_id):
        return finish_save(call, outcome, left_s)
    found = read_finish(call, outcome, left_s, SAVE)
    return unfinished(outcome, SAVE, "its file is not in place") if found is None else found


def read_finish(call: ToolCall, save: Done, left_s: float, caller: Caller) -> Outcome | None:
    # What the bridge holds of a finish another process sent; None when none was sent.
    found = call.bridge.operation(
        finish_operation_id(str(save.operation_id)), budget_s=finish_budget(call, left_s)
    )
    if unknown(found):
        return None
    # Another process's retry may not run the finish, so its answer promises none.
    return as_save(save, found, caller, hint=False)


def unknown(found: Outcome) -> bool:
    # The bridge has no operation under that id: it was never sent.
    return (
        isinstance(found, Failed) and found.op is None and found.error["code"] == "INVALID_ARGUMENT"
    )


def finish_budget(call: ToolCall, left_s: float) -> float:
    return max(left_s, min(MIN_FINISH_S, call.bridge.budget_s))


def as_save(save: Done, finished: Outcome, caller: Caller = SAVE, hint: bool = True) -> Outcome:
    return chained(save, finished, lambda failed: _finish_error(save, failed, caller, hint))


def chained(save: Done, step: Outcome, error: Callable[[Failed], dict[str, Any]]) -> Outcome:
    # A step sent after the save answers as the save: the receipt and the journal name the
    # save's own operation and request, and a step still running is followed by the save's id.
    if isinstance(step, Pending):
        return Pending(step.status, save.operation_id or step.operation_id, save.op)
    operation_id, request_id, session_id = save.operation_id, save.request_id, save.session_id
    if isinstance(step, Done):
        return replace(
            step, operation_id=operation_id, request_id=request_id, session_id=session_id
        )
    return replace(
        step,
        error=error(step),
        submitted=True,
        operation_id=operation_id,
        request_id=request_id,
        session_id=session_id,
    )


def _finish_error(save: Done, finished: Failed, caller: Caller, hint: bool) -> dict[str, Any]:
    error = finished.error
    details = error["details"]
    same_session = finished.session_id == save.session_id
    if (
        details.get("outcome") == NOT_APPLIED
        and details.get("rollback_verified") is True
        and same_session
        and not save.result.get("replaced_pending")
    ):
        # The finish removed the save's file and folders and confirmed it.
        return error
    # The save reached Krita and may have left its file, or dropped an earlier unfinished one.
    message = error["message"]
    # A finish cancelled at Krita's quit never runs again: a retry meets a new Krita session.
    rerun = finished.submitted and error["retryable"] and error["code"] != "CANCELLED"
    if hint and rerun and same_session:
        message = f"{message} {retry_hint(details, caller.tool, f'finishes the {caller.noun}')}"
    details = {**details, "outcome": UNCERTAIN}
    return {**error, "message": message, "retryable": False, "details": details}


def retry_hint(details: dict[str, Any], tool: str, does: str) -> str:
    # A step refused retryably changed nothing, so the bridge runs it again on a retry.
    holder = details.get("holder_pid")
    if holder is not None:
        return (
            f"Retrying {tool} with the same request_id {does} from the server process {holder} "
            "that holds the document, or once that process has ended."
        )
    return f"Retrying {tool} with the same request_id {does}."


def unfinished(save: Done, caller: Caller, left: str) -> Failed:
    noun = caller.noun
    message = (
        f"Krita wrote and verified this {noun}, but {left}: a poll finishes a {noun} only in "
        f"the server process that made the call. Retrying {caller.tool} with the same request_id "
        "finishes it."
    )
    details = {
        "outcome": UNCERTAIN,
        "document_id": save.result.get("document_id"),
        "operation_id": save.operation_id,
    }
    return Failed(
        error_body("INTERNAL_ERROR", message, retryable=False, details=details),
        save.operation_id,
        submitted=True,
        op=save.op,
        request_id=save.request_id,
        session_id=save.session_id,
    )


def finish_operation_id(save_id: str) -> str:
    return derived_operation_id(save_id, "finish")


def derived_operation_id(save_id: str, step: str) -> str:
    # Derived from the save's, so any poll or retry can ask the bridge for the step.
    return "op-" + hashlib.sha256(f"{save_id}:{step}".encode()).hexdigest()[:32]


def _merged(places: Places, result: dict[str, Any]) -> tuple[str | None, str | None]:
    # Never raises: a finish that does not run leaves the hidden file behind.
    try:
        return _merged_sha256(places, result)
    except Exception as problem:
        return None, f"The saved file cannot be read: {problem}"


def _merged_sha256(places: Places, result: dict[str, Any]) -> tuple[str | None, str | None]:
    # The written file's mergedimage.png, hashed as the plugin hashes the live composite; once
    # the finish has moved it, the target holds the same bytes.
    written, target = Path(result["written"]), Path(result["path"])
    try:
        allowed = roots.allowed(places.config_file, places.harness_dir)
    except roots.ConfigError as problem:
        return None, str(problem)
    if not all(roots.inside(os.path.realpath(path), allowed) for path in (written, target)):
        return None, "The saved file is outside every allowed root."
    if written.exists():
        source = written
    elif target.exists() and file_sha256(target) == result["sha256"]:
        source = target
    else:
        return None, "The saved file is gone from where it was written."
    try:
        pixels = imaging.merged_image(source, result["size_px"])
    except imaging.MergedError as problem:
        return None, str(problem)
    return imaging.bgra_sha256(pixels), None


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def save_receipt(outcome: Outcome) -> CallToolResult:
    if isinstance(outcome, Done) and "dirty_cleared" not in outcome.result:
        # Only the finish's result describes a file in place.
        return envelope.failure(
            "INTERNAL_ERROR",
            "The save was not finished.",
            details={"outcome": UNCERTAIN},
            document_id=outcome.result.get("document_id"),
            operation_id=outcome.operation_id,
        )

    def data(result: dict[str, Any]) -> dict[str, Any]:
        return {key: result[key] for key in SAVE_DATA}

    def text(result: dict[str, Any]) -> str:
        count = len(result["expected_losses"])
        losses = f"{count} expected loss{'' if count == 1 else 'es'}"
        stays = "" if result["dirty_cleared"] else "; it changed meanwhile, so it is still dirty"
        held = ""
        if result["krita_modified"]:
            where = result["document_path"] or "no file of its own"
            held = f" Krita still marks the document modified; it points at {where}."
        return (
            f"Saved {result['document_id']} to {result['path']} ({result['format'].upper()}), "
            f"verified by reopening, {losses}{stays}.{held}"
        )

    return from_outcome(outcome, data, text, lambda result: result["document_id"])
