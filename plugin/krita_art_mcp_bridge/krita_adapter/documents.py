import logging
import time
from typing import Any

from krita import InfoObject, Krita, Selection

from ..bridge_core import log
from ..bridge_core.errors import BridgeError
from . import painting, selections
from .qt import EXCLUDE_USER_INPUT, QApplication, QCoreApplication, QIcon

ANNOUNCEMENT = "krita-art-mcp: an agent is working on this document"
ANNOUNCEMENT_MS = 1500
# Krita's lowest, so the message never displaces one of Krita's own.
ANNOUNCEMENT_PRIORITY = 2
INITIAL_LAYER = "Layer 1"
PROBE_MASK = "krita-art-mcp probe mask"
PROBE_NODE = "krita-art-mcp probe node"
# A filter every Krita build has, which spreads a change past a layer's bounds.
PROBE_FILTER = "blur"
UNLIMITED = 1_000_000_000
# KisConfig::undoStackLimit's own default when kritarc sets none (libs/ui/kis_config.cc).
UNDO_LIMIT_DEFAULT = 200


class KritaDocuments:
    # The registry's view of Krita; every method runs inside a job on the main thread.
    def documents(self) -> list[Any]:
        return list(Krita.instance().documents())

    def refusal(self) -> BridgeError | None:
        # At job start only: Krita's own busy dialog inside a job's waitForDone is expected (K41).
        if QApplication.activeModalWidget() is not None:
            message = "A dialog is open in Krita; close it, then retry."
            return BridgeError("KRITA_MODAL_DIALOG", message, True)
        windows = len(Krita.instance().windows())
        if windows != 1:
            message = f"Krita needs exactly one main window; it has {windows}."
            return BridgeError("MULTIPLE_WINDOWS", message, True, {"windows": windows})
        return None

    def create(self, name: str, width: int, height: int) -> Any:
        app = Krita.instance()
        document = app.createDocument(width, height, name, "RGBA", "U8", "", 72.0)
        if document is None:
            raise BridgeError("INTERNAL_ERROR", "Krita did not create the document.")
        try:
            # createDocument's Background layer is opaque white; a new paint layer is transparent.
            # setChildNodes swaps it without an undo step, so undo cannot bring the white back.
            layer = document.createNode(INITIAL_LAYER, "paintlayer")
            document.rootNode().setChildNodes([layer])
            # The refusal at job start leaves exactly one window; activeWindow() may be None.
            app.windows()[0].addView(document)
            document.setActiveNode(layer)
            document.waitForDone()
        except BaseException:
            self.close(document)
            raise
        return document

    def open(self, path: str) -> Any:
        app = Krita.instance()
        # Batch mode keeps Krita's import dialogs away during the open (K14).
        batch = bool(app.batchmode())
        app.setBatchmode(True)
        try:
            document = app.openDocument(path)
        finally:
            app.setBatchmode(batch)
        if document is None:
            raise BridgeError("IO_ERROR", "Krita could not open the file.", False, {"path": path})
        return document

    def show(self, document: Any) -> None:
        # The wrapper owns the document until a view takes it (K6).
        Krita.instance().windows()[0].addView(document)
        document.waitForDone()

    def describe(self, document: Any) -> dict[str, Any]:
        path = str(document.fileName())
        current = int(document.currentTime())
        return {
            "name": str(document.name()),
            "path": path or None,
            "size_px": [int(document.width()), int(document.height())],
            "color_model": str(document.colorModel()),
            "depth": str(document.colorDepth()),
            "profile_id": str(document.colorProfile()),
            "current_time": current,
            # Only walked when it can matter: at frame 0 every document shows frame 0.
            "animated": current != 0 and _animated(document.rootNode()),
        }

    def layers(self, document: Any) -> tuple[str, list[dict[str, Any]]]:
        document.waitForDone()
        root = document.rootNode()
        active = document.activeNode()
        active_id = None if active is None else _layer_id(active)
        children = []
        for node in root.childNodes():
            pixel = bytes(node.pixelData(0, 0, 1, 1))
            children.append(
                {
                    "id": _layer_id(node),
                    "type": str(node.type()),
                    "opacity": int(node.opacity()),
                    "active": _layer_id(node) == active_id,
                    # Integer RGBA is stored B, G, R, A (K12).
                    "alpha_at_origin": pixel[3] if len(pixel) == 4 else None,
                }
            )
        return _layer_id(root), children

    def tree(self, document: Any) -> dict[str, Any]:
        root = document.rootNode()
        active = document.activeNode()
        nodes: list[dict[str, Any]] = []
        _walk(root, _layer_id(root), nodes)
        return {
            "root_id": _layer_id(root),
            "active_id": None if active is None else _layer_id(active),
            "nodes": nodes,
        }

    def composite(self, document: Any) -> Any:
        document.waitForDone()
        return _buffer(document.pixelData(0, 0, int(document.width()), int(document.height())))

    def selection_bounds(self, document: Any) -> dict[str, int] | None:
        document.waitForDone()
        selection = document.selection()
        if selection is None:
            return None
        return {
            "x": int(selection.x()),
            "y": int(selection.y()),
            "width": int(selection.width()),
            "height": int(selection.height()),
        }

    def composite_rects(self, document: Any, rects: list[dict[str, int]]) -> list[Any]:
        document.waitForDone()
        return [_buffer(document.pixelData(*_xywh(rect))) for rect in rects]

    def layer_rects(self, document: Any, layer_id: str, rects: list[dict[str, int]]) -> list[Any]:
        document.waitForDone()
        node = _node(document, layer_id)
        # The layer's own paint device, in document coordinates (K12).
        return [_buffer(node.pixelData(*_xywh(rect))) for rect in rects]

    def selection_rect(self, document: Any, rect: dict[str, int]) -> Any | None:
        document.waitForDone()
        selection = document.selection()
        if selection is None:
            return None
        return _buffer(selection.pixelData(*_xywh(rect)))

    def mask_active(self, document: Any) -> bool:
        active = document.activeNode()
        return active is not None and str(active.type()) == "selectionmask"

    def bring_forward(self, document: Any) -> Any:
        # The refusal at job start leaves exactly one window; activeWindow() may be None.
        window = Krita.instance().windows()[0]
        previous = window.activeView()
        if previous is not None and previous.document() == document:
            return None
        view = next((view for view in window.views() if view.document() == document), None)
        if view is None:
            raise BridgeError("INTERNAL_ERROR", "The document has no view to bring forward.")
        # setVisible activates the view's own sub-window; Window.showView would give its widget
        # a new one.
        view.setVisible()
        now = window.activeView()
        if now is None or now.document() != document:
            if previous is not None:
                self.restore_view(previous)
            raise BridgeError("INTERNAL_ERROR", "Krita did not bring the document's view forward.")
        return previous

    def restore_view(self, view: Any) -> None:
        # Never raises, so a failure here cannot hide the read's own outcome.
        try:
            view.setVisible()
        except Exception:
            logging.getLogger(log.NAME).exception("the previous view was not put back")

    def front(self) -> Any:
        windows = Krita.instance().windows()
        view = windows[0].activeView() if windows else None
        return None if view is None else view.document()

    def announce(self, document: Any) -> None:
        # Never raises, so the message cannot fail the job it announces.
        try:
            view = Krita.instance().windows()[0].activeView()
            if view is not None and view.document() == document:
                view.showFloatingMessage(
                    ANNOUNCEMENT, QIcon(), ANNOUNCEMENT_MS, ANNOUNCEMENT_PRIORITY
                )
        except Exception:
            logging.getLogger(log.NAME).exception("the floating message was not shown")

    def activate(self, document: Any, node_id: str) -> None:
        document.setActiveNode(_node(document, node_id))
        document.waitForDone()

    def create_layer(
        self, document: Any, parent_id: str, above_id: str | None, kind: str, name: str
    ) -> str:
        root = document.rootNode()
        parent = root if _layer_id(root) == parent_id else _node(document, parent_id)
        above = None if above_id is None else _node(document, above_id)
        node = document.createNode(name, kind)
        if node is None:
            raise BridgeError("INTERNAL_ERROR", "Krita did not make the layer.")
        # addChildNode is one undo step (K22).
        if not parent.addChildNode(node, above):
            raise BridgeError("INTERNAL_ERROR", "Krita did not add the layer.")
        document.waitForDone()
        return _layer_id(node)

    def set_selection(self, document: Any, recipe: list[tuple[Any, ...]]) -> None:
        selections.commit(document, recipe, _node)

    def set_blend(self, document: Any, layer_id: str, mode: str) -> None:
        # One undo step, which marks the node's old and new extent for a redraw (K22).
        _node(document, layer_id).setBlendingMode(mode)
        document.waitForDone()

    def set_properties(self, document: Any, layer_id: str, values: dict[str, Any]) -> None:
        # None of these is an undo step or redraws (K22, K42); refresh() redraws.
        node = _node(document, layer_id)
        if "name" in values:
            node.setName(values["name"])
        if "locked" in values:
            node.setLocked(values["locked"])
        if "alpha_locked" in values:
            node.setAlphaLocked(values["alpha_locked"])
        if "inherit_alpha" in values:
            node.setInheritAlpha(values["inherit_alpha"])
        if "visible" in values:
            node.setVisible(values["visible"])
        if "opacity" in values:
            node.setOpacity(values["opacity"])
        document.waitForDone()

    def refresh(self, document: Any) -> None:
        document.refreshProjection()
        document.waitForDone()

    def effects(self, document: Any, reach: bool) -> dict[str, Any]:
        styled, clones, animated = [], {}, False
        pending = list(document.rootNode().childNodes())
        while pending:
            node = pending.pop()
            node_id = _layer_id(node)
            # libkis says whether a layer has a style only by serialising it.
            if reach and str(node.layerStyleToAsl()):
                styled.append(node_id)
            if reach and str(node.type()) == "clonelayer":
                clones[node_id] = _source_id(node)
            animated = animated or bool(node.animated())
            pending.extend(node.childNodes())
        return {"styled": sorted(styled), "clones": clones, "animated": animated}

    def undo(self, document: Any) -> None:
        _trigger("edit_undo", document)

    def redo(self, document: Any) -> None:
        _trigger("edit_redo", document)

    def undo_labels(self, document: Any) -> tuple[str | None, str | None]:
        _flush()
        return _label("edit_undo", "Undo"), _label("edit_redo", "Redo")

    def undo_actions(self, document: Any) -> dict[str, Any]:
        _flush()
        return {"undo": _raw("edit_undo"), "redo": _raw("edit_redo")}

    def undo_limit(self) -> int:
        # Krita's own setting; 0 keeps every step.
        text = str(Krita.instance().readSetting("", "undoStackLimit", str(UNDO_LIMIT_DEFAULT)))
        try:
            limit = int(text)
        except ValueError:
            return UNDO_LIMIT_DEFAULT
        return limit if limit > 0 else UNLIMITED

    def label_timing(self, document: Any, trials: int) -> list[list[str | None]]:
        root = document.rootNode()
        reads = []
        for trial in range(trials):
            node = document.createNode(f"krita-art-mcp probe timing {trial}", "paintlayer")
            root.addChildNode(node, None)
            document.waitForDone()
            straight = _label("edit_undo", "Undo")
            _flush()
            reads.append([straight, _label("edit_undo", "Undo")])
        return reads

    def add_active_mask(self, document: Any, layer_id: str, rect: dict[str, int]) -> bool:
        layer = _node(document, layer_id)
        document.waitForDone()
        before = bytes(document.pixelData(*_xywh(rect)))
        selection = Selection()
        selection.select(*_xywh(rect), 255)
        mask = document.createSelectionMask(PROBE_MASK)
        mask.setSelection(selection)
        layer.addChildNode(mask, None)
        document.setActiveNode(mask)
        document.waitForDone()
        if not self.mask_active(document):
            raise BridgeError("INTERNAL_ERROR", "Krita did not make the selection mask active.")
        return bytes(document.pixelData(*_xywh(rect))) != before

    def add_fixture_node(self, document: Any, kind: str, layer_id: str) -> tuple[str, bool]:
        layer = _node(document, layer_id)
        width, height = int(document.width()), int(document.height())
        document.waitForDone()
        before = bytes(document.pixelData(0, 0, width, height))
        if kind == "filter_layer":
            node = document.createFilterLayer(PROBE_NODE, _filter(), _whole(width, height))
            placed = layer.parentNode().addChildNode(node, layer)
        elif kind == "filter_mask":
            node = document.createFilterMask(PROBE_NODE, _filter(), _whole(width, height))
            placed = layer.addChildNode(node, None)
        elif kind == "transform_mask":
            node = document.createTransformMask(PROBE_NODE)
            placed = layer.addChildNode(node, None)
        else:
            node = document.createCloneLayer(PROBE_NODE, layer)
            placed = document.rootNode().addChildNode(node, None)
        if node is None or not placed:
            raise BridgeError("INTERNAL_ERROR", f"Krita did not add the {kind}.")
        document.waitForDone()
        return _layer_id(node), bytes(document.pixelData(0, 0, width, height)) != before

    def set_brush(self, document: Any, brush: dict[str, Any], preset: Any) -> dict[str, Any]:
        return painting.set_brush(document, brush, preset)

    def brush(self, document: Any) -> dict[str, Any]:
        return painting.read_brush(document)

    def paint_ability(self, document: Any, layer_id: str) -> str:
        return str(_node(document, layer_id).paintAbility())

    def paint_path(self, document: Any, layer_id: str, path: dict[str, Any]) -> None:
        painting.paint_path(document, _node(document, layer_id), path)

    def cumulative_undo(self) -> bool:
        return painting.cumulative_undo()

    def view_state(self, document: Any) -> dict[str, Any]:
        return painting.view_state(document)

    def set_view(self, document: Any, view: dict[str, Any]) -> dict[str, Any]:
        return painting.set_view(document, view)

    def brush_state(self, document: Any, preset_ids: list[str]) -> dict[str, Any]:
        return painting.brush_state(document, preset_ids)

    def set_brush_state(self, document: Any, state: dict[str, Any]) -> None:
        painting.set_brush_state(document, state)

    def export(self, document: Any, target: str) -> bool:
        # exportImage, never saveAs: the document keeps pointing at its own file (K39).
        batch = bool(document.batchmode())
        document.setBatchmode(True)
        try:
            exported = bool(document.exportImage(target, InfoObject()))
        finally:
            document.setBatchmode(batch)
        document.waitForDone()
        return exported

    def node_pixels(
        self, document: Any, node_id: str, rect: dict[str, int], projection: bool
    ) -> Any:
        document.waitForDone()
        node = _node(document, node_id)
        if projection:
            return _buffer(node.projectionPixelData(*_xywh(rect)))
        return _buffer(node.pixelData(*_xywh(rect)))

    def close(self, document: Any, settle_s: float = 0.0) -> bool:
        document.waitForDone()
        _settle(settle_s)
        document.setModified(False)
        return bool(document.close())


