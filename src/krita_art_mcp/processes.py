import os
import subprocess


def _ps(*args: str) -> str | None:
    try:
        found = subprocess.run(
            ["/bin/ps", *args], capture_output=True, text=True, timeout=5, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return found.stdout if found.returncode == 0 else ""


def _is_krita(command: str) -> bool:
    return os.path.basename(command.strip()).lower() == "krita"


def is_live_krita(pid: int) -> bool:
    # bridge.json may name a pid reused after a crash, so the process must also be Krita.
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    command = _ps("-p", str(pid), "-o", "comm=")
    return command is None or _is_krita(command)


def krita_running() -> bool:
    commands = _ps("-axo", "comm=")
    return commands is not None and any(_is_krita(line) for line in commands.splitlines())


def start_time(pid: int) -> str:
    # With the pid, this tells a restarted server from its predecessor (the writer lease).
    started = _ps("-p", str(pid), "-o", "lstart=")
    return (started or "").strip()
