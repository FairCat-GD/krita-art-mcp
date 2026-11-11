import xml.etree.ElementTree as ElementTree
from typing import Any

from .port import DocumentsPort

# Per axis, for one call's move and for a mask's whole translation.
MAX_TRANSLATE = 16384
TRANSFORM_MASK = "transformmask"
# A fresh transform mask's params as TransformMask.toXML writes them on Krita 5.3.4 (measured):
# the transform tool's free transform at identity. A translation sets transformedCenter alone.
PARAMS = "tooltransformparams"
MODE = "0"
CENTER = "transformedCenter"
FREE = (
    (CENTER, {"x": "0", "y": "0", "type": "pointf"}),
    ("originalCenter", {"x": "0", "y": "0", "type": "pointf"}),
    ("rotationCenterOffset", {"x": "0", "y": "0", "type": "pointf"}),
    ("transformAroundRotationCenter", {"value": "0", "type": "value"}),
    ("aX", {"value": "0", "type": "value"}),
    ("aY", {"value": "0", "type": "value"}),
    ("aZ", {"value": "0", "type": "value"}),
    ("cameraPos", {"x": "0", "y": "0", "z": "1024", "type": "vector3d"}),
    ("scaleX", {"value": "1", "type": "value"}),
    ("scaleY", {"value": "1", "type": "value"}),
    ("shearX", {"value": "0", "type": "value"}),
    ("shearY", {"value": "0", "type": "value"}),
    ("boundsRotation", {"value": "0", "type": "value"}),
    ("keepAspectRatio", {"value": "0", "type": "value"}),
    (
        "flattenedPerspectiveTransform",
        {
            "m11": "1",
            "m12": "0",
            "m13": "0",
            "m21": "0",
            "m22": "1",
            "m23": "0",
            "m31": "0",
            "m32": "0",
            "m33": "1",
            "type": "transform",
        },
    ),
    ("filterId", {"value": "Bicubic", "type": "value"}),
)


def translate_xml(x: int, y: int) -> str:
    # Krita's own attribute order varies by session, so ours is fixed and parsed back by value.
    root = ElementTree.Element("transform_params")
    ElementTree.SubElement(root, "main", {"id": PARAMS})
    data = ElementTree.SubElement(root, "data", {"mode": MODE})
    free = ElementTree.SubElement(data, "free_transform")
    for tag, attributes in FREE:
        values = {**attributes, "x": str(x), "y": str(y)} if tag == CENTER else attributes
        ElementTree.SubElement(free, tag, values)
    return ElementTree.tostring(root, encoding="unicode")


def translation(xml: str) -> tuple[int, int] | None:
    # The whole-pixel translation a mask's params hold when they are a translate's and nothing
    # else; None for any other params.
    if "<!ENTITY" in xml:
        return None
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError:
        return None
    if root.tag != "transform_params" or _text(root) or len(root) != 2:
        return None
    main, data = root
    if (main.tag, main.attrib, len(main)) != ("main", {"id": PARAMS}, 0):
        return None
    if (data.tag, data.attrib, len(data)) != ("data", {"mode": MODE}, 1):
        return None
    [free] = list(data)
    if free.tag != "free_transform" or len(free) != len(FREE) or _text(free) or _text(data):
        return None
    found = {child.tag: child for child in free}
    if set(found) != {tag for tag, _ in FREE}:
        return None
    for tag, attributes in FREE:
        child = found[tag]
        if len(child) or _text(child):
            return None
        if tag != CENTER and not _same(child.attrib, attributes):
            return None
    center = found[CENTER].attrib
    if set(center) != {"x", "y", "type"} or center["type"] != "pointf":
        return None
    moved = (_whole(center["x"]), _whole(center["y"]))
    if moved[0] is None or moved[1] is None:
        return None
    return moved[0], moved[1]


def translations(port: DocumentsPort, document: Any, tree: dict[str, Any]) -> dict[str, Any]:
    # Each transform mask's translation as [x, y], or None for params a translate did not make.
    found: dict[str, Any] = {}
    for node in tree["nodes"]:
        if node["type"] == TRANSFORM_MASK:
            moved = translation(port.transform_xml(document, node["id"]))
            found[node["id"]] = None if moved is None else list(moved)
    return found


def _same(found: dict[str, str], expected: dict[str, str]) -> bool:
    # Numbers by value, so Krita's "-0" reads as "0".
    if set(found) != set(expected):
        return False
    for key, value in expected.items():
        number = _number(value)
        if found[key] != value and (number is None or _number(found[key]) != number):
            return False
    return True


def _number(text: str) -> float | None:
    try:
        return float(text)
    except ValueError:
        return None


def _whole(text: str) -> int | None:
    value = _number(text)
    if value is None or value != int(value) or abs(value) > MAX_TRANSLATE:
        return None
    return int(value)


def _text(element: Any) -> bool:
    return bool((element.text or "").strip() or (element.tail or "").strip())
