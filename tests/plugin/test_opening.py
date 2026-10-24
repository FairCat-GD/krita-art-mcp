import datetime
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest
from bridge_core import documents, files, opening
from bridge_core.errors import BridgeError
from bridge_core.jobs import Call
from bridge_core.registry import Registry
from fake_krita import FakePort, bgra, layer_id

A: dict[str, Any] = {"pid": 101, "started_at": "Sat Oct 24 10:00:00 2026"}
NOW = datetime.datetime(2026, 10, 24, 12, 30, 5, 123456, tzinfo=datetime.timezone.utc)
COPY = "20261024T123005.123Z-"


class World:
    def __init__(self, tmp: Path) -> None:
        self.data = tmp / "data"
        self.art = tmp / "art"
        (self.art / "accepted").mkdir(parents=True)
        self.work = self.art / "work"
        self.data.mkdir()
        roots = {"v": 1, "roots": [os.path.realpath(self.art)]}
        (self.data / "config.json").write_text(json.dumps(roots))
        self.port = FakePort()
        self.registry = Registry(self.port, lambda client: True)
        self.ops = documents.handlers(self.registry, self.port, self.data)
        self.ops.update(opening.handlers(self.registry, self.port, self.data, now=lambda: NOW))

    def source(self, name: str = "hero.kra", content: bytes = b"accepted art") -> tuple[str, str]:
        path = self.art / "accepted" / name
        path.write_bytes(content)
        return str(path), hashlib.sha256(content).hexdigest()

    def run(self, op: str, args: dict[str, Any]) -> dict[str, Any]:
        return self.ops[op](args, Call("op-x", "req-x", A))

    def open(self, name: str = "hero.kra", **changes: Any) -> dict[str, Any]:
        path, sha = self.source(name) if "source_path" not in changes else ("", "")
        args = {
            "source_path": path,
            "source_sha256": sha,
            "mode": "working_copy",
            "working_dir": str(self.work),
            "editable_layer_ids": None,
            "editable_layer_names": None,
            **changes,
        }
        return self.run("document.open", args)

    def code(self, **changes: Any) -> str:
        with pytest.raises(BridgeError) as refused:
            self.open(**changes)
        return str(refused.value.body["code"])

    def transfer_files(self) -> list[Path]:
        folder = self.data / "transfer"
        return sorted(folder.iterdir()) if folder.exists() else []


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


def test_a_working_copy_is_a_timestamped_copy_beside_no_source(world: World) -> None:
    world.port.files[str(world.work / f"{COPY}hero.kra")] = {"names": ["base", "rim"]}
    opened = world.open()
    copy = world.work / f"{COPY}hero.kra"
    assert opened["path"] == str(copy) and copy.read_bytes() == b"accepted art"
    assert opened["mode"] == "working_copy" and opened["working_copy"] is True
    assert opened["source_path"] == str(world.art / "accepted" / "hero.kra")
    assert world.port.opened == [str(copy)]
    # Every layer that existed at open is protected.
    assert [(layer["name"], layer["protected"]) for layer in opened["layers"]] == [
        ("base", True),
        ("rim", True),
    ]
    handle = world.registry.find(opened["document_id"])
    assert handle.owned and handle.path == str(copy)
    assert handle.source_sha256 == hashlib.sha256(b"accepted art").hexdigest()
    assert handle.baseline_id == opened["baseline_id"]
    assert opened["baseline_id"].startswith("baseline-") and len(opened["baseline_id"]) == 21
    # The as_opened composite waits in transfer/ for the server, as B, G, R, A.
    assert Path(opened["baseline"]["path"]).read_bytes() == bgra(8, 4)
    assert opened["baseline"]["format"] == "BGRA8"


def test_a_read_only_open_opens_the_source_itself_and_copies_nothing(world: World) -> None:
    path, sha = world.source()
    opened = world.open(source_path=path, source_sha256=sha, mode="read_only", working_dir=None)
    assert opened["path"] == path and opened["working_copy"] is False
    assert world.port.opened == [path] and not world.work.exists()
    assert world.registry.find(opened["document_id"]).mode == "read_only"


