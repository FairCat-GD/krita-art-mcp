import base64
import hashlib
import io
import logging
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
from mcp.types import CallToolResult, ImageContent
from PIL import Image

from krita_art_mcp import envelope, imaging, masks, roots, transfer, verification
from krita_art_mcp.bridge_client import BeforeSend, Done, Failed, Outcome, Pending
from krita_art_mcp.paths import Places
from krita_art_mcp.tools.dispatch import ToolCall, applied_failure, from_outcome, journaled
from krita_art_mcp.tools.observe import LIMITS
from krita_art_mcp.tools.pixels import IMAGE_META, discard, operation_id_of, today

log = logging.getLogger(__name__)

# Each op that pushes ledger steps, by the tool that sends it.
STEP_TOOLS = {
    "layer.create": "krita_layer_create",
    "layer.update": "krita_layer_update",
    "paint.fill": "krita_paint_fill",
    "paint.stroke": "krita_paint_stroke",
    "selection.set": "krita_selection_set",
}


def layer_create(call: ToolCall, arguments: dict[str, Any]) -> CallToolResult:
    if arguments["type"] == "transparency_mask":
        details = {"type": "transparency_mask", "supported": ["paint", "group"]}
        message = "Transparency masks arrive in Phase 2, with mask_edit."
        return envelope.failure("UNSUPPORTED_CAPABILITY", message, details=details)
    guard = arguments["guard"]
    op_args = {
        "document_id": guard["document_id"],
        **{field: arguments[field] for field in ("parent_id", "above_id", "type", "name")},
    }

    def send(before_send: BeforeSend) -> Outcome:
        return call.bridge.call(
            "layer.create", op_args, request_id=guard["request_id"], before_send=before_send
        )

    return journaled(
        call, "krita_layer_create", arguments, guard["request_id"], send, layer_receipt
    )


def layer_receipt(outcome: Outcome) -> CallToolResult:
    def text(result: dict[str, Any]) -> str:
        return f"Added {result['type']} layer {result['layer_id']} to {result['document_id']}."

    return from_outcome(outcome, without_document, text, document_of)


def layer_update(call: ToolCall, arguments: dict[str, Any]) -> CallToolResult:
    guard = arguments["guard"]
    op_args = {
        "document_id": guard["document_id"],
        "layer_id": arguments["layer_id"],
        "properties": arguments["properties"],
        "verify": arguments.get("verify", "region"),
    }

    def send(before_send: BeforeSend) -> Outcome:
        outcome = call.bridge.call(
            "layer.update", op_args, request_id=guard["request_id"], before_send=before_send
        )
        return resolve_update(call.places, outcome)

    return journaled(
        call, "krita_layer_update", arguments, guard["request_id"], send, update_receipt
    )


def resolve_update(places: Places, outcome: Outcome) -> Outcome:
    # PNGs before the receipt, wherever the outcome arrives; never raises or changes the outcome.
    if isinstance(outcome, Done) and isinstance(outcome.result.get("verification"), dict):
        sent = outcome.result["verification"]
        try:
            made = verification.receipt(places, operation_id_of(outcome), sent, today())
        except Exception:
            log.exception("the change %s was not made into images", outcome.operation_id)
            made = _without_files(places, sent, ("before", "after"))
        return replace(outcome, result={**outcome.result, "verification": made})
    if isinstance(outcome, Failed) and isinstance(
        outcome.error["details"].get("verification"), dict
    ):
        sent = outcome.error["details"]["verification"]
        try:
            made = verification.failure(places, operation_id_of(outcome), sent, today())
        except Exception:
            log.exception("the refusal %s was not made into a diff", outcome.operation_id)
            made = _without_files(places, sent, ("diff",))
        details = {**outcome.error["details"], "verification": made}
        return replace(outcome, error={**outcome.error, "details": details})
    return outcome


def _without_files(places: Places, sent: dict[str, Any], kept: tuple[str, ...]) -> dict[str, Any]:
    for name in ("before", "after", "diff"):
        discard(places, sent.get(name))
    counts = {key: sent.get(key) for key in ("mode", "rect", *verification.COUNTS)}
    return {**counts, **dict.fromkeys(kept)}


