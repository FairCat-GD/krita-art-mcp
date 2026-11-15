import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest
from bridge_core import documents, files, protection, saving
from bridge_core.errors import BridgeError
from bridge_core.jobs import Call
from bridge_core.registry import Handle, Registry
from fake_krita import FakePort, bgra, fake_node

A: dict[str, Any] = {"pid": 101, "started_at": "Sat Oct 24 10:00:00 2026"}
B: dict[str, Any] = {"pid": 202, "started_at": "Sat Oct 24 10:05:00 2026"}
ACCEPTED = b"accepted art"
WIDTH, HEIGHT = 8, 4
WHOLE = {"x": 0, "y": 0, "width": WIDTH, "height": HEIGHT}
PIXEL = bytes([9, 8, 7, 255])
CREATE = {
    "name": "sprite",
    "size_px": [WIDTH, HEIGHT],
    "color_model": "RGBA",
    "depth": "U8",
    "profile_id": documents.SRGB_PROFILE,
    "background": "transparent",
}


class World:
    def __init__(self, tmp: Path) -> None:
        self.data = tmp / "data"
        self.art = tmp / "art"
        (self.art / "accepted").mkdir(parents=True)
        self.branches = self.art / "branches"
        self.data.mkdir()
        roots = {"v": 1, "roots": [os.path.realpath(self.art)]}
        (self.data / "config.json").write_text(json.dumps(roots))
        self.port = FakePort()
        self.registry = Registry(self.port, lambda client: True)
        self.ops = documents.handlers(self.registry, self.port, self.data)

    def run(
        self,
        op: str,
        args: dict[str, Any],
        operation_id: str = "op-x",
        client: dict[str, Any] = A,
    ) -> dict[str, Any]:
        return self.ops[op](args, Call(operation_id, "req-x", client))

    def open(self, mode: str = "working_copy") -> str:
        path = self.art / "accepted" / "hero.kra"
        path.write_bytes(ACCEPTED)
        args = {
            "source_path": str(path),
            "source_sha256": hashlib.sha256(ACCEPTED).hexdigest(),
            "mode": mode,
            "working_dir": str(self.art / "work") if mode == "working_copy" else None,
            "editable_layer_ids": None,
            "editable_layer_names": None,
        }
        document_id = str(self.run("document.open", args)["document_id"])
        if mode == "working_copy":
            # A protected group holding a protected layer, and a layer of the agent's own.
            key = self.key(document_id)
            tree = self.port._tree(key)
            root = tree["root_id"]
            group = fake_node(key, 10, "group", root, 1, type="grouplayer")
            inner = fake_node(key, 11, "inner", group["id"], 0)
            own = fake_node(key, 12, "own", root, 2)
            tree["nodes"] += [group, inner, own]
            handle = self.handle(document_id)
            handle.protected |= {group["id"], inner["id"]}
        return document_id

    def created(self) -> str:
        return str(self.run("document.create", CREATE)["document_id"])

    def handle(self, document_id: str) -> Handle:
        return self.registry.find(document_id)

    def key(self, document_id: str) -> int:
        return int(self.handle(document_id).document.key)

    def ids(self, document_id: str) -> set[str]:
        return {node["id"] for node in self.port._tree(self.key(document_id))["nodes"]}

    def duplicate(
        self, document_id: str, name: str = "hero-b.kra", client: dict[str, Any] = A
    ) -> dict[str, Any]:
        args = {"document_id": document_id, "path": str(self.branches / name)}
        return self.run("document.duplicate", args, f"op-dup-{name}", client)

    def finish(self, saved: dict[str, Any]) -> dict[str, Any]:
        args = {
            "document_id": saved["document_id"],
            "save_id": saved["save_id"],
            "merged_sha256": saved["composite_sha256"],
            "merged_problem": None,
        }
        return self.run("document.save_finish", args, "op-finish")

    def open_branch(
        self, saved: dict[str, Any], client: dict[str, Any] = A, save_id: str | None = None
    ) -> dict[str, Any]:
        args = {"document_id": saved["document_id"], "save_id": save_id or saved["save_id"]}
        return self.run("document.duplicate_open", args, "op-open", client)

    def branch(self, document_id: str, name: str = "hero-b.kra") -> dict[str, Any]:
        saved = self.duplicate(document_id, name)
        self.finish(saved)
        return self.open_branch(saved)

    def refused(self, call: Any) -> dict[str, Any]:
        with pytest.raises(BridgeError) as refused:
            call()
        body: dict[str, Any] = refused.value.body
        return body

    def files(self) -> list[str]:
        return sorted(os.listdir(self.branches)) if self.branches.exists() else []

    def preview(self, document_id: str, baseline_id: str | None, read: bool) -> dict[str, Any]:
        source = {
            "document_id": document_id,
            "frame": 0,
            "target": "composite",
            "layer_id": None,
            "rect": None,
            "baseline_id": baseline_id,
            "read_baseline": read,
            "overlays": [],
        }
        [got] = self.run("preview.read", {"sources": [source], "render": {}})["sources"]
        return dict(got)


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


