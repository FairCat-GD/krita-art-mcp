import contextlib
import hashlib
import logging
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from . import log, nodes, paths, verification
from .errors import BridgeError, exact, integer
from .jobs import Call, Handler
from .ledger import Fingerprint, Step, fingerprint
from .port import DocumentsPort
from .rects import union
from .registry import Handle, Registry

HISTORY_FIELDS = {"document_id", "action", "steps"}
MAX_STEPS = 50


def reach(port: DocumentsPort) -> int:
    # The steps one call may push and still take back whole: Krita's own limit, and ours.
    return min(MAX_STEPS, port.undo_limit())


UNDO = "undo"
REDO = "redo"
# The names Krita's Undo and Redo actions give each step an op pushes, in Krita's order (K7), as
# measured on Krita 5.3.4 in English; any other name is a step the bridge did not make. A
# selection's step and a transform mask's params change are unnamed (K53). Krita's own Layer >
# Transform names its steps as a scale, rotate or shear's are named (K54).
ADD = "Add Layer"
REMOVE = "Remove Layer"
SCALE = "Scale Layer"
ROTATE = "Rotate Layer"
SHEAR = "Shear Layer"
LABELS: dict[str, tuple[str, ...]] = {
    "layer.create": (ADD,),
    "layer.duplicate": (ADD,),
    "layer.remove": (REMOVE,),
    "layer.reorder": (REMOVE, ADD),
    "layer.transform": (ADD, ""),
    "layer.transform.scale": (SCALE,),
    "layer.transform.rotate": (ROTATE,),
    "layer.transform.shear": (SHEAR,),
    "layer.update": ("Composition Mode Change",),
    "selection.set": ("",),
    "selection.clear": ("",),
    "paint.stroke": ("Scripted Brush Stroke",),
    "paint.fill": ("Scripted Brush Stroke",),
}


DONE = "done"
# Nothing changed: the top step is not the one expected.
FOREIGN = "foreign"
# The step moved Krita, could not be confirmed, and was put back.
REVERSED = "reversed"
# The step moved Krita and neither it nor its reversal could be confirmed.
LOST = "lost"
# What a receipt says stopped a batch after its first step.
STOPPED = {
    FOREIGN: "not_the_bridges_step",
    REVERSED: "unconfirmed",
    LOST: "document_unsafe",
}


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
    acting: Callable[[], None] | None = None,
) -> tuple[str, dict[str, Any], Fingerprint | None]:
    # Undoes or redoes one ledger step, inside in_front(). Krita must show the step on top, by
    # its label, the document's state and any witness pixels, before and after; a move that
    # cannot be confirmed is reversed once, and the document is unsafe if that cannot be
    # confirmed either. known is the state the previous move confirmed in this job, so it is not
    # read again (pixels always are); the state now confirmed comes back. A raise before Krita
    # is asked to move leaves it as it was; once asked, a raise is LOST, or re-raised if it is
    # not an Exception. acting runs just before that: history.step's marker, which a rollback
    # has no use for, being past its own op's.
    document = handle.document
    back = direction == UNDO
    now, then = (step.after, step.before) if back else (step.before, step.after)
    shown, hidden = _pixels(step, back), _pixels(step, not back)
    seen = _shows(port, document, step.label, UNDO if back else REDO, now, known, shown)
    if seen is not None:
        return FOREIGN, seen, None
    if acting is not None:
        acting()
    was = handle.before_change()
    try:
        _act(port, document, back)
        seen = _shows(port, document, step.label, REDO if back else UNDO, then, None, hidden)
        if seen is None:
            return DONE, {}, then
        _act(port, document, not back)
        if _shows(port, document, step.label, UNDO if back else REDO, now, None, shown) is None:
            # Back as it was, so nothing changed.
            handle.dirty = was
            return REVERSED, seen, now
    except Exception as raised:
        logging.getLogger(log.NAME).exception("Krita raised once asked to move a step")
        seen = {"expected_label": step.label, "raised": type(raised).__name__}
    except BaseException:
        handle.lost()
        raise
    handle.lost()
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
    pixels: tuple[str, dict[str, int], str] | None = None,
) -> dict[str, Any] | None:
    # None when the action names the step and the document is in that state; else what was seen.
    front = port.front() == document
    undo_label, redo_label = port.undo_labels(document)
    found = undo_label if action == UNDO else redo_label
    # Whether the document reached the state the move would have left: an unnamed step reads the
    # same empty label either way (Krita keeps Redo enabled as "Redo "), so only this tells a
    # step Krita did not take from one it moved.
    matched = (known or fingerprint(port, document)) == state
    if front and found == label and matched and _holds(port, document, pixels):
        return None
    return {
        "expected_label": label,
        "found_label": found,
        "action": action,
        "in_front": front,
        "state_matched": matched,
    }


def _pixels(step: Step, after: bool) -> tuple[str, dict[str, int], str] | None:
    # The layer, rect and hash the step's witness expects on that side of it.
    if step.witness is None:
        return None
    layer_id, rect, before, done = step.witness
    return layer_id, rect, done if after else before


def _holds(
    port: DocumentsPort, document: Any, pixels: tuple[str, dict[str, int], str] | None
) -> bool:
    if pixels is None:
        return True
    layer_id, rect, digest = pixels
    [buffer] = port.layer_rects(document, layer_id, [rect])
    return hashlib.sha256(memoryview(buffer).cast("B")).hexdigest() == digest


