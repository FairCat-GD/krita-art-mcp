import errno
import hashlib
import logging
import os
import secrets
from pathlib import Path
from typing import Any

from . import files, log, nodes, reopening, roots
from .errors import UNCERTAIN, BridgeError, cleaned, exact
from .inspection import TYPES, check_shown_frame
from .jobs import Call, Handler
from .pixels import MAX_READ_PIXELS
from .port import DocumentsPort
from .rects import union
from .registry import Handle, Registry

SAVE_FIELDS = {"document_id", "path"}
FINISH_FIELDS = {"document_id", "save_id", "merged_sha256", "merged_problem"}
FORMATS = (".kra", ".ora")
FORMATS_MESSAGE = "Phase 1 saves .kra and .ora files; PNG export arrives in Phase 4."
# The server holds equal copies.
DUPLICATE_FORMATS = (".kra",)
DUPLICATE_FORMATS_MESSAGE = (
    "A duplicate is a .kra file: only KRA keeps the layer ids protection names."
)
# Phase 1 saves only the documents it paints; the server holds an equal copy of the profiles.
SAVE_SPACE = ("RGBA", "U8")
SRGB_PROFILES = ("sRGB-elle-V2-srgbtrc.icc", "sRGB built-in")
# A KRA keeps every field tree() reads.
KRA_FIELDS = (
    "parent_id",
    "name",
    "type",
    "order",
    "visible",
    "opacity",
    "blend_mode",
    "locked",
    "alpha_locked",
    "inherit_alpha",
    "offset_px",
    "bounds_px",
    "color_model",
    "depth",
    "profile_id",
)
# What Krita's ORA exporter writes as layers: groups stay groups, the rest come back
# as paint layers. Masks are baked into their layer's pixels, and adjustment layers are dropped.
ORA_LAYERS = {"paintlayer", "grouplayer", "filllayer", "clonelayer", "filelayer", "vectorlayer"}
ORA_FIELDS = ("name", "visible", "blend_mode", "locked", "inherit_alpha")
# Layer properties ORA has no place for; a layer that had one is listed as losing it.
ORA_DROPS = ("alpha_locked",)
MAX_MISMATCHES = 20
# A file name's limit where the filesystem does not say.
NAME_MAX = 255
# Errors that mean the folder's filesystem has no hard links.
NO_LINKS = {errno.EPERM, errno.ENOTSUP, errno.EOPNOTSUPP, errno.EMLINK, errno.EXDEV}


class Inherited:
    # What a duplicate's branch takes from its source, read in the job that wrote its file.
    def __init__(self, handle: Handle, size_px: list[int]) -> None:
        self.protected = set(handle.protected)
        # The handle's own bytes, never changed in place, so no copy is needed.
        self.allowed_mask = handle.allowed_mask
        self.preserve_composite_alpha = handle.preserve_composite_alpha
        self.preserve_canvas = handle.preserve_canvas
        self.size_px = list(size_px)


class Placed:
    # A duplicate's file in place, waiting for document.duplicate_open.
    def __init__(self, path: str, sha256: str, inherited: Inherited) -> None:
        self.path = path
        self.sha256 = sha256
        self.inherited = inherited


class Pending:
    # A save written beside its target and verified in Krita, waiting for the server's check of
    # its mergedimage.png.
    def __init__(
        self,
        save_id: str,
        written: str,
        made: list[str],
        changes: int,
        receipt: dict[str, Any],
        state: dict[str, Any],
        branch: Inherited | None = None,
    ) -> None:
        self.save_id = save_id
        self.written = written
        # The folders the save made for its path, deepest first.
        self.made = made
        # Checked again by the finish; hashed once already, so its stat is enough.
        self.stat = _stat(written)
        self.target = receipt["path"]
        self.changes = changes
        self.receipt = receipt
        # What this save compared, its composite's hash included, which becomes the handle's saved
        # state once it lands.
        self.state = state
        # A duplicate's, which leaves its source's dirt alone and opens as a document of its own.
        self.branch = branch

    def discard(self) -> bool:
        # Whatever the file holds now: its hidden name carries this save's own token. Whether
        # nothing of this save stays.
        removed = files.remove(self.written)
        folders_gone = files.unmake(self.made)
        return removed and folders_gone


