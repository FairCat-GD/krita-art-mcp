import difflib
import hashlib
import logging
import math
import re
from pathlib import Path
from typing import Any

from . import brushes, log, verification
from .documents import COLOR_MODEL, DEPTH, SRGB_PROFILE
from .errors import BridgeError, exact
from .history import DONE, LABELS, UNDO, in_front, move
from .inspection import TYPES
from .jobs import Call, Handler
from .ledger import Fingerprint, Step, fingerprint
from .opening import LAYER_ID
from .port import DocumentsPort, ResourcesPort
from .registry import Handle, Registry
from .resources import BLEND_MODES
from .resources import fingerprint as preset_fingerprint

STROKE_FIELDS = {"document_id", "layer_id", "verify", "accepted_points", "brush", "path"}
BRUSH_FIELDS = {
    "preset_id",
    "preset_sha256",
    "size_px",
    "opacity",
    "flow",
    "color",
    "eraser",
    "blend_mode",
    "alpha_lock",
    "rotation_deg",
}
PATH_FIELDS = {"start", "segments"}
MAX_POINTS = 4096
MIN_SIZE_PX, MAX_SIZE_PX = 1, 1000
SHA256 = re.compile(r"^[0-9a-f]{64}$")
NEAREST = 5
PAINTABLE = "PAINT"
UNKNOWN_TIP = "unknown"
# The fields Krita must take exactly; the others it may adjust, and they are reported as held.
TAKEN = ("blend_mode", "eraser", "alpha_lock")


