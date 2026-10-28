import base64
import functools
import hashlib
import json
import logging
import math
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
from jsonschema import Draft202012Validator
from mcp.types import CallToolResult, ImageContent

from krita_art_mcp import baselines, colour, envelope, imaging, schemas, sheets, transfer
from krita_art_mcp.bridge_client import Done, Failed, Outcome
from krita_art_mcp.envelope import MAX_RESULT_BYTES
from krita_art_mcp.errors import error_body
from krita_art_mcp.paths import Places
from krita_art_mcp.tools.dispatch import ToolCall, from_outcome
from krita_art_mcp.tools.documents import frame_refusal
from krita_art_mcp.tools.pixels import IMAGE_META, discard, failed, operation_id_of, today

TOOL = "krita_preview_render"
PREVIEW_DATA = ("sheets", "static_only", "source_pixels_changed")
# What one preview reads; the plugin holds an equal copy (MAX_PREVIEW_PIXELS).
MAX_PREVIEW_PIXELS = 2 * 8192 * 8192
# Room in one result for the envelope, the text line and the image wrappers.
RESERVED_BYTES = 64 * 1024
UNITS = ("export_pixels_per_unit", "master_to_export_scale")

log = logging.getLogger(__name__)


def preview_render(call: ToolCall, arguments: dict[str, Any]) -> CallToolResult:
    refused = _rules(arguments)
    if refused is not None:
        return refused
    asked: set[str] = set()
    op_sources = []
    for source in arguments["sources"]:
        baseline_id = source.get("baseline_id")
        # Read from the working copy's file only by the first render that needs it.
        read = False
        if baseline_id is not None and baseline_id not in asked:
            asked.add(baseline_id)
            kept = baselines.path_of(call.places.baselines_dir, baseline_id)
            read = kept is None or not kept.exists()
        op_sources.append(
            {
                "document_id": source["document_id"],
                "frame": 0,
                "target": source["target"],
                "layer_id": source.get("layer_id"),
                "rect": source.get("crop_rect"),
                "baseline_id": baseline_id,
                "read_baseline": read,
                "overlays": list(arguments["overlays"]),
            }
        )
    outcome = call.bridge.call("preview.read", {"sources": op_sources, "render": arguments})
    return preview_receipt(resolve_preview(call.places, outcome))


def _rules(arguments: dict[str, Any]) -> CallToolResult | None:
    # Each depends on the arguments alone, so nothing is sent to Krita to be refused.
    if not _finite(arguments):
        return envelope.failure("INVALID_ARGUMENT", "Every number is finite.")
    sources = arguments["sources"]
    for source in sources:
        refused = frame_refusal(source["frame"])
        if refused is not None:
            return refused
    for field in ("recipes", "tints"):
        counted = Counter(entry["id"] for entry in arguments.get(field, []))
        twice = sorted(name for name, count in counted.items() if count > 1)
        if twice:
            message = f"Each of the {field} has its own id."
            return envelope.failure("INVALID_ARGUMENT", message, details={"ids": twice})
    for index, source in enumerate(sources):
        if "baseline_id" in source and source["target"] != "composite":
            message = "baseline_id pairs the composite with the document as opened; use composite."
            return envelope.failure("INVALID_ARGUMENT", message, details={"source": index})
        missing = [unit for unit in UNITS if unit not in source and unit not in arguments]
        if missing and any("target_pixels_per_unit" in r for r in arguments["recipes"]):
            details = {"source": index, "missing": missing}
            message = (
                f"World-unit recipes need {' and '.join(missing)} for source {index}, given on it "
                "or as the default (master_to_export_scale is 1 when it is at export size)."
            )
            return envelope.failure("INVALID_ARGUMENT", message, details=details)
        if "crop_rect" in source and "anchor_px" in source:
            try:
                sheets.check_anchor(index, source["crop_rect"], source["anchor_px"])
            except sheets.Refused as problem:
                return envelope.failure(problem.code, problem.message, details=problem.details)
    crops = [source["crop_rect"] for source in sources if "crop_rect" in source]
    area = sum(crop["width"] * crop["height"] for crop in crops)
    if area > MAX_PREVIEW_PIXELS:
        details = {"pixels": area, "max_preview_pixels": MAX_PREVIEW_PIXELS}
        message = "The crops cover too many pixels for one preview; render fewer at a time."
        return envelope.failure("INVALID_ARGUMENT", message, details=details)
    return None


