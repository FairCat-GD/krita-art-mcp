import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from bridge_core import documents
from fake_krita import layer_id
from mcp.types import ImageContent
from PIL import Image
from worlds import NOW, B, World, running_world

from krita_art_mcp import imaging, verification
from krita_art_mcp.bridge_client import Done, Failed
from krita_art_mcp.tools import changes

CREATE = {
    "name": "sketch",
    "size_px": [16, 8],
    "color_model": "RGBA",
    "depth": "U8",
    "profile_id": documents.SRGB_PROFILE,
    "background": "transparent",
}
LAYER = layer_id(1, 0)
OPERATION = "op-" + "c" * 32


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    with running_world(tmp_path) as running:
        yield running


def _render(tree: dict[str, Any]) -> bytes:
    # The layer covers the left half; its opacity is its blue byte.
    layer = tree["nodes"][0]
    out = bytearray()
    for _ in range(8):
        for x in range(16):
            out += bytes([layer["opacity"], 20, 30, 255] if x < 8 else [9, 9, 9, 255])
    return bytes(out)


def _document(world: World) -> str:
    server = world.server()
    created = server.content("krita_document_create", {**CREATE, "request_id": "req-create"})
    world.port._tree(1)["nodes"][0]["bounds_px"] = {"x": 0, "y": 0, "width": 8, "height": 8}
    world.port.render[1] = _render
    return str(created["document_id"])


def _update(document_id: str, request_id: str, **properties: Any) -> dict[str, Any]:
    guard = {"document_id": document_id, "request_id": request_id}
    return {"guard": guard, "layer_id": LAYER, "properties": properties}


def _transfers(world: World) -> list[str]:
    folder = world.data / "transfer"
    return sorted(path.name for path in folder.iterdir()) if folder.exists() else []


def _pixels(path: str) -> np.ndarray:
    with Image.open(path) as image:
        return np.asarray(image.convert("RGBA"))


def test_a_change_is_verified_and_its_before_and_after_kept_as_pngs(world: World) -> None:
    document_id = _document(world)
    server = world.server()
    done = server.content("krita_layer_update", _update(document_id, "req-u", opacity=0.5))
    assert done["status"] == "completed", done["error"]
    data = done["data"]
    assert data["effective_properties"] == {"opacity": 128 / 255}
    checked = data["verification"]
    assert (checked["changed_px"], checked["changed_outside_px"]) == (64, 0)
    assert checked["rect"] == {"x": 0, "y": 0, "width": 8, "height": 8}
    # BGRA from the plugin, RGBA in the PNG.
    assert tuple(_pixels(checked["before"]["path"])[0, 0]) == (30, 20, 255, 255)
    assert tuple(_pixels(checked["after"]["path"])[0, 0]) == (30, 20, 128, 255)
    assert _transfers(world) == []
    path = world.tmp_path / "a" / "journal" / f"{NOW.date().isoformat()}.jsonl"
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    assert [line["tool"] for line in lines[-2:]] == ["krita_layer_update"] * 2


def test_verify_full_and_active_reach_krita(world: World) -> None:
    document_id = _document(world)
    arguments = {**_update(document_id, "req-f", opacity=0.25, active=True), "verify": "full"}
    data = world.server().content("krita_layer_update", arguments)["data"]
    assert data["verification"]["rect"] == {"x": 0, "y": 0, "width": 16, "height": 8}
    assert data["effective_properties"]["active"] is True


def test_a_leak_is_refused_with_its_diff_inline_and_rebuilt(world: World) -> None:
    document_id = _document(world)
    server = world.server()
    protect = {
        "guard": {"document_id": document_id, "request_id": "req-p"},
        "protected_layer_ids": [],
        "allowed_change_mask": {"rect": {"x": 0, "y": 0, "width": 4, "height": 8}},
        "preserve_composite_alpha": False,
        "preserve_canvas": False,
    }
    assert server.content("krita_protection_set", protect)["status"] == "completed"
    result = server.call("krita_layer_update", _update(document_id, "req-l", opacity=0.5))
    content = result.structured_content or {}
    assert result.is_error and content["error"]["code"] == "PROTECTED_REGION_CHANGED"
    details = content["error"]["details"]
    assert (details["rolled_back"], details["rollback_verified"]) == (True, True)
    checked = details["verification"]
    assert (checked["changed_px"], checked["changed_outside_px"]) == (64, 32)
    assert set(checked) == {"mode", "rect", *verification.COUNTS, "diff"}
    diff = _pixels(checked["diff"]["path"])
    red = np.all(diff == verification.OFFENDING, axis=-1)
    assert red[:, 4:8].all() and not red[:, :4].any() and not red[:, 8:].any()
    assert [type(part) for part in result.content] == [type(result.content[0]), ImageContent]
    assert _transfers(world) == []
    got = server.call("krita_operation_get", {"operation_id": content["operation_id"]})
    receipt = (got.structured_content or {})["data"]["receipt"]
    assert receipt == content
    assert any(isinstance(part, ImageContent) for part in got.content)


def test_a_retry_runs_once_and_another_server_gets_the_counts_without_the_images(
    world: World,
) -> None:
    document_id = _document(world)
    arguments = _update(document_id, "req-r", visible=False)
    first = world.server().content("krita_layer_update", arguments)
    again = world.server().content("krita_layer_update", arguments)
    from_b = world.server(B, "b").content("krita_layer_update", arguments)
    assert again == first
    shared = {**first["data"]["verification"], "before": None, "after": None}
    assert from_b["data"]["verification"] == shared
    # Server b's operation id is an alias of the one operation.
    calls = {id(op) for op in world.bridge.jobs._operations.values() if op.op == "layer.update"}
    assert len(calls) == 1


