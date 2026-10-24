import asyncio
import contextlib
import datetime
import logging
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from bridge_core import documents, harness, resources
from bridge_core.bridge import Bridge
from bridge_core.jobs import Call
from bridge_core.registry import Registry
from fake_krita import FakePort, FakeResources, MainThread
from mcp import Client
from mcp.types import CallToolResult

from krita_art_mcp.bridge_client import REGISTER_GRACE_S, BridgeClient
from krita_art_mcp.journal import Journal
from krita_art_mcp.paths import Places
from krita_art_mcp.server import build_server
from krita_art_mcp.setup_checks import Step

# A real Bridge on a fake Krita, and real servers that reach it, for the server's tests.
PLUGIN_PACKAGE = Path(__file__).resolve().parents[2] / "plugin" / "krita_art_mcp_bridge"
A: dict[str, Any] = {"pid": 101, "started_at": "Sat Oct 24 10:00:00 2026"}
B: dict[str, Any] = {"pid": 202, "started_at": "Sat Oct 24 10:05:00 2026"}
NOT_RUNNING = Step("Krita is running", False, "no krita process", "Start Krita.")
NOW = datetime.datetime(2026, 10, 24, 12, 0, tzinfo=datetime.UTC)


class World:
    def __init__(
        self, tmp_path: Path, bridge: Bridge, port: FakePort, resources: FakeResources
    ) -> None:
        self.tmp_path = tmp_path
        self.bridge = bridge
        self.port = port
        self.resources = resources
        self.alive: dict[int, bool] = {}
        self.gate = threading.Event()
        self.gate.set()

    def journal(self, name: str = "a") -> Journal:
        return Journal(self.tmp_path / name / "journal", now=lambda: NOW)

    def places(self, name: str = "a") -> Places:
        # The bridge's data dir is tmp_path; each server keeps its own baselines.
        return Places.under(self.tmp_path, self.tmp_path / name)

    def client(
        self,
        identity: dict[str, Any] = A,
        budget_s: float = 3.0,
        grace_s: float = REGISTER_GRACE_S,
    ) -> BridgeClient:
        return BridgeClient(
            bridge_file=self.tmp_path / "bridge.json",
            budget_s=budget_s,
            poll_s=0.2,
            grace_s=grace_s,
            is_live_krita=lambda pid: True,
            explain=lambda: NOT_RUNNING,
            identity=identity,
        )

    def server(self, identity: dict[str, Any] = A, name: str = "a", budget_s: float = 3.0) -> Any:
        client = self.client(identity, budget_s)
        return Server(build_server(client, self.journal(name), self.places(name)))


class Server:
    def __init__(self, mcp_server: Any) -> None:
        self.mcp_server = mcp_server

    def call(self, tool: str, arguments: dict[str, Any]) -> CallToolResult:
        async def run() -> CallToolResult:
            async with Client(self.mcp_server) as mcp:
                return await mcp.call_tool(tool, arguments)

        return asyncio.run(run())

    def content(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = self.call(tool, arguments)
        content: dict[str, Any] | None = result.structured_content
        assert content is not None
        return content


@contextlib.contextmanager
def running_world(tmp_path: Path) -> Iterator[World]:
    main = MainThread()
    port = FakePort()
    resources_port = FakeResources()
    state: dict[str, World] = {}
    registry = Registry(port, lambda client: state["world"].alive.get(client["pid"], True))

    def slow(args: dict[str, Any], call: Call) -> dict[str, Any]:
        state["world"].gate.wait(10)
        return {"slow": True}

    bridge = Bridge(
        data_dir=tmp_path,
        package_dir=PLUGIN_PACKAGE,
        facts={"krita_version": "5.3.4", "qt_major": 5},
        handlers={
            **documents.handlers(registry, port, tmp_path),
            **harness.handlers(registry, port, tmp_path),
            **resources.handlers(resources_port),
            "slow": slow,
        },
        wake=main.wake,
        on_main_thread=main.is_current,
        is_live_krita=lambda pid: False,
        log=logging.getLogger("worlds"),
    )
    main.bridge = bridge
    main.thread.start()
    assert bridge.start()
    state["world"] = World(tmp_path, bridge, port, resources_port)
    try:
        yield state["world"]
    finally:
        state["world"].gate.set()
        bridge.stop()
        main.stopping = True
        main.thread.join(5)
