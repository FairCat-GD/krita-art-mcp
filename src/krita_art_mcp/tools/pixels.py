import base64
import datetime
import hashlib
import json
import logging
from dataclasses import replace
from pathlib import Path
from typing import Any

from mcp.types import CallToolResult, ImageContent

from krita_art_mcp import colour, envelope, imaging, transfer
from krita_art_mcp.bridge_client import Done, Failed, Outcome
from krita_art_mcp.errors import error_body
from krita_art_mcp.imaging import Render
from krita_art_mcp.paths import Places
from krita_art_mcp.tools.dispatch import ToolCall, from_outcome
from krita_art_mcp.tools.documents import frame_refusal
from krita_art_mcp.tools.observe import LIMITS

# Codex shows the image at full resolution instead of downscaling it (C2).
IMAGE_META = {"codex/imageDetail": "original"}
CAPTURE_DATA = (
    "image",
    "inline",
    "target",
    "layer_id",
    "source_rect",
    "output_size_px",
    "scale",
    "source_to_image",
    "filter",
    "background",
    "greyscale",
    "profile_id",
    "fresh",
)
SAMPLE_DATA = ("target", "layer_id", "profile_id", "radius_px", "samples")
RENDER_FIELDS = {"scale", "filter", "background", "greyscale", "max_px"}

log = logging.getLogger(__name__)


def today() -> datetime.date:
    # The journal's calendar, so a day's captures and journal lines share a date.
    return datetime.datetime.now(datetime.UTC).date()


def capture(call: ToolCall, arguments: dict[str, Any]) -> CallToolResult:
    refused = frame_refusal(arguments["source"]["frame"]) or _capture_rules(arguments)
    if refused is not None:
        return refused
    resampled = arguments["scale"] != 1
    coloured = arguments["target"] != "selection"
    how = {
        "scale": arguments["scale"],
        "filter": arguments["filter"],
        "background": arguments.get("background", "checker") if resampled and coloured else None,
        "greyscale": arguments.get("greyscale", False),
        "max_px": arguments.get("max_px", imaging.DEFAULT_MAX_PX),
    }
    op_args = {
        "document_id": arguments["source"]["document_id"],
        "frame": 0,
        "target": arguments["target"],
        "layer_id": arguments["layer_id"],
        "rect": arguments["rect"],
        "render": how,
    }
    return capture_receipt(resolve_capture(call.places, call.bridge.call("capture.read", op_args)))


def _capture_rules(arguments: dict[str, Any]) -> CallToolResult | None:
    # Each depends on the arguments alone, so nothing is sent to Krita to be refused.
    given = [field for field in ("background", "greyscale") if field in arguments]
    if given and arguments["scale"] == 1:
        message = (
            "scale 1 returns the native pixels; background and greyscale apply when resampling."
        )
        return envelope.failure("INVALID_ARGUMENT", message, details={"fields": given})
    if given and arguments["target"] == "selection":
        message = "A selection is captured as its own mask; it takes no background or greyscale."
        return envelope.failure("INVALID_ARGUMENT", message, details={"fields": given})
    rect = arguments["rect"]
    area, limit = rect["width"] * rect["height"], LIMITS["capture_source_pixels"]
    if area > limit:
        message = f"The rect covers {area} px, over capture_source_pixels ({limit}); capture tiles."
        details = {"source_pixels": area, "capture_source_pixels": limit}
        return envelope.failure("INVALID_ARGUMENT", message, details=details)
    max_px = arguments.get("max_px", imaging.DEFAULT_MAX_PX)
    try:
        imaging.output_size(rect["width"], rect["height"], arguments["scale"], max_px)
    except imaging.GeometryError as problem:
        return envelope.failure("INVALID_ARGUMENT", str(problem), details={"max_px": max_px})
    return None


def resolve_capture(places: Places, outcome: Outcome) -> Outcome:
    # The crop becomes PNG files before the receipt, wherever the outcome arrives; never raises.
    if not isinstance(outcome, Done):
        return outcome
    try:
        return _capture_files(places, outcome)
    except Exception:
        log.exception("the capture %s was not made into an image", outcome.operation_id)
        return _failed(outcome, error_body("INTERNAL_ERROR", "The capture could not be made."))


