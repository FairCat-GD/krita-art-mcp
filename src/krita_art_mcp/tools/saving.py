import hashlib
import os
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from mcp.types import CallToolResult

from krita_art_mcp import envelope, imaging, roots
from krita_art_mcp.bridge_client import BeforeSend, Done, Outcome, Pending
from krita_art_mcp.errors import error_body
from krita_art_mcp.paths import Places
from krita_art_mcp.tools.dispatch import ToolCall, from_outcome, journaled

TOOL = "krita_document_save"
FORMATS = (".kra", ".ora")
SAVE_DATA = (
    "path",
    "sha256",
    "reopened_verified",
    "layers_preserved",
    "baseline_untouched",
    "composite_preserved",
    "expected_losses",
)
# What the finish may wait when the save used the whole budget; it is next in Krita's queue.
MIN_FINISH_S = 5.0
CHUNK = 1 << 20


def document_save(call: ToolCall, arguments: dict[str, Any]) -> CallToolResult:
    extension = os.path.splitext(arguments["path"])[1].lower()
    if extension not in FORMATS:
        details = {"formats": list(FORMATS)}
        message = "Phase 1 saves .kra and .ora files; PNG export arrives in Phase 4."
        return envelope.failure("UNSUPPORTED_CAPABILITY", message, details=details)
    guard = arguments["guard"]
    op_args = {"document_id": guard["document_id"], "path": arguments["path"]}
    started = time.monotonic()

    def precheck() -> CallToolResult | None:
        return _path_refusal(call.places, arguments["path"])

    def send(before_send: BeforeSend) -> Outcome:
        outcome = call.bridge.call(
            "document.save", op_args, request_id=guard["request_id"], before_send=before_send
        )
        return finish_save(call, outcome, call.bridge.budget_s - (time.monotonic() - started))

    return journaled(call, TOOL, arguments, guard["request_id"], send, save_receipt, precheck)


def finish_save(call: ToolCall, outcome: Outcome, left_s: float) -> Outcome:
    # A save's second half: its mergedimage.png is checked here, then the plugin puts the file
    # in place, or removes it. Retries and polls send the same finish, which the bridge dedups.
    if not isinstance(outcome, Done) or outcome.request_id is None:
        return outcome
    result = outcome.result
    merged, problem = _merged(call.places, result)
    args = {
        "document_id": result["document_id"],
        "save_id": result["save_id"],
        "merged_sha256": merged,
        "merged_problem": problem,
    }
    finished = call.bridge.call(
        "document.save_finish",
        args,
        request_id=f"{outcome.request_id}:finish",
        budget_s=max(left_s, min(MIN_FINISH_S, call.bridge.budget_s)),
    )
    if isinstance(finished, Pending):
        # Followed by the save's own operation id, which finishes the same way.
        return Pending(finished.status, str(outcome.operation_id), outcome.op)
    # The receipt and the journal name the save's own operation and request.
    operation_id, request_id, session_id = (
        outcome.operation_id,
        outcome.request_id,
        outcome.session_id,
    )
    if isinstance(finished, Done):
        return replace(
            finished, operation_id=operation_id, request_id=request_id, session_id=session_id
        )
    error = finished.error
    if error["code"] == "REQUEST_ID_CONFLICT":
        details = {"path": result["path"]}
        message = (
            "This save finished earlier, but its file is no longer where it was written; "
            "look in the folder before saving again."
        )
        error = error_body("INTERNAL_ERROR", message, details=details)
    # The save itself reached Krita, whatever became of the finish.
    return replace(
        finished,
        error=error,
        submitted=True,
        operation_id=operation_id,
        request_id=request_id,
        session_id=session_id,
    )


def _merged(places: Places, result: dict[str, Any]) -> tuple[str | None, str | None]:
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
    elif target.exists() and _file_sha256(target) == result["sha256"]:
        source = target
    else:
        return None, "The saved file is gone from where it was written."
    try:
        pixels = imaging.merged_image(source)
    except imaging.MergedError as problem:
        return None, str(problem)
    width, height = result["size_px"]
    if pixels.shape[:2] != (height, width):
        found = f"{pixels.shape[1]} x {pixels.shape[0]}"
        return None, f"{imaging.MERGED} is {found} px; the document is {width} x {height}."
    return imaging.bgra_sha256(pixels), None


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _path_refusal(places: Places, path: str) -> CallToolResult | None:
    # Invariant 3, on the server's side; the plugin checks again.
    try:
        allowed = roots.allowed(places.config_file, places.harness_dir)
    except roots.ConfigError as problem:
        return envelope.failure("INTERNAL_ERROR", str(problem))
    resolved = roots.resolve(path)
    if resolved is None:
        message = "path must be an absolute path."
        return envelope.failure("INVALID_ARGUMENT", message, details={"field": "path"})
    if not roots.inside(resolved, allowed):
        message = "path is outside every allowed root."
        return envelope.failure("PATH_NOT_ALLOWED", message, details={"field": "path"})
    return None


def save_receipt(outcome: Outcome) -> CallToolResult:
    if isinstance(outcome, Done) and "dirty_cleared" not in outcome.result:
        # Only the finish's result describes a file in place.
        return envelope.failure("INTERNAL_ERROR", "The save was not finished.")

    def data(result: dict[str, Any]) -> dict[str, Any]:
        return {key: result[key] for key in SAVE_DATA}

    def text(result: dict[str, Any]) -> str:
        count = len(result["expected_losses"])
        losses = f"{count} expected loss{'' if count == 1 else 'es'}"
        stays = "" if result["dirty_cleared"] else "; it changed meanwhile, so it is still dirty"
        return (
            f"Saved {result['document_id']} to {result['path']} ({result['format'].upper()}), "
            f"verified by reopening, {losses}{stays}."
        )

    return from_outcome(outcome, data, text, lambda result: result["document_id"])
