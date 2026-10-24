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
from fake_krita import FakePort

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

    def open(self, folder: Path) -> str:
        source = folder / "fixture.ora"
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
    assert world.port.prepared[-1] == 1


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
