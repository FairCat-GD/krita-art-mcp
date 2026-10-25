import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from bridge_core import documents
from fake_krita import layer_id
from jsonschema import Draft202012Validator
from mcp.types import ImageContent
from worlds import NOW, B, World, running_world

from krita_art_mcp import schemas

CREATE = {
    "name": "sketch",
    "size_px": [32, 16],
    "color_model": "RGBA",
    "depth": "U8",
    "profile_id": documents.SRGB_PROFILE,
    "background": "transparent",
}
LAYER = layer_id(1, 0)
OUTPUT = Draft202012Validator(schemas.load("krita_paint_stroke")["outputSchema"])


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    with running_world(tmp_path) as running:
        yield running


def _lines(world: World) -> list[dict[str, Any]]:
    path = world.tmp_path / "a" / "journal" / f"{NOW.date().isoformat()}.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


def _document(world: World) -> str:
    created = world.server().content("krita_document_create", {**CREATE, "request_id": "req-c"})
    return str(created["document_id"])


def _stroke(document_id: str, request_id: str) -> dict[str, Any]:
    return {
        "guard": {"document_id": document_id, "request_id": request_id},
        "layer_id": LAYER,
        "brush": {
            "preset_id": "basic-round.kpp",
            "size_px": 4,
            "opacity": 1,
            "flow": 1,
            "color": {"space": "srgb", "rgba": [0.8, 0.2, 0.4, 1]},
            "eraser": False,
        },
        "points": [{"x": 4.5, "y": 4.5}, {"x": 10.5, "y": 6.5}],
    }


def test_a_stroke_reaches_the_plugin_and_comes_back_verified_with_its_pngs(world: World) -> None:
    document_id = _document(world)
    done = world.server().content("krita_paint_stroke", _stroke(document_id, "req-s"))
    assert done["status"] == "completed", done["error"]
    assert not list(OUTPUT.iter_errors(done))
    data = done["data"]
    assert (data["input_applied"], data["undo_steps"], data["accepted_points"]) == ("flat", 1, 2)
    assert data["effective_brush"]["preset_id"] == "basic-round.kpp"
    checked = data["verification"]
    assert checked["changed_px"] > 0 and checked["changed_outside_px"] == 0
    for name in ("before", "after"):
        assert Path(checked[name]["path"]).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    phases = [line["phase"] for line in _lines(world) if line["tool"] == "krita_paint_stroke"]
    assert phases == ["dispatched", "finished"]


def test_a_leaking_stroke_is_undone_and_its_diff_shown_inline_and_by_operation_get(
    world: World,
) -> None:
    document_id = _document(world)
    server = world.server()
    protected = server.content(
        "krita_protection_set",
        {
            "guard": {"document_id": document_id, "request_id": "req-p"},
            "protected_layer_ids": [],
            "allowed_change_mask": {"rect": {"x": 0, "y": 0, "width": 16, "height": 16}},
            "preserve_composite_alpha": False,
            "preserve_canvas": False,
        },
    )
    assert protected["status"] == "completed", protected["error"]
    world.port.stray.append({"x": 24, "y": 2, "width": 4, "height": 4})
    result = server.call("krita_paint_stroke", _stroke(document_id, "req-leak"))
    content = result.structured_content or {}
    error = content["error"]
    assert (error["code"], error["retryable"]) == ("PROTECTED_REGION_CHANGED", False)
    details = error["details"]
    assert (details["rolled_back"], details["rollback_verified"]) == (True, True)
    assert details["verification"]["changed_outside_px"] > 0
    assert any(isinstance(part, ImageContent) for part in result.content)
    got = server.call("krita_operation_get", {"operation_id": content["operation_id"]})
    receipt = (got.structured_content or {})["data"]["receipt"]
    assert receipt == content
    assert any(isinstance(part, ImageContent) for part in got.content)


def test_a_retry_paints_once_and_another_server_shares_the_receipt(world: World) -> None:
    document_id = _document(world)
    arguments = _stroke(document_id, "req-retry")
    first = world.server().content("krita_paint_stroke", arguments)
    again = world.server().content("krita_paint_stroke", arguments)
    other = world.server(B, "b").content("krita_paint_stroke", arguments)
    assert first["status"] == "completed", first["error"]
    assert again == first
    assert other["data"]["stroke_id"] == first["data"]["stroke_id"]
    # The other server finds the pixels taken, so its images are null; the counts are the same.
    assert other["data"]["verification"]["before"] is None
    assert len(world.port.paths) == 1


def test_history_undoes_a_stroke_by_its_tool_name_and_captures_its_region(world: World) -> None:
    document_id = _document(world)
    server = world.server()
    painted = server.content("krita_paint_stroke", _stroke(document_id, "req-h"))
    assert painted["status"] == "completed", painted["error"]
    undone = server.content(
        "krita_history_step",
        {
            "guard": {"document_id": document_id, "request_id": "req-u"},
            "action": "undo",
            "steps": 1,
        },
    )
    assert undone["status"] == "completed", undone["error"]
    data = undone["data"]
    assert data["steps"] == [
        {"tool": "krita_paint_stroke", "operation_id": painted["operation_id"]}
    ]
    assert data["verified"] is True and data["capture"] is not None
