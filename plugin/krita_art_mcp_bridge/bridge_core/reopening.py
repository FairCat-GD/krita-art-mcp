import functools
from collections.abc import Callable
from typing import Any, TypeVar

from .errors import UNCERTAIN, BridgeError, cleaned
from .port import DocumentsPort
from .registry import READ_ONLY, Registry

T = TypeVar("T")


def read_file(
    registry: Registry,
    port: DocumentsPort,
    path: str,
    client: dict[str, Any],
    read: Callable[[Any], T],
    kept_message: str,
) -> T:
    # Opens a file a second time without a view, reads it and closes it, all inside one job. A
    # file Krita keeps open is registered owned, read-only and unsafe, and the job fails naming it.
    document = port.open(path)
    # Never in front, so Krita's layer docker owes it no update.
    close = functools.partial(port.close, settle_s=0.0)
    try:
        found = read(document)
    except BaseException as raised:
        kept = registry.discard(document, close, READ_ONLY, client)
        if kept is not None:
            cleaned(raised, False)
            if isinstance(raised, BridgeError):
                raised.body["details"].update(left_open=kept, outcome=UNCERTAIN)
        raise
    kept = registry.discard(document, close, READ_ONLY, client)
    if kept is not None:
        details = {"document_id": kept, "outcome": UNCERTAIN, "rollback_verified": False}
        raise BridgeError("INTERNAL_ERROR", kept_message, False, details)
    return found
