import copy
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from mcp.types import ImageContent
from worlds import NOW, World, running_world

from krita_art_mcp import journal, schemas, verification
from krita_art_mcp.bridge_client import BridgeClient, Done, Failed, Outcome
from krita_art_mcp.tools import changes, painting
from krita_art_mcp.tools.dispatch import ToolCall

LAYER = "3f0c9a2e-8b41-4d6a-9e57-c1a2b3d4e5f6"
OPERATION = "op-" + "d" * 32
BRUSH: dict[str, Any] = {
    "preset_id": "b) Basic-5 Size.kpp",
    "size_px": 6,
    "opacity": 0.8,
    "flow": 1,
    "color": {"space": "srgb", "rgba": [0.4, 0.3, 0.3, 1]},
    "eraser": False,
}
OUTPUT = Draft202012Validator(schemas.load("krita_paint_stroke")["outputSchema"])


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    with running_world(tmp_path) as running:
        yield running


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    # The ops the server sends, with their args, before the bridge answers.
    calls: list[tuple[str, dict[str, Any]]] = []
    real = BridgeClient.call

    def spy(self: BridgeClient, op: str, args: Any = None, **kwargs: Any) -> Any:
        calls.append((op, copy.deepcopy(args)))
        return real(self, op, args, **kwargs)

    monkeypatch.setattr(BridgeClient, "call", spy)
    return calls


def _stroke(request_id: str = "req-s", **fields: Any) -> dict[str, Any]:
    return {
        "guard": {"document_id": "doc-1", "request_id": request_id},
        "layer_id": LAYER,
        "brush": copy.deepcopy(BRUSH),
        "points": [{"x": 1.5, "y": 2.5}, {"x": 7.5, "y": 3.5}],
        **fields,
    }


def _journal(world: World) -> list[dict[str, Any]]:
    path = world.tmp_path / "a" / "journal" / f"{NOW.date().isoformat()}.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def _with_brush(**fields: Any) -> dict[str, Any]:
    arguments = _stroke()
    arguments["brush"].update(fields)
    return arguments


def _with_point(index: int, **fields: Any) -> dict[str, Any]:
    arguments = _stroke()
    arguments["points"][index].update(fields)
    return arguments


REFUSALS = [
    ({**_stroke(), "smooth": "basic"}, "UNSUPPORTED_CAPABILITY", {"smooth": "basic"}),
    ({**_stroke(), "smooth": "stabilizer"}, "UNSUPPORTED_CAPABILITY", {"smooth": "stabilizer"}),
    (_with_brush(antialias=False), "UNSUPPORTED_CAPABILITY", {"antialias": False}),
    (_with_point(1, pressure=0.4), "UNSUPPORTED_CAPABILITY", {"point": 1, "fields": ["pressure"]}),
    *[
        (_with_point(0, **{field: 1}), "UNSUPPORTED_CAPABILITY", {"point": 0, "fields": [field]})
        for field in painting.PER_POINT
    ],
    (
        _with_point(1, pressure=0.5, speed=2, time_ms=40),
        "UNSUPPORTED_CAPABILITY",
        {"point": 1, "fields": ["pressure", "time_ms", "speed"]},
    ),
    (
        _with_brush(eraser=True, alpha_lock=True),
        "INVALID_ARGUMENT",
        {"eraser": True, "alpha_lock": True},
    ),
    (
        _with_brush(color={"space": "srgb", "rgba": [0.4, 0.3, 0.3, 0.5]}),
        "INVALID_ARGUMENT",
        {"alpha": 0.5},
    ),
    (_with_brush(eraser=True), "UNSUPPORTED_CAPABILITY", {"eraser": True, "supported": [False]}),
    (
        {**_stroke(), "points": [{"x": 4.5, "y": 4.5}]},
        "UNSUPPORTED_CAPABILITY",
        {"length_px": 0, "minimum_length_px": 0.5},
    ),
    (
        {**_stroke(), "points": [{"x": 4.5, "y": 4.5}, {"x": 4.5, "y": 4.5}]},
        "UNSUPPORTED_CAPABILITY",
        {"length_px": 0, "minimum_length_px": 0.5},
    ),
    (
        {**_stroke(), "points": [{"x": 4.5, "y": 4.5}, {"x": 4.6, "y": 4.5}, {"x": 4.5, "y": 4.7}]},
        "UNSUPPORTED_CAPABILITY",
        {"minimum_length_px": 0.5},
    ),
]