def test_a_missing_working_dir_is_made_inside_its_root(world: World) -> None:
    deeper = world.art / "work" / "rim pass"
    assert world.open(working_dir=str(deeper))["path"] == str(deeper / f"{COPY}hero.kra")


def test_a_working_copy_never_replaces_a_file(world: World) -> None:
    world.work.mkdir()
    taken = world.work / f"{COPY}hero.kra"
    taken.write_bytes(b"someone's work")
    with pytest.raises(BridgeError) as refused:
        world.open()
    # Nothing was made, so a retry may run.
    assert refused.value.body["code"] == "FILE_EXISTS" and refused.value.body["retryable"]
    assert taken.read_bytes() == b"someone's work"
    assert world.port.opened == []


def test_the_working_dir_is_never_the_sources_own_folder(world: World) -> None:
    assert world.code(working_dir=str(world.art / "accepted")) == "INVALID_ARGUMENT"
    assert sorted(os.listdir(world.art / "accepted")) == ["hero.kra"]


def test_a_source_that_differs_from_its_hash_leaves_no_copy(world: World) -> None:
    path, _ = world.source()
    with pytest.raises(BridgeError) as refused:
        world.open(source_path=path, source_sha256="0" * 64)
    assert refused.value.body["code"] == "SOURCE_HASH_MISMATCH"
    assert refused.value.body["details"]["file"] == "the source"
    assert os.listdir(world.work) == []
    assert world.code(
        source_path=path, source_sha256="0" * 64, mode="read_only", working_dir=None
    ) == ("SOURCE_HASH_MISMATCH")


def test_a_source_that_cannot_be_read_leaks_no_descriptor(world: World) -> None:
    path, sha = world.source()
    os.chmod(path, 0)
    before = len(os.listdir("/dev/fd"))
    try:
        assert world.code(source_path=path, source_sha256=sha) == "IO_ERROR"
    finally:
        os.chmod(path, 0o644)
    assert len(os.listdir("/dev/fd")) == before
    assert os.listdir(world.work) == []


