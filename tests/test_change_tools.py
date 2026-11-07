import hashlib
import io
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from bridge_core import documents
from fake_krita import layer_id
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
        "coverage": None,
        "protected": False,
        "undo_steps": 1,
        "verification": None,
    }
    assert [line["phase"] for line in _lines(world)][-2:] == ["dispatched", "finished"]
    assert server.content("krita_layer_create", arguments) == made


def test_a_transparency_mask_is_created_through_the_tool_with_its_verification(
    world: World,
) -> None:
    server = world.server()
    document_id = _document(server)
    layer = layer_id(1, 0)
    painted = server.content(
        "krita_paint_fill",
        {
            "guard": _guard(document_id, "req-paint"),
            "layer_id": layer,
            "shape": {"type": "rect", "rect": {"x": 1, "y": 1, "width": 3, "height": 2}},
            "color": {"space": "srgb", "rgba": [0.8, 0.2, 0.4, 1]},
            "opacity": 1,
        },
    )
    assert painted["status"] == "completed", painted
    made = server.content(
        "krita_layer_create",
        {
            "guard": _guard(document_id, "req-mask"),
            "parent_id": layer,
            "above_id": None,
            "type": "transparency_mask",
            "name": "mask",
            "coverage": "all",
        },
    )
    data = made["data"]
    assert made["status"] == "completed", made
    assert (data["type"], data["coverage"], data["parent_id"]) == (
        "transparency_mask",
        "all",
        layer,
    )
    assert (data["verification"]["mode"], data["verification"]["changed_px"]) == ("region", 0)
    assert data["verification"]["before"]["path"].endswith(".png")
    got = server.content("krita_operation_get", {"operation_id": made["operation_id"]})
    receipt = got["data"]["receipt"]
    assert got["data"]["receipt_valid"] is True
    assert receipt["data"]["verification"]["before"]["path"].endswith(".png")


def test_coverage_is_required_for_a_mask_and_refused_for_a_layer(world: World) -> None:
    server = world.server()
    document_id = _document(server)
    base = {"guard": _guard(document_id, "req-x"), "above_id": None, "name": "x"}
    missing = server.content(
        "krita_layer_create", {**base, "parent_id": layer_id(1, 0), "type": "transparency_mask"}
    )
    stray = server.content(
        "krita_layer_create", {**base, "parent_id": "root-1", "type": "paint", "coverage": "all"}
    )
    assert missing["error"]["code"] == stray["error"]["code"] == "INVALID_ARGUMENT"
    assert missing["operation_id"] is stray["operation_id"] is None


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


def test_a_layer_is_copied_moved_and_removed_through_the_tools(world: World) -> None:
    server = world.server()
    document_id = _document(server)
    layer = layer_id(1, 0)
    group = server.content(
        "krita_layer_create",
        {
            "guard": _guard(document_id, "req-group"),
            "parent_id": "root-1",
            "above_id": None,
            "type": "group",
            "name": "trials",
        },
    )["data"]["layer_id"]
    copied = server.content(
        "krita_layer_duplicate",
        {"guard": _guard(document_id, "req-copy"), "layer_id": layer, "name": "trial"},
    )
    assert copied["status"] == "completed", copied
    copy = copied["data"]["layer_id"]
    assert copied["data"]["id_map"] == {layer: copy} and copied["data"]["visible"] is False
    assert copied["data"]["verification"]["mode"] == "region"
    move = {
        "guard": _guard(document_id, "req-move"),
        "layer_id": copy,
        "parent_id": group,
        "above_id": None,
    }
    moved = server.content("krita_layer_reorder", move)
    assert moved["status"] == "completed", moved
    assert (moved["data"]["effective_order"], moved["data"]["undo_steps"]) == ([copy], 2)
    split = server.content(
        "krita_history_step", {"guard": _guard(document_id, "req-u1"), "action": "undo", "steps": 1}
    )
    assert split["error"]["code"] == "INVALID_ARGUMENT"
    assert split["error"]["details"]["steps_needed"] == 2
    undone = server.content(
        "krita_history_step", {"guard": _guard(document_id, "req-u2"), "action": "undo", "steps": 2}
    )
    assert [step["tool"] for step in undone["data"]["steps"]] == ["krita_layer_reorder"] * 2
    server.content(
        "krita_history_step", {"guard": _guard(document_id, "req-r2"), "action": "redo", "steps": 2}
    )
    again = server.content("krita_layer_reorder", {**move, "guard": _guard(document_id, "req-a")})
    assert again["data"]["undo_steps"] == 0 and again["data"]["verification"] is None
    removed = server.content(
        "krita_layer_remove", {"guard": _guard(document_id, "req-remove"), "layer_id": copy}
    )
    assert removed["status"] == "completed", removed
    assert removed["data"]["removed"] == [copy] and removed["data"]["undo_steps"] == 1
    for made in (copied, moved, removed):
        got = server.content("krita_operation_get", {"operation_id": made["operation_id"]})
        assert got["data"]["receipt_valid"] is True
        assert got["data"]["receipt"]["data"]["layer_id"] == made["data"]["layer_id"]


