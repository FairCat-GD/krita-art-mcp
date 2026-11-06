import difflib
import logging
import math
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import brushes, dynamics, log, mutation, shapes, verification
from .documents import COLOR_MODEL, DEPTH, SRGB_PROFILE
from .errors import BridgeError, exact, integer, number
from .history import LABELS, in_front
from .inspection import TYPES
from .jobs import Call, Handler
from .opening import LAYER_ID
from .port import DocumentsPort, ResourcesPort
from .protection import MASK, refuse_held_line
from .rects import union
from .registry import Handle, Registry
from .resources import BLEND_MODES
from .resources import fingerprint as preset_fingerprint

STROKE_FIELDS = {
    "document_id",
    "layer_id",
    "verify",
    "accepted_points",
    "brush",
    "path",
    "dynamics",
}
BRUSH_FIELDS = {
    "preset_id",
    "preset_sha256",
    "size_px",
    "opacity",
    "flow",
    "color",
    "mask",
    "eraser",
    "blend_mode",
    "alpha_lock",
    "rotation_deg",
}
PATH_FIELDS = {"start", "segments"}
MAX_POINTS = 4096
MIN_SIZE_PX, MAX_SIZE_PX = 1, 1000
# How far past the canvas an on-curve point may lie, as a fraction of the brush's size.
OVERHANG_OF_SIZE = 0.5
SHA256 = re.compile(r"^[0-9a-f]{64}$")
NEAREST = 5
PAINTABLE = "PAINT"
UNKNOWN_TIP = "unknown"
# The fields Krita must take exactly; the others it may adjust, and they are reported as held.
TAKEN = ("blend_mode", "eraser", "alpha_lock")
FILL_FIELDS = {"document_id", "layer_id", "verify", "shape", "fill"}
FILL_STYLE_FIELDS = {"color", "mask", "opacity", "blend_mode", "alpha_lock"}
# Mask paint in Krita's terms: white reveals and black hides, each by the opacity, on a mask's
# one byte a pixel (measured on 5.3.4.1).
MASK_COLOURS = {"reveal": [1.0, 1.0, 1.0, 1.0], "hide": [0.0, 0.0, 0.0, 1.0]}
# A transparency mask's colour model and depth, as Node.colorModel() and colorDepth() read them.
MASK_SPACE = ("A", "U8")
# A fill paints the same pixels under every preset, but a wash preset leaves colour under alpha
# 0 up to 3 px past the shape (K49), so every fill activates this build-up stock preset first.
FILL_PRESET = "c)_Pencil-3_Large_4B.kpp"
FILL_PRESET_NAME = "c) Pencil-3 Large 4B"
# Past the shape's box: its antialiased edge touches the pixels the box's outward rounding holds,
# and the measured fill touched nothing past them.
FILL_MARGIN_PX = 2


