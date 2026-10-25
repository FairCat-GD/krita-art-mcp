import io
import xml.etree.ElementTree as ElementTree
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

from krita_art_mcp.transfer import Pixels

# What a harness fixture holds is fictional: flat rectangles in colours whose red and blue
# differ, so a missed B, G, R, A swap shows.
WIDTH, HEIGHT = 64, 48
PAINT_WIDTH, PAINT_HEIGHT = 160, 96
# Past the strokes' area on each side: more than any benchmark stroke's region reaches.
BENCHMARK_PAD = 96


@dataclass(frozen=True)
class Layer:
    name: str
    # Straight-alpha RGBA of the layer's own size; None for a group.
    pixels: Pixels | None = None
    x: int = 0
    y: int = 0
    opacity: float = 1.0
    visible: bool = True
    composite_op: str = "svg:src-over"
    locked: bool = False
    # A group's layers, top first, as ORA lists them.
    children: tuple["Layer", ...] = field(default_factory=tuple)

    @property
    def is_group(self) -> bool:
        return self.pixels is None


def rect(width: int, height: int, rgb: tuple[int, int, int]) -> Pixels:
    pixels = np.zeros((height, width, 4), dtype=np.uint8)
    pixels[...] = (*rgb, 255)
    return pixels


def probe_stack() -> tuple[Layer, ...]:
    # Top first. The hidden layer carries what an exact composite cannot (opacity, multiply);
    # everything visible is opaque or empty, so Krita's composite is exact.
    base = np.zeros((HEIGHT, WIDTH, 4), dtype=np.uint8)
    base[40:, :] = (10, 120, 220, 255)
    return (
        Layer(
            "probe hidden",
            rect(WIDTH, HEIGHT, (90, 40, 200)),
            opacity=0.5,
            visible=False,
            composite_op="svg:multiply",
        ),
        Layer(
            "probe group",
            children=(
                Layer(
                    "probe clip",
                    rect(24, 24, (240, 30, 60)),
                    x=20,
                    y=10,
                    composite_op="svg:src-atop",
                ),
                Layer("probe shape", rect(20, 16, (167, 194, 132)), x=8, y=12),
            ),
        ),
        Layer("probe locked", rect(12, 12, (32, 64, 200)), x=44, y=30, locked=True),
        Layer("probe base", base),
    )


def update_stack() -> tuple[Layer, ...]:
    # Top first: a group holding a layer, an editable rect, and an opaque base, all flat.
    return (
        Layer(
            "probe group", children=(Layer("probe inner", rect(6, 6, (90, 200, 40)), x=50, y=36),)
        ),
        Layer("probe paint", rect(24, 16, (200, 40, 90)), x=8, y=8),
        Layer("probe base", rect(WIDTH, HEIGHT, (30, 110, 200))),
    )


def rim_stack() -> tuple[Layer, ...]:
    # A silhouette whose edge fades through two rings of partial alpha, and a hidden recolour
    # layer that covers it and spills past it, on a transparent canvas.
    silhouette = np.zeros((HEIGHT, WIDTH, 4), dtype=np.uint8)
    for inset, alpha in ((0, 64), (1, 160), (2, 255)):
        silhouette[12 + inset : 36 - inset, 16 + inset : 48 - inset] = (40, 160, 90, alpha)
    return (
        Layer("probe recolour", rect(48, 36, (230, 60, 30)), x=8, y=6, visible=False),
        Layer("probe silhouette", silhouette),
    )


def paint_stack() -> tuple[Layer, ...]:
    # The paint checks' canvas: an opaque base under the strokes.
    return (Layer("probe base", rect(PAINT_WIDTH, PAINT_HEIGHT, (30, 110, 200))),)