def update_receipt(outcome: Outcome) -> CallToolResult:
    def text(result: dict[str, Any]) -> str:
        names = ", ".join(sorted(result["effective_properties"]))
        line = f"Set {names} on layer {result['layer_id']} of {result['document_id']}"
        checked = result["verification"]
        if checked is not None:
            line += f"; {checked['changed_px']} px changed, verified over {checked['mode']}"
        return line + "."

    receipt = from_outcome(outcome, without_document, text, document_of)
    if isinstance(outcome, Failed):
        image = diff_image(outcome.error["details"])
        if image is not None:
            receipt.content.append(image)
    return receipt


def diff_image(details: dict[str, Any]) -> ImageContent | None:
    # The refusal's diff, inline, as the call and krita_operation_get both show it.
    checked = details.get("verification")
    diff = checked.get("diff") if isinstance(checked, dict) else None
    if not isinstance(diff, dict) or not str(diff.get("path", "")).endswith(".diff.png"):
        return None
    path = Path(diff["path"])
    try:
        png = path.read_bytes()
    except OSError:
        return None
    # The artifact still names it; inline it would break the message bound.
    if len(png) > imaging.INLINE_BYTES:
        return None
    return ImageContent.model_validate(
        {
            "type": "image",
            "data": base64.b64encode(png).decode("ascii"),
            "mimeType": "image/png",
            "_meta": dict(IMAGE_META),
        }
    )


def selection_set(call: ToolCall, arguments: dict[str, Any]) -> CallToolResult:
    refused = _clear_rules(arguments)
    if refused is not None:
        return refused
    shape = arguments["shape"]
    guard = arguments["guard"]
    request_id = guard["request_id"]

    def send(before_send: BeforeSend) -> Outcome:
        try:
            sent_shape = _selection_shape(call.places, shape, request_id)
        except masks.MaskError as problem:
            return Failed(problem.body)
        op_args = {
            "document_id": guard["document_id"],
            "combine": arguments["combine"],
            "shape": sent_shape,
            "grow_px": arguments.get("grow_px", 0),
            "shrink_px": arguments.get("shrink_px", 0),
            "feather_px": arguments["feather_px"],
            "invert": arguments["invert"],
        }
        outcome = call.bridge.call(
            "selection.set", op_args, request_id=request_id, before_send=before_send
        )
        _settle_masks(call.places, outcome, request_id)
        return resolve_selection(call.places, outcome)

    return journaled(call, "krita_selection_set", arguments, request_id, send, selection_receipt)


def _clear_rules(arguments: dict[str, Any]) -> CallToolResult | None:
    # The plugin checks this too.
    modified = [field for field in ("grow_px", "shrink_px") if arguments.get(field)]
    if arguments["shape"]["type"] == "none" and (
        arguments["combine"] != "replace"
        or arguments["feather_px"]
        or arguments["invert"]
        or modified
    ):
        message = "Clearing the selection takes combine replace and no modifiers."
        return envelope.failure("INVALID_ARGUMENT", message)
    return None


def _selection_shape(places: Places, shape: dict[str, Any], request_id: str) -> dict[str, Any]:
    limit = LIMITS["capture_source_pixels"]
    kind = shape["type"]
    if kind in ("all", "none"):
        return {"kind": kind}
    if kind == "layer_alpha":
        return {"kind": "layer_alpha", "layer_id": shape["layer_id"]}
    if kind == "rect":
        mask = masks.rect(shape["rect"], limit)
    elif kind == "ellipse":
        mask = masks.ellipse(shape["rect"], limit)
    elif kind == "polygon":
        mask = masks.polygon(shape["points"], limit)
    else:
        mask = masks.from_png(
            shape["mask_uri"], shape["mask_sha256"], _allowed(places), limit, False, "mask_uri"
        )
        mask.origin = (shape["origin_px"][0], shape["origin_px"][1])
    return {"kind": "mask", **_sent(places, mask, request_id)}