def refuse_cumulative(port: DocumentsPort, noun: str = "stroke") -> None:
    if port.cumulative_undo():
        details: dict[str, Any] = {"reason": "cumulative_undo"}
        message = (
            f"Krita's cumulative undo merges {noun}s into one undo step, so a {noun} could "
            "not be undone alone; turn it off in Krita's settings."
        )
        raise BridgeError("UNSUPPORTED_CAPABILITY", message, False, details)


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
        needed = whole(ledger, action, count)
        if needed != count:
            details = {
                "steps": count,
                "steps_needed": needed,
                "undo_available": ledger.undo_available(),
                "redo_available": ledger.redo,
            }
            message = (
                f"{count} {action} step(s) would split an operation, such as a reorder, whose "
                f"steps move together; ask for {needed}."
            )
            reach = min(available, MAX_STEPS)
            if needed > reach:
                # Its other steps lie past what history reaches, so no count takes it whole.
                done = "undone" if action == UNDO else "redone"
                message = (
                    f"{count} {action} step(s) would split an operation, such as a reorder, "
                    f"whose steps move together, and its {needed} steps run past the {reach} "
                    f"history can reach, so it can no longer be {done} whole."
                )
            raise BridgeError("INVALID_ARGUMENT", message, False, details)
        applied: list[Step] = []
        stopped = None
        current: Fingerprint | None = None
        with in_front(port, handle.document):
            for _ in range(count):
                index = ledger.applied - 1 if action == UNDO else ledger.applied
                try:
                    outcome, seen, current = move(
                        port, handle, ledger.steps[index], action, current, call.mark
                    )
                except Exception as raised:
                    # Before Krita was asked to move: the document is as it was.
                    logging.getLogger(log.NAME).exception("history.step raised before a step")
                    outcome, seen, current = REVERSED, {"raised": type(raised).__name__}, None
                if outcome == DONE:
                    (ledger.undone if action == UNDO else ledger.redone)()
                    applied.append(ledger.steps[index])
                    continue
                named = seen.get("found_label") == ledger.steps[index].label
                if outcome == REVERSED and named and seen.get("state_matched"):
                    # Krita moved a step of that name that was not this one, as a retry would;
                    # one it did not take leaves the state as it was and stays retryable.
                    outcome = FOREIGN
                if outcome == FOREIGN:
                    # History cannot cross a step it cannot name, now or later.
                    ledger.seal()
                stopped = STOPPED[outcome]
                if not applied:
                    _refuse(handle, outcome, seen)
                break
        region = union(step.region for step in applied)
        pixels = None
        if region is not None:
            pixels = _capture(handle, region)
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

    def _capture(handle: Handle, region: dict[str, int]) -> dict[str, Any] | None:
        # The steps ran, so a capture that cannot be read or written leaves the receipt true.
        try:
            with nodes.unmasked_view(port, handle.document):
                [buffer] = port.composite_rects(handle.document, [region])
        except Exception:
            logging.getLogger(log.NAME).exception("history.step's capture was not read")
            return None
        return verification.write(paths.transfer_dir(data), buffer, region, "BGRA8")

    guarded = registry.guarded(step_history)

    def history_step(args: dict[str, Any], call: Call) -> dict[str, Any]:
        exact(args, HISTORY_FIELDS)
        steps = args["steps"]
        if args["action"] not in (UNDO, REDO):
            raise BridgeError("INVALID_ARGUMENT", "action is undo or redo.")
        if not integer(steps) or not 1 <= steps <= MAX_STEPS:
            raise BridgeError("INVALID_ARGUMENT", f"steps is a whole number from 1 to {MAX_STEPS}.")
        return guarded(args, call)

    return {"history.step": history_step}


def whole(ledger: Any, action: str, count: int) -> int:
    # The fewest steps from count up that stop at an operation's edge, so no op is left half
    # moved; a rollback undoes its own steps whole, so ops start and end there.
    steps, needed = ledger.steps, count
    if action == UNDO:
        while (
            ledger.applied - needed - 1 >= 0
            and steps[ledger.applied - needed - 1].operation_id
            == steps[ledger.applied - needed].operation_id
        ):
            needed += 1
        return needed
    while (
        ledger.applied + needed < len(steps)
        and steps[ledger.applied + needed].operation_id
        == steps[ledger.applied + needed - 1].operation_id
    ):
        needed += 1
    return needed


def _refuse(handle: Handle, outcome: str, seen: dict[str, Any]) -> None:
    details = {"document_id": handle.document_id, **seen}
    raised = "raised" in seen
    if outcome == LOST:
        message = (
            "Krita raised once asked to move the step, so nothing confirmed where it is"
            if raised
            else "Krita's history did not move as the bridge expected and could not be put back"
        )
        message += "; the document is unsafe. Inspect it, then reopen it."
        raise BridgeError("INTERNAL_ERROR", message, False, details)
    if outcome == REVERSED:
        # Krita did not take the step, or raised before it was asked to; nothing changed.
        message = "Krita raised before the step" if raised else "Krita did not take the step"
        message += "; the document is as it was. Retry."
        raise BridgeError("INTERNAL_ERROR", message, True, details)
    message = (
        "The document's history holds a step the bridge did not make (an edit in Krita, or one "
        "the bridge cannot name), so history stops there."
    )
    raise BridgeError("INVALID_ARGUMENT", message, False, details)
