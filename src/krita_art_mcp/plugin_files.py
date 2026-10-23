import hashlib
import shutil
from pathlib import Path

from krita_art_mcp.paths import PLUGIN_NAME


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


def installed(krita_data_dir: Path) -> Path:
    return krita_data_dir / "pykrita" / PLUGIN_NAME


def install(source: Path, krita_data_dir: Path) -> Path:
    pykrita = krita_data_dir / "pykrita"
    pykrita.mkdir(exist_ok=True)
    target = pykrita / PLUGIN_NAME
    staging = pykrita / f".{PLUGIN_NAME}.installing"
    retired = pykrita / f".{PLUGIN_NAME}.retired"
    for leftover in (staging, retired):
        shutil.rmtree(leftover, ignore_errors=True)
    # The new copy is complete before it takes the plugin's name, and other plugins stay put.
    shutil.copytree(
        source / PLUGIN_NAME, staging, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
    )
    if target.exists():
        target.rename(retired)
    staging.rename(target)
    shutil.rmtree(retired, ignore_errors=True)
    desktop = pykrita / desktop_name()
    staged_desktop = pykrita / f".{desktop_name()}.installing"
    shutil.copyfile(source / desktop_name(), staged_desktop)
    staged_desktop.replace(desktop)
    return target
