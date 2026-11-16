import sys
from pathlib import Path
from typing import TextIO

from krita_art_mcp import paths, plugin_files, setup_checks


def run(krita_data_dir: Path, kritarc: Path, out: TextIO = sys.stdout) -> int:
    source = paths.plugin_source()
    checked = plugin_files.payload(source)
    if isinstance(checked, plugin_files.SourceProblem):
        print(f"install-plugin: {checked.detail}. {setup_checks.CHECKOUT}", file=out)
        return 1
    if not krita_data_dir.is_dir():
        print(
            f"install-plugin: {krita_data_dir} does not exist. Start Krita once so it creates its "
            "resource folder, or pass --krita-data-dir.",
            file=out,
        )
        return 1
    target = plugin_files.install(source, krita_data_dir)
    installed_hash = plugin_files.source_hash(target)[:12]
    print(f"Installed the plugin into {target.parent} (hash {installed_hash}).", file=out)
    if setup_checks.plugin_enabled(setup_checks.Setup(kritarc=kritarc)).passed:
        print("Next: restart Krita so it loads this version.", file=out)
    else:
        print("Next:", file=out)
        print("  1. Quit Krita and start it again.", file=out)
        print(
            "  2. In Configure Krita > Python Plugin Manager (in the application menu), enable "
            "Krita Art MCP Bridge.",
            file=out,
        )
        print("  3. Quit Krita and start it again.", file=out)
    print("Then check the setup with `uv run krita-art-mcp doctor`.", file=out)
    return 0
