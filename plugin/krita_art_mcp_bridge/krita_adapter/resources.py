import os
from typing import Any

from krita import Krita, Preset


class KritaResources:
    # Krita's resources as resource.list sees them; every method runs inside a job.
    def presets(self) -> list[dict[str, str]]:
        return _named(Krita.instance().resources("preset"))

    def preset_xmls(self, names: list[str]) -> dict[str, str]:
        found = Krita.instance().resources("preset")
        xmls = {}
        for name in names:
            resource = found.get(name)
            try:
                xmls[name] = "" if resource is None else str(Preset(resource).toXML())
            except Exception:
                xmls[name] = ""
        return xmls

    def profiles(self, model: str, depth: str) -> list[str]:
        return [str(profile) for profile in Krita.instance().profiles(model, depth)]

    def palettes(self) -> list[dict[str, str]]:
        return _named(Krita.instance().resources("palette"))


def _named(resources: Any) -> list[dict[str, str]]:
    # The id is the file name; a resource Krita gives none is known by its name.
    entries = []
    for name, resource in resources.items():
        file = os.path.basename(str(resource.filename()))
        entries.append({"name": str(name), "file": file or str(name)})
    return entries
