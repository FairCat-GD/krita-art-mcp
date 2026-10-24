import logging
import os
import stat
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from bridge_core import transfer as plugin_transfer
from bridge_core.errors import BridgeError
from fake_krita import bgra

from krita_art_mcp import baselines, transfer
from krita_art_mcp.bridge_client import BridgeClient, Done, Failed, Outcome
from krita_art_mcp.errors import error_body
from krita_art_mcp.paths import Places


@pytest.fixture
def places(tmp_path: Path) -> Places:
    return Places.under(tmp_path / "data", tmp_path / "server")


def _written(places: Places, width: int = 3, height: int = 2) -> dict[str, Any]:
    return plugin_transfer.write(places.transfer_dir, bgra(width, height), width, height, "BGRA8")


def test_the_plugin_writes_bgra_and_the_server_reads_rgba(places: Places) -> None:
    spec = _written(places)
    assert spec["size_px"] == [3, 2] and spec["format"] == "BGRA8"
    assert stat.S_IMODE(Path(spec["path"]).stat().st_mode) == 0o600
    pixels = transfer.take(places.transfer_dir, spec)
    raw = np.frombuffer(bgra(3, 2), dtype=np.uint8).reshape(2, 3, 4)
    assert pixels.shape == (2, 3, 4) and type(pixels) is np.ndarray
    assert (pixels[..., 0] == raw[..., 2]).all() and (pixels[..., 2] == raw[..., 0]).all()
    assert (pixels[..., 1] == raw[..., 1]).all() and (pixels[..., 3] == raw[..., 3]).all()
    # Reading never deletes; the caller does, once what it made is safe.
    assert Path(spec["path"]).exists()
    transfer.discard(places.transfer_dir, spec)
    assert not Path(spec["path"]).exists()


def test_a_selection_arrives_as_one_byte_per_pixel(places: Places) -> None:
    spec = plugin_transfer.write(places.transfer_dir, bytes([0, 128, 255, 7]), 2, 2, "A8")
    assert transfer.take(places.transfer_dir, spec)[..., 0].tolist() == [[0, 128], [255, 7]]


def test_the_plugin_refuses_a_buffer_of_the_wrong_size(places: Places) -> None:
    with pytest.raises(BridgeError) as refused:
        plugin_transfer.write(places.transfer_dir, b"\0" * 7, 1, 2, "BGRA8")
    assert refused.value.body["code"] == "INTERNAL_ERROR"


@pytest.mark.parametrize("break_it", ["size", "folder", "symlink", "directory", "format"])
def test_the_server_reads_only_a_regular_file_of_the_right_size_in_the_folder(
    places: Places, tmp_path: Path, break_it: str
) -> None:
    spec = _written(places)
    path = Path(spec["path"])
    if break_it == "size":
        spec["size_px"] = [3, 3]
    elif break_it == "folder":
        outside = tmp_path / "elsewhere.raw"
        outside.write_bytes(path.read_bytes())
        spec["path"] = str(outside)
    elif break_it == "symlink":
        link = places.transfer_dir / "link.raw"
        link.symlink_to(path)
        spec["path"] = str(link)
    elif break_it == "directory":
        path.unlink()
        path.mkdir()
    else:
        spec["format"] = "RGBA16"
    with pytest.raises(transfer.TransferError):
        transfer.take(places.transfer_dir, spec)


def test_the_bridge_sweeps_leftover_transfer_files_and_keeps_the_folder_private(
    places: Places,
) -> None:
    spec = _written(places)
    (places.transfer_dir / "dangling.raw").symlink_to(places.transfer_dir / "gone")
    plugin_transfer.sweep(places.transfer_dir)
    assert not Path(spec["path"]).exists()
    assert list(places.transfer_dir.iterdir()) == []
    assert stat.S_IMODE(places.transfer_dir.stat().st_mode) == 0o700


def test_a_mask_goes_to_the_plugin_named_by_its_hash_and_is_read_once(places: Places) -> None:
    mask = np.array([[0, 255, 255], [0, 0, 255]], dtype=np.uint8)
    spec = transfer.put_mask(places.transfer_dir, mask)
    assert Path(spec["path"]).name == f"mask-{spec['sha256']}.a8"
    assert transfer.put_mask(places.transfer_dir, mask) == spec
    assert spec["size_px"] == [3, 2]
    assert plugin_transfer.take_mask(places.transfer_dir, spec) == mask.tobytes()
    assert not Path(spec["path"]).exists()


@pytest.mark.parametrize("break_it", ["hash", "folder", "size"])
def test_the_plugin_refuses_a_mask_that_is_not_what_the_server_sent(
    places: Places, tmp_path: Path, break_it: str
) -> None:
    spec = transfer.put_mask(places.transfer_dir, np.zeros((2, 2), dtype=np.uint8))
    code = "INVALID_ARGUMENT"
    if break_it == "hash":
        Path(spec["path"]).write_bytes(b"\1\0\0\0")
        code = "RESOURCE_HASH_MISMATCH"
    elif break_it == "folder":
        moved = tmp_path / Path(spec["path"]).name
        os.replace(spec["path"], moved)
        spec["path"] = str(moved)
    else:
        spec["size_px"] = [4, 2]
    with pytest.raises(BridgeError) as refused:
        plugin_transfer.take_mask(places.transfer_dir, spec)
    assert refused.value.body["code"] == code