def handlers(
    registry: Registry, port: DocumentsPort, resources: ResourcesPort, data: Path
) -> dict[str, Handler]:
    # For each preset, the digests Krita's loading of it gave after the bridge activated it, by
    # the digest it was checked against: Krita fills in a tip's defaults on its first activation
    # in a session, which moves the listed digest without anyone changing the preset.
    activated: dict[tuple[str, str], str] = {}

    def remember(preset_id: str, listed: str | None, resource: Any) -> None:
        # The stored preset's, not the view's: a dirty digest here could vouch for a later
        # change the owner saves.
        _, loaded = preset_fingerprint(resources.preset_xml(resource))
        if listed is not None and loaded is not None and loaded != listed:
            activated[(preset_id, loaded)] = listed

    # Presets a taper could not put back, by the digest each had before it: Krita still holds
    # the edit, so no stroke or fill paints with one until it reads as before.
    held: dict[str, str] = {}

    def unheld(preset_id: str, xml: str) -> None:
        if preset_id not in held:
            return
        _, found = preset_fingerprint(xml)
        if found == held[preset_id]:
            del held[preset_id]
            return
        details = {"preset_id": preset_id, "reason": "preset_held"}
        message = (
            "A taper could not put this preset back in Krita; reload it in Krita's brush "
            "editor, then list it again."
        )
        raise BridgeError("RESOURCE_HASH_MISMATCH", message, False, details)

    def painted(
        handle: Handle,
        call: Call,
        op: str,
        noun: str,
        info: dict[str, Any],
        tree: dict[str, Any],
        target: dict[str, Any],
        effects: dict[str, Any],
        mode: str,
        loose: dict[str, int],
        loose_ring: dict[str, int],
        effective: dict[str, Any],
        paint: Callable[[], None],
    ) -> tuple[mutation.Mutation, mutation.Applied]:
        # One verified paint call, from R on: loose is R and loose_ring R' as Krita's unclipped
        # bounds see them.
        document, layer_id, size = handle.document, target["id"], info["size_px"]
        region, ring = _clip(loose, size), _clip(loose_ring, size)
        scope = region if mode == verification.REGION else _whole(size)
        old_bounds = target["bounds_px"]
        target_rect = (
            ring
            if mode == verification.REGION
            else _clip(union([_box(old_bounds), loose_ring]) or loose_ring, size)
        )
        protected = _protected_paint_layers(tree, handle.protected)
        hashed = {
            node_id: met
            for node_id, bounds in protected.items()
            if (met := _meet(bounds, scope)) is not None
        }
        channels = 1 if target["type"] == MASK else 4
        reads = mutation.verifiable(
            handle, info, effects, mode, scope, layer_id, target_rect, channels, hashed
        )
        near = reads.allowed if scope == region else verification.allowed_rows(handle, size, region)
        if near is not None and b"\xff" not in near:
            details = {"layer_id": layer_id, "region_px": region}
            message = f"The {noun}'s reach lies wholly outside the allowed mask."
            raise BridgeError("OUTSIDE_ALLOWED_MASK", message, False, details)
        frame = mutation.Mutation(
            port, handle, call, op, (LABELS[op],), reads, data, {"layer_id": layer_id}, noun
        )
        frame.read()
        held = {key: value for key, value in effective.items() if key != "preset_xml"}
        if port.brush(document) != held:
            message = f"Krita's brush changed after it was set, so the {noun} was not painted."
            raise BridgeError("INTERNAL_ERROR", message, False, {"layer_id": layer_id})

        def change(steps: mutation.Steps) -> None:
            paint()

        def judge(applied: mutation.Applied) -> tuple[Any, Any]:
            assert applied.verdict is not None
            final = port.tree(document)
            problem = _verdict(
                final,
                layer_id,
                protected,
                applied.verdict,
                applied.diff,
                mode,
                region,
                loose_ring,
                old_bounds,
                noun,
            )
            if problem is not None:
                raise problem
            diff = applied.diff
            new = _box(_node_bounds(final, layer_id))
            # Krita's bounds run past the canvas, where paint changes nothing anyone can see.
            shown = None if new is None else _box(_clip(new, size))
            if mode == verification.FULL and shown and not _inside(shown, target_rect):
                # Full scope does not hold the target to R; what it painted past the read
                # shows in its bounds.
                diff = union([diff, shown])
            return diff, new

        def back() -> bool:
            return bool(_node_bounds(port.tree(document), layer_id) == old_bounds)

        return frame, frame.run(change, judge, back)

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
        target = _target(tree, layer_id, handle.protected, "stroke", asked["mask"] is not None)
        size = info["size_px"]
        _on_canvas(args["path"], size, asked["size_px"])
        preset = _preset(resources, asked["preset_id"])
        unheld(asked["preset_id"], preset["xml"])
        name = preset["name"]
        listed = _listed(preset["xml"], asked["preset_id"], asked["preset_sha256"], activated)
        taper = args["dynamics"]
        # The preset's own dirty flag before the brush is set, which the taper puts back.
        dirty = None if taper is None else _taperable(resources, preset, asked["preset_id"])
        _refuse_cumulative(port)
        effects = port.effects(document, mode == verification.REGION)
        if mode == verification.REGION:
            verification.refuse_reach(tree, effects, layer_id, "this stroke past its reach")
        with in_front(port, document):
            effective = port.set_brush(document, _krita_brush(asked, name), preset["resource"])
            _taken(_krita_brush(asked, name), name, effective)
            remember(asked["preset_id"], listed, preset["resource"])
            _paintable(port, document, layer_id)
            reach = brushes.brush_reach(effective["preset_xml"])
            if mode == verification.REGION and reach["reasons"]:
                _refuse_brush(reach, layer_id)
            tip = reach["tip"] or brushes.IMAGE
            scatter = brushes.MAX_SCATTER if reach["scatter"] is None else reach["scatter"]
            margin = brushes.margin_px(effective["size_px"], tip, scatter)
            loose = _grow(_path_box(args["path"]), margin)
            loose_ring = _grow(loose, max(brushes.MIN_MARGIN_PX, effective["size_px"]))

            def draw() -> None:
                port.paint_path(document, layer_id, args["path"])

            tapered = None
            if taper is not None:
                draw, tapered = _tapered(
                    port, resources, document, args, preset, effective, dirty, held, draw
                )
            frame, applied = painted(
                handle,
                call,
                "paint.stroke",
                "stroke",
                info,
                tree,
                target,
                effects,
                mode,
                loose,
                loose_ring,
                effective,
                draw,
            )
            return {
                "document_id": handle.document_id,
                "layer_id": layer_id,
                "stroke_id": call.operation_id,
                "accepted_points": args["accepted_points"],
                "effective_brush": {
                    **_effective(asked, listed, effective, reach, tip, scatter, margin),
                    "dynamics": tapered,
                },
                **_receipt(frame, applied),
            }

    def fill(handle: Handle, args: dict[str, Any], call: Call) -> dict[str, Any]:
        document, layer_id, mode, shape = (
            handle.document,
            args["layer_id"],
            args["verify"],
            args["shape"],
        )
        info = port.describe(document)
        _check_space(info)
        tree = port.tree(document)
        style = args["fill"]
        target = _target(tree, layer_id, handle.protected, "fill", style["mask"] is not None)
        size = info["size_px"]
        drawn = None if shape["kind"] == "selection" else shapes.on_canvas(shape, size)
        preset = resources.preset(FILL_PRESET)
        if preset is None:
            details: dict[str, Any] = {"preset_id": FILL_PRESET}
            message = (
                f"A fill paints with Krita's stock preset {FILL_PRESET_NAME}, which Krita "
                "does not list."
            )
            raise BridgeError("UNSUPPORTED_CAPABILITY", message, False, details)
        unheld(FILL_PRESET, preset["xml"])
        _, found = preset_fingerprint(preset["xml"])
        listed = None if found is None else activated.get((FILL_PRESET, found), found)
        _refuse_cumulative(port)
        effects = port.effects(document, mode == verification.REGION)
        if mode == verification.REGION:
            verification.refuse_reach(tree, effects, layer_id, "this fill past its reach")
        with in_front(port, document):
            if drawn is None:
                # Read here, where it is filled: a selection's bounds can run past the canvas.
                shape = {"kind": "rect", "rect": _selected(port, document, size)}
                drawn = shapes.box(shape)
            krita_fill = {**style, "color": _paint_colour(style)}
            effective = port.set_fill(document, krita_fill, preset["resource"])
            _filled_as_asked(krita_fill, preset["name"], effective)
            remember(FILL_PRESET, listed, preset["resource"])
            reasons = brushes.unplain(effective["preset_xml"])
            if reasons:
                details = {"preset_id": FILL_PRESET, "reasons": reasons}
                message = (
                    f"The stock preset {FILL_PRESET_NAME} no longer fills straight into the "
                    "layer (build-up, no masking brush); put it back as Krita ships it."
                )
                raise BridgeError("UNSUPPORTED_CAPABILITY", message, False, details)
            _paintable(port, document, layer_id)
            loose = _grow(drawn, FILL_MARGIN_PX)
            loose_ring = _grow(loose, brushes.MIN_MARGIN_PX)
            frame, applied = painted(
                handle,
                call,
                "paint.fill",
                "fill",
                info,
                tree,
                target,
                effects,
                mode,
                loose,
                loose_ring,
                effective,
                lambda: port.fill_path(document, layer_id, shape),
            )
            return {
                "document_id": handle.document_id,
                "layer_id": layer_id,
                "fill_id": call.operation_id,
                "shape": args["shape"]["kind"],
                "shape_bounds_px": shapes.aligned(drawn),
                "effective_fill": {
                    "preset_id": FILL_PRESET,
                    **_paint_reported(style, effective),
                    "opacity": effective["opacity"],
                    "blend_mode": effective["blend_mode"],
                    "alpha_lock": effective["alpha_lock"],
                    "antialias": True,
                },
                **_receipt(frame, applied),
            }

    guarded_stroke = registry.guarded(stroke)
    guarded_fill = registry.guarded(fill)

    def paint_stroke(args: dict[str, Any], call: Call) -> dict[str, Any]:
        _check_args(args)
        return guarded_stroke(args, call)

    def paint_fill(args: dict[str, Any], call: Call) -> dict[str, Any]:
        _check_fill(args)
        return guarded_fill(args, call)

    return {"paint.stroke": paint_stroke, "paint.fill": paint_fill}


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
    if not integer(points) or not 1 <= points <= MAX_POINTS:
        raise BridgeError("INVALID_ARGUMENT", f"accepted_points is 1 to {MAX_POINTS}.")
    _check_brush(args["brush"])
    _check_path(args["path"])
    dynamics.check(args["dynamics"], args["brush"], args["path"])