def _finite(value: Any) -> bool:
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, dict):
        return all(_finite(item) for item in value.values())
    if isinstance(value, list):
        return all(_finite(item) for item in value)
    return True


def resolve_preview(places: Places, outcome: Outcome) -> Outcome:
    # The sheets become PNG files before the receipt, wherever the outcome arrives; never raises.
    if not isinstance(outcome, Done):
        return outcome
    try:
        return _preview_files(places, outcome)
    except Exception:
        log.exception("the preview %s was not made", outcome.operation_id)
        # No retry can use the pixels, so they go now rather than at the plugin's expiry.
        _discard_all(places, outcome.result)
        return failed(outcome, error_body("INTERNAL_ERROR", "The preview could not be made."))


def _preview_files(places: Places, outcome: Done) -> Outcome:
    operation_id = operation_id_of(outcome)
    found = imaging.find(places.captures_dir, operation_id, ".json")
    if found is None:
        made = _make(places, outcome)
        if isinstance(made, Failed):
            return made
        found = made
    data = json.loads(found.read_text(encoding="utf-8"))
    shown = [
        base64.b64encode(Path(sheet["image"]["path"]).read_bytes()).decode("ascii")
        if sheet["inline"]
        else None
        for sheet in data["sheets"]
    ]
    documents = {column["document_id"] for column in data["sheets"][0]["columns"]}
    one = next(iter(documents)) if len(documents) == 1 else None
    resolved = {"document_id": one, "documents": len(documents), **data, "inline_pngs": shown}
    return replace(outcome, result=resolved)


def _make(places: Places, outcome: Done) -> Path | Failed:
    # The receipt's JSON is written last, so finding it means every sheet is on disk.
    result = outcome.result
    operation_id = operation_id_of(outcome)
    arguments = _echoed(result.get("render"))
    read = result["sources"]
    if not isinstance(read, list) or len(read) != len(arguments["sources"]):
        raise ValueError("the plugin read another number of sources")
    for given, got in zip(arguments["sources"], read, strict=True):
        if given.get("crop_rect", got["rect"]) != got["rect"]:
            raise ValueError("the plugin read another rect")
    try:
        found = sheets.sources_of(arguments, read)
        if arguments.get("greyscale") and any(
            source.profile_id not in colour.SRGB_PROFILES for source in found
        ):
            details = {"srgb_profiles": sorted(colour.SRGB_PROFILES)}
            message = "Greyscale is CIE L*, which needs sRGB bytes; a source is not sRGB."
            raise sheets.Refused("COLOR_PROFILE_MISMATCH", message, details)
        crops, masks = _pixels(places, read)
        made = sheets.render(arguments, found, crops, masks)
    except sheets.Refused as problem:
        _discard_all(places, result)
        error = error_body(problem.code, problem.message, details=problem.details)
        return failed(outcome, error)
    except transfer.TransferError:
        # Another server sharing this data folder may have just made it.
        again = imaging.find(places.captures_dir, operation_id, ".json")
        if again is not None:
            return again
        message = "The preview's pixels were already taken; render again."
        return failed(outcome, error_body("INTERNAL_ERROR", message, retryable=True))
    except _BaselineGone:
        _discard_all(places, result)
        message = "The as_opened baseline could not be kept; render again."
        return failed(outcome, error_body("INTERNAL_ERROR", message, retryable=True))
    folder = imaging.folder_for(places.captures_dir, today())
    try:
        target = _write(folder, operation_id, made)
    except OSError as problem:
        message = f"The preview could not be written: {problem}"
        return failed(outcome, error_body("IO_ERROR", message, retryable=True))
    _discard_all(places, result)
    imaging.sweep(places.captures_dir, today())
    return target


class _BaselineGone(Exception):
    pass


@functools.cache
def _inputs() -> Draft202012Validator:
    return Draft202012Validator(schemas.load(TOOL)["inputSchema"])


def _echoed(echo: Any) -> dict[str, Any]:
    # The server's own arguments, echoed by the plugin; checked before anything is allocated.
    if not isinstance(echo, dict) or not _inputs().is_valid(echo) or not _finite(echo):
        raise ValueError("the plugin echoed malformed preview arguments")
    return echo


