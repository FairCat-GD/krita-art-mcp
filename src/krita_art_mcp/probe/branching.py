import os
from pathlib import Path
from typing import Any

import numpy as np
from mcp import Client

from krita_art_mcp import baselines
from krita_art_mcp.bridge_client import BridgeClient, Done
from krita_art_mcp.probe import fixtures
from krita_art_mcp.probe.common import (
    add_layer,
    brush_args,
    brush_colour,
    by_name,
    capture,
    capture_composite,
    close,
    create_args,
    finished,
    guard,
    harness_call,
    inspect_data,
    line_points,
    listed_entry,
    open_args,
    protect,
    select,
    stroke_args,
)
from krita_art_mcp.probe.opening import UNWRITABLE
from krita_art_mcp.probe.report import Report, code, differs, sheet_cell, tool
from krita_art_mcp.tools.saving import file_sha256

TOOL = "krita_document_duplicate"
LIMIT_S = 600.0
WHOLE = {"x": 0, "y": 0, "width": fixtures.WIDTH, "height": fixtures.HEIGHT}
# The fixture's base is opaque from row 40 down, where a stroke keeps the composite's alpha.
ALLOWED = {"rect": {"x": 2, "y": 2, "width": 60, "height": 44}}
OVER_BASE = (10, 43, 50, 43)
# Every kind of node the plugin can put in a document beside its paint layers and groups.
NODES = (
    ("filter_layer", "probe shape"),
    ("filter_mask", "probe shape"),
    ("transform_mask", "probe base"),
    ("clone_layer", "probe shape"),
)


def duplicate_args(document_id: str, path: Path) -> dict[str, Any]:
    return {"guard": guard(document_id), "path": str(path)}


async def duplicate(a: Client, document_id: str, path: Path) -> dict[str, Any]:
    arguments = duplicate_args(document_id, path)
    got = await finished(a, await tool(a, TOOL, arguments), LIMIT_S)
    if code(got) == "BUSY":
        # An autosave can hold the document for a moment; nothing was written, so it retries.
        got = await finished(a, await tool(a, TOOL, arguments), LIMIT_S)
    return got


def _render(*sources: dict[str, Any]) -> dict[str, Any]:
    return {
        "recipes": [{"id": "native", "target_size_px": [fixtures.WIDTH, fixtures.HEIGHT]}],
        "filter": "nearest",
        "sources": list(sources),
        "overlays": [],
        "backgrounds": ["transparent"],
    }


def _source(document_id: str, baseline_id: str) -> dict[str, Any]:
    return {
        "document_id": document_id,
        "frame": 0,
        "target": "composite",
        "baseline_id": baseline_id,
    }


async def _closed(a: Client, open_ids: set[str], document_id: str) -> dict[str, Any]:
    # Closes a document the checks still hold open, and only once.
    if document_id not in open_ids:
        return {}
    closed = await close(a, document_id)
    if closed.get("status") == "completed":
        open_ids.discard(document_id)
    return closed


def _held(folder: Path, baseline_id: str) -> bool:
    found = baselines.path_of(folder, baseline_id)
    return found is not None and found.exists()


async def run(
    report: Report, a: Client, client: BridgeClient, harness: Path, hard: dict[str, Any]
) -> None:
    harness = Path(os.path.realpath(harness))
    folder = harness / "branching"
    folder.mkdir(exist_ok=True)
    fixture = folder / "probe.ora"
    fixtures.write_ora(fixture, fixtures.probe_stack())
    fixture_sha = file_sha256(fixture)
    opened = await tool(
        a, "krita_document_open", open_args(fixture, "working_copy", folder / "work")
    )
    document_id = opened.get("document_id")
    if opened.get("status") != "completed" or not document_id:
        report.check("the branch checks' working copy opens", False, str(opened.get("error")))
        return
    held = harness / "server-a" / "baselines"
    open_ids = {document_id}
    try:
        own, problem = await _prepare(a, client, document_id, opened["data"], hard)
        if own is None:
            report.check("the branch checks' document is prepared", False, problem)
            return
        await _branches(report, a, document_id, opened["data"], own, folder, held, hard, open_ids)
    finally:
        await _closed(a, open_ids, document_id)
    working = Path(opened["data"]["path"])
    report.check(
        "the branch checks leave the fixture and the working copy's file as they were",
        file_sha256(fixture) == fixture_sha
        and file_sha256(working) == opened["data"]["source_sha256"],
    )
    await _created(report, a, folder, held)


