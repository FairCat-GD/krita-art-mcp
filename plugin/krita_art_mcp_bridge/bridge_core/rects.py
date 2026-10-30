from collections.abc import Iterable

from .errors import BridgeError


def union(rects: Iterable[dict[str, int] | None]) -> dict[str, int] | None:
    # The canvas rect around every non-empty rect given; None when there is none.
    found = [
        rect for rect in rects if rect is not None and rect["width"] > 0 and rect["height"] > 0
    ]
    if not found:
        return None
    left = min(rect["x"] for rect in found)
    top = min(rect["y"] for rect in found)
    right = max(rect["x"] + rect["width"] for rect in found)
    bottom = max(rect["y"] + rect["height"] for rect in found)
    return {"x": left, "y": top, "width": right - left, "height": bottom - top}


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