@pytest.mark.parametrize(("arguments", "code", "details"), REFUSALS)
def test_a_refusal_is_returned_before_the_journal(
    world: World,
    sent: list[tuple[str, dict[str, Any]]],
    arguments: dict[str, Any],
    code: str,
    details: dict[str, Any],
) -> None:
    result = world.server().call("krita_paint_stroke", arguments)
    content = result.structured_content or {}
    assert result.is_error and content["operation_id"] is None
    assert content["error"]["code"] == code
    assert details.items() <= content["error"]["details"].items()
    assert sent == [] and _journal(world) == []


def test_smooth_and_the_gate_name_what_they_support(world: World) -> None:
    server = world.server()
    smooth = server.content("krita_paint_stroke", {**_stroke(), "smooth": "basic"})
    assert smooth["error"]["details"]["supported"] == ["none", "catmull_rom"]
    gate = server.content("krita_paint_stroke", _with_point(0, tilt_x=10))
    assert gate["error"]["details"]["input_fallback"] == ["flat"]


@pytest.mark.parametrize(
    ("change", "field"),
    [
        ({"brush": {**BRUSH, "size_px": float("nan")}}, "brush.size_px"),
        ({"brush": {**BRUSH, "rotation_deg": float("inf")}}, "brush.rotation_deg"),
        (
            {"brush": {**BRUSH, "color": {"space": "srgb", "rgba": [float("nan"), 0, 0, 1]}}},
            "brush.color",
        ),
        ({"points": [{"x": float("nan"), "y": 0}]}, "points"),
        ({"points": [{"x": 10**400, "y": 0}]}, "points"),
        # Integers too large for a float would raise inside the smoothing.
        ({"points": [{"x": 10**400, "y": 0}] * 3, "smooth": "catmull_rom"}, "points"),
        # Finite points whose controls overflow.
        (
            {
                "points": [{"x": 1.7e308, "y": 0}, {"x": -1.7e308, "y": 0}, {"x": 1.7e308, "y": 0}],
                "smooth": "catmull_rom",
            },
            "points",
        ),
    ],
)
def test_a_number_that_is_not_finite_is_refused_before_the_journal(
    world: World, change: dict[str, Any], field: str
) -> None:
    # MCP carries NaN and Infinity, and the schema's bounds let them through.
    call = ToolCall(world.client(), world.journal(), world.places())
    result = painting.paint_stroke(call, {**_stroke(), **change})
    content = result.structured_content or {}
    assert content["error"]["code"] == "INVALID_ARGUMENT"
    assert content["error"]["details"] == {"field": field}
    assert content["operation_id"] is None and _journal(world) == []


def test_the_defaults_are_filled_and_the_path_sent(
    world: World, sent: list[tuple[str, dict[str, Any]]]
) -> None:
    arguments = _stroke()
    world.server().call("krita_paint_stroke", arguments)
    assert sent == [
        (
            "paint.stroke",
            {
                "document_id": "doc-1",
                "layer_id": LAYER,
                "verify": "region",
                "accepted_points": 2,
                "brush": {
                    "preset_id": "b) Basic-5 Size.kpp",
                    "preset_sha256": None,
                    "size_px": 6,
                    "opacity": 0.8,
                    "flow": 1,
                    "color": [0.4, 0.3, 0.3, 1],
                    "eraser": False,
                    "blend_mode": "normal",
                    "alpha_lock": False,
                    "rotation_deg": 0,
                },
                "path": {"start": [1.5, 2.5], "segments": [[7.5, 3.5]]},
            },
        )
    ]
    dispatched = [line for line in _journal(world) if line["phase"] == "dispatched"]
    folder = world.tmp_path / "a" / "journal"
    assert [(line["tool"], journal.arguments(folder, line)) for line in dispatched] == [
        ("krita_paint_stroke", arguments)
    ]


