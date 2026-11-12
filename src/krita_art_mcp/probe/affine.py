import os
from pathlib import Path
from typing import Any

import numpy as np
from mcp import Client

from krita_art_mcp.bridge_client import BridgeClient
from krita_art_mcp.probe import fixtures
from krita_art_mcp.probe.common import (
    by_name,
    capture,
    capture_composite,
    close,
    guard,
    history_args,
    inspect_data,
    open_working,
    protect,
    undo_labels,
)
from krita_art_mcp.probe.report import Report, code, differs, tool

WHOLE = {"x": 0, "y": 0, "width": fixtures.WIDTH, "height": fixtures.HEIGHT}
EDITABLE = ["probe group", "probe inner", "probe mark", "probe other", "probe masked"]
TOOL = "krita_layer_transform"
# The names Krita gives these steps, as history.LABELS holds them (K54).
LABELS = {"scale": "Scale Layer", "rotate": "Rotate Layer", "shear": "Shear Layer"}
FILTERS = (
    "BSpline",
    "Bell",
    "Bicubic",
    "Bilinear",
    "Hermite",
    "Lanczos3",
    "Mitchell",
    "NearestNeighbor",
)
MARK_RGB = (40, 60, 220)
# The marked layer: 12 x 8 at (8, 8), its centre (14, 12).
MARKED = {"x": 8, "y": 8, "width": 12, "height": 8}


def _args(document_id: str, layer_id: str, operation: dict[str, Any]) -> dict[str, Any]:
    return {"guard": guard(document_id), "layer_id": layer_id, "operation": operation}


def _reason(refused: dict[str, Any]) -> Any:
    return ((refused.get("error") or {}).get("details") or {}).get("reason")


def _outcome(refused: dict[str, Any]) -> Any:
    return ((refused.get("error") or {}).get("details") or {}).get("outcome")


def _outside_same(before: Any, after: Any, rects: list[dict[str, int]]) -> bool:
    # The composite changed nowhere but inside the rects.
    if before is None or after is None:
        return False
    kept = np.ones(before.shape[:2], dtype=bool)
    for rect in rects:
        kept[rect["y"] : rect["y"] + rect["height"], rect["x"] : rect["x"] + rect["width"]] = False
    return bool((before[kept] == after[kept]).all())


def _blue(composite: Any, x: int, y: int) -> bool:
    if composite is None:
        return False
    red, _, blue = (int(value) for value in composite[y, x, :3])
    return blue > 150 and red < 120


async def run(report: Report, a: Client, client: BridgeClient, folder: Path, harness: Path) -> None:
    ora = Path(os.path.realpath(folder)) / "affine.ora"
    fixtures.write_ora(ora, fixtures.affine_stack())
    opened = await open_working(a, ora, harness, "affine", editable_layer_names=EDITABLE)
    document_id = opened.get("document_id")
    if opened.get("status") != "completed" or not document_id:
        report.check(
            "the scale, rotate and shear checks' working copy opens",
            False,
            str(opened.get("error")),
        )
        return
    try:
        names = {name: layer["id"] for name, layer in by_name(opened["data"]["layers"]).items()}
        kept = await capture(a, document_id, WHOLE, "layer", names["probe base"])
        await _scale(report, a, client, document_id, names)
        await _rotate(report, a, client, document_id, names)
        await _shear(report, a, client, document_id, names)
        await _group(report, a, document_id, names)
        await _filters(report, a, document_id, names)
        await _order(report, a, document_id, names)
        await _refusals(report, a, client, document_id, names)
        await _kra(report, a, document_id, names, folder)
        # Protection seals history, so the checks that undo come first.
        await _leak(report, a, document_id, names)
        now = await capture(a, document_id, WHOLE, "layer", names["probe base"])
        report.check(
            "the protected base's own bytes are unchanged through every scale, rotate and shear "
            "check",
            now is not None and not differs(now, kept),
            differs(now, kept) or "same",
        )
    finally:
        await close(a, document_id)


