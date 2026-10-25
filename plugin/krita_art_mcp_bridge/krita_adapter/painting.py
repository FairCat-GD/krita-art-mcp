import logging
from typing import Any

from krita import Krita, ManagedColor, Preset

from ..bridge_core import log
from ..bridge_core.errors import BridgeError
from .qt import QAbstractScrollArea, QMdiArea, QPainterPath, QPointF

# The sRGB profile Phase 1 paints in; the core refuses any other document.
SRGB_PROFILE = "sRGB-elle-V2-srgbtrc.icc"
# Where each of R, G, B, A sits in ManagedColor's components for RGBA / U8 (K18).
CHANNELS = (2, 1, 0, 3)
MIRRORS = ("hmirror_action", "vmirror_action")
PRESET_FIELDS = ("size_px", "opacity", "flow", "blend_mode", "eraser")


def view_of(document: Any) -> Any:
    # The view in front, which the core brought forward; paint calls read its resources (K2).
    windows = Krita.instance().windows()
    view = windows[0].activeView() if windows else None
    if view is None or view.document() != document:
        raise BridgeError("INTERNAL_ERROR", "The document's view is not in front.")
    return view


def set_brush(document: Any, brush: dict[str, Any]) -> dict[str, Any]:
    view = view_of(document)
    preset = Krita.instance().resources("preset").get(brush["preset"])
    if preset is None:
        details = {"preset": brush["preset"]}
        raise BridgeError("INVALID_ARGUMENT", "Krita has no preset by that name.", False, details)
    # K3's order: activating a preset resets the composite op, so the blend follows it.
    view.setCurrentBrushPreset(preset)
    view.setBrushSize(float(brush["size_px"]))
    view.setPaintingOpacity(float(brush["opacity"]))
    view.setPaintingFlow(float(brush["flow"]))
    view.setCurrentBlendingMode(brush["blend_mode"])
    view.setEraserMode(bool(brush["eraser"]))
    view.setGlobalAlphaLock(bool(brush["alpha_lock"]))
    view.setBrushRotation(float(brush["rotation_deg"]))
    view.setForeGroundColor(_colour(brush["color"]))
    return read_brush(document)


def read_brush(document: Any) -> dict[str, Any]:
    view = view_of(document)
    preset = view.currentBrushPreset()
    try:
        xml = "" if preset is None else str(Preset(preset).toXML())
    except Exception:
        xml = ""
    return {**_current(view), "preset_xml": xml}


def _current(view: Any) -> dict[str, Any]:
    preset = view.currentBrushPreset()
    components = list(view.foregroundColor().components())
    return {
        "preset": None if preset is None else str(preset.name()),
        "size_px": float(view.brushSize()),
        "opacity": float(view.paintingOpacity()),
        "flow": float(view.paintingFlow()),
        "color": [float(components[index]) for index in CHANNELS],
        "eraser": bool(view.eraserMode()),
        "blend_mode": str(view.currentBlendingMode()),
        "alpha_lock": bool(view.globalAlphaLock()),
        "rotation_deg": float(view.brushRotation()),
    }


def _colour(rgba: list[float]) -> Any:
    colour = ManagedColor("RGBA", "U8", SRGB_PROFILE)
    components = [0.0] * 4
    for channel, index in enumerate(CHANNELS):
        components[index] = float(rgba[channel])
    colour.setComponents(components)
    return colour


def paint_path(document: Any, node: Any, path: dict[str, Any]) -> None:
    view = view_of(document)
    canvas = view.canvas()
    mirrors = _switch_mirrors_off()
    wrapped = _switch_wrap_off(canvas)
    try:
        node.paintPath(_painter_path(path), "ForegroundColor", "None")
        document.waitForDone()
    finally:
        _restore_mirrors(mirrors)
        _restore_wrap(canvas, wrapped)


def _painter_path(path: dict[str, Any]) -> Any:
    shape = QPainterPath()
    shape.moveTo(QPointF(*path["start"]))
    for segment in path["segments"]:
        if len(segment) == 2:
            shape.lineTo(QPointF(*segment))
        else:
            c1x, c1y, c2x, c2y, x, y = segment
            shape.cubicTo(QPointF(c1x, c1y), QPointF(c2x, c2y), QPointF(x, y))
    return shape


def _switch_mirrors_off() -> dict[str, bool]:
    # Mirror painting is a canvas resource Krita's actions toggle (K2).
    was = {}
    for name in MIRRORS:
        action = Krita.instance().action(name)
        if action is not None and action.isChecked():
            was[name] = True
            action.setChecked(False)
    return was


