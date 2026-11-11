import errno
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest
from bridge_core import documents, files, saving, translations
from bridge_core.errors import BridgeError
from bridge_core.jobs import Call
from bridge_core.registry import Handle, Registry
from fake_krita import FakePort, bgra, fake_node, layer_id

A: dict[str, Any] = {"pid": 101, "started_at": "Sat Oct 24 10:00:00 2026"}
B: dict[str, Any] = {"pid": 202, "started_at": "Sat Oct 24 10:05:00 2026"}
WHOLE = {"x": 0, "y": 0, "width": 8, "height": 4}
PIXEL = bytes([9, 8, 7, 255])


class World:
    def __init__(self, tmp: Path) -> None:
        self.data = tmp / "data"
        self.art = tmp / "art"
        (self.art / "accepted").mkdir(parents=True)
        self.saves = self.art / "revisions"
        self.data.mkdir()
        roots = {"v": 1, "roots": [os.path.realpath(self.art)]}
        (self.data / "config.json").write_text(json.dumps(roots))
        self.port = FakePort()
        self.registry = Registry(self.port, lambda client: True)
        self.ops = documents.handlers(self.registry, self.port, self.data)

    def run(self, op: str, args: dict[str, Any], operation_id: str = "op-x") -> dict[str, Any]:
        return self.ops[op](args, Call(operation_id, "req-x", A))

    def open(self, mode: str = "working_copy") -> str:
        path = self.art / "accepted" / "hero.kra"
        path.write_bytes(b"accepted art")
        args = {
            "source_path": str(path),
            "source_sha256": hashlib.sha256(b"accepted art").hexdigest(),
            "mode": mode,
            "working_dir": str(self.art / "work") if mode == "working_copy" else None,
            "editable_layer_ids": None,
            "editable_layer_names": None,
        }
        return str(self.run("document.open", args)["document_id"])

    def handle(self, document_id: str) -> Handle:
        return self.registry.find(document_id)

    def key(self, document_id: str) -> int:
        return int(self.handle(document_id).document.key)

    def save(self, document_id: str, name: str = "hero-r02.kra") -> dict[str, Any]:
        args = {"document_id": document_id, "path": str(self.saves / name)}
        return self.run("document.save", args, f"op-save-{name}")

    def finish(
        self, saved: dict[str, Any], merged: str | None = None, problem: str | None = None
    ) -> dict[str, Any]:
        args = {
            "document_id": saved["document_id"],
            "save_id": saved["save_id"],
            "merged_sha256": saved["composite_sha256"] if merged is None else merged,
            "merged_problem": problem,
        }
        return self.run("document.save_finish", args, "op-finish")

    def change(self, document_id: str) -> None:
        # A change through the bridge: the bridge marks it, and Krita pushes an undo step.
        handle = self.handle(document_id)
        handle.before_change()
        root = self.port._tree(self.key(document_id))["root_id"]
        self.port.create_layer(handle.document, root, None, "paintlayer", "agent")

    def flags(self, document_id: str) -> tuple[bool, bool]:
        listed = self.run("document.list", {})["documents"]
        [entry] = [entry for entry in listed if entry["document_id"] == document_id]
        return entry["dirty"], entry["krita_modified"]

    def close(self, document_id: str, policy: str = "refuse") -> dict[str, Any]:
        return self.run("document.close", {"document_id": document_id, "dirty_policy": policy})

    def code(self, op: str, *args: Any, **changes: Any) -> str:
        with pytest.raises(BridgeError) as refused:
            getattr(self, op)(*args, **changes)
        return str(refused.value.body["code"])

    def refused(self, op: str, *args: Any) -> dict[str, Any]:
        with pytest.raises(BridgeError) as refused:
            getattr(self, op)(*args)
        body: dict[str, Any] = refused.value.body
        return body

    def files(self) -> list[str]:
        return sorted(os.listdir(self.saves)) if self.saves.exists() else []

    def add(self, document_id: str, name: str, parent: str | None = None, **changes: Any) -> str:
        key = self.key(document_id)
        tree = self.port._tree(key)
        parent = parent or tree["root_id"]
        order = sum(1 for node in tree["nodes"] if node["parent_id"] == parent)
        node = fake_node(key, len(tree["nodes"]) + 50, name, parent, order, **changes)
        tree["nodes"].append(node)
        return str(node["id"])


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