def handlers(registry: Registry, port: DocumentsPort, data: Path) -> dict[str, Handler]:
    def save(handle: Handle, args: dict[str, Any], call: Call) -> dict[str, Any]:
        return write(handle, args, call, False)

    def duplicate(handle: Handle, args: dict[str, Any], call: Call) -> dict[str, Any]:
        return write(handle, args, call, True)

    def write(handle: Handle, args: dict[str, Any], call: Call, branch: bool) -> dict[str, Any]:
        formats = (
            (DUPLICATE_FORMATS, DUPLICATE_FORMATS_MESSAGE) if branch else (FORMATS, FORMATS_MESSAGE)
        )
        target, kind = _target(data, args["path"], *formats)
        info = port.describe(handle.document)
        _check_space(info)
        _check_size(info)
        check_shown_frame(info)
        call.mark()
        made = files.make_folder(os.path.dirname(target), "path's folder")
        written = _written_name(target)
        try:
            _check_writable(written, target)
            # K46: no selection mask's overlay may enter the file or the reads. The projection is
            # recomposed first: after a stroke it can differ from its layers' own composite, which
            # is what the file holds and its reopening shows.
            with nodes.unmasked_view(port, handle.document):
                port.refresh(handle.document)
                exported = port.export(handle.document, written)
            if not exported:
                message = "Krita did not export; an autosave may hold the document. Retry."
                raise BridgeError("BUSY", message, True, {"document_id": handle.document_id})
            if port.describe(handle.document)["path"] != info["path"]:
                # Removing the file cannot undo this.
                moved = {"outcome": UNCERTAIN, "rollback_verified": False}
                message = "The export moved the document to its file."
                raise BridgeError("INTERNAL_ERROR", message, False, moved)
            live = port.tree(handle.document)
            composite = _sha256(port.composite(handle.document))

            def read(document: Any) -> dict[str, Any]:
                return _reopened(port, document, kind, live)

            message = "Krita kept open the saved file read to verify it; close it with discard."
            saved = reopening.read_file(registry, port, written, call.client, read, message)
            for pair in saved["pairs"]:
                if pair["rect"] is not None:
                    # An ORA layer holds its projection, its masks applied.
                    projection = kind == ".ora"
                    pair["live_sha256"] = _pixels_sha256(
                        port, handle.document, pair["live"]["id"], pair["rect"], projection
                    )
            mismatches, losses = compare(kind, info, live, composite, saved)
            if mismatches:
                details = {
                    "document_id": handle.document_id,
                    "path": target,
                    "mismatches": mismatches[:MAX_MISMATCHES],
                    "mismatch_count": len(mismatches),
                }
                message = "The saved file, reopened in Krita, differs from the document."
                raise BridgeError("SAVE_VERIFY_FAILED", message, False, details)
            owned = _own_pixels(port, handle.document, kind, live, saved["pairs"])
            sha = files.sha256_of(written)
        except BaseException as raised:
            removed = files.remove(written)
            folders_gone = files.unmake(made)
            cleaned(raised, removed and folders_gone)
            raise
        untouched = None
        if handle.source_path is not None and handle.source_sha256 is not None:
            untouched = files.unchanged(
                handle.source_path, handle.source_sha256, handle.source_stat
            )
        receipt = {
            "document_id": handle.document_id,
            "path": target,
            "format": kind[1:],
            "sha256": sha,
            "reopened_verified": True,
            "layers_preserved": not losses,
            "composite_preserved": True,
            "baseline_untouched": untouched,
            "expected_losses": losses,
        }
        # Last, so a save that fails leaves an earlier unfinished one as it was. Its folders may
        # now hold this save's file, so they stay this save's to remove.
        earlier = handle.pending_save
        handle.drop_pending_save()
        if isinstance(earlier, Pending):
            made = made + earlier.made
        state = {"nodes": live["nodes"], "composite_sha256": composite, "pixels": owned}
        inherited = Inherited(handle, info["size_px"]) if branch else None
        handle.pending_save = Pending(
            call.operation_id, written, made, handle.changes, receipt, state, inherited
        )
        return {
            **receipt,
            "save_id": call.operation_id,
            "written": written,
            "composite_sha256": composite,
            "size_px": info["size_px"],
            # The earlier save's file went with it, so this save's failure is never nothing.
            "replaced_pending": isinstance(earlier, Pending),
        }

    def finish(handle: Handle, args: dict[str, Any], call: Call) -> dict[str, Any]:
        pending = handle.pending_save
        if not isinstance(pending, Pending) or pending.save_id != args["save_id"]:
            details = {"document_id": handle.document_id, "save_id": args["save_id"]}
            message = "No save of this document waits for that save_id."
            raise BridgeError("INVALID_ARGUMENT", message, False, details)
        call.mark()
        handle.pending_save = None
        details = {"document_id": handle.document_id, "path": pending.target}
        if _stat(pending.written) != pending.stat:
            details["rollback_verified"] = pending.discard()
            message = "The saved file changed or went before its mergedimage.png was checked."
            raise BridgeError("SAVE_VERIFY_FAILED", message, False, details)
        if (
            args["merged_problem"] is not None
            or args["merged_sha256"] != pending.state["composite_sha256"]
        ):
            details["rollback_verified"] = pending.discard()
            details["mismatches"] = [
                {
                    "field": "mergedimage",
                    "live": pending.state["composite_sha256"],
                    "saved": args["merged_sha256"],
                    "problem": args["merged_problem"],
                }
            ]
            message = "The saved file's mergedimage.png differs from the document."
            raise BridgeError("SAVE_VERIFY_FAILED", message, False, details)
        try:
            info = port.describe(handle.document)
            _place(pending.written, pending.target)
        except BaseException as raised:
            cleaned(raised, pending.discard())
            raise
        cleared = False
        if pending.branch is not None:
            # A duplicate leaves its source as it was; its file waits to open as its own document.
            target, sha = pending.target, pending.receipt["sha256"]
            handle.branches[pending.save_id] = Placed(target, sha, pending.branch)
        elif handle.changes == pending.changes:
            # A change since the save read the document keeps its dirt.
            cleared = True
            handle.dirty = False
            handle.saved_state = pending.state
        # Krita's flag stays set and the document keeps its own file (K39, K45).
        return {
            **pending.receipt,
            "dirty_cleared": cleared,
            "dirty": handle.dirty,
            "krita_modified": info["modified"],
            "document_path": info["path"],
        }

    guarded_save = registry.guarded(save)
    guarded_duplicate = registry.guarded(duplicate)
    guarded_finish = registry.guarded(finish, allow_unsafe=True, lease_retryable=True)

    def save_document(args: dict[str, Any], call: Call) -> dict[str, Any]:
        exact(args, SAVE_FIELDS)
        return guarded_save(args, call)

    def duplicate_document(args: dict[str, Any], call: Call) -> dict[str, Any]:
        exact(args, SAVE_FIELDS)
        return guarded_duplicate(args, call)

    def finish_save(args: dict[str, Any], call: Call) -> dict[str, Any]:
        exact(args, FINISH_FIELDS)
        if not isinstance(args["save_id"], str) or not all(
            value is None or isinstance(value, str)
            for value in (args["merged_sha256"], args["merged_problem"])
        ):
            message = "save_id is text, and each merged field text or null."
            raise BridgeError("INVALID_ARGUMENT", message)
        return guarded_finish(args, call)

    return {
        "document.save": save_document,
        "document.duplicate": duplicate_document,
        "document.save_finish": finish_save,
    }


