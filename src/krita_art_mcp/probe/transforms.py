import os
from pathlib import Path
from typing import Any

import numpy as np
from mcp import Client

from krita_art_mcp.bridge_client import BridgeClient, Done
from krita_art_mcp.probe import fixtures
from krita_art_mcp.probe.common import (
    brush_colour,
    by_name,
    capture,
    capture_composite,
    close,
    guard,
    harness_call,
    history_args,
    inspect_data,
    open_working,
    protect,
)
from krita_art_mcp.probe.report import Report, code, differs, tool

WHOLE = {"x": 0, "y": 0, "width": fixtures.WIDTH, "height": fixtures.HEIGHT}
EDITABLE = ["probe paint", "probe group", "probe inner"]
BASE_RGB, PAINT_RGB, INNER_RGB = (200, 180, 30), (220, 40, 60), (40, 200, 90)
FILL_RGB = (30, 60, 220)
TOOL = "krita_layer_transform"
TRANSFORM = "transform_mask"


def _args(document_id: str, layer_id: str, by: list[int]) -> dict[str, Any]:
    return {
        "guard": guard(document_id),
        "layer_id": layer_id,
        "operation": {"type": "translate", "by_px": by},
    }


def _labels(client: BridgeClient, document_id: str) -> tuple[Any, Any]:
    found = harness_call(client, "harness.undo_labels", document_id=document_id)
    if not isinstance(found, Done):
        return None, None
    return found.result.get("undo"), found.result.get("redo")


async def _moved(a: Client, document_id: str) -> dict[str, Any]:
    # Each transform mask's translation, by its layer.
    layers = (await inspect_data(a, document_id)).get("layers") or []
    return {
        layer["parent_id"]: layer["translation_px"]
        for layer in layers
        if layer["type"] == TRANSFORM
    }


def _painted(composite: np.ndarray | None, x: int, y: int, width: int, height: int) -> Any:
    if composite is None:
        return None
    return composite[y : y + height, x : x + width, :3]


def _is(found: Any, rgb: tuple[int, int, int]) -> bool:
    return found is not None and found.size > 0 and bool((found == np.array(rgb)).all())


async def run(report: Report, a: Client, client: BridgeClient, folder: Path, harness: Path) -> None:
    # Inside the paint stage, whose brush state is written back after it.
    ora = Path(os.path.realpath(folder)) / "transforms.ora"
    fixtures.write_ora(ora, fixtures.transform_stack())
    opened = await open_working(a, ora, harness, "transforms", editable_layer_names=EDITABLE)
    document_id = opened.get("document_id")
    if opened.get("status") != "completed" or not document_id:
        report.check("the translate checks' working copy opens", False, str(opened.get("error")))
        return
    try:
        names = {name: layer["id"] for name, layer in by_name(opened["data"]["layers"]).items()}
        kept = await capture(a, document_id, WHOLE, "layer", names["probe base"])
        mask = await _first(report, a, client, document_id, names)
        await _second(report, a, document_id, names, mask)
        await _history(report, a, document_id, names)
        await _fill(report, a, document_id, names)
        await _group(report, a, document_id, names)
        await _no_copy(report, a, document_id, names)
        # Protection seals history, so the checks that undo come first.
        await _leak(report, a, document_id, names)
        await _kra(report, a, document_id, names, mask, folder, harness)
        await _ora(report, a, document_id, folder)
        now = await capture(a, document_id, WHOLE, "layer", names["probe base"])
        report.check(
            "the protected base's own bytes are unchanged through every translate check",
            now is not None and not differs(now, kept),
            differs(now, kept) or "same",
        )
    finally:
        await close(a, document_id)


async def _first(
    report: Report, a: Client, client: BridgeClient, document_id: str, names: dict[str, str]
) -> str | None:
    paint = names["probe paint"]
    before = await capture_composite(a, document_id)
    own = await capture(a, document_id, WHOLE, "layer", paint)
    made = await tool(a, TOOL, _args(document_id, paint, [5, 3]))
    data = made.get("data") or {}
    after = await capture_composite(a, document_id)
    own_after = await capture(a, document_id, WHOLE, "layer", paint)
    undo, _ = _labels(client, document_id)
    expected = None
    if before is not None:
        expected = before.copy()
        expected[8:16, 8:20] = (*BASE_RGB, 255)
        expected[11:19, 13:25] = (*PAINT_RGB, 255)
    report.check(
        "a first translate adds its transform mask in two native undo steps, moves the composite "
        "by exactly the whole pixels asked, and leaves the layer's own pixels",
        made.get("status") == "completed"
        and data.get("created_mask") is True
        and data.get("undo_steps") == 2
        and data.get("translation_px") == [5, 3]
        and (data.get("verification") or {}).get("mode") == "full"
        and undo == ""
        and expected is not None
        and not differs(after, expected)
        and own is not None
        and not differs(own_after, own),
        f"{code(made)}, {data.get('undo_steps')} steps, undo label {undo!r}, composite "
        f"{differs(after, expected) or 'moved exactly'}, own {differs(own_after, own) or 'same'}",
    )
    mask: str | None = data.get("transform_mask_id")
    return mask


