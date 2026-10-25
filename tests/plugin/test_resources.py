import hashlib
import xml.etree.ElementTree as ElementTree
from typing import Any

import pytest
from bridge_core import resources
from bridge_core.errors import BridgeError
from bridge_core.jobs import Call
from fake_krita import PRESET_XML, FakeResources, preset_xml

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
    root = ElementTree.fromstring(PRESET_XML)
    tip = next(param for param in root if param.get("name") == "brush_definition")
    tip.text = ElementTree.canonicalize(tip.text or "")
    canonical = ElementTree.canonicalize(ElementTree.tostring(root, encoding="unicode"))
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
    reordered = PRESET_XML.replace(
        '<Preset paintopid="paintbrush" name="Basic Round">',
        '<Preset name="Basic Round" paintopid="paintbrush">',
    ).replace('type="string" name="PressureScatter"', 'name="PressureScatter" type="string"')
    assert reordered != PRESET_XML
    assert resources.fingerprint(reordered) == resources.fingerprint(PRESET_XML)
    changed = PRESET_XML.replace("false", "true")
    assert resources.fingerprint(changed)[1] != resources.fingerprint(PRESET_XML)[1]
    assert resources.fingerprint("") == (None, None)
    assert resources.fingerprint("<Preset") == (None, None)


def test_the_fingerprint_leaves_out_what_every_stroke_sets() -> None:
    # A stroke writes opacity, flow, blend, eraser and the tip's size into the active preset.
    tip = (
        '<Brush type="auto_brush" spacing="0.1">'
        '<MaskGenerator type="circle" diameter="40"/></Brush>'
    )
    asked = preset_xml("Round", brush=tip)
    painted = preset_xml("Round", brush=tip.replace('diameter="40"', 'diameter="12"'))
    extras = (
        '<param type="string" name="OpacityValue">0.5</param>'
        '<param type="string" name="FlowValue">1</param>'
        '<param type="string" name="CompositeOp">multiply</param>'
        '<param type="string" name="EraserMode">true</param>'
    )
    painted = painted.replace("</Preset>", extras + "</Preset>")
    assert resources.fingerprint(painted) == resources.fingerprint(asked)
    # Krita writes the rotation into the tip, and lays the tip out anew once it holds it.
    turned = tip.replace("<MaskGenerator", '\n <MaskGenerator angle="30"').replace(
        "/></Brush>", "/>\n</Brush>\n"
    )
    assert resources.fingerprint(preset_xml("Round", brush=turned)) == resources.fingerprint(asked)

    def image(scale: str, spacing: str = "0.1") -> str:
        return preset_xml(
            "Image", brush=f'<Brush type="png_brush" scale="{scale}" spacing="{spacing}"/>'
        )

    assert resources.fingerprint(image("0.5")) == resources.fingerprint(image("2"))
    # Krita fills in an image tip's defaults when it first loads it; any other value counts.
    filled = preset_xml(
        "Image",
        brush='<Brush type="png_brush" scale="2" spacing="0.1" ColorAsMask="1" md5sum="ab"'
        ' AdjustmentMidPoint="127" ContrastAdjustment="0"/>',
    )
    assert resources.fingerprint(filled) == resources.fingerprint(image("2"))
    contrast = filled.replace(
        "ContrastAdjustment=&quot;0&quot;", "ContrastAdjustment=&quot;0.5&quot;"
    )
    assert contrast != filled
    assert resources.fingerprint(contrast)[1] != resources.fingerprint(image("2"))[1]
    # Anything else in the tip, or any other setting, still moves it.
    assert resources.fingerprint(image("2", "0.3"))[1] != resources.fingerprint(image("2"))[1]
    other = asked.replace(
        "</Preset>", '<param type="string" name="RatioValue">0.5</param></Preset>'
    )
    assert resources.fingerprint(other)[1] != resources.fingerprint(asked)[1]


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
