import hashlib
import os
import uuid
from pathlib import Path
from typing import Any

import numpy as np
from mcp import Client

from krita_art_mcp import masks
from krita_art_mcp.bridge_client import BridgeClient, Done
from krita_art_mcp.probe import fixtures
from krita_art_mcp.probe.common import (
    by_name,
    capture_composite,
    capture_selection,
    close,
    guard,
    harness_call,
    history_args,
    inspect_data,
    open_args,
)
from krita_art_mcp.probe.report import Report, code, differs, tool
from krita_art_mcp.tools.observe import LIMITS

WIDTH, HEIGHT = fixtures.WIDTH, fixtures.HEIGHT
LIMIT = LIMITS["capture_source_pixels"]
LABEL_TRIALS = 7
CLOSE_CYCLES = 5
ELLIPSE = {"x": 10, "y": 6, "width": 30, "height": 20}
POLYGON: list[list[float]] = [[4.5, 3.25], [50, 8], [30.5, 40.75], [12, 30]]


def _rect(x: int, y: int, width: int, height: int) -> dict[str, Any]:
    return {"x": x, "y": y, "width": width, "height": height}


def _select(document_id: str, shape: dict[str, Any], **changes: Any) -> dict[str, Any]:
    request_id = changes.pop("request_id", None)
    return {
        "guard": guard(document_id, request_id),
        "combine": "replace",
        "shape": shape,
        "feather_px": 0,
        "invert": False,
        **changes,
    }


def _layer(document_id: str, parent_id: str, above_id: str | None, **changes: Any) -> Any:
    return {
        "guard": guard(document_id),
        "parent_id": parent_id,
        "above_id": above_id,
        "type": "paint",
        "name": "krita-art-mcp probe repair",
        **changes,
    }


def _canvas(mask: masks.Mask) -> np.ndarray:
    canvas = np.zeros((HEIGHT, WIDTH), dtype=np.uint8)
    x, y = mask.origin
    height, width = mask.pixels.shape
    canvas[y : y + height, x : x + width] = mask.pixels
    return canvas


def _box(x: int, y: int, width: int, height: int) -> np.ndarray:
    return _canvas(masks.rect(_rect(x, y, width, height), LIMIT))


def undo_labels(client: BridgeClient, document_id: str) -> str:
    read = harness_call(client, "harness.undo_labels", document_id=document_id)
    if not isinstance(read, Done):
        return f"unread ({read})"
    actions = read.result.get("actions") or {}
    raw = {name: (value.get("text"), value.get("enabled")) for name, value in actions.items()}
    return f"undo {read.result['undo']!r}, redo {read.result['redo']!r}; actions {raw}"


async def run(report: Report, a: Client, b: Client, client: BridgeClient, harness: Path) -> None:
    harness = Path(os.path.realpath(harness))
    folder = harness / "changes"
    folder.mkdir(exist_ok=True)
    ora, raster = folder / "changes.ora", folder / "raster.png"
    composite = fixtures.write_ora(ora, fixtures.probe_stack())
    gradient = np.tile(np.arange(0, 240, 16, dtype=np.uint8), (6, 1))
    raster.write_bytes(fixtures.png(gradient))
    await _read_only(report, a, ora, raster)
    opened = await tool(
        a, "krita_document_open", open_args(ora, "working_copy", harness / "work" / "changes")
    )
    if opened.get("status") != "completed":
        report.check("the change checks' working copy opens", False, str(opened.get("error")))
        return
    document_id = opened["document_id"]
    try:
        made = await _layers(report, a, client, document_id, opened["data"], composite)
        await _selections(report, a, client, document_id, raster, gradient)
        await _ledger(report, a, document_id, opened["data"]["root_layer_id"])
        await _retries(report, a, b, document_id)
        await _protection(report, a, document_id, made)
        # Its harness op seals history, so it runs after the checks that undo.
        await _k46(report, a, client, document_id, opened["data"], composite)
        await _label_timing(report, client, document_id)
    finally:
        await close(a, document_id)
    await _close_at_once(report, a, ora, harness)