def handlers(
    registry: Registry, port: DocumentsPort, resources: ResourcesPort, data: Path
) -> dict[str, Handler]:
    def stroke(handle: Handle, args: dict[str, Any], call: Call) -> dict[str, Any]:
        document, layer_id, mode, asked = (
            handle.document,
            args["layer_id"],
            args["verify"],
            args["brush"],
        )
        info = port.describe(document)
        _check_space(info)
        tree = port.tree(document)
        target = _target(tree, layer_id, handle.protected)
        size = info["size_px"]
        _on_canvas(args["path"], size, asked["size_px"])
        name = _preset(resources, asked["preset_id"])
        listed = _listed(resources, name, asked["preset_id"], asked["preset_sha256"])
        if port.cumulative_undo():
            details: dict[str, Any] = {"reason": "cumulative_undo"}
            message = (
                "Krita's cumulative undo merges strokes into one undo step, so a stroke could "
                "not be undone alone; turn it off in Krita's settings."
            )
            raise BridgeError("UNSUPPORTED_CAPABILITY", message, False, details)
        effects = port.effects(document, mode == verification.REGION)
        if mode == verification.REGION:
            _refuse_reach(verification.reach(tree, effects, layer_id), layer_id)
        with in_front(port, document):
            effective = port.set_brush(document, _krita_brush(asked, name))
            _taken(asked, name, effective)
            ability = port.paint_ability(document, layer_id)
            if ability != PAINTABLE:
                details = {"layer_id": layer_id, "paint_ability": ability}
                message = "Krita says this layer cannot be painted now."
                raise BridgeError("LAYER_NOT_PAINTABLE", message, False, details)
            reach = brushes.brush_reach(effective["preset_xml"])
            if mode == verification.REGION and reach["reasons"]:
                _refuse_brush(reach, layer_id)
            tip = reach["tip"] or brushes.IMAGE
            scatter = brushes.MAX_SCATTER if reach["scatter"] is None else reach["scatter"]
            margin = brushes.margin_px(effective["size_px"], tip, scatter)
            loose = _grow(_path_box(args["path"]), margin)
            loose_ring = _grow(loose, max(brushes.MIN_MARGIN_PX, effective["size_px"]))
            region, ring = _clip(loose, size), _clip(loose_ring, size)
            scope = region if mode == verification.REGION else _whole(size)
            old_bounds = target["bounds_px"]
            target_rect = (
                ring
                if mode == verification.REGION
                else _clip(_union([_box(old_bounds), loose_ring]) or loose_ring, size)
            )
            verification.refuse_unverifiable(info, effects, scope)
            verification.refuse_unverifiable(info, effects, target_rect)
            allowed = verification.allowed_rows(handle, size, scope)
            near = allowed if scope == region else verification.allowed_rows(handle, size, region)
            if near is not None and b"\xff" not in near:
                details = {"layer_id": layer_id, "region_px": region}
                message = "The stroke's reach lies wholly outside the allowed mask."
                raise BridgeError("OUTSIDE_ALLOWED_MASK", message, False, details)
            protected = _protected_paint_layers(tree, handle.protected)
            hashed = {
                node_id: met
                for node_id, bounds in protected.items()
                if (met := _meet(bounds, scope)) is not None
            }
            port.refresh(document)
            before = verification.read(
                port, document, scope, layer_id, list(hashed), {layer_id: target_rect, **hashed}
            )
            if port.brush(document) != effective:
                message = "Krita's brush changed after it was set, so the stroke was not painted."
                raise BridgeError("INTERNAL_ERROR", message, False, {"layer_id": layer_id})
            start = fingerprint(port, document)
            was = handle.before_change()
            try:
                return painted(
                    handle,
                    args,
                    call,
                    Stroke(mode, start, was, before, allowed, region, loose_ring, target_rect),
                    old_bounds,
                    protected,
                    _effective(asked, listed, effective, reach, tip, scatter, margin),
                )
            except BridgeError:
                raise
            except BaseException:
                # Krita may hold a stroke the bridge can neither name nor confirm.
                handle.ledger.seal()
                handle.unsafe = True
                raise

    def painted(
        handle: Handle,
        args: dict[str, Any],
        call: Call,
        stroke: "Stroke",
        old_bounds: dict[str, int],
        protected: dict[str, dict[str, int]],
        effective: dict[str, Any],
    ) -> dict[str, Any]:
        document, layer_id = handle.document, args["layer_id"]
        before = stroke.before
        step: Step | None = None
        after: verification.Reading | None = None
        verdict: verification.Verdict | None = None
        diff: dict[str, int] | None = None
        problem: BridgeError | None = None
        try:
            port.paint_path(document, layer_id, args["path"])
            after = verification.read(
                port,
                document,
                before.rect,
                layer_id,
                list(before.hashes),
                before.rects,
                before.hashes,
            )
            verdict = verification.check(
                before, after, stroke.allowed, handle.preserve_composite_alpha
            )
            _, diff = verification.changes(before.target, after.target, stroke.target_rect)
            if diff is None:
                # No pixel tells this stroke's step from another, so history stops below it.
                handle.ledger.seal()
            else:
                witness = (
                    layer_id,
                    diff,
                    _sha(verification.crop(before.target, stroke.target_rect, diff)),
                    _sha(verification.crop(after.target, stroke.target_rect, diff)),
                )
                region = _union([verdict.changed_bounds_px, diff])
                made = Step(
                    "paint.stroke",
                    call.operation_id,
                    LABELS["paint.stroke"],
                    stroke.start,
                    stroke.start,
                    region,
                    witness,
                )
                handle.ledger.push(made, port.undo_limit())
                step = made
            final = port.tree(document)
            problem = _verdict(final, layer_id, protected, verdict, diff, stroke, old_bounds)
            new = _box(_node_bounds(final, layer_id))
            if stroke.mode == verification.FULL and new and not _inside(new, stroke.target_rect):
                # Full scope does not hold the target to R; what it painted past the read shows
                # in its bounds.
                diff = _union([diff, new])
        except BridgeError as raised:
            problem = raised
        except Exception as raised:
            logging.getLogger(log.NAME).exception("paint.stroke raised mid-stroke")
            details = {"op": "paint.stroke", "raised": type(raised).__name__}
            message = "Krita raised during the stroke; see plugin.log."
            problem = BridgeError("INTERNAL_ERROR", message, False, details)
        if problem is not None:
            kept = None if after is None else after.kept
            # Dropped first, so the re-read never holds two copies of the scope.
            after = None
            roll_back(handle, args, call, stroke, step, old_bounds, kept, problem, verdict)
        assert after is not None and verdict is not None
        return {
            "document_id": handle.document_id,
            "layer_id": layer_id,
            "stroke_id": call.operation_id,
            "accepted_points": args["accepted_points"],
            "effective_brush": effective,
            "changed_bounds_px": diff,
            "protected_pixels_changed": 0,
            "undo_label": LABELS["paint.stroke"],
            "undo_steps": 1,
            "verification": verification.files(data, args["verify"], before, after, verdict, False),
        }

    def roll_back(
        handle: Handle,
        args: dict[str, Any],
        call: Call,
        stroke: "Stroke",
        step: Step | None,
        old_bounds: dict[str, int],
        kept: tuple[str, Any] | None,
        problem: BridgeError,
        verdict: verification.Verdict | None,
    ) -> None:
        # Invariant 5: undone, then confirmed by the scope, the target and its bounds, or the
        # document is unsafe.
        layer_id = args["layer_id"]
        rolled_back, confirmed, counted = restore(handle, call, stroke, step, old_bounds, kept)
        found = problem.body["details"]
        details = {
            **found,
            "document_id": handle.document_id,
            "layer_id": layer_id,
            "rolled_back": rolled_back,
            "rollback_verified": confirmed,
            "protected_layer_ids": found.get("protected_layer_ids", []),
            "protected_pixels_changed": counted,
            "target_outside_reach": found.get("target_outside_reach", False),
        }
        if verdict is not None:
            details["verification"] = verification.files(
                data, args["verify"], stroke.before, None, verdict, True
            )
        if confirmed:
            handle.dirty = stroke.was
            # Never retryable: a retry under this request_id would paint again.
            raise BridgeError(problem.body["code"], problem.body["message"], False, details)
        handle.unsafe = True
        details["cause"] = problem.body["code"]
        message = "The stroke could not be undone and confirmed; the document is unsafe. Reopen it."
        raise BridgeError("ROLLBACK_FAILED", message, False, details)

    def restore(
        handle: Handle,
        call: Call,
        stroke: "Stroke",
        step: Step | None,
        old_bounds: dict[str, int],
        kept: tuple[str, Any] | None,
    ) -> tuple[bool, bool, int]:
        # Whether an undo ran, whether the document was confirmed as it was, and how many pixels
        # of the first changed protected layer the stroke had changed.
        document, before = handle.document, stroke.before
        layer_id = before.target_id or ""
        try:
            undone, back = False, False
            if step is not None:
                outcome, _, _ = move(port, handle, step, UNDO, step.after)
                if outcome != DONE:
                    return False, False, 0
                handle.ledger.rolled_back()
                undone = True
            else:
                # Krita may hold a step the ledger does not: history stops below it.
                handle.ledger.seal()
                port.refresh(document)
                again = verification.again(port, document, before)
                back = _back(port, document, before, again, layer_id, old_bounds)
                if not back:
                    if not _undo_unnamed(handle, call, stroke, again):
                        return False, False, 0
                    undone = True
                del again
            if undone:
                port.refresh(document)
                again = verification.again(port, document, before)
                back = _back(port, document, before, again, layer_id, old_bounds)
                del again
            counted = 0
            if kept is not None:
                kept_id, pixels = kept
                rect = before.rects.get(kept_id, before.rect)
                [now] = port.layer_rects(document, kept_id, [rect])
                counted, _ = verification.changes(pixels, memoryview(now).cast("B"), rect)
            return undone, back, counted
        except Exception:
            logging.getLogger(log.NAME).exception("paint.stroke's rollback raised")
            return False, False, 0

    def _undo_unnamed(
        handle: Handle, call: Call, stroke: "Stroke", again: verification.Reading
    ) -> bool:
        # A stroke that raised before the ledger held it is undone only when the top step is a
        # stroke whose pixels are the ones this job saw change.
        before = stroke.before
        _, diff = verification.changes(before.target, again.target, stroke.target_rect)
        if diff is None:
            return False
        witness = (
            before.target_id or "",
            diff,
            _sha(verification.crop(before.target, stroke.target_rect, diff)),
            _sha(verification.crop(again.target, stroke.target_rect, diff)),
        )
        unnamed = Step(
            "paint.stroke",
            call.operation_id,
            LABELS["paint.stroke"],
            stroke.start,
            stroke.start,
            None,
            witness,
        )
        outcome, _, _ = move(port, handle, unnamed, UNDO)
        return outcome == DONE

    guarded = registry.guarded(stroke)

    def paint_stroke(args: dict[str, Any], call: Call) -> dict[str, Any]:
        _check_args(args)
        return guarded(args, call)

    return {"paint.stroke": paint_stroke}


