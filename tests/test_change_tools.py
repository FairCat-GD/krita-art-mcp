import hashlib
import io
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from bridge_core import documents
from PIL import Image
from worlds import NOW, A, B, Server, World, running_world

from krita_art_mcp import transfer
from krita_art_mcp.bridge_client import Done, Pending
from krita_art_mcp.tools import changes

CREATE = {
    "name": "sketch",
    "size_px": [64, 32],
    "color_model": "RGBA",
    "depth": "U8",
    "profile_id": documents.SRGB_PROFILE,
    "background": "transparent",
}


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    with running_world(tmp_path) as running:
        yield running


def _document(server: Server) -> str:
    created = server.content("krita_document_create", {**CREATE, "request_id": "req-create"})
    return str(created["document_id"])


def _guard(document_id: str, request_id: str) -> dict[str, str]:
    return {"document_id": document_id, "request_id": request_id}


def _select(document_id: str, request_id: str, shape: dict[str, Any], **changes_: Any) -> Any:
    return {
        "guard": _guard(document_id, request_id),
        "combine": "replace",
        "shape": shape,
        "feather_px": 0,
        "invert": False,
        **changes_,
    }


def _rect(x: int, y: int, width: int, height: int) -> dict[str, Any]:
    return {"type": "rect", "rect": {"x": x, "y": y, "width": width, "height": height}}


def _protect(document_id: str, request_id: str, mask: Any, **changes_: Any) -> dict[str, Any]:
    return {
        "guard": _guard(document_id, request_id),
        "protected_layer_ids": [],
        "allowed_change_mask": mask,
        "preserve_composite_alpha": False,
        "preserve_canvas": False,
        **changes_,
    }


def _transfers(world: World) -> list[str]:
    folder = world.data / "transfer"
    return sorted(path.name for path in folder.iterdir()) if folder.exists() else []


def _lines(world: World, name: str = "a") -> list[dict[str, Any]]:
    path = world.tmp_path / name / "journal" / f"{NOW.date().isoformat()}.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


def _png(path: Path, pixels: np.ndarray) -> str:
    stream = io.BytesIO()
    Image.fromarray(pixels).save(stream, "PNG")
    path.write_bytes(stream.getvalue())
    return hashlib.sha256(stream.getvalue()).hexdigest()


def test_a_layer_is_created_through_the_tool_and_journaled(world: World) -> None:
    server = world.server()
    document_id = _document(server)
    arguments = {
        "guard": _guard(document_id, "req-layer"),
        "parent_id": "root-1",
        "above_id": None,
        "type": "paint",
        "name": "repair",
    }
    made = server.content("krita_layer_create", arguments)
    assert made["status"] == "completed" and made["document_id"] == document_id
    assert made["data"] == {
        "layer_id": made["data"]["layer_id"],
        "parent_id": "root-1",
        "above_id": None,
        "type": "paint",
        "name": "repair",
        "protected": False,
        "undo_steps": 1,
    }
    assert [line["phase"] for line in _lines(world)][-2:] == ["dispatched", "finished"]
    assert server.content("krita_layer_create", arguments) == made


def test_a_transparency_mask_is_refused_without_reaching_krita(world: World) -> None:
    server = world.server()
    document_id = _document(server)
    refused = server.content(
        "krita_layer_create",
        {
            "guard": _guard(document_id, "req-mask"),
            "parent_id": "root-1",
            "above_id": None,
            "type": "transparency_mask",
            "name": "mask",
        },
    )
    assert refused["error"]["code"] == "UNSUPPORTED_CAPABILITY"
    assert refused["operation_id"] is None
    assert [line["request_id"] for line in _lines(world)] == ["req-create", "req-create"]


