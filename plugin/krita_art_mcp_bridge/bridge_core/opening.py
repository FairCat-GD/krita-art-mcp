import datetime
import os
import re
import secrets
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import files, nodes, roots
from .closing import settled_close
from .errors import BridgeError, exact
from .inspection import check_shown_frame, layer_entries
from .jobs import Call, Handler
from .port import DocumentsPort
from .registry import READ_ONLY, WORKING_COPY, Registry

OPEN_FIELDS = {
    "source_path",
    "source_sha256",
    "mode",
    "working_dir",
    "editable_layer_ids",
    "editable_layer_names",
}
FORMATS = (".kra", ".ora", ".png")
# Phase 1 reads every document as 8-bit RGBA bytes; any RGB profile may come with them.
OPEN_SPACE = ("RGBA", "U8")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
LAYER_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def new_baseline_id() -> str:
    return f"baseline-{secrets.token_hex(6)}"


def utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


class _Made:
    # What a failing open has made so far, undone in the same job.
    def __init__(self, copy: str | None) -> None:
        self.copy = copy
        self.document: Any = None

    def undo(
        self, registry: Registry, port: DocumentsPort, mode: str, call: Call, raised: BaseException
    ) -> None:
        kept = None
        if self.document is not None:
            kept = registry.discard(self.document, settled_close(port), mode, call.client)
        if kept is not None and isinstance(raised, BridgeError):
            raised.body["details"]["document_id"] = kept
        if self.copy is not None and kept is None:
            try:
                os.unlink(self.copy)
            except FileNotFoundError:
                pass


def handlers(
    registry: Registry,
    port: DocumentsPort,
    data: Path,
    now: Callable[[], datetime.datetime] = utc_now,
    new_id: Callable[[], str] = new_baseline_id,
) -> dict[str, Handler]:
    def open_document(args: dict[str, Any], call: Call) -> dict[str, Any]:
        exact(args, OPEN_FIELDS)
        given = _check_args(args)
        registry.refuse_at_job_start()
        source = roots.check(data, args["source_path"], "source_path")
        if _format(source) != given:
            raise BridgeError("INVALID_ARGUMENT", "source_path resolves to another format.")
        working = None
        if args["mode"] == WORKING_COPY:
            working = roots.check(data, args["working_dir"], "working_dir")
            if working == os.path.dirname(source):
                message = "working_dir must not be the source's own folder."
                raise BridgeError("INVALID_ARGUMENT", message, False, {"field": "working_dir"})
        # Taken before the hash, so a change while it runs shows as a moved stat.
        stat = files.source_stat(source)
        # Nothing has changed up to here, so only these refusals may be retryable.
        if working is None:
            files.check_source(source, args["source_sha256"])
            path = source
        else:
            path = files.working_copy(source, working, args["source_sha256"], now())
        made = _Made(None if working is None else path)
        try:
            return _open(made, path, source, stat, args, call)
        except BaseException as raised:
            made.undo(registry, port, args["mode"], call, raised)
            raise

    def _open(
        made: _Made,
        path: str,
        source: str,
        stat: files.Stat | None,
        args: dict[str, Any],
        call: Call,
    ) -> dict[str, Any]:
        document = made.document = port.open(path)
        port.show(document)
        info = port.describe(document)
        if (info["color_model"], info["depth"]) != OPEN_SPACE:
            details = {key: info[key] for key in ("color_model", "depth", "profile_id")}
            message = "Phase 1 opens RGBA / U8 documents only."
            raise BridgeError("COLOR_PROFILE_MISMATCH", message, False, details)
        # Every read is of frame 0, the baseline read later from this file included.
        check_shown_frame(info)
        nodes.unmask(port, document)
        tree = port.tree(document)
        editable = _editable(
            tree["nodes"], args["editable_layer_ids"], args["editable_layer_names"]
        )
        # Every layer that exists now is protected, except those the agent resumes (PDD Part 4).
        protected = {node["id"] for node in tree["nodes"]} - editable
        layers = layer_entries(tree, protected)
        width, height = info["size_px"]
        # Its pixels are the file's, read by the first preview that needs them.
        baseline_id = new_id()
        # Registered last, so nothing can fail once the registry holds the document.
        handle = registry.add(document, args["mode"], call.client)
        handle.path = path
        handle.source_path = source
        handle.source_sha256 = args["source_sha256"]
        handle.source_stat = stat
        handle.baseline_id = baseline_id
        handle.protected = protected
        return {
            "document_id": handle.document_id,
            "mode": handle.mode,
            "working_copy": handle.mode == WORKING_COPY,
            "path": path,
            "source_path": source,
            "source_sha256": handle.source_sha256,
            "baseline_id": baseline_id,
            "canvas_px": [width, height],
            "color_model": info["color_model"],
            "depth": info["depth"],
            "profile_id": info["profile_id"],
            "root_layer_id": tree["root_id"],
            "active_layer_id": tree["active_id"],
            "layers": layers,
        }

    return {"document.open": open_document}


