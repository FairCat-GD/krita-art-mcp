import io
import xml.etree.ElementTree as ElementTree
import zipfile
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from krita_art_mcp.probe import fixtures


def _decoded(data: bytes) -> np.ndarray:
    with Image.open(io.BytesIO(data)) as image:
        return np.asarray(image.convert("RGBA"))


def test_the_ora_is_laid_out_as_openraster_requires(tmp_path: Path) -> None:
    fixtures.write_ora(tmp_path / "fixture.ora", fixtures.probe_stack())
    with zipfile.ZipFile(tmp_path / "fixture.ora") as archive:
        first = archive.infolist()[0]
        assert (first.filename, first.compress_type) == ("mimetype", zipfile.ZIP_STORED)
        assert archive.read("mimetype") == b"image/openraster"
        names = archive.namelist()
        assert {"stack.xml", "mergedimage.png", "Thumbnails/thumbnail.png"} <= set(names)


def test_stack_xml_lists_the_layers_top_first_with_their_properties(tmp_path: Path) -> None:
    fixtures.write_ora(tmp_path / "fixture.ora", fixtures.probe_stack())
    with zipfile.ZipFile(tmp_path / "fixture.ora") as archive:
        image = ElementTree.fromstring(archive.read("stack.xml"))
        assert (image.get("w"), image.get("h")) == ("64", "48")
        stack = image.find("stack")
        assert stack is not None
        top = list(stack)
        assert [(node.tag, node.get("name")) for node in top] == [
            ("layer", "probe hidden"),
            ("stack", "probe group"),
            ("layer", "probe locked"),
            ("layer", "probe base"),
        ]
        hidden, group, locked, _ = top
        assert (hidden.get("visibility"), hidden.get("opacity")) == ("hidden", "0.5")
        assert hidden.get("composite-op") == "svg:multiply"
        assert locked.get("edit-locked") == "true"
        clip, shape = list(group)
        assert clip.get("composite-op") == "svg:src-atop"
        assert (shape.get("x"), shape.get("y")) == ("8", "12")
        # Each layer's PNG is its own pixels, at its own size.
        pixels = _decoded(archive.read(shape.get("src") or ""))
        assert pixels.shape == (16, 20, 4) and tuple(pixels[0, 0]) == (167, 194, 132, 255)


def test_the_composite_is_what_krita_should_show(tmp_path: Path) -> None:
    merged = fixtures.write_ora(tmp_path / "fixture.ora", fixtures.probe_stack())
    with zipfile.ZipFile(tmp_path / "fixture.ora") as archive:
        assert (_decoded(archive.read("mergedimage.png")) == merged).all()
    # The clip shows only over the shape, the hidden layer nowhere, and the rest is empty.
    assert tuple(merged[20, 24]) == (240, 30, 60, 255)
    assert tuple(merged[11, 24]) == (0, 0, 0, 0)
    assert tuple(merged[20, 10]) == (167, 194, 132, 255)
    assert tuple(merged[35, 50]) == (32, 64, 200, 255)
    assert tuple(merged[45, 5]) == (10, 120, 220, 255)
    assert tuple(merged[0, 0]) == (0, 0, 0, 0)
    assert set(np.unique(merged[..., 3])) == {0, 255}


def test_a_fixture_never_replaces_a_file(tmp_path: Path) -> None:
    (tmp_path / "taken.ora").write_bytes(b"earlier")
    (tmp_path / "taken.png").write_bytes(b"earlier")
    with pytest.raises(FileExistsError):
        fixtures.write_ora(tmp_path / "taken.ora", fixtures.probe_stack())
    with pytest.raises(FileExistsError):
        fixtures.write_png(tmp_path / "taken.png", fixtures.rect(2, 2, (1, 2, 3)))
    assert (tmp_path / "taken.ora").read_bytes() == b"earlier"


