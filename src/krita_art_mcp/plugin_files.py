import hashlib
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
    # The one check of the plugin's source: nothing is compared, hashed or copied before it.
    # A missing folder hashes as the empty digest, so its absence must never reach a compare.
    package = source / PLUGIN_NAME
    try:
        (package / "__init__.py").read_bytes()
        desktop = (source / desktop_name()).read_bytes()
        return Payload(source_hash(package), desktop)
    except (FileNotFoundError, NotADirectoryError):
        if not source.is_dir():
            absent = f"{tilde(source)} does not exist"
        else:
            parts = (f"{PLUGIN_NAME}/__init__.py", desktop_name())
            missing = [part for part in parts if not (source / part).is_file()]
            absent = f"{tilde(source)} has no {' or '.join(missing)}"
        return SourceProblem(f"no plugin source beside this copy of the server ({absent})")
    except OSError as error:
        return SourceProblem(f"cannot read the plugin source in {tilde(source)}: {error.strerror}")


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
    shutil.copytree(
        source / PLUGIN_NAME, staging, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
    )
    shutil.copyfile(source / desktop_name(), staged_desktop)
    if target.exists():
        target.rename(retired)
    staging.rename(target)
    shutil.rmtree(retired, ignore_errors=True)
    staged_desktop.replace(desktop)
    return target
