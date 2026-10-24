import os
from dataclasses import dataclass
from pathlib import Path

PLUGIN_NAME = "krita_art_mcp_bridge"


def private_dir(path: Path) -> Path:
    # mkdir's mode reaches only the last folder, and only when it makes it.
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


def default_data_dir() -> Path:
    # bridge.json, logs and the harness folder stay here whatever KRITA_ART_MCP_DATA_DIR says,
    # because Krita launched from the Dock never sees the variable (decision 25).
    return Path.home() / "Library" / "Application Support" / "krita-art-mcp"


def server_data_dir() -> Path:
    # Only what the server owns (captures, baselines, the journal) follows the variable.
    override = os.environ.get("KRITA_ART_MCP_DATA_DIR")
    return Path(override) if override else default_data_dir()


def journal_dir() -> Path:
    return server_data_dir() / "journal"


def config_file() -> Path:
    return default_data_dir() / "config.json"


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


@dataclass(frozen=True)
class Places:
    # Every folder a tool reaches, handed in, so no test can reach the owner's.
    config_file: Path
    transfer_dir: Path
    harness_dir: Path
    baselines_dir: Path
    captures_dir: Path

    @classmethod
    def under(cls, default_data: Path, server_data: Path) -> "Places":
        # The plugin sees only the default data dir (decision 25); baselines are the server's.
        return cls(
            config_file=default_data / "config.json",
            transfer_dir=default_data / "transfer",
            harness_dir=default_data / "harness",
            baselines_dir=server_data / "baselines",
            captures_dir=server_data / "captures",
        )

    @classmethod
    def default(cls) -> "Places":
        return cls.under(default_data_dir(), server_data_dir())