async def _read_only(report: Report, a: Client, ora: Path, raster: Path) -> None:
    opened = await tool(a, "krita_document_open", open_args(ora, "read_only"))
    document_id = opened.get("document_id")
    if not document_id:
        report.check("the read-only refusals' fixture opens", False, str(opened.get("error")))
        return
    try:
        root = opened["data"]["root_layer_id"]
        protected = [layer["id"] for layer in opened["data"]["layers"]]
        calls = {
            "krita_layer_create": _layer(document_id, root, None),
            "krita_selection_set": _select(document_id, {"type": "all"}),
            "krita_protection_set": {
                "guard": guard(document_id),
                "protected_layer_ids": protected,
                "allowed_change_mask": None,
                "preserve_composite_alpha": True,
                "preserve_canvas": False,
            },
            "krita_history_step": history_args(document_id, "undo"),
            "krita_layer_update": {
                "guard": guard(document_id),
                "layer_id": protected[0],
                "properties": {"opacity": 0.5},
            },
        }
        found = {name: code(await tool(a, name, arguments)) for name, arguments in calls.items()}
        report.check(
            "a read_only document refuses layer_create, selection_set, protection_set, "
            "history_step and layer_update",
            set(found.values()) == {"DOCUMENT_READ_ONLY"},
            ", ".join(f"{name}: {found_code}" for name, found_code in found.items()),
        )
    finally:
        await close(a, document_id)


async def _layers(
    report: Report,
    a: Client,
    client: BridgeClient,
    document_id: str,
    opened: dict[str, Any],
    composite: np.ndarray,
) -> list[str]:
    layers = by_name(opened["layers"])
    root, base = opened["root_layer_id"], layers["probe base"]
    group, shape = layers["probe group"], layers["probe shape"]
    first = await tool(a, "krita_layer_create", _layer(document_id, root, base["id"]))
    report.measured("the undo labels after layer_create", undo_labels(client, document_id))
    second = await tool(
        a, "krita_layer_create", _layer(document_id, group["id"], shape["id"], type="group")
    )
    made = [
        str((first.get("data") or {}).get("layer_id")),
        str((second.get("data") or {}).get("layer_id")),
    ]
    inspected = await inspect_data(a, document_id)
    # Both new layers share a name, so they are found by id.
    entries = {layer["id"]: layer for layer in inspected.get("layers") or []}
    seen = by_name(inspected.get("layers") or [])
    report.measured(
        "the active layer after layer_create",
        "the new one"
        if inspected.get("active_layer_id") == made[1]
        else str(inspected.get("active_layer_id")),
    )
    problems = []
    for content, parent, above, kind in (
        (first, root, base, "paint"),
        (second, group["id"], shape, "group"),
    ):
        entry = entries.get((content.get("data") or {}).get("layer_id", ""))
        sibling = entries.get(above["id"])
        if entry is None or sibling is None:
            problems.append(f"{kind}: {code(content)}")
            continue
        if (entry["parent_id"], entry["type"], entry["protected"], entry["order"]) != (
            parent,
            kind,
            False,
            sibling["order"] + 1,
        ):
            problems.append(f"{kind} placed at {entry['parent_id']}, order {entry['order']}")
    unchanged = {key: value for key, value in group.items() if key != "order"}
    if {key: value for key, value in seen["probe group"].items() if key != "order"} != unchanged:
        problems.append("the protected group changed")
    found = await capture_composite(a, document_id)
    if found is None or differs(found, composite):
        problems.append(f"composite: {differs(found, composite)}")
    listed = (await tool(a, "krita_document_list", {})).get("data") or {}
    dirty = [
        entry["dirty"]
        for entry in listed.get("documents", [])
        if entry["document_id"] == document_id
    ]
    refused = code(await close(a, document_id, "refuse"))
    if dirty != [True] or refused != "DOCUMENT_DIRTY":
        problems.append(f"dirty {dirty}, close {refused}")
    report.check(
        "layer_create adds layers where asked, inside the protected group too, unprotected; the "
        "composite and the group are unchanged and the document is dirty",
        not problems,
        "; ".join(problems),
    )
    return made