def test_a_copy_that_reads_back_differently_is_removed(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(files, "sha256_of", lambda path: "f" * 64)
    with pytest.raises(BridgeError) as refused:
        world.open()
    assert refused.value.body["code"] == "SOURCE_HASH_MISMATCH"
    assert refused.value.body["details"]["file"] == "the working copy"
    assert os.listdir(world.work) == []


@pytest.mark.parametrize(
    ("relative", "field"),
    [("../outside/hero.kra", "source_path"), ("../outside", "working_dir")],
)
def test_the_plugin_refuses_paths_outside_every_root(
    world: World, relative: str, field: str
) -> None:
    outside = world.art.parent / "outside"
    outside.mkdir()
    (outside / "hero.kra").write_bytes(b"accepted art")
    path, sha = world.source()
    changes: dict[str, Any] = {"source_path": path, "source_sha256": sha}
    changes[field] = str(world.art / relative)
    with pytest.raises(BridgeError) as refused:
        world.open(**changes)
    assert refused.value.body["code"] == "PATH_NOT_ALLOWED"
    assert refused.value.body["details"] == {"field": field}
    assert world.port.opened == [] and not world.work.exists()


def test_a_path_must_name_its_real_format(world: World) -> None:
    psd = world.art / "accepted" / "hero.psd"
    psd.write_bytes(b"psd")
    (world.art / "accepted" / "hero.png").symlink_to(psd)
    ora = world.art / "accepted" / "rim.ora"
    ora.write_bytes(b"ora")
    (world.art / "accepted" / "rim.png").symlink_to(ora)
    sha = hashlib.sha256(b"psd").hexdigest()
    path = str(world.art / "accepted" / "hero.png")
    assert world.code(source_path=path, source_sha256=sha) == "UNSUPPORTED_CAPABILITY"
    path = str(world.art / "accepted" / "rim.png")
    assert world.code(source_path=path, source_sha256=sha) == "INVALID_ARGUMENT"
    path = str(world.art / "accepted" / "hero.psd")
    assert world.code(source_path=path, source_sha256=sha) == "UNSUPPORTED_CAPABILITY"


def _layers(world: World, name: str, names: list[str]) -> None:
    world.port.files[str(world.work / f"{COPY}{name}")] = {"names": names}


def test_editable_layer_ids_resume_a_kras_own_layers(world: World) -> None:
    _layers(world, "hero.kra", ["base", "fix"])
    opened = world.open(editable_layer_ids=[layer_id(1, 1)])
    assert [layer["protected"] for layer in opened["layers"]] == [True, False]
    assert world.registry.find(opened["document_id"]).protected == {layer_id(1, 0)}


def test_editable_layer_names_resume_an_oras_own_layers(world: World) -> None:
    _layers(world, "rim.ora", ["base", "fix"])
    opened = world.open("rim.ora", editable_layer_names=["fix"])
    assert [layer["protected"] for layer in opened["layers"]] == [True, False]


@pytest.mark.parametrize(
    ("name", "changes", "code"),
    [
        (
            "hero.kra",
            {"editable_layer_ids": ["00000000-0000-4000-8000-999999999999"]},
            "LAYER_NOT_FOUND",
        ),
        ("rim.ora", {"editable_layer_names": ["nobody"]}, "LAYER_NOT_FOUND"),
        ("rim.ora", {"editable_layer_names": ["twice"]}, "INVALID_ARGUMENT"),
        ("rim.ora", {"editable_layer_ids": [layer_id(1, 0)]}, "INVALID_ARGUMENT"),
        ("hero.kra", {"editable_layer_names": ["base"]}, "INVALID_ARGUMENT"),
        ("rim.ora", {"editable_layer_names": ["fix", "fix"]}, "INVALID_ARGUMENT"),
        ("hero.kra", {"editable_layer_ids": ["NOT-A-UUID"]}, "INVALID_ARGUMENT"),
        ("hero.kra", {"mode": "read_only"}, "INVALID_ARGUMENT"),
        ("hero.kra", {"working_dir": None}, "INVALID_ARGUMENT"),
        ("hero.kra", {"mode": "edit"}, "INVALID_ARGUMENT"),
        ("hero.psd", {}, "UNSUPPORTED_CAPABILITY"),
    ],
    ids=[
        "unknown id",
        "unknown name",
        "ambiguous name",
        "ids for an ORA",
        "names for a KRA",
        "a name twice",
        "a malformed id",
        "read_only with a working_dir",
        "working_copy without one",
        "another mode",
        "another format",
    ],
)
def test_the_editable_lists_and_the_mode_are_exact(
    world: World, name: str, changes: dict[str, Any], code: str
) -> None:
    _layers(world, name, ["base", "twice", "twice", "fix"])
    assert world.code(name=name, **changes) == code
    assert world.registry.sync() == []
    assert not world.work.exists() or os.listdir(world.work) == []
    assert world.transfer_files() == []


@pytest.mark.parametrize(
    "step", ["open", "show", "tree", "composite", "colour space", "another frame"]
)
def test_a_failure_after_the_copy_undoes_everything_in_the_same_job(
    world: World, step: str
) -> None:
    if step == "colour space":
        world.port.files[str(world.work / f"{COPY}hero.kra")] = {
            "space": ("GRAYA", "U8", "Gray-D50-elle-V2-srgbtrc.icc")
        }
        code = "COLOR_PROFILE_MISMATCH"
    elif step == "another frame":
        # The baseline is frame 0, as every read is.
        world.port.files[str(world.work / f"{COPY}hero.kra")] = {
            "current_time": 5,
            "animated": True,
        }
        code = "UNSUPPORTED_CAPABILITY"
    else:
        world.port.fail[step] = BridgeError("IO_ERROR", f"{step} failed")
        code = "IO_ERROR"
    assert world.code() == code
    assert os.listdir(world.work) == []
    assert world.transfer_files() == []
    assert world.registry.sync() == [] and world.port.live == {}
    assert world.port.closed == ([] if step == "open" else [1])


def test_a_failure_once_the_composite_is_out_removes_its_transfer_file(world: World) -> None:
    def failing() -> str:
        raise BridgeError("INTERNAL_ERROR", "no id")

    world.ops.update(opening.handlers(world.registry, world.port, world.data, lambda: NOW, failing))
    assert world.code() == "INTERNAL_ERROR"
    assert world.transfer_files() == [] and os.listdir(world.work) == []
    assert world.registry.sync() == [] and world.port.closed == [1]


@pytest.mark.parametrize("step", ["show", "composite"])
def test_a_document_krita_will_not_close_stays_owned_and_unsafe(world: World, step: str) -> None:
    world.port.close_works = False
    world.port.fail[step] = BridgeError("IO_ERROR", f"{step} failed")
    with pytest.raises(BridgeError) as refused:
        world.open()
    kept = refused.value.body["details"]["document_id"]
    handle = world.registry.find(kept)
    # A discard close can still end it: it is the agent's, not the owner's.
    assert handle.owned and handle.unsafe and handle.mode == "working_copy"
    assert os.listdir(world.work) == [f"{COPY}hero.kra"]


def test_a_refusal_at_job_start_copies_nothing(world: World) -> None:
    world.port.refuse = BridgeError("KRITA_MODAL_DIALOG", "a dialog", True)
    assert world.code() == "KRITA_MODAL_DIALOG"
    assert not world.work.exists()


def test_a_created_document_shares_the_unclosable_fallback(world: World) -> None:
    world.port.close_works = False
    world.port.layer = {**world.port.layer, "alpha_at_origin": 255}
    args = {
        "name": "sketch",
        "size_px": [64, 32],
        "color_model": "RGBA",
        "depth": "U8",
        "profile_id": documents.SRGB_PROFILE,
        "background": "transparent",
    }
    with pytest.raises(BridgeError) as refused:
        world.run("document.create", args)
    handle = world.registry.find(refused.value.body["details"]["document_id"])
    assert handle.owned and handle.unsafe and handle.mode == "new"


def test_close_reports_whether_the_source_is_untouched(world: World) -> None:
    first = world.open()
    closed = world.run(
        "document.close", {"document_id": first["document_id"], "dirty_policy": "refuse"}
    )
    assert closed["baseline_untouched"] is True and closed["baseline_id"] == first["baseline_id"]
    second = world.open(working_dir=str(world.work / "2"))
    (world.art / "accepted" / "hero.kra").write_bytes(b"changed by hand")
    closed = world.run(
        "document.close", {"document_id": second["document_id"], "dirty_policy": "refuse"}
    )
    assert closed["baseline_untouched"] is False
    third = world.open(working_dir=str(world.work / "3"))
    (world.art / "accepted" / "hero.kra").unlink()
    closed = world.run(
        "document.close", {"document_id": third["document_id"], "dirty_policy": "refuse"}
    )
    assert closed["baseline_untouched"] is False


def test_the_bridge_lists_the_live_baselines(world: World) -> None:
    opened = world.open()
    world.run(
        "document.create",
        {
            "name": "sketch",
            "size_px": [8, 8],
            "color_model": "RGBA",
            "depth": "U8",
            "profile_id": documents.SRGB_PROFILE,
            "background": "transparent",
        },
    )
    assert world.run("document.baselines", {}) == {"baseline_ids": [opened["baseline_id"]]}
    world.run("document.close", {"document_id": opened["document_id"], "dirty_policy": "discard"})
    assert world.run("document.baselines", {}) == {"baseline_ids": []}
