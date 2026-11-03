import os
import statistics
import time
from pathlib import Path
from typing import Any

import numpy as np
from mcp import Client

from krita_art_mcp import sheets
from krita_art_mcp.probe import fixtures
from krita_art_mcp.probe.common import capture, close, guard, open_working
from krita_art_mcp.probe.report import Report, code, differs, sheet_cell, tool

TOOL = "krita_preview_render"
RIVER = {"space": "srgb", "rgba": [0.19, 0.42, 0.55, 1]}
BASE = (30, 110, 200)
# The first game's recipes: a 2x master exported at 4 px per unit, reviewed at 2.95 and 1.8.
EXPORT_PER_UNIT = 4
GAME = (
    {"id": "game-2.95", "target_pixels_per_unit": 2.95},
    {"id": "game-1.8", "target_pixels_per_unit": 1.8},
)
MASTER_PX = (650, 490)
# 650 x 0.36875 = 239.6875 and 490 x 0.36875 = 180.6875 round up; 1.8 gives 146.25 and 110.25.
GAME_CELLS = ([240, 181], [146, 110])
ICON_PX = 512
ICONS = (
    {"id": "icon-128", "target_size_px": [128, 128]},
    {"id": "icon-256", "target_size_px": [256, 256]},
    {"id": "icon-256-x2", "target_size_px": [256, 256], "integer_zoom": 2},
)
HAMMING = "a Hamming preview is its own filter's, not bicubic's, at the disc's edge"
# N-02's budget, gated on the first render and on the p95 of the renders after it.
N02_SIZE = 2000
N02_RENDERS = 20
N02_BUDGET_S = 2.0


def arguments(sources: list[dict[str, Any]], recipes: Any, **changes: Any) -> dict[str, Any]:
    return {
        "recipes": list(recipes),
        "filter": "lanczos",
        "sources": sources,
        "overlays": [],
        "backgrounds": [RIVER],
        **changes,
    }


def source(document_id: str, **changes: Any) -> dict[str, Any]:
    return {"document_id": document_id, "frame": 0, "target": "composite", **changes}


def master_stack() -> tuple[fixtures.Layer, ...]:
    width, height = MASTER_PX
    return (
        fixtures.Layer("probe sun", fixtures.rect(150, 150, (240, 160, 30)), x=400, y=250),
        fixtures.Layer("probe hull", fixtures.rect(200, 150, (200, 60, 90)), x=100, y=100),
        fixtures.Layer("probe base", fixtures.rect(width, height, BASE)),
    )


async def run(report: Report, a: Client, harness: Path) -> None:
    harness = Path(os.path.realpath(harness))
    folder = harness / "previews"
    folder.mkdir(exist_ok=True)
    master, icon = folder / "master.ora", folder / "icon.ora"
    fixtures.write_ora(master, master_stack(), *MASTER_PX)
    disc = np.zeros((ICON_PX, ICON_PX, 4), dtype=np.uint8)
    ys, xs = np.indices((ICON_PX, ICON_PX))
    disc[(xs - 256) ** 2 + (ys - 256) ** 2 < 200**2] = (167, 194, 132, 255)
    fixtures.write_ora(icon, (fixtures.Layer("probe icon", disc),), ICON_PX, ICON_PX)
    await _game(report, a, master, harness)
    await _icons(report, a, icon, harness)
    await _overlays(report, a, master, harness)
    await _n02(report, a, folder, harness)