def _check_args(args: dict[str, Any]) -> str:
    # The server checks these too; the plugin trusts no caller.
    mode, sha = args["mode"], args["source_sha256"]
    if mode not in (WORKING_COPY, READ_ONLY):
        raise BridgeError("INVALID_ARGUMENT", "mode is working_copy or read_only.")
    if not isinstance(sha, str) or not SHA256.match(sha):
        raise BridgeError("INVALID_ARGUMENT", "source_sha256 is 64 lowercase hex digits.")
    roots.resolve(args["source_path"], "source_path")
    given = _format(args["source_path"])
    ids, names = args["editable_layer_ids"], args["editable_layer_names"]
    if mode == READ_ONLY and (
        args["working_dir"] is not None or ids is not None or names is not None
    ):
        message = "A read_only open takes no working_dir and no editable layers."
        raise BridgeError("INVALID_ARGUMENT", message)
    if mode == WORKING_COPY and args["working_dir"] is None:
        raise BridgeError("INVALID_ARGUMENT", "A working_copy open needs a working_dir.")
    _names(ids, "editable_layer_ids", LAYER_ID)
    _names(names, "editable_layer_names", None)
    if ids is not None and given != ".kra":
        message = (
            "editable_layer_ids is for KRA, whose layer ids persist; use editable_layer_names."
        )
        raise BridgeError("INVALID_ARGUMENT", message)
    if names is not None and given == ".kra":
        message = "editable_layer_names is for ORA and PNG; a KRA keeps its layer ids."
        raise BridgeError("INVALID_ARGUMENT", message)
    return given


def _format(path: str) -> str:
    extension = os.path.splitext(path)[1].lower()
    if extension not in FORMATS:
        details = {"formats": list(FORMATS)}
        message = "Phase 1 opens .kra, .ora and .png files."
        raise BridgeError("UNSUPPORTED_CAPABILITY", message, False, details)
    return extension


def _names(values: Any, field: str, pattern: re.Pattern[str] | None) -> None:
    if values is None:
        return
    if (
        not isinstance(values, list)
        or not all(isinstance(value, str) and value for value in values)
        or len(set(values)) != len(values)
        or (pattern is not None and not all(pattern.match(value) for value in values))
    ):
        raise BridgeError("INVALID_ARGUMENT", f"{field} is a list of distinct layer references.")


def _editable(nodes: list[dict[str, Any]], ids: Any, names: Any) -> set[str]:
    if ids is not None:
        missing = [layer for layer in ids if layer not in {node["id"] for node in nodes}]
        if missing:
            details = {"missing": missing}
            raise BridgeError("LAYER_NOT_FOUND", "No layer has that id.", False, details)
        return set(ids)
    if names is not None:
        counts = Counter(node["name"] for node in nodes)
        missing = [name for name in names if counts[name] == 0]
        if missing:
            details = {"missing": missing}
            raise BridgeError("LAYER_NOT_FOUND", "No layer has that name.", False, details)
        # A name is a label; one shared by several layers cannot say which to unprotect.
        ambiguous = [name for name in names if counts[name] > 1]
        if ambiguous:
            details = {"ambiguous": ambiguous}
            message = "More than one layer has that name."
            raise BridgeError("INVALID_ARGUMENT", message, False, details)
        return {node["id"] for node in nodes if node["name"] in names}
    return set()