def _pixels(
    places: Places, read: list[dict[str, Any]]
) -> tuple[dict[tuple[int, str], transfer.Pixels], dict[int, dict[str, transfer.Pixels]]]:
    crops: dict[tuple[int, str], transfer.Pixels] = {}
    masks: dict[int, dict[str, transfer.Pixels]] = {}
    for index, got in enumerate(read):
        rect = got["rect"]
        crops[(index, sheets.CURRENT)] = transfer.take(places.transfer_dir, got["pixels"])
        masks[index] = {
            name: transfer.take(places.transfer_dir, spec)[..., 0]
            for name, spec in got["overlays"].items()
            if spec is not None
        }
        baseline = got["baseline"]
        if baseline is None:
            continue
        if baseline["pixels"] is not None:
            baselines.adopt(places, baseline["baseline_id"], baseline["pixels"])
        kept = baselines.load(places.baselines_dir, baseline["baseline_id"])
        width, height = got["canvas_px"]
        if kept is None or kept.shape != (height, width, 4):
            raise _BaselineGone
        crop = kept[rect["y"] : rect["y"] + rect["height"], rect["x"] : rect["x"] + rect["width"]]
        crops[(index, sheets.AS_OPENED)] = np.array(crop)
    return crops, masks


def _write(folder: Path, operation_id: str, made: list[sheets.Sheet]) -> Path:
    entries = []
    for number, sheet in enumerate(made):
        name = f"{operation_id}-{number}"
        clean = None
        if sheet.clean is not None:
            clean = _artifact(folder / f"{name}.clean.png", imaging.encode(sheet.clean))
        image = _artifact(folder / f"{name}.png", imaging.encode(sheet.image))
        entries.append({**sheet.data, "image": image, "clean_image": clean, "inline": False})
    data = {"sheets": entries, "static_only": True, "source_pixels_changed": 0}
    # Every sheet that fits goes inline at full size, in recipe order; the rest stay on disk.
    room = (MAX_RESULT_BYTES - RESERVED_BYTES - len(json.dumps(data))) * 3 // 4
    for entry in entries:
        if entry["image"]["size_bytes"] <= room:
            entry["inline"] = True
            room -= entry["image"]["size_bytes"]
    target = folder / f"{operation_id}.json"
    imaging.write(target, json.dumps(data, separators=(",", ":")).encode("utf-8"))
    return target


def _artifact(path: Path, data: bytes) -> dict[str, Any]:
    imaging.write(path, data)
    return {
        "uri": str(path),
        "path": str(path),
        "mime_type": "image/png",
        "sha256": hashlib.sha256(data).hexdigest(),
        "size_bytes": len(data),
        "retention_days": imaging.RETENTION_DAYS,
    }


def _discard_all(places: Places, result: dict[str, Any]) -> None:
    read = result.get("sources")
    for got in read if isinstance(read, list) else []:
        if not isinstance(got, dict):
            continue
        specs = [got.get("pixels"), *(got.get("overlays") or {}).values()]
        baseline = got.get("baseline")
        if isinstance(baseline, dict):
            specs.append(baseline.get("pixels"))
        for spec in specs:
            if spec is not None:
                discard(places, spec)


def preview_receipt(outcome: Outcome) -> CallToolResult:
    def data(result: dict[str, Any]) -> dict[str, Any]:
        return {key: result[key] for key in PREVIEW_DATA}

    def text(result: dict[str, Any]) -> str:
        parts = []
        for sheet in result["sheets"]:
            width, height = sheet["size_px"]
            part = f"{sheet['recipe_id']}, {width} x {height} px: {sheet['image']['path']}"
            if not sheet["inline"]:
                part += " (on disk only, too large to show with the others)"
            parts.append(part)
        count = len(result["sheets"])
        who = result["document_id"] or f"{result['documents']} documents"
        return (
            f"Rendered {count} sheet{'' if count == 1 else 's'} of {who}: " + "; ".join(parts) + "."
        )

    receipt = from_outcome(outcome, data, text, lambda result: result["document_id"])
    if isinstance(outcome, Done):
        for encoded in outcome.result["inline_pngs"]:
            if encoded is not None:
                image = ImageContent.model_validate(
                    {
                        "type": "image",
                        "data": encoded,
                        "mimeType": "image/png",
                        "_meta": dict(IMAGE_META),
                    }
                )
                receipt.content.append(image)
    return receipt