class Stroke:
    # What the job knew just before it painted.
    def __init__(
        self,
        mode: str,
        start: Fingerprint,
        was: bool,
        before: verification.Reading,
        allowed: bytes | None,
        region: dict[str, int],
        loose_ring: dict[str, int],
        target_rect: dict[str, int],
    ) -> None:
        self.mode = mode
        self.start = start
        self.was = was
        self.before = before
        self.allowed = allowed
        # R, clipped to the canvas, and the guard ring R' as Krita's unclipped bounds see it.
        self.region = region
        self.loose_ring = loose_ring
        self.target_rect = target_rect


# Arguments.


def _check_args(args: Any) -> None:
    if not isinstance(args, dict):
        raise BridgeError("INVALID_ARGUMENT", "The op's arguments are an object.")
    exact(args, STROKE_FIELDS)
    if not isinstance(args["document_id"], str):
        raise BridgeError("INVALID_ARGUMENT", "document_id is a document id.")
    if not isinstance(args["layer_id"], str) or not LAYER_ID.match(args["layer_id"]):
        raise BridgeError("INVALID_ARGUMENT", "layer_id is a layer id.")
    if args["verify"] not in verification.MODES:
        raise BridgeError("INVALID_ARGUMENT", "verify is region or full.")
    points = args["accepted_points"]
    if not _integer(points) or not 1 <= points <= MAX_POINTS:
        raise BridgeError("INVALID_ARGUMENT", f"accepted_points is 1 to {MAX_POINTS}.")
    _check_brush(args["brush"])
    _check_path(args["path"])