def test_a_save_writes_only_a_hidden_file_and_verifies_it_by_reopening(world: World) -> None:
    document_id = world.open()
    saved = world.save(document_id)
    written = Path(saved["written"])
    assert written.parent == world.saves and written.name.startswith(".hero-r02.")
    assert written.name.endswith(".saving.kra")
    assert world.files() == [written.name]
    assert world.port.opened[-1] == str(written)
    # The reopened file was closed in the same job; only the working copy is open.
    assert [handle.document_id for handle in world.registry.sync()] == [document_id]
    assert saved["path"] == str(world.saves / "hero-r02.kra") and saved["format"] == "kra"
    assert saved["sha256"] == hashlib.sha256(written.read_bytes()).hexdigest()
    assert saved["composite_sha256"] == hashlib.sha256(bgra(8, 4)).hexdigest()
    assert saved["save_id"] == "op-save-hero-r02.kra" and saved["size_px"] == [8, 4]
    assert saved["reopened_verified"] is True and saved["layers_preserved"] is True
    assert saved["composite_preserved"] is True and saved["baseline_untouched"] is True
    assert saved["expected_losses"] == []


def test_finishing_puts_the_file_in_place_and_clears_the_dirt(world: World) -> None:
    document_id = world.open()
    world.handle(document_id).before_change()
    saved = world.save(document_id)
    content = Path(saved["written"]).read_bytes()
    finished = world.finish(saved)
    assert world.files() == ["hero-r02.kra"]
    assert (world.saves / "hero-r02.kra").read_bytes() == content
    assert world.handle(document_id).dirty is False and finished["dirty_cleared"] is True
    assert finished["sha256"] == saved["sha256"] and finished["path"] == saved["path"]
    assert "written" not in finished and "save_id" not in finished
    # The working document still points at its own file (K39).
    assert world.port.describe(world.handle(document_id).document)["path"].startswith(
        str(world.art / "work")
    )


def test_a_change_between_the_save_and_its_finish_keeps_the_dirt(world: World) -> None:
    document_id = world.open()
    handle = world.handle(document_id)
    handle.before_change()
    saved = world.save(document_id)
    handle.before_change()
    finished = world.finish(saved)
    assert world.files() == ["hero-r02.kra"]
    assert handle.dirty is True and finished["dirty_cleared"] is False
    assert handle.saved_state is None


def test_a_document_marked_unsafe_meanwhile_keeps_the_dirt(world: World) -> None:
    document_id = world.open()
    handle = world.handle(document_id)
    handle.before_change()
    saved = world.save(document_id)
    handle.lost()
    handle.dirty = True
    assert world.finish(saved)["dirty_cleared"] is False


def test_a_verified_save_reports_both_flags_and_where_the_document_points(world: World) -> None:
    document_id = world.open()
    world.change(document_id)
    finished = world.finish(world.save(document_id))
    working_copy = world.port.describe(world.handle(document_id).document)["path"]
    assert working_copy.startswith(str(world.art / "work"))
    assert (finished["dirty"], finished["krita_modified"]) == (False, True)
    assert finished["document_path"] == working_copy
    assert world.flags(document_id) == (False, True)
    assert world.close(document_id)["closed"] is True


def test_a_refused_or_failed_save_clears_neither_flag(world: World) -> None:
    document_id = world.open()
    world.change(document_id)
    world.saves.mkdir()
    (world.saves / "taken.kra").write_bytes(b"there")
    assert world.code("save", document_id, "taken.kra") == "FILE_EXISTS"
    assert world.flags(document_id) == (True, True)
    saved = world.save(document_id)
    assert world.code("finish", saved, "0" * 64) == "SAVE_VERIFY_FAILED"
    assert world.flags(document_id) == (True, True)
    assert world.handle(document_id).saved_state is None
    assert world.code("close", document_id) == "DOCUMENT_DIRTY"


