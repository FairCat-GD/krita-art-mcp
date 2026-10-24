import contextlib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from . import nodes, paths, transfer
from .errors import BridgeError, exact
from .jobs import Call, Handler
from .ledger import Fingerprint, Step, fingerprint
from .port import DocumentsPort
from .registry import Handle, Registry

HISTORY_FIELDS = {"document_id", "action", "steps"}
MAX_STEPS = 50

UNDO = "undo"
REDO = "redo"
# The names Krita's Undo and Redo actions give each step the bridge pushes (K7), as measured on
# Krita 5.3.4 in English; any other name is a step the bridge did not make.
LABELS = {
    "layer.create": "Add Layer",
    "selection.set": "",
    "selection.clear": "",
}


DONE = "done"
# Nothing changed: the top step is not the one expected.
FOREIGN = "foreign"
# The step moved Krita, could not be confirmed, and was put back.
REVERSED = "reversed"
# The step moved Krita and neither it nor its reversal could be confirmed.
LOST = "lost"


@contextlib.contextmanager
def in_front(port: DocumentsPort, document: Any) -> Iterator[None]:
    # Undo and redo act on the document in the active view (K7); the owner's view comes back.
    previous = port.bring_forward(document)
    try:
        yield
    finally:
        if previous is not None:
            port.restore_view(previous)


def move(
    port: DocumentsPort,
    handle: Any,
    step: Step,
    direction: str,
    known: Fingerprint | None = None,
) -> tuple[str, dict[str, Any], Fingerprint | None]:
    # Undoes or redoes one ledger step, inside in_front(). Krita must show the step on top, by
    # its label and by the document's state, before and after; a move that cannot be confirmed
    # is reversed once, and the document is unsafe if that cannot be confirmed either. known is
    # the state the previous move confirmed in this job, so it is not read again; the state now
    # confirmed comes back.
    document = handle.document
    back = direction == UNDO
    now, then = (step.after, step.before) if back else (step.before, step.after)
    seen = _shows(port, document, step.label, UNDO if back else REDO, now, known)
    if seen is not None:
        return FOREIGN, seen, None
    was = handle.before_change()
    _act(port, document, back)
    seen = _shows(port, document, step.label, REDO if back else UNDO, then)
    if seen is None:
        return DONE, {}, then
    _act(port, document, not back)
    if _shows(port, document, step.label, UNDO if back else REDO, now) is None:
        # Back as it was, so nothing changed.
        handle.dirty = was
        return REVERSED, seen, now
    handle.unsafe = True
    return LOST, seen, None


def _act(port: DocumentsPort, document: Any, back: bool) -> None:
    if back:
        port.undo(document)
    else:
        port.redo(document)


def _shows(
    port: DocumentsPort,
    document: Any,
    label: str,
    action: str,
    state: Fingerprint,
    known: Fingerprint | None = None,
) -> dict[str, Any] | None:
    # None when the action names the step and the document is in that state; else what was seen.
    front = port.front() == document
    undo_label, redo_label = port.undo_labels(document)
    found = undo_label if action == UNDO else redo_label
    if front and found == label and (known or fingerprint(port, document)) == state:
        return None
    return {"expected_label": label, "found_label": found, "action": action, "in_front": front}


def handlers(registry: Registry, port: DocumentsPort, data: Path) -> dict[str, Handler]:
    def step_history(handle: Handle, args: dict[str, Any], call: Call) -> dict[str, Any]:
        action, count, ledger = args["action"], args["steps"], handle.ledger
        available = ledger.undo_available() if action == UNDO else ledger.redo
        if count > available:
            details = {
                "steps": count,
                "undo_available": ledger.undo_available(),
                "redo_available": ledger.redo,
            }
            message = (
                f"Only {available} {action} step(s) are allowed: undo never goes below the last "
                "protection change, and redo only re-applies what history undid."
            )
            raise BridgeError("INVALID_ARGUMENT", message, False, details)
        applied: list[Step] = []
        stopped = None
        current: Fingerprint | None = None
        with in_front(port, handle.document):
            for _ in range(count):
                index = ledger.applied - 1 if action == UNDO else ledger.applied
                outcome, seen, current = move(port, handle, ledger.steps[index], action, current)
                if outcome == DONE:
                    (ledger.undone if action == UNDO else ledger.redone)()
                    applied.append(ledger.steps[index])
                    continue
                if outcome == FOREIGN:
                    # History cannot cross a step it cannot name, now or later.
                    ledger.seal()
                stopped = "not_the_bridges_step" if outcome == FOREIGN else "unconfirmed"
                if not applied:
                    _refuse(handle, outcome, seen)
                break
        region = _union([step.region for step in applied])
        pixels = None
        if region is not None:
            with nodes.unmasked_view(port, handle.document):
                [buffer] = port.composite_rects(handle.document, [region])
            pixels = transfer.write(
                paths.transfer_dir(data), buffer, region["width"], region["height"], "BGRA8"
            )
        return {
            "document_id": handle.document_id,
            "action": action,
            "steps_applied": len(applied),
            "verified": stopped is None,
            "stopped": stopped,
            "steps": [{"op": step.op, "operation_id": step.operation_id} for step in applied],
            "undo_available": ledger.undo_available(),
            "redo_available": ledger.redo,
            "region_px": region,
            "pixels": pixels,
        }

    guarded = registry.guarded(step_history)

    def history_step(args: dict[str, Any], call: Call) -> dict[str, Any]:
        exact(args, HISTORY_FIELDS)
        steps = args["steps"]
        if args["action"] not in (UNDO, REDO):
            raise BridgeError("INVALID_ARGUMENT", "action is undo or redo.")
        if not isinstance(steps, int) or isinstance(steps, bool) or not 1 <= steps <= MAX_STEPS:
            raise BridgeError("INVALID_ARGUMENT", f"steps is a whole number from 1 to {MAX_STEPS}.")
        return guarded(args, call)

    return {"history.step": history_step}


def _refuse(handle: Handle, outcome: str, seen: dict[str, Any]) -> None:
    details = {"document_id": handle.document_id, **seen}
    if outcome == LOST:
        message = (
            "Krita's history did not move as the bridge expected and could not be put back; the "
            "document is unsafe. Inspect it, then reopen it."
        )
        raise BridgeError("INTERNAL_ERROR", message, False, details)
    if outcome == REVERSED:
        # Krita did not take the step, and the document was confirmed back as it was.
        message = "Krita did not take the step; the document is as it was. Retry."
        raise BridgeError("INTERNAL_ERROR", message, True, details)
    message = (
        "The document's history holds a step the bridge did not make (an edit in Krita, or one "
        "the bridge cannot name), so history stops there."
    )
    raise BridgeError("INVALID_ARGUMENT", message, False, details)


def _union(regions: list[dict[str, int] | None]) -> dict[str, int] | None:
    found = [region for region in regions if region is not None]
    if not found:
        return None
    left = min(region["x"] for region in found)
    top = min(region["y"] for region in found)
    right = max(region["x"] + region["width"] for region in found)
    bottom = max(region["y"] + region["height"] for region in found)
    return {"x": left, "y": top, "width": right - left, "height": bottom - top}
