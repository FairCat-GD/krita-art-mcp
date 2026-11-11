import hashlib
import json
from typing import Any

from .nodes import ranks
from .port import DocumentsPort

# Each node outside the root's selection masks as (id, blend mode, parent, rank, a translate
# mask's move or None), then the selection's hash or None. The root's masks hold the global
# selection, which the hash already covers; the blend and a translate's move are what an undo step
# changes in place, and adds, removes and moves change the rest.
Nodes = tuple[tuple[str, str, str, int, tuple[int, ...] | None], ...]
Fingerprint = tuple[Nodes, str | None]
# A layer, a rect, and the SHA-256 of the layer's own BGRA bytes over it before and after.
Witness = tuple[str, dict[str, int], str, str]


class Step:
    def __init__(
        self,
        op: str,
        operation_id: str,
        label: str,
        before: Fingerprint,
        after: Fingerprint,
        region: dict[str, int] | None = None,
        witness: Witness | None = None,
    ) -> None:
        self.op = op
        self.operation_id = operation_id
        self.label = label
        self.before = before
        self.after = after
        # The canvas rect whose pixels the step changed; None when it changed none.
        self.region = region
        # The pixels that tell this step from another of the same label and node state.
        self.witness = witness


class Ledger:
    # The undo steps the bridge pushed into one document, in Krita's order (invariant 5).
    def __init__(self) -> None:
        self.steps: list[Step] = []
        self.applied = 0
        # No undo goes below this: the last protection change, or a step the bridge cannot name.
        self.floor = 0
        # How many redos are allowed: those an agent's undos made, never a rollback's (K43).
        self.redo = 0
        # Steps Krita has dropped from the bottom of its undo stack.
        self.bottom = 0

    def push(self, step: Step, limit: int) -> None:
        # A new step deletes Krita's redo tail (K43).
        del self.steps[self.applied :]
        self.steps.append(step)
        self.applied += 1
        self.redo = 0
        self.bottom = max(self.bottom, len(self.steps) - limit)

    def rolled_back(self) -> None:
        # Krita keeps the undone step as a redo, which no history call may reach: its push left
        # no redo allowed, and the rollback adds none.
        self.applied -= 1
        del self.steps[self.applied :]

    def seal(self) -> None:
        self.floor = self.applied
        self.redo = 0

    def undone(self) -> None:
        self.applied -= 1
        self.redo += 1

    def redone(self) -> None:
        self.applied += 1
        self.redo -= 1

    def undo_available(self) -> int:
        return max(0, self.applied - max(self.floor, self.bottom))


def selection_state(
    port: DocumentsPort, document: Any, size: list[int]
) -> tuple[dict[str, int], bytes] | None:
    # The global selection over its bounds clipped to the canvas, one byte per pixel.
    bounds = port.selection_bounds(document)
    if bounds is None:
        return None
    left, top = max(0, bounds["x"]), max(0, bounds["y"])
    right = min(size[0], bounds["x"] + bounds["width"])
    bottom = min(size[1], bounds["y"] + bounds["height"])
    if right <= left or bottom <= top:
        return {"x": 0, "y": 0, "width": 0, "height": 0}, b""
    clipped = {"x": left, "y": top, "width": right - left, "height": bottom - top}
    pixels = port.selection_rect(document, clipped)
    return clipped, b"" if pixels is None else bytes(pixels)


def fingerprint(
    port: DocumentsPort, document: Any, tree: dict[str, Any] | None = None
) -> Fingerprint:
    # tree is one the caller read since the document last changed.
    size = port.describe(document)["size_px"]
    return fingerprint_of(tree or port.tree(document), selection_state(port, document, size))


def fingerprint_of(tree: dict[str, Any], state: tuple[dict[str, int], Any] | None) -> Fingerprint:
    states = node_states(tree)
    if state is None:
        return states, None
    bounds, pixels = state
    digest = hashlib.sha256(json.dumps(bounds, sort_keys=True).encode("utf-8"))
    digest.update(pixels)
    return states, digest.hexdigest()


def node_states(tree: dict[str, Any]) -> Nodes:
    ranked = ranks(tree)
    return tuple(
        sorted(
            (
                node["id"],
                node["blend_mode"],
                node["parent_id"],
                ranked[node["id"]],
                None if node["translation_px"] is None else tuple(node["translation_px"]),
            )
            for node in tree["nodes"]
            if node["id"] in ranked
        )
    )
