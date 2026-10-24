import hashlib
import re
import xml.etree.ElementTree as ElementTree
from collections.abc import Callable
from typing import Any

from .errors import BridgeError, exact
from .jobs import Call, Handler
from .port import ResourcesPort

LIST_FIELDS = {"kind", "cursor", "limit"}
MAX_LIMIT = 100
CURSOR = re.compile(r"^(0|[1-9][0-9]*)$")
# The blend modes paint calls will accept, as Krita's composite-op ids (K21): Krita paints an
# unknown id as normal without a word, so nothing outside this list is ever passed to it.
BLEND_MODES = (
    ("normal", "Normal"),
    ("multiply", "Multiply"),
    ("screen", "Screen"),
    ("overlay", "Overlay"),
    ("soft_light_svg", "Soft Light (SVG)"),
    ("darken", "Darken"),
    ("lighten", "Lighten"),
    ("color", "Color"),
    ("luminize", "Luminosity"),
    ("behind", "Behind"),
)


def fingerprint(xml: str) -> tuple[str | None, str | None]:
    # The engine, and the SHA-256 of the settings as canonical XML (C14N 2.0): Qt writes a
    # preset's attributes in hash order, which may differ from one Krita run to the next.
    try:
        root = ElementTree.fromstring(xml)
        canonical = ElementTree.canonicalize(xml)
    except ElementTree.ParseError:
        return None, None
    engine = root.get("paintopid") or None
    return engine, hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def handlers(port: ResourcesPort) -> dict[str, Handler]:
    def brushes() -> list[dict[str, Any]]:
        return [_entry(preset["file"], preset["name"]) for preset in port.presets()]

    def palettes() -> list[dict[str, Any]]:
        return [_entry(palette["file"], palette["name"]) for palette in port.palettes()]

    def profiles() -> list[dict[str, Any]]:
        return [_entry(name, name) for name in port.profiles("RGBA", "U8")]

    def blend_modes() -> list[dict[str, Any]]:
        return [_entry(mode, name) for mode, name in BLEND_MODES]

    listers: dict[str, Callable[[], list[dict[str, Any]]]] = {
        "brush": brushes,
        "profile": profiles,
        "palette": palettes,
        "blend_mode": blend_modes,
    }

    def list_resources(args: dict[str, Any], call: Call) -> dict[str, Any]:
        exact(args, LIST_FIELDS)
        kind, cursor, limit = args["kind"], args["cursor"], args["limit"]
        if not isinstance(kind, str) or kind not in listers:
            raise BridgeError("INVALID_ARGUMENT", f"kind is one of {', '.join(listers)}.")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_LIMIT:
            raise BridgeError("INVALID_ARGUMENT", f"limit is 1 to {MAX_LIMIT}.")
        if cursor is not None and (not isinstance(cursor, str) or not CURSOR.match(cursor)):
            raise BridgeError("INVALID_ARGUMENT", "cursor is a next_cursor this op returned.")
        entries = sorted(listers[kind](), key=lambda entry: (entry["id"], entry["name"]))
        offset = 0 if cursor is None else int(cursor)
        if offset and offset >= len(entries):
            details = {"cursor": cursor, "total": len(entries)}
            raise BridgeError("INVALID_ARGUMENT", "cursor is past the end.", False, details)
        page = entries[offset : offset + limit]
        if kind == "brush":
            # Only the page is fingerprinted: toXML runs once per preset asked for.
            xmls = port.preset_xmls([entry["name"] for entry in page])
            for entry in page:
                entry["engine"], entry["sha256"] = fingerprint(xmls.get(entry["name"], ""))
        following = offset + limit
        return {
            "kind": kind,
            "total": len(entries),
            "resources": page,
            "next_cursor": str(following) if following < len(entries) else None,
        }

    return {"resource.list": list_resources}


def _entry(resource_id: str, name: str) -> dict[str, Any]:
    return {"id": resource_id, "name": name, "engine": None, "sha256": None}
