from typing import Any

from krita import InfoObject, Krita

from ..bridge_core.errors import BridgeError
from .qt import QApplication

INITIAL_LAYER = "Layer 1"


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
        try:
            # The wrapper owns the document until a view takes it (K6).
            app.windows()[0].addView(document)
            document.waitForDone()
        except BaseException:
            self.close(document)
            raise
        return document

    def describe(self, document: Any) -> dict[str, Any]:
        path = str(document.fileName())
        return {
            "name": str(document.name()),
            "path": path or None,
            "size_px": [int(document.width()), int(document.height())],
            "color_model": str(document.colorModel()),
            "depth": str(document.colorDepth()),
            "profile_id": str(document.colorProfile()),
        }

    def layers(self, document: Any) -> tuple[str, list[dict[str, Any]]]:
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

    def prepare_read(self, document: Any) -> None:
        # setActiveNode acts on the document in front, which an open's own view is (K46).
        active = document.activeNode()
        if active is not None and str(active.type()) == "selectionmask":
            document.setActiveNode(_unmasked(document, active))
            now = document.activeNode()
            if now is None or str(now.type()) == "selectionmask":
                message = "Krita kept a selection mask active, so its overlay would enter reads."
                raise BridgeError("INTERNAL_ERROR", message)
        document.waitForDone()

    def composite(self, document: Any) -> bytes:
        document.waitForDone()
        return bytes(document.pixelData(0, 0, int(document.width()), int(document.height())))

    def selection(self, document: Any) -> tuple[dict[str, int], bytes] | None:
        selection = document.selection()
        if selection is None:
            return None
        bounds = {
            "x": int(selection.x()),
            "y": int(selection.y()),
            "width": int(selection.width()),
            "height": int(selection.height()),
        }
        if bounds["width"] <= 0 or bounds["height"] <= 0:
            return bounds, b""
        data = selection.pixelData(bounds["x"], bounds["y"], bounds["width"], bounds["height"])
        return bounds, bytes(data)

    def export_kra(self, document: Any, target: str) -> bool:
        # exportImage, never saveAs: the document keeps pointing at its own file (K39).
        batch = bool(document.batchmode())
        document.setBatchmode(True)
        try:
            exported = bool(document.exportImage(target, InfoObject()))
        finally:
            document.setBatchmode(batch)
        document.waitForDone()
        return exported

    def close(self, document: Any) -> bool:
        document.waitForDone()
        document.setModified(False)
        return bool(document.close())


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


def _unmasked(document: Any, mask: Any) -> Any:
    # A local mask's layer; for the global selection's mask, the top-most layer.
    root = document.rootNode()
    parent = mask.parentNode()
    if parent is not None and _layer_id(parent) != _layer_id(root):
        return parent
    for node in reversed(root.childNodes()):
        if not str(node.type()).endswith("mask"):
            return node
    raise BridgeError("INTERNAL_ERROR", "The document has no layer to make active.")


def _layer_id(node: Any) -> str:
    # Krita's uuid as lowercase text without braces, the contract's layer id.
    return str(node.uniqueId().toString()).strip("{}").lower()