def _check_fill(args: Any) -> None:
    if not isinstance(args, dict):
        raise BridgeError("INVALID_ARGUMENT", "The op's arguments are an object.")
    exact(args, FILL_FIELDS)
    if not isinstance(args["document_id"], str):
        raise BridgeError("INVALID_ARGUMENT", "document_id is a document id.")
    if not isinstance(args["layer_id"], str) or not LAYER_ID.match(args["layer_id"]):
        raise BridgeError("INVALID_ARGUMENT", "layer_id is a layer id.")
    if args["verify"] not in verification.MODES:
        raise BridgeError("INVALID_ARGUMENT", "verify is region or full.")
    style = args["fill"]
    if not isinstance(style, dict):
        raise BridgeError("INVALID_ARGUMENT", "fill is an object.")
    exact(style, FILL_STYLE_FIELDS)
    _check_paint(style, "fill", "opacity sets transparency")
    if not number(style["opacity"]) or not 0 <= style["opacity"] <= 1:
        raise BridgeError("INVALID_ARGUMENT", "fill.opacity is 0 to 1.")
    if style["blend_mode"] not in {mode for mode, _ in BLEND_MODES}:
        raise BridgeError("INVALID_ARGUMENT", "fill.blend_mode is malformed.")
    if not isinstance(style["alpha_lock"], bool):
        raise BridgeError("INVALID_ARGUMENT", "fill.alpha_lock is true or false.")
    _check_mask_paint(style, "fill")
    shapes.check(args["shape"])