def _sent(places: Places, mask: masks.Mask, request_id: str) -> dict[str, Any]:
    spec = transfer.put_mask(places.transfer_dir, mask.pixels, request_id)
    return {"origin_px": list(mask.origin), "mask": spec, "source_path": mask.source}


def _allowed(places: Places) -> list[str]:
    try:
        return roots.allowed(places.config_file, places.harness_dir)
    except roots.ConfigError as problem:
        raise masks.MaskError("INTERNAL_ERROR", str(problem)) from None


def _settle_masks(places: Places, outcome: Outcome, request_id: str) -> None:
    # After a final outcome no op of this request takes its mask any more.
    if not isinstance(outcome, Pending):
        settle_masks(places, request_id)


def settle_masks(places: Places, request_id: str | None) -> None:
    if request_id is None:
        return
    try:
        transfer.discard_masks(places.transfer_dir, request_id)
    except OSError:
        log.exception("the masks of %s were not removed", request_id)


def resolve_selection(places: Places, outcome: Outcome) -> Outcome:
    # The selection becomes a PNG before the receipt, wherever the outcome arrives; never raises.
    if not isinstance(outcome, Done):
        return outcome
    try:
        return _selection_files(places, outcome)
    except Exception:
        log.exception("the selection %s was not made into a mask", outcome.operation_id)
        selection = outcome.result.get("selection") or {}
        discard(places, selection.get("pixels"))
        return applied_failure(outcome, "INTERNAL_ERROR", "The selection's mask was not made.")


def _selection_files(places: Places, outcome: Done) -> Outcome:
    result = outcome.result
    selection = result["selection"]
    data: dict[str, Any] = {
        "selection_id": None,
        "mask": None,
        "bounds_px": None,
        "selected_pixels": 0,
        "undo_steps": result["undo_steps"],
    }
    if selection is not None:
        data.update(
            selection_id=selection["selection_id"],
            bounds_px=selection["bounds_px"],
            selected_pixels=selection["selected_pixels"],
        )
        if selection["pixels"] is not None:
            made = _kept_png(places, outcome, selection["pixels"], "selection's mask")
            if isinstance(made, Failed):
                return made
            if made is not None:
                data["mask"] = verification.artifact(*made)
    return replace(outcome, result={"document_id": result["document_id"], **data})


def _kept_png(
    places: Places, outcome: Done, spec: dict[str, Any], what: str
) -> tuple[Path, bytes] | Failed | None:
    # None when another server took the pixels first (a retry it shared): the change is made.
    try:
        kept = verification.keep(
            places, operation_id_of(outcome), ".png", today(), [spec], verification.image_of
        )
    except OSError as problem:
        # No retry will come for it: the journal holds this answer.
        discard(places, spec)
        return applied_failure(outcome, "IO_ERROR", f"The {what} could not be written: {problem}")
    if kept is not None:
        discard(places, spec)
    return kept


def selection_receipt(outcome: Outcome) -> CallToolResult:
    def text(result: dict[str, Any]) -> str:
        if result["bounds_px"] is None:
            return f"{result['document_id']} has no selection."
        return f"Selected {result['selected_pixels']} px in {result['document_id']}."

    return from_outcome(outcome, without_document, text, document_of)


def protection_set(call: ToolCall, arguments: dict[str, Any]) -> CallToolResult:
    guard = arguments["guard"]
    request_id = guard["request_id"]

    def send(before_send: BeforeSend) -> Outcome:
        try:
            allowed = _allowed_change_mask(
                call.places, arguments["allowed_change_mask"], request_id
            )
        except masks.MaskError as problem:
            return Failed(problem.body)
        op_args = {
            "document_id": guard["document_id"],
            "protected_layer_ids": arguments["protected_layer_ids"],
            "allowed_change_mask": allowed,
            "preserve_composite_alpha": arguments["preserve_composite_alpha"],
            "preserve_canvas": arguments["preserve_canvas"],
        }
        outcome = call.bridge.call(
            "protection.set", op_args, request_id=request_id, before_send=before_send
        )
        _settle_masks(call.places, outcome, request_id)
        return outcome

    return journaled(call, "krita_protection_set", arguments, request_id, send, protection_receipt)


