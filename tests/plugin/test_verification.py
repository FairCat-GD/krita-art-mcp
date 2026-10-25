from pathlib import Path
from typing import Any

import pytest
from bridge_core import transfer, verification
from bridge_core.errors import BridgeError
from bridge_core.registry import Handle
from bridge_core.verification import Reading
from fake_krita import FakeDocument, FakePort, fake_node, layer_id

RECT = {"x": 0, "y": 0, "width": 4, "height": 2}
NONE: dict[str, Any] = {"styled": [], "clones": {}, "animated": False}


def _pixels(*values: tuple[int, int, int, int]) -> bytes:
    return b"".join(bytes(value) for value in values)


def _reading(composite: bytes, rect: dict[str, int] = RECT, **extra: Any) -> Reading:
    return Reading(rect, memoryview(composite), **extra)


BLUE = (200, 10, 10, 255)
BEFORE = _pixels(*[BLUE] * 8)


def _changed(*indices: int, value: tuple[int, int, int, int] = (1, 10, 10, 255)) -> bytes:
    pixels = [BLUE] * 8
    for index in indices:
        pixels[index] = value
    return _pixels(*pixels)


# The checks.


def test_changes_are_counted_and_bounded_with_nothing_to_leak_without_a_mask() -> None:
    verdict = verification.check(_reading(BEFORE), _reading(_changed(1, 6)), None, False)
    assert (verdict.changed_px, verdict.changed_outside_px, verdict.alpha_changed_px) == (2, 0, 0)
    assert verdict.changed_bounds_px == {"x": 1, "y": 0, "width": 2, "height": 2}
    assert not verdict.leaked
    assert list(verdict.flags) == [0, 1, 0, 0, 0, 0, 1, 0]


def test_a_change_where_the_mask_is_0_leaks_and_one_inside_it_does_not() -> None:
    allowed = bytes([255, 255, 0, 0] * 2)
    inside = verification.check(_reading(BEFORE), _reading(_changed(1, 5)), allowed, False)
    assert (inside.changed_px, inside.changed_outside_px, inside.leaked) == (2, 0, False)
    outside = verification.check(_reading(BEFORE), _reading(_changed(1, 3)), allowed, False)
    assert (outside.changed_px, outside.changed_outside_px, outside.leaked) == (2, 1, True)
    assert list(outside.flags) == [0, 1, 2, 3, 0, 0, 2, 2]


def test_an_alpha_change_leaks_only_under_preserve_composite_alpha() -> None:
    after = _reading(_changed(4, value=(200, 10, 10, 128)))
    kept = verification.check(_reading(BEFORE), after, None, False)
    assert (kept.alpha_changed_px, kept.leaked) == (1, False)
    preserved = verification.check(_reading(BEFORE), after, None, True)
    assert (preserved.alpha_changed_px, preserved.leaked) == (1, True)
    assert preserved.flags[4] == verification.CHANGED | verification.ALPHA
    # Colour alone never trips it.
    colour = verification.check(_reading(BEFORE), _reading(_changed(4)), None, True)
    assert (colour.alpha_changed_px, colour.leaked) == (0, False)


def test_bands_give_the_same_verdict_as_one_buffer(monkeypatch: pytest.MonkeyPatch) -> None:
    # Every pixel differs from the others, so a band read from the wrong place shows.
    before = _pixels(*[(200, 10, index, 255) for index in range(8)])
    changed = [(200, 10, index, 255) for index in range(8)]
    for index in (0, 3, 6):
        changed[index] = (200, 10, 100 + index, 0)
    after = _reading(_pixels(*changed))
    allowed = bytes([255, 0, 255, 0] * 2)
    whole = verification.check(_reading(before), after, allowed, True)
    monkeypatch.setattr(verification, "BAND_PIXELS", 3)
    banded = verification.check(_reading(before), after, allowed, True)
    assert banded.flags == whole.flags and banded.counts() == whole.counts()
    assert whole.counts() == {
        "changed_px": 3,
        "changed_outside_px": 1,
        "alpha_changed_px": 3,
        "changed_bounds_px": {"x": 0, "y": 0, "width": 4, "height": 2},
    }


def test_a_protected_layer_whose_hash_moved_is_named_and_leaks() -> None:
    before = _reading(BEFORE, hashes={"a": "1", "b": "2"})
    after = _reading(BEFORE, hashes={"a": "1", "b": "3"})
    verdict = verification.check(before, after, None, False)
    assert verdict.protected_changed == ["b"] and verdict.changed_px == 0 and verdict.leaked


