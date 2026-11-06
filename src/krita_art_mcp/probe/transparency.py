import hashlib
from pathlib import Path
from typing import Any

import numpy as np
from mcp import Client
from PIL import Image

from krita_art_mcp.bridge_client import BridgeClient, Done
from krita_art_mcp.probe import fixtures
from krita_art_mcp.probe.common import (
    add_layer,
    brush_args,
    capture,
    capture_composite,
    close,
    guard,
    harness_call,
    history_args,
    inspect_data,
    line_points,
    open_working,
    protect,
    stroke_args,
)
from krita_art_mcp.probe.filling import fill_args
from krita_art_mcp.probe.report import Report, code, differs, tool
from krita_art_mcp.probe.saving import save

FILL = "krita_paint_fill"
WIDTH, HEIGHT = fixtures.PAINT_WIDTH, fixtures.PAINT_HEIGHT
WHOLE = {"x": 0, "y": 0, "width": WIDTH, "height": HEIGHT}
RED = (230, 60, 30)
# Unlike every layer below it, so hiding it shows in the composite.
AMBER = (200, 120, 40)
# Where each check's layer is painted, and where its mask is painted inside it.
SUBJECT = {"x": 20, "y": 20, "width": 60, "height": 40}
INSIDE = {"x": 24, "y": 24, "width": 8, "height": 8}
BESIDE = {"x": 40, "y": 24, "width": 8, "height": 8}


def _shape(rect: dict[str, int]) -> dict[str, Any]:
    return {"type": "rect", "rect": dict(rect)}


def _crop(pixels: np.ndarray | None, rect: dict[str, int]) -> np.ndarray | None:
    if pixels is None:
        return None
    return pixels[rect["y"] : rect["y"] + rect["height"], rect["x"] : rect["x"] + rect["width"]]


def _mask_paint(
    document_id: str, mask: str, rect: dict[str, int], paint: str, opacity: float
) -> Any:
    return {
        "guard": guard(document_id),
        "layer_id": mask,
        "shape": _shape(rect),
        "mask": paint,
        "opacity": opacity,
    }


async def _mask(
    a: Client, document_id: str, parent: str, coverage: str, name: str
) -> dict[str, Any]:
    arguments = {
        "guard": guard(document_id),
        "parent_id": parent,
        "above_id": None,
        "type": "transparency_mask",
        "name": f"krita-art-mcp probe {name}",
        "coverage": coverage,
    }
    return await tool(a, "krita_layer_create", arguments)


async def _subject(
    a: Client, document_id: str, root: str, name: str, rgb: tuple[int, int, int] = RED
) -> str | None:
    layer = await add_layer(a, document_id, root, name)
    if layer is None:
        return None
    done = await tool(a, FILL, fill_args(document_id, layer, _shape(SUBJECT), rgb))
    return layer if done.get("status") == "completed" else None


async def _read_mask(a: Client, document_id: str, mask: str) -> np.ndarray | None:
    return await capture(a, document_id, WHOLE, "mask", mask)


async def run(
    report: Report,
    a: Client,
    client: BridgeClient,
    paint: Path,
    harness: Path,
    presets: dict[str, Any],
) -> None:
    await _capability(report, a)
    folder = harness / "masks"
    folder.mkdir(exist_ok=True)
    opened = await open_working(a, paint, harness, "masks")
    document_id = opened.get("document_id")
    if opened.get("status") != "completed" or not document_id:
        report.check("the mask checks' working copy opens", False, str(opened.get("error")))
        return
    try:
        data = opened["data"]
        root = data["root_layer_id"]
        await _from_selection(report, a, client, folder, document_id, root)
        await _all_and_none(report, a, document_id, root)
        await _reveal_and_hide(report, a, document_id, root, presets["hard"])
        await _create_undone(report, a, document_id, root)
        await _round_trips(report, a, folder, harness, document_id, root)
        await _refusals(report, a, document_id, root, data["layers"], presets["hard"])
    finally:
        await close(a, document_id)


async def _capability(report: Report, a: Client) -> None:
    data = (await tool(a, "krita_server_info", {})).get("data") or {}
    entry = (data.get("capabilities") or {}).get("mask.transparency") or {}
    report.check(
        "the capability matrix marks mask.transparency supported since 0.22.0",
        entry.get("supported") is True and entry.get("since") == "0.22.0",
        str(entry),
    )