async def _second(
    report: Report, a: Client, document_id: str, names: dict[str, str], mask: str | None
) -> None:
    paint = names["probe paint"]
    moved = await tool(a, TOOL, _args(document_id, paint, [-2, 1]))
    data = moved.get("data") or {}
    shown = await _moved(a, document_id)
    report.check(
        "a second translate moves the same mask in one step, and inspect reports its translation",
        moved.get("status") == "completed"
        and data.get("created_mask") is False
        and data.get("transform_mask_id") == mask
        and data.get("undo_steps") == 1
        and data.get("translation_px") == [3, 4]
        and shown.get(paint) == [3, 4],
        f"{code(moved)}, {data.get('undo_steps')} step(s), {data.get('translation_px')}, "
        f"inspect {shown.get(paint)}",
    )


async def _history(report: Report, a: Client, document_id: str, names: dict[str, str]) -> None:
    paint = names["probe paint"]
    one = await tool(a, "krita_history_step", history_args(document_id, "undo", 1))
    first = (await _moved(a, document_id)).get(paint)
    split = await tool(a, "krita_history_step", history_args(document_id, "undo", 1))
    needed = ((split.get("error") or {}).get("details") or {}).get("steps_needed")
    whole = await tool(a, "krita_history_step", history_args(document_id, "undo", 2))
    gone = paint not in await _moved(a, document_id)
    plain = await capture_composite(a, document_id)
    redone = await tool(a, "krita_history_step", history_args(document_id, "redo", 3))
    again = (await _moved(a, document_id)).get(paint)
    report.check(
        "history undoes a later translate alone, refuses to split the first, undoes and redoes "
        "it whole, confirmed",
        (one.get("data") or {}).get("verified") is True
        and first == [5, 3]
        and code(split) == "INVALID_ARGUMENT"
        and needed == 2
        and (whole.get("data") or {}).get("verified") is True
        and gone
        and _is(_painted(plain, 8, 8, 12, 8), PAINT_RGB)
        and (redone.get("data") or {}).get("verified") is True
        and again == [3, 4],
        f"{code(one)} to {first}, split {code(split)} needing {needed}, {code(whole)}, mask gone "
        f"{gone}, {code(redone)} to {again}",
    )


async def _fill(report: Report, a: Client, document_id: str, names: dict[str, str]) -> None:
    # Paint lands where it is aimed in the layer's own pixels, and shows moved.
    paint = names["probe paint"]
    arguments = {
        "guard": guard(document_id),
        "layer_id": paint,
        "shape": {"type": "rect", "rect": {"x": 10, "y": 10, "width": 4, "height": 3}},
        "color": brush_colour(FILL_RGB),
        "opacity": 1,
        "verify": "full",
    }
    region = await tool(
        a, "krita_paint_fill", {**arguments, "guard": guard(document_id), "verify": "region"}
    )
    filled = await tool(a, "krita_paint_fill", arguments)
    after = await capture_composite(a, document_id)
    bounds = (filled.get("data") or {}).get("changed_bounds_px")
    undone = await tool(a, "krita_history_step", history_args(document_id, "undo", 1))
    report.check(
        "a fill on a translated layer needs full scope, lands at its aim in the layer's own "
        "pixels and shows moved by the translation",
        code(region) == "UNSUPPORTED_CAPABILITY"
        and filled.get("status") == "completed"
        and bounds == {"x": 10, "y": 10, "width": 4, "height": 3}
        and _is(_painted(after, 13, 14, 4, 3), FILL_RGB)
        and (undone.get("data") or {}).get("verified") is True,
        f"region {code(region)}, {code(filled)}, bounds {bounds}, shown at 13, 14: "
        f"{_is(_painted(after, 13, 14, 4, 3), FILL_RGB)}, {code(undone)}",
    )