def test_an_empty_scope_finds_nothing() -> None:
    empty = {"x": 0, "y": 0, "width": 0, "height": 0}
    verdict = verification.check(_reading(b"", empty), _reading(b"", empty), None, True)
    assert verdict.counts()["changed_px"] == 0 and verdict.changed_bounds_px is None
    assert not verdict.leaked


def test_same_compares_the_composite_the_target_and_the_hashes() -> None:
    base = _reading(BEFORE, target=memoryview(b"t"), hashes={"a": "1"})
    assert verification.same(base, _reading(BEFORE, target=memoryview(b"t"), hashes={"a": "1"}))
    assert not verification.same(base, _reading(_changed(2), target=b"t", hashes={"a": "1"}))
    assert not verification.same(base, _reading(BEFORE, target=b"u", hashes={"a": "1"}))
    assert not verification.same(base, _reading(BEFORE, target=b"t", hashes={"a": "2"}))


def test_the_allowed_rows_are_the_masks_bytes_over_the_scope() -> None:
    handle = Handle("doc-1", FakeDocument(1), True, "new")
    assert verification.allowed_rows(handle, [4, 3], RECT) is None
    handle.allowed_mask = bytes(range(12))
    rect = {"x": 1, "y": 1, "width": 2, "height": 2}
    assert verification.allowed_rows(handle, [4, 3], rect) == bytes([5, 6, 9, 10])
    with pytest.raises(BridgeError) as raised:
        verification.allowed_rows(handle, [4, 4], rect)
    assert raised.value.body["code"] == "INVALID_ARGUMENT"


# What is read.


def _document(port: FakePort) -> Any:
    document = port.create("sketch", 4, 2)
    tree = port._tree(document.key)
    tree["nodes"].append(fake_node(1, 1, "other", tree["root_id"], 1))
    port.layer_pixels = {layer_id(1, 0): bytes([1, 2, 3, 255]), layer_id(1, 1): bytes([4] * 4)}
    return document


def test_a_read_takes_the_composite_the_target_and_each_hashed_layer() -> None:
    port = FakePort()
    document = _document(port)
    found = verification.read(port, document, RECT, layer_id(1, 0), [layer_id(1, 1)])
    assert bytes(found.composite) == bytes(port.composite_rects(document, [RECT])[0])
    assert bytes(found.target or b"") == bytes([1, 2, 3, 255]) * 8
    port.layer_pixels[layer_id(1, 1)] = bytes([5] * 4)
    again = verification.read(port, document, RECT, layer_id(1, 0), [layer_id(1, 1)])
    assert again.hashes[layer_id(1, 1)] != found.hashes[layer_id(1, 1)]


def test_a_read_activates_a_layer_in_place_of_an_active_selection_mask() -> None:
    port = FakePort()
    document = _document(port)
    port.mask(document.key)
    port.calls.clear()
    verification.read(port, document, RECT)
    assert port.calls.index("activate") < port.calls.index("read")
    assert not port.is_masked(document.key)


def test_an_empty_scope_reads_nothing() -> None:
    port = FakePort()
    document = _document(port)
    port.calls.clear()
    found = verification.read(port, document, {"x": 0, "y": 0, "width": 0, "height": 0})
    assert port.calls == [] and bytes(found.composite) == b""


# The scope, and what can carry a change past it.


def _node(index: int, parent: str, order: int, **changes: Any) -> dict[str, Any]:
    node: dict[str, Any] = fake_node(1, index, f"n{index}", parent, order, **changes)
    return node


def _tree(*nodes: dict[str, Any]) -> dict[str, Any]:
    return {"root_id": "root-1", "active_id": None, "nodes": list(nodes)}


def _box(x: int, y: int, width: int, height: int) -> dict[str, int]:
    return {"x": x, "y": y, "width": width, "height": height}


