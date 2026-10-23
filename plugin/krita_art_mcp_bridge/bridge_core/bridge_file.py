import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any


def write(path: Path, content: dict[str, Any]) -> None:
    # Readers never see a partial file, and the token is never readable by another user.
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.unlink(missing_ok=True)
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(content, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise


def read(path: Path) -> dict[str, Any] | None:
    try:
        content = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return content if isinstance(content, dict) else None


def other_instance(path: Path, own_pid: int, is_live: Callable[[int], bool]) -> int | None:
    current = read(path)
    pid = None if current is None else current.get("pid")
    if not isinstance(pid, int) or isinstance(pid, bool) or pid == own_pid:
        return None
    return pid if is_live(pid) else None


def remove_if_ours(path: Path, session_id: str) -> None:
    current = read(path)
    if current is not None and current.get("session_id") == session_id:
        path.unlink(missing_ok=True)
