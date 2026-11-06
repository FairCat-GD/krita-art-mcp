import asyncio
import contextlib
import json
import os
import shutil
import statistics
import sys
import time
import uuid
from pathlib import Path
from typing import Any, TextIO

from jsonschema import Draft202012Validator
from mcp import Client, StdioServerParameters

from krita_art_mcp import __version__, journal, paths, schemas, setup_checks
from krita_art_mcp.bridge_client import BridgeClient, Done
from krita_art_mcp.instructions import INSTRUCTIONS
from krita_art_mcp.probe import changes, opening, painting, pixels, previews, updates, writes
from krita_art_mcp.probe.common import close
from krita_art_mcp.probe.report import Report, code, tool
from krita_art_mcp.tools import BUILT_TOOLS, operations
from krita_art_mcp.tools.documents import SRGB_PROFILE

H4_CALLS = 500
H4_P95_BUDGET_S = 0.050
MAX_INSTRUCTIONS = 4096
CYCLES = 20
# About half the calls a whole run journals; fewer means the check read the wrong place.
MIN_JOURNALED = 340
# Another client's transfer file lives for milliseconds; one the probe leaked stays.
LEFTOVER_SETTLE_S = 1.0
# Every document the probe makes carries this name, so a killed run's leftovers can be found.
PREFIX = "krita-art-mcp probe"


def run(
    out: TextIO = sys.stdout,
    client: BridgeClient | None = None,
    harness: Path | None = None,
    serve: list[str] | None = None,
) -> int:
    started = time.monotonic()
    report = Report(out)
    harness = harness or paths.harness_dir()
    # The probe owns the harness folder: leftovers from a killed run go first, and its own
    # files go when it ends, however it ends.
    with contextlib.ExitStack() as cleanup:
        _sweep(harness)
        cleanup.callback(_sweep, harness)
        bridge = client or BridgeClient(any_plugin=True)
        _probe(report, bridge, serve or _serve_command(), harness)
    return report.summary(time.monotonic() - started)


def _sweep(harness: Path) -> None:
    shutil.rmtree(harness, ignore_errors=True)
    paths.private_dir(harness)


def _serve_command() -> list[str]:
    return [str(Path(sys.executable).with_name("krita-art-mcp")), "serve"]


def _server(serve: list[str], harness: Path, name: str) -> StdioServerParameters:
    # Each server keeps its journal in the harness folder, never in the owner's data dir.
    env = {"KRITA_ART_MCP_DATA_DIR": str(harness / name)}
    return StdioServerParameters(command=serve[0], args=serve[1:], env=env)


def _probe(report: Report, client: BridgeClient, serve: list[str], harness: Path) -> None:
    health = client.health()
    if not isinstance(health, Done):
        report.check("the bridge answers its health check", False, health.error["message"])
        return
    info = health.result
    current = setup_checks.plugin_current(info, paths.plugin_source())
    if not report.check("the running plugin is the repo's", current.passed, current.detail):
        report.note(f"Stopped: {current.fix}")
        return
    report.check(
        "health reports this plugin version",
        info.get("plugin_version") == __version__,
        f"plugin {info.get('plugin_version')}",
    )
    asyncio.run(_over_stdio(report, _server(serve, harness, "server-a"), info))
    _runtime(report, info)
    # First, because what a dead run left dirty would stop this one at the unsaved check.
    asyncio.run(_close_leftovers(report, client, serve, harness))
    if _no_unsaved_documents(report, client):
        asyncio.run(_documents(report, client, serve, harness))
        _nothing_uncertain(report, harness)


async def _over_stdio(
    report: Report, server_a: StdioServerParameters, info: dict[str, Any]
) -> None:
    async with Client(server_a) as mcp:
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


def _runtime(report: Report, info: dict[str, Any]) -> None:
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


def _no_unsaved_documents(report: Report, client: BridgeClient) -> bool:
    # A crash while the probe makes and closes documents must cost the owner nothing.
    outcome = client.call("bridge.unsaved_documents")
    unsaved = outcome.result.get("unsaved") if isinstance(outcome, Done) else None
    if isinstance(outcome, Done):
        report.open_documents = outcome.result.get("open")
    return report.check(
        "no Krita document has unsaved changes, so the document checks may run",
        unsaved == 0,
        "0 unsaved" if unsaved == 0 else f"{unsaved} unsaved: save your documents first",
    )


def _create_args(name: str, request_id: str, **changes: Any) -> dict[str, Any]:
    return {
        "name": f"{PREFIX} {name}",
        "size_px": [64, 32],
        "color_model": "RGBA",
        "depth": "U8",
        "profile_id": SRGB_PROFILE,
        "background": "transparent",
        "request_id": request_id,
        **changes,
    }


def _created_here(entry: dict[str, Any]) -> bool:
    # Never one the owner opened: those are read_only, whatever their name.
    return bool(entry["name"].startswith(PREFIX)) and entry["mode"] != "read_only"


async def _probe_documents(mcp: Client) -> list[dict[str, Any]]:
    listed = await tool(mcp, "krita_document_list", {})
    entries = (listed.get("data") or {}).get("documents", [])
    return [entry for entry in entries if _created_here(entry)]