def test_given_values_and_flat_input_reach_the_op(
    world: World, sent: list[tuple[str, dict[str, Any]]]
) -> None:
    brush = {
        **BRUSH,
        "preset_sha256": "e" * 64,
        "blend_mode": "multiply",
        "alpha_lock": True,
        "rotation_deg": 30,
        "antialias": True,
    }
    points = [
        {"x": 0, "y": 0, "pressure": 0.4, "tilt_x": 20, "time_ms": 0},
        {"x": 6, "y": 12, "speed": 3, "rotation_deg": 5, "tangential_pressure": -1},
        {"x": 18, "y": 6, "pressure": 1, "tilt_y": -90, "time_ms": 30},
    ]
    arguments = {
        **_stroke(),
        "brush": brush,
        "points": points,
        "smooth": "catmull_rom",
        "input_fallback": "flat",
        "verify": "full",
    }
    world.server().call("krita_paint_stroke", arguments)
    [(op, args)] = sent
    assert (op, args["verify"], args["accepted_points"]) == ("paint.stroke", "full", 3)
    expected = {**brush, "color": [0.4, 0.3, 0.3, 1]}
    del expected["antialias"]
    assert args["brush"] == expected
    assert args["path"] == {
        "start": [0, 0],
        "segments": [[1, 2, 3, 11, 6, 12], [9, 13, 16, 7, 18, 6]],
    }


# The receipt, on outcomes built by hand: the plugin op arrives with its own part.


def _raw(world: World, name: str, data: bytes, size: list[int], kind: str) -> dict[str, Any]:
    folder = world.places().transfer_dir
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(data)
    return {"path": str(folder / name), "size_px": size, "format": kind}


def _counts(**fields: Any) -> dict[str, Any]:
    return {
        "mode": "region",
        "rect": {"x": 0, "y": 0, "width": 2, "height": 1},
        "changed_px": 1,
        "changed_bounds_px": {"x": 1, "y": 0, "width": 1, "height": 1},
        "changed_outside_px": 0,
        "alpha_changed_px": 1,
        "preserve_composite_alpha": False,
        **fields,
    }


def _result(checked: dict[str, Any]) -> dict[str, Any]:
    return {
        "document_id": "doc-1",
        "layer_id": LAYER,
        "stroke_id": OPERATION,
        "accepted_points": 2,
        "effective_brush": {
            "preset_id": "b) Basic-5 Size.kpp",
            "preset_sha256": "d" * 64,
            "engine": "paintbrush",
            "size_px": 6,
            "opacity": 0.8,
            "flow": 1,
            "color": {"space": "srgb", "rgba": [0.4, 0.3, 0.3, 1]},
            "eraser": False,
            "blend_mode": "normal",
            "alpha_lock": False,
            "rotation_deg": 0,
            "antialias": True,
            "spacing": None,
            "reach": {"tip": "round", "scatter": 0, "margin_px": 32},
        },
        "changed_bounds_px": {"x": 1, "y": 0, "width": 1, "height": 1},
        "protected_pixels_changed": 0,
        "undo_label": "Scripted Brush Stroke",
        "undo_steps": 1,
        "history_sealed": False,
        "verification": checked,
    }


def _checked_receipt(outcome: Outcome) -> tuple[Any, dict[str, Any]]:
    receipt = painting.paint_receipt(outcome)
    content = receipt.structured_content or {}
    assert list(OUTPUT.iter_errors(content)) == []
    return receipt, content