def _check_brush(brush: Any) -> None:
    if not isinstance(brush, dict):
        raise BridgeError("INVALID_ARGUMENT", "brush is an object.")
    exact(brush, BRUSH_FIELDS)
    if not isinstance(brush["preset_id"], str) or not brush["preset_id"]:
        _malformed("preset_id")
    sha = brush["preset_sha256"]
    if sha is not None and (not isinstance(sha, str) or not SHA256.match(sha)):
        _malformed("preset_sha256")
    if not number(brush["size_px"]) or not MIN_SIZE_PX <= brush["size_px"] <= MAX_SIZE_PX:
        _malformed("size_px")
    for key in ("opacity", "flow"):
        if not number(brush[key]) or not 0 <= brush[key] <= 1:
            _malformed(key)
    _check_paint(brush, "brush", "opacity and flow set transparency")
    for key in ("eraser", "alpha_lock"):
        if not isinstance(brush[key], bool):
            _malformed(key)
    if brush["eraser"] and brush["alpha_lock"]:
        # K37: Krita ignores the alpha lock while erasing.
        message = "eraser and alpha_lock cannot be combined: Krita erases through the lock."
        raise BridgeError("INVALID_ARGUMENT", message)
    if brush["blend_mode"] not in {mode for mode, _ in BLEND_MODES}:
        _malformed("blend_mode")
    if not number(brush["rotation_deg"]):
        _malformed("rotation_deg")
    _check_mask_paint(brush, "brush")


