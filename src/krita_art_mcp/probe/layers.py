import os
from pathlib import Path
from typing import Any

import numpy as np
from mcp import Client

from krita_art_mcp.bridge_client import BridgeClient, Done
from krita_art_mcp.probe import fixtures
from krita_art_mcp.probe.common import (
    brush_args,
    brush_colour,
    by_name,
    capture,
    capture_composite,
    capture_selection,
    close,
    guard,
    harness_call,
    history_args,
    inspect_data,
    line_points,
    open_working,
    protect,
    remove_args,
    reorder_args,
    select,
    stroke_args,
)
from krita_art_mcp.probe.report import Report, code, differs, tool

WHOLE = {"x": 0, "y": 0, "width": fixtures.WIDTH, "height": fixtures.HEIGHT}
EDITABLE = ["probe left", "probe right", "probe group", "probe inner"]
ADD, REMOVE = "Add Layer", "Remove Layer"


async def run(
    report: Report, a: Client, client: BridgeClient, folder: Path, harness: Path, hard: Any
) -> None:
    # Inside the paint stage, whose brush state is written back after it.
    ora = Path(os.path.realpath(folder)) / "layers.ora"
    fixtures.write_ora(ora, fixtures.layer_stack())
    opened = await open_working(a, ora, harness, "layers", editable_layer_names=EDITABLE)
    document_id = opened.get("document_id")
    if opened.get("status") != "completed" or not document_id:
        report.check("the layer checks' working copy opens", False, str(opened.get("error")))
        return
    try:
        data = opened["data"]
        names = {name: layer["id"] for name, layer in by_name(data["layers"]).items()}
        names["root"] = data["root_layer_id"]
        kept = {
            name: await capture(a, document_id, WHOLE, "layer", names[name])
            for name in ("probe base", "probe locked")
        }
        copy = await _duplicate(report, a, client, document_id, names)
        await _group_copy(report, a, document_id, names)
        await _trial(report, a, client, document_id, names, hard)
        await _grouping(report, a, client, document_id, names)
        await _history(report, a, document_id, names, copy)
        await _cleared_selection(report, a, document_id, names)
        # Protection seals history, so the checks that undo come first.
        await _leak(report, a, client, document_id, names)
        await _refusals(report, a, client, document_id, names)
        now = {
            name: await capture(a, document_id, WHOLE, "layer", names[name])
            for name in ("probe base", "probe locked")
        }
        report.check(
            "the protected layers' own bytes are unchanged through every layer check",
            all(now[name] is not None and not differs(now[name], kept[name]) for name in kept),
            ", ".join(f"{name}: {differs(now[name], kept[name]) or 'same'}" for name in kept),
        )
    finally:
        await close(a, document_id)


def _labels(client: BridgeClient, document_id: str) -> tuple[Any, Any]:
    found = harness_call(client, "harness.undo_labels", document_id=document_id)
    if not isinstance(found, Done):
        return None, None
    return found.result.get("undo"), found.result.get("redo")


async def _layers(a: Client, document_id: str) -> dict[str, dict[str, Any]]:
    found = (await inspect_data(a, document_id)).get("layers") or []
    return {layer["id"]: layer for layer in found}


def _duplicate_args(document_id: str, layer_id: str, name: str) -> dict[str, Any]:
    return {"guard": guard(document_id), "layer_id": layer_id, "name": name}


def _shown(document_id: str, layer_id: str, visible: bool) -> dict[str, Any]:
    return {
        "guard": guard(document_id),
        "layer_id": layer_id,
        "properties": {"visible": visible},
        "verify": "region",
    }


async def _duplicate(
    report: Report, a: Client, client: BridgeClient, document_id: str, names: dict[str, str]
) -> str | None:
    base = names["probe base"]
    before = await capture_composite(a, document_id)
    made = await tool(a, "krita_layer_duplicate", _duplicate_args(document_id, base, "base trial"))
    result = made.get("data") or {}
    copy = result.get("layer_id")
    undo, _ = _labels(client, document_id)
    after = await capture_composite(a, document_id)
    layers = await _layers(a, document_id)
    mine = layers.get(copy or "", {})
    report.check(
        "a protected layer's copy is hidden, unprotected and directly above it, derived from it; "
        "the composite is unchanged, and Krita's step reads Add Layer",
        made.get("status") == "completed"
        and result.get("derived_from") == base
        and result.get("id_map") == {base: copy}
        and mine.get("visible") is False
        and mine.get("protected") is False
        and mine.get("parent_id") == layers[base]["parent_id"]
        and mine.get("order") == layers[base]["order"] + 1
        and layers[base]["protected"] is True
        and undo == ADD
        and before is not None
        and not differs(after, before),
        f"{code(made)}, copy {mine.get('visible')}/{mine.get('protected')}, undo {undo!r}, "
        f"composite {differs(after, before) or 'as before'}",
    )
    return copy if isinstance(copy, str) else None