def benchmark_stack(count: int, area: dict[str, int]) -> tuple[Layer, ...]:
    # Opaque squares each covering the strokes' area and its margin, so every protected layer is
    # read over the whole of each stroke's region; the rest of the canvas stays empty, so the
    # file stays small.
    pad = BENCHMARK_PAD
    side = max(area["width"], area["height"]) + 2 * pad
    layers = []
    for index in range(count):
        colour = (40 + index * 7 % 200, 200 - index * 5 % 150, 90 + index * 3 % 120)
        x, y = area["x"] - pad - index % 4, area["y"] - pad - index % 3
        layers.append(Layer(f"probe bench {index}", rect(side, side, colour), x=x, y=y))
    return tuple(reversed(layers))


def composite(layers: tuple[Layer, ...], width: int = WIDTH, height: int = HEIGHT) -> Pixels:
    # Straight-alpha src-over and src-atop, rounded once; exact wherever alpha is 0 or 255.
    canvas = _stack(layers, width, height)
    return np.rint(canvas).astype(np.uint8)


def write_ora(
    path: Path, layers: tuple[Layer, ...], width: int = WIDTH, height: int = HEIGHT
) -> Pixels:
    merged = composite(layers, width, height)
    image = ElementTree.Element("image", {"version": "0.0.3", "w": str(width), "h": str(height)})
    files: dict[str, bytes] = {}
    _xml(ElementTree.SubElement(image, "stack"), layers, files)
    stack = ElementTree.tostring(image, encoding="UTF-8", xml_declaration=True)
    thumbnail = Image.fromarray(merged)
    thumbnail.thumbnail((256, 256))
    with zipfile.ZipFile(path, "x") as archive:
        # The mimetype comes first and uncompressed, as OpenRaster requires.
        archive.writestr("mimetype", "image/openraster", compress_type=zipfile.ZIP_STORED)
        archive.writestr("stack.xml", stack, compress_type=zipfile.ZIP_DEFLATED)
        for name, data in files.items():
            archive.writestr(name, data, compress_type=zipfile.ZIP_DEFLATED)
        archive.writestr("mergedimage.png", _png(merged), compress_type=zipfile.ZIP_DEFLATED)
        archive.writestr("Thumbnails/thumbnail.png", _png(np.asarray(thumbnail)))
    return merged


def write_sparse_ora(path: Path, layers: tuple[Layer, ...], width: int, height: int) -> None:
    # For large canvases: each layer is stored at its own size and the merged image is built in
    # 8 bits, never as a float canvas. Paint layers only, composited src-over.
    if any(layer.pixels is None or layer.composite_op != "svg:src-over" for layer in layers):
        raise ValueError("a sparse fixture holds src-over paint layers only")
    merged = Image.new("RGBA", (width, height))
    for layer in reversed(layers):
        if layer.visible and layer.pixels is not None:
            tile = Image.fromarray(layer.pixels)
            box = (layer.x, layer.y, layer.x + tile.width, layer.y + tile.height)
            merged.paste(Image.alpha_composite(merged.crop(box), tile), box)
    image = ElementTree.Element("image", {"version": "0.0.3", "w": str(width), "h": str(height)})
    files: dict[str, bytes] = {}
    _xml(ElementTree.SubElement(image, "stack"), layers, files)
    stack = ElementTree.tostring(image, encoding="UTF-8", xml_declaration=True)
    thumbnail = merged.copy()
    thumbnail.thumbnail((256, 256))
    with zipfile.ZipFile(path, "x") as archive:
        archive.writestr("mimetype", "image/openraster", compress_type=zipfile.ZIP_STORED)
        archive.writestr("stack.xml", stack, compress_type=zipfile.ZIP_DEFLATED)
        for name, data in files.items():
            archive.writestr(name, data, compress_type=zipfile.ZIP_DEFLATED)
        archive.writestr("mergedimage.png", _encode(merged), compress_type=zipfile.ZIP_STORED)
        archive.writestr("Thumbnails/thumbnail.png", _encode(thumbnail))


def write_png(path: Path, pixels: Pixels) -> None:
    with path.open("xb") as stream:
        stream.write(_png(pixels))