def _check_paint(style: dict[str, Any], field: str, transparency: str) -> None:
    # Exactly one of a colour and mask paint.
    color, mask = style["color"], style["mask"]
    if (color is None) == (mask is None):
        message = f"{field} takes a color for a paint layer or a mask for a transparency mask."
        raise BridgeError("INVALID_ARGUMENT", message, False, {"field": f"{field}.color"})
    if mask is not None:
        if mask not in MASK_COLOURS:
            raise BridgeError("INVALID_ARGUMENT", f"{field}.mask is reveal or hide.")
        return
    if not _colour(color):
        raise BridgeError("INVALID_ARGUMENT", f"{field}.color is malformed.")
    if color[3] != 1:
        message = f"{field}.color's alpha must be 1; {transparency}."
        raise BridgeError("INVALID_ARGUMENT", message)


def _check_mask_paint(style: dict[str, Any], field: str) -> None:
    # Mask paint picks its own colour, so it takes no blend, alpha lock or eraser: an erase with
    # white would hide under a receipt saying reveal.
    if style["mask"] is not None and (
        style["blend_mode"] != "normal" or style["alpha_lock"] or style.get("eraser")
    ):
        message = f"{field}.mask paints in normal blend, without alpha lock or eraser."
        raise BridgeError("INVALID_ARGUMENT", message, False, {"field": f"{field}.mask"})


def _paint_colour(style: dict[str, Any]) -> list[float]:
    return list(MASK_COLOURS[style["mask"]]) if style["mask"] is not None else style["color"]


def _paint_reported(style: dict[str, Any], effective: dict[str, Any]) -> dict[str, Any]:
    if style["mask"] is not None:
        return {"color": None, "mask": style["mask"]}
    return {"color": {"space": "srgb", "rgba": list(effective["color"])}, "mask": None}


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


def _colour(color: Any) -> bool:
    return (
        isinstance(color, list)
        and len(color) == 4
        and all(number(value) and 0 <= value <= 1 for value in color)
    )


def _malformed(key: str) -> None:
    raise BridgeError("INVALID_ARGUMENT", f"brush.{key} is malformed.")


def _malformed_path(message: str) -> None:
    raise BridgeError("INVALID_ARGUMENT", message)


def _numbers(values: Any, lengths: tuple[int, ...]) -> bool:
    return (
        isinstance(values, list)
        and len(values) in lengths
        and all(number(value) for value in values)
    )


# A taper.


def _taperable(resources: ResourcesPort, preset: dict[str, Any], preset_id: str) -> bool:
    # Refused before any change: what the taper's restore could not put back as it was. The
    # preset's dirty flag, which the restore keeps.
    engine, _ = preset_fingerprint(preset["xml"])
    details: dict[str, Any] = {"preset_id": preset_id, "field": "dynamics"}
    if engine != brushes.ENGINE:
        details["engine"] = engine
        message = (
            "dynamics drives the pixel brush engine's Distance sensor; this preset is another."
        )
        raise BridgeError("UNSUPPORTED_CAPABILITY", message, False, details)
    setting = resources.dirty_presets_setting()
    if setting is not None:
        details["reason"] = "dirty_presets_setting"
        message = (
            "Krita's 'save tweaks to presets temporarily' setting was changed from its default, "
            "which dynamics has not been measured under."
        )
        raise BridgeError("UNSUPPORTED_CAPABILITY", message, False, details)
    dirty = resources.preset_dirty(preset_id)
    if dirty is None:
        details["reason"] = "preset_state_unread"
        message = (
            "Krita does not say whether this preset has unsaved changes, so it could not be "
            "put back as it was."
        )
        raise BridgeError("UNSUPPORTED_CAPABILITY", message, False, details)
    return dirty