async def _own_documents(mcp: Client, harness: Path) -> list[dict[str, Any]]:
    # The probe's own: the documents it created, and any file it opened from its folder.
    listed = await tool(mcp, "krita_document_list", {})
    entries = (listed.get("data") or {}).get("documents", [])
    folder = os.path.realpath(harness) + "/"
    return [
        entry
        for entry in entries
        if _created_here(entry)
        or (entry["mode"] != "new" and (entry["path"] or "").startswith(folder))
    ]


async def _sweep_documents(mcp: Client, harness: Path) -> int:
    swept = 0
    for entry in await _own_documents(mcp, harness):
        closed = await close(mcp, entry["document_id"])
        swept += bool((closed.get("data") or {}).get("closed"))
    return swept


def _only_ours_unsaved(client: BridgeClient, own: list[dict[str, Any]]) -> bool:
    # A close can crash Krita, so one runs only when that could cost the owner nothing.
    outcome = client.call("bridge.unsaved_documents")
    if not isinstance(outcome, Done):
        return False
    # Krita counts its own flag, which a verified save leaves set.
    held = sum(bool(entry["krita_modified"]) for entry in own)
    return int(outcome.result.get("unsaved", 1)) <= held


async def _close_leftovers(
    report: Report, client: BridgeClient, serve: list[str], harness: Path
) -> None:
    async with Client(_server(serve, harness, "server-a")) as a:
        own = await _own_documents(a, harness)
        if not own or not _only_ours_unsaved(client, own):
            return
        swept = await _sweep_documents(a, harness)
    if swept:
        report.note(f"Closed {swept} document(s) a dead probe run left open.")


async def _documents(report: Report, client: BridgeClient, serve: list[str], harness: Path) -> None:
    async with (
        Client(_server(serve, harness, "server-a")) as a,
        Client(_server(serve, harness, "server-b")) as b,
    ):
        before = _transfer_files(harness)
        listed = writes.take(writes.places(harness.parent))
        try:
            with report.timed("document"):
                await _document_checks(report, a, b, harness)
            with report.timed("cycle"):
                await _cycles(report, a)
            with report.timed("open"):
                await opening.run(report, a, b, client, harness)
            with report.timed("pixel"):
                await pixels.run(report, a, client, harness)
            with report.timed("preview"):
                await previews.run(report, a, harness)
            with report.timed("change"):
                await changes.run(report, a, b, client, harness)
            with report.timed("update"):
                await updates.run(report, a, client, harness)
            await painting.run(report, a, b, client, harness)
            await _no_leftovers(report, a, harness, before)
            _nothing_stray(report, listed)
        finally:
            await _sweep_documents(a, harness)
            await _sweep_documents(b, harness)