async def _selections(
    report: Report,
    a: Client,
    client: BridgeClient,
    document_id: str,
    raster: Path,
    gradient: np.ndarray,
) -> None:
    layers = by_name((await inspect_data(a, document_id)).get("layers") or [])
    shape = layers["probe shape"]
    expected_shape = _box(8, 12, 20, 16)
    cases: dict[str, tuple[dict[str, Any], np.ndarray]] = {
        "rect": ({"type": "rect", "rect": _rect(5, 7, 21, 13)}, _box(5, 7, 21, 13)),
        "ellipse": (
            {"type": "ellipse", "rect": dict(ELLIPSE)},
            _canvas(masks.ellipse(ELLIPSE, LIMIT)),
        ),
        "polygon": (
            {"type": "polygon", "points": POLYGON},
            _canvas(masks.polygon(POLYGON, LIMIT)),
        ),
        "raster": (
            {
                "type": "raster",
                "mask_uri": str(raster),
                "mask_sha256": hashlib.sha256(raster.read_bytes()).hexdigest(),
                "origin_px": [40, 30],
            },
            _canvas(masks.Mask(gradient, (40, 30))),
        ),
        "layer_alpha": ({"type": "layer_alpha", "layer_id": shape["id"]}, expected_shape),
        "all": ({"type": "all"}, np.full((HEIGHT, WIDTH), 255, dtype=np.uint8)),
    }
    problems = []
    for name, (shape_arg, expected) in cases.items():
        selected = await tool(a, "krita_selection_set", _select(document_id, shape_arg))
        if selected.get("status") != "completed":
            problems.append(f"{name}: {code(selected)}")
            continue
        if name == "rect":
            report.measured("the undo labels after selection_set", undo_labels(client, document_id))
        found = await capture_selection(a, document_id)
        if found is None or differs(found, expected):
            problems.append(f"{name}: {differs(found, expected)}")
    cleared = await tool(a, "krita_selection_set", _select(document_id, {"type": "none"}))
    report.measured(
        "the undo labels after clearing the selection", undo_labels(client, document_id)
    )
    if (cleared.get("data") or {}).get("bounds_px") is not None or (
        await inspect_data(a, document_id)
    ).get("selection") is not None:
        problems.append(f"none: {code(cleared)}")
    report.check(
        "selection shapes land exactly (capture target selection): rect, ellipse, polygon, "
        "raster, layer_alpha and all; none clears",
        not problems,
        "; ".join(problems),
    )
    combined = [
        ("replace", _rect(0, 0, 32, 48), _box(0, 0, 32, 48)),
        ("add", _rect(16, 0, 32, 48), _box(0, 0, 48, 48)),
        ("subtract", _rect(0, 0, 8, 48), _box(8, 0, 40, 48)),
        ("intersect", _rect(24, 0, 40, 48), _box(24, 0, 24, 48)),
    ]
    problems = []
    for combine, rect, expected in combined:
        await tool(
            a,
            "krita_selection_set",
            _select(document_id, {"type": "rect", "rect": rect}, combine=combine),
        )
        found = await capture_selection(a, document_id)
        if found is None or differs(found, expected):
            problems.append(f"{combine}: {differs(found, expected)}")
    await tool(
        a,
        "krita_selection_set",
        _select(document_id, {"type": "rect", "rect": _rect(8, 8, 16, 16)}, invert=True),
    )
    found = await capture_selection(a, document_id)
    inverted = 255 - _box(8, 8, 16, 16)
    if found is None or differs(found, inverted):
        problems.append(f"invert: {differs(found, inverted)}")
    report.check(
        "add, subtract and intersect of rects, and the invert of a rect, are exact",
        not problems,
        "; ".join(problems),
    )
    measured = []
    for name, value in (("grow_px", 3), ("shrink_px", 3), ("feather_px", 3)):
        selected = await tool(
            a,
            "krita_selection_set",
            _select(document_id, {"type": "rect", "rect": _rect(20, 14, 20, 16)}, **{name: value}),
        )
        data = selected.get("data") or {}
        measured.append(f"{name} {value}: {data.get('bounds_px')} {data.get('selected_pixels')} px")
    report.measured("a 20 x 16 rect grown, shrunk and feathered by 3", "; ".join(measured))


