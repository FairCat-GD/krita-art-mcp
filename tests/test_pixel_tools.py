import base64
import hashlib
import io
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from bridge_core import documents, pixels
from bridge_core import resources as bridge_resources
from fake_krita import PRESET_XML, bgra, layer_id
from mcp.types import CallToolResult, ImageContent, TextContent
from PIL import Image
from worlds import World, running_world

from krita_art_mcp import imaging
from krita_art_mcp.tools import observe

SRGB = documents.SRGB_PROFILE


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    with running_world(tmp_path) as running:
        yield running


def _created(world: World, width: int = 64, height: int = 32) -> tuple[str, int]:
    arguments = {
        "name": "sketch",
        "size_px": [width, height],
        "color_model": "RGBA",
        "depth": "U8",
        "profile_id": SRGB,
        "background": "transparent",
        "request_id": f"req-{width}-{height}",
    }
    created = world.server().content("krita_document_create", arguments)
    assert created["status"] == "completed"
    return created["document_id"], max(world.port.live)


def _capture(document_id: str, **changes: Any) -> dict[str, Any]:
    return {
        "source": {"document_id": document_id, "frame": 0},
        "target": "composite",
        "layer_id": None,
        "rect": {"x": 2, "y": 1, "width": 5, "height": 3},
        "scale": 1,
        "filter": "nearest",
        **changes,
    }


def _sample(document_id: str, **changes: Any) -> dict[str, Any]:
    return {
        "source": {"document_id": document_id, "frame": 0},
        "target": "composite",
        "layer_id": None,
        "points": [[3, 2]],
        **changes,
    }


def _expected(width: int, height: int, rect: dict[str, int]) -> np.ndarray:
    canvas = np.frombuffer(bgra(width, height), dtype=np.uint8).reshape(height, width, 4)
    crop = canvas[rect["y"] : rect["y"] + rect["height"], rect["x"] : rect["x"] + rect["width"]]
    return crop[..., [2, 1, 0, 3]]


def _image(result: CallToolResult) -> ImageContent:
    images = [item for item in result.content if isinstance(item, ImageContent)]
    assert len(images) == 1
    return images[0]


def _pixels(data: bytes) -> np.ndarray:
    with Image.open(io.BytesIO(data)) as image:
        return np.asarray(image)