def _check_brush(brush: Any) -> None:
    if not isinstance(brush, dict):
        raise BridgeError("INVALID_ARGUMENT", "brush is an object.")
    exact(brush, BRUSH_FIELDS)
    if not isinstance(brush["preset_id"], str) or not brush["preset_id"]:
        _malformed("preset_id")
    sha = brush["preset_sha256"]
    if sha is not None and (not isinstance(sha, str) or not SHA256.match(sha)):
        _malformed("preset_sha256")
    if not _number(brush["size_px"]) or not MIN_SIZE_PX <= brush["size_px"] <= MAX_SIZE_PX:
        _malformed("size_px")
    for key in ("opacity", "flow"):
        if not _number(brush[key]) or not 0 <= brush[key] <= 1:
            _malformed(key)
    color = brush["color"]
    if (
        not isinstance(color, list)
        or len(color) != 4
        or not all(_number(value) and 0 <= value <= 1 for value in color)
    ):
        _malformed("color")
    if color[3] != 1:
        message = "brush.color's alpha must be 1; opacity and flow set transparency."
        raise BridgeError("INVALID_ARGUMENT", message)
    for key in ("eraser", "alpha_lock"):
        if not isinstance(brush[key], bool):
            _malformed(key)
    if brush["eraser"] and brush["alpha_lock"]:
        # K37: Krita ignores the alpha lock while erasing.
        message = "eraser and alpha_lock cannot be combined: Krita erases through the lock."
        raise BridgeError("INVALID_ARGUMENT", message)
    if brush["blend_mode"] not in {mode for mode, _ in BLEND_MODES}:
        _malformed("blend_mode")
    if not _number(brush["rotation_deg"]):
        _malformed("rotation_deg")


def _check_path(path: Any) -> None:
    if not isinstance(path, dict) or set(path) != PATH_FIELDS:
        raise BridgeError("INVALID_ARGUMENT", "path is {start, segments}.")
    if not _numbers(path["start"], (2,)):
        _malformed_path("path.start is [x, y].")
    segments = path["segments"]
    if not isinstance(segments, list) or not 1 <= len(segments) <= MAX_POINTS - 1:
        _malformed_path(f"path.segments holds 1 to {MAX_POINTS - 1} segments.")
    if not all(_numbers(segment, (2, 6)) for segment in segments):
        _malformed_path("Each segment is [x, y] or [c1x, c1y, c2x, c2y, x, y].")