async def _undone_and_redone(
    a: Client, document_id: str, start: Any, after: Any
) -> tuple[bool, str]:
    # Undo, redo, undo: each confirmed, and the composite back as it was each time.
    undone = await tool(a, "krita_history_step", history_args(document_id, "undo"))
    back = await capture_composite(a, document_id)
    redone = await tool(a, "krita_history_step", history_args(document_id, "redo"))
    again = await capture_composite(a, document_id)
    last = await tool(a, "krita_history_step", history_args(document_id, "undo"))
    held = (
        all((one.get("data") or {}).get("verified") is True for one in (undone, redone, last))
        and not differs(back, start)
        and not differs(again, after)
    )
    detail = (
        f"undo {code(undone)} {differs(back, start) or 'as before'}, redo {code(redone)} "
        f"{differs(again, after) or 'as after'}, undo {code(last)}"
    )
    return held, detail


async def _scale(
    report: Report, a: Client, client: BridgeClient, document_id: str, names: dict[str, str]
) -> None:
    start = await capture_composite(a, document_id)
    scaled = await tool(
        a, TOOL, _args(document_id, names["probe mark"], {"type": "scale", "size_px": [24, 16]})
    )
    data = scaled.get("data") or {}
    after = await capture_composite(a, document_id)
    undo, _ = undo_labels(client, document_id)
    grown = {"x": 2, "y": 4, "width": 24, "height": 16}
    history, detail = await _undone_and_redone(a, document_id, start, after)
    report.check(
        "a scale resamples a layer to the size asked about its bounds' centre, Bicubic by "
        "default, in one step named Scale Layer that history undoes and redoes, confirmed",
        scaled.get("status") == "completed"
        and data.get("undo_steps") == 1
        and data.get("filter") == "Bicubic"
        and data.get("pivot_px") == [14, 12]
        and data.get("bounds_after_px") == grown
        and (data.get("verification") or {}).get("mode") == "full"
        and undo == LABELS["scale"]
        and _outside_same(start, after, [grown])
        and history,
        f"{code(scaled)}, bounds {data.get('bounds_after_px')}, label {undo!r}, {detail}",
    )


async def _rotate(
    report: Report, a: Client, client: BridgeClient, document_id: str, names: dict[str, str]
) -> None:
    start = await capture_composite(a, document_id)
    turned = await tool(
        a, TOOL, _args(document_id, names["probe mark"], {"type": "rotate", "degrees": 90})
    )
    data = turned.get("data") or {}
    after = await capture_composite(a, document_id)
    undo, _ = undo_labels(client, document_id)
    upright = {"x": 10, "y": 6, "width": 8, "height": 12}
    history, detail = await _undone_and_redone(a, document_id, start, after)
    report.check(
        "a rotate of 90 degrees turns a layer clockwise about its bounds' centre, its top-left "
        "marker to the top right, in one step named Rotate Layer that history undoes and redoes",
        turned.get("status") == "completed"
        and data.get("filter") == "Bicubic"
        and data.get("bounds_after_px") == upright
        and _blue(after, 16, 6)
        and _blue(after, 17, 7)
        and undo == LABELS["rotate"]
        and _outside_same(start, after, [MARKED, upright])
        and history,
        f"{code(turned)}, bounds {data.get('bounds_after_px')}, label {undo!r}, {detail}",
    )