def _buffer(data: Any) -> Any:
    # A view of Krita's QByteArray, so a large read is never held twice; bytes where it has none.
    try:
        return memoryview(data)
    except TypeError:
        return bytes(data)


def _walk(parent: Any, parent_id: str, nodes: list[dict[str, Any]]) -> None:
    for order, node in enumerate(parent.childNodes()):
        node_id = _layer_id(node)
        position, bounds = node.position(), node.bounds()
        nodes.append(
            {
                "id": node_id,
                "parent_id": parent_id,
                "name": str(node.name()),
                "type": str(node.type()),
                "order": order,
                "visible": bool(node.visible()),
                "opacity": int(node.opacity()),
                "blend_mode": str(node.blendingMode()),
                "locked": bool(node.locked()),
                "alpha_locked": bool(node.alphaLocked()),
                "inherit_alpha": bool(node.inheritAlpha()),
                "offset_px": [int(position.x()), int(position.y())],
                "bounds_px": {
                    "x": int(bounds.x()),
                    "y": int(bounds.y()),
                    "width": int(bounds.width()),
                    "height": int(bounds.height()),
                },
                "color_model": str(node.colorModel()),
                "depth": str(node.colorDepth()),
                "profile_id": str(node.colorProfile()),
            }
        )
        _walk(node, node_id, nodes)