async def _from_selection(
    report: Report, a: Client, client: BridgeClient, folder: Path, document_id: str, root: str
) -> None:
    before = await capture_composite(a, document_id, WIDTH, HEIGHT)
    layer = await _subject(a, document_id, root, "mask graded")
    if layer is None:
        report.check("the graded mask's layer is painted", False)
        return
    gradient = np.tile(
        np.round(np.linspace(0, 255, SUBJECT["width"])).astype(np.uint8), (SUBJECT["height"], 1)
    )
    raster = folder / "graded.png"
    Image.fromarray(gradient, "L").save(raster)
    shape = {
        "type": "raster",
        "mask_uri": str(raster),
        "mask_sha256": hashlib.sha256(raster.read_bytes()).hexdigest(),
        "origin_px": [SUBJECT["x"], SUBJECT["y"]],
    }
    selected = await tool(
        a,
        "krita_selection_set",
        {
            "guard": guard(document_id),
            "combine": "replace",
            "shape": shape,
            "feather_px": 0,
            "invert": False,
        },
    )
    made = await _mask(a, document_id, layer, "selection", "graded mask")
    mask = (made.get("data") or {}).get("layer_id")
    selection = await capture(a, document_id, WHOLE, "selection")
    found = None if mask is None else await _read_mask(a, document_id, mask)
    composite = await capture_composite(a, document_id, WIDTH, HEIGHT)
    labels = harness_call(client, "harness.undo_labels", document_id=document_id)
    undo = labels.result.get("undo") if isinstance(labels, Done) else None
    expected = None
    if before is not None:
        cover = np.zeros((HEIGHT, WIDTH), dtype=float)
        top, left = SUBJECT["y"], SUBJECT["x"]
        cover[top : top + SUBJECT["height"], left : left + SUBJECT["width"]] = gradient / 255
        red = np.zeros((HEIGHT, WIDTH, 3))
        red[...] = RED
        mixed = red * cover[..., None] + before[..., :3] * (1 - cover[..., None])
        expected = before.copy()
        expected[..., :3] = np.rint(mixed).astype(np.uint8)
    report.check(
        "a mask made from a graded PNG selection holds the selection byte for byte, as one undo "
        "step labelled Add Layer",
        selected.get("status") == "completed"
        and made.get("status") == "completed"
        and (made.get("data") or {}).get("undo_steps") == 1
        and undo == "Add Layer"
        and found is not None
        and selection is not None
        and np.array_equal(found, selection),
        f"{code(selected) or code(made) or 'made'}, undo {undo!r}",
    )
    report.check(
        "beside it the composite shows the layer by the mask's coverage, rounded",
        not differs(composite, expected),
        differs(composite, expected) or "as computed",
    )
    await tool(
        a,
        "krita_selection_set",
        {
            "guard": guard(document_id),
            "combine": "replace",
            "shape": {"type": "none"},
            "feather_px": 0,
            "invert": False,
        },
    )


async def _all_and_none(report: Report, a: Client, document_id: str, root: str) -> None:
    before = await capture_composite(a, document_id, WIDTH, HEIGHT)
    shown = await _subject(a, document_id, root, "mask all")
    painted = await capture_composite(a, document_id, WIDTH, HEIGHT)
    hidden = None if shown is None else await _mask(a, document_id, shown, "all", "all mask")
    with_all = await capture_composite(a, document_id, WIDTH, HEIGHT)
    none = None if shown is None else await _mask(a, document_id, shown, "none", "none mask")
    with_none = await capture_composite(a, document_id, WIDTH, HEIGHT)
    mode = ((none or {}).get("data") or {}).get("verification") or {}
    report.check(
        "an all mask leaves the composite as it was, and a none mask hides its layer",
        hidden is not None
        and none is not None
        and hidden.get("status") == none.get("status") == "completed"
        and not differs(with_all, painted)
        and not differs(with_none, before)
        and mode.get("changed_px", 0) > 0,
        f"all {differs(with_all, painted) or 'unchanged'}, "
        f"none {differs(with_none, before) or 'hidden'}",
    )
    if none is None or none.get("status") != "completed":
        return
    mask = none["data"]["layer_id"]
    args = {"guard": guard(document_id), "layer_id": mask, "verify": "region"}
    off = await tool(a, "krita_layer_update", {**args, "properties": {"visible": False}})
    disabled = await capture_composite(a, document_id, WIDTH, HEIGHT)
    on = await tool(
        a,
        "krita_layer_update",
        {**args, "guard": guard(document_id), "properties": {"visible": True}},
    )
    enabled = await capture_composite(a, document_id, WIDTH, HEIGHT)
    report.check(
        "a mask disabled shows its layer again, and enabled hides it again",
        off.get("status") == on.get("status") == "completed"
        and not differs(disabled, painted)
        and not differs(enabled, before),
        f"{code(off) or code(on) or 'set'}, off {differs(disabled, painted) or 'shown'}, "
        f"on {differs(enabled, before) or 'hidden'}",
    )