async def _ledger(report: Report, a: Client, document_id: str, root: str) -> None:
    layer = await tool(a, "krita_layer_create", _layer(document_id, root, None))
    layer_id = (layer.get("data") or {}).get("layer_id")
    rect_x = {"type": "rect", "rect": _rect(2, 2, 10, 10)}
    rect_y = {"type": "rect", "rect": _rect(30, 20, 12, 8)}
    await tool(a, "krita_selection_set", _select(document_id, rect_x))
    second = await tool(a, "krita_selection_set", _select(document_id, rect_y))
    problems = []
    undone = await tool(a, "krita_history_step", history_args(document_id, "undo"))
    steps = (undone.get("data") or {}).get("steps")
    if steps != [{"tool": "krita_selection_set", "operation_id": second.get("operation_id")}]:
        problems.append(f"undo: {code(undone) or steps}")
    found = await capture_selection(a, document_id)
    if found is None or differs(found, _box(2, 2, 10, 10)):
        problems.append(f"after undo: {differs(found, _box(2, 2, 10, 10))}")
    await tool(a, "krita_history_step", history_args(document_id, "redo"))
    found = await capture_selection(a, document_id)
    if found is None or differs(found, _box(30, 20, 12, 8)):
        problems.append(f"after redo: {differs(found, _box(30, 20, 12, 8))}")
    # Back over both selections and the layer, then forward again.
    deep = await tool(a, "krita_history_step", history_args(document_id, "undo", 3))
    tools = [step["tool"] for step in (deep.get("data") or {}).get("steps", [])]
    ids = {entry["id"] for entry in (await inspect_data(a, document_id)).get("layers") or []}
    if (
        tools != ["krita_selection_set", "krita_selection_set", "krita_layer_create"]
        or layer_id in ids
    ):
        problems.append(
            f"undo 3: {code(deep) or tools}, the layer {'kept' if layer_id in ids else 'gone'}"
        )
    redone = await tool(a, "krita_history_step", history_args(document_id, "redo", 3))
    ids = {entry["id"] for entry in (await inspect_data(a, document_id)).get("layers") or []}
    if (redone.get("data") or {}).get("steps_applied") != 3 or layer_id not in ids:
        problems.append(
            f"redo 3: {code(redone)}, the layer {'back' if layer_id in ids else 'missing'}"
        )
    report.check(
        "each operation's undo count matches the ledger: undo and redo move exactly one layer or "
        "selection per step, and back the same way",
        not problems,
        "; ".join(problems),
    )


async def _retries(report: Report, a: Client, b: Client, document_id: str) -> None:
    arguments = _select(
        document_id, {"type": "rect", "rect": _rect(1, 1, 5, 5)}, request_id=str(uuid.uuid4())
    )
    first = await tool(a, "krita_selection_set", arguments)
    before = (await inspect_data(a, document_id)).get("history")
    again = await tool(a, "krita_selection_set", arguments)
    from_b = await tool(b, "krita_selection_set", arguments)
    after = (await inspect_data(a, document_id)).get("history")
    same = {**(from_b.get("data") or {}), "mask": (first.get("data") or {}).get("mask")}
    report.check(
        "a retried selection_set returns the original receipt through the journal and the "
        "bridge, and runs once",
        first.get("status") == "completed"
        and again == first
        and same == first.get("data")
        and before == after,
        f"{code(first)}, history {before} then {after}",
    )


async def _k46(
    report: Report,
    a: Client,
    client: BridgeClient,
    document_id: str,
    opened: dict[str, Any],
    composite: np.ndarray,
) -> None:
    root = opened["root_layer_id"]
    await tool(
        a,
        "krita_selection_set",
        _select(document_id, {"type": "rect", "rect": _rect(3, 3, 10, 10)}),
    )
    seen = await inspect_data(a, document_id)
    layers = seen.get("layers") or []
    names = {layer["id"]: layer["name"] for layer in layers}
    global_masks = [
        layer
        for layer in layers
        if layer["type"] == "selection_mask" and layer["parent_id"] == root
    ]
    if len(global_masks) == 1:
        made = harness_call(
            client,
            "harness.activate",
            document_id=document_id,
            node_id=global_masks[0]["id"],
        )
        active = made.result.get("active_id") if isinstance(made, Done) else None
        report.measured(
            "setActiveNode on the global selection's own mask",
            "it became active"
            if active == global_masks[0]["id"]
            else f"{names.get(active, active)!r} stayed active",
        )
    else:
        report.measured(
            "the global selection's own mask", f"{len(global_masks)} listed under the root"
        )
    name = (
        "K46: with a selection mask active, inspect counts the global selection alone, a capture "
        "matches the fixture, and the read makes the mask's layer active"
    )
    base = next(layer for layer in layers if layer["name"] == "probe base")
    made = harness_call(
        client,
        "harness.select_mask",
        document_id=document_id,
        layer_id=base["id"],
        rect=_rect(30, 30, 8, 8),
    )
    if not isinstance(made, Done):
        report.check(name, False, f"harness.select_mask: {made}")
        return
    counted = ((await inspect_data(a, document_id)).get("selection") or {}).get("selected_pixels")
    found = await capture_composite(a, document_id)
    active = (await inspect_data(a, document_id)).get("active_layer_id")
    problems = []
    if counted != 100:
        problems.append(f"inspect counted {counted} px")
    if found is None or differs(found, composite):
        problems.append(f"capture: {differs(found, composite)}")
    if active != base["id"]:
        problems.append(f"active {names.get(active, active)!r}, not 'probe base'")
    report.check(name, not problems, "; ".join(problems))