def test_a_native_capture_is_the_composites_bytes_with_its_image_and_path(world: World) -> None:
    document_id, _ = _created(world)
    result = world.server().call("krita_capture", _capture(document_id))
    content = result.structured_content
    assert content is not None and content["status"] == "completed"
    data = content["data"]
    path = Path(data["image"]["path"])
    expected = _expected(64, 32, data["source_rect"])
    assert np.array_equal(_pixels(path.read_bytes()), expected)
    assert (
        data["image"]["uri"] == str(path)
        and path.parent.parent == world.tmp_path / "a" / "captures"
    )
    assert data["image"]["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert (data["output_size_px"], data["source_to_image"]) == ([5, 3], [1, 0, -2, 0, 1, -1])
    assert (data["filter"], data["background"], data["greyscale"]) == (None, None, False)
    assert data["profile_id"] == SRGB and data["fresh"] is True
    image = _image(result)
    # Codex shows it at full resolution (C2); the SDK's own Image type cannot carry this.
    assert image.meta == {"codex/imageDetail": "original"} and image.mime_type == "image/png"
    assert base64.b64decode(image.data) == path.read_bytes()
    # Clients that downscale or drop images still get the path (C4).
    assert isinstance(result.content[0], TextContent) and str(path) in result.content[0].text
    assert list((world.data / "transfer").iterdir()) == []


def test_a_layer_capture_is_the_layers_own_pixels(world: World) -> None:
    document_id, key = _created(world)
    world.port.layer_pixels[layer_id(key, 0)] = bytes([30, 20, 10, 128])
    arguments = _capture(document_id, target="layer", layer_id=layer_id(key, 0))
    data = world.server().content("krita_capture", arguments)["data"]
    found = _pixels(Path(data["image"]["path"]).read_bytes())
    assert (found == [10, 20, 30, 128]).all() and data["layer_id"] == layer_id(key, 0)


def test_a_selection_capture_is_its_mask_as_grey(world: World) -> None:
    document_id, key = _created(world)
    world.port.live[key]["selection"] = ({"x": 3, "y": 1, "width": 2, "height": 1}, b"\x80\xff")
    data = world.server().content("krita_capture", _capture(document_id, target="selection"))[
        "data"
    ]
    assert _pixels(Path(data["image"]["path"]).read_bytes()).tolist() == [
        [0, 128, 255, 0, 0],
        [0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0],
    ]
    assert data["profile_id"] is None and data["background"] is None
    world.port.live[key]["selection"] = None
    refused = world.server().content("krita_capture", _capture(document_id, target="selection"))
    assert refused["error"]["code"] == "INVALID_ARGUMENT" and refused["operation_id"]


def test_a_resampled_capture_lands_on_a_checker_by_default(world: World) -> None:
    document_id, _ = _created(world)
    rect = {"x": 0, "y": 0, "width": 64, "height": 32}
    arguments = _capture(document_id, rect=rect, scale=0.5, filter="bilinear")
    data = world.server().content("krita_capture", arguments)["data"]
    assert data["output_size_px"] == [32, 16]
    assert data["source_to_image"] == [0.5, 0, 0, 0, 0.5, 0]
    assert (data["filter"], data["background"]) == ("bilinear", "checker")
    with Image.open(data["image"]["path"]) as image:
        assert image.size == (32, 16) and image.mode == "RGB"


@pytest.mark.parametrize(
    "changes",
    [
        {"background": "checker"},
        {"greyscale": False},
        {"target": "selection", "scale": 2, "greyscale": True},
        {"source": {"document_id": "doc-000000000000", "frame": 1}},
        {"rect": {"x": 0, "y": 0, "width": 8193, "height": 8192}, "scale": 0.1},
        {"rect": {"x": 0, "y": 0, "width": 1601, "height": 1}},
        {"scale": 0.1},
    ],
)
def test_the_server_refuses_what_the_arguments_alone_rule_out(
    world: World, changes: dict[str, Any]
) -> None:
    refused = world.server().content("krita_capture", _capture("doc-000000000000", **changes))
    assert refused["status"] == "failed"
    assert refused["error"]["code"] in ("INVALID_ARGUMENT", "UNSUPPORTED_CAPABILITY")
    # Refused before anything was sent: the plugin's own refusal would carry an operation_id.
    assert refused["operation_id"] is None


def test_the_read_limit_is_the_plugins() -> None:
    assert observe.LIMITS["capture_source_pixels"] == pixels.MAX_READ_PIXELS


def test_a_capture_over_the_inline_cap_comes_back_as_a_preview(world: World) -> None:
    document_id, key = _created(world, 1300, 1300)
    noise = np.random.default_rng(5).integers(0, 256, 1300 * 1300 * 4, dtype=np.uint8)
    world.port.canvas[key] = noise.tobytes()
    rect = {"x": 0, "y": 0, "width": 1300, "height": 1300}
    result = world.server().call("krita_capture", _capture(document_id, rect=rect))
    content = result.structured_content
    assert content is not None and content["status"] == "completed", content
    data = content["data"]
    assert data["image"]["size_bytes"] > imaging.INLINE_BYTES
    assert data["inline"]["preview"] is True and data["inline"]["output_size_px"] == [650, 650]
    assert data["inline"]["source_to_image"] == [0.5, 0, 0, 0, 0.5, 0]
    shown = base64.b64decode(_image(result).data)
    assert _pixels(shown).shape[:2] == (650, 650)
    assert "650 x 650 preview" in str(result.content[0])
    assert len(result.model_dump_json(by_alias=True, exclude_none=True)) < 6 * 1024 * 1024


def test_operation_get_finishes_a_capture_that_came_back_running(world: World) -> None:
    document_id, _ = _created(world)
    world.gate.clear()
    world.port.on_read.append(lambda: world.gate.wait(10))
    running = world.server(budget_s=0.6).content("krita_capture", _capture(document_id))
    assert running["status"] == "running" and running["data"] is None
    world.gate.set()
    follow = {"operation_id": running["operation_id"]}
    first = world.server(budget_s=3.0).call("krita_operation_get", follow)
    again = world.server(budget_s=3.0).call("krita_operation_get", follow)
    for got in (first, again):
        assert got.structured_content is not None
        receipt = got.structured_content["data"]["receipt"]
        assert receipt["status"] == "completed"
        # The receipt's own line, with the path, and its image come along.
        assert receipt["data"]["image"]["path"] in str(got.content[1])
        assert _image(got).meta == {"codex/imageDetail": "original"}
    assert first.structured_content == again.structured_content


def test_an_owners_document_with_an_active_mask_is_refused_untouched(world: World) -> None:
    key = world.port.open_by_hand("their painting")
    world.port.mask(key)
    [owners] = world.server().content("krita_document_list", {})["data"]["documents"]
    refused = world.server().content("krita_capture", _capture(owners["document_id"]))
    assert refused["error"]["code"] == "DOCUMENT_READ_ONLY"
    assert refused["error"]["details"]["reason"] == "selection_mask_active"
    assert world.port.calls == [] and world.port.is_masked(key)


def test_samples_report_the_stored_values_and_their_colour(world: World) -> None:
    document_id, _ = _created(world)
    data = world.server().content("krita_sample", _sample(document_id))["data"]
    [found] = data["samples"]
    expected = _expected(64, 32, {"x": 3, "y": 2, "width": 1, "height": 1})[0, 0].tolist()
    assert found["rgba"] == expected and found["pixel_count"] == 1
    assert found["hex"] == "#{:02X}{:02X}{:02X}".format(*expected[:3])
    assert found["lab"] is not None and data["profile_id"] == SRGB
    disc = world.server().content("krita_sample", _sample(document_id, radius=1.5))["data"]
    assert disc["radius_px"] == 1.5 and disc["samples"][0]["pixel_count"] == 9


def test_a_layer_sample_and_a_corner_disc(world: World) -> None:
    document_id, key = _created(world)
    world.port.layer_pixels[layer_id(key, 0)] = bytes([132, 194, 167, 255])
    arguments = _sample(
        document_id, target="layer", layer_id=layer_id(key, 0), points=[[0, 0]], radius=2
    )
    data = world.server().content("krita_sample", arguments)["data"]
    [found] = data["samples"]
    assert found["rgba"] == [167, 194, 132, 255] and found["hex"] == "#A7C284"
    # The quarter of a radius-2 disc that lies on the canvas.
    assert found["pixel_count"] == 6 and found["stdev_l"] == 0


def test_a_sample_is_rebuilt_by_operation_get_twice(world: World) -> None:
    document_id, _ = _created(world)
    sampled = world.server().content("krita_sample", _sample(document_id))
    follow = {"operation_id": sampled["operation_id"]}
    for _ in range(2):
        got = world.server().content("krita_operation_get", follow)
        assert got["data"]["receipt"] == sampled


def test_outside_srgb_the_colour_maths_are_null_and_greyscale_refused(world: World) -> None:
    key = world.port.open_by_hand("their painting")
    world.port.live[key]["space"] = ("RGBA", "U8", "AdobeRGB")
    [owners] = world.server().content("krita_document_list", {})["data"]["documents"]
    document_id = owners["document_id"]
    [found] = world.server().content("krita_sample", _sample(document_id))["data"]["samples"]
    assert found["hex"] is not None and (found["lab"], found["lch"], found["stdev_l"]) == (
        None,
        None,
        None,
    )
    grey = _capture(document_id, scale=0.5, filter="box", greyscale=True)
    refused = world.server().content("krita_capture", grey)
    assert refused["error"]["code"] == "COLOR_PROFILE_MISMATCH"
    assert list((world.data / "transfer").iterdir()) == []


def test_resources_page_through_the_cursor_with_fingerprints(world: World) -> None:
    server = world.server()
    first = server.content("krita_resource_list", {"kind": "brush", "cursor": None, "limit": 2})
    data = first["data"]
    assert (data["kind"], data["total"], data["next_cursor"]) == ("brush", 3, "2")
    assert [entry["id"] for entry in data["resources"]] == ["airbrush-soft.kpp", "basic-round.kpp"]
    basic = data["resources"][1]
    # The plugin's own digest, which leaves out what every stroke sets.
    assert basic["sha256"] == bridge_resources.fingerprint(PRESET_XML)[1]
    assert basic["engine"] == "paintbrush"
    rest = server.content("krita_resource_list", {"kind": "brush", "cursor": "2", "limit": 2})
    [broken] = rest["data"]["resources"]
    assert (broken["engine"], broken["sha256"], rest["data"]["next_cursor"]) == (None, None, None)
    modes = server.content(
        "krita_resource_list", {"kind": "blend_mode", "cursor": None, "limit": 20}
    )
    assert len(modes["data"]["resources"]) == 10
    past = server.content("krita_resource_list", {"kind": "brush", "cursor": "3", "limit": 2})
    assert past["error"]["code"] == "INVALID_ARGUMENT"
