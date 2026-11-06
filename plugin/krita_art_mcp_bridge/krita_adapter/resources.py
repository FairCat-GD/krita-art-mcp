import os
from typing import Any

from krita import Krita, Preset

from .qt import QAbstractItemView, QAbstractProxyModel, QApplication

# Qt::UserRole as a number, and the columns of Krita's resource model read as roles past it
# (K51); the bridge avoids Qt enums.
USER_ROLE = 256
FILENAME, RESOURCE_TYPE, DIRTY, RESOURCE_ACTIVE, STORAGE_ACTIVE = 3, 8, 12, 14, 15
PRESETS = "paintoppresets"
# useDirtyPresets as Krita reads it when kritarc says nothing, or as it writes that default
# back (KisConfig::useDirtyPresets).
DIRTY_PRESETS_DEFAULT = "true"


class KritaResources:
    # Krita's resources as resource.list sees them; every method runs inside a job.
    def __init__(self) -> None:
        # The preset model found last, kept while Krita keeps it.
        self._models: list[Any] = []

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

    def preset_dirty(self, preset_id: str) -> bool | None:
        if self._models:
            try:
                return _dirty(self._models, preset_id)
            except RuntimeError:
                # A model Krita has since deleted: look again.
                pass
        self._models = _preset_models()
        return _dirty(self._models, preset_id)

    def dirty_presets_setting(self) -> str | None:
        text = str(Krita.instance().readSetting("", "useDirtyPresets", ""))
        return None if text in ("", DIRTY_PRESETS_DEFAULT) else text

    def profiles(self, model: str, depth: str) -> list[str]:
        return [str(profile) for profile in Krita.instance().profiles(model, depth)]

    def palettes(self) -> list[dict[str, str]]:
        return _named(Krita.instance().resources("palette"))


def _dirty(models: list[Any], preset_id: str) -> bool | None:
    # Where two storages hold the file name, the row of an active preset in an active storage.
    rows = []
    for model in models:
        for row in range(model.rowCount()):
            index = model.index(row, 0)
            name = model.data(index, USER_ROLE + FILENAME)
            if name is not None and os.path.basename(str(name)) == preset_id:
                active = model.data(index, USER_ROLE + RESOURCE_ACTIVE) is True
                active = active and model.data(index, USER_ROLE + STORAGE_ACTIVE) is True
                rows.append((not active, model.data(index, USER_ROLE + DIRTY)))
    if not rows:
        return None
    dirty = min(rows, key=lambda found: found[0])[1]
    return dirty if isinstance(dirty, bool) else None


def _preset_models() -> list[Any]:
    # The brush presets' own model behind Krita's resource choosers, which all show the same
    # rows. Only resource views are asked: another docker's model can crash on a stray data().
    for widget in QApplication.allWidgets():
        if not isinstance(widget, QAbstractItemView) or "Resource" not in _class(widget):
            continue
        model = widget.model()
        while isinstance(model, QAbstractProxyModel) and model.sourceModel() is not None:
            model = model.sourceModel()
        if model is None or "Resource" not in _class(model):
            continue
        if model.rowCount() and model.data(model.index(0, 0), USER_ROLE + RESOURCE_TYPE) == PRESETS:
            return [model]
    return []


def _class(thing: Any) -> str:
    return str(thing.metaObject().className())


def _named(resources: Any) -> list[dict[str, str]]:
    return [
        {"name": str(name), "file": _file(name, resource)} for name, resource in resources.items()
    ]


def _file(name: Any, resource: Any) -> str:
    # The id is the file name; a resource Krita gives none is known by its name.
    return os.path.basename(str(resource.filename())) or str(name)