def _restore_mirrors(was: dict[str, bool]) -> None:
    # Never raises, so a restore cannot hide the stroke's own outcome.
    for name in was:
        try:
            Krita.instance().action(name).setChecked(True)
        except Exception:
            logging.getLogger(log.NAME).exception("mirror painting was not put back")


def _switch_wrap_off(canvas: Any) -> bool:
    # Scripted strokes honour wrap-around mode (K47).
    wrapped = bool(canvas.wrapAroundMode())
    if wrapped:
        canvas.setWrapAroundMode(False)
    return wrapped


def _restore_wrap(canvas: Any, wrapped: bool) -> None:
    if not wrapped:
        return
    try:
        canvas.setWrapAroundMode(True)
    except Exception:
        logging.getLogger(log.NAME).exception("wrap-around mode was not put back")


def cumulative_undo() -> bool:
    text = str(Krita.instance().readSetting("", "useCumulativeUndoRedo", "false"))
    return text.strip().lower() == "true"


def view_state(document: Any) -> dict[str, Any]:
    canvas = view_of(document).canvas()
    bars = _scroll_bars()
    return {
        "zoom": float(canvas.zoomLevel()),
        "rotation_deg": float(canvas.rotation()),
        "pan_px": None if bars is None else [int(bars[0].value()), int(bars[1].value())],
    }


def set_view(document: Any, view: dict[str, Any]) -> dict[str, Any]:
    canvas = view_of(document).canvas()
    if "zoom" in view:
        canvas.setZoomLevel(float(view["zoom"]))
    if "rotation_deg" in view:
        canvas.setRotation(float(view["rotation_deg"]))
    if "pan_px" in view:
        bars = _scroll_bars()
        if bars is None:
            raise BridgeError("INTERNAL_ERROR", "Krita's canvas has no scroll bars to pan.")
        bars[0].setValue(int(view["pan_px"][0]))
        bars[1].setValue(int(view["pan_px"][1]))
    document.waitForDone()
    return view_state(document)


def _scroll_bars() -> tuple[Any, Any] | None:
    # libkis has no pan, so the canvas controller's scroll bars move the view.
    window = Krita.instance().windows()[0].qwindow()
    area = window.findChild(QMdiArea)
    sub = None if area is None else area.activeSubWindow()
    if sub is None:
        return None
    scrolled = sub.findChildren(QAbstractScrollArea)
    canvas = next(
        (found for found in scrolled if "CanvasController" in found.metaObject().className()),
        None,
    )
    if canvas is None:
        return None
    return canvas.horizontalScrollBar(), canvas.verticalScrollBar()


def _window_view() -> Any:
    # The brush is window-wide (K3), so any view in front reads and writes it.
    windows = Krita.instance().windows()
    view = windows[0].activeView() if windows else None
    if view is None:
        raise BridgeError("INTERNAL_ERROR", "Krita has no view in front.")
    return view


def brush_state(document: Any, preset_names: list[str]) -> dict[str, Any]:
    view = _window_view()
    current = _current(view)
    presets = {}
    found = Krita.instance().resources("preset")
    try:
        for name in preset_names:
            resource = found.get(name)
            if resource is None:
                continue
            view.setCurrentBrushPreset(resource)
            values = _current(view)
            presets[name] = {field: values[field] for field in PRESET_FIELDS}
    finally:
        _put_back(view, current)
    return {"current": current, "presets": presets}


def set_brush_state(document: Any, state: dict[str, Any]) -> None:
    view = _window_view()
    found = Krita.instance().resources("preset")
    for name, values in state["presets"].items():
        resource = found.get(name)
        if resource is None:
            continue
        view.setCurrentBrushPreset(resource)
        _preset_values(view, values)
    _put_back(view, state["current"])


def _put_back(view: Any, current: dict[str, Any]) -> None:
    name = current["preset"]
    resource = None if name is None else Krita.instance().resources("preset").get(name)
    if resource is not None:
        view.setCurrentBrushPreset(resource)
    _preset_values(view, current)
    view.setGlobalAlphaLock(bool(current["alpha_lock"]))
    view.setBrushRotation(float(current["rotation_deg"]))
    view.setForeGroundColor(_colour(current["color"]))


def _preset_values(view: Any, values: dict[str, Any]) -> None:
    view.setBrushSize(float(values["size_px"]))
    view.setPaintingOpacity(float(values["opacity"]))
    view.setPaintingFlow(float(values["flow"]))
    view.setCurrentBlendingMode(str(values["blend_mode"]))
    view.setEraserMode(bool(values["eraser"]))
