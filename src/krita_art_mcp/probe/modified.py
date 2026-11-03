from pathlib import Path
from typing import Any

from mcp import Client

from krita_art_mcp.bridge_client import BridgeClient, Done
from krita_art_mcp.probe import fixtures
from krita_art_mcp.probe.common import (
    add_layer,
    brush_args,
    close,
    finished,
    harness_call,
    inspect_data,
    line_points,
    listed_entry,
    open_args,
    stroke_args,
)
from krita_art_mcp.probe.opening import harness_export
from krita_art_mcp.probe.report import Report, code, tool
from krita_art_mcp.probe.saving import SAVE_LIMIT_S, save_args

KINDS = ("png", "kra", "ora")
ARTICLES = {"png": "a", "kra": "a", "ora": "an"}


async def run(
    report: Report, a: Client, client: BridgeClient, harness: Path, hard: dict[str, Any]
) -> None:
    # Krita's own flag beside the bridge's dirty: an export never clears it (K45), so after a
    # verified save the two differ, and refuse closes only what that save holds.
    folder = harness / "modified"
    folder.mkdir(exist_ok=True)
    sources = await _sources(report, a, client, folder)
    if sources is None:
        return
    for kind in KINDS:
        await _saved(report, a, kind, sources[kind], folder, hard)
    await _krita_only(report, a, client, sources["png"], folder)


async def _sources(
    report: Report, a: Client, client: BridgeClient, folder: Path
) -> dict[str, Path] | None:
    sources = {kind: folder / f"flags.{kind}" for kind in KINDS}
    fixtures.write_png(sources["png"], fixtures.composite(fixtures.probe_stack()))
    fixtures.write_ora(sources["ora"], fixtures.probe_stack())
    opened = await tool(a, "krita_document_open", open_args(sources["ora"], "read_only"))
    exported: Any = opened.get("error")
    if opened.get("status") == "completed":
        try:
            exported = harness_export(client, opened["document_id"], sources["kra"])
        finally:
            await close(a, opened["document_id"])
    if not isinstance(exported, Done):
        report.check("the modified-flag checks' KRA fixture is written", False, str(exported))
        return None
    return sources


async def _saved(
    report: Report, a: Client, kind: str, source: Path, folder: Path, hard: dict[str, Any]
) -> None:
    name = (
        f"after a verified save of {ARTICLES[kind]} {kind.upper()} working copy, the receipt, "
        "list and inspect say dirty false and krita_modified true, it still points at its "
        "working copy, and refuse closes it"
    )
    work = folder / f"work-{kind}"
    opened = await tool(a, "krita_document_open", open_args(source, "working_copy", work))
    if opened.get("status") != "completed":
        report.check(name, False, f"open: {code(opened)}")
        return
    document_id, data = opened["document_id"], opened["data"]
    painted: dict[str, Any] = {}
    saved: dict[str, Any] = {}
    closed: dict[str, Any] = {}
    found: list[dict[str, Any]] = []
    try:
        layer = await add_layer(a, document_id, data["root_layer_id"], f"flags {kind}")
        line = line_points(6, 6, 40, 10)
        stroke = stroke_args(document_id, layer or "", brush_args(hard, size_px=4), line)
        painted = await tool(a, "krita_paint_stroke", stroke)
        target = folder / f"flags-{kind}.kra"
        sent = await tool(a, "krita_document_save", save_args(document_id, target))
        saved = await finished(a, sent, SAVE_LIMIT_S)
        found = [saved.get("data") or {}, await listed_entry(a, document_id)]
        found.append(await inspect_data(a, document_id))
        closed = await close(a, document_id, "refuse")
    finally:
        if (closed.get("data") or {}).get("closed") is not True:
            await close(a, document_id)
    flags = [(one.get("dirty"), one.get("krita_modified")) for one in found]
    paths = [found[0].get("document_path"), found[2].get("path")] if found else []
    report.check(
        name,
        painted.get("status") == "completed"
        and saved.get("status") == "completed"
        and flags == [(False, True)] * 3
        and paths == [data["path"]] * 2
        and (closed.get("data") or {}).get("closed") is True,
        f"{code(painted) or code(saved) or ''} flags {flags}, close {code(closed) or 'closed'}",
    )


async def _krita_only(
    report: Report, a: Client, client: BridgeClient, source: Path, folder: Path
) -> None:
    name = (
        "a layer only Krita added lists as krita_modified with dirty false, and refuse refuses "
        "the close with both flags and leaves the document open"
    )
    work = folder / "work-krita-only"
    opened = await tool(a, "krita_document_open", open_args(source, "working_copy", work))
    if opened.get("status") != "completed":
        report.check(name, False, f"open: {code(opened)}")
        return
    document_id, data = opened["document_id"], opened["data"]
    try:
        added = harness_call(
            client,
            "harness.add_node",
            document_id=document_id,
            kind="clone_layer",
            layer_id=data["layers"][0]["id"],
        )
        entry = await listed_entry(a, document_id)
        refused = await close(a, document_id, "refuse")
        still = await listed_entry(a, document_id)
    finally:
        await close(a, document_id)
    listed = (entry.get("dirty"), entry.get("krita_modified"))
    details = (refused.get("error") or {}).get("details") or {}
    report.check(
        name,
        isinstance(added, Done)
        and listed == (False, True)
        and code(refused) == "DOCUMENT_DIRTY"
        and (details.get("dirty"), details.get("krita_modified")) == (False, True)
        and bool(still),
        f"listed {listed}, close {code(refused)} {details}",
    )
