import asyncio
import os
import statistics
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import numpy as np
from mcp import Client
from mcp.types import CallToolResult

from krita_art_mcp import paths
from krita_art_mcp.bridge_client import BridgeClient, Done, Outcome, Pending
from krita_art_mcp.paths import Places
from krita_art_mcp.probe import fixtures
from krita_art_mcp.probe.common import (
    add_layer,
    brush_args,
    by_name,
    capture,
    close,
    document_dirty,
    finished,
    guard,
    harness_call,
    held_bounds,
    inspect_data,
    krita_rss_kb,
    line_points,
    megabytes,
    open_args,
    stroke_args,
)
from krita_art_mcp.probe.filling import fill_args
from krita_art_mcp.probe.opening import UNWRITABLE
from krita_art_mcp.probe.report import Report, code, differs, tool
from krita_art_mcp.tools.changes import resolve_update
from krita_art_mcp.tools.documents import SRGB_PROFILE
from krita_art_mcp.tools.painting import stroke_op
from krita_art_mcp.tools.saving import file_sha256

# The fields a KRA brings back for every layer, beside its id; the root's own id is new.
KRA_FIELDS = (
    "parent_id",
    "name",
    "type",
    "order",
    "visible",
    "opacity",
    "blend_mode",
    "locked",
    "alpha_locked",
    "inherit_alpha",
    "offset_px",
    "bounds_px",
    "translation_px",
)
SAVED_NAME = "krita-art-mcp probe saved"
CLIP_NAME = "krita-art-mcp probe clip"
SAVE_LIMIT_S = 600.0
# H4's long save: gradient quarter-canvas layers on an 8k canvas, about 5 s with a 2.6 s silence
# while Krita exports, inside which the paint call's short waits time out.
LONG_SIZE = 8192
LONG_LAYERS = 8
LONG_SIDE = 4096
# The health poller's pace and patience, and how soon the bridge must answer after the save.
POLL_S = 0.1
POLL_TIMEOUT_S = 120.0
RECOVERY_S = 1.0
# Sent this long after the save starts, the paint call lands while Krita exports.
PAINT_DELAY_S = 0.5
# The paint client's waits, so the call and its retry both time out inside the export's silence.
PAINT_BUDGET_S = 1.0
RETRY_BUDGET_S = 0.3
PAINT_POLL_S = 0.2
# A grouped case where the save's recompose moves colour under alpha 0, rebuilt from its recipe:
# a transparent canvas, a group holding one paint layer, three opaque polygon fills; and its
# control, the first fill alone on a layer at the root.
RECOMPOSE_PX = (768, 640)
RECOMPOSE_WHOLE = {"x": 0, "y": 0, "width": RECOMPOSE_PX[0], "height": RECOMPOSE_PX[1]}
FILLS: tuple[tuple[tuple[int, int, int], list[list[int]]], ...] = (
    (
        (103, 97, 118),
        [
            [397, 478],
            [423, 452],
            [469, 447],
            [514, 476],
            [527, 513],
            [502, 537],
            [445, 543],
            [409, 521],
        ],
    ),
    ((183, 176, 191), [[403, 478], [426, 458], [467, 454], [508, 478], [489, 499], [445, 507]]),
    (
        (143, 136, 156),
        [
            [403, 478],
            [445, 507],
            [489, 499],
            [508, 478],
            [521, 511],
            [498, 530],
            [447, 536],
            [413, 518],
        ],
    ),
)
# (x, y) of the pixels the case's first report saw change, all under alpha 0.
DRIFT_SEEN = ((402, 500), (402, 501), (402, 502), (402, 503), (521, 493), (521, 494), (521, 519))
# How many changed pixels a MEASURED line lists.
LISTED = 12


def save_args(document_id: str, path: Path, request_id: str | None = None) -> dict[str, Any]:
    return {
        "guard": guard(document_id, request_id),
        "path": str(path),
        "overwrite": False,
        "verify_reopen": True,
    }


