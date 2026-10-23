from pathlib import Path


def data_dir() -> Path:
    # Krita launched from the Dock never sees KRITA_ART_MCP_DATA_DIR, so the bridge stays here.
    return Path.home() / "Library" / "Application Support" / "krita-art-mcp"


def bridge_file(data: Path) -> Path:
    return data / "bridge.json"


def log_dir(data: Path) -> Path:
    return data / "logs"


def private_dir(path: Path) -> Path:
    # Created as a parent, the folder would get the default 0755; it holds the token's file.
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.chmod(0o700)
    return path
