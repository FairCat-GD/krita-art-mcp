import os
from pathlib import Path
from typing import Any

import numpy as np
from mcp import Client

from krita_art_mcp.bridge_client import BridgeClient, Done
from krita_art_mcp.probe import fixtures
from krita_art_mcp.probe.common import (
    by_name,
    capture_composite,
    close,
    document_dirty,
    guard,
    harness_call,
    history_args,
    inspect_data,
    open_working,
)
from krita_art_mcp.probe.report import Report, code, differs, tool

BLEND_LABEL = "Composition Mode Change"
# The property changes that push no undo step, in the order the ledger check makes them.
UNDO_FREE = (
    {"name": "krita-art-mcp probe renamed"},
    {"opacity": 0.5},
    {"visible": False},
    {"visible": True},
    {"inherit_alpha": True},
    {"alpha_locked": True},
    {"locked": True},
    {"locked": False},
)
SPREADERS = ("filter_layer", "filter_mask", "transform_mask", "clone_layer")


async def run(report: Report, a: Client, client: BridgeClient, harness: Path) -> None:
    harness = Path(os.path.realpath(harness))
    folder = harness / "updates"
    folder.mkdir(exist_ok=True)
    ora, rim = folder / "update.ora", folder / "rim.ora"
    fixtures.write_ora(ora, fixtures.update_stack())
    fixtures.write_ora(rim, fixtures.rim_stack())
    await _properties(report, a, client, ora, harness)
    await _leaks(report, a, client, ora, harness)
    await _rim(report, a, rim, harness)


def _update(document_id: str, layer_id: str, **properties: Any) -> dict[str, Any]:
    verify = properties.pop("verify", None)
    arguments = {"guard": guard(document_id), "layer_id": layer_id, "properties": properties}
    return arguments if verify is None else {**arguments, "verify": verify}


async def _properties(
    report: Report, a: Client, client: BridgeClient, ora: Path, harness: Path
) -> None:
    opened = await open_working(
        a, ora, harness, "updates", editable_layer_names=["probe paint", "probe group"]
    )
    document_id = opened.get("document_id")
    if opened.get("status") != "completed" or not document_id:
        report.check("the layer_update checks' working copy opens", False, str(opened.get("error")))
        return
    try:
        layers = by_name(opened["data"]["layers"])
        paint = layers["probe paint"]["id"]
        await _active(report, a, document_id, paint)
        await _ledger(report, a, document_id, paint)
        await _locked(report, a, document_id, layers)
        # Its harness ops seal history, so they come last.
        await _reach(report, a, client, document_id, paint)
    finally:
        await close(a, document_id)


async def _active(report: Report, a: Client, document_id: str, paint: str) -> None:
    done = await tool(a, "krita_layer_update", _update(document_id, paint, active=True))
    seen = await inspect_data(a, document_id)
    dirty = await document_dirty(a, document_id)
    report.check(
        "layer_update with active alone makes the layer active and leaves the document clean",
        (done.get("data") or {}).get("effective_properties") == {"active": True}
        and seen.get("active_layer_id") == paint
        and dirty is False,
        f"{code(done)}, active {seen.get('active_layer_id') == paint}, dirty {dirty}",
    )


async def _ledger(report: Report, a: Client, document_id: str, paint: str) -> None:
    problems = []
    for mode in ("multiply", "screen"):
        done = await tool(a, "krita_layer_update", _update(document_id, paint, blend_mode=mode))
        if (done.get("data") or {}).get("undo_steps") != 1:
            problems.append(f"{mode}: {code(done) or done.get('data')}")
    await tool(a, "krita_history_step", history_args(document_id, "undo"))
    middle = by_name((await inspect_data(a, document_id)).get("layers") or [])
    if middle.get("probe paint", {}).get("blend_mode") != "multiply":
        problems.append(f"undo 1 left {middle.get('probe paint', {}).get('blend_mode')}")
    await tool(a, "krita_history_step", history_args(document_id, "redo"))
    for properties in UNDO_FREE:
        done = await tool(a, "krita_layer_update", _update(document_id, paint, **properties))
        if done.get("status") != "completed" or (done.get("data") or {}).get("undo_steps") != 0:
            problems.append(f"{properties}: {code(done)}")
    # Both blend steps are still on top of Krita's stack: a step any property pushed would stop
    # history.
    undone = (await tool(a, "krita_history_step", history_args(document_id, "undo", 2))).get(
        "data"
    ) or {}
    seen = by_name((await inspect_data(a, document_id)).get("layers") or [])
    renamed = seen.get("krita-art-mcp probe renamed", {})
    if undone.get("steps_applied") != 2 or renamed.get("blend_mode") != "normal":
        problems.append(f"undo 2: {undone.get('steps_applied')}, {renamed.get('blend_mode')}")
    report.check(
        "two blend changes are two undo steps history moves one at a time; name, opacity, "
        "visibility, inherit-alpha, alpha lock and lock push none",
        not problems,
        "; ".join(problems),
    )