def matches_saved(port: DocumentsPort, handle: Handle) -> bool:
    # Whether the live document still holds exactly what its last verified save compared. The
    # composite comes first, because its read waits for Krita.
    state = handle.saved_state
    if state is None:
        return False
    if _sha256(port.composite(handle.document)) != state["composite_sha256"]:
        return False
    if port.tree(handle.document)["nodes"] != state["nodes"]:
        return False
    return all(
        _pixels_sha256(port, handle.document, node_id, rect, False) == sha
        for node_id, rect, sha in state["pixels"]
    )


def _own_pixels(
    port: DocumentsPort,
    document: Any,
    kind: str,
    live: dict[str, Any],
    pairs: list[dict[str, Any]],
) -> list[tuple[str, dict[str, int], str]]:
    # Every node's own pixels, so the close sees a change to any of them. A KRA save hashed each
    # node already; an ORA save hashed only what ORA stores, and as projections.
    if kind == ".kra":
        return [(pair["live"]["id"], pair["rect"], pair["live_sha256"]) for pair in pairs]
    return [
        (
            node["id"],
            node["bounds_px"],
            _pixels_sha256(port, document, node["id"], node["bounds_px"], False),
        )
        for node in live["nodes"]
        if node["type"] != "grouplayer"
    ]


def _target(data: Path, path: Any, formats: tuple[str, ...], message: str) -> tuple[str, str]:
    roots.resolve(path, "path")
    kind = os.path.splitext(path)[1].lower()
    if kind not in formats:
        raise BridgeError("UNSUPPORTED_CAPABILITY", message, False, {"formats": list(formats)})
    target = roots.check(data, path, "path")
    if os.path.lexists(path) or os.path.lexists(target):
        message = "path exists; nothing is overwritten."
        raise BridgeError("FILE_EXISTS", message, False, {"path": target})
    return target, kind