def _nothing_uncertain(report: Report, harness: Path) -> None:
    # A failed call the run provoked proves what it did, so a misplaced marker shows here. Only
    # calls with a request_id are journaled: reads, harness ops and the probe's own bridge calls
    # are outside it.
    dispatched, left = 0, []
    for folder in sorted(harness.glob("server-*/journal")):
        requests: dict[str, None] = {}
        for path in sorted(folder.glob("*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                found = json.loads(line)
                if found["phase"] == "dispatched":
                    dispatched += 1
                    requests[found["request_id"]] = None
        reader = journal.Journal(folder)
        for request_id in requests:
            prior = reader.lookup(request_id)
            for attempt in prior.attempts if prior is not None else []:
                if attempt.outcome == journal.UNKNOWN:
                    left.append(f"{attempt.tool} {_left_as(reader, attempt.operation_id)}")
    report.check(
        "no journaled call in this run was left unsettled (reads, harness ops and direct bridge "
        "calls are not journaled)",
        dispatched >= MIN_JOURNALED and not left,
        f"{dispatched} dispatched, at least {MIN_JOURNALED}" + "".join(f"; {it}" for it in left),
    )


def _left_as(reader: journal.Journal, operation_id: str) -> str:
    # What an unsettled attempt's own line says of it, if it has one.
    line = reader.finished_line(operation_id)
    if line is None:
        return "dispatched with no finished line"
    if line.result is None:
        return "joined another call that never settled"
    return operations.said(((line.result or {}).get("structured") or {}).get("error"))


def _nothing_stray(report: Report, listed: writes.Listing) -> None:
    # Before the final sweeps, as the leftovers are.
    stray = writes.strays(listed, writes.take(list(listed)))
    report.check(
        "N-04: nothing is written outside the data directory and Krita's own files",
        not stray,
        "; ".join(stray[:5]) or f"{len(listed)} places listed",
    )


def _transfer_files(harness: Path) -> set[str]:
    # Beside the harness folder, as Places has it.
    transfer = harness.parent / "transfer"
    return {entry.name for entry in os.scandir(transfer)} if transfer.is_dir() else set()


async def _settle() -> None:
    await asyncio.sleep(LEFTOVER_SETTLE_S)


async def _no_leftovers(report: Report, mcp: Client, harness: Path, before: set[str]) -> None:
    # Before the final sweeps, which would hide what a check failed to clean up. Only files that
    # appeared during the run and outlast a pause count, so another client's are left out.
    left = await _own_documents(mcp, harness)
    files = _transfer_files(harness) - before
    if files:
        await _settle()
        files &= _transfer_files(harness)
    report.check(
        "the probe left no document open and no transfer file",
        not left and not files,
        f"{len(left)} document(s) open, {len(files)} transfer file(s)",
    )


async def _document_checks(report: Report, a: Client, b: Client, harness: Path) -> None:
    request_id = str(uuid.uuid4())
    arguments = _create_args("lease", request_id)
    created = await tool(a, "krita_document_create", arguments)
    data = created.get("data") or {}
    if not report.check(
        "krita_document_create makes a new RGBA / U8 / sRGB document",
        created.get("status") == "completed"
        and data.get("mode") == "new"
        and data.get("profile_id") == SRGB_PROFILE
        and data.get("canvas_px") == [64, 32],
        f"{data.get('profile_id')}" if data else str(created.get("error")),
    ):
        return
    document_id = created["document_id"]
    first = await _probe_documents(a)
    second = await _probe_documents(a)
    mine = [entry for entry in first if entry["document_id"] == document_id]
    report.check(
        "krita_document_list shows it once, clean, under one stable id",
        len(mine) == 1
        and mine[0]["dirty"] is False
        and mine[0]["mode"] == "new"
        and mine[0]["path"] is None
        and first == second,
        f"{len(mine)} entries for {document_id}",
    )
    again = await tool(a, "krita_document_create", arguments)
    from_b = await tool(b, "krita_document_create", arguments)
    count = len(await _probe_documents(a))
    report.check(
        "a retried create returns the original receipt, through the journal and the bridge",
        again == created and from_b == created and count == 1,
        f"{count} probe document(s) open",
    )
    changed = _create_args("other", request_id)
    report.check(
        "the same request_id with other arguments conflicts, in the server and the bridge",
        code(await tool(a, "krita_document_create", changed)) == "REQUEST_ID_CONFLICT"
        and code(await tool(b, "krita_document_create", changed)) == "REQUEST_ID_CONFLICT",
    )
    refused = await close(b, document_id)
    b_sees = [entry["document_id"] for entry in await _probe_documents(b)]
    report.check(
        "a second serve process is refused the lease, and still reads",
        code(refused) == "DOCUMENT_IN_USE" and b_sees == [document_id],
        str(code(refused)),
    )
    got = await tool(a, "krita_operation_get", {"operation_id": created["operation_id"]})
    report.check(
        "krita_operation_get returns the create's receipt",
        (got.get("data") or {}).get("receipt") == created,
    )
    cancel = {"operation_id": created["operation_id"], "request_id": str(uuid.uuid4())}
    cancelled = await tool(a, "krita_operation_cancel", cancel)
    report.check(
        "krita_operation_cancel reports a finished operation as completed",
        (cancelled.get("data") or {}).get("state") == "completed",
    )
    deeper = _create_args("deep", str(uuid.uuid4()), depth="U16")
    report.check(
        "a 16-bit document is UNSUPPORTED_CAPABILITY",
        code(await tool(a, "krita_document_create", deeper)) == "UNSUPPORTED_CAPABILITY",
    )
    report.check(
        "closing an unknown id is DOCUMENT_NOT_FOUND",
        code(await close(a, "doc-000000000000", "refuse")) == "DOCUMENT_NOT_FOUND",
    )
    closed = await close(a, document_id, "refuse")
    remaining = [entry["document_id"] for entry in await _probe_documents(a)]
    report.check(
        "krita_document_close closes a clean document",
        (closed.get("data") or {}).get("closed") is True and document_id not in remaining,
    )
    report.check(
        "the journal holds the create as dispatched, then finished",
        _phases(harness / "server-a", request_id) == ["dispatched", "finished"],
        ", ".join(_phases(harness / "server-a", request_id)),
    )


def _phases(data_dir: Path, request_id: str) -> list[str]:
    lines = []
    for path in sorted((data_dir / "journal").glob("*.jsonl")):
        lines += [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    return [line["phase"] for line in lines if line["request_id"] == request_id]


async def _cycles(report: Report, a: Client) -> None:
    # krita_document_close stays only if this never crashes Krita.
    failures = []
    for cycle in range(CYCLES):
        created = await tool(
            a, "krita_document_create", _create_args(f"cycle {cycle}", str(uuid.uuid4()))
        )
        closed = (
            await close(a, created["document_id"])
            if created.get("status") == "completed"
            else created
        )
        if (closed.get("data") or {}).get("closed") is not True:
            failures.append(f"cycle {cycle}: {code(closed)}")
            break
    alive = await tool(a, "krita_server_info", {})
    report.check(
        f"{CYCLES} create and close cycles, and Krita still answers",
        not failures and alive.get("status") == "completed",
        "; ".join(failures) or f"{CYCLES} cycles",
    )
