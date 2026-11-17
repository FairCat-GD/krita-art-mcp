import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from krita_art_mcp import paths, plugin_files, processes, roots
from krita_art_mcp.errors import PROTOCOL

INSTALL = "Run `uv run krita-art-mcp install-plugin`, then restart Krita."
# Never install-plugin: with no source beside this copy, it has nothing to install.
CHECKOUT = (
    "Run krita-art-mcp from a readable checkout of the repository, cloned at a release tag; "
    "a wheel or an sdist alone holds no plugin."
)
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
    config_file: Path = field(default_factory=paths.config_file)


def plugin_installed(setup: Setup) -> Step:
    name = "the plugin files are installed and current"
    source = plugin_files.payload(setup.plugin_source)
    if isinstance(source, plugin_files.SourceProblem):
        return Step(name, False, source.detail, CHECKOUT)
    target = plugin_files.installed(setup.krita_data_dir)
    desktop = target.parent / plugin_files.desktop_name()
    if not target.is_dir() or not desktop.is_file():
        return Step(name, False, f"nothing is installed in {paths.tilde(target.parent)}", INSTALL)
    try:
        installed_desktop = desktop.read_bytes()
        installed_hash = plugin_files.source_hash(target)
    except OSError as error:
        detail = f"cannot read the installed plugin in {paths.tilde(target.parent)}: "
        return Step(name, False, detail + str(error.strerror), INSTALL)
    if installed_desktop != source.desktop:
        return Step(name, False, "the installed .desktop file differs from the repo's", INSTALL)
    if installed_hash != source.hash:
        detail = f"installed {installed_hash[:12]}, repo {source.hash[:12]}"
        return Step(name, False, detail, INSTALL)
    return Step(name, True, f"hash {source.hash[:12]}")


def plugin_enabled(setup: Setup) -> Step:
    name = "kritarc enables the plugin"
    if _kritarc_enables(setup.kritarc):
        return Step(name, True, f"[python] enable_{paths.PLUGIN_NAME}=true")
    return Step(name, False, f"{paths.tilde(setup.kritarc)} does not enable it", ENABLE)


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
    name = "the protocol and plugin hash match"
    source = plugin_files.payload(plugin_source)
    if isinstance(source, plugin_files.SourceProblem):
        return Step(name, False, source.detail, CHECKOUT)
    running_hash = str(health.get("plugin_hash"))
    protocol = health.get("protocol")
    current = protocol == PROTOCOL and running_hash == source.hash
    detail = f"protocol {protocol}, running {running_hash[:12]}, repo {source.hash[:12]}"
    return Step(name, current, detail, INSTALL)


def roots_allowed(setup: Setup) -> Step:
    # Counts only: doctor's output is pasted into notes, and roots name the owner's folders.
    name = "at least one root is allowed"
    try:
        allowed = roots.load(setup.config_file)
    except roots.ConfigError as problem:
        fix = f"Fix {setup.config_file.name} by hand, or delete it and add the roots again."
        return Step(name, False, str(problem), fix)
    if not allowed:
        return Step(name, False, "no roots, so agents can open nothing", roots.ADD)
    reaching = roots.too_far(allowed, setup.config_file)
    if reaching:
        detail = f"{reaching} of {len(allowed)} roots reach too far"
        fix = "Run `uv run krita-art-mcp roots remove <folder>` for /, home or the data folder."
        return Step(name, False, detail, fix)
    missing = sum(not os.path.isdir(root) for root in allowed)
    if missing:
        detail = f"{missing} of {len(allowed)} roots are no longer folders"
        fix = "Re-create them, or run `uv run krita-art-mcp roots remove <folder>`."
        return Step(name, False, detail, fix)
    return Step(name, True, f"{len(allowed)} root{'' if len(allowed) == 1 else 's'}")


def bridge_missing() -> Step:
    log = paths.tilde(paths.plugin_log())
    fix = f"Restart Krita; if the bridge still does not start, read {log}."
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