async def _game(report: Report, a: Client, master: Path, harness: Path) -> None:
    opened = await open_working(a, master, harness, "previews")
    document_id = opened.get("document_id")
    name = "the first game's recipes: 2.95 and 1.8 px per unit from a 2x master exported at 4"
    if opened.get("status") != "completed" or not document_id:
        report.check(name, False, str(opened.get("error")))
        return
    try:
        rendered = await tool(
            a,
            TOOL,
            arguments(
                [source(document_id)],
                GAME,
                export_pixels_per_unit=EXPORT_PER_UNIT,
                master_to_export_scale=0.5,
            ),
        )
        found = (rendered.get("data") or {}).get("sheets") or []
        problems = [] if len(found) == 2 else [f"{code(rendered) or len(found)} sheets"]
        width, height = MASTER_PX
        for sheet, want in zip(found, GAME_CELLS, strict=False):
            column = sheet["columns"][0]
            exact = [want[0] / width, 0, 0, 0, want[1] / height, 0]
            if sheet["cell_px"] != want or column["image_px"] != want:
                problems.append(f"{sheet['recipe_id']}: cell {sheet['cell_px']}, not {want}")
            if column["document_to_cell"] != exact or column["filter"] != "lanczos":
                problems.append(f"{sheet['recipe_id']}: transform {column['document_to_cell']}")
            # Deep inside the flat base, far from either shape and the filter's reach.
            if tuple(sheet_cell(sheet, 0)[20, 20][:3]) != BASE:
                problems.append(
                    f"{sheet['recipe_id']}: the base reads {sheet_cell(sheet, 0)[20, 20]}"
                )
        report.check(
            name,
            not problems,
            "; ".join(problems) or ", ".join(f"{s['recipe_id']} {s['cell_px']}" for s in found),
        )
    finally:
        await close(a, document_id)


async def _icons(report: Report, a: Client, icon: Path, harness: Path) -> None:
    opened = await open_working(a, icon, harness, "previews")
    document_id = opened.get("document_id")
    name = "128 / 256 px icons fit their boxes, and integer_zoom 2 replicates the 256 px one"
    if opened.get("status") != "completed" or not document_id:
        report.check(name, False, str(opened.get("error")))
        report.check(HAMMING, False, str(opened.get("error")))
        return
    try:
        await _boxes(report, a, document_id, name)
        await _hamming(report, a, document_id)
    finally:
        await close(a, document_id)


async def _boxes(report: Report, a: Client, document_id: str, name: str) -> None:
    rendered = await tool(
        a, TOOL, arguments([source(document_id)], ICONS, backgrounds=["transparent"])
    )
    found = (rendered.get("data") or {}).get("sheets") or []
    if len(found) != 3:
        report.check(name, False, f"{code(rendered) or len(found)} sheets")
        return
    sizes = [sheet["cell_px"] for sheet in found]
    replicated = np.repeat(np.repeat(sheet_cell(found[1], 0), 2, axis=0), 2, axis=1)
    problem = differs(sheet_cell(found[2], 0), replicated)
    transforms = [sheet["columns"][0]["document_to_cell"][0] for sheet in found]
    report.check(
        name,
        sizes == [[128, 128], [256, 256], [512, 512]]
        and transforms == [0.25, 0.5, 1]
        and not problem,
        f"cells {sizes}, scales {transforms}" + (f"; {problem}" if problem else ""),
    )


async def _hamming(report: Report, a: Client, document_id: str) -> None:
    cells = {}
    for chosen in ("hamming", "bicubic"):
        rendered = await tool(
            a,
            TOOL,
            arguments([source(document_id)], ICONS[:1], filter=chosen, backgrounds=["transparent"]),
        )
        [sheet] = (rendered.get("data") or {}).get("sheets") or [None]
        if sheet is None or sheet["columns"][0]["filter"] != chosen:
            report.check(HAMMING, False, f"{chosen}: {code(rendered) or 'another filter'}")
            return
        cells[chosen] = sheet_cell(sheet, 0)
    problem = differs(cells["hamming"], cells["bicubic"])
    same_shape = cells["hamming"].shape == cells["bicubic"].shape
    report.check(HAMMING, same_shape and bool(problem), problem or "the two cells are equal")