def test_a_rect_selection_returns_its_mask_and_leaves_no_transfer_file(world: World) -> None:
    server = world.server()
    document_id = _document(server)
    selected = server.content(
        "krita_selection_set", _select(document_id, "req-s", _rect(4, 2, 6, 3))
    )
    data = selected["data"]
    assert selected["status"] == "completed", selected
    assert data["bounds_px"] == {"x": 4, "y": 2, "width": 6, "height": 3}
    assert data["selected_pixels"] == 18 and data["selection_id"].startswith("sel-")
    with Image.open(data["mask"]["path"]) as image:
        assert image.mode == "L" and np.asarray(image).tolist() == [[255] * 6] * 3
    assert (
        data["mask"]["sha256"]
        == hashlib.sha256(Path(data["mask"]["path"]).read_bytes()).hexdigest()
    )
    assert _transfers(world) == []
    [recipe] = world.port.recipes
    assert recipe[0][0] == "mask" and recipe[0][1] == {"x": 4, "y": 2, "width": 6, "height": 3}


def test_a_retried_selection_runs_once_on_either_server(world: World) -> None:
    first = world.server(A, "a")
    document_id = _document(first)
    arguments = _select(document_id, "req-s", _rect(0, 0, 2, 2))
    original = first.content("krita_selection_set", arguments)
    assert first.content("krita_selection_set", arguments) == original
    # Another server is answered by the bridge; the pixels went to the first, so no mask.
    again = world.server(B, "b").content("krita_selection_set", arguments)
    assert again["data"]["mask"] is None
    assert {**again["data"], "mask": original["data"]["mask"]} == original["data"]
    assert len(world.port.recipes) == 1 and _transfers(world) == []


def test_ellipse_polygon_and_raster_shapes_reach_krita_rasterised(world: World) -> None:
    server = world.server()
    document_id = _document(server)
    ellipse = {"type": "ellipse", "rect": {"x": 2, "y": 2, "width": 8, "height": 4}}
    server.content("krita_selection_set", _select(document_id, "req-e", ellipse))
    polygon = {"type": "polygon", "points": [[1.5, 1], [9, 1], [9, 6.5]]}
    server.content("krita_selection_set", _select(document_id, "req-p", polygon))
    folder = world.data / "harness"
    folder.mkdir(parents=True, exist_ok=True)
    pixels = np.array([[0, 64], [128, 255]], dtype=np.uint8)
    sha = _png(folder / "mask.png", pixels)
    raster = {
        "type": "raster",
        "mask_uri": str(folder / "mask.png"),
        "mask_sha256": sha,
        "origin_px": [5, 6],
    }
    selected = server.content("krita_selection_set", _select(document_id, "req-r", raster))
    assert selected["status"] == "completed", selected
    shapes = [recipe[0] for recipe in world.port.recipes]
    assert [shape[1] for shape in shapes] == [
        {"x": 2, "y": 2, "width": 8, "height": 4},
        {"x": 1, "y": 1, "width": 8, "height": 6},
        {"x": 5, "y": 6, "width": 2, "height": 2},
    ]
    assert shapes[2][2] == pixels.tobytes()
    # The ellipse's corner is partly covered, its centre (row 2, column 4) wholly.
    assert 0 < shapes[0][2][0] < 255 and shapes[0][2][2 * 8 + 4] == 255


def test_a_raster_that_differs_from_its_hash_is_refused_before_anything_is_sent(
    world: World,
) -> None:
    server = world.server()
    document_id = _document(server)
    folder = world.data / "harness"
    folder.mkdir(parents=True, exist_ok=True)
    _png(folder / "mask.png", np.zeros((2, 2), dtype=np.uint8))
    raster = {
        "type": "raster",
        "mask_uri": str(folder / "mask.png"),
        "mask_sha256": "0" * 64,
        "origin_px": [0, 0],
    }
    refused = server.content("krita_selection_set", _select(document_id, "req-r", raster))
    assert refused["error"]["code"] == "RESOURCE_HASH_MISMATCH"
    assert world.port.recipes == [] and _transfers(world) == []
    assert "req-r" not in [line["request_id"] for line in _lines(world)]