def _tapered(
    port: DocumentsPort,
    resources: ResourcesPort,
    document: Any,
    args: dict[str, Any],
    preset: dict[str, Any],
    effective: dict[str, Any],
    dirty: bool | None,
    held: dict[str, str],
    draw: Callable[[], None],
) -> tuple[Callable[[], None], dict[str, Any]]:
    # The paint, with the preset edited for it and put back after: by its own XML, then from
    # Krita's storage when it had no unsaved change before (K51). After the marker, so a
    # preset left edited makes the outcome uncertain.
    taper, path, preset_id = args["dynamics"], args["path"], args["brush"]["preset_id"]
    before = effective["preset_xml"]
    _, stored = preset_fingerprint(preset["xml"])
    _, set_digest = preset_fingerprint(before)
    reload = dirty is False
    wanted = stored if reload else set_digest
    text, tapered = dynamics.edited(before, taper, path)
    brush = {key: value for key, value in effective.items() if key != "preset_xml"}

    def put_back() -> bool:
        # Never raises, so the stroke's own outcome is never hidden.
        try:
            now = port.restore_preset(document, before, reload)
            kept = resources.preset_xml(preset["resource"])
            return (
                preset_fingerprint(now)[1] == wanted
                and preset_fingerprint(kept)[1] == wanted
                and resources.preset_dirty(preset_id) == dirty
            )
        except Exception:
            logging.getLogger(log.NAME).exception("the taper's preset was not put back")
            return False

    def lost() -> BridgeError:
        held[preset_id] = stored or ""
        details = {"preset_id": preset_id, "preset_restored": False, "outcome": "uncertain"}
        message = (
            "Krita's brush preset could not be put back after the taper, so the stroke was "
            "undone; reload the preset in Krita's brush editor."
        )
        return BridgeError("INTERNAL_ERROR", message, False, details)

    def paint() -> None:
        try:
            now = port.edit_preset(document, text)
            wrong = dynamics.took(now, taper, path)
            if wrong:
                details = {"preset_id": preset_id, "fields": [f"dynamics.{key}" for key in wrong]}
                message = "Krita did not take the taper as asked, so the stroke was not painted."
                raise BridgeError("INTERNAL_ERROR", message, False, details)
            if port.brush(document) != brush:
                details = {"preset_id": preset_id}
                message = (
                    "Krita's brush moved when the taper was set, so the stroke was not painted."
                )
                raise BridgeError("INTERNAL_ERROR", message, False, details)
            draw()
        except Exception as raised:
            if not put_back():
                logging.getLogger(log.NAME).error("the taper failed: %r", raised)
                raise lost() from raised
            raise
        except BaseException:
            if not put_back():
                lost()
            raise
        if not put_back():
            raise lost()

    return paint, tapered


# Refusals before any change.


def _refuse_cumulative(port: DocumentsPort) -> None:
    if port.cumulative_undo():
        details: dict[str, Any] = {"reason": "cumulative_undo"}
        message = (
            "Krita's cumulative undo merges strokes into one undo step, so a stroke could "
            "not be undone alone; turn it off in Krita's settings."
        )
        raise BridgeError("UNSUPPORTED_CAPABILITY", message, False, details)


def _paintable(port: DocumentsPort, document: Any, layer_id: str) -> None:
    ability = port.paint_ability(document, layer_id)
    if ability != PAINTABLE:
        details = {"layer_id": layer_id, "paint_ability": ability}
        message = "Krita says this layer cannot be painted now."
        raise BridgeError("LAYER_NOT_PAINTABLE", message, False, details)


def _selected(port: DocumentsPort, document: Any, size: list[int]) -> dict[str, int]:
    # The rect a selection fill paints, clipped: Krita's bounds can run past the canvas.
    bounds = port.selection_bounds(document)
    shown = None if bounds is None else _box(_clip(bounds, size))
    if shown is None:
        message = "There is no selection on the canvas to fill; set one first."
        raise BridgeError("INVALID_ARGUMENT", message, False, {"field": "shape"})
    return shown