async def _shear(
    report: Report, a: Client, client: BridgeClient, document_id: str, names: dict[str, str]
) -> None:
    # A positive x shear moves the rows above the centre left, the top-left marker with them.
    start = await capture_composite(a, document_id)
    sheared = await tool(
        a, TOOL, _args(document_id, names["probe mark"], {"type": "shear", "degrees": [20, 0]})
    )
    data = sheared.get("data") or {}
    after = await capture_composite(a, document_id)
    undo, _ = undo_labels(client, document_id)
    bounds = data.get("bounds_after_px") or {}
    history, detail = await _undone_and_redone(a, document_id, start, after)
    report.check(
        "a shear of 20 degrees on x moves the rows above a layer's centre left and those below it "
        "right, Bilinear, in one step named Shear Layer that history undoes and redoes",
        sheared.get("status") == "completed"
        and data.get("filter") == "Bilinear"
        and bounds.get("y") == 8
        and bounds.get("height") == 8
        and bounds.get("x", 8) < 8
        and bounds.get("x", 0) + bounds.get("width", 0) > 20
        and _blue(after, 7, 8)
        and undo == LABELS["shear"]
        and _outside_same(start, after, [bounds or MARKED])
        and history,
        f"{code(sheared)}, bounds {bounds}, label {undo!r}, {detail}",
    )


async def _group(report: Report, a: Client, document_id: str, names: dict[str, str]) -> None:
    group = names["probe group"]
    scaled = await tool(
        a,
        TOOL,
        _args(
            document_id, group, {"type": "scale", "size_px": [16, 12], "filter": "NearestNeighbor"}
        ),
    )
    data = scaled.get("data") or {}
    layers = by_name((await inspect_data(a, document_id)).get("layers") or [])
    inner = (layers.get("probe inner") or {}).get("bounds_px")
    undone = await tool(a, "krita_history_step", history_args(document_id, "undo"))
    report.check(
        "a group is scaled with the layer it holds about the group's centre, in one step history "
        "undoes",
        scaled.get("status") == "completed"
        and data.get("pivot_px") == [44, 33]
        and inner == {"x": 36, "y": 27, "width": 16, "height": 12}
        and (undone.get("data") or {}).get("verified") is True,
        f"{code(scaled)}, inner {inner}, undo {code(undone)}",
    )


async def _filters(report: Report, a: Client, document_id: str, names: dict[str, str]) -> None:
    # Each is Krita's own: the bridge refuses a name Krita does not list.
    found = {}
    for name in FILTERS:
        operation = {"type": "scale", "size_px": [18, 12], "filter": name}
        scaled = await tool(a, TOOL, _args(document_id, names["probe mark"], operation))
        undone = await tool(a, "krita_history_step", history_args(document_id, "undo"))
        found[name] = (
            code(scaled) or (scaled.get("data") or {}).get("filter"),
            (undone.get("data") or {}).get("verified"),
        )
    report.check(
        "each of Krita's eight filters scales a layer, and each scale is undone",
        all(found[name] == (name, True) for name in FILTERS),
        ", ".join(f"{name}: {result}" for name, result in found.items()),
    )


async def _order(report: Report, a: Client, document_id: str, names: dict[str, str]) -> None:
    # Only Krita's order, x then y, changes the marked layer's size under this shear.
    operation = {"type": "shear", "degrees": [-4, 3.6]}
    sheared = await tool(a, TOOL, _args(document_id, names["probe mark"], operation))
    undone = await tool(a, "krita_history_step", history_args(document_id, "undo"))
    bounds = (sheared.get("data") or {}).get("bounds_after_px")
    report.check(
        "a shear that keeps its size only under another order is made by Krita, as the bridge "
        "predicts",
        sheared.get("status") == "completed"
        and bounds != MARKED
        and (undone.get("data") or {}).get("verified") is True,
        f"{code(sheared) or bounds}, undo {code(undone)}",
    )