def test_clearing_takes_no_modifiers(world: World) -> None:
    server = world.server()
    document_id = _document(server)
    arguments = _select(document_id, "req-n", {"type": "none"}, grow_px=2)
    refused = server.content("krita_selection_set", arguments)
    # The server's own refusal: nothing reaches Krita.
    assert refused["error"]["code"] == "INVALID_ARGUMENT" and refused["operation_id"] is None


def test_an_off_canvas_shape_is_refused_by_krita_and_its_mask_goes(world: World) -> None:
    server = world.server()
    document_id = _document(server)
    refused = server.content(
        "krita_selection_set", _select(document_id, "req-s", _rect(60, 0, 8, 2))
    )
    assert refused["error"]["code"] == "INVALID_ARGUMENT"
    assert refused["error"]["details"]["canvas_px"] == [64, 32]
    assert _transfers(world) == []


@pytest.mark.parametrize("form", ["rect", "polygon", "uri"])
def test_protection_takes_its_mask_in_each_form(world: World, form: str) -> None:
    server = world.server()
    document_id = _document(server)
    if form == "rect":
        mask: dict[str, Any] = {"rect": {"x": 0, "y": 0, "width": 4, "height": 2}}
    elif form == "polygon":
        mask = {"polygon": [[0, 0], [4, 0], [4, 2], [0, 2]]}
    else:
        folder = world.data / "harness"
        folder.mkdir(parents=True, exist_ok=True)
        pixels = np.zeros((32, 64), dtype=np.uint8)
        pixels[:2, :4] = 255
        mask = {"uri": str(folder / "allowed.png"), "sha256": _png(folder / "allowed.png", pixels)}
    set_ = server.content("krita_protection_set", _protect(document_id, "req-p", mask))
    assert set_["status"] == "completed", set_
    summary = set_["data"]["allowed_change_mask"]
    assert summary["bounds_px"] == {"x": 0, "y": 0, "width": 4, "height": 2}
    assert summary["allowed_pixels"] == 8 and set_["data"]["undo_steps"] == 0
    assert _transfers(world) == []


def test_protection_refuses_to_loosen_and_a_png_of_another_size(world: World) -> None:
    server = world.server()
    document_id = _document(server)
    tight = {"rect": {"x": 0, "y": 0, "width": 4, "height": 2}}
    server.content("krita_protection_set", _protect(document_id, "req-1", tight))
    wider = {"rect": {"x": 0, "y": 0, "width": 5, "height": 2}}
    loosened = server.content("krita_protection_set", _protect(document_id, "req-2", wider))
    assert loosened["error"]["code"] == "INVALID_ARGUMENT"
    assert loosened["error"]["details"]["loosened_px"] == 2
    folder = world.data / "harness"
    folder.mkdir(parents=True, exist_ok=True)
    small = {
        "uri": str(folder / "small.png"),
        "sha256": _png(folder / "small.png", np.zeros((2, 4), dtype=np.uint8)),
    }
    refused = server.content("krita_protection_set", _protect(document_id, "req-3", small))
    assert refused["error"]["code"] == "INVALID_ARGUMENT"
    assert _transfers(world) == []


def test_history_undoes_and_redoes_the_bridges_steps(world: World) -> None:
    server = world.server()
    document_id = _document(server)
    made = server.content(
        "krita_layer_create",
        {
            "guard": _guard(document_id, "req-layer"),
            "parent_id": "root-1",
            "above_id": None,
            "type": "group",
            "name": "repair",
        },
    )
    undone = server.content(
        "krita_history_step", {"guard": _guard(document_id, "req-u"), "action": "undo", "steps": 1}
    )
    assert undone["status"] == "completed", undone
    assert undone["data"] == {
        "action": "undo",
        "steps_applied": 1,
        "verified": True,
        "stopped": None,
        "steps": [{"tool": "krita_layer_create", "operation_id": made["operation_id"]}],
        "undo_available": 0,
        "redo_available": 1,
        "region_px": None,
        "content_sha256": None,
        "capture": None,
    }
    deeper = server.content(
        "krita_history_step", {"guard": _guard(document_id, "req-d"), "action": "undo", "steps": 1}
    )
    assert deeper["error"]["code"] == "INVALID_ARGUMENT"