def test_region_is_the_union_of_the_target_and_its_descendants_clipped() -> None:
    group = _node(1, "root-1", 0, type="grouplayer", bounds_px=_box(0, 0, 0, 0))
    inner = _node(2, group["id"], 0, bounds_px=_box(-2, 1, 4, 2))
    deep = _node(3, group["id"], 1, bounds_px=_box(5, 2, 10, 1))
    other = _node(4, "root-1", 1, bounds_px=_box(0, 0, 9, 9))
    tree = _tree(group, inner, deep, other)
    assert verification.scope("region", tree, group["id"], [8, 4]) == _box(0, 1, 8, 2)
    assert verification.scope("region", tree, inner["id"], [8, 4]) == _box(0, 1, 2, 2)
    assert verification.scope("full", tree, inner["id"], [8, 4]) == _box(0, 0, 8, 4)
    empty = _node(5, "root-1", 2)
    assert verification.scope("region", _tree(empty), empty["id"], [8, 4]) == _box(0, 0, 0, 0)
    off = _node(6, "root-1", 3, bounds_px=_box(9, 0, 2, 2))
    assert verification.scope("region", _tree(off), off["id"], [8, 4]) == _box(0, 0, 0, 0)


def _reasons(tree: dict[str, Any], target: str, effects: Any = None) -> list[tuple[str, str]]:
    found = verification.reach(tree, effects or NONE, target)
    return [(entry["reason"], entry["node_id"]) for entry in found]


def test_a_plain_stack_bounds_the_change() -> None:
    below = _node(1, "root-1", 0)
    target = _node(2, "root-1", 1)
    above = _node(3, "root-1", 2)
    local = _node(4, target["id"], 0, type="transparencymask")
    assert _reasons(_tree(below, target, above, local), target["id"]) == []


@pytest.mark.parametrize(
    ("kind", "reason"),
    [
        ("filtermask", "filter_mask"),
        ("transformmask", "transform_mask"),
        ("colorizemask", "colorize_mask"),
    ],
)
def test_a_spreading_mask_on_the_target_or_an_ancestor_is_named(kind: str, reason: str) -> None:
    group = _node(1, "root-1", 0, type="grouplayer")
    target = _node(2, group["id"], 0)
    on_target = _node(3, target["id"], 0, type=kind)
    assert _reasons(_tree(group, target, on_target), target["id"]) == [(reason, on_target["id"])]
    on_group = _node(4, group["id"], 1, type=kind)
    assert _reasons(_tree(group, target, on_group), target["id"]) == [(reason, on_group["id"])]


def test_inside_a_group_target_a_filter_or_a_derived_layer_is_named() -> None:
    group = _node(1, "root-1", 0, type="grouplayer")
    filtered = _node(2, group["id"], 0, type="filterlayer")
    clone = _node(3, group["id"], 1, type="clonelayer")
    found = _reasons(_tree(group, filtered, clone), group["id"])
    assert ("filter_layer", filtered["id"]) in found and ("layer_type", clone["id"]) in found


def test_a_target_whose_bounds_are_derived_is_named() -> None:
    fill = _node(1, "root-1", 0, type="filllayer")
    assert _reasons(_tree(fill), fill["id"]) == [("layer_type", fill["id"])]


def test_a_layer_style_on_the_target_or_an_ancestor_is_named_one_above_is_not() -> None:
    group = _node(1, "root-1", 0, type="grouplayer")
    target = _node(2, group["id"], 0)
    above = _node(3, group["id"], 1)
    tree = _tree(group, target, above)
    for styled in (target, group):
        effects = {**NONE, "styled": [styled["id"]]}
        assert _reasons(tree, target["id"], effects) == [("layer_style", styled["id"])]
    assert _reasons(tree, target["id"], {**NONE, "styled": [above["id"]]}) == []


@pytest.mark.parametrize("mode", sorted(verification.SPREADING_BLENDS))
def test_a_blend_that_composites_past_the_extent_is_named_in_the_target(mode: str) -> None:
    target = _node(1, "root-1", 0, blend_mode=mode)
    assert _reasons(_tree(target), target["id"]) == [("blend_mode", target["id"])]
    group = _node(2, "root-1", 1, type="grouplayer")
    inner = _node(3, group["id"], 0, blend_mode=mode)
    assert _reasons(_tree(group, inner), group["id"]) == [("blend_mode", inner["id"])]


def test_per_pixel_blends_masks_and_ancestors_blends_bound_the_change() -> None:
    group = _node(1, "root-1", 0, type="grouplayer", blend_mode="destination-in")
    target = _node(2, group["id"], 0, blend_mode="hard_light")
    mask = _node(3, target["id"], 0, type="transparencymask", blend_mode="copy")
    assert _reasons(_tree(group, target, mask), target["id"]) == []


