import json
import queue
import subprocess
import sys
import threading
from importlib.metadata import version
from pathlib import Path
from typing import Any

import bridge_core

CLI = str(Path(sys.executable).with_name("krita-art-mcp"))


def test_plugin_version_equals_package_version() -> None:
    assert bridge_core.PLUGIN_VERSION == version("krita-art-mcp") == "0.1.0"


def test_cli_prints_its_version() -> None:
    result = subprocess.run([CLI, "--version"], capture_output=True, text=True, check=True)
    assert result.stdout == "krita-art-mcp 0.1.0\n"


def test_stdio_initialize_names_the_server_and_lists_no_tools() -> None:
    initialize = {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "version-test", "version": "0"},
    }
    server = subprocess.Popen(
        [CLI, "serve"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True
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

    def reply() -> Any:
        return json.loads(replies.get(timeout=30))["result"]

    try:
        send({"id": 1, "method": "initialize", "params": initialize})
        assert reply()["serverInfo"] == {"name": "krita-art", "version": "0.1.0"}
        send({"method": "notifications/initialized"})
        send({"id": 2, "method": "tools/list"})
        assert reply()["tools"] == []
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