async def _locked(report: Report, a: Client, document_id: str, layers: dict[str, Any]) -> None:
    found = {
        name: code(
            await tool(
                a, "krita_layer_update", _update(document_id, layers[name]["id"], visible=False)
            )
        )
        for name in ("probe base", "probe group")
    }
    report.check(
        "layer_update refuses a protected layer and a group holding one with LOCKED_TARGET",
        set(found.values()) == {"LOCKED_TARGET"},
        ", ".join(f"{name}: {value}" for name, value in found.items()),
    )


async def _reach(
    report: Report, a: Client, client: BridgeClient, document_id: str, paint: str
) -> None:
    made = {}
    for kind in SPREADERS:
        added = harness_call(
            client, "harness.add_node", document_id=document_id, kind=kind, layer_id=paint
        )
        if not isinstance(added, Done):
            report.check(f"harness.add_node makes a {kind}", False, str(added))
            return
        made[kind] = added.result["node_id"]
        if kind == "filter_layer":
            region = await tool(a, "krita_layer_update", _update(document_id, paint, opacity=0.75))
            full = await tool(
                a, "krita_layer_update", _update(document_id, paint, opacity=0.6, verify="full")
            )
            reasons = (region.get("error") or {}).get("details", {}).get("reasons", [])
            checked = (full.get("data") or {}).get("verification") or {}
            report.check(
                "a filter layer above the target makes region scope UNSUPPORTED_CAPABILITY, and "
                "verify full passes over the whole canvas",
                code(region) == "UNSUPPORTED_CAPABILITY"
                and {"reason": "filter_layer", "node_id": made[kind]} in reasons
                and full.get("status") == "completed"
                and checked.get("rect")
                == {"x": 0, "y": 0, "width": fixtures.WIDTH, "height": fixtures.HEIGHT},
                f"region {code(region)}, full {code(full) or checked.get('changed_bounds_px')}",
            )
    # A value no earlier call set, so the update always changes something to refuse.
    region = await tool(a, "krita_layer_update", _update(document_id, paint, opacity=0.3))
    reasons = (region.get("error") or {}).get("details", {}).get("reasons", [])
    named = {(entry["reason"], entry["node_id"]) for entry in reasons}
    report.check(
        "a filter mask and a transform mask on the target and a clone of it are each named in the "
        "refusal",
        code(region) == "UNSUPPORTED_CAPABILITY"
        and {(kind, made[kind]) for kind in SPREADERS[1:]} <= named,
        f"{code(region)}: {sorted(reason for reason, _ in named)}",
    )