async def _protection(report: Report, a: Client, document_id: str, made: list[str]) -> None:
    seen = await inspect_data(a, document_id)
    protected = sorted(
        [layer["id"] for layer in seen.get("layers") or [] if layer["protected"]] + [made[0]]
    )

    def arguments(mask: Any, **changes: Any) -> dict[str, Any]:
        return {
            "guard": guard(document_id),
            "protected_layer_ids": protected,
            "allowed_change_mask": mask,
            "preserve_composite_alpha": True,
            "preserve_canvas": True,
            **changes,
        }

    allowed = {"rect": _rect(16, 8, 32, 24)}
    # An undo first, so there is a step to undo and one to redo when protection tightens.
    await tool(a, "krita_history_step", history_args(document_id, "undo"))
    set_ = await tool(a, "krita_protection_set", arguments(allowed))
    summary = ((await inspect_data(a, document_id)).get("protection") or {}).get(
        "allowed_change_mask"
    ) or {}
    floor = code(await tool(a, "krita_history_step", history_args(document_id, "undo")))
    redo = code(await tool(a, "krita_history_step", history_args(document_id, "redo")))
    report.check(
        "protection_set tightens: the mask's summary shows in inspect; undo below it and the "
        "cleared redo are refused",
        set_.get("status") == "completed"
        and summary.get("bounds_px") == allowed["rect"]
        and summary.get("allowed_pixels") == 32 * 24
        and (floor, redo) == ("INVALID_ARGUMENT", "INVALID_ARGUMENT"),
        f"{code(set_)}, {summary.get('bounds_px')}, undo {floor}, redo {redo}",
    )
    loosen = {
        "the whole canvas": arguments(None),
        "a wider rect": arguments({"rect": _rect(15, 8, 33, 24)}),
        "a dropped layer": arguments(allowed, protected_layer_ids=protected[1:]),
        "a flag back off": arguments(allowed, preserve_canvas=False),
    }
    found = {
        name: code(await tool(a, "krita_protection_set", value)) for name, value in loosen.items()
    }
    tighter = await tool(
        a, "krita_protection_set", arguments({"polygon": [[20, 10], [40, 10], [40, 30], [20, 30]]})
    )
    left = ((tighter.get("data") or {}).get("allowed_change_mask") or {}).get("allowed_pixels")
    report.check(
        "protection never loosens: the whole canvas, a wider rect, a dropped layer and a flag back "
        "off are refused; a tighter polygon passes",
        set(found.values()) == {"INVALID_ARGUMENT"} and left == 400,
        ", ".join(f"{name}: {value}" for name, value in found.items())
        + f"; tighter {code(tighter) or left}",
    )


async def _label_timing(report: Report, client: BridgeClient, document_id: str) -> None:
    timed = harness_call(
        client, "harness.label_timing", document_id=document_id, trials=LABEL_TRIALS
    )
    reads = timed.result.get("reads", []) if isinstance(timed, Done) else []
    stale = sum(1 for straight, _ in reads if straight is None or straight == "")
    fresh = [flushed for _, flushed in reads]
    report.measured(
        "the Undo label read straight after a push in the same job",
        f"stale in {stale} of {len(reads)}: {sorted({str(straight) for straight, _ in reads})}",
    )
    report.check(
        "after posted events are through, the Undo label names the step just pushed, every time",
        len(reads) == LABEL_TRIALS and len(set(fresh)) == 1 and fresh[0] is not None,
        f"{sorted({str(flushed) for flushed in fresh})}" if reads else str(timed),
    )


async def _close_at_once(report: Report, a: Client, ora: Path, harness: Path) -> None:
    # Krita's layer docker updates a changed node from a timer and crashes if the document has
    # closed by then; the close waits for it.
    failures = []
    for cycle in range(CLOSE_CYCLES):
        opened = await tool(
            a, "krita_document_open", open_args(ora, "working_copy", harness / "work" / "close")
        )
        document_id = opened.get("document_id")
        if not document_id:
            failures.append(f"open {cycle}: {code(opened)}")
            break
        await tool(a, "krita_selection_set", _select(document_id, {"type": "all"}))
        closed = await close(a, document_id)
        if (closed.get("data") or {}).get("closed") is not True:
            failures.append(f"close {cycle}: {code(closed)}")
            break
    alive = await tool(a, "krita_server_info", {})
    report.check(
        f"{CLOSE_CYCLES} documents closed straight after a selection change, and Krita still "
        "answers",
        not failures and alive.get("status") == "completed",
        "; ".join(failures) or str(code(alive) or "answers"),
    )
