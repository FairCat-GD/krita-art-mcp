import itertools
import math
from collections.abc import Callable
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
# A taper's sensor length is a whole number of pixels, and its knots sit at least this far apart
# along the stroke; the plugin holds both.
MIN_DYNAMICS_PX = 1.0
MIN_KNOT_GAP = 0.001


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
            "color": _rgba(brush.get("color")),
            "mask": brush.get("mask"),
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
    refused = _dynamics_length(arguments, path)
    if refused is not None:
        return refused
    op_args["path"] = path
    taper = arguments.get("dynamics")
    op_args["dynamics"] = (
        None if taper is None else {"size": taper.get("size"), "opacity": taper.get("opacity")}
    )
    return op_args


def _refusal(arguments: dict[str, Any]) -> CallToolResult | None:
    # Refused before the journal: no op could paint these.
    refused = _brush_rules(arguments) or _dynamics_rules(arguments)
    if refused is not None:
        return refused
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


def _brush_rules(arguments: dict[str, Any]) -> CallToolResult | None:
    # The plugin holds the same rules.
    return _paint_rules(arguments["brush"], "brush", "the brush's opacity")


def _dynamics_rules(arguments: dict[str, Any]) -> CallToolResult | None:
    # The plugin holds the same rules.
    taper = arguments.get("dynamics")
    if taper is None:
        return None
    for key in ("size", "opacity"):
        knots = taper.get(key)
        if knots is None:
            continue
        at = [knot["at"] for knot in knots]
        if at[0] != 0 or at[-1] != 1:
            message = f"dynamics.{key} starts at 0 and ends at 1."
            return envelope.failure(
                "INVALID_ARGUMENT", message, details={"field": f"dynamics.{key}"}
            )
        if any(later - earlier < MIN_KNOT_GAP for earlier, later in itertools.pairwise(at)):
            message = (
                f"dynamics.{key}'s at values rise by at least {MIN_KNOT_GAP:g} from knot to knot."
            )
            return envelope.failure(
                "INVALID_ARGUMENT", message, details={"field": f"dynamics.{key}"}
            )
    brush = arguments["brush"]
    if brush.get("preset_sha256") is None:
        message = "dynamics edits the preset for one stroke, so it needs brush.preset_sha256."
        details = {"field": "brush.preset_sha256"}
        return envelope.failure("INVALID_ARGUMENT", message, details=details)
    if brush.get("mask") is not None:
        message = "dynamics paints colour on a paint layer, never mask paint."
        return envelope.failure("INVALID_ARGUMENT", message, details={"field": "dynamics"})
    return None


def _dynamics_length(arguments: dict[str, Any], path: dict[str, Any]) -> CallToolResult | None:
    # The plugin measures the painted path the same way.
    if arguments.get("dynamics") is None or strokes.arc_length(path) >= MIN_DYNAMICS_PX:
        return None
    message = f"dynamics needs a stroke at least {MIN_DYNAMICS_PX:g} px long."
    return envelope.failure("INVALID_ARGUMENT", message, details={"field": "dynamics"})


def _paint_rules(style: dict[str, Any], field: str, transparency: str) -> CallToolResult | None:
    # A colour for a paint layer or mask paint for a transparency mask; the schema refuses both.
    color = style.get("color")
    if color is None and style.get("mask") is None:
        message = f"{field} takes a color for a paint layer, or a mask for a transparency mask."
        return envelope.failure("INVALID_ARGUMENT", message, details={"field": f"{field}.color"})
    if color is not None and color["rgba"][3] != 1:
        alpha = color["rgba"][3]
        message = f"The colour's alpha must be 1; transparency comes from {transparency}."
        details: dict[str, Any] = {"alpha": alpha, "supported": [1]}
        return envelope.failure("INVALID_ARGUMENT", message, details=details)
    return None


def _rgba(color: dict[str, Any] | None) -> list[float] | None:
    return None if color is None else list(color["rgba"])


def _path(points: list[dict[str, Any]], smooth: str) -> dict[str, Any] | None:
    # None when smoothing overflows; a caller past the server's own check can send any number.
    try:
        path = strokes.path(points, smooth)
    except OverflowError:
        return None
    numbers = [*path["start"], *(value for segment in path["segments"] for value in segment)]
    return path if all(finite(value) for value in numbers) else None