def _animated(parent: Any) -> bool:
    return any(bool(node.animated()) or _animated(node) for node in parent.childNodes())


def _xywh(rect: dict[str, int]) -> tuple[int, int, int, int]:
    return rect["x"], rect["y"], rect["width"], rect["height"]


def _node(document: Any, layer_id: str) -> Any:
    pending = list(document.rootNode().childNodes())
    while pending:
        node = pending.pop()
        if _layer_id(node) == layer_id:
            return node
        pending.extend(node.childNodes())
    raise BridgeError("LAYER_NOT_FOUND", "No layer has that id.", False, {"layer_id": layer_id})


def _source_id(clone: Any) -> str | None:
    # None when Krita names no source, which counts as reaching everything.
    try:
        source = clone.sourceNode()
    except AttributeError:
        return None
    return None if source is None else _layer_id(source)


def _filter() -> Any:
    found = Krita.instance().filter(PROBE_FILTER)
    if found is None:
        raise BridgeError("INTERNAL_ERROR", f"Krita has no {PROBE_FILTER} filter.")
    return found


def _whole(width: int, height: int) -> Any:
    selection = Selection()
    selection.select(0, 0, width, height, 255)
    return selection


def _settle(seconds: float) -> None:
    # Krita's layer docker sends a changed node's update from a timer a moment later, and
    # crashes if the document has closed by then; its timers run here, user input does not.
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        QCoreApplication.processEvents(EXCLUDE_USER_INPUT, 20)
        time.sleep(0.01)