def _check_writable(written: str, target: str) -> None:
    # Krita's export says only that it failed, which is BUSY; these failures it would hide.
    folder, name = os.path.split(written)
    try:
        limit = os.pathconf(folder, "PC_NAME_MAX")
    except (OSError, ValueError):
        limit = NAME_MAX
    if len(name.encode("utf-8")) > limit:
        spare = limit - (len(name.encode("utf-8")) - len(os.path.basename(target).encode("utf-8")))
        details = {"max_name_bytes": spare}
        message = f"path's file name is too long; the save needs it at most {spare} bytes."
        raise BridgeError("INVALID_ARGUMENT", message, False, details)
    if not os.access(folder, os.W_OK):
        raise BridgeError("IO_ERROR", "path's folder cannot be written.", False, {"path": target})


def _written_name(target: str) -> str:
    # Hidden beside the target, ending in its extension so Krita picks the same exporter.
    folder, name = os.path.split(target)
    stem, extension = os.path.splitext(name)
    return os.path.join(folder, f".{stem}.{secrets.token_hex(4)}.saving{extension}")


def _check_size(info: dict[str, Any]) -> None:
    # The save reads the whole canvas, live and reopened, and the server decodes it once more.
    width, height = info["size_px"]
    if width * height > MAX_READ_PIXELS:
        details = {"size_px": info["size_px"], "max_pixels": MAX_READ_PIXELS}
        message = "Phase 1 saves at most 67 megapixels (8192 x 8192)."
        raise BridgeError("UNSUPPORTED_CAPABILITY", message, False, details)


def _check_space(info: dict[str, Any]) -> None:
    space = (info["color_model"], info["depth"])
    if space != SAVE_SPACE or info["profile_id"] not in SRGB_PROFILES:
        details = {
            "color_space": [*space, info["profile_id"]],
            "supported": [*SAVE_SPACE, *SRGB_PROFILES],
        }
        message = "Phase 1 saves RGBA / U8 / sRGB documents only."
        raise BridgeError("UNSUPPORTED_CAPABILITY", message, False, details)


def _reopened(
    port: DocumentsPort, document: Any, kind: str, live: dict[str, Any]
) -> dict[str, Any]:
    # The saved file as Krita reads it back, with each matched node's pixels hashed over the
    # union of both nodes' bounds.
    info = port.describe(document)
    tree = port.tree(document)
    pairs = match(kind, live, tree)
    for pair in pairs:
        if pair["rect"] is not None:
            pair["saved_sha256"] = _pixels_sha256(
                port, document, pair["saved"]["id"], pair["rect"], False
            )
    return {
        "info": info,
        "tree": tree,
        "composite_sha256": _sha256(port.composite(document)),
        "pairs": pairs,
    }


