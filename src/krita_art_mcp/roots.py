import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from krita_art_mcp.paths import private_dir

# config.json's format; the plugin holds an equal copy (`bridge_core.roots.CONFIG_VERSION`).
VERSION = 1
ADD = "Run `uv run krita-art-mcp roots add <folder>` for each folder agents may use."
# The plugin holds an equal rule (`bridge_core.roots.reaches_too_far`).
TOO_FAR = (
    "{name} allows a root that reaches too far: /, the home folder, or krita-art-mcp's data "
    "folder. Run `uv run krita-art-mcp roots list`, then `roots remove` that root."
)


class ConfigError(Exception):
    pass


def load(config: Path) -> list[str]:
    try:
        text = config.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except OSError as problem:
        raise ConfigError(f"{config.name} cannot be read: {problem}") from problem
    try:
        content = json.loads(text)
    except ValueError as problem:
        raise ConfigError(f"{config.name} is not valid JSON; fix or delete it.") from problem
    version = content.get("v") if isinstance(content, dict) else None
    if not isinstance(version, int) or isinstance(version, bool):
        raise ConfigError(f"{config.name} has no version; fix or delete it.")
    if version > VERSION:
        raise ConfigError(
            f"{config.name} is version {version}, written by a newer krita-art-mcp; this one "
            f"reads up to version {VERSION}. Update it."
        )
    roots = content.get("roots")
    if not isinstance(roots, list) or not all(
        isinstance(root, str) and os.path.isabs(root) for root in roots
    ):
        raise ConfigError(f"{config.name} lists its roots wrongly; fix or delete it.")
    return list(roots)


def save(config: Path, roots: list[str]) -> None:
    private_dir(config.parent)
    temp = config.with_name(f".{config.name}.{os.getpid()}.tmp")
    temp.unlink(missing_ok=True)
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"v": VERSION, "roots": roots}, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, config)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise


def allowed(config: Path, harness: Path) -> list[str]:
    # The harness folder is always allowed, so the probe needs no root of the owner's.
    listed = load(config)
    if too_far(listed, config):
        raise ConfigError(TOO_FAR.format(name=config.name))
    return [os.path.realpath(root) for root in [*listed, str(harness)]]


def too_far(roots: list[str], config: Path) -> int:
    # Roots written by hand, or before `add` refused them, against the folder config.json is in.
    home, data = os.path.realpath(Path.home()), [os.path.realpath(config.parent)]
    return sum(refusal(os.path.realpath(root), home, data) is not None for root in roots)


def resolve(path: str) -> str | None:
    # None for a path no realpath can be trusted for: relative, or holding a NUL byte.
    if not os.path.isabs(path) or "\0" in path:
        return None
    return os.path.realpath(path)


def inside(real: str, roots: list[str]) -> bool:
    return any(real == root or real.startswith(root.rstrip("/") + "/") for root in roots)


def refusal(real: str, home: str, data_dirs: Sequence[str]) -> str | None:
    # Each folder is a realpath, as every path an agent names is (invariant 3).
    if real == "/":
        return "/ would let agents reach every file on this Mac."
    if real == home:
        return f"{real} is your home folder, which would let agents reach all your files."
    for data in data_dirs:
        if inside(real, [data]):
            return f"{real} is krita-art-mcp's data folder or inside it, where its own files live."
        if inside(data, [real]):
            return f"{real} holds krita-art-mcp's data folder ({data}), where its own files live."
    return None


def run(
    action: str,
    directory: str | None,
    config: Path,
    out: TextIO = sys.stdout,
    home: Path | None = None,
    data_dirs: Sequence[Path] = (),
) -> int:
    try:
        roots = load(config)
        if action == "list":
            for root in roots:
                print(root, file=out)
            if not roots:
                print(f"No roots yet, so agents can open nothing. {ADD}", file=out)
            return 0
        assert directory is not None
        real = os.path.realpath(directory)
        if action == "add":
            if not os.path.isdir(real):
                print(f"{directory} is not a folder.", file=out)
                return 1
            # The folder config.json lives in is a data folder, wherever it is.
            data = [os.path.realpath(folder) for folder in (config.parent, *data_dirs)]
            refused = refusal(real, os.path.realpath(home or Path.home()), data)
            if refused is not None:
                print(f"Refused: {refused} Allow the folder that holds the art.", file=out)
                return 1
            if real in roots:
                print(f"{real} is already allowed.", file=out)
                return 0
            save(config, [*roots, real])
            print(f"Agents may now use {real}.", file=out)
            return 0
        kept = [root for root in roots if root not in (real, directory)]
        if kept == roots:
            print(f"{directory} is not a root.", file=out)
            return 1
        save(config, kept)
        print(f"Agents may no longer use {directory}.", file=out)
        return 0
    except (ConfigError, OSError) as problem:
        print(f"roots: {problem}", file=out)
        return 1