async def _refusals(
    report: Report, a: Client, client: BridgeClient, document_id: str, names: dict[str, str]
) -> None:
    mark = names["probe mark"]
    translated = await tool(
        a, TOOL, _args(document_id, names["probe other"], {"type": "translate", "by_px": [1, 0]})
    )
    moved = await tool(
        a, TOOL, _args(document_id, names["probe other"], {"type": "scale", "size_px": [12, 8]})
    )
    masking = {
        "guard": guard(document_id),
        "parent_id": names["probe masked"],
        "above_id": None,
        "type": "transparency_mask",
        "name": "krita-art-mcp probe mask",
        "coverage": "all",
    }
    masked = await tool(a, "krita_layer_create", masking)
    held = await tool(
        a, TOOL, _args(document_id, names["probe masked"], {"type": "rotate", "degrees": 45})
    )
    base = await tool(
        a, TOOL, _args(document_id, names["probe base"], {"type": "rotate", "degrees": 45})
    )
    same = await tool(a, TOOL, _args(document_id, mark, {"type": "scale", "size_px": [12, 8]}))
    labels = undo_labels(client, document_id)
    tiny = await tool(a, TOOL, _args(document_id, mark, {"type": "shear", "degrees": [0.5, 0]}))
    after = undo_labels(client, document_id)
    found = {
        "translated": (code(moved), _reason(moved)),
        "masked": (code(held), _reason(held)),
        "protected": (code(base), None),
        "same size": (code(same), _reason(same)),
        "tiny shear": (code(tiny), _reason(tiny)),
    }
    report.check(
        "a transform is refused, changing nothing, for a translated layer, a layer holding a "
        "mask, a protected layer, the layer's own size and a shear too small to move an edge",
        translated.get("status") == "completed"
        and masked.get("status") == "completed"
        and found
        == {
            "translated": ("UNSUPPORTED_CAPABILITY", "transform_mask"),
            "masked": ("UNSUPPORTED_CAPABILITY", "node_type"),
            "protected": ("LOCKED_TARGET", None),
            "same size": ("INVALID_ARGUMENT", "no_change"),
            "tiny shear": ("INVALID_ARGUMENT", "no_change"),
        }
        and all(_outcome(one) == "not_applied" for one in (moved, held, base, same, tiny))
        and labels == after,
        ", ".join(f"{name}: {result}" for name, result in found.items()),
    )


async def _kra(
    report: Report, a: Client, document_id: str, names: dict[str, str], folder: Path
) -> None:
    turned = await tool(
        a, TOOL, _args(document_id, names["probe mark"], {"type": "rotate", "degrees": 30})
    )
    path = Path(os.path.realpath(folder)) / "affine.kra"
    arguments = {
        "guard": guard(document_id),
        "path": str(path),
        "overwrite": False,
        "verify_reopen": True,
    }
    saved = await tool(a, "krita_document_save", arguments)
    report.check(
        "a KRA save after a rotate is verified by reopening",
        turned.get("status") == "completed" and saved.get("status") == "completed",
        f"{code(turned)}, {code(saved)}",
    )


async def _leak(report: Report, a: Client, document_id: str, names: dict[str, str]) -> None:
    layers = (await inspect_data(a, document_id)).get("layers") or []
    protected = [layer for layer in layers if layer["protected"]]
    mask = {"rect": {"x": 0, "y": 0, "width": 32, "height": 24}}
    protection = await protect(a, document_id, protected, mask)
    before = await capture_composite(a, document_id)
    operation = {"type": "scale", "size_px": [40, 30], "filter": "Bicubic"}
    refused = await tool(a, TOOL, _args(document_id, names["probe mark"], operation))
    details = (refused.get("error") or {}).get("details", {})
    after = await capture_composite(a, document_id)
    report.check(
        "a scale of the layer the KRA check turned, which leaves colour under alpha 0 past its "
        "bounds, that grows paint past the allowed mask is refused, undone and confirmed",
        protection.get("status") == "completed"
        and code(refused) == "PROTECTED_REGION_CHANGED"
        and details.get("rolled_back") is True
        and details.get("rollback_verified") is True
        and details.get("outcome") == "not_applied"
        and not differs(after, before),
        f"{code(protection)}, {code(refused)}, composite {differs(after, before) or 'as before'}",
    )