def _malformed(key: str) -> None:
    raise BridgeError("INVALID_ARGUMENT", f"brush.{key} is malformed.")


def _malformed_path(message: str) -> None:
    raise BridgeError("INVALID_ARGUMENT", message)


def _integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _numbers(values: Any, lengths: tuple[int, ...]) -> bool:
    return (
        isinstance(values, list)
        and len(values) in lengths
        and all(_number(value) for value in values)
    )


# Refusals before any change.


def _check_space(info: dict[str, Any]) -> None:
    if (info["color_model"], info["depth"], info["profile_id"]) != (
        COLOR_MODEL,
        DEPTH,
        SRGB_PROFILE,
    ):
        details = {key: info[key] for key in ("color_model", "depth", "profile_id")}
        message = "Phase 1 paints RGBA / U8 / sRGB documents only."
        raise BridgeError("COLOR_PROFILE_MISMATCH", message, False, details)


def _target(tree: dict[str, Any], layer_id: str, protected: set[str]) -> dict[str, Any]:
    node: dict[str, Any] | None = next(
        (node for node in tree["nodes"] if node["id"] == layer_id), None
    )
    details: dict[str, Any] = {"layer_id": layer_id}
    if node is None:
        raise BridgeError("LAYER_NOT_FOUND", "No layer has that id.", False, details)
    if layer_id in protected:
        raise BridgeError("LOCKED_TARGET", "The layer is protected.", False, details)
    if node["type"] != "paintlayer":
        kind = TYPES.get(node["type"], node["type"])
        details["layer_type"] = kind
        message = f"Only paint layers take strokes; this layer is a {kind}."
        raise BridgeError("LAYER_NOT_PAINTABLE", message, False, details)
    if (node["color_model"], node["depth"]) != (COLOR_MODEL, DEPTH):
        details.update({key: node[key] for key in ("color_model", "depth", "profile_id")})
        message = "Phase 1 paints RGBA / U8 layers only."
        raise BridgeError("COLOR_PROFILE_MISMATCH", message, False, details)
    masks = sorted(
        child["id"]
        for child in tree["nodes"]
        if child["parent_id"] == layer_id and child["type"] == "selectionmask"
    )
    if masks:
        # K10: a local selection mask confines the stroke in place of the global selection, and
        # libkis does not say which mask is active.
        details["mask_ids"] = masks
        message = "The layer has a local selection mask, which would confine the stroke instead."
        raise BridgeError("LAYER_HAS_LOCAL_SELECTION", message, False, details)
    return node


def _on_canvas(path: dict[str, Any], size: list[int], brush_px: float) -> None:
    # Only on-curve points: a curve's control points may lie anywhere.
    half = brush_px / 2
    points = [path["start"]] + [segment[-2:] for segment in path["segments"]]
    for index, (x, y) in enumerate(points):
        if not (-half <= x <= size[0] + half and -half <= y <= size[1] + half):
            details = {"point_index": index, "point": [x, y], "canvas_px": size}
            message = "A point of the path lies off the canvas by more than half the brush."
            raise BridgeError("INVALID_ARGUMENT", message, False, details)


def _preset(resources: ResourcesPort, preset_id: str) -> str:
    presets = resources.presets()
    for preset in presets:
        if preset["file"] == preset_id:
            return preset["name"]
    files = [preset["file"] for preset in presets]
    nearest = difflib.get_close_matches(preset_id, files, NEAREST, 0.0)
    details = {"preset_id": preset_id, "nearest": nearest}
    message = "No brush preset has that id; resource.list names them."
    raise BridgeError("INVALID_ARGUMENT", message, False, details)


def _listed(resources: ResourcesPort, name: str, preset_id: str, wanted: str | None) -> str:
    # The digest resource.list gives for the preset.
    _, digest = preset_fingerprint(resources.preset_xmls([name]).get(name, ""))
    if digest is None:
        details: dict[str, Any] = {"preset_id": preset_id}
        message = "Krita cannot describe this preset, so its stroke could not be reported."
        raise BridgeError("INVALID_ARGUMENT", message, False, details)
    if wanted is not None and wanted != digest:
        details = {"preset_id": preset_id, "expected": wanted, "found": digest}
        message = "The preset changed since its hash was taken; list it again."
        raise BridgeError("RESOURCE_HASH_MISMATCH", message, False, details)
    return digest