def _xml(parent: ElementTree.Element, layers: tuple[Layer, ...], files: dict[str, bytes]) -> None:
    for layer in layers:
        attributes = {
            "name": layer.name,
            "x": str(layer.x),
            "y": str(layer.y),
            "opacity": f"{layer.opacity:g}",
            "visibility": "visible" if layer.visible else "hidden",
            "composite-op": layer.composite_op,
        }
        if layer.locked:
            attributes["edit-locked"] = "true"
        if layer.pixels is None:
            _xml(ElementTree.SubElement(parent, "stack", attributes), layer.children, files)
            continue
        source = f"data/layer{len(files)}.png"
        files[source] = _png(layer.pixels)
        ElementTree.SubElement(parent, "layer", {**attributes, "src": source})


def _stack(layers: tuple[Layer, ...], width: int, height: int) -> np.ndarray:
    canvas = np.zeros((height, width, 4))
    for layer in reversed(layers):
        if not layer.visible:
            continue
        if layer.pixels is None:
            source = _stack(layer.children, width, height)
        else:
            source = np.zeros((height, width, 4))
            h, w = layer.pixels.shape[:2]
            source[layer.y : layer.y + h, layer.x : layer.x + w] = layer.pixels
        canvas = _blend(canvas, source, layer.opacity, layer.composite_op)
    return canvas


def _blend(backdrop: np.ndarray, source: np.ndarray, opacity: float, op: str) -> np.ndarray:
    source_alpha = source[..., 3:] / 255 * opacity
    backdrop_alpha = backdrop[..., 3:] / 255
    if op == "svg:src-atop":
        alpha = backdrop_alpha
        colour = source[..., :3] * source_alpha + backdrop[..., :3] * (1 - source_alpha)
    elif op == "svg:src-over":
        alpha = source_alpha + backdrop_alpha * (1 - source_alpha)
        mixed = source[..., :3] * source_alpha + backdrop[..., :3] * backdrop_alpha * (
            1 - source_alpha
        )
        colour = np.divide(mixed, alpha, out=np.zeros_like(mixed), where=alpha > 0)
    else:
        raise ValueError(f"the fixture composites src-over and src-atop only, not {op}")
    colour = np.where(alpha > 0, colour, 0)
    return np.concatenate([colour, alpha * 255], axis=-1)


def _png(pixels: Pixels) -> bytes:
    return _encode(Image.fromarray(pixels))


def _encode(image: Image.Image) -> bytes:
    stream = io.BytesIO()
    image.save(stream, "PNG")
    return stream.getvalue()


BLENDS = {"svg:src-over": "normal", "svg:src-atop": "normal", "svg:multiply": "multiply"}


def expected_tree(layers: tuple[Layer, ...], parent: str | None = None) -> list[dict[str, object]]:
    # What Krita's ORA loader should build: depth-first, bottom first, as Node.childNodes() lists.
    nodes: list[dict[str, object]] = []
    for order, layer in enumerate(reversed(layers)):
        nodes.append(
            {
                "name": layer.name,
                "type": "group" if layer.is_group else "paint",
                "parent": parent,
                "order": order,
                "visible": layer.visible,
                "opacity": layer.opacity,
                "blend_mode": BLENDS[layer.composite_op],
                "locked": layer.locked,
                "alpha_locked": False,
                "inherit_alpha": layer.composite_op == "svg:src-atop",
                "bounds_px": None
                if layer.pixels is None
                else bounds(layer.pixels, layer.x, layer.y),
            }
        )
        nodes += expected_tree(layer.children, layer.name)
    return nodes


def bounds(pixels: Pixels, x: int = 0, y: int = 0) -> dict[str, int]:
    rows, columns = np.nonzero(pixels[..., 3])
    if not len(rows):
        return {"x": 0, "y": 0, "width": 0, "height": 0}
    return {
        "x": x + int(columns.min()),
        "y": y + int(rows.min()),
        "width": int(columns.max() - columns.min()) + 1,
        "height": int(rows.max() - rows.min()) + 1,
    }