def test_a_stroke_receipt_keeps_the_scope_as_pngs_and_says_flat(world: World) -> None:
    places = world.places()
    before = _raw(world, "before.raw", bytes([0, 0, 0, 0] * 2), [2, 1], "BGRA8")
    after = _raw(world, "after.raw", bytes([0, 0, 0, 0, 30, 20, 10, 255]), [2, 1], "BGRA8")
    checked = _counts(before=before, after=after, diff=None)
    resolved = changes.resolve_update(places, Done(_result(checked), OPERATION))
    receipt, content = _checked_receipt(resolved)
    data = content["data"]
    assert (content["status"], content["document_id"]) == ("completed", "doc-1")
    assert "document_id" not in data and data["input_applied"] == "flat"
    expected = {key: value for key, value in _result({}).items() if key != "document_id"}
    assert {key: value for key, value in data.items() if key != "verification"} == {
        **{key: value for key, value in expected.items() if key != "verification"},
        "input_applied": "flat",
    }
    made = data["verification"]
    assert set(made) == {"mode", "rect", *verification.COUNTS, "before", "after"}
    assert made["after"]["path"].endswith(f"{OPERATION}.after.png")
    assert Path(made["before"]["path"]).exists() and not Path(after["path"]).exists()
    assert receipt.content[0].text == (
        f"Painted 2 point(s) on layer {LAYER} of doc-1; 1 px changed, verified over region."
    )


def test_a_sealed_stroke_says_history_stops_there(world: World) -> None:
    checked = _counts(before=None, after=None, diff=None)
    result = {**_result(checked), "changed_bounds_px": None, "history_sealed": True}
    resolved = changes.resolve_update(world.places(), Done(result, OPERATION))
    receipt, content = _checked_receipt(resolved)
    assert content["data"]["history_sealed"] is True
    assert receipt.content[0].text.endswith(
        "; the layer did not change, so history stops at this stroke."
    )


def test_pixels_another_server_took_leave_the_images_null(world: World) -> None:
    gone = {"path": str(world.places().transfer_dir / "gone.raw"), "size_px": [2, 1]}
    checked = _counts(before={**gone, "format": "BGRA8"}, after=None, diff=None)
    resolved = changes.resolve_update(world.places(), Done(_result(checked), OPERATION))
    _, content = _checked_receipt(resolved)
    made = content["data"]["verification"]
    assert (made["before"], made["after"], made["changed_px"]) == (None, None, 1)


def test_a_refused_stroke_inlines_its_diff(world: World) -> None:
    flags = verification.CHANGED | verification.OUTSIDE
    diff = _raw(world, "diff.raw", bytes([0, flags]), [2, 1], "A8")
    before = _raw(world, "before.raw", bytes([0, 0, 0, 255] * 2), [2, 1], "BGRA8")
    details = {
        "document_id": "doc-1",
        "layer_id": LAYER,
        "rolled_back": True,
        "rollback_verified": True,
        "protected_layer_ids": [],
        "protected_pixels_changed": 0,
        "target_outside_reach": False,
        "verification": _counts(changed_outside_px=1, before=before, diff=diff),
    }
    error = {
        "code": "PROTECTED_REGION_CHANGED",
        "message": "The stroke leaked.",
        "retryable": False,
        "details": details,
    }
    resolved = changes.resolve_update(world.places(), Failed(error, OPERATION, submitted=True))
    receipt, content = _checked_receipt(resolved)
    assert (content["status"], content["document_id"]) == ("failed", "doc-1")
    made = content["error"]["details"]["verification"]
    assert made["diff"]["path"].endswith(f"{OPERATION}.diff.png")
    assert [type(part) for part in receipt.content][1:] == [ImageContent]


def test_a_refusal_without_a_diff_has_no_image() -> None:
    error = {"code": "LOCKED_TARGET", "message": "m", "retryable": False, "details": {}}
    receipt, content = _checked_receipt(Failed(error, OPERATION, submitted=True))
    assert content["error"]["code"] == "LOCKED_TARGET" and len(receipt.content) == 1


def test_a_full_stroke_may_report_a_reach_the_plugin_cannot_name(world: World) -> None:
    result = _result(_counts(mode="full", before=None, after=None, diff=None))
    result["effective_brush"]["reach"] = {"tip": "unknown", "scatter": 5, "margin_px": 32}
    resolved = changes.resolve_update(world.places(), Done(result, OPERATION))
    _, content = _checked_receipt(resolved)
    assert content["data"]["effective_brush"]["reach"]["tip"] == "unknown"
