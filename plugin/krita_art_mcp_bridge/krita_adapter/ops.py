import hashlib
from typing import Any

from krita import Krita, Preset

from ..bridge_core.errors import no_arguments
from ..bridge_core.jobs import Call, Handler
from ..bridge_core.resources import fingerprint
from .qt import QApplication


def unsaved_documents(args: dict[str, Any], call: Call) -> dict[str, Any]:
    # A session restarts Krita only when this reports nothing unsaved (decision 21).
    no_arguments(args)
    documents = Krita.instance().documents()
    return {
        "open": len(documents),
        "unsaved": sum(1 for document in documents if document.modified()),
    }


def undo_action(args: dict[str, Any], call: Call) -> dict[str, Any]:
    # Measures how edit_undo shows the top undo label, on a throwaway document of its own.
    no_arguments(args)
    app = Krita.instance()
    reason = _unsafe_to_probe(app)
    if reason is not None:
        return {"skipped": reason}
    window = app.activeWindow()
    previous = window.activeView()
    action = app.action("edit_undo")
    if action is None:
        return {"action_found": False}
    before = _texts(action)
    document = app.createDocument(64, 64, "krita-art-mcp undo probe", "RGBA", "U8", "", 72.0)
    try:
        window.addView(document)
        document.rootNode().addChildNode(document.createNode("undo probe", "paintlayer"), None)
        document.waitForDone()
        after = _texts(action)
    finally:
        # Never saved: clearing the flag lets close() discard it without asking.
        document.setModified(False)
        document.close()
        if previous is not None:
            window.showView(previous)
    return {"action_found": True, "before": before, "after_add_layer": after}


def preset_digests(args: dict[str, Any], call: Call) -> dict[str, Any]:
    # Measures whether presets' settings, raw and canonical, survive a Krita restart unchanged.
    no_arguments(args)
    raw, canonical = hashlib.sha256(), hashlib.sha256()
    found = Krita.instance().resources("preset")
    for name in sorted(found):
        try:
            xml = str(Preset(found[name]).toXML())
        except Exception:
            xml = ""
        raw.update(f"{name}\t{hashlib.sha256(xml.encode('utf-8')).hexdigest()}\n".encode())
        canonical.update(f"{name}\t{fingerprint(xml)[1]}\n".encode())
    return {"presets": len(found), "raw": raw.hexdigest(), "canonical": canonical.hexdigest()}


def _unsafe_to_probe(app: Any) -> str | None:
    if QApplication.activeModalWidget() is not None:
        return "a modal dialog is open"
    if len(app.windows()) != 1:
        return "Krita does not have exactly one window"
    if any(document.modified() for document in app.documents()):
        return "a document has unsaved changes"
    return None


def _texts(action: Any) -> dict[str, str]:
    return {"text": str(action.text()), "tooltip": str(action.toolTip())}


HANDLERS: dict[str, Handler] = {
    "bridge.unsaved_documents": unsaved_documents,
    "probe.undo_action": undo_action,
    "probe.preset_digests": preset_digests,
}
