import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest
from bridge_core import documents, previews
from bridge_core.errors import BridgeError
from bridge_core.jobs import Call
from bridge_core.registry import Registry
from fake_krita import FakePort, bgra

A: dict[str, Any] = {"pid": 101, "started_at": "Sat Oct 24 10:00:00 2026"}
OWN = object()


class World:
    def __init__(self, tmp: Path) -> None:
        self.data = tmp / "data"
        self.art = tmp / "art"
        (self.art / "accepted").mkdir(parents=True)
        self.data.mkdir()
        roots = {"v": 1, "roots": [os.path.realpath(self.art)]}
        (self.data / "config.json").write_text(json.dumps(roots))
        self.port = FakePort()
        self.registry = Registry(self.port, lambda client: True)
        self.ops = documents.handlers(self.registry, self.port, self.data)

    def run(self, op: str, args: dict[str, Any]) -> dict[str, Any]:
        return self.ops[op](args, Call("op-x", "req-x", A))

    def open(self, name: str = "hero.kra") -> dict[str, Any]:
        path = self.art / "accepted" / name
        path.write_bytes(b"accepted art")
        args = {
            "source_path": str(path),
            "source_sha256": hashlib.sha256(b"accepted art").hexdigest(),
            "mode": "working_copy",
            "working_dir": str(self.art / "work"),
            "editable_layer_ids": None,
            "editable_layer_names": None,
        }
        return self.run("document.open", args)

    def preview(self, *sources: dict[str, Any]) -> dict[str, Any]:
        return self.run("preview.read", {"sources": list(sources), "render": {"echo": True}})

    def code(self, *sources: dict[str, Any]) -> str:
        with pytest.raises(BridgeError) as refused:
            self.preview(*sources)
        return str(refused.value.body["code"])

    def transfer_files(self) -> list[Path]:
        folder = self.data / "transfer"
        return sorted(folder.iterdir()) if folder.exists() else []


def _source(document_id: str, **changes: Any) -> dict[str, Any]:
    return {
        "document_id": document_id,
        "frame": 0,
        "target": "composite",
        "layer_id": None,
        "rect": None,
        "baseline_id": None,
        "read_baseline": False,
        "overlays": [],
        **changes,
    }


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


def test_a_preview_reads_each_crop_and_echoes_its_render(world: World) -> None:
    opened = world.open()
    rect = {"x": 2, "y": 1, "width": 4, "height": 2}
    read = world.preview(_source(opened["document_id"], rect=rect))
    [got] = read["sources"]
    assert read["render"] == {"echo": True}
    assert (
        got["rect"] == rect
        and got["canvas_px"] == [8, 4]
        and got["profile_id"] == (documents.SRGB_PROFILE)
    )
    assert got["baseline"] is None and got["overlays"] == {}
    canvas = bgra(8, 4)
    rows = [canvas[(row * 8 + 2) * 4 : (row * 8 + 6) * 4] for row in (1, 2)]
    assert Path(got["pixels"]["path"]).read_bytes() == b"".join(rows)


def test_the_baseline_is_read_from_the_working_copys_file_without_a_view(world: World) -> None:
    opened = world.open()
    key = max(world.port.live)
    world.port.canvas[key] = bytes(8 * 4 * 4)
    baseline = opened["baseline_id"]
    read = world.preview(_source(opened["document_id"], baseline_id=baseline, read_baseline=True))
    [got] = read["sources"]
    assert got["baseline"]["baseline_id"] == baseline
    assert Path(got["baseline"]["pixels"]["path"]).read_bytes() == bgra(8, 4)
    assert Path(got["pixels"]["path"]).read_bytes() == bytes(8 * 4 * 4)
    # Opened again, closed in the same job, and never shown.
    assert world.port.opened == [opened["path"], opened["path"]]
    assert list(world.port.live) == [key] and world.port.front_key == key
    assert [handle.document_id for handle in world.registry.sync()] == [opened["document_id"]]
    held = world.preview(_source(opened["document_id"], baseline_id=baseline))
    assert held["sources"][0]["baseline"] == {"baseline_id": baseline, "pixels": None}
    assert len(world.port.opened) == 2


def test_a_file_changed_since_the_open_holds_no_baseline(world: World) -> None:
    opened = world.open()
    Path(opened["path"]).write_bytes(b"saved over")
    source = _source(opened["document_id"], baseline_id=opened["baseline_id"], read_baseline=True)
    assert world.code(source) == "SOURCE_HASH_MISMATCH"
    assert len(world.port.opened) == 1 and world.transfer_files() == []