async def _group(report: Report, a: Client, document_id: str, names: dict[str, str]) -> None:
    group = names["probe group"]
    moved = await tool(a, TOOL, _args(document_id, group, [-4, 2]))
    after = await capture_composite(a, document_id)
    undone = await tool(a, "krita_history_step", history_args(document_id, "undo", 2))
    back = await capture_composite(a, document_id)
    report.check(
        "a group is translated with what it holds, and its two steps undone",
        moved.get("status") == "completed"
        and (moved.get("data") or {}).get("created_mask") is True
        and _is(_painted(after, 36, 32, 8, 6), INNER_RGB)
        and _is(_painted(after, 44, 30, 4, 2), BASE_RGB)
        and (undone.get("data") or {}).get("verified") is True
        and _is(_painted(back, 40, 30, 8, 6), INNER_RGB),
        f"{code(moved)}, {code(undone)}",
    )


async def _no_copy(report: Report, a: Client, document_id: str, names: dict[str, str]) -> None:
    # Undoing a copy of a transform mask crashes Krita (K53), so none is made.
    arguments = {"guard": guard(document_id), "layer_id": names["probe paint"], "name": "trial"}
    refused = await tool(a, "krita_layer_duplicate", arguments)
    reason = ((refused.get("error") or {}).get("details") or {}).get("reason")
    report.check(
        "a translated layer is not duplicated",
        code(refused) == "UNSUPPORTED_CAPABILITY" and reason == TRANSFORM,
        f"{code(refused)}, {reason}",
    )


async def _leak(report: Report, a: Client, document_id: str, names: dict[str, str]) -> None:
    paint = names["probe paint"]
    layers = (await inspect_data(a, document_id)).get("layers") or []
    protected = [layer for layer in layers if layer["protected"]]
    mask = {"rect": {"x": 0, "y": 0, "width": 32, "height": fixtures.HEIGHT}}
    protection = await protect(a, document_id, protected, mask)
    before = await capture_composite(a, document_id)
    refused = await tool(a, TOOL, _args(document_id, paint, [30, 0]))
    details = (refused.get("error") or {}).get("details", {})
    after = await capture_composite(a, document_id)
    shown = (await _moved(a, document_id)).get(paint)
    report.check(
        "a translate that moves paint outside the allowed mask is refused, undone and confirmed",
        protection.get("status") == "completed"
        and code(refused) == "PROTECTED_REGION_CHANGED"
        and details.get("rolled_back") is True
        and details.get("rollback_verified") is True
        and details.get("outcome") == "not_applied"
        and not differs(after, before)
        and shown == [3, 4],
        f"{code(protection)}, {code(refused)}, composite {differs(after, before) or 'as before'}, "
        f"translation {shown}",
    )


async def _kra(
    report: Report,
    a: Client,
    document_id: str,
    names: dict[str, str],
    mask: str | None,
    folder: Path,
    harness: Path,
) -> None:
    paint = names["probe paint"]
    path = Path(os.path.realpath(folder)) / "transforms.kra"
    arguments = {
        "guard": guard(document_id),
        "path": str(path),
        "overwrite": False,
        "verify_reopen": True,
    }
    saved = await tool(a, "krita_document_save", arguments)
    editable = [paint, mask] if mask else [paint]
    reopened = await open_working(a, path, harness, "transforms-kra", editable_layer_ids=editable)
    branch = reopened.get("document_id")
    if reopened.get("status") != "completed" or not branch:
        report.check("a translated layer survives a KRA round trip", False, code(reopened) or "")
        return
    try:
        shown = await _moved(a, branch)
        moved = await tool(a, TOOL, _args(branch, paint, [1, 1]))
        data = moved.get("data") or {}
        report.check(
            "a KRA keeps the transform mask, its id and its translation, and a translate there "
            "moves it on",
            saved.get("status") == "completed"
            and shown.get(paint) == [3, 4]
            and data.get("transform_mask_id") == mask
            and data.get("created_mask") is False
            and data.get("translation_px") == [4, 5],
            f"{code(saved)}, reopened at {shown.get(paint)}, {code(moved)} to "
            f"{data.get('translation_px')}",
        )
    finally:
        await close(a, branch)


async def _ora(report: Report, a: Client, document_id: str, folder: Path) -> None:
    # An ORA drops the transform mask, so the reopened composite is not the document's.
    path = Path(os.path.realpath(folder)) / "transforms.ora.out.ora"
    arguments = {
        "guard": guard(document_id),
        "path": str(path),
        "overwrite": False,
        "verify_reopen": True,
    }
    refused = await tool(a, "krita_document_save", arguments)
    details = (refused.get("error") or {}).get("details", {})
    report.check(
        "an ORA save of a translated layer is refused, not passed silently, and leaves no file",
        code(refused) == "SAVE_VERIFY_FAILED"
        and details.get("outcome") == "not_applied"
        and not path.exists(),
        f"{code(refused)}, {details.get('outcome')}, file {path.exists()}",
    )