async def _leaks(report: Report, a: Client, client: BridgeClient, ora: Path, harness: Path) -> None:
    opened = await open_working(a, ora, harness, "updates", editable_layer_names=["probe paint"])
    document_id = opened.get("document_id")
    if opened.get("status") != "completed" or not document_id:
        report.check("the leak checks' working copy opens", False, str(opened.get("error")))
        return
    try:
        layers = opened["data"]["layers"]
        paint = by_name(layers)["probe paint"]["id"]
        protect = {
            "guard": guard(document_id),
            "protected_layer_ids": sorted(layer["id"] for layer in layers if layer["protected"]),
            # The left half of the paint layer.
            "allowed_change_mask": {"rect": {"x": 8, "y": 8, "width": 12, "height": 16}},
            "preserve_composite_alpha": False,
            "preserve_canvas": False,
        }
        protected = await tool(a, "krita_protection_set", protect)
        before = await capture_composite(a, document_id)
        leak = await tool(a, "krita_layer_update", _update(document_id, paint, opacity=0.5))
        details = (leak.get("error") or {}).get("details", {})
        after = await capture_composite(a, document_id)
        paint_now = by_name((await inspect_data(a, document_id)).get("layers") or [])["probe paint"]
        dirty = await document_dirty(a, document_id)
        checked = details.get("verification") or {}
        report.check(
            "an opacity change that leaks past the allowed mask is refused, restored and "
            "confirmed: the composite as before, opacity back, the document still clean",
            protected.get("status") == "completed"
            and code(leak) == "PROTECTED_REGION_CHANGED"
            and details.get("rolled_back") is True
            and details.get("rollback_verified") is True
            and checked.get("changed_outside_px", 0) > 0
            and (checked.get("diff") or {}).get("path") is not None
            and not differs(after, before)
            and paint_now["opacity"] == 1
            and dirty is False,
            f"{code(protected)}, {code(leak)}, {checked.get('changed_outside_px')} px outside, "
            f"composite {differs(after, before) or 'as before'}, opacity {paint_now['opacity']}, "
            f"dirty {dirty}",
        )
        blend = await tool(
            a, "krita_layer_update", _update(document_id, paint, blend_mode="multiply")
        )
        labels = harness_call(client, "harness.undo_labels", document_id=document_id)
        redo_label = labels.result.get("redo") if isinstance(labels, Done) else None
        redo = await tool(a, "krita_history_step", history_args(document_id, "redo"))
        again = await capture_composite(a, document_id)
        blend_now = by_name((await inspect_data(a, document_id)).get("layers") or [])["probe paint"]
        report.check(
            "K43: a leaking blend change is undone natively; Krita offers its redo and history "
            "refuses it; the composite is as before",
            code(blend) == "PROTECTED_REGION_CHANGED"
            and ((blend.get("error") or {}).get("details") or {}).get("rollback_verified") is True
            and redo_label == BLEND_LABEL
            and code(redo) == "INVALID_ARGUMENT"
            and not differs(again, before)
            and blend_now["blend_mode"] == "normal",
            f"{code(blend)}, Krita's redo {redo_label!r}, history {code(redo)}, "
            f"composite {differs(again, before) or 'as before'}",
        )
    finally:
        await close(a, document_id)


async def _rim(report: Report, a: Client, rim: Path, harness: Path) -> None:
    opened = await open_working(a, rim, harness, "updates", editable_layer_names=["probe recolour"])
    document_id = opened.get("document_id")
    if opened.get("status") != "completed" or not document_id:
        report.check("the rim checks' working copy opens", False, str(opened.get("error")))
        return
    try:
        layers = opened["data"]["layers"]
        recolour = by_name(layers)["probe recolour"]["id"]
        protect = {
            "guard": guard(document_id),
            "protected_layer_ids": sorted(layer["id"] for layer in layers if layer["protected"]),
            "allowed_change_mask": None,
            "preserve_composite_alpha": True,
            "preserve_canvas": False,
        }
        protected = await tool(a, "krita_protection_set", protect)
        before = await capture_composite(a, document_id)
        shown = await tool(a, "krita_layer_update", _update(document_id, recolour, visible=True))
        shown_details = (shown.get("error") or {}).get("details", {})
        alpha_px = (shown_details.get("verification") or {}).get("alpha_changed_px", 0)
        after_refusal = await capture_composite(a, document_id)
        report.check(
            "under preserve_composite_alpha, showing the recolour layer alone is refused for its "
            "alpha and restored",
            protected.get("status") == "completed"
            and code(shown) == "PROTECTED_REGION_CHANGED"
            and alpha_px > 0
            and shown_details.get("rollback_verified") is True
            and not differs(after_refusal, before),
            f"{code(protected)}, {code(shown)}, {alpha_px} alpha px, "
            f"composite {differs(after_refusal, before) or 'as before'}",
        )
        clipped = await tool(
            a,
            "krita_layer_update",
            _update(document_id, recolour, visible=True, inherit_alpha=True),
        )
        after = await capture_composite(a, document_id)
        checked = (clipped.get("data") or {}).get("verification") or {}
        same_alpha = (
            before is not None
            and after is not None
            and np.array_equal(before[..., 3], after[..., 3])
        )
        inside = before is not None and before[..., 3] > 0
        recoloured = (
            after is not None
            and before is not None
            and bool(np.any(np.any(after[..., :3] != before[..., :3], axis=-1) & inside))
        )
        report.check(
            "inherit_alpha shows the recolour layer over the soft rim under "
            "preserve_composite_alpha: every alpha byte as before, the colour changed inside",
            clipped.get("status") == "completed"
            and checked.get("alpha_changed_px") == 0
            and checked.get("changed_px", 0) > 0
            and same_alpha
            and recoloured,
            f"{code(clipped)}, alpha {'kept' if same_alpha else 'changed'}, "
            f"{checked.get('changed_px')} px changed",
        )
    finally:
        await close(a, document_id)