def test_new_paint_after_a_save_shows_in_both_flags_and_refuse_refuses_it(world: World) -> None:
    document_id = world.open()
    world.change(document_id)
    world.finish(world.save(document_id))
    world.change(document_id)
    assert world.flags(document_id) == (True, True)
    body = world.refused("close", document_id)
    assert body["code"] == "DOCUMENT_DIRTY"
    assert body["details"] == {"document_id": document_id, "dirty": True, "krita_modified": True}


def _visible_stroke(world: World, document_id: str, layers: dict[str, str]) -> None:
    box = {"x": 1, "y": 1, "width": 2, "height": 2}
    world.port.paint_by_hand(world.key(document_id), layers["shown"], box, PIXEL)


def _hidden_stroke(world: World, document_id: str, layers: dict[str, str]) -> None:
    box = {"x": 1, "y": 1, "width": 2, "height": 2}
    world.port.paint_by_hand(world.key(document_id), layers["hidden"], box, PIXEL)


def _new_node(world: World, document_id: str, layers: dict[str, str]) -> None:
    world.port.add_fixture_node(world.handle(document_id).document, "clone_layer", layers["shown"])


def _layer_style(world: World, document_id: str, layers: dict[str, str]) -> None:
    # A change only the composite shows, as a layer style's would.
    key = world.key(document_id)
    world.port.paintable(key, None)
    before = world.port._state(key)
    composite = world.port.canvas[key]
    assert isinstance(composite, bytearray)
    composite[0] ^= 1
    world.port._push(key, "Layer Style", before)


def _mask_edit(world: World, document_id: str, layers: dict[str, str]) -> None:
    # A mask ORA drops, edited where no composite shows it: its layer is hidden.
    key = world.key(document_id)
    before = world.port._state(key)
    world.port.node_canvas[(key, layers["mask"])] = bytes([0]) + b"\xff" * 31
    world.port._push(key, "Transparency Mask", before)


@pytest.mark.parametrize("name", ["hero-r02.kra", "hero-r02.ora"])
@pytest.mark.parametrize(
    "change", [_visible_stroke, _hidden_stroke, _new_node, _layer_style, _mask_edit]
)
def test_a_hand_change_after_a_save_is_refused(world: World, change: Any, name: str) -> None:
    document_id = world.open()
    layers = {
        "shown": world.add(document_id, "shown", bounds_px=WHOLE),
        "hidden": world.add(document_id, "hidden", visible=False, bounds_px=WHOLE),
    }
    layers["mask"] = world.add(
        document_id, "mask", layers["hidden"], type="transparencymask", bounds_px=WHOLE
    )
    world.change(document_id)
    finished = world.finish(world.save(document_id, name))
    assert finished["dirty"] is False
    change(world, document_id, layers)
    assert world.flags(document_id) == (False, True)
    body = world.refused("close", document_id)
    assert body["code"] == "DOCUMENT_DIRTY"
    assert body["details"] == {"document_id": document_id, "dirty": False, "krita_modified": True}
    assert world.close(document_id, "discard")["closed"] is True


@pytest.mark.parametrize("name", ["hero-r02.kra", "hero-r02.ora"])
def test_refuse_closes_a_saved_document_nothing_changed_since(world: World, name: str) -> None:
    document_id = world.open()
    hidden = world.add(document_id, "hidden", visible=False, bounds_px=WHOLE)
    world.add(document_id, "mask", hidden, type="transparencymask", bounds_px=WHOLE)
    world.add(document_id, "group", type="grouplayer")
    world.change(document_id)
    world.finish(world.save(document_id, name))
    assert world.flags(document_id) == (False, True)
    assert world.close(document_id)["closed"] is True


def test_a_hand_change_before_the_finish_is_refused_at_the_close(world: World) -> None:
    document_id = world.open()
    shown = world.add(document_id, "shown", bounds_px=WHOLE)
    world.change(document_id)
    saved = world.save(document_id)
    box = {"x": 0, "y": 0, "width": 1, "height": 1}
    world.port.paint_by_hand(world.key(document_id), shown, box, PIXEL)
    assert world.finish(saved)["dirty_cleared"] is True
    assert world.code("close", document_id) == "DOCUMENT_DIRTY"