def match(kind: str, live: dict[str, Any], saved: dict[str, Any]) -> list[dict[str, Any]]:
    # Each live node with the saved node it became: by id in a KRA, which keeps them; by place
    # among the stored siblings and name in an ORA, which keeps none.
    if kind == ".kra":
        found = {node["id"]: node for node in saved["nodes"]}
        pairs = [(node, found.get(node["id"])) for node in live["nodes"]]
    else:
        stored = _places(live, ORA_LAYERS)
        back = {place: node for node, place in _places(saved, None)}
        pairs = [(node, back.get(place)) for node, place in stored]
    return [
        {"live": node, "saved": other, "rect": _rect(kind, node, other)}
        for node, other in pairs
        if other is not None
    ]


Place = tuple[int, ...]


def _places(tree: dict[str, Any], kinds: set[str] | None) -> list[tuple[dict[str, Any], Place]]:
    # Each node a format stores, with its place: the ranks among its stored siblings, from the
    # root down. A node under one the format drops is dropped with it.
    found: list[tuple[dict[str, Any], Place]] = []

    def walk(parent_id: str, place: Place) -> None:
        children = sorted(
            (node for node in tree["nodes"] if node["parent_id"] == parent_id),
            key=lambda node: node["order"],
        )
        kept = [node for node in children if kinds is None or node["type"] in kinds]
        for rank, node in enumerate(kept):
            found.append((node, (*place, rank)))
            walk(node["id"], (*place, rank))

    walk(tree["root_id"], ())
    return found


def _rect(kind: str, live: dict[str, Any], saved: dict[str, Any]) -> dict[str, int] | None:
    # None where no pixels are compared: an ORA stores a group as its layers.
    if kind == ".ora" and live["type"] == "grouplayer":
        return None
    found = union([live["bounds_px"], saved["bounds_px"]])
    return found or {"x": 0, "y": 0, "width": 0, "height": 0}


