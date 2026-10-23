import asyncio
import contextlib
import shutil
import statistics
import sys
import time
from pathlib import Path
from typing import Any, TextIO

from jsonschema import Draft202012Validator
from mcp import Client, StdioServerParameters

from krita_art_mcp import __version__, paths, plugin_files, schemas
from krita_art_mcp.bridge_client import BridgeClient, Done, Failed
from krita_art_mcp.errors import PROTOCOL
from krita_art_mcp.instructions import INSTRUCTIONS
from krita_art_mcp.tools import BUILT_TOOLS

H4_CALLS = 500
H4_P95_BUDGET_S = 0.050
MAX_INSTRUCTIONS = 4096


class Report:
    def __init__(self, out: TextIO) -> None:
        self._out = out
        self.passed = 0
        self.failed = 0

    def check(self, name: str, passed: bool, detail: str = "") -> bool:
        if passed:
            self.passed += 1
        else:
            self.failed += 1
        self._line("PASS" if passed else "FAIL", name, detail)
        return passed

    def measured(self, name: str, detail: str) -> None:
        self._line("MEASURED", name, detail)

    def note(self, text: str) -> None:
        print(text, file=self._out, flush=True)

    def summary(self) -> int:
        self.note(f"probe: {self.passed} PASS, {self.failed} FAIL")
        return 1 if self.failed or not self.passed else 0

    def _line(self, outcome: str, name: str, detail: str) -> None:
        self.note(f"{outcome:<8} {name}" + (f": {detail}" if detail else ""))


def run(
    out: TextIO = sys.stdout,
    client: BridgeClient | None = None,
    harness: Path | None = None,
    serve: list[str] | None = None,
) -> int:
    report = Report(out)
    harness = harness or paths.harness_dir()
    # The probe owns the harness folder: leftovers from a killed run go first, and its own
    # files go when it ends, however it ends.
    with contextlib.ExitStack() as cleanup:
        _sweep(harness)
        cleanup.callback(_sweep, harness)
        _probe(report, client or BridgeClient(), serve or _serve_command())
    return report.summary()


def _sweep(harness: Path) -> None:
    shutil.rmtree(harness, ignore_errors=True)
    harness.mkdir(parents=True, exist_ok=True)


def _serve_command() -> list[str]:
    return [str(Path(sys.executable).with_name("krita-art-mcp")), "serve"]


def _probe(report: Report, client: BridgeClient, serve: list[str]) -> None:
    health = client.health()
    if not isinstance(health, Done):
        report.check("the bridge answers its health check", False, health.error["message"])
        return
    info = health.result
    repo_hash = plugin_files.source_hash(paths.plugin_source() / paths.PLUGIN_NAME)
    running_hash = str(info.get("plugin_hash"))
    if not report.check(
        "the running plugin is the repo's",
        running_hash == repo_hash,
        f"running {running_hash[:12]}, repo {repo_hash[:12]}",
    ):
        report.note("Stopped: run `uv run krita-art-mcp install-plugin`, then restart Krita.")
        return
    report.check(
        "health reports this protocol and version",
        info.get("protocol") == PROTOCOL and info.get("plugin_version") == __version__,
        f"protocol {info.get('protocol')}, plugin {info.get('plugin_version')}",
    )
    asyncio.run(_over_stdio(report, serve, info))
    _runtime(report, client, info)


async def _over_stdio(report: Report, serve: list[str], info: dict[str, Any]) -> None:
    async with Client(StdioServerParameters(command=serve[0], args=serve[1:])) as mcp:
        server = mcp.server_info
        report.check(
            "serverInfo names krita-art at this version",
            server is not None and (server.name, server.version) == ("krita-art", __version__),
            f"{server.name} {server.version}" if server else "missing",
        )
        instructions = mcp.instructions or ""
        report.check(
            "the instructions are served, at most 4,096 characters",
            instructions == INSTRUCTIONS and len(instructions) <= MAX_INSTRUCTIONS,
            f"{len(instructions)} characters",
        )
        listed = sorted((await mcp.list_tools()).tools, key=lambda tool: tool.name)
        expected = [schemas.load(name) for name in BUILT_TOOLS]
        report.check(
            "tools/list is the built tools, with their schemas",
            [(tool.name, tool.input_schema, tool.output_schema) for tool in listed]
            == [(spec["name"], spec["inputSchema"], spec["outputSchema"]) for spec in expected],
            ", ".join(tool.name for tool in listed),
        )
        validator = Draft202012Validator(schemas.load("krita_server_info")["outputSchema"])
        result = await mcp.call_tool("krita_server_info", {})
        content = result.structured_content or {}
        problems = [problem.message for problem in validator.iter_errors(content)]
        report.check(
            "krita_server_info completes over stdio and matches its schema",
            not result.is_error and content.get("status") == "completed" and not problems,
            "; ".join(problems) or str(content.get("status")),
        )
        data = content.get("data") or {}
        report.check(
            "krita_server_info reports the running Krita",
            (data.get("krita_version"), data.get("session_id"))
            == (info.get("krita_version"), info.get("session_id")),
            f"Krita {data.get('krita_version')}",
        )
        latencies: list[float] = []
        failures = 0
        for _ in range(H4_CALLS):
            started = time.perf_counter()
            reply = await mcp.call_tool("krita_server_info", {})
            latencies.append(time.perf_counter() - started)
            status = (reply.structured_content or {}).get("status")
            failures += reply.is_error or status != "completed"
        p95 = statistics.quantiles(latencies, n=20)[18]
        report.check(
            f"H4 idle: {H4_CALLS} krita_server_info calls, p95 under 50 ms",
            failures == 0 and p95 < H4_P95_BUDGET_S,
            f"p50 {statistics.median(latencies) * 1000:.1f} ms, p95 {p95 * 1000:.1f} ms, "
            f"max {max(latencies) * 1000:.1f} ms, {failures} failed",
        )


def _runtime(report: Report, client: BridgeClient, info: dict[str, Any]) -> None:
    report.measured(
        "Krita's runtime",
        f"Krita {info.get('krita_version')}, Qt {info.get('qt_version')}, "
        f"PyQt {info.get('pyqt_version')}, Python {info.get('python_version')}",
    )
    report.check(
        "Extension.setup() runs on Python's main thread",
        info.get("setup_on_python_main_thread") is True,
        str(info.get("setup_on_python_main_thread")),
    )
    report.measured("Node.paintPolylineStroke", str(info.get("paint_polyline_stroke")))
    outcome = client.call("probe.undo_action")
    if not isinstance(outcome, Done):
        failure = outcome.error["message"] if isinstance(outcome, Failed) else "still running"
        report.check("the edit_undo probe runs", False, failure)
        return
    result = outcome.result
    if "skipped" in result:
        report.measured("edit_undo", f"skipped: {result['skipped']}")
        return
    report.check("Krita has an edit_undo action", result.get("action_found") is True)
    if result.get("action_found"):
        before, after = result["before"], result["after_add_layer"]
        report.measured(
            "edit_undo text",
            f"before {before['text']!r}; after adding a layer {after['text']!r} "
            f"(tooltip {after['tooltip']!r})",
        )
