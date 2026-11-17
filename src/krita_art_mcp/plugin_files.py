import hashlib
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from krita_art_mcp.paths import PLUGIN_NAME, tilde


@dataclass(frozen=True)
class Payload:
    hash: str
    desktop: bytes


@dataclass(frozen=True)
class SourceProblem:
    detail: str


def source_hash(package_dir: Path) -> str:
    # An equal copy of `bridge_core.source_hash`: the server never imports the plugin.
    digest = hashlib.sha256()
    sources = {
        path.relative_to(package_dir).as_posix(): path
        for path in package_dir.rglob("*.py")
        if "__pycache__" not in path.relative_to(package_dir).parts
    }
    for relative in sorted(sources):
        name = relative.encode("utf-8")
        content = sources[relative].read_bytes()
        digest.update(len(name).to_bytes(8, "big") + name)
        digest.update(len(content).to_bytes(8, "big") + content)
    return digest.hexdigest()


def desktop_name() -> str:
    return f"{PLUGIN_NAME}.desktop"


def payload(source: Path) -> Payload | SourceProblem:
    # The one check of the plugin's source: nothing is compared, hashed or copied before it,
    # because a missing folder hashes as the empty digest.
    package = source / PLUGIN_NAME
    try:
        (package / "__init__.py").read_bytes()
        desktop = (source / desktop_name()).read_bytes()
        _readable_folders(package)
        return Payload(source_hash(package), desktop)
    except (FileNotFoundError, NotADirectoryError) as error:
        return SourceProblem(_absent(source, error))
    except OSError as error:
        return SourceProblem(f"cannot read the plugin source in {tilde(source)}: {error.strerror}")


def _readable_folders(package: Path) -> None:
    # The hash's rglob skips a folder it cannot list, so such a source would pass as a different
    # one and fail the copy.
    def fail(error: OSError) -> None:
        raise error

    for _, folders, _ in os.walk(package, onerror=fail):
        folders[:] = [folder for folder in folders if folder != "__pycache__"]


def _absent(source: Path, error: OSError) -> str:
    beside = "no plugin source beside this copy of the server"
    if not source.exists():
        return f"{beside} ({tilde(source)} does not exist)"
    if not source.is_dir():
        return f"{beside} ({tilde(source)} is not a folder)"
    parts = (f"{PLUGIN_NAME}/__init__.py", desktop_name())
    missing = [part for part in parts if not (source / part).is_file()]
    if missing:
        return f"{beside} ({tilde(source)} has no {' or '.join(missing)})"
    return f"the plugin source in {tilde(source)} is incomplete: {error.filename} is missing"


def installed(krita_data_dir: Path) -> Path:
    return krita_data_dir / "pykrita" / PLUGIN_NAME


def install(source: Path, krita_data_dir: Path) -> Path:
    pykrita = krita_data_dir / "pykrita"
    pykrita.mkdir(exist_ok=True)
    target = pykrita / PLUGIN_NAME
    staging = pykrita / f".{PLUGIN_NAME}.installing"
    retired = pykrita / f".{PLUGIN_NAME}.retired"
    desktop = pykrita / desktop_name()
    staged_desktop = pykrita / f".{desktop_name()}.installing"
    for leftover in (staging, retired):
        shutil.rmtree(leftover, ignore_errors=True)
    # Both new files are complete before either takes its name, so a failed copy leaves the old
    # plugin whole, and other plugins stay put.
    try:
        shutil.copytree(
            source / PLUGIN_NAME, staging, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
        )
        shutil.copyfile(source / desktop_name(), staged_desktop)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        staged_desktop.unlink(missing_ok=True)
        raise
    if target.exists():
        target.rename(retired)
    staging.rename(target)
    shutil.rmtree(retired, ignore_errors=True)
    staged_desktop.replace(desktop)
    return target