# The server's half of the verification.


def _flags(width: int, height: int, *marked: tuple[int, int, int]) -> np.ndarray:
    flags = np.zeros((height, width, 1), dtype=np.uint8)
    for x, y, value in marked:
        flags[y, x, 0] = value
    return flags


def test_a_diff_keeps_every_offending_pixel_when_it_shrinks() -> None:
    leak = verification.CHANGED | verification.OUTSIDE
    flags = _flags(3000, 2, (2999, 1, leak), (5, 0, verification.CHANGED))
    image = np.asarray(verification.diff_image(flags, None, False))
    assert max(image.shape[:2]) <= verification.DIFF_PX
    red = np.all(image == verification.OFFENDING, axis=-1)
    assert red.sum() == 1 and red[-1, -1]


def test_an_alpha_change_offends_only_under_preserve_composite_alpha() -> None:
    flags = _flags(2, 1, (0, 0, verification.CHANGED | verification.ALPHA))
    for preserve, count in ((False, 0), (True, 1)):
        image = np.asarray(verification.diff_image(flags, None, preserve))
        assert np.all(image == verification.OFFENDING, axis=-1).sum() == count


def test_the_diff_fades_the_scope_as_it_was() -> None:
    before = np.zeros((1, 2, 4), dtype=np.uint8)
    before[0, 0] = (0, 0, 0, 255)
    image = np.asarray(verification.diff_image(_flags(2, 1), before, False))
    assert tuple(image[0, 1]) == (255, 255, 255, 255)
    assert image[0, 0, 0] == round(255 * (1 - verification.FADE))


def test_a_refusal_without_verification_files_passes_unchanged(world: World) -> None:
    error = {"code": "LOCKED_TARGET", "message": "m", "retryable": False, "details": {}}
    outcome = Failed(error, OPERATION, submitted=True)
    assert changes.resolve_update(world.places(), outcome) is outcome


def test_images_that_cannot_be_made_leave_the_change_reported(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    places = world.places()
    places.transfer_dir.mkdir(parents=True, exist_ok=True)
    raw = places.transfer_dir / "before.raw"
    raw.write_bytes(bytes(4))
    spec = {"path": str(raw), "size_px": [1, 1], "format": "BGRA8"}
    sent = {
        "mode": "region",
        "rect": {"x": 0, "y": 0, "width": 1, "height": 1},
        "changed_px": 1,
        "changed_bounds_px": {"x": 0, "y": 0, "width": 1, "height": 1},
        "changed_outside_px": 0,
        "alpha_changed_px": 0,
        "preserve_composite_alpha": False,
        "before": spec,
        "after": None,
        "diff": None,
    }

    def broken(*args: Any) -> Any:
        raise RuntimeError("no images today")

    monkeypatch.setattr(verification, "receipt", broken)
    resolved = changes.resolve_update(places, Done({"verification": sent}, OPERATION))
    assert isinstance(resolved, Done)
    made = resolved.result["verification"]
    assert (made["before"], made["after"], made["changed_px"]) == (None, None, 1)
    assert not raw.exists()


def test_a_png_that_cannot_be_written_keeps_its_pixels_for_a_rebuild(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    places = world.places()
    places.transfer_dir.mkdir(parents=True, exist_ok=True)
    raw = places.transfer_dir / "before.raw"
    raw.write_bytes(bytes([1, 2, 3, 255]))
    sent = {
        "mode": "region",
        "rect": {"x": 0, "y": 0, "width": 1, "height": 1},
        "changed_px": 1,
        "changed_bounds_px": {"x": 0, "y": 0, "width": 1, "height": 1},
        "changed_outside_px": 0,
        "alpha_changed_px": 0,
        "preserve_composite_alpha": False,
        "before": {"path": str(raw), "size_px": [1, 1], "format": "BGRA8"},
        "after": None,
        "diff": None,
    }
    outcome = Done({"verification": sent}, OPERATION)
    real_write = imaging.write

    def full(target: Path, data: bytes) -> None:
        raise OSError("the disk is full")

    monkeypatch.setattr(imaging, "write", full)
    first = changes.resolve_update(places, outcome)
    assert isinstance(first, Done) and first.result["verification"]["before"] is None
    assert raw.exists()
    monkeypatch.setattr(imaging, "write", real_write)
    again = changes.resolve_update(places, outcome)
    assert isinstance(again, Done) and again.result["verification"]["before"] is not None
    assert not raw.exists()


def test_a_diff_too_large_to_inline_is_named_but_not_inlined(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    document_id = _document(world)
    server = world.server()
    protect = {
        "guard": {"document_id": document_id, "request_id": "req-p"},
        "protected_layer_ids": [],
        "allowed_change_mask": {"rect": {"x": 0, "y": 0, "width": 4, "height": 8}},
        "preserve_composite_alpha": False,
        "preserve_canvas": False,
    }
    server.content("krita_protection_set", protect)
    monkeypatch.setattr(imaging, "INLINE_BYTES", 10)
    result = server.call("krita_layer_update", _update(document_id, "req-big", opacity=0.5))
    content = result.structured_content or {}
    assert content["error"]["code"] == "PROTECTED_REGION_CHANGED"
    assert content["error"]["details"]["verification"]["diff"] is not None
    assert not any(isinstance(part, ImageContent) for part in result.content)