async def _prepare(
    a: Client, client: BridgeClient, document_id: str, data: dict[str, Any], hard: dict[str, Any]
) -> tuple[str | None, str]:
    # A painted layer of the agent's own with a transparency mask, each kind of node Krita can
    # add, a global and an active local selection, and every other node protected under an
    # allowed mask and a flag. The own layer's id, or what went wrong.
    layers = by_name(data["layers"])
    own = await add_layer(a, document_id, data["root_layer_id"], "branch own")
    if own is None:
        return None, "krita_layer_create made no layer"
    stroke = stroke_args(document_id, own, brush_args(hard, size_px=4), line_points(8, 8, 40, 30))
    if (await tool(a, "krita_paint_stroke", stroke)).get("status") != "completed":
        return None, "the own layer's stroke failed"
    mask = {
        "guard": guard(document_id),
        "parent_id": own,
        "above_id": None,
        "type": "transparency_mask",
        "name": "krita-art-mcp probe branch mask",
        "coverage": "all",
    }
    made = await tool(a, "krita_layer_create", mask)
    if made.get("status") != "completed":
        return None, f"the transparency mask: {code(made)}"
    for kind, layer in NODES:
        added = harness_call(
            client,
            "harness.add_node",
            document_id=document_id,
            kind=kind,
            layer_id=layers[layer]["id"],
        )
        if not isinstance(added, Done):
            return None, f"harness.add_node {kind}: {added}"
    if (await select(a, document_id, {"type": "all"})).get("status") != "completed":
        return None, "the global selection failed"
    rect = {"x": 0, "y": 0, "width": 20, "height": 20}
    local = harness_call(
        client,
        "harness.select_mask",
        document_id=document_id,
        layer_id=layers["probe base"]["id"],
        rect=rect,
    )
    if not isinstance(local, Done):
        return None, f"harness.select_mask: {local}"
    nodes = (await inspect_data(a, document_id))["layers"]
    mine = {own, made["data"]["layer_id"]}
    protected = await protect(
        a, document_id, [node for node in nodes if node["id"] not in mine], ALLOWED, True
    )
    if protected.get("status") != "completed":
        return None, f"krita_protection_set: {code(protected)}"
    return own, ""


