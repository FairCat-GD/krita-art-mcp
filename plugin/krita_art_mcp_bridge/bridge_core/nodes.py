import contextlib
from collections.abc import Iterator
from typing import Any

from .errors import BridgeError
from .port import DocumentsPort


def found(tree: dict[str, Any], node_id: str, verb: str) -> dict[str, Any]:
    # The node of that id, never the root.
    if node_id == tree["root_id"]:
        details: dict[str, Any] = {"layer_id": node_id}
        message = f"The root is not a layer to {verb}."
        raise BridgeError("INVALID_ARGUMENT", message, False, details)
    node = next((node for node in tree["nodes"] if node["id"] == node_id), None)
    if node is None:
        details = {"layer_id": node_id}
        raise BridgeError("LAYER_NOT_FOUND", "No layer has that id.", False, details)
    one: dict[str, Any] = node
    return one


def global_selection(tree: dict[str, Any], node: dict[str, Any]) -> bool:
    # Krita keeps the global selection in a selection mask under the root.
    return bool(node["type"] == "selectionmask" and node["parent_id"] == tree["root_id"])


def ranks(tree: dict[str, Any]) -> dict[str, int]:
    # Each node's place among its siblings, bottom first, leaving out the global selection's
    # mask, which comes and goes with the selection.
    ranked: dict[str, int] = {}
    counted: dict[str, int] = {}
    for node in sorted(tree["nodes"], key=lambda node: node["order"]):
        if global_selection(tree, node):
            continue
        parent = node["parent_id"]
        ranked[node["id"]] = counted.get(parent, 0)
        counted[parent] = ranked[node["id"]] + 1
    return ranked


def children(tree: dict[str, Any]) -> dict[str, list[str]]:
    # Each parent's children by rank, bottom first, the global selection's mask left out.
    ranked = ranks(tree)
    parents = {node["id"]: node["parent_id"] for node in tree["nodes"]}
    found: dict[str, list[str]] = {}
    for node_id in sorted(ranked, key=lambda one: ranked[one]):
        found.setdefault(parents[node_id], []).append(node_id)
    return found


def subtree(tree: dict[str, Any], node_id: str) -> list[str]:
    # The node and every descendant, depth first in child order.
    below = children(tree)
    found, pending = [], [node_id]
    while pending:
        current = pending.pop()
        found.append(current)
        pending.extend(reversed(below.get(current, [])))
    return found


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
