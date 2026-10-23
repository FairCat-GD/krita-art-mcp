from typing import Any

from krita import Krita

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
            app.activeWindow().addView(document)
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
        children = []
        for node in root.childNodes():
            pixel = bytes(node.pixelData(0, 0, 1, 1))
            children.append(
                {
                    "id": _layer_id(node),
                    "type": str(node.type()),
                    "opacity": int(node.opacity()),
                    # Integer RGBA is stored B, G, R, A (K12).
                    "alpha_at_origin": pixel[3] if len(pixel) == 4 else None,
                }
            )
        return _layer_id(root), children

    def close(self, document: Any) -> bool:
        document.waitForDone()
        document.setModified(False)
        return bool(document.close())


def _layer_id(node: Any) -> str:
    # Krita's uuid as lowercase text without braces, the contract's layer id.
    return str(node.uniqueId().toString()).strip("{}").lower()
