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