def test_a_baseline_is_kept_as_rgba_before_its_transfer_file_goes(places: Places) -> None:
    spec = _written(places)
    baselines.adopt(places, "baseline-0123456789ab", spec)
    kept = places.baselines_dir / "baseline-0123456789ab.npy"
    pixels = baselines.load(places.baselines_dir, "baseline-0123456789ab")
    assert pixels is not None and pixels.dtype == np.uint8
    assert (pixels == transfer_rgba(3, 2)).all()
    assert stat.S_IMODE(kept.stat().st_mode) == 0o600
    assert not Path(spec["path"]).exists()
    assert [entry.name for entry in places.baselines_dir.iterdir()] == [kept.name]
    # A second adoption of the same outcome changes nothing.
    baselines.adopt(places, "baseline-0123456789ab", spec)
    assert kept.exists()


def transfer_rgba(width: int, height: int) -> Any:
    return np.frombuffer(bgra(width, height), dtype=np.uint8).reshape(height, width, 4)[
        ..., [2, 1, 0, 3]
    ]


def test_a_baseline_that_cannot_be_written_keeps_its_transfer_file(
    places: Places, caplog: pytest.LogCaptureFixture
) -> None:
    spec = _written(places)
    places.baselines_dir.parent.mkdir(parents=True)
    places.baselines_dir.write_text("a file where the folder should be")
    with caplog.at_level(logging.ERROR):
        baselines.adopt(places, "baseline-0123456789ab", spec)
    assert Path(spec["path"]).exists()
    assert "was not kept" in caplog.text


@pytest.mark.parametrize(
    "baseline_id", ["../../escape", "baseline-0123", None, "baseline-ZZZZZZZZZZZZ"]
)
def test_a_baseline_id_the_plugin_would_never_mint_names_no_file(
    places: Places, baseline_id: Any
) -> None:
    assert baselines.path_of(places.baselines_dir, baseline_id) is None
    spec = _written(places)
    baselines.adopt(places, baseline_id, spec)
    baselines.remove(places, baseline_id)
    assert not places.baselines_dir.exists()


class _Baselines(BridgeClient):
    def __init__(self, outcome: Outcome, when_asked: Any = None) -> None:
        super().__init__()
        self.answer = outcome
        self.when_asked = when_asked

    def call(self, op: str, args: dict[str, Any] | None = None, **kwargs: Any) -> Outcome:
        assert op == "document.baselines"
        if self.when_asked is not None:
            self.when_asked()
        return self.answer


def _baseline(places: Places, baseline_id: str) -> Path:
    places.baselines_dir.mkdir(parents=True, exist_ok=True)
    path = places.baselines_dir / f"{baseline_id}.npy"
    path.write_bytes(b"npy")
    return path


def test_the_sweep_removes_baselines_whose_document_is_gone(places: Places) -> None:
    live = _baseline(places, "baseline-aaaaaaaaaaaa")
    orphan = _baseline(places, "baseline-bbbbbbbbbbbb")
    other = places.baselines_dir / "baseline-dddddddddddd.png"
    other.write_text("not a baseline")

    def written_meanwhile() -> None:
        _baseline(places, "baseline-cccccccccccc")

    client = _Baselines(Done({"baseline_ids": ["baseline-aaaaaaaaaaaa"]}, None), written_meanwhile)
    assert baselines.sweep(client, places.baselines_dir) == 1
    assert live.exists() and other.exists() and not orphan.exists()
    # Listed before the bridge answered, so a baseline written meanwhile is never taken.
    assert (places.baselines_dir / "baseline-cccccccccccc.npy").exists()


def test_with_krita_closed_every_baseline_is_an_orphan(places: Places) -> None:
    orphan = _baseline(places, "baseline-aaaaaaaaaaaa")
    closed = Failed(error_body("KRITA_NOT_RUNNING"))
    assert baselines.sweep(_Baselines(closed), places.baselines_dir) == 1
    assert not orphan.exists()


def test_a_bridge_that_cannot_say_sweeps_nothing(places: Places) -> None:
    kept = _baseline(places, "baseline-aaaaaaaaaaaa")
    busy = Failed(error_body("KRITA_MODAL_DIALOG"))
    assert baselines.sweep(_Baselines(busy), places.baselines_dir) == 0
    assert kept.exists()


def test_a_transfer_file_another_server_took_is_a_warning_not_a_traceback(
    places: Places, caplog: pytest.LogCaptureFixture
) -> None:
    spec = _written(places)
    Path(spec["path"]).unlink()
    with caplog.at_level(logging.WARNING):
        baselines.adopt(places, "baseline-0123456789ab", spec)
    [record] = caplog.records
    assert record.levelno == logging.WARNING and record.exc_info is None
    assert not places.baselines_dir.exists()


def test_the_formats_both_sides_know_agree() -> None:
    from bridge_core import opening

    from krita_art_mcp.tools import documents

    assert transfer.FORMATS == plugin_transfer.FORMATS
    assert documents.FORMATS == opening.FORMATS
