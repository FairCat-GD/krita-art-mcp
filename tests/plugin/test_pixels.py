import json
import os
from pathlib import Path
from typing import Any

import pytest
from bridge_core import documents, pixels
from bridge_core.errors import BridgeError
from bridge_core.jobs import Call
from bridge_core.registry import Registry
from fake_krita import FakePort, bgra, crop, layer_id

A: dict[str, Any] = {"pid": 101, "started_at": "Sat Oct 24 10:00:00 2026"}
CREATE = {
    "name": "sketch",
    "size_px": [64, 32],
    "color_model": "RGBA",
    "depth": "U8",
    "profile_id": documents.SRGB_PROFILE,
    "background": "transparent",
}
RENDER = {"scale": 1, "filter": "nearest", "background": None, "greyscale": False, "max_px": 1600}
RECT = {"x": 2, "y": 1, "width": 5, "height": 3}


class World:
    def __init__(self, tmp: Path) -> None:
        self.data = tmp / "data"
        self.data.mkdir()
        (self.data / "config.json").write_text(json.dumps({"v": 1, "roots": []}))
        self.port = FakePort()
        self.registry = Registry(self.port, lambda client: True)
        self.ops = documents.handlers(self.registry, self.port, self.data)

    def run(self, op: str, args: dict[str, Any]) -> dict[str, Any]:
        return self.ops[op](args, Call("op-x", "req-x", A))

    def created(self) -> tuple[str, int]:
        document_id = self.run("document.create", CREATE)["document_id"]
        return document_id, max(self.port.live)

    def capture(self, document_id: str, **changes: Any) -> dict[str, Any]:
        args = {
            "document_id": document_id,
            "frame": 0,
            "target": "composite",
            "layer_id": None,
            "rect": dict(RECT),
            "render": dict(RENDER),
            **changes,
        }
        return self.run("capture.read", args)

    def sample(self, document_id: str, **changes: Any) -> dict[str, Any]:
        args = {
            "document_id": document_id,
            "frame": 0,
            "target": "composite",
            "layer_id": None,
            "points": [[3, 2]],
            "radius": 0,
            **changes,
        }
        return self.run("sample.read", args)

    def refused(self, op: str, document_id: str, **changes: Any) -> dict[str, Any]:
        with pytest.raises(BridgeError) as refused:
            if op == "capture":
                self.capture(document_id, **changes)
            else:
                self.sample(document_id, **changes)
        body: dict[str, Any] = refused.value.body
        return body

    def transfers(self) -> list[str]:
        folder = self.data / "transfer"
        return sorted(os.listdir(folder)) if folder.exists() else []


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


def test_a_composite_capture_hands_over_the_rect_and_echoes_render(world: World) -> None:
    document_id, _ = world.created()
    found = world.capture(document_id)
    assert found["pixels"]["format"] == "BGRA8" and found["pixels"]["size_px"] == [5, 3]
    assert Path(found["pixels"]["path"]).read_bytes() == crop(bgra(64, 32), 64, RECT, 4)
    assert (found["rect"], found["render"], found["profile_id"]) == (
        RECT,
        RENDER,
        documents.SRGB_PROFILE,
    )
    # No selection mask is active, so the view is never touched.
    assert world.port.calls == ["read"]


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"rect": {"x": 60, "y": 0, "width": 5, "height": 1}}, "INVALID_ARGUMENT"),
        ({"rect": {"x": 0, "y": 0, "width": 0, "height": 1}}, "INVALID_ARGUMENT"),
        ({"rect": {"x": True, "y": 0, "width": 1, "height": 1}}, "INVALID_ARGUMENT"),
        ({"render": None}, "INVALID_ARGUMENT"),
        ({"target": "layer"}, "INVALID_ARGUMENT"),
        ({"layer_id": "x"}, "INVALID_ARGUMENT"),
        ({"target": "projection"}, "INVALID_ARGUMENT"),
        ({"frame": 1}, "UNSUPPORTED_CAPABILITY"),
    ],
)
def test_a_capture_is_refused_before_any_read(
    world: World, changes: dict[str, Any], code: str
) -> None:
    document_id, _ = world.created()
    assert world.refused("capture", document_id, **changes)["code"] == code
    assert world.port.calls == [] and world.transfers() == []


