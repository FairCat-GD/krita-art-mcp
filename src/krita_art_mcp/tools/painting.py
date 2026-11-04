import itertools
import math
from typing import Any

from mcp.types import CallToolResult

from krita_art_mcp import envelope, strokes
from krita_art_mcp.bridge_client import BeforeSend, Failed, Outcome
from krita_art_mcp.tools import changes
from krita_art_mcp.tools.dispatch import ToolCall, finite, from_outcome, journaled

# Point fields Phase 1 cannot apply: Node.paintPath paints every point at pressure 1.
PER_POINT = ("time_ms", "tilt_x", "tilt_y", "rotation_deg", "tangential_pressure", "speed")
# Krita paints no dab for a stroke shorter than this: 0.01 px painted nothing, 0.5 px one dab.
MIN_LENGTH_PX = 0.5


def paint_stroke(call: ToolCall, arguments: dict[str, Any]) -> CallToolResult:
    op_args = stroke_op(arguments)
    if isinstance(op_args, CallToolResult):
        return op_args
    guard = arguments["guard"]

    def send(before_send: BeforeSend) -> Outcome:
        outcome = call.bridge.call(
            "paint.stroke", op_args, request_id=guard["request_id"], before_send=before_send
        )
        return changes.resolve_update(call.places, outcome)

    return journaled(
        call, "krita_paint_stroke", arguments, guard["request_id"], send, paint_receipt
    )


def stroke_op(arguments: dict[str, Any]) -> dict[str, Any] | CallToolResult:
    # The bridge op's arguments for a stroke, or the refusal; the probe sends them itself too.
    refused = _refusal(arguments)
    if refused is not None:
        return refused
    guard = arguments["guard"]
    brush = arguments["brush"]
    points = arguments["points"]
    op_args = {
        "document_id": guard["document_id"],
        "layer_id": arguments["layer_id"],
        "verify": arguments.get("verify", "region"),
        "accepted_points": len(points),
        "brush": {
            "preset_id": brush["preset_id"],
            "preset_sha256": brush.get("preset_sha256"),
            "size_px": brush["size_px"],
            "opacity": brush["opacity"],
            "flow": brush["flow"],
            "color": list(brush["color"]["rgba"]),
            "eraser": brush["eraser"],
            "blend_mode": brush.get("blend_mode", "normal"),
            "alpha_lock": brush.get("alpha_lock", False),
            "rotation_deg": brush.get("rotation_deg", 0),
        },
    }
    path = _path(points, arguments.get("smooth", "none"))
    if path is None:
        message = "points are so large that the smoothed path's control points are not finite."
        return envelope.failure("INVALID_ARGUMENT", message, details={"field": "points"})
    length = sum(
        math.hypot(point["x"] - previous["x"], point["y"] - previous["y"])
        for previous, point in itertools.pairwise(points)
    )
    if length < MIN_LENGTH_PX:
        message = (
            f"Krita paints no dab for a stroke shorter than {MIN_LENGTH_PX} px; send points at "
            "least that far apart."
        )
        details = {"length_px": length, "minimum_length_px": MIN_LENGTH_PX}
        return envelope.failure("UNSUPPORTED_CAPABILITY", message, details=details)
    op_args["path"] = path
    return op_args


def _refusal(arguments: dict[str, Any]) -> CallToolResult | None:
    # Refused before the journal: no op could paint these.
    alpha = arguments["brush"]["color"]["rgba"][3]
    if alpha != 1:
        message = "The colour's alpha must be 1; transparency comes from the brush's opacity."
        details: dict[str, Any] = {"alpha": alpha, "supported": [1]}
        return envelope.failure("INVALID_ARGUMENT", message, details=details)
    if arguments.get("input_fallback") != "flat":
        for index, point in enumerate(arguments["points"]):
            fields = ["pressure"] if point.get("pressure", 1) != 1 else []
            fields += [field for field in PER_POINT if field in point]
            if fields:
                message = (
                    f"Point {index} carries {', '.join(fields)}, which this release cannot "
                    "apply. Send input_fallback flat to paint every point at pressure 1."
                )
                details = {"point": index, "fields": fields, "input_fallback": ["flat"]}
                return envelope.failure("UNSUPPORTED_CAPABILITY", message, details=details)
    return None


def _path(points: list[dict[str, Any]], smooth: str) -> dict[str, Any] | None:
    # The server refuses a point that is not finite before any tool runs; smoothing can still
    # overflow from large finite ones, and then this is None.
    path = strokes.path(points, smooth)
    numbers = [*path["start"], *(value for segment in path["segments"] for value in segment)]
    return path if all(finite(value) for value in numbers) else None


def paint_receipt(outcome: Outcome) -> CallToolResult:
    def data(result: dict[str, Any]) -> dict[str, Any]:
        return {**changes.without_document(result), "input_applied": "flat"}

    def text(result: dict[str, Any]) -> str:
        checked = result["verification"]
        line = (
            f"Painted {result['accepted_points']} point(s) on layer {result['layer_id']} of "
            f"{result['document_id']}; {checked['changed_px']} px changed, verified over "
            f"{checked['mode']}"
        )
        if result["history_sealed"]:
            # Its undo would change no pixel, so nothing could confirm it.
            line += "; the layer did not change, so history stops at this stroke"
        return line + "."

    receipt = from_outcome(outcome, data, text, changes.document_of)
    if isinstance(outcome, Failed):
        image = changes.diff_image(outcome.error["details"])
        if image is not None:
            receipt.content.append(image)
    return receipt
