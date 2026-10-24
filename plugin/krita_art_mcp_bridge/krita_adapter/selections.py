from collections.abc import Callable
from typing import Any

from krita import Selection

from ..bridge_core.errors import BridgeError


def commit(document: Any, recipe: list[tuple[Any, ...]], node: Callable[[Any, str], Any]) -> None:
    # Runs the core's recipe in its order and commits the result with setSelection, one undo
    # step (K8). The live selection is only ever duplicated, never changed (K23).
    if recipe == [("clear",)]:
        document.setSelection(None)
        document.waitForDone()
        return
    shape: Any = None
    for step in recipe:
        kind = step[0]
        if kind == "mask":
            rect, data = step[1], step[2]
            shape = _from_mask(data, rect["x"], rect["y"], rect["width"], rect["height"])
        elif kind == "all":
            rect = step[1]
            shape = Selection()
            shape.select(rect["x"], rect["y"], rect["width"], rect["height"], 255)
        elif kind == "layer_alpha":
            shape = _layer_alpha(document, node(document, step[1]))
        elif kind == "grow":
            shape.grow(step[1], step[1])
        elif kind == "shrink":
            shape.shrink(step[1], step[1], False)
        elif kind == "feather":
            shape.feather(step[1])
        elif kind == "invert":
            shape.invert()
        elif kind == "combine":
            shape = _combined(document, shape, step[1])
        else:
            raise BridgeError("INTERNAL_ERROR", f"Unknown selection step {kind!r}.")
    document.setSelection(shape)
    document.waitForDone()


def _from_mask(data: bytes, x: int, y: int, width: int, height: int) -> Any:
    # The plugin's one setPixelData call: one byte per pixel into a selection it has just made,
    # never into a layer (invariant 1, K11).
    selection = Selection()
    selection.setPixelData(data, x, y, width, height)
    return selection


def _layer_alpha(document: Any, layer: Any) -> Any:
    # The layer's own alpha (K12), over its bounds on the canvas.
    document.waitForDone()
    bounds = layer.bounds()
    left, top = max(0, int(bounds.x())), max(0, int(bounds.y()))
    right = min(int(document.width()), int(bounds.x()) + int(bounds.width()))
    bottom = min(int(document.height()), int(bounds.y()) + int(bounds.height()))
    if right <= left or bottom <= top:
        return Selection()
    width, height = right - left, bottom - top
    pixels = bytes(layer.pixelData(left, top, width, height))
    # Integer RGBA is stored B, G, R, A.
    return _from_mask(pixels[3::4], left, top, width, height)


def _combined(document: Any, shape: Any, mode: str) -> Any:
    current = document.selection()
    if mode == "replace" or current is None:
        return shape
    combined = current.duplicate()
    if mode == "add":
        combined.add(shape)
    elif mode == "subtract":
        combined.subtract(shape)
    else:
        combined.intersect(shape)
    return combined
