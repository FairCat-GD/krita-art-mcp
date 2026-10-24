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

    # Writes the document as KRA with Krita's own exporter; False while autosave holds it (K45).
    def export_kra(self, document: Any, target: str) -> bool: ...

    # Waits, clears the modified flag so Krita never asks to save, then closes.
    def close(self, document: Any) -> bool: ...
