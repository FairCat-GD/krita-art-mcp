from typing import Any, Protocol

from .errors import BridgeError


class DocumentsPort(Protocol):
    # Krita as the document ops see it; every method runs inside a job on the main thread.
    def documents(self) -> list[Any]: ...

    def refusal(self) -> BridgeError | None: ...

    # Creates, gives the document a view at once, and waits; cleans up after its own failure.
    def create(self, name: str, width: int, height: int) -> Any: ...

    # Opens in batch mode; IO_ERROR if Krita cannot. Nothing after it can strand the document.
    def open(self, path: str) -> Any: ...

    # Gives an opened document its view at once (K6), and waits.
    def show(self, document: Any) -> None: ...

    # {name, path, size_px, color_model, depth, profile_id, current_time}.
    def describe(self, document: Any) -> dict[str, Any]: ...

    # The root's id, then each child as {id, type, opacity, active, alpha_at_origin}.
    def layers(self, document: Any) -> tuple[str, list[dict[str, Any]]]: ...

    # {root_id, active_id, nodes}: every node depth-first in Krita's child order, as Krita
    # reports it (type as Node.type(), opacity 0-255, offset_px, bounds_px).
    def tree(self, document: Any) -> dict[str, Any]: ...

    # K46: no selection mask stays the active node, so its overlay never enters a read or save.
    def prepare_read(self, document: Any) -> None: ...

    # The projection over the whole canvas, B, G, R, A for integer RGBA (K12), as a bytes-like
    # buffer.
    def composite(self, document: Any) -> Any: ...

    # The global selection's bounds {x, y, width, height} and a buffer of one byte per pixel.
    def selection(self, document: Any) -> tuple[dict[str, int], Any] | None: ...

    # The projection over each rect {x, y, width, height}, as composite() reads it.
    def composite_rects(self, document: Any, rects: list[dict[str, int]]) -> list[Any]: ...

    # One paint layer's own device over each rect (K12): no opacity, masks or inherit-alpha
    # clip. LAYER_NOT_FOUND for an unknown id.
    def layer_rects(
        self, document: Any, layer_id: str, rects: list[dict[str, int]]
    ) -> list[Any]: ...

    # The global selection over a rect, one byte per pixel; None when there is no selection.
    def selection_rect(self, document: Any, rect: dict[str, int]) -> Any | None: ...

    # Whether a selection mask is the active node, whose overlay would enter a composite (K46).
    def mask_active(self, document: Any) -> bool: ...

    # Makes the document's view the active one, so prepare_read can act on it. Returns the view
    # it replaced, or None when nothing needs putting back.
    def bring_forward(self, document: Any) -> Any: ...

    # Puts back a view bring_forward replaced; logs a failure and never raises.
    def restore_view(self, view: Any) -> None: ...

    # The document in the active view, or None.
    def front(self) -> Any: ...

    # Harness only: adds a local selection mask over rect to a layer and makes it the active
    # node; whether the composite over rect changed with it.
    def add_active_mask(self, document: Any, layer_id: str, rect: dict[str, int]) -> bool: ...

    # Writes the document as KRA with Krita's own exporter; False while autosave holds it (K45).
    def export_kra(self, document: Any, target: str) -> bool: ...

    # Waits, clears the modified flag so Krita never asks to save, then closes.
    def close(self, document: Any) -> bool: ...


class ResourcesPort(Protocol):
    # Krita's resources as resource.list sees them; every method runs inside a job.
    # Every brush preset as {name, file}, file being the resource's file name.
    def presets(self) -> list[dict[str, str]]: ...

    # Each named preset's settings as Preset.toXML() writes them; "" for one it cannot.
    def preset_xmls(self, names: list[str]) -> dict[str, str]: ...

    def profiles(self, model: str, depth: str) -> list[str]: ...

    # Every palette as {name, file}.
    def palettes(self) -> list[dict[str, str]]: ...
