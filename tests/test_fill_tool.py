import copy
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from bridge_core import documents
from fake_krita import layer_id
from jsonschema import Draft202012Validator
from mcp.types import ImageContent
from worlds import NOW, World, running_world

from krita_art_mcp import schemas, strokes
from krita_art_mcp.bridge_client import BridgeClient, Done
from krita_art_mcp.tools import changes, painting

CREATE = {
    "name": "sketch",
    "size_px": [32, 16],
    "color_model": "RGBA",
    "depth": "U8",
    "profile_id": documents.SRGB_PROFILE,
    "background": "transparent",
}
LAYER = layer_id(1, 0)
OPERATION = "op-" + "d" * 32
OUTPUT = Draft202012Validator(schemas.load("krita_paint_fill")["outputSchema"])
RECT = {"type": "rect", "rect": {"x": 4, "y": 2, "width": 10, "height": 6}}


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    with running_world(tmp_path) as running:
        yield running


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    calls: list[tuple[str, dict[str, Any]]] = []
    real = BridgeClient.call

    def spy(self: BridgeClient, op: str, args: Any = None, **kwargs: Any) -> Any:
        calls.append((op, copy.deepcopy(args)))
        return real(self, op, args, **kwargs)

    monkeypatch.setattr(BridgeClient, "call", spy)
    return calls


def _fill(document_id: str = "doc-1", request_id: str = "req-f", **fields: Any) -> dict[str, Any]:
    return {
        "guard": {"document_id": document_id, "request_id": request_id},
        "layer_id": LAYER,
        "shape": copy.deepcopy(RECT),
        "color": {"space": "srgb", "rgba": [0.8, 0.2, 0.4, 1]},
        "opacity": 1,
        **fields,
    }


def _journal(world: World) -> list[dict[str, Any]]:
    path = world.tmp_path / "a" / "journal" / f"{NOW.date().isoformat()}.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def _document(world: World) -> str:
    created = world.server().content("krita_document_create", {**CREATE, "request_id": "req-c"})
    return str(created["document_id"])


# Refusals before the journal.

HUGE = 1.5e308
REFUSALS = [
    (
        _fill(color={"space": "srgb", "rgba": [0.8, 0.2, 0.4, 0.5]}),
        "INVALID_ARGUMENT",
        {"alpha": 0.5, "supported": [1]},
    ),
    (
        _fill(shape={"type": "polygon", "points": [[0, 0], [10, 10], [4, 4]]}),
        "INVALID_ARGUMENT",
        {"field": "shape"},
    ),
    (
        _fill(shape={"type": "path", "points": [[1, 1], [1, 1], [1, 1]]}),
        "INVALID_ARGUMENT",
        {"field": "shape"},
    ),
    (
        _fill(shape={"type": "path", "points": [[-HUGE, 0], [HUGE, 1], [0, HUGE]]}),
        "INVALID_ARGUMENT",
        {"field": "shape"},
    ),
]


@pytest.mark.parametrize(
    ("arguments", "code", "details"),
    REFUSALS,
    ids=["a colour with alpha", "a flat polygon", "a flat path", "a curve that overflows"],
)
def test_a_refusal_is_returned_before_the_journal(
    world: World,
    sent: list[tuple[str, dict[str, Any]]],
    arguments: dict[str, Any],
    code: str,
    details: dict[str, Any],
) -> None:
    result = world.server().call("krita_paint_fill", arguments)
    content = result.structured_content or {}
    assert result.is_error and content["operation_id"] is None
    assert content["error"]["code"] == code
    assert details.items() <= content["error"]["details"].items()
    assert sent == [] and _journal(world) == []


@pytest.mark.parametrize(
    "fields",
    [
        {"opacity": 1.5},
        {"shape": {"type": "rect", "rect": {"x": -1, "y": 0, "width": 4, "height": 4}}},
        {"shape": {"type": "path", "points": [[0, 0], [4, 4]]}},
        {"shape": {"type": "circle"}},
        {"blend_mode": "glow"},
        {"brush": {}},
    ],
    ids=["opacity", "a rect off the canvas", "two points", "a circle", "a blend", "a brush"],
)
def test_the_schema_refuses_what_no_fill_takes(
    world: World, sent: list[tuple[str, dict[str, Any]]], fields: dict[str, Any]
) -> None:
    content = world.server().content("krita_paint_fill", _fill(**fields))
    assert content["error"]["code"] == "INVALID_ARGUMENT" and sent == []


