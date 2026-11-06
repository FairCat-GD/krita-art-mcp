import math
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from typing import Any

import pytest
from bridge_core import dynamics
from bridge_core.errors import BridgeError
from bridge_core.resources import fingerprint
from fake_krita import FILL_PRESET, PRESET_XML, preset_xml
from paint_world import PAINT, World, box, fill_args

NAME = "Basic Round"
SHA = fingerprint(PRESET_XML)[1]
ENDS = [{"at": 0, "value": 0.2}, {"at": 0.5, "value": 1}, {"at": 1, "value": 0.2}]
TAPER = {"size": ENDS, "opacity": None}
PATH = {"start": [40, 60], "segments": [[50, 60]]}
BRUSH = {"preset_sha256": SHA, "mask": None}
# What a stroke would have painted, and where.
STROKE = box(30, 50, 30, 20)


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


def _tapered(world: World, document_id: str, **changes: Any) -> dict[str, Any]:
    brush = {"preset_sha256": SHA, **changes.pop("brush", {})}
    return world.stroke(
        document_id, brush=brush, dynamics=changes.pop("dynamics", TAPER), **changes
    )


def _refused(world: World, document_id: str, **changes: Any) -> dict[str, Any]:
    brush = {"preset_sha256": SHA, **changes.pop("brush", {})}
    taper = changes.pop("dynamics", TAPER)
    return world.stroke_refused(document_id, brush=brush, dynamics=taper, **changes)


def _params(xml: str) -> dict[str, str]:
    return {param.get("name") or "": param.text or "" for param in ElementTree.fromstring(xml)}


# The rules.


@pytest.mark.parametrize(
    ("taper", "brush", "path"),
    [
        ({"size": None, "opacity": None}, BRUSH, PATH),
        ({"size": ENDS}, BRUSH, PATH),
        ({"size": ENDS[:1], "opacity": None}, BRUSH, PATH),
        ({"size": [{"at": i / 16, "value": 1} for i in range(17)], "opacity": None}, BRUSH, PATH),
        ({"size": [{"at": 0.1, "value": 1}, {"at": 1, "value": 1}], "opacity": None}, BRUSH, PATH),
        (
            {
                "size": [{"at": 0, "value": 1}, {"at": 0.0009, "value": 1}, {"at": 1, "value": 1}],
                "opacity": None,
            },
            BRUSH,
            PATH,
        ),
        ({"size": [{"at": 0, "value": 1.2}, {"at": 1, "value": 1}], "opacity": None}, BRUSH, PATH),
        (
            {"size": [{"at": 0, "value": 1, "x": 0}, {"at": 1, "value": 1}], "opacity": None},
            BRUSH,
            PATH,
        ),
        (TAPER, {"preset_sha256": None, "mask": None}, PATH),
        (TAPER, {"preset_sha256": SHA, "mask": "reveal"}, PATH),
        (TAPER, BRUSH, {"start": [0, 0], "segments": [[0.6, 0], [0.6, 0.3]]}),
    ],
    ids=[
        "names-nothing",
        "one-option-key",
        "one-knot",
        "seventeen-knots",
        "starts-past-0",
        "knots-too-close",
        "value-past-1",
        "unknown-knot-field",
        "no-sha",
        "mask-paint",
        "under-a-pixel",
    ],
)
def test_a_taper_s_rules(taper: Any, brush: dict[str, Any], path: dict[str, Any]) -> None:
    with pytest.raises(BridgeError) as raised:
        dynamics.check(taper, brush, path)
    assert raised.value.body["code"] == "INVALID_ARGUMENT"


def test_a_taper_that_keeps_the_rules_passes() -> None:
    dynamics.check(TAPER, BRUSH, PATH)
    dynamics.check(None, {"preset_sha256": None, "mask": "hide"}, PATH)


def test_an_arc_length_follows_the_curve_and_a_line_is_exact() -> None:
    # A half circle of radius 10 from two cubics, against pi * r.
    k = 4 * (2**0.5 - 1) / 3 * 10
    half = {"start": [10, 0], "segments": [[10, k, k, 10, 0, 10], [-k, 10, -10, k, -10, 0]]}
    assert abs(dynamics.arc_length(half) - 10 * math.pi) < 0.01
    assert dynamics.arc_length({"start": [0, 0], "segments": [[3, 4], [3, 10]]}) == 11


