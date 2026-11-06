import json
import os
import queue
import subprocess
import sys
import threading
import time
from importlib.metadata import version
from pathlib import Path
from typing import Any

import bridge_core

from krita_art_mcp.instructions import INSTRUCTIONS
from krita_art_mcp.tools import BUILT_TOOLS

CLI = str(Path(sys.executable).with_name("krita-art-mcp"))
# The release this checkout is; bumped with the package version.
EXPECTED_VERSION = "0.23.0"


def test_plugin_version_equals_package_version() -> None:
    assert bridge_core.PLUGIN_VERSION == version("krita-art-mcp") == EXPECTED_VERSION


def test_cli_prints_its_version() -> None:
    result = subprocess.run([CLI, "--version"], capture_output=True, text=True, check=True)
    assert result.stdout == f"krita-art-mcp {EXPECTED_VERSION}\n"


def test_stdio_initialize_names_the_server_and_lists_the_built_tools(tmp_path: Path) -> None:
    initialize = {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "version-test", "version": "0"},
    }
    # Its own data dir, so the baseline sweep at start never reaches the owner's.
    env = {**os.environ, "KRITA_ART_MCP_DATA_DIR": str(tmp_path)}
    server = subprocess.Popen(
        [CLI, "serve"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=env
    )
    assert server.stdin is not None and server.stdout is not None
    stdin, stdout = server.stdin, server.stdout
    replies: queue.Queue[str] = queue.Queue()

    def read_replies() -> None:
        for line in stdout:
            replies.put(line)

    # A reader thread lets every reply wait under a timeout instead of hanging the run.
    threading.Thread(target=read_replies, daemon=True).start()

    def send(message: dict[str, Any]) -> None:
        stdin.write(json.dumps({"jsonrpc": "2.0", **message}) + "\n")
        stdin.flush()

    def reply(request_id: int) -> Any:
        # Notifications and other replies may come first; only the matching id answers.
        deadline = time.monotonic() + 30
        while True:
            message = json.loads(replies.get(timeout=max(0.0, deadline - time.monotonic())))
            if message.get("id") == request_id:
                return message["result"]

    try:
        send({"id": 1, "method": "initialize", "params": initialize})
        initialized = reply(1)
        assert initialized["serverInfo"] == {"name": "krita-art", "version": EXPECTED_VERSION}
        assert initialized["instructions"] == INSTRUCTIONS
        send({"method": "notifications/initialized"})
        send({"id": 2, "method": "tools/list"})
        assert sorted(tool["name"] for tool in reply(2)["tools"]) == BUILT_TOOLS
    finally:
        # Closing stdin first lets the server exit, so a failed assertion cannot hang the run.
        stdin.close()
        try:
            server.wait(timeout=30)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait()
        stdout.close()
    assert server.returncode == 0
