import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np
from PIL import Image

from krita_art_mcp import colour, imaging
from krita_art_mcp.transfer import Pixels

GUTTER_PX = 8
GUTTER = (128, 128, 128, 255)
MAX_SHEET_PX = 4096
# Drawn over the cells only, never into a clean sheet or the document.
OVERLAY_RGB = {"selection": (255, 0, 255), "allowed_mask": (0, 255, 255)}
AS_OPENED, CURRENT = "as_opened", "current"
# A source's fields that name what it shows, not how; the recipe hash leaves them out.
IDENTITY = ("document_id", "frame", "layer_id", "baseline_id")


class Refused(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


@dataclass(frozen=True)
class Source:
    # One source as read: its crop, its anchor, and the values a world-unit recipe scales it by.
    document_id: str
    target: str
    layer_id: str | None
    baseline_id: str | None
    profile_id: str
    rect: dict[str, int]
    anchor: tuple[float, float]
    export_pixels_per_unit: float | None
    master_to_export_scale: float | None


@dataclass(frozen=True)
class Placed:
    # One source in one recipe's cell, in game pixels, before the zoom.
    scale: float
    size: tuple[int, int]
    offset: tuple[int, int]


@dataclass(frozen=True)
class Row:
    background: Any
    tint: dict[str, Any] | None
    greyscale: bool


@dataclass(frozen=True)
class Layout:
    recipe: dict[str, Any]
    zoom: int
    # In game pixels; the sheet multiplies it by the zoom.
    cell: tuple[int, int]
    placed: list[Placed]
    columns: list[tuple[int, str]]
    rows: list[Row]
    size: tuple[int, int]


@dataclass(frozen=True)
class Sheet:
    image: Image.Image
    # The sheet without its overlays; None when none was drawn.
    clean: Image.Image | None
    data: dict[str, Any]


def check_anchor(index: int, rect: Mapping[str, int], anchor: Any) -> tuple[float, float]:
    x, y = anchor
    inside = (
        math.isfinite(x)
        and math.isfinite(y)
        and rect["x"] <= x <= rect["x"] + rect["width"]
        and rect["y"] <= y <= rect["y"] + rect["height"]
    )
    if not inside:
        details = {"source": index, "anchor_px": [x, y], "rect": dict(rect)}
        message = f"Source {index}'s anchor_px is outside its crop."
        raise Refused("INVALID_ARGUMENT", message, details)
    return float(x), float(y)


def sources_of(arguments: dict[str, Any], read: list[dict[str, Any]]) -> list[Source]:
    # Each source's own values win over the top-level defaults.
    found = []
    for index, (given, got) in enumerate(zip(arguments["sources"], read, strict=True)):
        rect = got["rect"]
        centre = (rect["x"] + rect["width"] / 2, rect["y"] + rect["height"] / 2)
        found.append(
            Source(
                document_id=got["document_id"],
                target=got["target"],
                layer_id=got["layer_id"],
                baseline_id=given.get("baseline_id"),
                profile_id=got["profile_id"],
                rect=rect,
                anchor=check_anchor(index, rect, given.get("anchor_px", centre)),
                export_pixels_per_unit=given.get(
                    "export_pixels_per_unit", arguments.get("export_pixels_per_unit")
                ),
                master_to_export_scale=given.get(
                    "master_to_export_scale", arguments.get("master_to_export_scale")
                ),
            )
        )
    return found


def scaled(recipe: dict[str, Any], source: Source, index: int) -> tuple[float, tuple[int, int]]:
    width, height = source.rect["width"], source.rect["height"]
    if "target_size_px" in recipe:
        # A fit, in integers: the side that binds is exact, the other rounds half up.
        box_w, box_h = recipe["target_size_px"]
        if box_w * height <= box_h * width:
            scale, size = box_w / width, (box_w, _half_up(height * box_w, width))
        else:
            scale, size = box_h / height, (_half_up(width * box_h, height), box_h)
    else:
        units, master = source.export_pixels_per_unit, source.master_to_export_scale
        if units is None or master is None:
            details = {"source": index, "recipe_id": recipe["id"]}
            message = (
                f"Source {index} needs export_pixels_per_unit and master_to_export_scale for the "
                f"world-unit recipe {recipe['id']!r} (1 when the document is at export size)."
            )
            raise Refused("INVALID_ARGUMENT", message, details)
        scale = recipe["target_pixels_per_unit"] / units * master
        if not math.isfinite(scale):
            raise Refused("INVALID_ARGUMENT", f"Source {index}'s scale is not a finite number.")
        size = (colour.half_up(width * scale), colour.half_up(height * scale))
    if min(size) < 1:
        details = {"source": index, "recipe_id": recipe["id"]}
        message = f"Source {index} would be under 1 px on a side in recipe {recipe['id']!r}."
        raise Refused("INVALID_ARGUMENT", message, details)
    return scale, size


def layout(
    recipe: dict[str, Any],
    sources: list[Source],
    backgrounds: list[Any],
    tints: list[dict[str, Any]],
    greyscale: bool,
) -> Layout:
    zoom = recipe.get("integer_zoom", 1)
    fits = [scaled(recipe, source, index) for index, source in enumerate(sources)]
    # Each anchor in game pixels from its image's corner, after rounding.
    anchors = [
        (
            (source.anchor[0] - source.rect["x"]) * size[0] / source.rect["width"],
            (source.anchor[1] - source.rect["y"]) * size[1] / source.rect["height"],
        )
        for source, (_, size) in zip(sources, fits, strict=True)
    ]
    if "target_size_px" in recipe:
        cell = (recipe["target_size_px"][0], recipe["target_size_px"][1])
        offsets = [
            (colour.half_up(cell[0] / 2 - x), colour.half_up(cell[1] / 2 - y)) for x, y in anchors
        ]
        for index, ((_, size), offset) in enumerate(zip(fits, offsets, strict=True)):
            if not all(0 <= offset[a] and offset[a] + size[a] <= cell[a] for a in (0, 1)):
                details = {"source": index, "recipe_id": recipe["id"]}
                message = (
                    f"Source {index}'s anchor puts it outside the {cell[0]} x {cell[1]} box of "
                    f"recipe {recipe['id']!r}."
                )
                raise Refused("INVALID_ARGUMENT", message, details)
    else:
        lefts = [colour.half_up(x) for x, _ in anchors]
        tops = [colour.half_up(y) for _, y in anchors]
        offsets = [
            (max(lefts) - left, max(tops) - top) for left, top in zip(lefts, tops, strict=True)
        ]
        cell = (
            max(offset[0] + size[0] for (_, size), offset in zip(fits, offsets, strict=True)),
            max(offset[1] + size[1] for (_, size), offset in zip(fits, offsets, strict=True)),
        )
    placed = [
        Placed(scale, size, offset) for (scale, size), offset in zip(fits, offsets, strict=True)
    ]
    columns = [
        (index, state)
        for index, source in enumerate(sources)
        for state in ((AS_OPENED, CURRENT) if source.baseline_id is not None else (CURRENT,))
    ]
    rows = [
        Row(background, tint, grey)
        for background in backgrounds
        for tint in [None, *tints]
        for grey in ((False, True) if greyscale else (False,))
    ]
    width = GUTTER_PX + len(columns) * (cell[0] * zoom + GUTTER_PX)
    height = GUTTER_PX + len(rows) * (cell[1] * zoom + GUTTER_PX)
    if max(width, height) > MAX_SHEET_PX:
        details = {"recipe_id": recipe["id"], "size_px": [width, height]}
        message = (
            f"Recipe {recipe['id']!r}'s sheet would be {width} x {height} px, over {MAX_SHEET_PX} "
            "on its long edge; ask for fewer sources, backgrounds or tints, a crop_rect, or a "
            "smaller integer_zoom."
        )
        raise Refused("INVALID_ARGUMENT", message, details)
    return Layout(recipe, zoom, cell, placed, columns, rows, (width, height))


def document_to_cell(source: Source, placed: Placed, zoom: int) -> list[int | float]:
    # Exact after rounding: the effective scale on each axis, the offset, then the zoom.
    rect = source.rect
    sx, sy = placed.size[0] / rect["width"], placed.size[1] / rect["height"]
    values = [
        zoom * sx,
        0.0,
        zoom * (placed.offset[0] - sx * rect["x"]),
        0.0,
        zoom * sy,
        zoom * (placed.offset[1] - sy * rect["y"]),
    ]
    return [_exact(value) for value in values]


def recipe_sha256(recipe: dict[str, Any], arguments: dict[str, Any]) -> str:
    # Everything that decides a sheet beside the pixels it shows: which documents, layers and
    # baselines are not part of it, how each source is cropped, anchored and scaled is.
    sources = [
        {
            **{key: value for key, value in given.items() if key not in IDENTITY},
            "as_opened": "baseline_id" in given,
        }
        for given in arguments["sources"]
    ]
    canonical = {
        "recipe": recipe,
        "filter": arguments["filter"],
        "backgrounds": arguments["backgrounds"],
        "tints": arguments.get("tints", []),
        "greyscale": arguments.get("greyscale", False),
        "overlays": arguments["overlays"],
        "export_pixels_per_unit": arguments.get("export_pixels_per_unit"),
        "master_to_export_scale": arguments.get("master_to_export_scale"),
        "sources": sources,
    }
    text = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def render(
    arguments: dict[str, Any],
    sources: list[Source],
    crops: dict[tuple[int, str], Pixels],
    masks: dict[int, dict[str, Pixels]],
) -> list[Sheet]:
    # crops are RGBA, by (source index, state); masks one byte per pixel, by source index.
    layouts = [
        layout(
            recipe,
            sources,
            arguments["backgrounds"],
            arguments.get("tints", []),
            arguments.get("greyscale", False),
        )
        for recipe in arguments["recipes"]
    ]
    return [_sheet(found, arguments, sources, crops, masks) for found in layouts]


def _sheet(
    found: Layout,
    arguments: dict[str, Any],
    sources: list[Source],
    crops: dict[tuple[int, str], Pixels],
    masks: dict[int, dict[str, Pixels]],
) -> Sheet:
    zoom, cell = found.zoom, found.cell
    step_x, step_y = cell[0] * zoom + GUTTER_PX, cell[1] * zoom + GUTTER_PX
    sheet = np.empty((found.size[1], found.size[0], 4), dtype=np.uint8)
    sheet[...] = GUTTER
    bases = [_base(row.background, cell) for row in found.rows]
    outlines = {
        index: {
            name: edge
            for name, mask in masks.get(index, {}).items()
            if (edge := _outline(mask, found.placed[index].size)).any()
        }
        for index in range(len(sources))
    }
    # A clean sheet only when some outline is drawn; otherwise the sheet is clean.
    clean = sheet.copy() if any(outlines.values()) else None
    columns = []
    for column, (index, state) in enumerate(found.columns):
        source, placed = sources[index], found.placed[index]
        art, applied = _resampled(crops[(index, state)], placed.size, arguments["filter"])
        x = GUTTER_PX + column * step_x
        for number, row in enumerate(found.rows):
            y = GUTTER_PX + number * step_y
            box = (slice(y, y + cell[1] * zoom), slice(x, x + cell[0] * zoom))
            painted = _treated(bases[number], cell, art, placed.offset, row)
            zoomed = _zoomed(painted, zoom)
            if clean is not None:
                clean[box] = zoomed
            for name, edge in outlines[index].items():
                left, top = placed.offset
                region = painted[top : top + placed.size[1], left : left + placed.size[0]]
                region[edge] = (*OVERLAY_RGB[name], 255)
            if outlines[index]:
                zoomed = _zoomed(painted, zoom)
            sheet[box] = zoomed
        columns.append(_column(x, index, state, source, placed, found, applied, outlines[index]))
    rows = [
        {
            "y_px": GUTTER_PX + number * step_y,
            "background": row.background,
            "tint": None if row.tint is None else row.tint["id"],
            "greyscale": row.greyscale,
        }
        for number, row in enumerate(found.rows)
    ]
    recipe = found.recipe
    data = {
        "recipe_id": recipe["id"],
        "recipe_sha256": recipe_sha256(recipe, arguments),
        "target_pixels_per_unit": recipe.get("target_pixels_per_unit"),
        "target_size_px": recipe.get("target_size_px"),
        "integer_zoom": zoom,
        "filter": arguments["filter"],
        "size_px": list(found.size),
        "cell_px": [cell[0] * zoom, cell[1] * zoom],
        "gutter_px": GUTTER_PX,
        "columns": columns,
        "rows": rows,
    }
    return Sheet(_image(sheet), None if clean is None else _image(clean), data)


def _column(
    x: int,
    index: int,
    state: str,
    source: Source,
    placed: Placed,
    found: Layout,
    applied: str | None,
    outlines: dict[str, np.ndarray],
) -> dict[str, Any]:
    zoom = found.zoom
    world = "target_pixels_per_unit" in found.recipe
    return {
        "x_px": x,
        "source_index": index,
        "document_id": source.document_id,
        "target": source.target,
        "layer_id": source.layer_id,
        "state": state,
        "baseline_id": source.baseline_id,
        "profile_id": source.profile_id,
        "source_rect": source.rect,
        "anchor_px": [_exact(source.anchor[0]), _exact(source.anchor[1])],
        "export_pixels_per_unit": source.export_pixels_per_unit if world else None,
        "master_to_export_scale": source.master_to_export_scale if world else None,
        "scale": placed.scale,
        "image_px": [placed.size[0] * zoom, placed.size[1] * zoom],
        "offset_px": [placed.offset[0] * zoom, placed.offset[1] * zoom],
        "filter": applied,
        "document_to_cell": document_to_cell(source, placed, zoom),
        "overlays": list(outlines),
    }


def _resampled(pixels: Pixels, size: tuple[int, int], name: str) -> tuple[Image.Image, str | None]:
    # Once, from the native crop; None when the size is native.
    image = Image.fromarray(np.ascontiguousarray(pixels))
    if image.size == size:
        return image, None
    return image.resize(size, imaging.FILTERS[name]), name


def _base(background: Any, cell: tuple[int, int]) -> Image.Image | None:
    # None for a transparent cell, which takes the art's pixels as they are.
    return None if background == "transparent" else imaging.background(background, cell)


def _treated(
    base: Image.Image | None,
    size: tuple[int, int],
    art: Image.Image,
    offset: tuple[int, int],
    row: Row,
) -> Pixels:
    # Over the background, then tinted as a whole, then grey; alpha is kept.
    if base is None:
        cell = Image.new("RGBA", size, (0, 0, 0, 0))
        cell.paste(art, offset)
    else:
        cell = base.copy()
        cell.alpha_composite(art, dest=offset)
    pixels = np.array(cell)
    if row.tint is not None:
        rgb = pixels[..., :3] / 255 * np.array(row.tint["multiply"]) + np.array(row.tint["add"])
        pixels[..., :3] = np.floor(np.clip(rgb, 0, 1) * 255 + 0.5).astype(np.uint8)
    if row.greyscale:
        pixels[..., :3] = imaging.lightness(pixels)[..., None]
    return pixels


def _outline(mask: Pixels, size: tuple[int, int]) -> np.ndarray:
    # The region's edge pixels at game size; the crop's own border is never an edge.
    image = Image.fromarray(np.ascontiguousarray(mask))
    if image.size != size:
        image = image.resize(size, Image.Resampling.BOX)
    inside = np.asarray(image) >= 128
    padded = np.pad(inside, 1, mode="edge")
    interior = padded[:-2, 1:-1] & padded[2:, 1:-1] & padded[1:-1, :-2] & padded[1:-1, 2:]
    edge: np.ndarray = inside & ~interior
    return edge


def _zoomed(pixels: Pixels, zoom: int) -> Pixels:
    # Pixel replication: each game pixel becomes zoom x zoom, and no value is new.
    if zoom == 1:
        return pixels
    return np.repeat(np.repeat(pixels, zoom, axis=0), zoom, axis=1)


def _image(pixels: Pixels) -> Image.Image:
    image = Image.fromarray(pixels)
    return image.convert("RGB") if (pixels[..., 3] == 255).all() else image


def _exact(value: float) -> int | float:
    # Whole numbers as integers, the rest unrounded.
    return int(value) if float(value).is_integer() else value


def _half_up(numerator: int, denominator: int) -> int:
    return (2 * numerator + denominator) // (2 * denominator)