def test_the_read_limit_covers_a_whole_8k_master(world: World) -> None:
    assert pixels.MAX_READ_PIXELS == 8192 * 8192
    document_id, _ = world.created()
    over = {"x": 0, "y": 0, "width": 8193, "height": 8192}
    body = world.refused("capture", document_id, rect=over)
    assert body["details"] == {"max_read_pixels": pixels.MAX_READ_PIXELS}
    assert world.port.calls == []


def test_an_animated_document_showing_another_frame_is_never_read(world: World) -> None:
    document_id, key = world.created()
    world.port.live[key].update(current_time=12, animated=True)
    body = world.refused("capture", document_id)
    assert body["code"] == "UNSUPPORTED_CAPABILITY" and body["details"]["current_time"] == 12
    assert world.port.calls == []


def test_a_still_document_reads_wherever_its_timeline_stands(world: World) -> None:
    # Without keyframes every frame is the same picture.
    document_id, key = world.created()
    world.port.live[key].update(current_time=12, animated=False)
    assert world.capture(document_id)["pixels"]["size_px"] == [5, 3]


def test_a_composite_of_a_document_that_is_not_8_bit_rgba_is_refused(world: World) -> None:
    key = world.port.open_by_hand("their painting")
    world.port.live[key]["space"] = ("GRAYA", "U16", "Gray-D50-elle-V2-g10.icc")
    [owners] = world.run("document.list", {})["documents"]
    for op in ("capture", "sample"):
        body = world.refused(op, owners["document_id"])
        assert body["code"] == "COLOR_PROFILE_MISMATCH"
        assert body["details"]["color_model"] == "GRAYA"
    assert world.port.calls == []


def test_a_layer_capture_reads_a_paint_layers_own_device(world: World) -> None:
    document_id, key = world.created()
    world.port.layer_pixels[layer_id(key, 0)] = bytes([1, 2, 3, 4])
    found = world.capture(document_id, target="layer", layer_id=layer_id(key, 0))
    assert Path(found["pixels"]["path"]).read_bytes() == bytes([1, 2, 3, 4]) * 15
    assert found["profile_id"] == documents.SRGB_PROFILE


def test_layer_reads_refuse_unknown_ids_groups_and_other_depths(world: World) -> None:
    document_id, key = world.created()
    missing = world.refused("capture", document_id, target="layer", layer_id="nope")
    assert missing["code"] == "LAYER_NOT_FOUND"
    node = world.port.tree(world.port.documents()[0])["nodes"][0]
    world.port.live[key]["tree"] = {"root_id": "root", "active_id": None, "nodes": [node]}
    node["type"] = "grouplayer"
    group = world.refused("capture", document_id, target="layer", layer_id=node["id"])
    assert group["code"] == "UNSUPPORTED_CAPABILITY" and group["details"]["layer_type"] == "group"
    node.update(type="paintlayer", depth="U16")
    deeper = world.refused("sample", document_id, target="layer", layer_id=node["id"])
    assert deeper["code"] == "COLOR_PROFILE_MISMATCH"
    assert world.transfers() == []


def _behind(world: World) -> tuple[str, int, int]:
    # The first document has its selection mask active; the second one is in front.
    document_id, key = world.created()
    world.port.live[key]["active_mask"] = True
    _, other = world.created()
    return document_id, key, other


