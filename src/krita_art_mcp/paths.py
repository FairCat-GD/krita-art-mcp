from pathlib import Path

PLUGIN_NAME = "krita_art_mcp_bridge"


def default_data_dir() -> Path:
    # bridge.json, logs and the harness folder stay here whatever KRITA_ART_MCP_DATA_DIR says,
    # because Krita launched from the Dock never sees the variable (decision 25).
    return Path.home() / "Library" / "Application Support" / "krita-art-mcp"


def bridge_file() -> Path:
    return default_data_dir() / "bridge.json"


def plugin_log() -> Path:
    return default_data_dir() / "logs" / "plugin.log"


def harness_dir() -> Path:
    return default_data_dir() / "harness"


def krita_data_dir() -> Path:
    return Path.home() / "Library" / "Application Support" / "Krita"


def kritarc() -> Path:
    return Path.home() / "Library" / "Preferences" / "kritarc"


def plugin_source() -> Path:
    # The server runs from its checkout (`uv run --project <repo>`), so the plugin sits beside it.
    return Path(__file__).resolve().parents[2] / "plugin"
