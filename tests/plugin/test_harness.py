import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest
from bridge_core import documents, harness
from bridge_core.errors import BridgeError
from bridge_core.jobs import Call
from bridge_core.registry import Registry
from fake_krita import FakePort, layer_id

A: dict[str, Any] = {"pid": 101, "started_at": "Sat Oct 24 10:00:00 2026"}
PROBE: dict[str, Any] = {"pid": 303, "started_at": "Sat Oct 24 10:10:00 2026"}


class World:
    def __init__(self, tmp: Path) -> None:
        self.data = tmp / "data"
        self.harness = self.data / "harness"
        self.art = tmp / "art"
        self.harness.mkdir(parents=True)
        self.art.mkdir()
        roots = {"v": 1, "roots": [os.path.realpath(self.art)]}
        (self.data / "config.json").write_text(json.dumps(roots))
        self.port = FakePort()
        self.registry = Registry(self.port, lambda client: True)
        self.ops = {
            **documents.handlers(self.registry, self.port, self.data),
            **harness.handlers(self.registry, self.port, self.data),
        }

    def run(self, op: str, args: dict[str, Any], client: dict[str, Any] = A) -> dict[str, Any]:
        return self.ops[op](args, Call("op-x", "req-x", client))

    def open(self, folder: Path, name: str = "fixture.ora") -> str:
        source = folder / name
        source.write_bytes(b"ora")
        args = {
            "source_path": str(source),
            "source_sha256": hashlib.sha256(b"ora").hexdigest(),
            "mode": "read_only",
            "working_dir": None,
            "editable_layer_ids": None,
            "editable_layer_names": None,
        }
        return str(self.run("document.open", args)["document_id"])

    def export(self, document_id: str, target: Path, client: dict[str, Any] = PROBE) -> Any:
        args = {"document_id": document_id, "target_path": str(target)}
        return self.run("harness.export_kra", args, client)

    def code(self, document_id: str, target: Path) -> str:
        with pytest.raises(BridgeError) as refused:
            self.export(document_id, target)
        return str(refused.value.body["code"])


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


def test_a_harness_document_is_exported_as_a_kra_by_another_process(world: World) -> None:
    document_id = world.open(world.harness)
    target = world.harness / "fixture.kra"
    # The probe's own client: an export changes nothing in the document, so takes no lease.
    exported = world.export(document_id, target)
    assert exported == {
        "target_path": str(target),
        "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
    }
    assert world.port.calls == []


def test_an_export_makes_a_layer_active_in_place_of_a_selection_mask(world: World) -> None:
    # K46: exportImage saves the live image, overlay and all, from the document in front.
    document_id = world.open(world.harness)
    world.port.mask(1)
    world.open(world.harness, "other.ora")
    world.export(document_id, world.harness / "fixture.kra")
    assert not world.port.is_masked(1)
    assert world.port.calls == ["forward", "activate", "restore"] and world.port.front_key == 2


def test_the_folder_gate_refuses_anything_outside_the_harness(world: World) -> None:
    inside = world.open(world.harness)
    outside = world.open(world.art)
    assert world.code(outside, world.harness / "x.kra") == "PATH_NOT_ALLOWED"
    assert world.code(inside, world.art / "x.kra") == "PATH_NOT_ALLOWED"
    assert world.code(inside, world.harness / ".." / "x.kra") == "PATH_NOT_ALLOWED"
    assert not (world.art / "x.kra").exists() and not (world.data / "x.kra").exists()


def test_an_owners_document_is_never_a_fixture(world: World) -> None:
    world.port.open_by_hand("their painting")
    [owners] = world.run("document.list", {})["documents"]
    assert world.code(owners["document_id"], world.harness / "x.kra") == "PATH_NOT_ALLOWED"


def test_the_export_never_overwrites_and_writes_only_kra(world: World) -> None:
    document_id = world.open(world.harness)
    taken = world.harness / "taken.kra"
    taken.write_bytes(b"earlier")
    assert world.code(document_id, taken) == "FILE_EXISTS"
    assert taken.read_bytes() == b"earlier"
    assert world.code(document_id, world.harness / "x.ora") == "INVALID_ARGUMENT"


def test_an_export_krita_refuses_is_busy_and_retryable(world: World) -> None:
    document_id = world.open(world.harness)
    world.port.export_works = False
    with pytest.raises(BridgeError) as refused:
        world.export(document_id, world.harness / "x.kra")
    assert refused.value.body["code"] == "BUSY" and refused.value.body["retryable"]


def _mask(world: World, document_id: str, layer: str = "") -> Any:
    args = {
        "document_id": document_id,
        "layer_id": layer or layer_id(1, 0),
        "rect": {"x": 1, "y": 1, "width": 2, "height": 2},
    }
    # The probe's own client: a fixture op takes no lease.
    return world.run("harness.select_mask", args, PROBE)


def test_select_mask_makes_an_active_mask_and_says_whether_its_overlay_shows(
    world: World,
) -> None:
    document_id = world.open(world.harness)
    assert _mask(world, document_id) == {"document_id": document_id, "overlay_seen": True}
    assert world.port.is_masked(1)
    world.port.overlay = False
    assert _mask(world, document_id)["overlay_seen"] is False


def test_select_mask_takes_only_a_harness_document_in_front(world: World) -> None:
    inside = world.open(world.harness)
    outside = world.open(world.art)
    with pytest.raises(BridgeError) as refused:
        _mask(world, outside)
    assert refused.value.body["code"] == "PATH_NOT_ALLOWED"
    # The second open came to the front; setActiveNode would do nothing for the first.
    with pytest.raises(BridgeError) as refused:
        _mask(world, inside)
    assert refused.value.body["code"] == "INVALID_ARGUMENT"
    assert not world.port.is_masked(1)


def test_front_document_names_only_a_harness_document(world: World) -> None:
    inside = world.open(world.harness)
    assert world.run("harness.front_document", {}) == {"document_id": inside}
    world.open(world.art)
    assert world.run("harness.front_document", {}) == {"document_id": None}
    world.port.open_by_hand("their painting")
    assert world.run("harness.front_document", {}) == {"document_id": None}