# What is sent.


def test_the_defaults_are_filled_and_the_rect_sent(
    world: World, sent: list[tuple[str, dict[str, Any]]]
) -> None:
    document_id = _document(world)
    world.server().content("krita_paint_fill", _fill(document_id))
    assert sent[-1] == (
        "paint.fill",
        {
            "document_id": document_id,
            "layer_id": LAYER,
            "verify": "region",
            "shape": {"kind": "rect", "rect": RECT["rect"]},
            "fill": {
                "color": [0.8, 0.2, 0.4, 1],
                "opacity": 1,
                "blend_mode": "normal",
                "alpha_lock": False,
            },
        },
    )


@pytest.mark.parametrize(
    ("shape", "expected"),
    [
        ({"type": "selection"}, {"kind": "selection"}),
        (
            {"type": "ellipse", "rect": {"x": 1, "y": 1, "width": 6, "height": 4}},
            {"kind": "ellipse", "rect": {"x": 1, "y": 1, "width": 6, "height": 4}},
        ),
        (
            {"type": "polygon", "points": [[1, 1], [9, 2], [4, 7]]},
            {"kind": "polygon", "points": [[1, 1], [9, 2], [4, 7]]},
        ),
        (
            {"type": "path", "points": [[1.0, 1.0], [9.0, 2.0], [4.0, 7.0]]},
            {
                "kind": "path",
                **strokes.closed_catmull_rom([(1.0, 1.0), (9.0, 2.0), (4.0, 7.0)]),
            },
        ),
    ],
    ids=["selection", "ellipse", "polygon", "path"],
)
def test_each_shape_is_sent_as_the_bridge_takes_it(
    world: World,
    sent: list[tuple[str, dict[str, Any]]],
    shape: dict[str, Any],
    expected: dict[str, Any],
) -> None:
    fields: dict[str, Any] = {
        "blend_mode": "multiply",
        "alpha_lock": True,
        "verify": "full",
        "opacity": 0.5,
    }
    world.server().content("krita_paint_fill", _fill(shape=shape, **fields))
    op, args = sent[-1]
    assert (op, args["shape"], args["verify"]) == ("paint.fill", expected, "full")
    assert args["fill"] == {
        "color": [0.8, 0.2, 0.4, 1],
        "opacity": 0.5,
        "blend_mode": "multiply",
        "alpha_lock": True,
    }


# The receipt, on outcomes built by hand.


def _result(**fields: Any) -> dict[str, Any]:
    return {
        "document_id": "doc-1",
        "layer_id": LAYER,
        "fill_id": OPERATION,
        "shape": "ellipse",
        "shape_bounds_px": {"x": 1, "y": 0, "width": 1, "height": 1},
        "effective_fill": {
            "preset_id": "c)_Pencil-3_Large_4B.kpp",
            "color": {"space": "srgb", "rgba": [0.8, 0.2, 0.4, 1]},
            "opacity": 1,
            "blend_mode": "normal",
            "alpha_lock": False,
            "antialias": True,
        },
        "changed_bounds_px": {"x": 1, "y": 0, "width": 1, "height": 1},
        "layer_bounds_px": {"x": -3, "y": 0, "width": 5, "height": 1},
        "protected_pixels_changed": 0,
        "undo_label": "Scripted Brush Stroke",
        "undo_steps": 1,
        "history_sealed": False,
        "verification": {
            "mode": "region",
            "rect": {"x": 0, "y": 0, "width": 2, "height": 1},
            "changed_px": 1,
            "changed_bounds_px": {"x": 1, "y": 0, "width": 1, "height": 1},
            "changed_outside_px": 0,
            "alpha_changed_px": 1,
            "before": None,
            "after": None,
        },
        **fields,
    }


def test_a_fill_receipt_matches_its_schema_and_says_what_it_filled() -> None:
    receipt = painting.fill_receipt(Done(_result(), OPERATION))
    content = receipt.structured_content or {}
    assert list(OUTPUT.iter_errors(content)) == []
    assert "document_id" not in content["data"] and content["document_id"] == "doc-1"
    line = receipt.content[0].text  # type: ignore[union-attr]
    assert line.startswith(f"Filled an ellipse on layer {LAYER} of doc-1; 1 px changed")