async def _branches(
    report: Report,
    a: Client,
    document_id: str,
    data: dict[str, Any],
    own: str,
    folder: Path,
    held: Path,
    hard: dict[str, Any],
    open_ids: set[str],
) -> None:
    source = await inspect_data(a, document_id)
    painted = [layer["id"] for layer in source["layers"] if layer["type"] == "paint"]
    before = {layer: await capture(a, document_id, WHOLE, "layer", layer) for layer in painted}
    flags = await listed_entry(a, document_id)
    target = folder / "branch.kra"
    got = await duplicate(a, document_id, target)
    result = got.get("data") or {}
    branch_id = result.get("new_document_id")
    problems = []
    if got.get("status") != "completed" or not branch_id:
        problems.append(f"{code(got)}: {(got.get('error') or {}).get('details')}")
    elif not target.exists() or file_sha256(target) != result["sha256"]:
        problems.append("the file at the path is not the one the receipt names")
    elif (await listed_entry(a, branch_id)).get("document_id") != branch_id:
        problems.append("the branch is not listed")
    hidden = sorted(name for name in os.listdir(folder) if name.startswith("."))
    if hidden:
        problems.append(f"left beside it: {hidden}")
    report.check(
        "a branch lands verified at its path, its file the receipt's, nothing beside it, as a "
        "document of its own",
        not problems,
        "; ".join(problems),
    )
    if not isinstance(branch_id, str):
        return
    open_ids.add(branch_id)
    try:
        await _inherited(report, a, source, branch_id, result)
        await _unloosened(report, a, branch_id, source, hard)
        after = {layer: await capture(a, document_id, WHOLE, "layer", layer) for layer in painted}
        now = await listed_entry(a, document_id)
        changed = [layer for layer in painted if differs(after[layer], before[layer])]
        stated = (result["source_dirty"], result["source_krita_modified"])
        report.check(
            "the source keeps its dirty and krita_modified flags, as the receipt states them, and "
            "every layer's own pixels",
            (now.get("dirty"), now.get("krita_modified"))
            == (flags.get("dirty"), flags.get("krita_modified"))
            == stated
            and not changed,
            f"{flags} then {now}, receipt {stated}; changed {changed}",
        )
        at_duplicate = await capture_composite(a, document_id)
        await _apart(report, a, document_id, branch_id, own, hard)
        await _compared(report, a, document_id, data["baseline_id"], result, at_duplicate, held)
        await _refusals(report, a, document_id, folder, target)
        closed = await _closed(a, open_ids, branch_id)
        report.check(
            "closing the branch removes its baseline alone, and its file stays the receipt's",
            closed.get("status") == "completed"
            and not _held(held, result["baseline_id"])
            and _held(held, data["baseline_id"])
            and file_sha256(target) == result["sha256"],
            str(code(closed)),
        )
        await _source_closed(report, a, document_id, folder, held, open_ids)
    finally:
        await _closed(a, open_ids, branch_id)


async def _inherited(
    report: Report, a: Client, source: dict[str, Any], branch_id: str, result: dict[str, Any]
) -> None:
    branch = await inspect_data(a, branch_id)
    kept = {layer["id"]: (layer["type"], layer["protected"]) for layer in source["layers"]}
    found = {layer["id"]: (layer["type"], layer["protected"]) for layer in branch.get("layers", [])}
    kinds = sorted({kind for kind, _ in kept.values()})
    report.check(
        "the branch keeps every node's id, type and protection, the allowed mask and both flags; "
        "its history is empty",
        found == kept
        and branch.get("protection") == source["protection"] == result["protection"]
        and branch.get("history", {}).get("undo_available") == 0
        and branch.get("path") == result["path"],
        f"kinds {kinds}; {len(found)} of {len(kept)} nodes; {branch.get('protection')}",
    )


async def _unloosened(
    report: Report, a: Client, branch_id: str, source: dict[str, Any], hard: dict[str, Any]
) -> None:
    looser = await protect(a, branch_id, [], None)
    base = by_name(source["layers"])["probe base"]["id"]
    stroke = stroke_args(branch_id, base, brush_args(hard, size_px=4), line_points(10, 10, 30, 20))
    refused = await tool(a, "krita_paint_stroke", stroke)
    report.check(
        "the branch's protection does not loosen, and its protected layer refuses a stroke",
        (code(looser), code(refused)) == ("INVALID_ARGUMENT", "LOCKED_TARGET"),
        f"{code(looser)}, {code(refused)}",
    )


async def _apart(
    report: Report, a: Client, document_id: str, branch_id: str, own: str, hard: dict[str, Any]
) -> None:
    was = await capture(a, document_id, WHOLE, "layer", own)
    brush = brush_args(hard, size_px=6, color=brush_colour((30, 160, 70)))
    painted = await tool(
        a, "krita_paint_stroke", stroke_args(branch_id, own, brush, line_points(*OVER_BASE))
    )
    branch = await capture(a, branch_id, WHOLE, "layer", own)
    source = await capture(a, document_id, WHOLE, "layer", own)
    report.check(
        "a stroke on the branch changes the branch's layer, not the source's",
        painted.get("status") == "completed"
        and differs(branch, was) != ""
        and differs(source, was) == "",
        f"{code(painted)}; branch {differs(branch, was) or 'unchanged'}; source "
        f"{differs(source, was) or 'unchanged'}",
    )