def test_a_filter_layer_above_the_target_or_an_ancestor_is_named_one_below_is_not() -> None:
    below = _node(1, "root-1", 0, type="filterlayer")
    group = _node(2, "root-1", 1, type="grouplayer")
    target = _node(3, group["id"], 0)
    assert _reasons(_tree(below, group, target), target["id"]) == []
    sibling = _node(4, group["id"], 1, type="filterlayer")
    assert _reasons(_tree(group, target, sibling), target["id"]) == [
        ("filter_layer", sibling["id"])
    ]
    passing = _node(5, "root-1", 2, type="grouplayer")
    nested = _node(6, passing["id"], 0, type="filterlayer")
    assert _reasons(_tree(group, target, passing, nested), target["id"]) == [
        ("filter_layer", nested["id"])
    ]


def test_a_clone_of_the_target_an_ancestor_or_an_unknown_source_is_named() -> None:
    group = _node(1, "root-1", 0, type="grouplayer")
    target = _node(2, group["id"], 0)
    other = _node(3, "root-1", 1)
    tree = _tree(group, target, other)
    for source in (target["id"], group["id"], None):
        effects = {**NONE, "clones": {"clone-1": source}}
        assert _reasons(tree, target["id"], effects) == [("clone_layer", "clone-1")]
    assert _reasons(tree, target["id"], {**NONE, "clones": {"clone-1": other["id"]}}) == []


def test_every_reason_is_listed_once() -> None:
    target = _node(1, "root-1", 0, blend_mode="copy")
    mask = _node(2, target["id"], 0, type="filtermask")
    above = _node(3, "root-1", 1, type="filterlayer")
    effects = {"styled": [target["id"]], "clones": {"c": target["id"]}, "animated": False}
    found = _reasons(_tree(target, mask, above), target["id"], effects)
    assert sorted(found) == sorted(
        [
            ("filter_mask", mask["id"]),
            ("layer_style", target["id"]),
            ("blend_mode", target["id"]),
            ("filter_layer", above["id"]),
            ("clone_layer", "c"),
        ]
    )


def test_what_the_reads_cannot_see_is_refused() -> None:
    still = {"animated": False, "current_time": 0}
    verification.refuse_unverifiable(still, NONE, RECT)
    for info, effects, rect in (
        (still, {**NONE, "animated": True}, RECT),
        ({"animated": True, "current_time": 3}, NONE, RECT),
        (still, NONE, _box(0, 0, 8193, 8192)),
    ):
        with pytest.raises(BridgeError) as raised:
            verification.refuse_unverifiable(info, effects, rect)
        assert raised.value.body["code"] == "UNSUPPORTED_CAPABILITY"


# The files.


def _verdict(failed: bool) -> verification.Verdict:
    after = _changed(3) if failed else _changed(1)
    allowed = bytes([255, 255, 0, 0] * 2)
    return verification.check(_reading(BEFORE), _reading(after), allowed, False)


def test_a_change_sends_before_and_after_and_a_refusal_before_and_the_flags(
    tmp_path: Path,
) -> None:
    passed = verification.files(
        tmp_path, "region", _reading(BEFORE), _reading(_changed(1)), _verdict(False), False
    )
    assert passed["after"] is not None and passed["diff"] is None
    assert Path(passed["before"]["path"]).read_bytes() == BEFORE
    assert passed["changed_px"] == 1 and passed["preserve_composite_alpha"] is False
    refused = verification.files(tmp_path, "region", _reading(BEFORE), None, _verdict(True), True)
    assert refused["after"] is None and refused["before"] is not None
    assert refused["diff"]["format"] == "A8"
    assert Path(refused["diff"]["path"]).read_bytes() == _verdict(True).flags


def test_a_scope_over_the_image_bound_sends_no_images(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(verification, "MAX_IMAGE_PIXELS", 7)
    passed = verification.files(
        tmp_path, "full", _reading(BEFORE), _reading(_changed(1)), _verdict(False), False
    )
    assert (passed["before"], passed["after"], passed["changed_px"]) == (None, None, 1)
    refused = verification.files(tmp_path, "full", _reading(BEFORE), None, _verdict(True), True)
    assert refused["before"] is None and refused["diff"] is not None


def test_a_file_that_cannot_be_written_is_left_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*args: Any, **kwargs: Any) -> Any:
        raise BridgeError("IO_ERROR", "the disk is full")

    monkeypatch.setattr(transfer, "write", broken)
    passed = verification.files(
        tmp_path, "region", _reading(BEFORE), _reading(_changed(1)), _verdict(False), False
    )
    assert (passed["before"], passed["after"], passed["changed_px"]) == (None, None, 1)