def test_k46_brings_an_agents_document_forward_reads_then_puts_the_view_back(
    world: World,
) -> None:
    document_id, key, other = _behind(world)
    seen: list[list[str]] = []
    restore = world.port.restore_view

    def watched(view: Any) -> None:
        seen.append(world.transfers())
        restore(view)

    world.port.restore_view = watched  # type: ignore[method-assign]
    found = world.capture(document_id)
    assert world.port.calls == ["forward", "prepare", "read", "restore"]
    assert world.port.front_key == other and world.port.live[key]["active_mask"] is False
    # The transfer file is written only after the view is back.
    assert seen == [[]] and Path(found["pixels"]["path"]).exists()


def test_k46_in_front_needs_no_switch(world: World) -> None:
    document_id, key = world.created()
    world.port.live[key]["active_mask"] = True
    world.sample(document_id)
    assert world.port.calls == ["forward", "prepare", "read"]


def test_k46_on_an_owners_document_refuses_and_changes_nothing(world: World) -> None:
    key = world.port.open_by_hand("their painting")
    world.port.live[key]["active_mask"] = True
    [owners] = world.run("document.list", {})["documents"]
    body = world.refused("capture", owners["document_id"])
    assert body["code"] == "DOCUMENT_READ_ONLY"
    assert body["details"] == {
        "document_id": owners["document_id"],
        "reason": "selection_mask_active",
    }
    assert world.port.calls == [] and world.port.live[key]["active_mask"] is True


def test_k46_puts_the_view_back_when_the_read_fails(world: World) -> None:
    document_id, _, other = _behind(world)
    world.port.fail["composite"] = BridgeError("INTERNAL_ERROR", "Krita failed")
    assert world.refused("capture", document_id)["code"] == "INTERNAL_ERROR"
    assert world.port.calls[-1] == "restore" and world.port.front_key == other
    assert world.transfers() == []


def test_a_selection_capture_is_one_byte_per_pixel_and_needs_a_selection(world: World) -> None:
    document_id, key = world.created()
    world.port.live[key]["selection"] = ({"x": 3, "y": 1, "width": 2, "height": 1}, b"\x80\xff")
    found = world.capture(document_id, target="selection")
    assert found["pixels"]["format"] == "A8" and found["profile_id"] is None
    assert Path(found["pixels"]["path"]).read_bytes()[:5] == b"\x00\x80\xff\x00\x00"
    world.port.live[key]["selection"] = None
    assert world.refused("capture", document_id, target="selection")["code"] == "INVALID_ARGUMENT"


def test_a_sample_reads_one_clipped_square_per_point_into_one_file(world: World) -> None:
    document_id, _ = world.created()
    found = world.sample(document_id, points=[[0, 0], [10, 5], [63, 31]], radius=2.5)
    assert found["squares"] == [
        {"x": 0, "y": 0, "width": 3, "height": 3},
        {"x": 8, "y": 3, "width": 5, "height": 5},
        {"x": 61, "y": 29, "width": 3, "height": 3},
    ]
    assert found["pixels"]["size_px"] == [9 + 25 + 9, 1]
    expected = b"".join(crop(bgra(64, 32), 64, square, 4) for square in found["squares"])
    assert Path(found["pixels"]["path"]).read_bytes() == expected
    assert (found["points"], found["radius"]) == ([[0, 0], [10, 5], [63, 31]], 2.5)
    assert world.port.calls == ["read"] and world.transfers() == [
        Path(found["pixels"]["path"]).name
    ]


@pytest.mark.parametrize(
    "changes",
    [
        {"points": [[64, 0]]},
        {"points": [[-1, 0]]},
        {"points": [[0, True]]},
        {"points": []},
        {"points": [[0, 0]] * 257},
        {"radius": -1},
        {"radius": 64.5},
        {"radius": True},
        {"radius": float("nan")},
        {"target": "selection"},
    ],
)
def test_a_sample_is_refused_before_any_read(world: World, changes: dict[str, Any]) -> None:
    document_id, _ = world.created()
    assert world.refused("sample", document_id, **changes)["code"] == "INVALID_ARGUMENT"
    assert world.port.calls == [] and world.transfers() == []
