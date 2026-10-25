import hashlib
from typing import Any

from krita import Krita, Preset

from ..bridge_core.errors import exact, no_arguments
from ..bridge_core.jobs import Call, Handler
from ..bridge_core.resources import fingerprint


def unsaved_documents(args: dict[str, Any], call: Call) -> dict[str, Any]:
    # A session restarts Krita only when this reports nothing unsaved (decision 21).
    no_arguments(args)
    documents = Krita.instance().documents()
    return {
        "open": len(documents),
        "unsaved": sum(1 for document in documents if document.modified()),
    }


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


def preset_xml(args: dict[str, Any], call: Call) -> dict[str, Any]:
    # Measures what a preset's settings hold as Krita has them now.
    exact(args, {"name"})
    found = Krita.instance().resources("preset").get(args["name"])
    return {"xml": None if found is None else str(Preset(found).toXML())}


HANDLERS: dict[str, Handler] = {
    "bridge.unsaved_documents": unsaved_documents,
    "probe.preset_digests": preset_digests,
    "probe.preset_xml": preset_xml,
}
