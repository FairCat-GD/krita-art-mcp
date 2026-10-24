import contextlib
from collections.abc import Iterator
from typing import Any

from .errors import BridgeError
from .port import DocumentsPort


def unmasked(tree: dict[str, Any]) -> str | None:
    # K46: the node to make active so no selection mask's overlay enters a read or a save; None
    # when no selection mask is active. A local mask gives way to its layer; the global
    # selection's mask, a child of the root, to the top-most layer.
    active = next((node for node in tree["nodes"] if node["id"] == tree["active_id"]), None)
    if active is None or active["type"] != "selectionmask":
        return None
    if active["parent_id"] != tree["root_id"]:
        parent_id: str = active["parent_id"]
        return parent_id
    layers = [
        node
        for node in tree["nodes"]
        if node["parent_id"] == tree["root_id"] and not node["type"].endswith("mask")
    ]
    if not layers:
        raise BridgeError("INTERNAL_ERROR", "The document has no layer to make active.")
    top: str = max(layers, key=lambda node: node["order"])["id"]
    return top


@contextlib.contextmanager
def unmasked_view(port: DocumentsPort, document: Any) -> Iterator[None]:
    # Makes a layer active in place of a selection mask; setActiveNode acts on the document in
    # front, so its view comes forward and the owner's goes back afterwards.
    target = unmasked(port.tree(document))
    if target is None:
        yield
        return
    previous = port.bring_forward(document)
    try:
        port.activate(document, target)
        if port.mask_active(document):
            message = "Krita kept a selection mask active, so its overlay would enter reads."
            raise BridgeError("INTERNAL_ERROR", message)
        yield
    finally:
        if previous is not None:
            port.restore_view(previous)


def unmask(port: DocumentsPort, document: Any) -> None:
    with unmasked_view(port, document):
        pass