def test_the_curve_moves_each_knot_past_the_origin_offset() -> None:
    # Krita reads the first dab at 0 and every later one offset further along (K51).
    found = dynamics.curve(ENDS, 100.0, 50.0, 150)
    assert (
        found
        == "0,0.2,is_corner;0.3333333333,0.2,is_corner;0.6666666667,1,is_corner;1,0.2,is_corner;"
    )
    # A stroke from the origin needs no first point of its own; a rounded length never passes 1.
    assert dynamics.curve(ENDS, 100.0, 0.0, 100).startswith("0,0.2,is_corner;0.5,")
    assert dynamics.curve(ENDS, 100.4, 0.0, 100).endswith("1,0.2,is_corner;")
    assert dynamics.sensor_length(100.2, 50.3) == 151


def test_the_edit_drives_each_option_by_distance_alone() -> None:
    xml = preset_xml(
        NAME,
        scatter={
            "PressureSize": "true",
            "SizeUseCurve": "true",
            "SizeSensor": (
                '<params id="sensorslist"><ChildSensor id="pressure"/>'
                '<ChildSensor id="fuzzy"/></params>'
            ),
            "SizeValue": "0.5",
            "OpacityUseCurve": "false",
            "OpacitySensor": '<params id="pressure"/>',
            "ScatterValue": "2",
        },
    )
    path = {"start": [30, 40], "segments": [[30, 60]]}
    text, applied = dynamics.edited(xml, {"size": ENDS, "opacity": ENDS}, path)
    params = _params(text)
    assert (params["PressureSize"], params["SizeUseSameCurve"], params["SizeValue"]) == (
        "true",
        "false",
        "1",
    )
    assert (params["PressureOpacity"], params["OpacityUseCurve"]) == ("true", "true")
    sensor = ElementTree.fromstring(params["SizeSensor"])
    assert (sensor.get("id"), sensor.get("length"), sensor.get("periodic")) == (
        "distance",
        "70",
        "0",
    )
    # Only the options' own params change: the tip and scatter stay as they were.
    before = _params(xml)
    assert params["brush_definition"] == before["brush_definition"]
    assert params["ScatterValue"] == before["ScatterValue"] == "2"
    assert applied == {
        "arc_length_px": 20.0,
        "origin_offset_px": 50.0,
        "sensor_length_px": 70,
        "size": ENDS,
        "opacity": ENDS,
        "replaced": {"size": ["pressure", "fuzzy"], "opacity": []},
        "raised_size_strength": 0.5,
    }
    assert dynamics.took(text, {"size": ENDS, "opacity": ENDS}, path) == []
    assert dynamics.took(xml, {"size": ENDS, "opacity": None}, path) == ["size"]


# The stroke.


def test_a_taper_edits_the_preset_for_its_stroke_and_puts_it_back(world: World) -> None:
    document_id, _ = world.document()
    done = _tapered(world, document_id)
    taper = done["effective_brush"]["dynamics"]
    assert (taper["size"], taper["opacity"], taper["sensor_length_px"]) == (ENDS, None, 82)
    assert taper["replaced"] == {"size": [], "opacity": None}
    [edit] = world.port.preset_edits
    assert ElementTree.fromstring(_params(edit)["SizeSensor"]).get("id") == "distance"
    order = [
        call for call in world.port.calls if call in ("edit_preset", "paint", "restore_preset")
    ]
    assert order == ["edit_preset", "paint", "restore_preset"]
    # Clean before, so reloaded from storage: as stored, and clean.
    assert world.resources.xmls[NAME] == world.resources.stored[NAME]
    assert world.resources.dirty[NAME] is False


def test_unsaved_changes_to_the_preset_survive_its_taper(world: World) -> None:
    document_id, _ = world.document()
    scatter = {"PressureScatter": "false", "ScatterValue": "1", "Scattering/AxisX": "true"}
    tweaked = preset_xml(NAME, scatter={**scatter, "Scattering/AxisY": "true"})
    world.resources.xmls[NAME] = world.port.preset_xml[NAME] = tweaked
    world.resources.dirty[NAME] = True
    _tapered(world, document_id, brush={"preset_sha256": fingerprint(tweaked)[1]})
    assert world.resources.xmls[NAME] == world.port.preset_xml[NAME] == tweaked
    assert world.resources.dirty[NAME] is True