def _flush() -> None:
    # Krita adds some undo commands through posted events; this lets them, and the action texts
    # they update, through before anything reads a label or undoes. Input events stay queued.
    QCoreApplication.sendPostedEvents()


def _trigger(name: str, document: Any) -> None:
    # Undo and redo act on the document in the active view (K7); the core brought it forward.
    action = Krita.instance().action(name)
    if action is None:
        raise BridgeError("INTERNAL_ERROR", f"Krita has no {name} action.")
    action.trigger()
    document.waitForDone()
    _flush()


def _label(name: str, prefix: str) -> str | None:
    # The action's text is "Undo <label>"; a disabled action names no step, and an unnamed
    # step reads "".
    action = Krita.instance().action(name)
    if action is None or not action.isEnabled():
        return None
    text = str(action.text())
    if text.startswith(prefix):
        text = text[len(prefix) :]
    return text.strip()


def _raw(name: str) -> dict[str, Any]:
    action = Krita.instance().action(name)
    if action is None:
        return {"text": None, "enabled": None}
    return {"text": str(action.text()), "enabled": bool(action.isEnabled())}


def _layer_id(node: Any) -> str:
    # Krita's uuid as lowercase text without braces, the contract's layer id.
    return str(node.uniqueId().toString()).strip("{}").lower()