def _mask(*allowed: int) -> bytes:
    found = bytearray(WIDTH * HEIGHT)
    for index in allowed:
        found[index] = 255
    return bytes(found)


@pytest.mark.parametrize("name", ["hero-b.ora", "hero-b.png"])
def test_a_duplicate_is_a_kra_alone(world: World, name: str) -> None:
    document_id = world.open()
    body = world.refused(lambda: world.duplicate(document_id, name))
    assert body["code"] == "UNSUPPORTED_CAPABILITY" and body["details"]["formats"] == [".kra"]
    assert body["message"] == saving.DUPLICATE_FORMATS_MESSAGE
    assert world.files() == [] and world.handle(document_id).pending_save is None


def test_a_duplicate_is_refused_where_a_save_is(world: World) -> None:
    read_only = world.open("read_only")
    assert world.refused(lambda: world.duplicate(read_only))["code"] == "DOCUMENT_READ_ONLY"
    document_id = world.open()
    world.handle(document_id).unsafe = True
    assert world.refused(lambda: world.duplicate(document_id))["code"] == "DOCUMENT_UNSAFE"
    world.handle(document_id).unsafe = False
    held = document_id
    assert world.refused(lambda: world.duplicate(held, client=B))["code"] == "DOCUMENT_IN_USE"
    (world.branches / "taken.kra").parent.mkdir(parents=True, exist_ok=True)
    (world.branches / "taken.kra").write_bytes(b"there first")
    assert world.refused(lambda: world.duplicate(held, "taken.kra"))["code"] == "FILE_EXISTS"
    assert world.files() == ["taken.kra"]


def test_a_duplicate_writes_and_verifies_its_file_as_a_save_does(world: World) -> None:
    document_id = world.open()
    saved = world.duplicate(document_id)
    written = Path(saved["written"])
    assert world.files() == [written.name] and written.name.endswith(".saving.kra")
    assert saved["sha256"] == hashlib.sha256(written.read_bytes()).hexdigest()
    assert saved["reopened_verified"] is True and saved["expected_losses"] == []
    pending = world.handle(document_id).pending_save
    assert isinstance(pending, saving.Pending) and pending.branch is not None
    assert pending.branch.protected == world.handle(document_id).protected


@pytest.mark.parametrize("dirty", [True, False])
def test_a_duplicate_leaves_its_source_as_it_was(world: World, dirty: bool) -> None:
    document_id = world.open()
    handle = world.handle(document_id)
    if dirty:
        handle.before_change()
    state = handle.saved_state = {"held": "as it was"}
    before = (handle.dirty, handle.changes, world.port.describe(handle.document)["modified"])
    saved = world.duplicate(document_id)
    finished = world.finish(saved)
    assert finished["dirty_cleared"] is False and finished["dirty"] is dirty
    opened = world.open_branch(saved)
    after = (handle.dirty, handle.changes, world.port.describe(handle.document)["modified"])
    assert after == before and handle.saved_state is state
    assert opened["source_dirty"] is dirty and opened["source_krita_modified"] is before[2]


def test_a_duplicate_reports_its_recompose_from_the_save_to_the_open(world: World) -> None:
    # A stale projection: the save's recompose fills in one colour under alpha 0.
    document_id = world.open()
    key = world.handle(document_id).document.key
    fresh = bytearray(WIDTH * HEIGHT * 4)
    fresh[(1 * WIDTH + 3) * 4 : (1 * WIDTH + 3) * 4 + 4] = bytes([4, 5, 6, 0])
    world.port.render[key] = lambda tree: bytes(fresh)
    world.port.projection[key] = bytes(WIDTH * HEIGHT * 4)
    drift = {
        "changed_px": 1,
        "visible_changed_px": 0,
        "changed_bounds_px": {"x": 3, "y": 1, "width": 1, "height": 1},
    }
    saved = world.duplicate(document_id)
    assert saved["recompose"] == drift
    assert world.finish(saved)["recompose"] == drift
    assert world.open_branch(saved)["recompose"] == drift