async def _group_copy(report: Report, a: Client, document_id: str, names: dict[str, str]) -> None:
    inner, group = names["probe inner"], names["probe group"]
    # A mask over half of the inner layer, from a selection.
    await select(
        a, document_id, {"type": "rect", "rect": {"x": 20, "y": 18, "width": 8, "height": 12}}
    )
    made = await tool(
        a,
        "krita_layer_create",
        {
            "guard": guard(document_id),
            "parent_id": inner,
            "above_id": None,
            "type": "transparency_mask",
            "name": "probe soft",
            "coverage": "selection",
        },
    )
    await select(a, document_id, {"type": "none"})
    mask = (made.get("data") or {}).get("layer_id")
    names["probe soft"] = mask or ""
    copied = await tool(
        a, "krita_layer_duplicate", _duplicate_args(document_id, group, "group trial")
    )
    id_map = (copied.get("data") or {}).get("id_map") or {}
    layers = await _layers(a, document_id)
    copies = [id_map.get(one) for one in (group, inner, mask)]
    source_mask = await capture(a, document_id, WHOLE, "mask", mask) if mask else None
    copy_mask = await capture(a, document_id, WHOLE, "mask", copies[2]) if copies[2] else None
    source_layer = await capture(a, document_id, WHOLE, "layer", inner)
    copy_layer = await capture(a, document_id, WHOLE, "layer", copies[1]) if copies[1] else None
    report.check(
        "a group's copy maps every node it holds, its mask included; the copies are unprotected "
        "and hold the source's bytes",
        copied.get("status") == "completed"
        and len(id_map) == 3
        and all(one in layers and layers[one]["protected"] is False for one in copies if one)
        and None not in copies
        and layers[copies[1] or ""]["parent_id"] == copies[0]
        and layers[copies[2] or ""]["parent_id"] == copies[1]
        and source_mask is not None
        and int(np.count_nonzero(source_mask)) > 0
        and not differs(copy_mask, source_mask)
        and source_layer is not None
        and not differs(copy_layer, source_layer),
        f"{code(made)}, {code(copied)}, {len(id_map)} mapped, "
        f"mask {differs(copy_mask, source_mask) or 'same'}, "
        f"layer {differs(copy_layer, source_layer) or 'same'}",
    )


async def _trial(
    report: Report,
    a: Client,
    client: BridgeClient,
    document_id: str,
    names: dict[str, str],
    hard: Any,
) -> None:
    left = names["probe left"]
    start = await capture_composite(a, document_id)
    source = await capture(a, document_id, WHOLE, "layer", left)
    made = await tool(a, "krita_layer_duplicate", _duplicate_args(document_id, left, "left trial"))
    copy = (made.get("data") or {}).get("layer_id") or ""
    brush = brush_args(hard, size_px=6, color=brush_colour((40, 200, 90)))
    stroke = await tool(
        a,
        "krita_paint_stroke",
        stroke_args(document_id, copy, brush, line_points(8, 12, 22, 12), verify="full"),
    )
    source_after = await capture(a, document_id, WHOLE, "layer", left)
    painted = await capture(a, document_id, WHOLE, "layer", copy)
    shown = await tool(a, "krita_layer_update", _shown(document_id, copy, True))
    hidden = await tool(a, "krita_layer_update", _shown(document_id, left, False))
    trying = await capture_composite(a, document_id)
    removed = await tool(a, "krita_layer_remove", remove_args(document_id, copy))
    undo, _ = _labels(client, document_id)
    back = await tool(a, "krita_layer_update", _shown(document_id, left, True))
    end = await capture_composite(a, document_id)
    report.check(
        "a trial on a hidden copy leaves its source's pixels alone; shown, it changes the "
        "composite, and removing it, as Remove Layer, brings the composite back",
        [code(one) for one in (made, stroke, shown, hidden, removed, back)] == [None] * 6
        and source is not None
        and not differs(source_after, source)
        and painted is not None
        and differs(painted, source) != ""
        and trying is not None
        and differs(trying, start) != ""
        and (removed.get("data") or {}).get("removed") == [copy]
        and undo == REMOVE
        and not differs(end, start),
        f"{[code(one) for one in (made, stroke, shown, hidden, removed, back)]}, source "
        f"{differs(source_after, source) or 'same'}, undo {undo!r}, "
        f"end {differs(end, start) or 'as at start'}",
    )
    base = names["probe base"]
    refused = await tool(a, "krita_layer_remove", remove_args(document_id, base))
    details = (refused.get("error") or {}).get("details", {})
    report.check(
        "removing a protected layer is LOCKED_TARGET, naming it",
        code(refused) == "LOCKED_TARGET" and details.get("protected_layer_ids") == [base],
        f"{code(refused)}, {details.get('protected_layer_ids')}",
    )


