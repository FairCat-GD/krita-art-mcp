import datetime
import fcntl
import json
import logging
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

VERSION = 1
# Within one Krita session the bridge dedups however old the id; across a Krita restart only
# the journal can, and it reads this far back (invariant 9, amended 2026-10-24).
WINDOW_DAYS = 7

# What became of one attempt. The bridge dedups within a Krita session, so a receipt or a
# no-effect refusal is the outcome of every attempt it shares; a conflict, or a call that never
# reached the bridge, is its own attempt's alone.
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
        self._append(
            {
                "client": client,
                "request_id": request_id,
                "operation_id": operation_id,
                "tool": tool,
                "args_sha256": args_sha256,
                "session_id": session_id,
                "phase": "dispatched",
                "args": args,
                "document_path": document_path,
                "layer_names": list(layer_names),
            }
        )

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
        document_path: str | None = None,
        layer_names: Sequence[str] = (),
    ) -> None:
        self._append(
            {
                "client": client,
                "request_id": request_id,
                "operation_id": operation_id,
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
        self._directory.mkdir(mode=0o700, parents=True, exist_ok=True)
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
        # Only whole lines: another process may be mid-write.
        end = chunk.rfind(b"\n") + 1
        for raw in chunk[:end].splitlines():
            self._apply(path, raw)
        self._offsets[path] = start + end

    def _apply(self, path: Path, raw: bytes) -> None:
        try:
            line = json.loads(raw)
            version = line["v"]
        except (ValueError, KeyError, TypeError):
            # Only a writer that died before sending leaves a broken line, so it sent nothing.
            log.warning("skipped a broken line in %s", path.name)
            return
        if not isinstance(version, int) or version > VERSION:
            raise JournalError(
                f"{path.name} holds a journal line of version {version}, written by a newer "
                f"krita-art-mcp; this server reads up to version {VERSION}. Update it."
            )
        prior = self._requests.setdefault(line["request_id"], Prior())
        if line["phase"] == "dispatched":
            self._sessions[line["operation_id"]] = line["session_id"]
            prior.attempts.append(
                Attempt(line["operation_id"], line["session_id"], line["tool"], line["args_sha256"])
            )
            return
        outcome = line["outcome"]
        for attempt in prior.attempts:
            if outcome in (CONFLICT, NOT_SENT):
                same = attempt.operation_id == line["operation_id"]
            else:
                same = (attempt.session_id, attempt.args_sha256) == (
                    line["session_id"],
                    line["args_sha256"],
                )
            if same and attempt.outcome == UNKNOWN and outcome != UNKNOWN:
                attempt.outcome = outcome
        if outcome == RECEIPT:
            prior.receipt = line["result"]