def test_the_png_fixture_holds_exactly_its_pixels(tmp_path: Path) -> None:
    merged = fixtures.composite(fixtures.probe_stack())
    fixtures.write_png(tmp_path / "fixture.png", merged)
    assert (_decoded((tmp_path / "fixture.png").read_bytes()) == merged).all()


def test_a_sparse_ora_stores_each_layer_at_its_own_size(tmp_path: Path) -> None:
    layers = fixtures.update_stack()[1:]
    fixtures.write_sparse_ora(tmp_path / "sparse.ora", layers, 64, 48)
    with zipfile.ZipFile(tmp_path / "sparse.ora") as archive:
        first = archive.infolist()[0]
        assert (first.filename, first.compress_type) == ("mimetype", zipfile.ZIP_STORED)
        stack = ElementTree.fromstring(archive.read("stack.xml")).find("stack")
        assert stack is not None
        paint = next(iter(stack))
        assert (paint.get("name"), paint.get("x"), paint.get("y")) == ("probe paint", "8", "8")
        assert _decoded(archive.read(paint.get("src") or "")).shape == (16, 24, 4)
        merged = _decoded(archive.read("mergedimage.png"))
    # The 8-bit merge matches the float one wherever alpha is 0 or 255.
    assert (merged == fixtures.composite(layers)).all()
    # A layer's transparent pixels leave what lies under them.
    holed = fixtures.rect(8, 8, (240, 30, 60))
    holed[2:6, 2:6, 3] = 0
    holes = (fixtures.Layer("probe hole", holed, x=10, y=10), *layers)
    fixtures.write_sparse_ora(tmp_path / "holed.ora", holes, 64, 48)
    with zipfile.ZipFile(tmp_path / "holed.ora") as archive:
        merged = _decoded(archive.read("mergedimage.png"))
    assert tuple(merged[14, 14]) == (200, 40, 90, 255)
    assert (merged == fixtures.composite(holes)).all()


def test_a_sparse_ora_takes_src_over_paint_layers_only(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        fixtures.write_sparse_ora(tmp_path / "group.ora", fixtures.update_stack(), 64, 48)
    clip = (fixtures.Layer("clip", fixtures.rect(2, 2, (1, 2, 3)), composite_op="svg:src-atop"),)
    with pytest.raises(ValueError):
        fixtures.write_sparse_ora(tmp_path / "clip.ora", clip, 64, 48)
    assert not (tmp_path / "group.ora").exists() and not (tmp_path / "clip.ora").exists()


def test_every_benchmark_layer_covers_the_strokes_area_and_its_margin() -> None:
    area = {"x": 800, "y": 800, "width": 400, "height": 400}
    layers = fixtures.benchmark_stack(30, area)
    assert len({layer.name for layer in layers}) == 30
    reach = 64
    for layer in layers:
        assert layer.pixels is not None
        height, width = layer.pixels.shape[:2]
        assert layer.x <= area["x"] - reach and area["x"] + area["width"] + reach <= layer.x + width
        assert (
            layer.y <= area["y"] - reach and area["y"] + area["height"] + reach <= layer.y + height
        )


@pytest.mark.parametrize(
    ("stack", "side"),
    [
        (fixtures.sprite_stack(), (fixtures.SPRITE_WIDTH, fixtures.SPRITE_HEIGHT)),
        (fixtures.icon_stack(), (fixtures.ICON_SIDE, fixtures.ICON_SIDE)),
    ],
    ids=["sprite", "icon"],
)
def test_an_acceptance_fixture_has_an_exterior_a_soft_edge_and_a_solid_inside(
    stack: tuple[fixtures.Layer, ...], side: tuple[int, int]
) -> None:
    alpha = fixtures.composite(stack, *side)[..., 3]
    assert alpha[0, 0] == alpha[-1, -1] == 0
    assert alpha[side[1] // 2, side[0] // 2] == 255
    assert np.any((alpha > 0) & (alpha < 255))
