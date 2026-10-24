from pathlib import Path
from typing import Any

from . import paths, roots, transfer
from .errors import BridgeError

MASK_FIELDS = {"origin_px", "mask", "source_path"}


def check(value: Any, field: str) -> dict[str, Any]:
    # A mask the server rasterised or read: {origin_px, mask (a transfer description),
    # source_path (the PNG's realpath, or None)}.
    if (
        not isinstance(value, dict)
        or set(value) != MASK_FIELDS
        or not isinstance(value["origin_px"], list)
        or len(value["origin_px"]) != 2
        or not all(_whole(side) for side in value["origin_px"])
        or not (value["source_path"] is None or isinstance(value["source_path"], str))
    ):
        raise BridgeError("INVALID_ARGUMENT", f"{field} is not a mask the server sent.")
    return value


def take(data: Path, value: dict[str, Any], request_id: str) -> bytes:
    return transfer.take_mask(paths.transfer_dir(data), value["mask"], request_id)


def source(data: Path, value: dict[str, Any], field: str) -> None:
    # Invariant 3 on the plugin's side too; the plugin never opens the file.
    if value["source_path"] is not None:
        roots.check(data, value["source_path"], field)


def box(value: dict[str, Any]) -> dict[str, int]:
    width, height = value["mask"]["size_px"]
    x, y = value["origin_px"]
    return {"x": x, "y": y, "width": width, "height": height}


def inside(rect: dict[str, int], size: list[int], field: str) -> None:
    # Off the canvas is refused, never clipped.
    if (
        rect["x"] < 0
        or rect["y"] < 0
        or rect["width"] < 1
        or rect["height"] < 1
        or rect["x"] + rect["width"] > size[0]
        or rect["y"] + rect["height"] > size[1]
    ):
        details = {"field": field, "rect": rect, "canvas_px": size}
        message = f"{field} reaches outside the canvas."
        raise BridgeError("INVALID_ARGUMENT", message, False, details)


def on_canvas(data: bytes, rect: dict[str, int], size: list[int]) -> bytes:
    # The mask placed in a buffer of one byte per canvas pixel, row by row.
    canvas = bytearray(size[0] * size[1])
    width = rect["width"]
    for row in range(rect["height"]):
        start = (rect["y"] + row) * size[0] + rect["x"]
        canvas[start : start + width] = data[row * width : (row + 1) * width]
    return bytes(canvas)


def _whole(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)