def _check_space(info: dict[str, Any]) -> None:
    if (info["color_model"], info["depth"], info["profile_id"]) != (
        COLOR_MODEL,
        DEPTH,
        SRGB_PROFILE,
    ):
        details = {key: info[key] for key in ("color_model", "depth", "profile_id")}
        message = "Phase 1 paints RGBA / U8 / sRGB documents only."
        raise BridgeError("COLOR_PROFILE_MISMATCH", message, False, details)


def _target(
    tree: dict[str, Any], layer_id: str, protected: set[str], noun: str, masking: bool
) -> dict[str, Any]:
    node: dict[str, Any] | None = next(
        (node for node in tree["nodes"] if node["id"] == layer_id), None
    )
    details: dict[str, Any] = {"layer_id": layer_id}
    if node is None:
        raise BridgeError("LAYER_NOT_FOUND", "No layer has that id.", False, details)
    if layer_id in protected:
        raise BridgeError("LOCKED_TARGET", "The layer is protected.", False, details)
    kind = TYPES.get(node["type"], node["type"])
    if (node["type"] == MASK) != masking:
        details["layer_type"] = kind
        message = (
            f"A transparency mask takes a {noun} with mask reveal or hide, never a colour."
            if node["type"] == MASK
            else f"mask paints transparency masks; this layer is a {kind}."
        )
        raise BridgeError("INVALID_ARGUMENT", message, False, details)
    if masking:
        refuse_held_line(tree, layer_id, protected, "mask")
        if (node["color_model"], node["depth"]) != MASK_SPACE:
            details.update({key: node[key] for key in ("color_model", "depth", "profile_id")})
            message = "This mask is not Krita's one-byte coverage."
            raise BridgeError("COLOR_PROFILE_MISMATCH", message, False, details)
        # A mask is confined by the global selection alone; a local selection mask on its
        # layer does not confine it (measured).
        return node
    if node["type"] != "paintlayer":
        details["layer_type"] = kind
        message = f"Only paint layers take {noun}s; this layer is a {kind}."
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
        # K10: a local selection mask confines paint in place of the global selection, and
        # libkis does not say which mask is active.
        details["mask_ids"] = masks
        message = f"The layer has a local selection mask, which would confine the {noun} instead."
        raise BridgeError("LAYER_HAS_LOCAL_SELECTION", message, False, details)
    return node


def _on_canvas(path: dict[str, Any], size: list[int], brush_px: float) -> None:
    # Only on-curve points: a curve's control points may lie anywhere.
    half = brush_px * OVERHANG_OF_SIZE
    points = [path["start"]] + [segment[-2:] for segment in path["segments"]]
    for index, (x, y) in enumerate(points):
        if not (-half <= x <= size[0] + half and -half <= y <= size[1] + half):
            details = {"point_index": index, "point": [x, y], "canvas_px": size}
            message = "A point of the path lies off the canvas by more than half the brush."
            raise BridgeError("INVALID_ARGUMENT", message, False, details)


def _preset(resources: ResourcesPort, preset_id: str) -> dict[str, Any]:
    preset = resources.preset(preset_id)
    if preset is not None:
        return preset
    files = [entry["file"] for entry in resources.presets()]
    nearest = difflib.get_close_matches(preset_id, files, NEAREST, 0.0)
    details = {"preset_id": preset_id, "nearest": nearest}
    message = "No brush preset has that id; resource.list names them."
    raise BridgeError("INVALID_ARGUMENT", message, False, details)