async def _reveal_and_hide(
    report: Report, a: Client, document_id: str, root: str, hard: dict[str, Any]
) -> None:
    layer = await _subject(a, document_id, root, "mask paint")
    hidden = None if layer is None else await _mask(a, document_id, layer, "none", "reveal mask")
    shown = None if layer is None else await _mask(a, document_id, layer, "all", "hide mask")
    made = [content for content in (hidden, shown) if content is not None]
    if len(made) != 2 or any(content.get("status") != "completed" for content in made):
        report.check("the mask paint checks' masks are made", False)
        return
    assert hidden is not None and shown is not None
    reveal, hide = hidden["data"]["layer_id"], shown["data"]["layer_id"]
    fills = [
        (reveal, INSIDE, "reveal", 1, {255}),
        (reveal, BESIDE, "reveal", 0.5, {128}),
        (hide, INSIDE, "hide", 1, {0}),
        (hide, BESIDE, "hide", 0.5, {127, 128}),
    ]
    problems = []
    for mask, rect, paint, opacity, values in fills:
        done = await tool(a, FILL, _mask_paint(document_id, mask, rect, paint, opacity))
        found = _crop(await _read_mask(a, document_id, mask), rect)
        got = None if found is None else set(found.flatten().tolist())
        if done.get("status") != "completed" or got is None or not got <= values:
            problems.append(f"{paint} {opacity}: {code(done)} {got}")
    report.check(
        "fills on masks reveal and hide by their opacity: 1 gives 255 or 0, 0.5 gives half",
        not problems,
        "; ".join(problems) or "exact",
    )
    # Below the fills, so each stroke is judged against its own change alone.
    revealed = await _stroked(a, document_id, reveal, hard, "reveal", 1, 50)
    broke = _moved(revealed, higher=True, centre={255})
    report.check(
        "a reveal stroke on a mask raises coverage only inside its reported bounds, to 255 at "
        "its centre",
        not broke,
        f"{revealed[4]}; {broke}" if broke else revealed[4],
    )
    halved = await _stroked(a, document_id, hide, hard, "hide", 0.5, 50)
    broke = _moved(halved, higher=False, centre={127, 128}, floor=127)
    report.check(
        "a hide stroke at opacity 0.5 lowers coverage only inside its bounds, to half at its "
        "centre and never below",
        not broke,
        f"{halved[4]}; {broke}" if broke else halved[4],
    )
    stroked = await _stroked(a, document_id, hide, hard, "hide", 1, 40)
    _, before, after, _, _ = stroked
    broke = _moved(stroked, higher=False, centre={0})
    report.check(
        "a hide stroke on a mask lowers coverage only inside its reported bounds, to 0 at its "
        "centre",
        not broke,
        f"{stroked[4]}; {broke}" if broke else stroked[4],
    )
    undone = await tool(a, "krita_history_step", history_args(document_id, "undo"))
    back = await _read_mask(a, document_id, hide)
    redone = await tool(a, "krita_history_step", history_args(document_id, "redo"))
    again = await _read_mask(a, document_id, hide)
    report.check(
        "a mask stroke is one undo step: undo brings the mask back, redo paints it again",
        (undone.get("data") or {}).get("steps_applied") == 1
        and (redone.get("data") or {}).get("steps_applied") == 1
        and before is not None
        and back is not None
        and np.array_equal(back, before)
        and again is not None
        and after is not None
        and np.array_equal(again, after),
        f"{code(undone) or 'undone'}, {code(redone) or 'redone'}",
    )