def _allowed_change_mask(
    places: Places, value: dict[str, Any] | None, request_id: str
) -> dict[str, Any] | None:
    limit = LIMITS["capture_source_pixels"]
    if value is None:
        return None
    if "rect" in value:
        mask = masks.rect(value["rect"], limit)
    elif "polygon" in value:
        mask = masks.polygon(value["polygon"], limit, binary=True)
    else:
        mask = masks.from_png(
            value["uri"], value["sha256"], _allowed(places), limit, True, "allowed_change_mask"
        )
    return _sent(places, mask, request_id)


def protection_receipt(outcome: Outcome) -> CallToolResult:
    def text(result: dict[str, Any]) -> str:
        mask = result["allowed_change_mask"]
        allowed = "the whole canvas" if mask is None else f"{mask['allowed_pixels']} px"
        return (
            f"Protected {len(result['protected_layer_ids'])} layer(s) of {result['document_id']}; "
            f"changes allowed in {allowed}."
        )

    return from_outcome(outcome, without_document, text, document_of)


def history_step(call: ToolCall, arguments: dict[str, Any]) -> CallToolResult:
    guard = arguments["guard"]
    op_args = {
        "document_id": guard["document_id"],
        "action": arguments["action"],
        "steps": arguments["steps"],
    }

    def send(before_send: BeforeSend) -> Outcome:
        outcome = call.bridge.call(
            "history.step", op_args, request_id=guard["request_id"], before_send=before_send
        )
        return resolve_history(call.places, outcome)

    return journaled(
        call, "krita_history_step", arguments, guard["request_id"], send, history_receipt
    )


def resolve_history(places: Places, outcome: Outcome) -> Outcome:
    if not isinstance(outcome, Done):
        return outcome
    try:
        return _history_files(places, outcome)
    except Exception:
        log.exception("the history step %s was not captured", outcome.operation_id)
        discard(places, outcome.result.get("pixels"))
        return applied_failure(outcome, "INTERNAL_ERROR", "The step's capture was not made.")


def _history_files(places: Places, outcome: Done) -> Outcome:
    result = outcome.result
    data = {
        "action": result["action"],
        "steps_applied": result["steps_applied"],
        "verified": result["verified"],
        "stopped": result["stopped"],
        "steps": [
            {"tool": STEP_TOOLS.get(step["op"], step["op"]), "operation_id": step["operation_id"]}
            for step in result["steps"]
        ],
        "undo_available": result["undo_available"],
        "redo_available": result["redo_available"],
        "region_px": result["region_px"],
        "content_sha256": None,
        "capture": None,
    }
    if result["pixels"] is not None:
        made = _kept_png(places, outcome, result["pixels"], "step's capture")
        if isinstance(made, Failed):
            return made
        if made is not None:
            path, png = made
            with Image.open(io.BytesIO(png)) as image:
                rgba = np.array(image.convert("RGBA"), dtype=np.uint8).tobytes()
            data["content_sha256"] = hashlib.sha256(rgba).hexdigest()
            data["capture"] = verification.artifact(path, png)
    return replace(outcome, result={"document_id": result["document_id"], **data})


def history_receipt(outcome: Outcome) -> CallToolResult:
    def text(result: dict[str, Any]) -> str:
        done = f"{result['action'].capitalize()} of {result['steps_applied']} step(s)"
        if result["verified"]:
            return f"{done} in {result['document_id']}, verified."
        if result["stopped"] == "document_unsafe":
            return (
                f"{done} in {result['document_id']}; nothing confirmed where the next step left "
                "Krita, so the document is unsafe: reopen it."
            )
        return f"{done} in {result['document_id']}; stopped: {result['stopped']}."

    return from_outcome(outcome, without_document, text, document_of)


def without_document(result: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in result.items() if key != "document_id"}


def document_of(result: dict[str, Any]) -> str | None:
    document_id: str | None = result.get("document_id")
    return document_id