def test_the_finish_places_the_duplicate_and_waits_for_its_open(world: World) -> None:
    document_id = world.open()
    saved = world.duplicate(document_id)
    world.finish(saved)
    assert world.files() == ["hero-b.kra"]
    placed = world.handle(document_id).branches[saved["save_id"]]
    assert placed.path == saved["path"] and placed.sha256 == saved["sha256"]
    # Nothing opened yet: only the source is registered.
    assert [h.document_id for h in world.registry.sync()] == [document_id]


def test_the_branch_opens_with_its_sources_protection_and_its_own_baseline(world: World) -> None:
    document_id = world.open()
    source = world.handle(document_id)
    source.allowed_mask = _mask(1, 2, 9)
    source.allowed_summary = protection.summary(source.allowed_mask, WIDTH)
    source.preserve_composite_alpha = True
    saved = world.duplicate(document_id)
    world.finish(saved)
    opened = world.open_branch(saved)
    branch = world.handle(opened["new_document_id"])
    assert opened["document_id"] == document_id and branch is not source
    assert branch.mode == "working_copy" and branch.path == saved["path"] == opened["path"]
    assert branch.opened_sha256 == saved["sha256"] == opened["sha256"]
    assert (branch.source_path, branch.source_sha256, branch.source_stat) == (
        source.source_path,
        source.source_sha256,
        source.source_stat,
    )
    assert branch.baseline_id is not None and branch.baseline_id != source.baseline_id
    assert opened["baseline_id"] == branch.baseline_id and opened["baseline_untouched"] is True
    # A KRA keeps every node's id, so protection names the same layers.
    assert world.ids(opened["new_document_id"]) == world.ids(document_id)
    assert branch.protected == source.protected
    assert branch.allowed_mask == source.allowed_mask
    assert branch.allowed_summary == source.allowed_summary
    assert (branch.preserve_composite_alpha, branch.preserve_canvas) == (True, False)
    assert opened["protection"] == {
        "allowed_change_mask": source.allowed_summary,
        "preserve_composite_alpha": True,
        "preserve_canvas": False,
    }
    assert {layer["id"] for layer in opened["layers"] if layer["protected"]} == source.protected
    assert branch.ledger.undo_available() == 0 and branch.dirty is False
    assert branch.lease == A and branch.owned and not branch.unsafe
    assert opened["reopened_verified"] is True and opened["canvas_px"] == [WIDTH, HEIGHT]
    assert world.handle(document_id).branches == {}


def test_a_rerun_takes_the_tighter_of_the_save_and_the_source_now(world: World) -> None:
    document_id = world.open()
    source = world.handle(document_id)
    source.allowed_mask = _mask(1, 2, 9)
    saved = world.duplicate(document_id)
    world.finish(saved)
    # Before the open, a protected layer gone from the source drops out of its protection, and
    # the source tightens its mask and a flag.
    inner = next(
        node
        for node in world.port._tree(world.key(document_id))["nodes"]
        if node["name"] == "inner"
    )
    source.protected = source.protected - {inner["id"]}
    source.allowed_mask = _mask(2, 9, 30)
    source.preserve_canvas = True
    branch = world.handle(world.open_branch(saved)["new_document_id"])
    assert inner["id"] in branch.protected
    assert branch.allowed_mask == _mask(2, 9)
    assert branch.allowed_summary == protection.summary(_mask(2, 9), WIDTH)
    assert branch.preserve_canvas is True


def test_the_open_takes_only_a_duplicate_its_own_finish_placed(world: World) -> None:
    document_id = world.open()
    saved = world.duplicate(document_id)
    opened = len(world.port.opened)
    body = world.refused(lambda: world.open_branch(saved))
    assert body["code"] == "INVALID_ARGUMENT" and body["details"]["save_id"] == saved["save_id"]
    world.finish(saved)
    other = world.refused(lambda: world.open_branch(saved, save_id="op-another"))
    assert other["code"] == "INVALID_ARGUMENT" and len(world.port.opened) == opened
    world.open_branch(saved)
    # Opened once: the same save_id waits for nothing now.
    assert world.refused(lambda: world.open_branch(saved))["code"] == "INVALID_ARGUMENT"


def test_a_placed_file_changed_since_is_not_opened(world: World) -> None:
    document_id = world.open()
    saved = world.duplicate(document_id)
    world.finish(saved)
    Path(saved["path"]).write_bytes(b"written over")
    opened = len(world.port.opened)
    body = world.refused(lambda: world.open_branch(saved))
    assert body["code"] == "SOURCE_HASH_MISMATCH" and len(world.port.opened) == opened
    assert saved["save_id"] in world.handle(document_id).branches