async def _compared(
    report: Report,
    a: Client,
    document_id: str,
    baseline_id: str,
    result: dict[str, Any],
    at_duplicate: np.ndarray | None,
    held: Path,
) -> None:
    sources = (
        _source(document_id, baseline_id),
        _source(result["new_document_id"], result["baseline_id"]),
    )
    rendered = await tool(a, "krita_preview_render", _render(*sources))
    sheets = (rendered.get("data") or {}).get("sheets") or []
    columns = sheets[0]["columns"] if sheets else []
    opened_as = next(
        (
            index
            for index, column in enumerate(columns)
            if column["document_id"] == result["new_document_id"] and column["state"] == "as_opened"
        ),
        None,
    )
    cell = None if opened_as is None else sheet_cell(sheets[0], opened_as)
    report.check(
        "one preview shows the source and the branch, each beside its own baseline, and the "
        "branch as opened is the source as it was duplicated",
        rendered.get("status") == "completed"
        and _held(held, baseline_id)
        and _held(held, result["baseline_id"])
        and differs(cell, at_duplicate) == "",
        f"{code(rendered)}; {differs(cell, at_duplicate)}",
    )


async def _refusals(report: Report, a: Client, document_id: str, folder: Path, taken: Path) -> None:
    before = file_sha256(taken)
    codes = [
        code(await tool(a, TOOL, duplicate_args(document_id, path)))
        for path in (taken, UNWRITABLE / "x.kra", folder / "x.ora")
    ]
    report.check(
        "a duplicate to an existing path, outside the roots or to an .ora is refused, and the "
        "file stays",
        codes == ["FILE_EXISTS", "PATH_NOT_ALLOWED", "UNSUPPORTED_CAPABILITY"]
        and file_sha256(taken) == before
        and not (folder / "x.ora").exists(),
        ", ".join(str(found) for found in codes),
    )


async def _source_closed(
    report: Report, a: Client, document_id: str, folder: Path, held: Path, open_ids: set[str]
) -> None:
    got = await duplicate(a, document_id, folder / "second.kra")
    result = got.get("data") or {}
    second = result.get("new_document_id")
    if not second:
        report.check("closing the source leaves a branch's baseline", False, str(code(got)))
        return
    open_ids.add(second)
    try:
        first = await tool(
            a, "krita_preview_render", _render(_source(second, result["baseline_id"]))
        )
        closed = await _closed(a, open_ids, document_id)
        again = await tool(
            a, "krita_preview_render", _render(_source(second, result["baseline_id"]))
        )
        report.check(
            "closing the source leaves a branch's baseline, which serves on",
            first.get("status") == closed.get("status") == again.get("status") == "completed"
            and _held(held, result["baseline_id"]),
            f"{code(first)}, {code(closed)}, {code(again)}",
        )
    finally:
        await _closed(a, open_ids, second)


async def _created(report: Report, a: Client, folder: Path, held: Path) -> None:
    arguments = create_args("branch source", size_px=[fixtures.WIDTH, fixtures.HEIGHT])
    created = await tool(a, "krita_document_create", arguments)
    document_id = created.get("document_id")
    if not document_id:
        report.check("a created document's branch has no source", False, str(code(created)))
        return
    second = None
    try:
        got = await duplicate(a, document_id, folder / "created.kra")
        result = got.get("data") or {}
        second = result.get("new_document_id")
        rendered = (
            await tool(a, "krita_preview_render", _render(_source(second, result["baseline_id"])))
            if second
            else {}
        )
        report.check(
            "a created document's branch has no source, mode new, and reads its own baseline",
            (
                result.get("source_path"),
                result.get("source_sha256"),
                result.get("baseline_untouched"),
            )
            == (None, None, None)
            and result.get("mode") == "new"
            and rendered.get("status") == "completed"
            and _held(held, result["baseline_id"]),
            f"{code(got)}; {code(rendered) if rendered else 'no render'}",
        )
    finally:
        if second:
            await close(a, second)
        await close(a, document_id)