def test_a_layer_moved_inside_itself_is_refused_before_dispatch(world: World) -> None:
    server = world.server()
    document_id = _document(server)
    layer = layer_id(1, 0)
    refused = server.content(
        "krita_layer_reorder",
        {
            "guard": _guard(document_id, "req-move"),
            "layer_id": layer,
            "parent_id": layer,
            "above_id": None,
        },
    )
    assert refused["error"]["code"] == "INVALID_ARGUMENT" and refused["operation_id"] is None
    assert refused["error"]["details"]["field"] == "parent_id"


def test_a_history_step_lost_mid_batch_says_the_document_is_unsafe(world: World) -> None:
    server = world.server()
    document_id = _document(server)
    for index in range(2):
        server.content(
            "krita_layer_create",
            {
                "guard": _guard(document_id, f"req-layer-{index}"),
                "parent_id": "root-1",
                "above_id": None,
                "type": "paint",
                "name": f"repair {index}",
            },
        )
    undo, presses = world.port.undo, [0]

    def second_raises(document: Any) -> None:
        presses[0] += 1
        if presses[0] == 2:
            raise RuntimeError("Krita raised")
        undo(document)

    world.port.undo = second_raises  # type: ignore[method-assign]
    result = server.call(
        "krita_history_step", {"guard": _guard(document_id, "req-u"), "action": "undo", "steps": 2}
    )
    content = result.structured_content or {}
    assert content["status"] == "completed", content
    assert (content["data"]["steps_applied"], content["data"]["stopped"]) == (1, "document_unsafe")
    text = result.content[0].text
    assert "the document is unsafe" in text and "reopen" in text
    again = server.content(
        "krita_history_step", {"guard": _guard(document_id, "req-r"), "action": "redo", "steps": 1}
    )
    assert again["error"]["code"] == "DOCUMENT_UNSAFE"


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


def test_a_history_capture_another_server_took_is_left_out_not_failed(world: World) -> None:
    places = world.places()
    places.transfer_dir.mkdir(parents=True, exist_ok=True)
    spec = {"path": str(places.transfer_dir / "gone.raw"), "size_px": [1, 1], "format": "BGRA8"}
    result = {
        "document_id": "doc-1",
        "action": "undo",
        "steps_applied": 1,
        "verified": True,
        "stopped": None,
        "steps": [],
        "undo_available": 0,
        "redo_available": 1,
        "region_px": {"x": 0, "y": 0, "width": 1, "height": 1},
        "pixels": spec,
    }
    resolved = changes.resolve_history(places, Done(result, "op-" + "a" * 32))
    assert isinstance(resolved, Done)
    assert (resolved.result["capture"], resolved.result["content_sha256"]) == (None, None)
    assert resolved.result["region_px"] == result["region_px"]
