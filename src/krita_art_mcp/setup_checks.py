from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from krita_art_mcp import paths, plugin_files, processes
from krita_art_mcp.errors import PROTOCOL

INSTALL = "Run `uv run krita-art-mcp install-plugin`, then restart Krita."
ENABLE = (
    "Enable Krita Art MCP Bridge in Configure Krita > Python Plugin Manager "
    "(in the application menu), then restart Krita."
)
START = "Start Krita."


@dataclass(frozen=True)
class Step:
    name: str
    passed: bool
    detail: str
    fix: str = ""


@dataclass(frozen=True)
class Setup:
    plugin_source: Path = field(default_factory=paths.plugin_source)
    krita_data_dir: Path = field(default_factory=paths.krita_data_dir)
    kritarc: Path = field(default_factory=paths.kritarc)
    krita_running: Callable[[], bool] = processes.krita_running


def plugin_installed(setup: Setup) -> Step:
    name = "the plugin files are installed and current"
    target = plugin_files.installed(setup.krita_data_dir)
    desktop = target.parent / plugin_files.desktop_name()
    if not target.is_dir() or not desktop.is_file():
        return Step(name, False, f"nothing is installed in {_home(target.parent)}", INSTALL)
    source_desktop = setup.plugin_source / plugin_files.desktop_name()
    if desktop.read_bytes() != source_desktop.read_bytes():
        return Step(name, False, "the installed .desktop file differs from the repo's", INSTALL)
    installed_hash = plugin_files.source_hash(target)
    repo_hash = plugin_files.source_hash(setup.plugin_source / paths.PLUGIN_NAME)
    if installed_hash != repo_hash:
        detail = f"installed {installed_hash[:12]}, repo {repo_hash[:12]}"
        return Step(name, False, detail, INSTALL)
    return Step(name, True, f"hash {repo_hash[:12]}")


def plugin_enabled(setup: Setup) -> Step:
    name = "kritarc enables the plugin"
    if _kritarc_enables(setup.kritarc):
        return Step(name, True, f"[python] enable_{paths.PLUGIN_NAME}=true")
    return Step(name, False, f"{_home(setup.kritarc)} does not enable it", ENABLE)


def krita_running(setup: Setup) -> Step:
    name = "Krita is running"
    if setup.krita_running():
        return Step(name, True, "found a krita process")
    return Step(name, False, "no krita process", START)


LOCAL_STEPS: list[Callable[[Setup], Step]] = [plugin_installed, plugin_enabled, krita_running]


def first_local_failure(setup: Setup) -> Step | None:
    for check in LOCAL_STEPS:
        step = check(setup)
        if not step.passed:
            return step
    return None


def plugin_current(health: dict[str, Any], plugin_source: Path) -> Step:
    # Invariant 11: the plugin Krita runs is the repository's, at this protocol.
    repo_hash = plugin_files.source_hash(plugin_source / paths.PLUGIN_NAME)
    running_hash = str(health.get("plugin_hash"))
    protocol = health.get("protocol")
    current = protocol == PROTOCOL and running_hash == repo_hash
    detail = f"protocol {protocol}, running {running_hash[:12]}, repo {repo_hash[:12]}"
    return Step("the protocol and plugin hash match", current, detail, INSTALL)


def bridge_missing() -> Step:
    fix = f"Restart Krita; if the bridge still does not start, read {_home(paths.plugin_log())}."
    return Step("the bridge is reachable", False, "Krita runs, but its bridge does not", fix)


def _kritarc_enables(kritarc: Path) -> bool:
    # kritarc is KDE's INI dialect, which configparser rejects in places; read it by hand.
    try:
        lines = kritarc.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return False
    section = ""
    for line in lines:
        text = line.strip()
        if text.startswith("[") and text.endswith("]"):
            section = text[1:-1]
        elif section == "python" and "=" in text:
            key, _, value = text.partition("=")
            if key.strip() == f"enable_{paths.PLUGIN_NAME}":
                return value.strip().lower() == "true"
    return False


def _home(path: Path) -> str:
    home = str(Path.home())
    text = str(path)
    return "~" + text[len(home) :] if text.startswith(home + "/") else text