# The receipt, the mask before and after, the row stroked along, and what to print.
Stroked = tuple[dict[str, Any], np.ndarray | None, np.ndarray | None, int, str]


async def _stroked(
    a: Client,
    document_id: str,
    mask: str,
    hard: dict[str, Any],
    paint: str,
    opacity: float,
    row: int,
) -> Stroked:
    # A stroke along one row, and the mask read before and after it.
    before = await _read_mask(a, document_id, mask)
    brush = {**brush_args(hard, size_px=6, opacity=opacity), "mask": paint}
    del brush["color"]
    points = line_points(50, row, 70, row)
    done = await tool(a, "krita_paint_stroke", stroke_args(document_id, mask, brush, points))
    after = await _read_mask(a, document_id, mask)
    bounds = (done.get("data") or {}).get("changed_bounds_px")
    detail = f"{code(done) or 'stroked'}, bounds {bounds}"
    if after is not None:
        detail += f", centre {sorted(set(_centre(after, row).flatten().tolist()))}"
    return done, before, after, row, detail


def _centre(pixels: np.ndarray, row: int) -> np.ndarray:
    # The two rows either side of the line a stroke ran along, well inside its ends.
    return pixels[row - 1 : row + 1, 55:66]


def _moved(stroked: Stroked, higher: bool, centre: set[int], floor: int | None = None) -> str:
    # Every changed byte inside the bounds and moved one way, and the stroke's middle at what
    # its opacity gives; what broke, or "" when nothing did.
    done, before, after, row, _ = stroked
    bounds = (done.get("data") or {}).get("changed_bounds_px")
    if done.get("status") != "completed" or before is None or after is None or bounds is None:
        return "not stroked"
    rows, columns = np.nonzero(before != after)
    if rows.size == 0:
        return "nothing changed"
    old, new = before[rows, columns].astype(int), after[rows, columns].astype(int)
    outside = ~(
        (columns >= bounds["x"])
        & (columns < bounds["x"] + bounds["width"])
        & (rows >= bounds["y"])
        & (rows < bounds["y"] + bounds["height"])
    )
    wrong = (new <= old) if higher else (new >= old)
    middle = set(_centre(after, row).flatten().tolist())
    problems = []
    if outside.any():
        spots = list(zip(rows[outside].tolist(), columns[outside].tolist(), strict=True))[:4]
        problems.append(f"{int(outside.sum())} changed outside the bounds, at {spots}")
    if wrong.any():
        problems.append(f"{int(wrong.sum())} moved the other way")
    if not middle <= centre:
        problems.append(f"centre {sorted(middle)}")
    if floor is not None and int(new.min()) < floor:
        problems.append(f"down to {int(new.min())}")
    return "; ".join(problems)


async def _create_undone(report: Report, a: Client, document_id: str, root: str) -> None:
    # Amber, unlike what lies under it, so the mask that hides it shows in the composite.
    layer = await _subject(a, document_id, root, "mask undone", AMBER)
    before = await capture_composite(a, document_id, WIDTH, HEIGHT)
    made = None if layer is None else await _mask(a, document_id, layer, "none", "undone mask")
    mask = ((made or {}).get("data") or {}).get("layer_id")
    hidden = await capture_composite(a, document_id, WIDTH, HEIGHT)
    undone = await tool(a, "krita_history_step", history_args(document_id, "undo"))
    back = await capture_composite(a, document_id, WIDTH, HEIGHT)
    layers = (await inspect_data(a, document_id)).get("layers") or []
    data = undone.get("data") or {}
    tools = [step.get("tool") for step in data.get("steps") or []]
    report.check(
        "a mask's create is one undo step: undone, the mask is gone and the composite as before",
        mask is not None
        and bool(differs(hidden, before))
        and data.get("steps_applied") == 1
        and tools == ["krita_layer_create"]
        and not differs(back, before)
        and mask not in {entry.get("id") for entry in layers},
        f"{code(made or {}) or code(undone) or 'undone'}, steps {tools}, "
        f"{differs(back, before) or 'composite back'}",
    )