def _capture_files(places: Places, outcome: Done) -> Outcome:
    result = outcome.result
    operation_id = _operation_id(outcome)
    how = _render(result["render"])
    rect = result["rect"]
    size = imaging.output_size(rect["width"], rect["height"], how.scale, how.max_px)
    found = imaging.find(places.captures_dir, operation_id, ".png")
    if found is None:
        made = _make_capture(places, outcome, how, rect, size)
        if isinstance(made, Failed):
            return made
        found = made
    full = found.read_bytes()
    small = found.parent / f"{operation_id}.preview.png"
    if small.is_file():
        shown, shown_size, preview = small.read_bytes(), imaging.size_of(small), True
    elif len(full) <= imaging.INLINE_BYTES:
        shown, shown_size, preview = full, size, False
    else:
        message = "The capture's preview is missing; capture again."
        return _failed(outcome, error_body("INTERNAL_ERROR", message, retryable=True))
    path = str(found)
    data = {
        "image": {
            "uri": path,
            "path": path,
            "mime_type": "image/png",
            "sha256": hashlib.sha256(full).hexdigest(),
            "size_bytes": len(full),
            "retention_days": imaging.RETENTION_DAYS,
        },
        "inline": {
            "preview": preview,
            "output_size_px": list(shown_size),
            "source_to_image": imaging.transform(rect, shown_size),
            "filter": imaging.effective(rect, shown_size, how),
        },
        "target": result["target"],
        "layer_id": result["layer_id"],
        "source_rect": rect,
        "output_size_px": list(size),
        "scale": how.scale,
        "source_to_image": imaging.transform(rect, size),
        "filter": imaging.effective(rect, size, how),
        "background": how.background,
        "greyscale": how.greyscale,
        "profile_id": result["profile_id"],
        "fresh": True,
    }
    encoded = base64.b64encode(shown).decode("ascii")
    resolved = {"document_id": result["document_id"], **data, "inline_png": encoded}
    return replace(outcome, result=resolved)


def _make_capture(
    places: Places, outcome: Done, how: Render, rect: dict[str, int], size: tuple[int, int]
) -> Path | Failed:
    result = outcome.result
    operation_id = _operation_id(outcome)
    spec = result["pixels"]
    if how.greyscale and result["profile_id"] not in colour.SRGB_PROFILES:
        _discard(places, spec)
        details = {
            "profile_id": result["profile_id"],
            "srgb_profiles": sorted(colour.SRGB_PROFILES),
        }
        message = "Greyscale is CIE L*, which needs sRGB bytes; this profile is not sRGB."
        return _failed(outcome, error_body("COLOR_PROFILE_MISMATCH", message, details=details))
    try:
        pixels = transfer.take(places.transfer_dir, spec)
    except transfer.TransferError:
        # Another server sharing this data folder may have just made it.
        again = imaging.find(places.captures_dir, operation_id, ".png")
        if again is not None:
            return again
        message = "The capture's pixels were already taken; capture again."
        return _failed(outcome, error_body("INTERNAL_ERROR", message, retryable=True))
    image, _ = imaging.render(pixels, size, how)
    full = imaging.encode(image)
    folder = imaging.folder_for(places.captures_dir, today())
    target = folder / f"{operation_id}.png"
    try:
        # The preview first: a full image on disk means its preview, if any, is there too.
        if len(full) > imaging.INLINE_BYTES:
            small, _, _ = imaging.preview(pixels, rect, size, how)
            imaging.write(folder / f"{operation_id}.preview.png", small)
        imaging.write(target, full)
    except OSError as problem:
        message = f"The capture could not be written: {problem}"
        return _failed(outcome, error_body("IO_ERROR", message, retryable=True))
    _discard(places, spec)
    imaging.sweep(places.captures_dir, today())
    return target


def capture_receipt(outcome: Outcome) -> CallToolResult:
    def data(result: dict[str, Any]) -> dict[str, Any]:
        return {key: result[key] for key in CAPTURE_DATA}

    def text(result: dict[str, Any]) -> str:
        width, height = result["output_size_px"]
        line = (
            f"Captured {_target(result)} of {result['document_id']}, {width} x {height} px: "
            f"{result['image']['path']}"
        )
        if result["inline"]["preview"]:
            shown_width, shown_height = result["inline"]["output_size_px"]
            line += f" (shown as a {shown_width} x {shown_height} preview)"
        return line + "."

    receipt = from_outcome(outcome, data, text, lambda result: result["document_id"])
    if isinstance(outcome, Done):
        image = ImageContent.model_validate(
            {
                "type": "image",
                "data": outcome.result["inline_png"],
                "mimeType": "image/png",
                "_meta": dict(IMAGE_META),
            }
        )
        receipt.content.append(image)
    return receipt


def sample(call: ToolCall, arguments: dict[str, Any]) -> CallToolResult:
    refused = frame_refusal(arguments["source"]["frame"])
    if refused is not None:
        return refused
    op_args = {
        "document_id": arguments["source"]["document_id"],
        "frame": 0,
        "target": arguments["target"],
        "layer_id": arguments["layer_id"],
        "points": arguments["points"],
        "radius": arguments.get("radius", 0),
    }
    return sample_receipt(resolve_sample(call.places, call.bridge.call("sample.read", op_args)))