def _hidden(folder: Path) -> list[str]:
    return sorted(name for name in os.listdir(folder) if name.startswith("."))


async def save(a: Client, document_id: str, path: Path) -> dict[str, Any]:
    saved, _ = await save_retried(a, document_id, path)
    return saved


async def save_retried(
    a: Client, document_id: str, path: Path
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    # The receipt, and the BUSY refusal it retried after, if any.
    arguments = save_args(document_id, path)
    saved = await finished(a, await tool(a, "krita_document_save", arguments), SAVE_LIMIT_S)
    if code(saved) != "BUSY":
        return saved, None
    # An autosave can hold the document for a moment; the save wrote nothing, so it retries.
    again = await finished(a, await tool(a, "krita_document_save", arguments), SAVE_LIMIT_S)
    return again, saved


async def run(
    report: Report, a: Client, client: BridgeClient, harness: Path, hard: dict[str, Any]
) -> None:
    folder = harness / "saving"
    folder.mkdir(exist_ok=True)
    await _recompose(report, a, folder)
    await _round_trips(report, a, client, folder, hard)
    await _long_save(report, a, client, folder, hard)


async def _recompose(report: Report, a: Client, folder: Path) -> None:
    # Its own folder, so its files never meet the round trips' check for hidden ones.
    own = folder / "recompose"
    own.mkdir(exist_ok=True)
    grouped = await _grouped_case(a, own)
    if isinstance(grouped, str):
        report.check("the grouped recompose case is prepared", False, grouped)
    else:
        _grouped_checks(report, grouped)
    control = await _control_case(a, own)
    if isinstance(control, str):
        report.check("the recompose control is prepared", False, control)
    else:
        _control_check(report, control)


async def _created(a: Client, name: str) -> tuple[str, dict[str, Any]] | str:
    arguments = {
        "name": f"krita-art-mcp probe {name}",
        "size_px": list(RECOMPOSE_PX),
        "color_model": "RGBA",
        "depth": "U8",
        "profile_id": SRGB_PROFILE,
        "background": "transparent",
        "request_id": str(uuid.uuid4()),
    }
    created = await tool(a, "krita_document_create", arguments)
    if created.get("status") != "completed":
        return f"krita_document_create: {code(created)}"
    return created["document_id"], created["data"]


async def _filled(a: Client, document_id: str, layer_id: str, count: int) -> str | None:
    for rgb, points in FILLS[:count]:
        shape = {"type": "polygon", "points": points}
        filled = await tool(
            a, "krita_paint_fill", fill_args(document_id, layer_id, shape, rgb, verify="full")
        )
        if filled.get("status") != "completed":
            return f"krita_paint_fill: {code(filled)}"
    return None


async def _layer_in(
    a: Client, document_id: str, parent_id: str, above_id: str | None, kind: str
) -> str | None:
    arguments = {
        "guard": guard(document_id),
        "parent_id": parent_id,
        "above_id": above_id,
        "type": kind,
        "name": f"krita-art-mcp probe recompose {kind}",
    }
    made = await tool(a, "krita_layer_create", arguments)
    layer_id: str | None = (made.get("data") or {}).get("layer_id")
    return layer_id


async def _grouped_case(a: Client, folder: Path) -> dict[str, Any] | str:
    # Three fills on a layer inside a group; captures of the composite before and after the save,
    # of the layer's own pixels, and of the saved file reopened.
    created = await _created(a, "recompose")
    if isinstance(created, str):
        return created
    document_id, data = created
    target = folder / "grouped.kra"
    try:
        group = await _layer_in(
            a, document_id, data["root_layer_id"], data["initial_layer_id"], "group"
        )
        layer = None if group is None else await _layer_in(a, document_id, group, None, "paint")
        if layer is None:
            return "krita_layer_create made no group, or no layer in it"
        failed = await _filled(a, document_id, layer, len(FILLS))
        if failed is not None:
            return failed
        before = await capture(a, document_id, RECOMPOSE_WHOLE)
        own = await capture(a, document_id, RECOMPOSE_WHOLE, "layer", layer)
        saved, busy = await save_retried(a, document_id, target)
        after = await capture(a, document_id, RECOMPOSE_WHOLE)
    finally:
        await close(a, document_id)
    reopened = None
    if saved.get("status") == "completed":
        opened = await tool(a, "krita_document_open", open_args(target, "read_only"))
        if opened.get("status") == "completed":
            try:
                reopened = await capture(a, opened["document_id"], RECOMPOSE_WHOLE)
            finally:
                await close(a, opened["document_id"])
    return {
        "before": before,
        "after": after,
        "own": own,
        "reopened": reopened,
        "saved": saved,
        "busy": busy,
    }


def _grouped_checks(report: Report, case: dict[str, Any]) -> None:
    before, after, saved = case["before"], case["after"], case["saved"]
    changed = None if before is None or after is None else np.any(before != after, axis=2)
    if changed is None:
        count = shown = 0
        drift = "a capture is missing"
    else:
        count = int(changed.sum())
        hidden = (before[..., 3] == 0) & (after[..., 3] == 0)
        shown = int((changed & ~hidden).sum())
        drift = f"{count} pixels differ, {shown} of them with alpha above 0"
    report.check(
        "a grouped document's captures before and after its save differ, under alpha 0 alone",
        changed is not None and count > 0 and shown == 0,
        drift,
    )
    recompose = (saved.get("data") or {}).get("recompose")
    problems = []
    if saved.get("status") != "completed":
        problems.append(f"the save: {code(saved) or saved.get('status')}")
    elif recompose is None:
        problems.append("the receipt has no recompose")
    elif changed is None:
        problems.append("a capture is missing")
    else:
        expected = {
            "changed_px": count,
            "visible_changed_px": shown,
            "changed_bounds_px": held_bounds(changed[..., None]),
        }
        problems += [
            f"{key} {recompose.get(key)}, where the captures say {value}"
            for key, value in expected.items()
            if recompose.get(key) != value
        ]
    detail = "; ".join(problems) or str(recompose)
    if case["busy"] is not None:
        # A retry's own recompose counts nothing the first attempt's refresh already moved.
        details = (case["busy"].get("error") or {}).get("details") or {}
        detail += f"; after a BUSY retry, whose details held {details.get('recompose')}"
    report.check(
        "the grouped save's recompose counts exactly what its captures before and after it say",
        not problems,
        detail,
    )
    report.check(
        "the grouped document's capture after its save equals the saved file's, reopened, byte "
        "for byte",
        after is not None and case["reopened"] is not None and not differs(case["reopened"], after),
        differs(case["reopened"], after) or "equal",
    )
    if changed is not None:
        _drift_measured(report, changed, before, after, case["own"])


def _drift_measured(
    report: Report,
    changed: np.ndarray,
    before: np.ndarray,
    after: np.ndarray,
    own: np.ndarray | None,
) -> None:
    where = [(int(x), int(y)) for y, x in np.argwhere(changed)]
    seen = sum(point in where for point in DRIFT_SEEN)
    listed = ", ".join(
        f"({x},{y}) {before[y, x].tolist()} to {after[y, x].tolist()}" for x, y in where[:LISTED]
    )
    report.measured(
        "the grouped save's drift: each pixel the save changed, before and after",
        f"{len(where)} pixels, {seen} of the first report's 7 among them: {listed}",
    )
    if own is None:
        report.measured("the grouped layer's own pixels at the drift", "the layer was not read")
        return
    hidden = sum(int(own[y, x, 3]) == 0 and bool(own[y, x, :3].any()) for x, y in where)
    same = sum(own[y, x].tolist() == after[y, x].tolist() for x, y in where)
    pixels = ", ".join(f"({x},{y}) {own[y, x].tolist()}" for x, y in where[:LISTED])
    report.measured(
        "the grouped layer's own pixels at the drift",
        f"{hidden} of {len(where)} hold colour under alpha 0, {same} equal the composite after "
        f"the save: {pixels}",
    )


async def _control_case(a: Client, folder: Path) -> dict[str, Any] | str:
    # The first fill alone on the document's own layer, at the root.
    created = await _created(a, "recompose control")
    if isinstance(created, str):
        return created
    document_id, data = created
    try:
        failed = await _filled(a, document_id, data["initial_layer_id"], 1)
        if failed is not None:
            return failed
        before = await capture(a, document_id, RECOMPOSE_WHOLE)
        saved, busy = await save_retried(a, document_id, folder / "control.kra")
        after = await capture(a, document_id, RECOMPOSE_WHOLE)
    finally:
        await close(a, document_id)
    return {"before": before, "after": after, "saved": saved, "busy": busy}


def _control_check(report: Report, case: dict[str, Any]) -> None:
    before, after, saved = case["before"], case["after"], case["saved"]
    problems = []
    hidden = 0
    if before is None or after is None:
        problems.append("a capture is missing")
    else:
        if differs(after, before):
            problems.append(f"the save changed it: {differs(after, before)}")
        hidden = int(((before[..., 3] == 0) & np.any(before[..., :3] != 0, axis=2)).sum())
        if hidden < 1:
            problems.append("its composite holds no colour under alpha 0")
    recompose = (saved.get("data") or {}).get("recompose")
    zero = {"changed_px": 0, "visible_changed_px": 0, "changed_bounds_px": None}
    if saved.get("status") != "completed":
        problems.append(f"the save: {code(saved) or saved.get('status')}")
    elif recompose is None:
        problems.append("the receipt has no recompose")
    elif recompose != zero:
        problems.append(f"the receipt's recompose is {recompose}")
    if case["busy"] is not None:
        problems.append("the save was retried after a BUSY")
    report.check(
        "an ungrouped one-fill save reports a recompose of 0 while its composite holds colour "
        "under alpha 0",
        not problems,
        "; ".join(problems) or f"{hidden} pixels hold colour under alpha 0",
    )


async def _round_trips(
    report: Report, a: Client, client: BridgeClient, folder: Path, hard: dict[str, Any]
) -> None:
    source = folder / "probe.ora"
    fixtures.write_ora(source, fixtures.probe_stack())
    opened = await tool(
        a, "krita_document_open", open_args(source, "working_copy", folder / "work")
    )
    if opened.get("status") != "completed":
        report.check("the save checks' working copy opens", False, str(opened.get("error")))
        return
    document_id, data = opened["document_id"], opened["data"]
    try:
        ids = await _prepare(a, client, document_id, data, hard)
        if isinstance(ids, str):
            report.check("the save checks' document is prepared", False, ids)
            return
        await _ora(report, a, document_id, folder)
        shape = by_name(data["layers"])["probe shape"]["id"]
        blurred = harness_call(
            client, "harness.add_node", document_id=document_id, kind="filter_mask", layer_id=shape
        )
        painted = await _paint(a, document_id, ids[SAVED_NAME], hard, (34, 6, 50, 14))
        if not isinstance(blurred, Done) or painted is not None:
            report.check("the KRA check's document is prepared", False, f"{blurred}; {painted}")
            return
        await _kra(report, a, document_id, data, folder)
        await _refusals(report, a, document_id, folder)
        await _adjustment(report, a, client, document_id, shape, folder)
        refused = await close(a, document_id, "refuse")
        details = (refused.get("error") or {}).get("details") or {}
        report.check(
            "after a verified save, a filter layer only Krita holds makes refuse refuse the "
            "close, with dirty false and krita_modified true",
            code(refused) == "DOCUMENT_DIRTY"
            and (details.get("dirty"), details.get("krita_modified")) == (False, True),
            f"{code(refused)}: {details}",
        )
    finally:
        await close(a, document_id)


async def _paint(
    a: Client,
    document_id: str,
    layer_id: str,
    hard: dict[str, Any],
    line: tuple[float, float, float, float],
) -> str | None:
    stroke = stroke_args(document_id, layer_id, brush_args(hard, size_px=4), line_points(*line))
    painted = await tool(a, "krita_paint_stroke", stroke)
    return None if painted.get("status") == "completed" else f"krita_paint_stroke: {code(painted)}"


async def _prepare(
    a: Client,
    client: BridgeClient,
    document_id: str,
    data: dict[str, Any],
    hard: dict[str, Any],
) -> dict[str, str] | str:
    # Two layers of the agent's own, one inherit-alpha, each with a stroke; a clone layer, a
    # transform mask, and an active local selection mask, which K46 keeps out of the file.
    ids = {}
    for name in (SAVED_NAME, CLIP_NAME):
        arguments = {
            "guard": guard(document_id),
            "parent_id": data["root_layer_id"],
            "above_id": None,
            "type": "paint",
            "name": name,
        }
        created = await tool(a, "krita_layer_create", arguments)
        if created.get("status") != "completed":
            return f"krita_layer_create: {code(created)}"
        ids[name] = created["data"]["layer_id"]
    clip = {"guard": guard(document_id), "layer_id": ids[CLIP_NAME], "properties": {}}
    clip["properties"]["inherit_alpha"] = True
    updated = await tool(a, "krita_layer_update", clip)
    if updated.get("status") != "completed":
        return f"krita_layer_update: {code(updated)}"
    for name, line in ((SAVED_NAME, (6, 6, 30, 20)), (CLIP_NAME, (4, 42, 60, 44))):
        failed = await _paint(a, document_id, ids[name], hard, line)
        if failed is not None:
            return failed
    layers = by_name(data["layers"])
    shape, base = layers["probe shape"]["id"], layers["probe base"]["id"]
    rect = {"x": 0, "y": 0, "width": 30, "height": 30}
    for op, args in (
        ("harness.add_node", {"kind": "clone_layer", "layer_id": shape}),
        ("harness.add_node", {"kind": "transform_mask", "layer_id": base}),
        ("harness.select_mask", {"layer_id": base, "rect": rect}),
    ):
        outcome = harness_call(client, op, document_id=document_id, **args)
        if not isinstance(outcome, Done):
            return f"{op}: {outcome}"
    return ids


async def _ora(report: Report, a: Client, document_id: str, folder: Path) -> None:
    target = folder / "saved.ora"
    saved = await save(a, document_id, target)
    result = saved.get("data") or {}
    lost = sorted((loss["type"], loss["lost"]) for loss in result.get("expected_losses", []))
    # The fixture's hidden layer is at 50%, 127, which Krita's ORA round trip makes 126.
    expected = [
        ("clone", "type"),
        ("paint", "opacity"),
        ("selection_mask", "node"),
        ("transform_mask", "node"),
    ]
    report.check(
        "an ORA save keeps the composite, lists the masks, the clone and the 50% opacity as "
        "losses, and leaves nothing beside it",
        saved.get("status") == "completed"
        and result.get("composite_preserved") is True
        and result.get("layers_preserved") is False
        and lost == expected
        and not _hidden(folder)
        and await document_dirty(a, document_id) is False,
        f"{code(saved)}: {(saved.get('error') or {}).get('details')}" if code(saved) else str(lost),
    )
    reopened = await tool(a, "krita_document_open", open_args(target, "read_only"))
    back = by_name((reopened.get("data") or {}).get("layers", []))
    report.check(
        "an inherit_alpha layer saved to ORA reads back as inherit-alpha",
        back.get(CLIP_NAME, {}).get("inherit_alpha") is True,
        str(back.get(CLIP_NAME, {}).get("inherit_alpha")),
    )
    if reopened.get("status") == "completed":
        await close(a, reopened["document_id"])


async def _kra(
    report: Report, a: Client, document_id: str, data: dict[str, Any], folder: Path
) -> None:
    target = folder / "saved.kra"
    live = await inspect_data(a, document_id)
    was_dirty = await document_dirty(a, document_id)
    arguments = save_args(document_id, target)
    saved = await finished(a, await tool(a, "krita_document_save", arguments), SAVE_LIMIT_S)
    result = saved.get("data") or {}
    flags = ("reopened_verified", "layers_preserved", "composite_preserved", "baseline_untouched")
    problems = []
    if saved.get("status") != "completed":
        problems.append(f"{code(saved)}: {(saved.get('error') or {}).get('details')}")
    elif not target.exists() or result.get("sha256") != file_sha256(target):
        problems.append("the file at the path is not the one the receipt names")
    elif [result[flag] for flag in flags] != [True] * 4 or result["expected_losses"] != []:
        problems.append(f"the receipt says {result}")
    if _hidden(folder):
        problems.append(f"left beside it: {_hidden(folder)}")
    if (was_dirty, await document_dirty(a, document_id)) != (True, False):
        problems.append(f"dirty went from {was_dirty} to {await document_dirty(a, document_id)}")
    if file_sha256(Path(data["path"])) != data["source_sha256"]:
        problems.append("the working copy's file changed")
    report.check(
        "a KRA save of a dirty working copy lands verified: every flag true, no losses, nothing "
        "beside it, dirty cleared, the working copy's file untouched",
        not problems,
        "; ".join(problems),
    )
    files = sorted(os.listdir(folder))
    again = await tool(a, "krita_document_save", arguments)
    report.check(
        "a retried save returns the original receipt and writes nothing new",
        again == saved and sorted(os.listdir(folder)) == files,
    )
    reopened = await tool(a, "krita_document_open", open_args(target, "read_only"))
    back = (
        await inspect_data(a, reopened["document_id"])
        if reopened.get("status") == "completed"
        else {}
    )
    differences = kra_differences(live, back)
    report.check(
        "the saved KRA, opened read-only, keeps every layer id and every compared field, masks "
        "and the selection included",
        bool(back) and not differences,
        "; ".join(differences[:5]) or f"{len(back.get('layers', []))} layers",
    )
    if reopened.get("status") == "completed":
        refused = await tool(
            a, "krita_document_save", save_args(reopened["document_id"], folder / "copy.kra")
        )
        report.check(
            "a read-only document is refused a save",
            code(refused) == "DOCUMENT_READ_ONLY" and not (folder / "copy.kra").exists(),
            str(code(refused)),
        )
        await close(a, reopened["document_id"])


def kra_differences(live: dict[str, Any], back: dict[str, Any]) -> list[str]:
    roots = (live.get("root_layer_id"), back.get("root_layer_id"))
    found = {layer["id"]: layer for layer in back.get("layers", [])}
    differences = []
    for layer in live.get("layers", []):
        other = found.pop(layer["id"], None)
        if other is None:
            differences.append(f"{layer['name']} is missing")
            continue
        for field in KRA_FIELDS:
            was, now = layer[field], other[field]
            if field == "parent_id" and was in roots and now in roots:
                continue
            if was != now:
                differences.append(f"{layer['name']} {field}: {was} became {now}")
    differences += [f"{layer['name']} is new" for layer in found.values()]
    return differences


async def _refusals(report: Report, a: Client, document_id: str, folder: Path) -> None:
    taken = folder / "saved.kra"
    if not taken.exists():
        report.check("the refusals have a saved KRA to try to overwrite", False)
        return
    before = file_sha256(taken)
    codes = [
        code(await tool(a, "krita_document_save", save_args(document_id, path)))
        for path in (taken, UNWRITABLE / "x.kra", folder / "x.png")
    ]
    report.check(
        "an existing path, a path outside the roots and a .png are refused, and the file stays",
        codes == ["FILE_EXISTS", "PATH_NOT_ALLOWED", "UNSUPPORTED_CAPABILITY"]
        and file_sha256(taken) == before
        and not (folder / "x.png").exists(),
        ", ".join(str(found) for found in codes),
    )


async def _adjustment(
    report: Report, a: Client, client: BridgeClient, document_id: str, shape: str, folder: Path
) -> None:
    # ORA drops adjustment layers, and a lost node never excuses a composite difference.
    added = harness_call(
        client, "harness.add_node", document_id=document_id, kind="filter_layer", layer_id=shape
    )
    changed = isinstance(added, Done) and added.result.get("composite_changed") is True
    target = folder / "adjusted.ora"
    refused = await save(a, document_id, target)
    mismatches = (refused.get("error") or {}).get("details", {}).get("mismatches", [])
    report.check(
        "a visible filter layer saved to ORA is SAVE_VERIFY_FAILED on the composite, with nothing "
        "left at the path or beside it",
        changed
        and code(refused) == "SAVE_VERIFY_FAILED"
        and "composite" in {mismatch["field"] for mismatch in mismatches}
        and not target.exists()
        and not _hidden(folder),
        str(code(refused)),
    )


class _Poller:
    # Asks the bridge for its health, one call at a time, and keeps when each was sent and
    # answered, or that it failed.
    def __init__(self) -> None:
        self.calls: list[tuple[float, float | None]] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        client = BridgeClient()
        while not self._stop.is_set():
            sent = time.monotonic()
            answered = client.health(timeout_s=POLL_TIMEOUT_S)
            self.calls.append((sent, time.monotonic() if isinstance(answered, Done) else None))
            time.sleep(POLL_S)

    def __enter__(self) -> "_Poller":
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        self._thread.join(POLL_TIMEOUT_S + 10)


async def _long_save(
    report: Report, a: Client, client: BridgeClient, folder: Path, hard: dict[str, Any]
) -> None:
    source = folder / "long.ora"
    fixtures.write_sparse_ora(
        source, fixtures.long_save_stack(LONG_LAYERS, LONG_SIDE, LONG_SIZE), LONG_SIZE, LONG_SIZE
    )
    rss_before = krita_rss_kb()
    opened = await finished(
        a,
        await tool(a, "krita_document_open", open_args(source, "working_copy", folder / "work")),
        SAVE_LIMIT_S,
    )
    painted = harness_call(client, "document.create", **_canvas())
    if opened.get("status") != "completed" or not isinstance(painted, Done):
        report.check("H4's documents open", False, f"{opened.get('error')}; {painted}")
        if isinstance(painted, Done):
            harness_call(
                client,
                "document.close",
                document_id=painted.result["document_id"],
                dirty_policy="discard",
            )
        if opened.get("document_id"):
            await close(a, opened["document_id"])
        return
    document_id, paint_id = opened["document_id"], painted.result["document_id"]
    try:
        # A layer of its own, so Krita holds the working copy modified and refuse compares it.
        await add_layer(a, document_id, opened["data"]["root_layer_id"], "h4")
        request_id = str(uuid.uuid4())
        stroke = {
            "guard": {"document_id": paint_id, "request_id": request_id},
            "layer_id": painted.result["initial_layer_id"],
            "brush": brush_args(hard, size_px=4),
            "points": line_points(4, 4, 40, 20),
        }
        op_args = stroke_op(stroke)
        assert not isinstance(op_args, CallToolResult)
        quick = BridgeClient(budget_s=PAINT_BUDGET_S, poll_s=PAINT_POLL_S)

        def paint_twice() -> list[Outcome]:
            first = quick.call("paint.stroke", op_args, request_id=request_id)
            again = quick.call(
                "paint.stroke", op_args, request_id=request_id, budget_s=RETRY_BUDGET_S
            )
            return [first, again]

        target = folder / "long.kra"
        with _Poller() as poller:
            started = time.monotonic()
            saving = asyncio.ensure_future(
                tool(a, "krita_document_save", save_args(document_id, target))
            )
            await asyncio.sleep(PAINT_DELAY_S)
            sent = await asyncio.to_thread(paint_twice)
            saved = await finished(a, await saving, SAVE_LIMIT_S)
            ended = time.monotonic()
            took = ended - started
            await asyncio.sleep(2 * RECOVERY_S)
        followed = [client.operation(str(one.operation_id)) for one in sent]
        if isinstance(followed[0], Done):
            # Its images cross as transfer files, which the tool's resolver takes; the probe sent
            # the stroke itself, so it resolves it too, into the harness folder.
            resolve_update(Places.under(paths.default_data_dir(), folder / "h4"), followed[0])
        history = (await inspect_data(a, paint_id)).get("history") or {}
        _h4_checks(report, poller.calls, ended, saved, sent, followed, history)
        silences = sorted(
            (answered - sent_at for sent_at, answered in poller.calls if answered is not None),
            reverse=True,
        )
        report.measured(
            f"H4: saving the {LONG_SIZE} x {LONG_SIZE} working copy with {LONG_LAYERS} gradient "
            f"{LONG_SIDE} px layers and an empty one of the agent's",
            f"{took:.1f} s; longest silence {silences[0]:.2f} s, median answer "
            f"{statistics.median(silences) * 1000:.0f} ms; Krita {megabytes(rss_before)} before, "
            f"{megabytes(krita_rss_kb())} after",
        )
        held = (await inspect_data(a, document_id)).get("krita_modified")
        started = time.monotonic()
        closed = await close(a, document_id, "refuse")
        took_close = time.monotonic() - started
        report.measured(
            f"refuse closing the {LONG_SIZE} x {LONG_SIZE} working copy after its verified save, "
            "which reads it again while Krita holds it modified",
            f"{took_close:.1f} s, {code(closed) or 'closed'}; krita_modified {held}",
        )
    finally:
        await close(a, document_id)
        harness_call(client, "document.close", document_id=paint_id, dirty_policy="discard")


def _canvas() -> dict[str, Any]:
    # The paint call's own small document, made by the probe's bridge client, which holds it.
    return {
        "name": "krita-art-mcp probe h4",
        "size_px": [64, 32],
        "color_model": "RGBA",
        "depth": "U8",
        "profile_id": SRGB_PROFILE,
        "background": "transparent",
    }


def _h4_checks(
    report: Report,
    calls: list[tuple[float, float | None]],
    ended: float,
    saved: dict[str, Any],
    sent: list[Outcome],
    followed: list[Outcome],
    history: dict[str, Any],
) -> None:
    report.check(
        "H4: the long save completes, verified",
        saved.get("status") == "completed",
        str(code(saved) or ""),
    )
    lost = sum(answered is None for _, answered in calls)
    after = [answered - sent_at for sent_at, answered in calls if sent_at >= ended and answered]
    report.check(
        "H4: no health call is lost, and the bridge answers within 1 s after the save",
        lost == 0 and bool(after) and max(after) < RECOVERY_S,
        f"{len(calls)} calls, {lost} lost, slowest after the save {max(after) * 1000:.0f} ms"
        if after
        else f"{len(calls)} calls, none after the save",
    )
    queued = all(isinstance(one, Pending) for one in sent)
    ids = {one.operation_id for one in followed}
    done = all(isinstance(one, Done) for one in followed)
    report.check(
        "H4: a paint call queued behind the save and retried under its request_id runs once",
        queued and done and len(ids) == 1 and history.get("undo_available") == 1,
        f"sent {[type(one).__name__ for one in sent]}, followed "
        f"{[type(one).__name__ for one in followed]}, {len(ids)} operation(s), "
        f"{history.get('undo_available')} undo step(s)",
    )