@pytest.mark.parametrize("problem", [None, "mergedimage.png is 16-bit"])
def test_a_mergedimage_that_differs_removes_the_file(world: World, problem: str | None) -> None:
    document_id = world.open()
    world.handle(document_id).before_change()
    saved = world.save(document_id)
    other = "0" * 64 if problem is None else None
    body = world.refused("finish", saved, other, problem)
    assert body["code"] == "SAVE_VERIFY_FAILED" and body["retryable"] is False
    [mismatch] = body["details"]["mismatches"]
    assert mismatch["field"] == "mergedimage" and mismatch["problem"] == problem
    assert world.files() == [] and world.handle(document_id).dirty is True


def test_a_finish_needs_the_save_still_pending(world: World) -> None:
    document_id = world.open()
    saved = world.save(document_id)
    assert world.code("finish", {**saved, "save_id": "op-other"}) == "INVALID_ARGUMENT"
    world.finish(saved)
    assert world.code("finish", saved) == "INVALID_ARGUMENT"


def test_a_written_file_changed_before_the_finish_fails_it(world: World) -> None:
    document_id = world.open()
    saved = world.save(document_id)
    Path(saved["written"]).write_bytes(b"someone else's")
    assert world.code("finish", saved) == "SAVE_VERIFY_FAILED"
    assert world.files() == [] and not world.saves.exists()


def test_a_target_that_appears_meanwhile_is_never_overwritten(world: World) -> None:
    document_id = world.open()
    saved = world.save(document_id)
    (world.saves / "hero-r02.kra").write_bytes(b"theirs")
    assert world.code("finish", saved) == "FILE_EXISTS"
    assert world.files() == ["hero-r02.kra"]
    assert (world.saves / "hero-r02.kra").read_bytes() == b"theirs"