async def _grouping(
    report: Report, a: Client, client: BridgeClient, document_id: str, names: dict[str, str]
) -> None:
    root, left, right = names["root"], names["probe left"], names["probe right"]
    made = await tool(
        a,
        "krita_layer_create",
        {
            "guard": guard(document_id),
            "parent_id": root,
            "above_id": None,
            "type": "group",
            "name": "probe built group",
        },
    )
    group = (made.get("data") or {}).get("layer_id") or ""
    names["probe built group"] = group
    first = await tool(a, "krita_layer_reorder", reorder_args(document_id, left, group, None))
    second = await tool(a, "krita_layer_reorder", reorder_args(document_id, right, group, left))
    undo, _ = _labels(client, document_id)
    layers = await _layers(a, document_id)
    report.check(
        "a group is built by reordering two layers into it, each in two undo steps, the last "
        "Add Layer, with the parents and order exact",
        [code(one) for one in (made, first, second)] == [None] * 3
        and (first.get("data") or {}).get("undo_steps") == 2
        and (second.get("data") or {}).get("effective_order") == [left, right]
        and (layers[left]["parent_id"], layers[right]["parent_id"]) == (group, group)
        and layers[right]["order"] == layers[left]["order"] + 1
        and undo == ADD,
        f"{[code(one) for one in (made, first, second)]}, undo {undo!r}, "
        f"parents {layers[left]['parent_id'] == group}/{layers[right]['parent_id'] == group}",
    )
    inner, moved, mask = names["probe inner"], names["probe group"], names["probe soft"]
    covered = await capture(a, document_id, WHOLE, "mask", mask)
    moving = await tool(a, "krita_layer_reorder", reorder_args(document_id, moved, root, None))
    layers = await _layers(a, document_id)
    kept = await capture(a, document_id, WHOLE, "mask", mask)
    others = [one for one in layers.values() if one["parent_id"] == root and one["id"] != moved]
    report.check(
        "a group holding a masked layer moves whole to the top, in one remove and an add for "
        "each of its three nodes, its mask's coverage kept",
        code(moving) is None
        and (moving.get("data") or {}).get("undo_steps") == 4
        and layers[moved]["parent_id"] == root
        and all(one["order"] < layers[moved]["order"] for one in others)
        and (layers[inner]["parent_id"], layers[mask]["parent_id"]) == (moved, inner)
        and covered is not None
        and not differs(kept, covered),
        f"{code(moving)}, {(moving.get('data') or {}).get('undo_steps')} steps, "
        f"mask {differs(kept, covered) or 'same'}",
    )


async def _history(
    report: Report, a: Client, document_id: str, names: dict[str, str], copy: str | None
) -> None:
    moved, built, inner = names["probe group"], names["probe built group"], names["probe inner"]
    split = await tool(a, "krita_history_step", history_args(document_id, "undo", 1))
    needed = ((split.get("error") or {}).get("details") or {}).get("steps_needed")
    undone = await tool(a, "krita_history_step", history_args(document_id, "undo", 4))
    out = await _layers(a, document_id)
    redone = await tool(a, "krita_history_step", history_args(document_id, "redo", 4))
    again = await _layers(a, document_id)
    report.check(
        "history refuses to split a group's move, then undoes and redoes its four steps together",
        code(split) == "INVALID_ARGUMENT"
        and needed == 4
        and (undone.get("data") or {}).get("steps_applied") == 4
        and out[moved]["order"] < out[built]["order"]
        and out[inner]["parent_id"] == moved
        and (redone.get("data") or {}).get("verified") is True
        and again[moved]["order"] > again[built]["order"],
        f"{code(split)} needing {needed}, {code(undone)}, {code(redone)}",
    )
    removed = await tool(a, "krita_layer_remove", remove_args(document_id, copy or "", "full"))
    gone = copy not in await _layers(a, document_id)
    undone = await tool(a, "krita_history_step", history_args(document_id, "undo", 1))
    back = copy in await _layers(a, document_id)
    made = await tool(
        a,
        "krita_layer_duplicate",
        _duplicate_args(document_id, names["probe right"], "right trial"),
    )
    duplicate = (made.get("data") or {}).get("layer_id")
    dropped = await tool(a, "krita_history_step", history_args(document_id, "undo", 1))
    after = duplicate not in await _layers(a, document_id)
    report.check(
        "history undoes a removal, the same id coming back, and a duplicate",
        [code(one) for one in (removed, undone, made, dropped)] == [None] * 4
        and gone
        and back
        and after,
        f"{[code(one) for one in (removed, undone, made, dropped)]}, gone {gone}, back {back}, "
        f"copy undone {after}",
    )