def _refuse_reach(reasons: list[dict[str, str]], layer_id: str) -> None:
    if not reasons:
        return
    details = {"layer_id": layer_id, "verify": verification.REGION, "reasons": reasons}
    message = (
        f"A {reasons[0]['reason']} can carry this stroke past its reach, so region "
        'verification cannot bound it; verify "full" checks the whole canvas.'
    )
    raise BridgeError("UNSUPPORTED_CAPABILITY", message, False, details)


def _refuse_brush(reach: dict[str, Any], layer_id: str) -> None:
    reasons = [{"reason": reason} for reason in reach["reasons"]]
    details = {"layer_id": layer_id, "verify": verification.REGION, "reasons": reasons}
    message = (
        f"The preset's reach cannot be named ({reach['reasons'][0]}), so region verification "
        'cannot bound the stroke; verify "full" checks the whole canvas.'
    )
    raise BridgeError("UNSUPPORTED_CAPABILITY", message, False, details)


# The brush.


def _krita_brush(asked: dict[str, Any], name: str) -> dict[str, Any]:
    keys = ("size_px", "opacity", "flow", "color", "eraser", "blend_mode", "alpha_lock")
    return {
        "preset": name,
        **{key: asked[key] for key in keys},
        "rotation_deg": asked["rotation_deg"],
    }


def _taken(asked: dict[str, Any], name: str, effective: dict[str, Any]) -> None:
    refused = [key for key in TAKEN if effective[key] != asked[key]]
    if effective["preset"] != name:
        refused.insert(0, "preset")
    if refused:
        details = {"fields": refused}
        message = "Krita did not take the brush as asked, so the stroke was not painted."
        raise BridgeError("INTERNAL_ERROR", message, False, details)


def _effective(
    asked: dict[str, Any],
    listed: str,
    effective: dict[str, Any],
    reach: dict[str, Any],
    tip: str,
    scatter: float,
    margin: float,
) -> dict[str, Any]:
    return {
        "preset_id": asked["preset_id"],
        "preset_sha256": listed,
        "engine": reach["engine"],
        "size_px": effective["size_px"],
        "opacity": effective["opacity"],
        "flow": effective["flow"],
        "color": {"space": "srgb", "rgba": list(effective["color"])},
        "eraser": effective["eraser"],
        "blend_mode": effective["blend_mode"],
        "alpha_lock": effective["alpha_lock"],
        "rotation_deg": effective["rotation_deg"],
        "antialias": True,
        "spacing": reach["spacing"],
        "reach": {
            "tip": UNKNOWN_TIP if reach["tip"] is None else tip,
            "scatter": scatter,
            "margin_px": margin,
        },
    }


# After the stroke.


def _verdict(
    tree: dict[str, Any],
    layer_id: str,
    protected: dict[str, dict[str, int]],
    verdict: verification.Verdict,
    diff: dict[str, int] | None,
    stroke: Stroke,
    old_bounds: dict[str, int],
) -> BridgeError | None:
    bounds = {node["id"]: node["bounds_px"] for node in tree["nodes"]}
    moved = [node_id for node_id, old in protected.items() if bounds.get(node_id) != old]
    changed = sorted(set(verdict.protected_changed) | set(moved))
    new = _box(bounds.get(layer_id))
    allowed_bounds = _union([_box(old_bounds), stroke.loose_ring]) or stroke.loose_ring
    # R bounds the check only in region scope; full scope reads every composite byte.
    outside = stroke.mode == verification.REGION and (
        (diff is not None and not _inside(diff, stroke.region))
        or (new is not None and not _inside(new, allowed_bounds))
    )
    if not (verdict.leaked or changed or outside):
        return None
    details: dict[str, Any] = {"protected_layer_ids": changed, "target_outside_reach": outside}
    if outside:
        message = (
            "The stroke reached past the region it was verified over, so it was undone; "
            'verify "full" checks the whole canvas.'
        )
    else:
        message = (
            "The stroke changed what protection forbids (a protected layer, the composite "
            "outside the allowed mask, or its alpha under preserve_composite_alpha)."
        )
    return BridgeError("PROTECTED_REGION_CHANGED", message, False, details)


