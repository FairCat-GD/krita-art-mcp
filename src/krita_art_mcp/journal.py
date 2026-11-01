import datetime
import fcntl
import json
import logging
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from krita_art_mcp.paths import private_dir

# Each call's arguments live in a file of their own, so reading the journal never decodes them.
VERSION = 2
ARGS_DIR = "args"
# Within one Krita session the bridge dedups however old the id; across a Krita restart only
# the journal can, and it reads this far back.
WINDOW_DAYS = 7

# What became of one attempt. The bridge dedups within a Krita session, so a receipt is the
# outcome of every attempt it shares. A no-effect refusal releases the request_id, so an attempt
# sent after it may have run: it settles only its own attempt and the one whose operation the
# bridge named. A conflict, or a call that never reached the bridge, settles its own alone.
RECEIPT = "receipt"
NO_EFFECT = "no_effect"
NOT_SENT = "not_sent"
CONFLICT = "conflict"
UNKNOWN = "unknown"
OUTCOMES = (RECEIPT, NO_EFFECT, NOT_SENT, CONFLICT, UNKNOWN)

log = logging.getLogger(__name__)


class JournalError(Exception):
    pass


def utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


@dataclass
class Attempt:
    operation_id: str
    session_id: str
    tool: str
    args_sha256: str
    outcome: str = UNKNOWN


@dataclass
class Prior:
    # What the journal knows of one request_id: every attempt, and the receipt if one came.
    attempts: list[Attempt] = field(default_factory=list)
    receipt: dict[str, Any] | None = None

    def binding(self) -> tuple[str, str] | None:
        # A request_id belongs to the arguments of its first attempt the bridge did not refuse.
        for attempt in self.attempts:
            if attempt.outcome != CONFLICT:
                return attempt.tool, attempt.args_sha256
        return None

    def unsettled(self) -> bool:
        return any(attempt.outcome == UNKNOWN for attempt in self.attempts)

    def unknown_in(self, session_id: str) -> bool:
        return any(a.outcome == UNKNOWN and a.session_id == session_id for a in self.attempts)

    def unknown_elsewhere(self, session_id: str) -> Attempt | None:
        # Sent to a Krita session that has ended without saying whether it ran.
        return next(
            (a for a in self.attempts if a.outcome == UNKNOWN and a.session_id != session_id), None
        )


