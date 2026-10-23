import os
import subprocess
from typing import Any

# Both sides format start times alike, whatever locale and zone Krita or a shell started with.
PS_ENV = {"LC_ALL": "C", "TZ": "UTC"}


def ps(*args: str) -> str | None:
    # None when ps could not answer; "" when it found no such process.
    try:
        found = subprocess.run(
            ["/bin/ps", *args],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            env=PS_ENV,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return found.stdout.strip() if found.returncode == 0 else ""


def pid_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    return True


def is_live_krita(pid: int) -> bool:
    # A pid reused after a crash belongs to some other program, so the name must be Krita's.
    if not pid_exists(pid):
        return False
    command = ps("-p", str(pid), "-o", "comm=")
    # Unsure means live: refusing to start beats taking over another Krita's bridge.
    return command is None or os.path.basename(command).lower() == "krita"


def holder_alive(client: dict[str, Any]) -> bool:
    # The lease passes on only on proof: the pid is gone, or it now belongs to a later process.
    if not pid_exists(client["pid"]):
        return False
    started = ps("-p", str(client["pid"]), "-o", "lstart=")
    return not started or started == client["started_at"]