async def _cleared_selection(
    report: Report, a: Client, document_id: str, names: dict[str, str]
) -> None:
    # The global selection's mask under the root, a layer added above it, then the clear undone.
    chosen = await select(a, document_id, {"type": "all"})
    made = await tool(
        a,
        "krita_layer_create",
        {
            "guard": guard(document_id),
            "parent_id": names["root"],
            "above_id": None,
            "type": "paint",
            "name": "probe above the mask",
        },
    )
    cleared = await select(a, document_id, {"type": "none"})
    undone = await tool(a, "krita_history_step", history_args(document_id, "undo", 1))
    restored = await capture_selection(a, document_id)
    redone = await tool(a, "krita_history_step", history_args(document_id, "redo", 1))
    report.check(
        "a selection cleared under a layer added above its mask is undone and redone, confirmed",
        [code(one) for one in (chosen, made, cleared)] == [None] * 3
        and (undone.get("data") or {}).get("verified") is True
        and restored is not None
        and int(np.count_nonzero(restored)) == fixtures.WIDTH * fixtures.HEIGHT
        and (redone.get("data") or {}).get("verified") is True,
        f"{code(undone)}, {code(redone)}",
    )


async def _leak(
    report: Report, a: Client, client: BridgeClient, document_id: str, names: dict[str, str]
) -> None:
    moved, root, base = names["probe group"], names["root"], names["probe base"]
    layers = list((await _layers(a, document_id)).values())
    protected = [layer for layer in layers if layer["protected"]]
    # Only the right half may change. Moved down under the built group, the inner layer's masked
    # strip goes under the left layer, at x 20 to 27.
    mask = {"rect": {"x": 32, "y": 0, "width": 32, "height": fixtures.HEIGHT}}
    protection = await protect(a, document_id, protected, mask)
    before = await capture_composite(a, document_id)
    tree = await _layers(a, document_id)
    refused = await tool(a, "krita_layer_reorder", reorder_args(document_id, moved, root, base))
    details = (refused.get("error") or {}).get("details", {})
    checked = details.get("verification") or {}
    after = await capture_composite(a, document_id)
    now = await _layers(a, document_id)
    _, redo = _labels(client, document_id)
    again = await tool(a, "krita_history_step", history_args(document_id, "redo", 1))
    report.check(
        "a group's move that changes the composite outside the allowed mask is refused, its four "
        "steps undone and confirmed; Krita offers the redo and history refuses it",
        protection.get("status") == "completed"
        and code(refused) == "PROTECTED_REGION_CHANGED"
        and details.get("rolled_back") is True
        and details.get("rollback_verified") is True
        and checked.get("changed_outside_px", 0) > 0
        and not differs(after, before)
        and now == tree
        and redo == REMOVE
        and code(again) == "INVALID_ARGUMENT",
        f"{code(protection)}, {code(refused)}, {checked.get('changed_outside_px')} px outside, "
        f"composite {differs(after, before) or 'as before'}, tree same {now == tree}, "
        f"redo {redo!r}, history {code(again)}",
    )


async def _refusals(
    report: Report, a: Client, client: BridgeClient, document_id: str, names: dict[str, str]
) -> None:
    group, right = names["probe group"], names["probe right"]
    made = await tool(
        a,
        "krita_layer_create",
        {
            "guard": guard(document_id),
            "parent_id": group,
            "above_id": None,
            "type": "group",
            "name": "probe nested",
        },
    )
    nested = (made.get("data") or {}).get("layer_id")
    inside = await tool(
        a, "krita_layer_reorder", reorder_args(document_id, group, nested or "", None)
    )
    inside_details = (inside.get("error") or {}).get("details", {})
    report.check(
        "a group moved into its own subtree is refused, naming the parent",
        code(inside) == "INVALID_ARGUMENT" and inside_details.get("parent_id") == nested,
        f"{code(made)}, {code(inside)}, {inside_details}",
    )
    # Last: the fixture node seals history.
    added = harness_call(
        client, "harness.add_node", document_id=document_id, kind="clone_layer", layer_id=right
    )
    clone = added.result.get("node_id") if isinstance(added, Done) else None
    removal = await tool(a, "krita_layer_remove", remove_args(document_id, right, "full"))
    move = await tool(
        a, "krita_layer_reorder", reorder_args(document_id, right, names["root"], None)
    )
    found = [((one.get("error") or {}).get("details") or {}) for one in (removal, move)]
    report.check(
        "removing or moving a layer a clone layer shows is refused as clone_source, naming the "
        "clone",
        clone is not None
        and [code(one) for one in (removal, move)] == ["UNSUPPORTED_CAPABILITY"] * 2
        and all(
            one.get("reason") == "clone_source" and one.get("clone_ids") == [clone] for one in found
        ),
        f"{[code(one) for one in (removal, move)]}, {found}",
    )
