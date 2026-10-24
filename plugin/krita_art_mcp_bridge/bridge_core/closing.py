import functools
import time
from collections.abc import Callable
from typing import Any

from .port import DocumentsPort
from .registry import Handle

# How long Krita's layer docker may still owe a changed node its update: a close this long after
# a selection change never crashed Krita 5.3.4, one at once did.
SETTLE_S = 0.5


def settle_s(handle: Handle, in_front: bool, now: float | None = None) -> float:
    # The docker shows the document in front, whoever changed it, and crashes Krita if that
    # document closes before an update it owes; a document behind is owed one only for a moment
    # after a change.
    if in_front:
        return SETTLE_S
    if handle.changed_at is None:
        return 0.0
    elapsed = (time.monotonic() if now is None else now) - handle.changed_at
    return max(0.0, SETTLE_S - elapsed)


def settled_close(port: DocumentsPort) -> Callable[[Any], bool]:
    # For a document a failing op made: it is in front and has just changed.
    return functools.partial(port.close, settle_s=SETTLE_S)