def paint_receipt(outcome: Outcome) -> CallToolResult:
    def data(result: dict[str, Any]) -> dict[str, Any]:
        return {**changes.without_document(result), "input_applied": "flat"}

    def text(result: dict[str, Any]) -> str:
        what = f"Painted {result['accepted_points']} point(s)"
        return _painted_line(result, what, "stroke")

    return _painted_receipt(outcome, data, text)


def paint_fill(call: ToolCall, arguments: dict[str, Any]) -> CallToolResult:
    op_args = fill_op(arguments)
    if isinstance(op_args, CallToolResult):
        return op_args
    guard = arguments["guard"]

    def send(before_send: BeforeSend) -> Outcome:
        outcome = call.bridge.call(
            "paint.fill", op_args, request_id=guard["request_id"], before_send=before_send
        )
        return changes.resolve_update(call.places, outcome)

    return journaled(call, "krita_paint_fill", arguments, guard["request_id"], send, fill_receipt)


def fill_op(arguments: dict[str, Any]) -> dict[str, Any] | CallToolResult:
    # The bridge op's arguments for a fill, or the refusal; the probe sends them itself too.
    refused = _fill_rules(arguments)
    if refused is not None:
        return refused
    shape = _fill_shape(arguments["shape"])
    if shape is None:
        message = "points are so large that the closed curve's control points are not finite."
        return envelope.failure("INVALID_ARGUMENT", message, details={"field": "shape"})
    return {
        "document_id": arguments["guard"]["document_id"],
        "layer_id": arguments["layer_id"],
        "verify": arguments.get("verify", "region"),
        "shape": shape,
        "fill": {
            "color": _rgba(arguments.get("color")),
            "mask": arguments.get("mask"),
            "opacity": arguments["opacity"],
            "blend_mode": arguments.get("blend_mode", "normal"),
            "alpha_lock": arguments.get("alpha_lock", False),
        },
    }


def _fill_rules(arguments: dict[str, Any]) -> CallToolResult | None:
    # Refused before the journal; the plugin holds the same rules.
    refused = _paint_rules(arguments, "fill", "the fill's opacity")
    if refused is not None:
        return refused
    shape = arguments["shape"]
    if shape["type"] in ("polygon", "path") and strokes.collinear(shape["points"]):
        message = "The shape encloses no area: its points lie on one line."
        return envelope.failure("INVALID_ARGUMENT", message, details={"field": "shape"})
    return None


def _fill_shape(shape: dict[str, Any]) -> dict[str, Any] | None:
    # The bridge's shape; None when a closed curve's control points overflow.
    kind = shape["type"]
    if kind == "selection":
        return {"kind": "selection"}
    if kind in ("rect", "ellipse"):
        return {"kind": kind, "rect": dict(shape["rect"])}
    if kind == "polygon":
        return {"kind": "polygon", "points": [list(point) for point in shape["points"]]}
    path = strokes.closed_catmull_rom([(x, y) for x, y in shape["points"]])
    numbers = [*path["start"], *(value for segment in path["segments"] for value in segment)]
    return {"kind": "path", **path} if all(finite(value) for value in numbers) else None


SHAPE_NAMES = {
    "selection": "the selection",
    "rect": "a rect",
    "ellipse": "an ellipse",
    "polygon": "a polygon",
    "path": "a closed path",
}


def fill_receipt(outcome: Outcome) -> CallToolResult:
    def text(result: dict[str, Any]) -> str:
        return _painted_line(result, f"Filled {SHAPE_NAMES[result['shape']]}", "fill")

    return _painted_receipt(outcome, changes.without_document, text)


def _painted_line(result: dict[str, Any], what: str, noun: str) -> str:
    checked = result["verification"]
    line = (
        f"{what} on layer {result['layer_id']} of {result['document_id']}; "
        f"{checked['changed_px']} px changed, verified over {checked['mode']}"
    )
    if result["history_sealed"]:
        # Its undo would change no pixel, so nothing could confirm it.
        line += f"; the layer did not change, so history stops at this {noun}"
    return line + "."


def _painted_receipt(
    outcome: Outcome,
    data: Callable[[dict[str, Any]], dict[str, Any]],
    text: Callable[[dict[str, Any]], str],
) -> CallToolResult:
    receipt = from_outcome(outcome, data, text, changes.document_of)
    if isinstance(outcome, Failed):
        image = changes.diff_image(outcome.error["details"])
        if image is not None:
            receipt.content.append(image)
    return receipt
