import contextlib
import hashlib
import logging
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from . import log, verification
from .errors import BridgeError
from .history import DONE, UNDO, in_front, move
from .jobs import Call
from .ledger import Fingerprint, Step, Witness, fingerprint, node_states
from .port import DocumentsPort
from .rects import union
from .registry import Handle

# What a change leaves alone on every node it does not name; bounds move with a group's projection.
WATCHED = (
    "name",
    "type",
    "parent_id",
    "order",
    "visible",
    "opacity",
    "blend_mode",
    "locked",
    "alpha_locked",
    "inherit_alpha",
    "offset_px",
    "transform_sha256",
)

# What the rollback found of a step the change never pushed.
BACK = "back"
NONE = "none"
UNDONE = "undone"
FAILED = "failed"


def watched(tree: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {node["id"]: {key: node[key] for key in WATCHED} for node in tree["nodes"]}


@contextlib.contextmanager
def unconfirmed(handle: Any, changing: bool = True) -> Iterator[None]:
    # Around a change and its rollback: anything but the op's own error leaves Krita holding a
    # change the bridge can neither name nor confirm.
    try:
        yield
    except BridgeError:
        raise
    except BaseException:
        if changing:
            handle.lost()
        raise


class Reads:
    # What a change is verified over, fixed before its first change: the composite over the scope,
    # and, where named, the target over its own rect and each protected layer over its own.
    def __init__(
        self,
        mode: str,
        scope: dict[str, int],
        allowed: bytes | None,
        target_id: str | None = None,
        target_rect: dict[str, int] | None = None,
        channels: int = 4,
        hashed: dict[str, dict[str, int]] | None = None,
    ) -> None:
        self.mode = mode
        self.scope = scope
        self.allowed = allowed
        self.target_id = target_id
        self.target_rect = target_rect
        # The target's bytes per pixel: B, G, R, A, or one for a mask.
        self.channels = channels
        # None for an op that counts no protected layer's pixels.
        self.hashed = hashed


def verifiable(
    handle: Handle,
    info: dict[str, Any],
    effects: dict[str, Any],
    mode: str,
    scope: dict[str, int],
    target_id: str | None = None,
    target_rect: dict[str, int] | None = None,
    channels: int = 4,
    hashed: dict[str, dict[str, int]] | None = None,
) -> Reads:
    # Before any change: nothing the reads cannot see is changed.
    verification.refuse_unverifiable(info, effects, scope)
    if target_rect is not None:
        verification.refuse_unverifiable(info, effects, target_rect)
    allowed = verification.allowed_rows(handle, info["size_px"], scope)
    return Reads(mode, scope, allowed, target_id, target_rect, channels, hashed)


class Steps:
    # The undo steps one op makes, in Krita's order, each pushed once Krita holds it.
    def __init__(
        self,
        port: DocumentsPort,
        handle: Handle,
        op: str,
        operation_id: str,
        labels: tuple[str, ...],
        start: Fingerprint,
    ) -> None:
        self._port = port
        self._handle = handle
        self._op = op
        self._operation_id = operation_id
        self.labels = labels
        self.pushed: list[Step] = []
        # The state the last pushed step left, or the op's start.
        self.state = start
        # A step Krita pushed whose undo changes no pixel, so nothing could confirm it.
        self.sealed = False

    @property
    def taken(self) -> int:
        return len(self.pushed) + (1 if self.sealed else 0)

    def push(
        self,
        after: Fingerprint | None = None,
        witness: Witness | None = None,
        region: dict[str, int] | None = None,
    ) -> Step:
        step = Step(
            self._op,
            self._operation_id,
            self.labels[self.taken],
            self.state,
            self.state if after is None else after,
            region,
            witness,
        )
        self._handle.ledger.push(step, self._port.undo_limit())
        self.pushed.append(step)
        self.state = step.after
        return step

    def seal(self) -> None:
        # History stops below it, and the receipt says so.
        self._handle.ledger.seal()
        self.sealed = True

    def of(self, tree: dict[str, Any]) -> Fingerprint:
        # A node change leaves the selection alone, so its hash is not read again.
        return node_states(tree), self.state[1]


class Applied:
    # What a verified change left, for the op's judge and receipt.
    def __init__(self, before: verification.Reading | None, steps: Steps) -> None:
        self.before = before
        self.after: verification.Reading | None = None
        self.verdict: verification.Verdict | None = None
        # The target's own change inside its rect; None when it changed none or is not read.
        self.diff: dict[str, int] | None = None
        self.steps = steps
        # What the change returned, then what the judge did.
        self.value: Any = None
        self.checked: Any = None


class Mutation:
    # Invariant 5 for one op: the reads, the marker, the change, the verdict, the ledger and a
    # confirmed rollback, always in this order. The op brings its change, its checks and receipt.
    def __init__(
        self,
        port: DocumentsPort,
        handle: Handle,
        call: Call,
        op: str,
        labels: tuple[str, ...],
        reads: Reads | None = None,
        data: Path | None = None,
        ids: dict[str, Any] | None = None,
        noun: str = "change",
    ) -> None:
        self.port = port
        self.handle = handle
        self.call = call
        self.op = op
        self.labels = labels
        self.reads = reads
        self.data = data
        self.ids = ids or {}
        self.noun = noun
        self.before: verification.Reading | None = None

    def read(self) -> verification.Reading:
        # A write elsewhere that Krita has not drawn yet (K42) is not read as this change.
        reads = self.reads
        assert reads is not None
        document = self.handle.document
        hashed = reads.hashed or {}
        rects = dict(hashed)
        if reads.target_id is not None and reads.target_rect is not None:
            rects = {reads.target_id: reads.target_rect, **hashed}
        self.port.refresh(document)
        self.before = verification.read(
            self.port, document, reads.scope, reads.target_id, list(hashed), rects
        )
        return self.before

    def run(
        self,
        change: Callable[[Steps], Any],
        judge: Callable[[Applied], Any] = lambda applied: None,
        back: Callable[[], bool] = lambda: True,
        compensate: Callable[[], bool] = lambda: False,
        tree: dict[str, Any] | None = None,
        changing: bool = True,
    ) -> Applied:
        port, handle, call = self.port, self.handle, self.call
        assert self.reads is None or self.before is not None, "the before-read comes first"
        # An op that names no step never reads its state, so it reads no selection either.
        start: Fingerprint = fingerprint(port, handle.document, tree) if self.labels else ((), None)
        call.mark()
        was = handle.before_change()
        steps = Steps(port, handle, self.op, call.operation_id, self.labels, start)
        applied = Applied(self.before, steps)
        with unconfirmed(handle, changing):
            problem: BridgeError | None = None
            try:
                applied.value = change(steps)
                if self.reads is not None:
                    self._verify(applied)
                if steps.taken != len(self.labels):
                    details = {"op": self.op, "named": len(self.labels), "taken": steps.taken}
                    message = "The change made other undo steps than it names."
                    raise BridgeError("INTERNAL_ERROR", message, False, details)
                applied.checked = judge(applied)
            except BridgeError as raised:
                problem = raised
            except Exception as raised:
                logging.getLogger(log.NAME).exception("%s raised mid-change", self.op)
                details = {"op": self.op, "raised": type(raised).__name__}
                message = f"Krita raised during the {self.noun}; see plugin.log."
                problem = BridgeError("INTERNAL_ERROR", message, False, details)
            if problem is not None:
                kept = None if applied.after is None else applied.after.kept
                # Dropped first, so the re-read never holds two copies of the scope.
                applied.after = None
                self._roll_back(applied, was, kept, problem, back, compensate)
        for step in steps.pushed:
            if step.witness is None:
                step.region = None if applied.verdict is None else applied.verdict.changed_bounds_px
        return applied

    def files(self, applied: Applied) -> dict[str, Any] | None:
        if self.reads is None or applied.before is None or applied.verdict is None:
            return None
        assert self.data is not None
        return verification.files(
            self.data, self.reads.mode, applied.before, applied.after, applied.verdict, False
        )

    def _verify(self, applied: Applied) -> None:
        reads, before = self.reads, applied.before
        assert reads is not None and before is not None
        after = verification.read(
            self.port,
            self.handle.document,
            before.rect,
            before.target_id,
            list(before.hashes),
            before.rects,
            before.hashes,
        )
        applied.after = after
        applied.verdict = verification.check(
            before, after, reads.allowed, self.handle.preserve_composite_alpha
        )
        if reads.target_id is None or reads.target_rect is None:
            return
        _, applied.diff = verification.changes(
            before.target, after.target, reads.target_rect, reads.channels
        )
        if applied.diff is None:
            # Krita still pushes a step, but its undo changes no pixel, so nothing could
            # confirm it.
            applied.steps.seal()
            return
        applied.steps.push(
            witness=self._witness(before.target, after.target, applied.diff),
            region=union([applied.verdict.changed_bounds_px, applied.diff]),
        )

    def _witness(self, old: Any, new: Any, diff: dict[str, int]) -> Witness:
        reads = self.reads
        assert reads is not None and reads.target_id is not None and reads.target_rect is not None
        return (
            reads.target_id,
            diff,
            _sha(verification.crop(old, reads.target_rect, diff, reads.channels)),
            _sha(verification.crop(new, reads.target_rect, diff, reads.channels)),
        )

    def _roll_back(
        self,
        applied: Applied,
        was: bool,
        kept: tuple[str, Any] | None,
        problem: BridgeError,
        back: Callable[[], bool],
        compensate: Callable[[], bool],
    ) -> None:
        # Invariant 5: undone, then confirmed, or the document is unsafe.
        rolled_back, confirmed, counted, seen = self._restore(applied, kept, back, compensate)
        found = problem.body["details"]
        # A step Krita may hold that the ledger cannot name seals history below it.
        sealed = len(applied.steps.pushed) < len(self.labels) or not confirmed
        details = {
            **found,
            "document_id": self.handle.document_id,
            **self.ids,
            "rolled_back": rolled_back,
            "rollback_verified": confirmed,
            "history_sealed": sealed,
        }
        reads = self.reads
        if reads is not None and reads.hashed is not None:
            details["protected_layer_ids"] = found.get("protected_layer_ids", [])
            details["protected_pixels_changed"] = counted
        if reads is not None and reads.target_id is not None:
            details["target_outside_reach"] = found.get("target_outside_reach", False)
        if reads is not None and applied.before is not None and applied.verdict is not None:
            assert self.data is not None
            details["verification"] = verification.files(
                self.data, reads.mode, applied.before, None, applied.verdict, True
            )
        if confirmed:
            self.handle.dirty = was
            # Never retryable: a retry under this request_id would make the change again.
            raise BridgeError(problem.body["code"], problem.body["message"], False, details)
        self.handle.lost()
        details = {**seen, **details, "cause": problem.body["code"]}
        message = (
            f"The {self.noun} could not be undone and confirmed; the document is unsafe. Reopen it."
        )
        raise BridgeError("ROLLBACK_FAILED", message, False, details)

    def _restore(
        self,
        applied: Applied,
        kept: tuple[str, Any] | None,
        back: Callable[[], bool],
        compensate: Callable[[], bool],
    ) -> tuple[bool, bool, int | None, dict[str, Any]]:
        # Whether anything was undone or written back, whether the document was confirmed as it
        # was, the first changed protected layer's changed pixels, and what a failed move saw.
        port, handle, steps = self.port, self.handle, applied.steps
        seen: dict[str, Any] = {}
        try:
            undone, failed, found = False, False, NONE
            unnamed = len(steps.pushed) < len(steps.labels)
            pixel = unnamed and self._pixel(steps)
            moved = self._moved_state(steps) if unnamed and not pixel else None
            # The view comes forward only for a step that may move (K7), never to confirm.
            moving = bool(steps.pushed) or pixel or moved is not None
            with in_front(port, handle.document) if moving else contextlib.nullcontext():
                if unnamed:
                    found, seen = self._unnamed(applied, back, moved)
                    failed, undone = found == FAILED, found == UNDONE
                known: Fingerprint | None = None
                for step in reversed(steps.pushed):
                    if failed:
                        break
                    outcome, seen, known = move(port, handle, step, UNDO, known)
                    if outcome != DONE:
                        failed = True
                        break
                    handle.ledger.rolled_back()
                    undone = True
                if unnamed:
                    # Krita may hold a step the ledger cannot name: history stops below it,
                    # sealed once the pushed steps are off the ledger.
                    handle.ledger.seal()
            wrote = compensate()
            if failed:
                return False, False, None, seen
            confirmed = (found == BACK and not undone and not wrote) or self._back(applied, back)
            return undone or wrote, confirmed, self._counted(applied, kept, confirmed), seen
        except Exception:
            logging.getLogger(log.NAME).exception("%s's rollback raised", self.op)
            return False, False, None, seen

    def _pixel(self, steps: Steps) -> bool:
        # Whether the step not pushed is the pixel step the frame pushes after its reads.
        reads = self.reads
        return (
            reads is not None
            and reads.target_id is not None
            and reads.target_rect is not None
            and len(steps.pushed) == len(steps.labels) - 1
        )

    def _moved_state(self, steps: Steps) -> Fingerprint | None:
        # The state a node step left that the change never pushed, or None if it never moved.
        now = fingerprint(self.port, self.handle.document)
        return None if now == steps.state else now

    def _unnamed(
        self, applied: Applied, back: Callable[[], bool], moved: Fingerprint | None
    ) -> tuple[str, dict[str, Any]]:
        # The step the change raised before pushing, the newest Krita may hold: undone only when
        # Krita's top step is the one this job saw happen.
        port, handle, steps, reads = self.port, self.handle, applied.steps, self.reads
        document, label = handle.document, steps.labels[len(steps.pushed)]
        if self._pixel(steps):
            assert reads is not None and reads.target_rect is not None
            before = applied.before
            assert before is not None
            port.refresh(document)
            again = verification.again(port, document, before)
            if verification.same(before, again) and back():
                return BACK, {}
            _, diff = verification.changes(
                before.target, again.target, reads.target_rect, reads.channels
            )
            if diff is None:
                return FAILED, {}
            witness = self._witness(before.target, again.target, diff)
            del again
            step = Step(
                self.op, self.call.operation_id, label, steps.state, steps.state, None, witness
            )
            outcome, seen, _ = move(port, handle, step, UNDO)
            return (UNDONE if outcome == DONE else FAILED), seen
        if moved is None:
            return NONE, {}
        step = Step(self.op, self.call.operation_id, label, steps.state, moved)
        outcome, seen, _ = move(port, handle, step, UNDO, moved)
        return (UNDONE if outcome == DONE else FAILED), seen

    def _back(self, applied: Applied, back: Callable[[], bool]) -> bool:
        before = applied.before
        if self.reads is not None and before is not None:
            self.port.refresh(self.handle.document)
            again = verification.again(self.port, self.handle.document, before)
            same = verification.same(before, again)
            del again
            if not same:
                return False
        return back()

    def _counted(
        self, applied: Applied, kept: tuple[str, Any] | None, confirmed: bool
    ) -> int | None:
        if kept is None:
            return 0
        if not confirmed or applied.before is None:
            # Not confirmed back, so the layer's pixels now are no measure of the change.
            return None
        kept_id, pixels = kept
        rect = applied.before.rects.get(kept_id, applied.before.rect)
        [now] = self.port.layer_rects(self.handle.document, kept_id, [rect])
        # Its bytes per pixel, from the read itself: four for a paint layer, one for a mask.
        channels = len(pixels) // (rect["width"] * rect["height"])
        counted, _ = verification.changes(pixels, memoryview(now).cast("B"), rect, channels)
        return counted


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
