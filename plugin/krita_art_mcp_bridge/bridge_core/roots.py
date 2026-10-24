import json
import os
from pathlib import Path
from typing import Any

from . import paths
from .errors import BridgeError

# config.json's format; the server holds an equal copy and writes the file.
CONFIG_VERSION = 1
TOO_FAR = (
    "config.json allows a root that reaches too far: /, the home folder, or krita-art-mcp's data "
    "folder. Run `uv run krita-art-mcp roots list`, then `roots remove` that root."
)


def load(config: Path) -> list[str]:
    try:
        text = config.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except OSError as problem:
        raise _config_error(f"{config.name} cannot be read: {problem}") from problem
    try:
        content = json.loads(text)
    except ValueError as problem:
        raise _config_error(f"{config.name} is not valid JSON; fix or delete it.") from problem
    version = content.get("v") if isinstance(content, dict) else None
    if not isinstance(version, int) or isinstance(version, bool):
        raise _config_error(f"{config.name} has no version; fix or delete it.")
    if version > CONFIG_VERSION:
        raise _config_error(
            f"{config.name} is version {version}, written by a newer krita-art-mcp; "
            f"this plugin reads up to version {CONFIG_VERSION}. Update the plugin."
        )
    roots = content.get("roots")
    if not isinstance(roots, list) or not all(
        isinstance(root, str) and os.path.isabs(root) for root in roots
    ):
        raise _config_error(f"{config.name} lists its roots wrongly; fix or delete it.")
    return list(roots)


def allowed(data: Path) -> list[str]:
    # The harness folder is always allowed, so the probe needs no root of the owner's.
    listed = [os.path.realpath(root) for root in load(paths.config_file(data))]
    home, folder = os.path.realpath(Path.home()), os.path.realpath(data)
    if any(reaches_too_far(root, home, folder) for root in listed):
        raise _config_error(TOO_FAR)
    return [*listed, os.path.realpath(paths.harness_dir(data))]


def reaches_too_far(real: str, home: str, data: str) -> bool:
    # As the server's `roots add` refuses: /, the home folder, or the data folder, inside or out.
    return real in ("/", home) or inside(real, [data]) or inside(data, [real])


def resolve(path: Any, field: str) -> str:
    if not isinstance(path, str) or not os.path.isabs(path) or "\0" in path:
        details = {"field": field}
        raise BridgeError("INVALID_ARGUMENT", f"{field} must be an absolute path.", False, details)
    return os.path.realpath(path)


def inside(real: str, roots: list[str]) -> bool:
    return any(real == root or real.startswith(root.rstrip("/") + "/") for root in roots)


def check(data: Path, path: Any, field: str) -> str:
    # Invariant 3: every path an agent names resolves inside an allowed root.
    real = resolve(path, field)
    if not inside(real, allowed(data)):
        details = {"field": field}
        message = f"{field} is outside every allowed root."
        raise BridgeError("PATH_NOT_ALLOWED", message, False, details)
    return real


def _config_error(message: str) -> BridgeError:
    return BridgeError("INTERNAL_ERROR", message)