def compare(
    kind: str,
    info: dict[str, Any],
    live: dict[str, Any],
    composite_sha256: str,
    saved: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    # The mismatches, which fail the save, and the losses the format explains. A loss never
    # excuses a composite difference.
    mismatches: list[dict[str, Any]] = []
    for field in ("size_px", "color_model", "depth", "profile_id"):
        if saved["info"][field] != info[field]:
            mismatches.append(_differs(None, field, info[field], saved["info"][field]))
    if saved["composite_sha256"] != composite_sha256:
        mismatches.append(_differs(None, "composite", composite_sha256, saved["composite_sha256"]))
    paired = {pair["live"]["id"] for pair in saved["pairs"]}
    used = {pair["saved"]["id"] for pair in saved["pairs"]}
    losses: list[dict[str, Any]] = []
    for node in live["nodes"]:
        if node["id"] in paired:
            continue
        if kind == ".ora" and _dropped_by_ora(live, node):
            losses.append(_loss(node, "node"))
        else:
            mismatches.append(_differs(node, "node", "present", None))
    for node in saved["tree"]["nodes"]:
        if node["id"] not in used:
            mismatches.append(_differs(node, "node", None, "present"))
    roots = (live["root_id"], saved["tree"]["root_id"])
    for pair in saved["pairs"]:
        before, after = pair["live"], pair["saved"]
        if kind == ".kra":
            for field in KRA_FIELDS:
                was, now = before[field], after[field]
                if field == "parent_id" and was in roots and now in roots:
                    continue
                if was != now:
                    mismatches.append(_differs(before, field, was, now))
        else:
            mismatches += _ora_fields(before, after, losses)
        if pair["rect"] is not None and pair["live_sha256"] != pair["saved_sha256"]:
            mismatches.append(_differs(before, "pixels", pair["live_sha256"], pair["saved_sha256"]))
    return mismatches, losses


def _ora_fields(
    before: dict[str, Any], after: dict[str, Any], losses: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    found = [
        _differs(before, field, before[field], after[field])
        for field in ORA_FIELDS
        if before[field] != after[field]
    ]
    rasterised = before["type"] != "grouplayer" and after["type"] == "paintlayer"
    if before["type"] != after["type"]:
        if rasterised:
            losses.append(_loss(before, "type"))
        else:
            found.append(_differs(before, "type", before["type"], after["type"]))
    if before["opacity"] != after["opacity"]:
        if after["opacity"] == ora_opacity(before["opacity"]):
            losses.append(_loss(before, "opacity"))
        else:
            found.append(_differs(before, "opacity", before["opacity"], after["opacity"]))
    for field in ORA_DROPS:
        if before[field] and not after[field]:
            losses.append(_loss(before, field))
        elif before[field] != after[field]:
            found.append(_differs(before, field, before[field], after[field]))
    return found


def ora_opacity(opacity: int) -> int:
    # Krita's ORA writer keeps six significant digits of opacity / 255 and its loader truncates,
    # so about half the values come back one lower (measured on Krita 5.3.4).
    return int(float(f"{opacity / 255:.6g}") * 255)


def _dropped_by_ora(tree: dict[str, Any], node: dict[str, Any]) -> bool:
    # A node ORA has no place for, or one inside such a node.
    by_id = {one["id"]: one for one in tree["nodes"]}
    found: dict[str, Any] | None = node
    while found is not None:
        if found["type"] not in ORA_LAYERS:
            return True
        found = by_id.get(found["parent_id"])
    return False


def _loss(node: dict[str, Any], lost: str) -> dict[str, Any]:
    return {
        "layer_id": node["id"],
        "name": node["name"],
        "type": TYPES.get(node["type"], node["type"]),
        "lost": lost,
    }


def _differs(node: dict[str, Any] | None, field: str, live: Any, saved: Any) -> dict[str, Any]:
    return {
        "layer_id": None if node is None else node["id"],
        "name": None if node is None else node["name"],
        "field": field,
        "live": live,
        "saved": saved,
    }


def _place(written: str, target: str) -> None:
    # A hard link never replaces a file, and the target appears whole; a filesystem without them
    # takes a rename, checked first within this one job. A failure leaves the file to its caller.
    try:
        os.link(written, target)
    except FileExistsError as problem:
        details = {"path": target}
        message = "path appeared while the save was checked; nothing is overwritten."
        raise BridgeError("FILE_EXISTS", message, False, details) from problem
    except OSError as problem:
        if problem.errno not in NO_LINKS:
            message = f"The saved file cannot be put in place: {problem}"
            raise BridgeError("IO_ERROR", message) from problem
        _rename(written, target)
        return
    if not files.remove(written):
        # The save is in place, so this fails nothing, and nothing else tracks the file now.
        logging.getLogger(log.NAME).warning("the save's hidden file stayed: %s", written)


def _rename(written: str, target: str) -> None:
    if os.path.lexists(target):
        details = {"path": target}
        message = "path appeared while the save was checked; nothing is overwritten."
        raise BridgeError("FILE_EXISTS", message, False, details)
    try:
        os.rename(written, target)
    except OSError as problem:
        message = f"The saved file cannot be put in place: {problem}"
        raise BridgeError("IO_ERROR", message) from problem


def _pixels_sha256(
    port: DocumentsPort, document: Any, node_id: str, rect: dict[str, int], projection: bool
) -> str:
    if rect["width"] <= 0 or rect["height"] <= 0:
        return _sha256(b"")
    return _sha256(port.node_pixels(document, node_id, rect, projection))


def _stat(path: str) -> tuple[int, int, int] | None:
    # No ctime: the finish has no hash to fall back on, so a metadata touch would fail it.
    try:
        found = os.stat(path)
    except OSError:
        return None
    return found.st_ino, found.st_size, found.st_mtime_ns


def _sha256(buffer: Any) -> str:
    return hashlib.sha256(buffer).hexdigest()