def _back(
    port: DocumentsPort,
    document: Any,
    before: verification.Reading,
    again: verification.Reading,
    layer_id: str,
    old_bounds: dict[str, int],
) -> bool:
    if not verification.same(before, again):
        return False
    node = next((node for node in port.tree(document)["nodes"] if node["id"] == layer_id), None)
    return node is not None and node["bounds_px"] == old_bounds


def _node_bounds(tree: dict[str, Any], layer_id: str) -> dict[str, int] | None:
    node = next((node for node in tree["nodes"] if node["id"] == layer_id), None)
    return None if node is None else dict(node["bounds_px"])


def _protected_paint_layers(tree: dict[str, Any], protected: set[str]) -> dict[str, dict[str, int]]:
    return {
        node["id"]: node["bounds_px"]
        for node in tree["nodes"]
        if node["id"] in protected and node["type"] == "paintlayer"
    }


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# Rects: {x, y, width, height} in canvas pixels.


def _path_box(path: dict[str, Any]) -> tuple[float, float, float, float]:
    # Every point, control points too: a cubic stays inside its control points' hull.
    xs = [path["start"][0]] + [value for segment in path["segments"] for value in segment[0::2]]
    ys = [path["start"][1]] + [value for segment in path["segments"] for value in segment[1::2]]
    return min(xs), min(ys), max(xs), max(ys)


def _grow(box: Any, by: float) -> dict[str, int]:
    if isinstance(box, dict):
        left, top = box["x"], box["y"]
        right, bottom = left + box["width"], top + box["height"]
    else:
        left, top, right, bottom = box
    left, top = math.floor(left - by), math.floor(top - by)
    right, bottom = math.ceil(right + by), math.ceil(bottom + by)
    return {"x": left, "y": top, "width": right - left, "height": bottom - top}


def _clip(rect: dict[str, int], size: list[int]) -> dict[str, int]:
    left, top = max(0, rect["x"]), max(0, rect["y"])
    right = min(size[0], rect["x"] + rect["width"])
    bottom = min(size[1], rect["y"] + rect["height"])
    if right <= left or bottom <= top:
        return {"x": 0, "y": 0, "width": 0, "height": 0}
    return {"x": left, "y": top, "width": right - left, "height": bottom - top}


def _whole(size: list[int]) -> dict[str, int]:
    return {"x": 0, "y": 0, "width": size[0], "height": size[1]}


def _box(rect: dict[str, int] | None) -> dict[str, int] | None:
    # None for an empty rect.
    if rect is None or rect["width"] <= 0 or rect["height"] <= 0:
        return None
    return rect


def _meet(rect: dict[str, int], scope: dict[str, int]) -> dict[str, int] | None:
    if _box(rect) is None or _box(scope) is None:
        return None
    left, top = max(rect["x"], scope["x"]), max(rect["y"], scope["y"])
    right = min(rect["x"] + rect["width"], scope["x"] + scope["width"])
    bottom = min(rect["y"] + rect["height"], scope["y"] + scope["height"])
    if right <= left or bottom <= top:
        return None
    return {"x": left, "y": top, "width": right - left, "height": bottom - top}


def _union(rects: list[dict[str, int] | None]) -> dict[str, int] | None:
    found = [rect for rect in rects if rect is not None and _box(rect) is not None]
    if not found:
        return None
    left = min(rect["x"] for rect in found)
    top = min(rect["y"] for rect in found)
    right = max(rect["x"] + rect["width"] for rect in found)
    bottom = max(rect["y"] + rect["height"] for rect in found)
    return {"x": left, "y": top, "width": right - left, "height": bottom - top}


def _inside(rect: dict[str, int], outer: dict[str, int]) -> bool:
    if _box(rect) is None:
        return True
    return (
        outer["x"] <= rect["x"]
        and outer["y"] <= rect["y"]
        and rect["x"] + rect["width"] <= outer["x"] + outer["width"]
        and rect["y"] + rect["height"] <= outer["y"] + outer["height"]
    )
