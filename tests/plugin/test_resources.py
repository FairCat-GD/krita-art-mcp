import hashlib
import xml.etree.ElementTree as ElementTree
from typing import Any

import pytest
from bridge_core import resources
from bridge_core.errors import BridgeError
from bridge_core.jobs import Call
from fake_krita import PRESET_XML, FakeResources

A: dict[str, Any] = {"pid": 101, "started_at": "Sat Oct 24 10:00:00 2026"}


def _list(port: FakeResources, kind: str, cursor: Any = None, limit: Any = 100) -> Any:
    op = resources.handlers(port)["resource.list"]
    return op({"kind": kind, "cursor": cursor, "limit": limit}, Call("op-x", "req-x", A))


def test_brushes_carry_their_file_name_engine_and_fingerprint() -> None:
    found = _list(FakeResources(), "brush")
    assert (found["kind"], found["total"], found["next_cursor"]) == ("brush", 3, None)
    by_id = {entry["id"]: entry for entry in found["resources"]}
    assert list(by_id) == ["airbrush-soft.kpp", "basic-round.kpp", "broken.kpp"]
    basic = by_id["basic-round.kpp"]
    canonical = ElementTree.canonicalize(PRESET_XML)
    assert basic == {
        "id": "basic-round.kpp",
        "name": "Basic Round",
        "engine": "paintbrush",
        "sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    }
    # A preset Krita cannot write out has no fingerprint, and spoils nothing else.
    assert (by_id["broken.kpp"]["engine"], by_id["broken.kpp"]["sha256"]) == (None, None)
    assert by_id["airbrush-soft.kpp"]["engine"] == "airbrush"


def test_the_fingerprint_ignores_the_order_qt_writes_attributes_in() -> None:
    reordered = (
        '<Preset name="Basic Round" paintopid="paintbrush">'
        '<param name="EraserMode" type="string">false</param></Preset>'
    )
    assert resources.fingerprint(reordered) == resources.fingerprint(PRESET_XML)
    changed = PRESET_XML.replace("false", "true")
    assert resources.fingerprint(changed)[1] != resources.fingerprint(PRESET_XML)[1]
    assert resources.fingerprint("") == (None, None)
    assert resources.fingerprint("<Preset") == (None, None)


def test_only_the_page_is_fingerprinted() -> None:
    port = FakeResources()
    _list(port, "brush", limit=1)
    assert port.asked == [["Soft Airbrush"]]


def test_pages_follow_the_cursor_to_the_end() -> None:
    port = FakeResources()
    first = _list(port, "brush", limit=2)
    assert first["next_cursor"] == "2" and len(first["resources"]) == 2
    last = _list(port, "brush", first["next_cursor"], 2)
    assert last["next_cursor"] is None and [entry["id"] for entry in last["resources"]] == [
        "broken.kpp"
    ]
    # A total that is a whole number of pages ends without an empty page.
    port.preset_list = port.preset_list[:2]
    assert _list(port, "brush", limit=2)["next_cursor"] is None
    port.preset_list = []
    assert _list(port, "brush")["resources"] == []


@pytest.mark.parametrize(
    ("kind", "cursor", "limit"),
    [
        ("brush", "3", 2),
        ("brush", "01", 2),
        ("brush", "-1", 2),
        ("brush", 2, 2),
        ("brush", None, 0),
        ("brush", None, 101),
        ("brush", None, True),
        ("pattern", None, 2),
        (["brush"], None, 2),
    ],
)
def test_a_cursor_or_limit_the_op_never_issued_is_refused(
    kind: str, cursor: Any, limit: Any
) -> None:
    with pytest.raises(BridgeError) as refused:
        _list(FakeResources(), kind, cursor, limit)
    assert refused.value.body["code"] == "INVALID_ARGUMENT"


def test_blend_modes_are_the_whitelist_and_profiles_and_palettes_what_krita_reports() -> None:
    port = FakeResources()
    modes = [entry["id"] for entry in _list(port, "blend_mode")["resources"]]
    assert sorted(modes) == sorted(mode for mode, _ in resources.BLEND_MODES)
    assert set(modes) == {
        "normal",
        "multiply",
        "screen",
        "overlay",
        "soft_light_svg",
        "darken",
        "lighten",
        "color",
        "luminize",
        "behind",
    }
    profiles = _list(port, "profile")["resources"]
    assert [entry["id"] for entry in profiles] == ["sRGB built-in", "sRGB-elle-V2-srgbtrc.icc"]
    assert _list(port, "palette")["resources"] == [
        {"id": "default.kpl", "name": "Default", "engine": None, "sha256": None}
    ]
