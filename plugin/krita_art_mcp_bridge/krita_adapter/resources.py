import os
from typing import Any

from krita import Krita, Preset


class KritaResources:
    # Krita's resources as resource.list sees them; every method runs inside a job.
    def presets(self) -> list[dict[str, str]]:
        return _named(Krita.instance().resources("preset"))

    def preset_xmls(self, names: list[str]) -> dict[str, str]:
        found = Krita.instance().resources("preset")
        return {name: self.preset_xml(found.get(name)) for name in names}

    def preset(self, preset_id: str) -> dict[str, Any] | None:
        for name, resource in Krita.instance().resources("preset").items():
            if _file(name, resource) == preset_id:
                return {
                    "name": str(name),
                    "xml": self.preset_xml(resource),
                    "resource": resource,
                }
        return None

    def preset_xml(self, resource: Any) -> str:
        try:
            return "" if resource is None else str(Preset(resource).toXML())
        except Exception:
            return ""

    def profiles(self, model: str, depth: str) -> list[str]:
        return [str(profile) for profile in Krita.instance().profiles(model, depth)]

    def palettes(self) -> list[dict[str, str]]:
        return _named(Krita.instance().resources("palette"))


def _named(resources: Any) -> list[dict[str, str]]:
    return [
        {"name": str(name), "file": _file(name, resource)} for name, resource in resources.items()
    ]


def _file(name: Any, resource: Any) -> str:
    # The id is the file name; a resource Krita gives none is known by its name.
    return os.path.basename(str(resource.filename())) or str(name)