def test_a_mask_of_another_canvas_is_refused_before_anything_opens(world: World) -> None:
    document_id = world.open()
    saved = world.duplicate(document_id)
    world.finish(saved)
    world.handle(document_id).allowed_mask = bytes(5)
    opened = len(world.port.opened)
    body = world.refused(lambda: world.open_branch(saved))
    assert body["code"] == "INVALID_ARGUMENT" and len(world.port.opened) == opened


def test_a_failed_open_closes_the_branch_and_keeps_its_file(world: World) -> None:
    document_id = world.open()
    saved = world.duplicate(document_id)
    world.finish(saved)
    world.port.fail["tree"] = BridgeError("IO_ERROR", "tree failed")
    body = world.refused(lambda: world.open_branch(saved))
    del world.port.fail["tree"]
    assert body["details"]["rollback_verified"] is True and body["retryable"] is False
    assert [h.document_id for h in world.registry.sync()] == [document_id]
    assert world.files() == ["hero-b.kra"]


def test_an_unmoved_placed_file_opens_without_hashing_it_again(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    document_id = world.open()
    saved = world.duplicate(document_id)
    world.finish(saved)

    def hashed(path: str) -> str:
        raise AssertionError(f"{path} was hashed again")

    monkeypatch.setattr(files, "sha256_of", hashed)
    assert world.open_branch(saved)["sha256"] == saved["sha256"]


def test_a_branch_paints_apart_from_its_source(world: World) -> None:
    document_id = world.open()
    own = next(n for n in world.port._tree(world.key(document_id))["nodes"] if n["name"] == "own")
    world.port.paintable(world.key(document_id), None)
    before = world.port.layer_rects(world.handle(document_id).document, own["id"], [WHOLE])
    composite = world.port.composite(world.handle(document_id).document)
    opened = world.branch(document_id)
    branch = world.handle(opened["new_document_id"])
    box = {"x": 0, "y": 0, "width": 2, "height": 2}
    world.port.paint_by_hand(world.key(opened["new_document_id"]), own["id"], box, PIXEL)
    source = world.handle(document_id).document
    assert world.port.layer_rects(source, own["id"], [WHOLE]) == before
    assert world.port.composite(source) == composite
    assert world.port.layer_rects(branch.document, own["id"], [WHOLE]) != before


def test_a_working_copys_branch_reads_its_baseline_from_its_own_file(world: World) -> None:
    document_id = world.open()
    world.port.canvas[world.key(document_id)] = bytearray(bytes(WIDTH * HEIGHT * 4))
    opened = world.branch(document_id)
    got = world.preview(opened["new_document_id"], opened["baseline_id"], True)
    assert got["baseline"]["baseline_id"] == opened["baseline_id"]
    # The branch as opened is the source as it was duplicated.
    assert Path(got["baseline"]["pixels"]["path"]).read_bytes() == bytes(WIDTH * HEIGHT * 4)
    assert world.port.opened[-1] == opened["path"]


def test_a_created_documents_branch_has_no_source_and_reads_its_baseline(world: World) -> None:
    document_id = world.created()
    opened = world.branch(document_id)
    branch = world.handle(opened["new_document_id"])
    assert opened["mode"] == branch.mode == "new"
    assert (opened["source_path"], opened["source_sha256"]) == (None, None)
    assert opened["baseline_untouched"] is None and branch.opened_sha256 == opened["sha256"]
    got = world.preview(opened["new_document_id"], opened["baseline_id"], True)
    assert Path(got["baseline"]["pixels"]["path"]).read_bytes() == bgra(WIDTH, HEIGHT)


def test_an_open_keeps_its_files_hash_for_the_baseline(world: World) -> None:
    document_id = world.open()
    handle = world.handle(document_id)
    assert handle.opened_sha256 == handle.source_sha256 == hashlib.sha256(ACCEPTED).hexdigest()
    assert world.handle(world.created()).opened_sha256 is None


def test_a_branch_of_a_branch_keeps_the_accepted_source(world: World) -> None:
    document_id = world.open()
    first = world.branch(document_id)
    second = world.branch(first["new_document_id"], "hero-c.kra")
    assert second["source_path"] == world.handle(document_id).source_path
    assert second["baseline_untouched"] is True and second["path"].endswith("hero-c.kra")


def test_a_save_after_a_duplicate_replaces_its_unfinished_file(world: World) -> None:
    document_id = world.open()
    duplicated = world.duplicate(document_id)
    args = {"document_id": document_id, "path": str(world.branches / "hero-r02.kra")}
    saved = world.run("document.save", args, "op-save")
    assert saved["replaced_pending"] is True and not os.path.lexists(duplicated["written"])
    assert world.refused(lambda: world.finish(duplicated))["code"] == "INVALID_ARGUMENT"