async def _overlays(report: Report, a: Client, master: Path, harness: Path) -> None:
    opened = await open_working(a, master, harness, "previews")
    document_id = opened.get("document_id")
    name = "a selection overlay is drawn into the sheet only, never the clean sheet or the document"
    if opened.get("status") != "completed" or not document_id:
        report.check(name, False, str(opened.get("error")))
        return
    try:
        selected = await tool(
            a,
            "krita_selection_set",
            {
                "guard": guard(document_id),
                "combine": "replace",
                "shape": {"type": "rect", "rect": {"x": 120, "y": 80, "width": 300, "height": 200}},
                "feather_px": 0,
                "invert": False,
            },
        )
        whole = {"x": 0, "y": 0, "width": MASTER_PX[0], "height": MASTER_PX[1]}
        before = await capture(a, document_id, whole)
        rendered = await tool(
            a,
            TOOL,
            arguments(
                [source(document_id)],
                GAME[:1],
                export_pixels_per_unit=EXPORT_PER_UNIT,
                master_to_export_scale=0.5,
                overlays=["selection", "allowed_mask"],
            ),
        )
        after = await capture(a, document_id, whole)
        [sheet] = (rendered.get("data") or {}).get("sheets") or [None]
        if sheet is None or sheet["clean_image"] is None or selected.get("status") != "completed":
            report.check(name, False, f"{code(selected)} / {code(rendered)}")
            return
        drawn, clean = sheet_cell(sheet, 0), sheet_cell(sheet, 0, clean=True)
        changed = (drawn != clean).any(axis=-1)
        colours = {tuple(pixel[:3]) for pixel in drawn[changed]}
        unchanged = differs(after, before)
        report.check(
            name,
            bool(changed.any())
            and colours == {sheets.OVERLAY_RGB["selection"]}
            and sheet["columns"][0]["overlays"] == ["selection"]
            and not unchanged,
            f"{int(changed.sum())} outline pixels"
            + (f"; the document {unchanged}" if unchanged else ""),
        )
    finally:
        await close(a, document_id)


def n02_master(size: int) -> fixtures.Layer:
    # Painted-looking: smooth gradients with a low ripple, so PNG works as it would on art.
    ys, xs = np.indices((size, size), dtype=np.float64)
    ripple = 18 * np.sin(xs / 37) * np.cos(ys / 53)
    pixels = np.empty((size, size, 4), dtype=np.uint8)
    pixels[..., 0] = np.clip(30 + xs / size * 190 + ripple, 0, 255)
    pixels[..., 1] = np.clip(60 + ys / size * 150 - ripple, 0, 255)
    pixels[..., 2] = np.clip(200 - (xs + ys) / size * 70 + ripple / 2, 0, 255)
    pixels[..., 3] = 255
    return fixtures.Layer("probe painting", pixels)


async def _n02(report: Report, a: Client, folder: Path, harness: Path) -> None:
    size = N02_SIZE
    master = folder / "n-02.ora"
    shapes = (
        fixtures.Layer("probe hull", fixtures.rect(700, 500, (200, 60, 90)), x=300, y=900),
        fixtures.Layer("probe sun", fixtures.rect(400, 400, (240, 160, 30)), x=1300, y=300),
    )
    fixtures.write_sparse_ora(master, (*shapes, n02_master(size)), size, size)
    opened = await open_working(a, master, harness, "previews")
    document_id = opened.get("document_id")
    if opened.get("status") != "completed" or not document_id:
        report.check("N-02's master opens", False, str(opened.get("error")))
        return
    baseline = opened["data"]["baseline_id"]
    asked = arguments(
        [source(document_id, baseline_id=baseline)],
        GAME,
        export_pixels_per_unit=EXPORT_PER_UNIT,
        master_to_export_scale=1,
    )
    budget = N02_BUDGET_S
    try:
        started = time.perf_counter()
        first = await tool(a, TOOL, asked)
        first_s = time.perf_counter() - started
        sheets_ = (first.get("data") or {}).get("sheets") or []
        sizes = ", ".join(
            f"{s['recipe_id']} {s['size_px'][0]} x {s['size_px'][1]}" for s in sheets_
        )
        report.check(
            f"N-02: the first render, reading the baseline from the file, under {budget} s",
            first.get("status") == "completed" and first_s < budget,
            f"{first_s:.2f} s, {code(first) or sizes}",
        )
        took, failures = [], []
        for index in range(N02_RENDERS):
            started = time.perf_counter()
            done = await tool(a, TOOL, asked)
            took.append(time.perf_counter() - started)
            if done.get("status") != "completed":
                failures.append(f"render {index}: {code(done) or done.get('status')}")
        p95 = statistics.quantiles(took, n=20)[18]
        inline = [s["inline"] for s in sheets_]
        report.check(
            f"N-02: {N02_RENDERS} renders of two recipes on a {size} x {size} master, as "
            f"opened beside now, p95 under {budget} s",
            not failures and p95 < budget,
            f"p95 {p95:.2f} s, mean {statistics.mean(took):.2f} s, max {max(took):.2f} s, "
            f"inline {inline}; " + "; ".join(failures[:3]),
        )
    finally:
        await close(a, document_id)