def _listed(
    xml: str,
    preset_id: str,
    wanted: str | None,
    activated: dict[tuple[str, str], str],
) -> str:
    # The digest resource.list gave for the preset before the bridge's own activation of it
    # moved it, if it did.
    _, found = preset_fingerprint(xml)
    if found is None:
        details: dict[str, Any] = {"preset_id": preset_id}
        message = "Krita cannot describe this preset, so its stroke could not be reported."
        raise BridgeError("INVALID_ARGUMENT", message, False, details)
    digest = activated.get((preset_id, found), found)
    if wanted is not None and wanted not in (digest, found):
        details = {"preset_id": preset_id, "expected": wanted, "found": digest}
        message = "The preset changed since its hash was taken; list it again."
        raise BridgeError("RESOURCE_HASH_MISMATCH", message, False, details)
    return digest


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
    keys = ("size_px", "opacity", "flow", "eraser", "blend_mode", "alpha_lock")
    return {
        "preset": name,
        **{key: asked[key] for key in keys},
        "color": _paint_colour(asked),
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


def _filled_as_asked(asked: dict[str, Any], name: str, effective: dict[str, Any]) -> None:
    refused = [key for key in ("blend_mode", "alpha_lock") if effective[key] != asked[key]]
    if effective["eraser"]:
        refused.append("eraser")
    if effective["preset"] != name:
        refused.insert(0, "preset")
    if refused:
        details = {"fields": refused}
        message = "Krita did not take the fill as asked, so nothing was painted."
        raise BridgeError("INTERNAL_ERROR", message, False, details)


def _receipt(frame: mutation.Mutation, applied: mutation.Applied) -> dict[str, Any]:
    diff, new = applied.checked
    return {
        "changed_bounds_px": diff,
        "layer_bounds_px": new,
        "protected_pixels_changed": 0,
        "undo_label": frame.labels[0],
        "undo_steps": len(frame.labels),
        "history_sealed": applied.steps.sealed,
        "verification": frame.files(applied),
    }


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
        **_paint_reported(asked, effective),
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
    mode: str,
    region: dict[str, int],
    loose_ring: dict[str, int],
    old_bounds: dict[str, int],
    noun: str,
) -> BridgeError | None:
    # region is R clipped to the canvas, and loose_ring the guard ring R' as Krita's unclipped
    # bounds see it.
    bounds = {node["id"]: node["bounds_px"] for node in tree["nodes"]}
    moved = [node_id for node_id, old in protected.items() if bounds.get(node_id) != old]
    changed = sorted(set(verdict.protected_changed) | set(moved))
    new = _box(bounds.get(layer_id))
    allowed_bounds = union([_box(old_bounds), loose_ring]) or loose_ring
    # R bounds the check only in region scope; full scope reads every composite byte.
    outside = mode == verification.REGION and (
        (diff is not None and not _inside(diff, region))
        or (new is not None and not _inside(new, allowed_bounds))
    )
    if not (verdict.leaked or changed or outside):
        return None
    details: dict[str, Any] = {"protected_layer_ids": changed, "target_outside_reach": outside}
    if outside:
        message = (
            f"The {noun} reached past the region it was verified over, so it was undone; "
            'verify "full" checks the whole canvas.'
        )
    else:
        message = (
            f"The {noun} changed what protection forbids (a protected layer, the composite "
            "outside the allowed mask, or its alpha under preserve_composite_alpha)."
        )
    return BridgeError("PROTECTED_REGION_CHANGED", message, False, details)


def _node_bounds(tree: dict[str, Any], layer_id: str) -> dict[str, int] | None:
    node = next((node for node in tree["nodes"] if node["id"] == layer_id), None)
    return None if node is None else dict(node["bounds_px"])


def _protected_paint_layers(tree: dict[str, Any], protected: set[str]) -> dict[str, dict[str, int]]:
    return {
        node["id"]: node["bounds_px"]
        for node in tree["nodes"]
        if node["id"] in protected and node["type"] == "paintlayer"
    }


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


def _inside(rect: dict[str, int], outer: dict[str, int]) -> bool:
    if _box(rect) is None:
        return True
    return (
        outer["x"] <= rect["x"]
        and outer["y"] <= rect["y"]
        and rect["x"] + rect["width"] <= outer["x"] + outer["width"]
        and rect["y"] + rect["height"] <= outer["y"] + outer["height"]
    )