def test_without_hard_links_the_file_is_renamed_after_a_check(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_links(source: str, target: str) -> None:
        raise OSError(errno.ENOTSUP, "no hard links here")

    monkeypatch.setattr(os, "link", no_links)
    document_id = world.open()
    saved = world.save(document_id)
    world.finish(saved)
    assert world.files() == ["hero-r02.kra"]
    again = world.save(document_id, "hero-r03.kra")
    (world.saves / "hero-r03.kra").write_bytes(b"theirs")
    assert world.code("finish", again) == "FILE_EXISTS"
    assert (world.saves / "hero-r03.kra").read_bytes() == b"theirs"
    assert world.files() == ["hero-r02.kra", "hero-r03.kra"]


def test_an_export_krita_refuses_is_busy_and_leaves_nothing(world: World) -> None:
    document_id = world.open()
    world.port.export_works = False
    body = world.refused("save", document_id)
    assert body["code"] == "BUSY" and body["retryable"] is True
    assert world.files() == [] and world.handle(document_id).pending_save is None


@pytest.mark.parametrize(
    "path, code",
    [
        ("revisions/hero.kra", "INVALID_ARGUMENT"),
        ("{outside}/hero.kra", "PATH_NOT_ALLOWED"),
        ("{saves}/hero.png", "UNSUPPORTED_CAPABILITY"),
        ("{saves}/hero.psd", "UNSUPPORTED_CAPABILITY"),
        ("{work}/hero.kra", "FILE_EXISTS"),
    ],
)
def test_the_path_is_a_new_kra_or_ora_inside_a_root(world: World, path: str, code: str) -> None:
    document_id = world.open()
    (world.art / "work" / "hero.kra").write_bytes(b"there already")
    outside = world.data / "elsewhere"
    filled = path.format(outside=outside, saves=world.saves, work=world.art / "work")
    with pytest.raises(BridgeError) as refused:
        world.run("document.save", {"document_id": document_id, "path": filled})
    assert refused.value.body["code"] == code
    assert world.files() == [] and not outside.exists()
    assert (world.art / "work" / "hero.kra").read_bytes() == b"there already"


def test_a_missing_folder_inside_the_root_is_made(world: World) -> None:
    document_id = world.open()
    world.saves = world.saves / "deeper"
    world.finish(world.save(document_id))
    assert world.files() == ["hero-r02.kra"]


def test_a_canvas_too_large_to_read_is_refused_before_anything_is_written(world: World) -> None:
    document_id = world.open()
    world.port.live[world.key(document_id)]["size_px"] = [8193, 8192]
    world.port.calls.clear()
    body = world.refused("save", document_id)
    assert body["code"] == "UNSUPPORTED_CAPABILITY" and body["details"]["max_pixels"] == 8192**2
    assert "export" not in world.port.calls and not world.saves.exists()


def test_a_failed_save_removes_the_folders_it_made(world: World) -> None:
    document_id = world.open()
    world.saves = world.saves / "deeper" / "deepest"
    world.port.export_works = False
    assert world.code("save", document_id) == "BUSY"
    assert not (world.art / "revisions").exists()
    world.port.export_works = True
    saved = world.save(document_id)
    assert world.code("finish", saved, "0" * 64) == "SAVE_VERIFY_FAILED"
    assert not (world.art / "revisions").exists()


def test_a_folder_that_cannot_be_written_is_io_error_not_busy(world: World) -> None:
    document_id = world.open()
    world.saves.mkdir()
    world.saves.chmod(0o555)
    try:
        world.port.calls.clear()
        assert world.code("save", document_id) == "IO_ERROR"
        assert "export" not in world.port.calls
    finally:
        world.saves.chmod(0o755)


def test_a_name_too_long_to_save_beside_is_refused(world: World) -> None:
    document_id = world.open()
    body = world.refused("save", document_id, "h" * 240 + ".kra")
    assert body["code"] == "INVALID_ARGUMENT" and body["details"]["max_name_bytes"] < 244
    assert world.files() == []


def test_read_only_and_unsafe_documents_are_refused(world: World) -> None:
    read_only = world.open("read_only")
    assert world.code("save", read_only) == "DOCUMENT_READ_ONLY"
    unsafe = world.open()
    world.handle(unsafe).unsafe = True
    assert world.code("save", unsafe) == "DOCUMENT_UNSAFE"
    assert world.files() == []


def test_another_server_is_refused_the_lease(world: World) -> None:
    document_id = world.open()
    args = {"document_id": document_id, "path": str(world.saves / "hero-r02.kra")}
    with pytest.raises(BridgeError) as refused:
        world.ops["document.save"](args, Call("op-b", "req-b", B))
    assert refused.value.body["code"] == "DOCUMENT_IN_USE"


@pytest.mark.parametrize(
    "space",
    [
        ("RGBA", "U16", "sRGB-elle-V2-srgbtrc.icc"),
        ("RGBA", "U8", "Rec2020-elle-V4-g10.icc"),
    ],
)
def test_only_rgba_u8_srgb_documents_are_saved(world: World, space: tuple[str, ...]) -> None:
    document_id = world.open()
    world.port.live[world.key(document_id)]["space"] = space
    assert world.code("save", document_id) == "UNSUPPORTED_CAPABILITY"
    assert world.files() == []


def test_a_selection_mask_gives_way_before_the_export(world: World) -> None:
    # K46: exportImage saves the live image, an active mask's overlay and all.
    document_id = world.open()
    world.port.mask(world.key(document_id))
    world.port.calls.clear()
    world.save(document_id)
    assert not world.port.is_masked(world.key(document_id))
    calls = world.port.calls
    assert calls.index("activate") < calls.index("export")


def test_the_projection_is_recomposed_before_the_export(world: World) -> None:
    # After a stroke Krita's projection can differ from its layers' composite, which the file
    # holds; the export and every read follow the refresh.
    document_id = world.open()
    node = world.port._tree(world.key(document_id))["nodes"][0]
    node["bounds_px"] = {"x": 0, "y": 0, "width": 8, "height": 4}
    world.port.calls.clear()
    world.save(document_id)
    calls = world.port.calls
    assert calls.index("refresh") < calls.index("export") < calls.index("node")


def _rename(saved: dict[str, Any]) -> None:
    saved["tree"]["nodes"][0]["name"] = "renamed"


def _hide(saved: dict[str, Any]) -> None:
    saved["tree"]["nodes"][0]["visible"] = False


def _new_id(saved: dict[str, Any]) -> None:
    saved["tree"]["nodes"][0]["id"] = layer_id(99, 99)


def _pixels(saved: dict[str, Any]) -> None:
    node_id = saved["tree"]["nodes"][0]["id"]
    saved["pixels"][node_id] = bytes(len(saved["pixels"][node_id]))


def _composite(saved: dict[str, Any]) -> None:
    saved["composite"] = bytes(len(saved["composite"]))


def _size(saved: dict[str, Any]) -> None:
    saved["size_px"] = [9, 4]


def _profile(saved: dict[str, Any]) -> None:
    saved["space"] = ("RGBA", "U8", "sRGB built-in")


@pytest.mark.parametrize(
    "change, field",
    [
        (_rename, "name"),
        (_hide, "visible"),
        (_new_id, "node"),
        (_pixels, "pixels"),
        (_composite, "composite"),
        (_size, "size_px"),
        (_profile, "profile_id"),
    ],
)
def test_any_difference_in_the_reopened_kra_fails_the_save(
    world: World, change: Any, field: str
) -> None:
    document_id = world.open()
    world.handle(document_id).before_change()
    # Pixels are compared over the nodes' bounds.
    world.port._tree(world.key(document_id))["nodes"][0]["bounds_px"] = {
        "x": 0,
        "y": 0,
        "width": 8,
        "height": 4,
    }
    world.port.on_export.append(change)
    body = world.refused("save", document_id)
    assert body["code"] == "SAVE_VERIFY_FAILED" and body["retryable"] is False
    assert field in {mismatch["field"] for mismatch in body["details"]["mismatches"]}
    assert world.files() == [] and world.handle(document_id).dirty is True
    assert world.handle(document_id).pending_save is None


@pytest.mark.parametrize("dropped, side", [(True, "live"), (False, "saved")])
def test_a_node_missing_on_either_side_fails_the_save(
    world: World, dropped: bool, side: str
) -> None:
    document_id = world.open()
    world.add(document_id, "extra")

    def change(found: dict[str, Any]) -> None:
        nodes = found["tree"]["nodes"]
        if dropped:
            nodes.pop()
        else:
            nodes.append({**nodes[0], "id": layer_id(99, 99), "name": "stray"})

    world.port.on_export.append(change)
    body = world.refused("save", document_id)
    found = [(m["field"], m["live"], m["saved"]) for m in body["details"]["mismatches"]]
    expected = ("node", "present", None) if side == "live" else ("node", None, "present")
    assert found == [expected]


def test_a_kra_compares_masks_and_every_field(world: World) -> None:
    document_id = world.open()
    layer = world.handle(document_id).document
    tree = world.port.tree(layer)
    top = tree["nodes"][0]["id"]
    world.add(document_id, "mask", top, type="transparencymask", alpha_locked=True)
    saved = world.save(document_id)
    assert saved["expected_losses"] == [] and saved["layers_preserved"] is True

    def unlock(found: dict[str, Any]) -> None:
        found["tree"]["nodes"][-1]["alpha_locked"] = False

    world.port.on_export.append(unlock)
    body = world.refused("save", document_id, "hero-r03.kra")
    assert [(m["name"], m["field"]) for m in body["details"]["mismatches"]] == [
        ("mask", "alpha_locked")
    ]


def test_a_kra_compares_a_transform_masks_params(world: World) -> None:
    document_id = world.open()
    top = world.port.tree(world.handle(document_id).document)["nodes"][0]["id"]
    mask = world.add(document_id, "translate", top, type="transformmask")
    assert world.save(document_id)["layers_preserved"] is True

    def moved(found: dict[str, Any]) -> None:
        found["transforms"][mask] = translations.translate_xml(5, 0)

    world.port.on_export.append(moved)
    body = world.refused("save", document_id, "hero-r03.kra")
    assert [(m["name"], m["field"]) for m in body["details"]["mismatches"]] == [
        ("translate", "transform_sha256")
    ]


def test_an_ora_lists_what_it_cannot_keep_and_matches_layers_by_place(world: World) -> None:
    document_id = world.open()
    top = world.port.tree(world.handle(document_id).document)["nodes"][0]["id"]
    group = world.add(document_id, "group", type="grouplayer")
    world.add(document_id, "group mask", group, type="transparencymask")
    world.add(document_id, "inner", group)
    world.add(document_id, "mask", top, type="filtermask")
    world.add(document_id, "locked alpha", alpha_locked=True)
    world.add(document_id, "clone", type="clonelayer")
    world.add(document_id, "adjust", type="filterlayer")
    saved = world.save(document_id, "hero-r02.ora")
    assert saved["format"] == "ora" and saved["composite_preserved"] is True
    assert saved["layers_preserved"] is False
    assert sorted(
        (loss["name"], loss["type"], loss["lost"]) for loss in saved["expected_losses"]
    ) == [
        ("adjust", "filter", "node"),
        ("clone", "clone", "type"),
        ("group mask", "transparency_mask", "node"),
        ("locked alpha", "paint", "alpha_locked"),
        ("mask", "filter_mask", "node"),
    ]


def test_an_ora_lists_the_opacity_its_rounding_lowers(world: World) -> None:
    document_id = world.open()
    world.add(document_id, "half", opacity=127, visible=False)
    world.add(document_id, "kept", opacity=128)
    saved = world.save(document_id, "hero-r02.ora")
    assert [(loss["name"], loss["lost"]) for loss in saved["expected_losses"]] == [
        ("half", "opacity")
    ]
    assert saving.ora_opacity(127) == 126 and saving.ora_opacity(254) == 253
    assert [saving.ora_opacity(value) for value in (0, 1, 2, 100, 128, 200, 255)] == [
        0,
        1,
        2,
        100,
        128,
        200,
        255,
    ]


def test_an_opacity_ora_rounding_cannot_explain_is_a_mismatch(world: World) -> None:
    document_id = world.open()
    world.add(document_id, "half", opacity=127)

    def lower(found: dict[str, Any]) -> None:
        found["tree"]["nodes"][-1]["opacity"] = 100

    world.port.on_export.append(lower)
    body = world.refused("save", document_id, "hero-r02.ora")
    assert [(m["name"], m["field"]) for m in body["details"]["mismatches"]] == [("half", "opacity")]


def test_a_loss_never_excuses_a_composite_difference(world: World) -> None:
    document_id = world.open()
    world.add(document_id, "adjust", type="filterlayer")
    world.port.on_export.append(_composite)
    body = world.refused("save", document_id, "hero-r02.ora")
    assert [m["field"] for m in body["details"]["mismatches"]] == ["composite"]
    assert world.files() == []


def test_an_ora_compares_what_it_stores(world: World) -> None:
    document_id = world.open()
    world.add(document_id, "clip", inherit_alpha=True)

    def lose_inherit_alpha(found: dict[str, Any]) -> None:
        found["tree"]["nodes"][-1]["inherit_alpha"] = False

    world.port.on_export.append(lose_inherit_alpha)
    body = world.refused("save", document_id, "hero-r02.ora")
    assert [(m["name"], m["field"]) for m in body["details"]["mismatches"]] == [
        ("clip", "inherit_alpha")
    ]


def test_the_reopened_file_krita_keeps_open_stays_owned_and_unsafe(world: World) -> None:
    document_id = world.open()
    world.port.close_works = False
    body = world.refused("save", document_id)
    assert body["code"] == "INTERNAL_ERROR"
    kept = world.handle(body["details"]["document_id"])
    assert kept.owned and kept.unsafe and kept.mode == "read_only"
    assert world.files() == []


def test_a_failure_reading_the_reopened_file_still_closes_it(world: World) -> None:
    document_id = world.open()

    def fail_once() -> None:
        world.port.fail["tree"] = RuntimeError("Krita raised")

    world.port.on_open.append(fail_once)
    with pytest.raises(RuntimeError):
        world.save(document_id)
    world.port.fail.clear()
    assert [handle.document_id for handle in world.registry.sync()] == [document_id]
    assert world.files() == []


def test_the_export_must_leave_the_document_on_its_own_file(world: World) -> None:
    document_id = world.open()
    key = world.key(document_id)

    def repoint(found: dict[str, Any]) -> None:
        world.port.live[key]["path"] = str(world.saves / "moved.kra")

    world.port.on_export.append(repoint)
    assert world.code("save", document_id) == "INTERNAL_ERROR"
    assert world.files() == []


def test_a_new_save_or_a_close_drops_the_one_never_finished(world: World) -> None:
    document_id = world.open()
    first = world.save(document_id)
    second = world.save(document_id, "hero-r03.kra")
    assert world.files() == [Path(second["written"]).name]
    # The second save says so, since a failure of its own can no longer mean nothing changed.
    assert (first["replaced_pending"], second["replaced_pending"]) == (False, True)
    assert world.code("finish", first) == "INVALID_ARGUMENT"
    world.run("document.close", {"document_id": document_id, "dirty_policy": "discard"})
    assert world.files() == []


def test_a_new_save_drops_one_never_finished_even_if_its_file_changed(world: World) -> None:
    document_id = world.open()
    first = world.save(document_id)
    Path(first["written"]).write_bytes(b"touched")
    second = world.save(document_id, "hero-r03.kra")
    assert world.files() == [Path(second["written"]).name]


def test_a_document_closed_by_hand_mid_finish_leaves_no_hidden_file(world: World) -> None:
    document_id = world.open()
    saved = world.save(document_id)
    assert world.files() == [Path(saved["written"]).name]
    del world.port.live[world.key(document_id)]
    assert world.code("finish", saved) == "DOCUMENT_NOT_FOUND"
    assert world.files() == [] and not world.saves.exists()


def test_a_created_document_has_no_baseline_to_touch(world: World) -> None:
    created = world.run(
        "document.create",
        {
            "name": "new",
            "size_px": [8, 4],
            "color_model": "RGBA",
            "depth": "U8",
            "profile_id": documents.SRGB_PROFILE,
            "background": "transparent",
        },
    )
    saved = world.save(created["document_id"])
    assert saved["baseline_untouched"] is None


def test_a_changed_source_is_reported_untouched_false(world: World) -> None:
    document_id = world.open()
    (world.art / "accepted" / "hero.kra").write_bytes(b"changed by hand")
    assert world.save(document_id)["baseline_untouched"] is False


def _source_hashes(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []
    real = files.sha256_of

    def counting(path: str) -> str:
        if path.endswith(os.path.join("accepted", "hero.kra")):
            seen.append(path)
        return real(path)

    monkeypatch.setattr(files, "sha256_of", counting)
    return seen


def test_an_untouched_source_is_answered_by_its_stat_with_no_hash(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    document_id = world.open()
    hashes = _source_hashes(monkeypatch)
    assert world.save(document_id)["baseline_untouched"] is True
    closing = {"document_id": document_id, "dirty_policy": "discard"}
    assert world.run("document.close", closing)["baseline_untouched"] is True
    assert hashes == []


def test_a_moved_stat_costs_a_hash_and_the_hash_decides(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    document_id = world.open()
    source = world.art / "accepted" / "hero.kra"
    hashes = _source_hashes(monkeypatch)
    os.utime(source, ns=(1, 1))
    assert world.save(document_id)["baseline_untouched"] is True
    assert len(hashes) == 1
    source.write_bytes(b"changed by hand")
    closing = {"document_id": document_id, "dirty_policy": "discard"}
    assert world.run("document.close", closing)["baseline_untouched"] is False
    assert len(hashes) == 2


def test_a_rewrite_that_restores_its_modification_time_is_still_seen(world: World) -> None:
    document_id = world.open()
    source = world.art / "accepted" / "hero.kra"
    before = source.stat()
    source.write_bytes(b"accepted ART")
    os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert source.stat().st_size == before.st_size
    assert world.save(document_id)["baseline_untouched"] is False


@pytest.mark.parametrize(
    ("mode", "hashing"), [("read_only", "check_source"), ("working_copy", "working_copy")]
)
def test_the_open_takes_the_stat_before_it_hashes(
    world: World, monkeypatch: pytest.MonkeyPatch, mode: str, hashing: str
) -> None:
    order: list[str] = []
    real_stat, real_hash = files.source_stat, getattr(files, hashing)

    def stat(path: str) -> Any:
        order.append("stat")
        return real_stat(path)

    def hash_it(*args: Any) -> Any:
        order.append("hash")
        return real_hash(*args)

    monkeypatch.setattr(files, "source_stat", stat)
    monkeypatch.setattr(files, hashing, hash_it)
    world.open(mode)
    assert order == ["stat", "hash"]
