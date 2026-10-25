import math
from typing import Any

from mcp.types import CallToolResult

from krita_art_mcp import envelope, strokes
from krita_art_mcp.bridge_client import BeforeSend, Failed, Outcome
from krita_art_mcp.tools import changes
from krita_art_mcp.tools.dispatch import ToolCall, from_outcome, journaled

# Point fields Phase 1 cannot apply: Node.paintPath paints every point at pressure 1.
PER_POINT = ("time_ms", "tilt_x", "tilt_y", "rotation_deg", "tangential_pressure", "speed")
SMOOTHED = ["none", "catmull_rom"]
BRUSH_NUMBERS = ("size_px", "opacity", "flow", "rotation_deg")


def paint_stroke(call: ToolCall, arguments: dict[str, Any]) -> CallToolResult:
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
    unbounded = _unbounded(op_args["brush"]) or (None if path is not None else "points")
    if unbounded is not None:
        message = f"{unbounded} holds a number that is not finite."
        return envelope.failure("INVALID_ARGUMENT", message, details={"field": unbounded})
    op_args["path"] = path

    def send(before_send: BeforeSend) -> Outcome:
        outcome = call.bridge.call(
            "paint.stroke", op_args, request_id=guard["request_id"], before_send=before_send
        )
        return changes.resolve_update(call.places, outcome)

    return journaled(
        call, "krita_paint_stroke", arguments, guard["request_id"], send, paint_receipt
    )


def _refusal(arguments: dict[str, Any]) -> CallToolResult | None:
    # Refused before the journal: no op could paint these.
    brush = arguments["brush"]
    if brush["eraser"] and brush.get("alpha_lock", False):
        message = "An eraser cannot paint with alpha_lock: Krita's alpha lock keeps every alpha."
        details: dict[str, Any] = {"eraser": True, "alpha_lock": True}
        return envelope.failure("INVALID_ARGUMENT", message, details=details)
    alpha = brush["color"]["rgba"][3]
    if alpha != 1:
        message = "The colour's alpha must be 1; transparency comes from the brush's opacity."
        details = {"alpha": alpha, "supported": [1]}
        return envelope.failure("INVALID_ARGUMENT", message, details=details)
    smooth = arguments.get("smooth", "none")
    if smooth not in SMOOTHED:
        message = f"smooth {smooth} is not built; the server smooths with catmull_rom."
        details = {"smooth": smooth, "supported": SMOOTHED}
        return envelope.failure("UNSUPPORTED_CAPABILITY", message, details=details)
    if not brush.get("antialias", True):
        message = "Every stroke is antialiased in this release."
        details = {"antialias": False, "supported": [True]}
        return envelope.failure("UNSUPPORTED_CAPABILITY", message, details=details)
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


def _unbounded(brush: dict[str, Any]) -> str | None:
    # JSON's NaN and Infinity pass the schema's bounds.
    for field in BRUSH_NUMBERS:
        if not _finite(brush[field]):
            return f"brush.{field}"
    return None if all(_finite(value) for value in brush["color"]) else "brush.color"


def _path(points: list[dict[str, Any]], smooth: str) -> dict[str, Any] | None:
    # None when a point, or a control point smoothing made from large ones, is not finite.
    if not all(_finite(point["x"]) and _finite(point["y"]) for point in points):
        return None
    path = strokes.path(points, smooth)
    numbers = [*path["start"], *(value for segment in path["segments"] for value in segment)]
    return path if all(_finite(value) for value in numbers) else None


def _finite(value: float) -> bool:
    # A JSON integer too large for a float overflows rather than answering.
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def paint_receipt(outcome: Outcome) -> CallToolResult:
    def data(result: dict[str, Any]) -> dict[str, Any]:
        return {**changes.without_document(result), "input_applied": "flat"}

    def text(result: dict[str, Any]) -> str:
        checked = result["verification"]
        return (
            f"Painted {result['accepted_points']} point(s) on layer {result['layer_id']} of "
            f"{result['document_id']}; {checked['changed_px']} px changed, verified over "
            f"{checked['mode']}."
        )

    receipt = from_outcome(outcome, data, text, changes.document_of)
    if isinstance(outcome, Failed):
        image = changes.diff_image(outcome.error["details"])
        if image is not None:
            receipt.content.append(image)
    return receipt