def resolve_sample(places: Places, outcome: Outcome) -> Outcome:
    # The squares become numbers before the receipt, and are kept so a receipt can be rebuilt.
    if not isinstance(outcome, Done):
        return outcome
    try:
        return _sample_files(places, outcome)
    except Exception:
        log.exception("the sample %s was not computed", outcome.operation_id)
        return _failed(outcome, error_body("INTERNAL_ERROR", "The samples could not be computed."))


def _sample_files(places: Places, outcome: Done) -> Outcome:
    operation_id = _operation_id(outcome)
    found = imaging.find(places.captures_dir, operation_id, ".json")
    if found is None:
        made = _make_samples(places, outcome)
        if isinstance(made, Failed):
            return made
        found = made
    data = json.loads(found.read_text(encoding="utf-8"))
    return replace(outcome, result={"document_id": outcome.result["document_id"], **data})


def _make_samples(places: Places, outcome: Done) -> Path | Failed:
    result = outcome.result
    operation_id = _operation_id(outcome)
    spec = result["pixels"]
    try:
        pixels = transfer.take(places.transfer_dir, spec)
    except transfer.TransferError:
        again = imaging.find(places.captures_dir, operation_id, ".json")
        if again is not None:
            return again
        message = "The samples' pixels were already taken; sample again."
        return _failed(outcome, error_body("INTERNAL_ERROR", message, retryable=True))
    # Every point's square, one after another in a single row.
    row = pixels.reshape(-1, 4)
    srgb = result["profile_id"] in colour.SRGB_PROFILES
    samples, offset = [], 0
    for point, square in zip(result["points"], result["squares"], strict=True):
        count = square["width"] * square["height"]
        block = row[offset : offset + count].reshape(square["height"], square["width"], 4)
        offset += count
        origin = (square["x"], square["y"])
        disc = colour.disc(block, origin, (point[0], point[1]), result["radius"], srgb)
        samples.append({"point_px": point, **disc})
    if offset != len(row):
        raise ValueError("the squares do not cover the transfer file")
    data = {
        "target": result["target"],
        "layer_id": result["layer_id"],
        "profile_id": result["profile_id"],
        "radius_px": colour.number(result["radius"]),
        "samples": samples,
    }
    target = imaging.folder_for(places.captures_dir, today()) / f"{operation_id}.json"
    try:
        imaging.write(target, json.dumps(data, separators=(",", ":")).encode("utf-8"))
    except OSError as problem:
        message = f"The samples could not be written: {problem}"
        return _failed(outcome, error_body("IO_ERROR", message, retryable=True))
    _discard(places, spec)
    imaging.sweep(places.captures_dir, today())
    return target


def sample_receipt(outcome: Outcome) -> CallToolResult:
    def data(result: dict[str, Any]) -> dict[str, Any]:
        return {key: result[key] for key in SAMPLE_DATA}

    def text(result: dict[str, Any]) -> str:
        count = len(result["samples"])
        return (
            f"Sampled {count} point{'' if count == 1 else 's'} of {_target(result)} of "
            f"{result['document_id']}."
        )

    return from_outcome(outcome, data, text, lambda result: result["document_id"])


def _target(result: dict[str, Any]) -> str:
    return (
        f"layer {result['layer_id']}" if result["target"] == "layer" else f"the {result['target']}"
    )


def _operation_id(outcome: Done) -> str:
    # It names files, so only the shape the server mints is accepted.
    operation_id = outcome.operation_id or ""
    if not imaging.OPERATION_ID.match(operation_id):
        raise ValueError(f"{operation_id!r} is not an operation id")
    return operation_id


def _render(echo: Any) -> Render:
    # The server's own parameters, echoed by the plugin; checked before anything is allocated.
    if (
        not isinstance(echo, dict)
        or set(echo) != RENDER_FIELDS
        or echo["filter"] not in imaging.FILTERS
        or not isinstance(echo["greyscale"], bool)
        or not isinstance(echo["max_px"], int)
        or not isinstance(echo["scale"], int | float)
    ):
        raise ValueError("the plugin echoed malformed render parameters")
    return Render(
        echo["scale"], echo["filter"], echo["background"], echo["greyscale"], echo["max_px"]
    )


def _discard(places: Places, spec: Any) -> None:
    try:
        transfer.discard(places.transfer_dir, spec)
    except (transfer.TransferError, OSError):
        log.exception("a transfer file was not removed")


def _failed(outcome: Done, error: dict[str, Any]) -> Failed:
    return Failed(
        error,
        outcome.operation_id,
        submitted=True,
        op=outcome.op,
        request_id=outcome.request_id,
        session_id=outcome.session_id,
    )
