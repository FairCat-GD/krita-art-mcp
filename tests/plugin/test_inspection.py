import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest
from bridge_core import documents, inspection
from bridge_core.errors import BridgeError
from bridge_core.jobs import Call
from bridge_core.registry import Registry
from fake_krita import FakePort, fake_node

A: dict[str, Any] = {"pid": 101, "started_at": "Sat Oct 24 10:00:00 2026"}
B: dict[str, Any] = {"pid": 202, "started_at": "Sat Oct 24 10:05:00 2026"}
CREATE = {
    "name": "sketch",
    "size_px": [64, 32],
    "color_model": "RGBA",
    "depth": "U8",
    "profile_id": documents.SRGB_PROFILE,
    "background": "transparent",
}


class World:
    def __init__(self, tmp: Path) -> None:
        self.data = tmp / "data"
        self.art = tmp / "art"
        self.art.mkdir()
        self.data.mkdir()
        roots = {"v": 1, "roots": [os.path.realpath(self.art)]}
        (self.data / "config.json").write_text(json.dumps(roots))
        self.port = FakePort()
        self.registry = Registry(self.port, lambda client: True)
        self.ops = documents.handlers(self.registry, self.port, self.data)

    def run(self, op: str, args: dict[str, Any], client: dict[str, Any] = A) -> dict[str, Any]:
        return self.ops[op](args, Call("op-x", "req-x", client))

    def inspect(self, document_id: str, frame: Any = 0, client: dict[str, Any] = A) -> Any:
        return self.run("document.inspect", {"document_id": document_id, "frame": frame}, client)

    def opened(self, **changes: Any) -> dict[str, Any]:
        source = self.art / "rim.ora"
        source.write_bytes(b"ora")
        args = {
            "source_path": str(source),
            "source_sha256": hashlib.sha256(b"ora").hexdigest(),
            "mode": "working_copy",
            "working_dir": str(self.art / "work"),
            "editable_layer_ids": None,
            "editable_layer_names": None,
            **changes,
        }
        return self.run("document.open", args)


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


def test_a_created_document_has_nothing_protected_and_no_source(world: World) -> None:
    created = world.run("document.create", CREATE)
    seen = world.inspect(created["document_id"])
    assert seen["mode"] == "new" and seen["frame"] == 0
    assert (seen["path"], seen["source_path"], seen["baseline_id"]) == (None, None, None)
    assert [layer["protected"] for layer in seen["layers"]] == [False]
    assert seen["layers"][0]["type"] == "paint" and seen["layers"][0]["opacity"] == 1.0
    assert seen["root_layer_id"] == seen["layers"][0]["parent_id"]
    assert seen["active_layer_id"] == seen["layers"][0]["id"]
    assert seen["selection"] is None
    assert seen["protection"] == {
        "allowed_change_mask": None,
        "preserve_composite_alpha": False,
        "preserve_canvas": False,
    }
    assert (seen["dirty"], seen["unsafe"]) == (False, False)


def test_an_owners_document_is_protected_whole(world: World) -> None:
    world.port.open_by_hand("their painting")
    [owners] = world.run("document.list", {})["documents"]
    seen = world.inspect(owners["document_id"])
    assert seen["mode"] == "read_only"
    assert all(layer["protected"] for layer in seen["layers"])


def test_an_opened_document_reports_its_protection_and_baseline(world: World) -> None:
    opened = world.opened(editable_layer_names=["Layer"])
    seen = world.inspect(opened["document_id"])
    assert seen["layers"] == opened["layers"]
    assert [layer["protected"] for layer in seen["layers"]] == [False]
    assert seen["baseline_id"] == opened["baseline_id"]
    assert (seen["path"], seen["source_path"]) == (opened["path"], opened["source_path"])


def test_inspect_is_a_read_that_leaves_the_view_alone(world: World) -> None:
    opened = world.opened()
    calls = list(world.port.calls)
    # Another server process reads freely; only writers need the lease.
    assert world.inspect(opened["document_id"], client=B)["mode"] == "working_copy"
    assert world.port.calls == calls


def test_krita_types_are_reported_in_the_contracts_words() -> None:
    nodes = [
        fake_node(1, 0, "group", "root", 0, type="grouplayer", opacity=128),
        fake_node(1, 1, "mask", "root", 1, type="selectionmask"),
        fake_node(1, 2, "refs", "root", 2, type="referenceimageslayer"),
    ]
    tree = {"root_id": "root", "active_id": None, "nodes": nodes}
    entries = inspection.layer_entries(tree, {nodes[0]["id"]}, {})
    assert [entry["type"] for entry in entries] == [
        "group",
        "selection_mask",
        "referenceimageslayer",
    ]
    assert entries[0]["opacity"] == 128 / 255
    assert [entry["protected"] for entry in entries] == [True, False, False]


@pytest.mark.parametrize(
    ("frame", "code"),
    [(1, "UNSUPPORTED_CAPABILITY"), (-1, "INVALID_ARGUMENT"), (True, "INVALID_ARGUMENT")],
)
def test_phase_1_reads_frame_0_only(world: World, frame: Any, code: str) -> None:
    created = world.run("document.create", CREATE)
    with pytest.raises(BridgeError) as refused:
        world.inspect(created["document_id"], frame)
    assert refused.value.body["code"] == code


def test_the_plugin_counts_the_selection_and_writes_no_file(world: World) -> None:
    opened = world.opened()
    key = next(iter(world.port.live))
    pixels = bytes([0, 255, 128, 0, 255, 255])
    bounds = {"x": 1, "y": 2, "width": 3, "height": 2}
    world.port.live[key]["selection"] = (bounds, pixels)
    assert world.inspect(opened["document_id"])["selection"] == {
        "bounds_px": bounds,
        "selected_pixels": 4,
        "coverage_px": (255 + 128 + 255 + 255) / 255,
    }
    assert not (world.data / "transfer").exists()


def test_an_empty_selection_counts_nothing(world: World) -> None:
    opened = world.opened()
    key = next(iter(world.port.live))
    empty = {"x": 0, "y": 0, "width": 0, "height": 0}
    world.port.live[key]["selection"] = (empty, b"")
    assert world.inspect(opened["document_id"])["selection"] == {
        "bounds_px": empty,
        "selected_pixels": 0,
        "coverage_px": 0.0,
    }


def test_a_selection_krita_reads_short_is_refused(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened = world.opened()
    key = next(iter(world.port.live))
    world.port.live[key]["selection"] = ({"x": 0, "y": 0, "width": 2, "height": 2}, bytes(4))
    monkeypatch.setattr(world.port, "selection_rect", lambda document, rect: None)
    with pytest.raises(BridgeError) as refused:
        world.inspect(opened["document_id"])
    assert refused.value.body["code"] == "INTERNAL_ERROR"
    assert refused.value.body["details"] == {"bytes": 0, "expected": 4}


def test_inspect_refuses_at_job_start_and_for_an_unknown_id(world: World) -> None:
    with pytest.raises(BridgeError) as refused:
        world.inspect("doc-000000000000")
    assert refused.value.body["code"] == "DOCUMENT_NOT_FOUND"
    created = world.run("document.create", CREATE)
    world.port.refuse = BridgeError("KRITA_MODAL_DIALOG", "a dialog", True)
    with pytest.raises(BridgeError) as refused:
        world.inspect(created["document_id"])
    assert refused.value.body["code"] == "KRITA_MODAL_DIALOG"