def test_a_fill_that_changed_nothing_says_history_stops_there() -> None:
    result = _result(history_sealed=True, changed_bounds_px=None, shape="selection")
    receipt = painting.fill_receipt(Done(result, OPERATION))
    assert list(OUTPUT.iter_errors(receipt.structured_content or {})) == []
    line = receipt.content[0].text  # type: ignore[union-attr]
    assert line.startswith("Filled the selection") and "history stops at this fill" in line


# End to end, against the plugin core over HTTP.


def test_a_fill_reaches_the_plugin_and_comes_back_verified_with_its_pngs(world: World) -> None:
    document_id = _document(world)
    done = world.server().content("krita_paint_fill", _fill(document_id))
    assert done["status"] == "completed", done["error"]
    assert not list(OUTPUT.iter_errors(done))
    data = done["data"]
    assert (data["shape"], data["shape_bounds_px"], data["undo_steps"]) == ("rect", RECT["rect"], 1)
    assert data["changed_bounds_px"] == RECT["rect"]
    for name in ("before", "after"):
        path = Path(data["verification"][name]["path"])
        assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    phases = [line["phase"] for line in _journal(world) if line["tool"] == "krita_paint_fill"]
    assert phases == ["dispatched", "finished"]


@pytest.mark.parametrize(
    "rect",
    [
        {"x": 0, "y": 0, "width": 6, "height": 4},
        {"x": 26, "y": 0, "width": 6, "height": 4},
        {"x": 0, "y": 12, "width": 6, "height": 4},
        {"x": 26, "y": 12, "width": 6, "height": 4},
        {"x": 0, "y": 0, "width": 32, "height": 16},
    ],
    ids=["top left", "top right", "bottom left", "bottom right", "the whole canvas"],
)
@pytest.mark.parametrize("verify", ["region", "full"])
def test_each_edge_and_corner_passes_the_output_schema(
    world: World, rect: dict[str, int], verify: str
) -> None:
    document_id = _document(world)
    arguments = _fill(document_id, shape={"type": "rect", "rect": rect}, verify=verify)
    done = world.server().content("krita_paint_fill", arguments)
    assert done["status"] == "completed", done["error"]
    assert not list(OUTPUT.iter_errors(done))
    assert done["data"]["changed_bounds_px"] == rect


def test_a_shape_past_the_canvas_is_refused_by_the_plugin_and_not_applied(world: World) -> None:
    document_id = _document(world)
    shape = {"type": "polygon", "points": [[20, 2], [33, 8], [20, 14]]}
    failed = world.server().content("krita_paint_fill", _fill(document_id, shape=shape))
    error = failed["error"]
    assert (error["code"], error["details"]["outcome"]) == ("INVALID_ARGUMENT", "not_applied")
    assert error["details"]["bounds_px"] == {"x": 20, "y": 2, "width": 13, "height": 12}
    assert world.port.shapes == []


def test_a_leaking_fill_is_undone_and_its_diff_shown_inline_and_by_operation_get(
    world: World,
) -> None:
    document_id = _document(world)
    world.port.stray = [{"x": 28, "y": 12, "width": 2, "height": 2}]
    result = world.server().call("krita_paint_fill", _fill(document_id))
    content = result.structured_content or {}
    error = content["error"]
    assert error["code"] == "PROTECTED_REGION_CHANGED" and error["details"]["rollback_verified"]
    assert any(isinstance(part, ImageContent) for part in result.content)
    got = world.server().call("krita_operation_get", {"operation_id": content["operation_id"]})
    assert (got.structured_content or {})["data"]["receipt"] == content
    assert any(isinstance(part, ImageContent) for part in got.content)


def test_a_retried_fill_returns_its_receipt_and_fills_once(world: World) -> None:
    document_id = _document(world)
    first = world.server().content("krita_paint_fill", _fill(document_id))
    again = world.server().content("krita_paint_fill", _fill(document_id))
    assert again == first and len(world.port.shapes) == 1


def test_history_names_the_fill_by_its_tool(world: World) -> None:
    document_id = _document(world)
    world.server().content("krita_paint_fill", _fill(document_id))
    arguments = {
        "guard": {"document_id": document_id, "request_id": "req-h"},
        "action": "undo",
        "steps": 1,
    }
    undone = world.server().content("krita_history_step", arguments)
    assert [step["tool"] for step in undone["data"]["steps"]] == ["krita_paint_fill"]
    assert changes.STEP_TOOLS["paint.fill"] == "krita_paint_fill"