class Journal:
    def __init__(self, directory: Path, now: Callable[[], datetime.datetime] = utc_now) -> None:
        self._directory = directory
        self._now = now
        self._offsets: dict[Path, int] = {}
        self._requests: dict[str, Prior] = {}
        self._sessions: dict[str, str] = {}
        # The argument folders this process has made private, so each is made so once.
        self._private: set[Path] = set()

    def lookup(self, request_id: str) -> Prior | None:
        self._refresh()
        return self._requests.get(request_id)

    def session_of(self, operation_id: str) -> str | None:
        self._refresh()
        return self._sessions.get(operation_id)

    def dispatched(
        self,
        *,
        client: str | None,
        request_id: str,
        operation_id: str,
        tool: str,
        args_sha256: str,
        session_id: str,
        args: dict[str, Any],
        document_path: str | None = None,
        layer_names: Sequence[str] = (),
    ) -> None:
        # The arguments are on disk before the line that names them.
        args_file = self._write_args(operation_id, args)
        self._append(
            {
                "client": client,
                "request_id": request_id,
                "operation_id": operation_id,
                "tool": tool,
                "args_sha256": args_sha256,
                "session_id": session_id,
                "phase": "dispatched",
                "args_file": args_file,
                "document_path": document_path,
                "layer_names": list(layer_names),
            }
        )

    def _write_args(self, operation_id: str, args: dict[str, Any]) -> str:
        relative = f"{ARGS_DIR}/{self._now().date().isoformat()}/{operation_id}.json"
        target = self._directory / relative
        if target.parent not in self._private:
            # Each folder made private, since mkdir's mode reaches only the last.
            private_dir(self._directory)
            private_dir(self._directory / ARGS_DIR)
            private_dir(target.parent)
            self._private.add(target.parent)
        partial = target.with_name(target.name + ".partial")
        data = json.dumps(args, ensure_ascii=False, separators=(",", ":")).encode()
        fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            view = memoryview(data)
            while view:
                view = view[os.write(fd, view) :]
        finally:
            os.close(fd)
        os.replace(partial, target)
        return relative

    def finished(
        self,
        *,
        client: str | None,
        request_id: str,
        operation_id: str | None,
        tool: str,
        args_sha256: str,
        session_id: str,
        outcome: str,
        result: dict[str, Any],
        bridge_operation_id: str | None = None,
        document_path: str | None = None,
        layer_names: Sequence[str] = (),
    ) -> None:
        self._append(
            {
                "client": client,
                "request_id": request_id,
                "operation_id": operation_id,
                "bridge_operation_id": bridge_operation_id,
                "tool": tool,
                "args_sha256": args_sha256,
                "session_id": session_id,
                "phase": "finished",
                "outcome": outcome,
                "result": result,
                "document_path": document_path,
                "layer_names": list(layer_names),
            }
        )

    def _append(self, entry: dict[str, Any]) -> None:
        now = self._now()
        line = {"v": VERSION, "ts": now.isoformat(timespec="milliseconds"), **entry}
        data = (json.dumps(line, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
        private_dir(self._directory)
        path = self._directory / f"{now.date().isoformat()}.jsonl"
        fd = os.open(path, os.O_RDWR | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            # Server processes for several clients append to the same day's file.
            fcntl.flock(fd, fcntl.LOCK_EX)
            size = os.fstat(fd).st_size
            # A writer that died mid-line must not swallow this line into its own.
            if size and os.pread(fd, 1, size - 1) != b"\n":
                data = b"\n" + data
            view = memoryview(data)
            while view:
                view = view[os.write(fd, view) :]
        finally:
            os.close(fd)

    def _refresh(self) -> None:
        today = self._now().date()
        for back in range(WINDOW_DAYS - 1, -1, -1):
            day = today - datetime.timedelta(days=back)
            self._read(self._directory / f"{day.isoformat()}.jsonl")

    def _read(self, path: Path) -> None:
        start = self._offsets.get(path, 0)
        try:
            with path.open("rb") as stream:
                stream.seek(start)
                chunk = stream.read()
        except FileNotFoundError:
            return
        # Only whole lines: another process may be mid-write. The offset moves line by line,
        # so a line that stops the read is never applied twice.
        for raw in chunk.splitlines(keepends=True):
            if not raw.endswith(b"\n"):
                break
            self._apply(path, raw)
            start += len(raw)
            self._offsets[path] = start

    def _apply(self, path: Path, raw: bytes) -> None:
        try:
            line = json.loads(raw)
            version = line["v"]
        except (ValueError, KeyError, TypeError):
            # Only a writer that died before sending leaves a broken line, so it sent nothing.
            log.warning("skipped a broken line in %s", path.name)
            return
        # A line skipped here could let a retry repeat the work it records.
        if not isinstance(version, int) or version != VERSION:
            raise JournalError(
                f"{path.name} holds a journal line of version {version}; this server reads only "
                f"version {VERSION}. Update krita-art-mcp, or move that file aside."
            )
        try:
            self._index(line)
        except (KeyError, TypeError, AttributeError):
            # Not a line this server wrote; it records nothing it sent.
            log.warning("skipped a malformed line in %s", path.name)

    def _index(self, line: dict[str, Any]) -> None:
        # Every field is read before anything changes, so a malformed line changes nothing.
        request_id, phase = line["request_id"], line["phase"]
        operation_id, session_id = line["operation_id"], line["session_id"]
        tool, digest = line["tool"], line["args_sha256"]
        if phase == "dispatched":
            prior = self._requests.setdefault(request_id, Prior())
            self._sessions[operation_id] = session_id
            prior.attempts.append(Attempt(operation_id, session_id, tool, digest))
            return
        outcome, result = line["outcome"], line.get("result")
        if phase != "finished" or outcome not in OUTCOMES:
            raise KeyError(phase)
        named = {operation_id, line.get("bridge_operation_id")} if outcome == NO_EFFECT else set()
        prior = self._requests.setdefault(request_id, Prior())
        for attempt in prior.attempts:
            if outcome == NO_EFFECT:
                same = attempt.operation_id in named
            elif outcome in (CONFLICT, NOT_SENT):
                same = attempt.operation_id == operation_id
            else:
                same = (attempt.session_id, attempt.args_sha256) == (session_id, digest)
            if same and attempt.outcome == UNKNOWN and outcome != UNKNOWN:
                attempt.outcome = outcome
        if outcome == RECEIPT:
            prior.receipt = result
