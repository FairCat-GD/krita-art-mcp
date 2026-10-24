import secrets
from collections.abc import Callable
from typing import Any, Protocol

from .errors import BridgeError
from .jobs import Call, Handler

NEW = "new"
WORKING_COPY = "working_copy"
READ_ONLY = "read_only"


class Port(Protocol):
    def documents(self) -> list[Any]: ...

    def refusal(self) -> BridgeError | None: ...


class Handle:
    # One open document, as every client and server process sees it (PDD Part 6).
    def __init__(self, document_id: str, document: Any, owned: bool, mode: str) -> None:
        self.document_id = document_id
        # For a document the bridge made, the only strong reference to its wrapper (K6).
        self.document = document
        self.owned = owned
        self.mode = mode
        self.dirty = False
        self.unsafe = False
        self.lease: dict[str, Any] | None = None
        # Set by an open: the file Krita shows, the accepted file and its hash, the baseline.
        self.path: str | None = None
        self.source_path: str | None = None
        self.source_sha256: str | None = None
        self.baseline_id: str | None = None
        # Ids of the layers agents may not change; an owner's document is protected whole.
        self.protected: set[str] = set()
        self.allowed_mask: dict[str, Any] | None = None
        self.preserve_composite_alpha = False
        self.preserve_canvas = False


DocumentHandler = Callable[[Handle, dict[str, Any], Call], dict[str, Any]]


def new_document_id() -> str:
    # Random, so an id held across a Krita restart never names someone else's document.
    return f"doc-{secrets.token_hex(6)}"


class Registry:
    def __init__(
        self,
        port: Port,
        holder_alive: Callable[[dict[str, Any]], bool],
        new_id: Callable[[], str] = new_document_id,
    ) -> None:
        self._port = port
        self._holder_alive = holder_alive
        self._new_id = new_id
        self._handles: list[Handle] = []

    def add(self, document: Any, mode: str, client: dict[str, Any]) -> Handle:
        handle = Handle(self._new_id(), document, True, mode)
        handle.lease = dict(client)
        self._handles.append(handle)
        return handle

    def discard(
        self, document: Any, close: Callable[[Any], bool], mode: str, client: dict[str, Any]
    ) -> str | None:
        # Closes a document a failing job made. One Krita keeps open stays registered, owned and
        # unsafe, so a discard close can still end it; its id is returned.
        try:
            closed = close(document)
        except Exception:
            closed = False
        if closed and not any(open_one == document for open_one in self._port.documents()):
            return None
        handle = self.add(document, mode, client)
        handle.unsafe = True
        return handle.document_id

    def remove(self, handle: Handle) -> None:
        self._handles = [kept for kept in self._handles if kept is not handle]

    def sync(self) -> list[Handle]:
        # Libkis wrappers compare by document but cannot be hashed, so matching is by ==.
        live = self._port.documents()
        self._handles = [h for h in self._handles if any(h.document == d for d in live)]
        ordered = []
        for document in live:
            handle = next((h for h in self._handles if h.document == document), None)
            if handle is None:
                # Opened by the owner, so agents may read it but never change it.
                handle = Handle(self._new_id(), document, False, READ_ONLY)
                self._handles.append(handle)
            ordered.append(handle)
        return ordered

    def find(self, document_id: str) -> Handle:
        for handle in self.sync():
            if handle.document_id == document_id:
                return handle
        details = {"document_id": document_id}
        raise BridgeError("DOCUMENT_NOT_FOUND", "No open document has that id.", False, details)

    def refuse_at_job_start(self) -> None:
        refusal = self._port.refusal()
        if refusal is not None:
            raise refusal

    def guarded(
        self,
        handler: DocumentHandler,
        *,
        dirties: Callable[[dict[str, Any]], bool],
        writes: bool = True,
        allow_unsafe: bool = False,
    ) -> Handler:
        # Every mutation of a document passes the same checks, in the same order.
        def run(args: dict[str, Any], call: Call) -> dict[str, Any]:
            self.refuse_at_job_start()
            handle = self.find(args["document_id"])
            if not handle.owned or (writes and handle.mode == READ_ONLY):
                details = {"document_id": handle.document_id, "mode": handle.mode}
                message = "The document is read-only to agents."
                raise BridgeError("DOCUMENT_READ_ONLY", message, False, details)
            if handle.unsafe and not allow_unsafe:
                details = {"document_id": handle.document_id}
                message = "A rollback on this document failed; reopen it."
                raise BridgeError("DOCUMENT_UNSAFE", message, False, details)
            self._lease(handle, call.client)
            result = handler(handle, args, call)
            if dirties(args):
                handle.dirty = True
            return result

        return run

    def _lease(self, handle: Handle, client: dict[str, Any]) -> None:
        holder = handle.lease
        if holder is not None and holder != client and self._holder_alive(holder):
            details = {"document_id": handle.document_id, "holder_pid": holder["pid"]}
            message = "Another server process holds this document's writer lease."
            raise BridgeError("DOCUMENT_IN_USE", message, False, details)
        handle.lease = dict(client)


def never(args: dict[str, Any]) -> bool:
    return False