def test_a_reopened_file_krita_will_not_close_stays_owned_and_unsafe(world: World) -> None:
    opened = world.open()
    world.port.close_works = False
    source = _source(opened["document_id"], baseline_id=opened["baseline_id"], read_baseline=True)
    with pytest.raises(BridgeError) as refused:
        world.preview(source)
    assert refused.value.body["code"] == "INTERNAL_ERROR"
    kept = world.registry.find(refused.value.body["details"]["document_id"])
    # A discard close can still end it: it is the bridge's, not the owner's.
    assert kept.owned and kept.unsafe and kept.mode == "read_only"
    assert world.transfer_files() == []


def test_a_failure_reading_the_reopened_file_still_closes_it(world: World) -> None:
    opened = world.open()
    # Only the file opened again for the baseline fails to read.
    failure = BridgeError("IO_ERROR", "composite failed")
    world.port.on_open.append(lambda: world.port.fail.update(composite=failure))
    source = _source(opened["document_id"], baseline_id=opened["baseline_id"], read_baseline=True)
    assert world.code(source) == "IO_ERROR"
    assert world.port.opened == [opened["path"], opened["path"]]
    assert len(world.port.live) == 1 and world.transfer_files() == []


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"baseline_id": "baseline-000000000000"}, "INVALID_ARGUMENT"),
        ({"target": "layer", "layer_id": "x", "baseline_id": OWN}, "INVALID_ARGUMENT"),
        ({"read_baseline": True}, "INVALID_ARGUMENT"),
        ({"overlays": ["selection", "selection"]}, "INVALID_ARGUMENT"),
        ({"overlays": ["anchor"]}, "INVALID_ARGUMENT"),
        ({"frame": 1}, "UNSUPPORTED_CAPABILITY"),
        ({"rect": {"x": 6, "y": 0, "width": 4, "height": 1}}, "INVALID_ARGUMENT"),
        ({"extra": 1}, "INVALID_ARGUMENT"),
    ],
    ids=[
        "another baseline",
        "a layer's baseline",
        "read with no baseline",
        "an overlay twice",
        "an unknown overlay",
        "frame 1",
        "a rect outside",
        "an unknown field",
    ],
)
def test_each_source_is_exact(world: World, changes: dict[str, Any], code: str) -> None:
    opened = world.open()
    # The document's own baseline, so only the rule under test can refuse it.
    given = {
        key: opened["baseline_id"] if value is OWN else value for key, value in changes.items()
    }
    assert world.code(_source(opened["document_id"], **given)) == code
    assert world.transfer_files() == []


def test_one_preview_reads_at_most_a_whole_8k_master_beside_its_baseline(world: World) -> None:
    opened = world.open()
    handle = world.registry.find(opened["document_id"])
    world.port.live[max(world.port.live)]["size_px"] = [8192, 8192]
    source = _source(opened["document_id"], baseline_id=handle.baseline_id, read_baseline=True)
    second = _source(opened["document_id"], rect={"x": 0, "y": 0, "width": 1, "height": 1})
    assert world.code(source, second) == "INVALID_ARGUMENT"
    assert previews.MAX_PREVIEW_PIXELS == 2 * 8192 * 8192
    assert len(world.port.opened) == 1


def test_the_overlays_are_the_selection_and_the_allowed_masks_crops(world: World) -> None:
    opened = world.open()
    handle = world.registry.find(opened["document_id"])
    rect = {"x": 1, "y": 1, "width": 3, "height": 2}
    empty = world.preview(_source(opened["document_id"], rect=rect, overlays=["selection"]))
    assert empty["sources"][0]["overlays"] == {"selection": None}
    handle.allowed_mask = bytes(range(32))
    key = max(world.port.live)
    world.port.live[key]["selection"] = ({"x": 0, "y": 0, "width": 8, "height": 4}, bytes(32))
    both = world.preview(
        _source(opened["document_id"], rect=rect, overlays=["allowed_mask", "selection"])
    )
    overlays = both["sources"][0]["overlays"]
    assert Path(overlays["allowed_mask"]["path"]).read_bytes() == bytes([9, 10, 11, 17, 18, 19])
    assert Path(overlays["selection"]["path"]).read_bytes() == bytes(6)
    assert overlays["selection"]["format"] == "A8"


def test_a_failure_part_way_removes_every_file_already_written(world: World) -> None:
    first, second = world.open("hero.kra"), world.open("rim.kra")
    calls = []

    def second_read_fails() -> None:
        calls.append(1)
        if len(calls) == 2:
            raise BridgeError("IO_ERROR", "the second read failed")

    world.port.on_read.append(second_read_fails)
    assert world.code(_source(first["document_id"]), _source(second["document_id"])) == "IO_ERROR"
    assert world.transfer_files() == []