def test_remember_reads_the_preset_before_its_edit_and_never_after(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    document_id, _ = world.document()
    log: list[str] = []
    for owner, name in (
        (world.resources, "preset_xml"),
        (world.port, "edit_preset"),
        (world.port, "restore_preset"),
    ):
        real = getattr(owner, name)

        def logged(*args: Any, _real: Any = real, _name: str = name) -> Any:
            log.append(_name)
            return _real(*args)

        monkeypatch.setattr(owner, name, logged)
    _tapered(world, document_id)
    # remember's read, the edit, the restore, then the restore's own check of the stored preset.
    assert log == ["preset_xml", "edit_preset", "restore_preset", "preset_xml"]


@pytest.mark.parametrize(
    ("change", "said"),
    [
        (
            {
                "brush": {
                    "preset_id": "smudge.kpp",
                    "preset_sha256": fingerprint(preset_xml("Smudge", engine="colorsmudge"))[1],
                }
            },
            {"engine": "colorsmudge"},
        ),
        ({"setting": "true"}, {"reason": "dirty_presets_setting"}),
        ({"dirty": None}, {"reason": "preset_state_unread"}),
    ],
    ids=["another-engine", "setting-changed", "dirty-unread"],
)
def test_a_taper_the_restore_could_not_vouch_for_is_refused_first(
    world: World, change: dict[str, Any], said: dict[str, str]
) -> None:
    document_id, _ = world.document()
    if "setting" in change:
        world.resources.setting = change.pop("setting")
    if "dirty" in change:
        world.resources.dirty[NAME] = change.pop("dirty")
    body = _refused(world, document_id, **change)
    assert body["code"] == "UNSUPPORTED_CAPABILITY"
    assert said.items() <= body["details"].items()
    # Before the brush is set: nothing of Krita's was touched.
    assert world.port.brush_order == [] and world.port.preset_edits == []


def test_a_preset_left_edited_makes_the_stroke_uncertain_and_is_held(world: World) -> None:
    document_id, _ = world.document()
    before = world.pixels(PAINT, STROKE)
    world.port.restore_keeps_edit = True
    body = _refused(world, document_id)
    details = body["details"]
    assert (body["code"], details["outcome"], details["preset_restored"]) == (
        "INTERNAL_ERROR",
        "uncertain",
        False,
    )
    # The paint is undone all the same, and confirmed.
    assert (details["rolled_back"], details["rollback_verified"]) == (True, True)
    assert world.pixels(PAINT, STROKE) == before
    # No stroke paints with the edited preset until it reads as before.
    held = world.stroke_refused(document_id, brush={"preset_sha256": None})
    assert (held["code"], held["details"]["reason"]) == ("RESOURCE_HASH_MISMATCH", "preset_held")
    world.port.restore_keeps_edit = False
    world.resources.xmls[NAME] = world.port.preset_xml[NAME] = world.resources.stored[NAME]
    world.stroke(document_id)


def test_a_restore_that_raises_is_uncertain_too(world: World) -> None:
    document_id, _ = world.document()
    world.port.fail["restore_preset"] = RuntimeError("Krita raised")
    body = _refused(world, document_id)
    assert (body["details"]["outcome"], body["details"]["preset_restored"]) == ("uncertain", False)


@pytest.mark.parametrize("fault", ["raises", "not-taken"])
def test_an_edit_krita_did_not_take_is_put_back_and_never_painted(
    world: World, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    document_id, _ = world.document()
    if fault == "raises":
        world.port.fail["edit_preset"] = RuntimeError("Krita raised")
    else:
        monkeypatch.setattr(world.port, "edit_preset", lambda document, xml: PRESET_XML)
    body = _refused(world, document_id)
    assert body["code"] == "INTERNAL_ERROR" and "outcome" not in body["details"]
    if fault == "not-taken":
        assert body["details"]["fields"] == ["dynamics.size"]
    assert "paint" not in world.port.calls and "restore_preset" in world.port.calls
    assert world.resources.xmls[NAME] == world.resources.stored[NAME]
    assert world.resources.dirty.get(NAME) is False


def test_a_fill_will_not_paint_with_a_preset_a_taper_left_edited(world: World) -> None:
    document_id, _ = world.document()
    file, name, xml = FILL_PRESET
    world.port.restore_keeps_edit = True
    sha = fingerprint(xml)[1]
    _refused(world, document_id, brush={"preset_id": file, "preset_sha256": sha}, verify="full")
    body = world.refused("paint.fill", fill_args(document_id))
    assert (body["code"], body["details"]["reason"]) == ("RESOURCE_HASH_MISMATCH", "preset_held")
    assert world.resources.xmls[name] != xml


def test_the_harness_reads_a_preset_s_dirty_flag_in_its_own_documents(world: World) -> None:
    document_id, _ = world.harness_document()
    world.resources.dirty[NAME] = True
    args = {"document_id": document_id, "preset_ids": ["basic-round.kpp", "missing.kpp"]}
    found = world.run("harness.preset_dirty", args)["dirty"]
    assert found == {"basic-round.kpp": True, "missing.kpp": None}
    bad = {"document_id": document_id, "preset_ids": [""]}
    assert world.refused("harness.preset_dirty", bad)["code"] == "INVALID_ARGUMENT"
    owners, _ = world.document()
    theirs = {"document_id": owners, "preset_ids": []}
    assert world.refused("harness.preset_dirty", theirs)["code"] == "PATH_NOT_ALLOWED"