def test_operation_get_rebuilds_a_selection_receipt_and_settles_its_masks(world: World) -> None:
    server = world.server()
    document_id = _document(server)
    selected = server.content(
        "krita_selection_set", _select(document_id, "req-s", _rect(0, 0, 2, 2))
    )
    left = transfer.put_mask(world.data / "transfer", np.zeros((1, 1), dtype=np.uint8), "req-s")
    got = server.content("krita_operation_get", {"operation_id": selected["operation_id"]})
    assert got["data"]["receipt"] == selected
    assert not Path(left["path"]).exists()


def test_masks_wait_while_their_call_is_pending_and_go_once_it_ends(world: World) -> None:
    places = world.places()
    spec = transfer.put_mask(places.transfer_dir, np.zeros((1, 1), dtype=np.uint8), "req-x")
    changes._settle_masks(places, Pending("running", "op-1"), "req-x")
    assert Path(spec["path"]).exists()
    changes._settle_masks(places, Done({}, "op-1"), "req-x")
    assert not Path(spec["path"]).exists()


def test_reads_are_ephemeral_in_the_bridge_and_agents_calls_are_not(world: World) -> None:
    server = world.server()
    document_id = _document(server)
    server.content("krita_document_list", {})
    operations = list(world.bridge.jobs._operations.values())
    reads = [op for op in operations if op.op == "document.list"]
    writes = [op for op in operations if op.op == "document.create"]
    assert reads and all(op.ephemeral for op in reads)
    assert writes and not any(op.ephemeral for op in writes)
    assert document_id


def test_an_older_bridge_that_takes_no_ephemeral_field_is_never_sent_one(world: World) -> None:
    # A plugin from before the field refuses calls that carry it; until Krita restarts on the new
    # plugin, reads must still work.
    path = world.data / "bridge.json"
    info = json.loads(path.read_text())
    del info["ephemeral_reads"]
    path.write_text(json.dumps(info))
    server = world.server()
    assert server.content("krita_document_list", {})["status"] == "completed"
    reads = [op for op in world.bridge.jobs._operations.values() if op.op == "document.list"]
    assert reads and not any(op.ephemeral for op in reads)


def test_a_history_region_becomes_a_capture_and_the_hash_of_its_rgba(world: World) -> None:
    places = world.places()
    bgra = bytes(range(24))
    path = places.transfer_dir / "region.raw"
    places.transfer_dir.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bgra)
    spec = {"path": str(path), "size_px": [3, 2], "format": "BGRA8"}
    result = {
        "document_id": "doc-1",
        "action": "undo",
        "steps_applied": 1,
        "verified": True,
        "stopped": None,
        "steps": [{"op": "selection.set", "operation_id": "op-1"}],
        "undo_available": 0,
        "redo_available": 1,
        "region_px": {"x": 0, "y": 0, "width": 3, "height": 2},
        "pixels": spec,
    }
    outcome = Done(result, "op-0123456789abcdef0123456789abcdef")
    resolved = changes.resolve_history(places, outcome)
    assert isinstance(resolved, Done)
    data = resolved.result
    rgba = np.frombuffer(bgra, dtype=np.uint8).reshape(2, 3, 4)[..., [2, 1, 0, 3]]
    assert data["content_sha256"] == hashlib.sha256(rgba.tobytes()).hexdigest()
    with Image.open(data["capture"]["path"]) as image:
        assert np.array_equal(np.asarray(image), rgba)
    assert data["steps"] == [{"tool": "krita_selection_set", "operation_id": "op-1"}]
    assert not path.exists()
    # Rebuilt from the capture once the transfer file has gone.
    again = changes.resolve_history(places, outcome)
    assert isinstance(again, Done) and again.result == data