async def _round_trips(
    report: Report, a: Client, folder: Path, harness: Path, document_id: str, root: str
) -> None:
    layer = await _subject(a, document_id, root, "mask saved")
    made = None if layer is None else await _mask(a, document_id, layer, "all", "saved mask")
    mask = ((made or {}).get("data") or {}).get("layer_id")
    if mask is None:
        report.check("the saved mask is made", False)
        return
    await tool(a, FILL, _mask_paint(document_id, mask, INSIDE, "hide", 1))
    kept = await _read_mask(a, document_id, mask)
    kra = await save(a, document_id, folder / "masked.kra")
    reopened = await open_working(a, folder / "masked.kra", harness, "masks-kra")
    again = reopened.get("document_id")
    try:
        found = None if again is None else await _read_mask(a, again, mask)
        refused = (
            {}
            if again is None
            else await tool(a, FILL, _mask_paint(again, mask, BESIDE, "hide", 1))
        )
        report.check(
            "a KRA save keeps the mask: reopened, it holds the same bytes and is protected",
            kra.get("status") == "completed"
            and (kra.get("data") or {}).get("expected_losses") == []
            and found is not None
            and kept is not None
            and np.array_equal(found, kept)
            and code(refused) == "LOCKED_TARGET",
            f"{code(kra) or 'saved'}, reopened {code(reopened) or 'open'}, paint {code(refused)}",
        )
    finally:
        if again is not None:
            await close(a, again)
    ora = await save(a, document_id, folder / "masked.ora")
    losses = (ora.get("data") or {}).get("expected_losses") or []
    lost = {(entry.get("layer_id"), entry.get("type"), entry.get("lost")) for entry in losses}
    report.check(
        "an ORA save keeps the composite and lists the mask in expected_losses",
        ora.get("status") == "completed" and (mask, "transparency_mask", "node") in lost,
        f"{code(ora) or 'saved'}, {len(losses)} losses",
    )


async def _refusals(
    report: Report,
    a: Client,
    document_id: str,
    root: str,
    layers: list[dict[str, Any]],
    hard: dict[str, Any],
) -> None:
    # Last: protection only tightens.
    layer = await _subject(a, document_id, root, "mask leak", AMBER)
    made = None if layer is None else await _mask(a, document_id, layer, "all", "leak mask")
    mask = ((made or {}).get("data") or {}).get("layer_id")
    allowed = {"x": 0, "y": 0, "width": 50, "height": HEIGHT}
    protected = await protect(a, document_id, layers, {"rect": allowed})
    if mask is None or layer is None or protected.get("status") != "completed":
        report.check("the mask leak checks' layer, mask and protection are set", False)
        return
    before = await capture_composite(a, document_id, WIDTH, HEIGHT)
    hidden = await _mask(a, document_id, layer, "none", "leaking mask")
    brush = {**brush_args(hard, size_px=6), "mask": "hide"}
    del brush["color"]
    stroked = await tool(
        a,
        "krita_paint_stroke",
        stroke_args(document_id, mask, brush, line_points(30, 40, 70, 40)),
    )
    after = await capture_composite(a, document_id, WIDTH, HEIGHT)
    confirmed = [
        ((content.get("error") or {}).get("details") or {}).get("rollback_verified")
        for content in (hidden, stroked)
    ]
    report.check(
        "past the allowed mask, a none mask and a hide stroke are each rolled back and confirmed",
        code(hidden) == code(stroked) == "PROTECTED_REGION_CHANGED"
        and confirmed == [True, True]
        and not differs(after, before),
        f"{code(hidden)}, {code(stroked)}, {confirmed}, {differs(after, before) or 'as before'}",
    )
    everything = [*layers, {"id": layer}]
    tightened = await protect(a, document_id, everything, {"rect": allowed})
    refused = await tool(a, FILL, _mask_paint(document_id, mask, INSIDE, "hide", 1))
    report.check(
        "a mask on a protected layer refuses paint",
        tightened.get("status") == "completed" and code(refused) == "LOCKED_TARGET",
        f"{code(tightened) or 'protected'}, {code(refused)}",
    )
