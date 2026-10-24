import hashlib
import os
import stat
from pathlib import Path

import pytest
from bridge_core import transfer
from bridge_core.errors import BridgeError


def test_a_buffer_is_written_whole_and_private(tmp_path: Path) -> None:
    spec = transfer.write(tmp_path / "transfer", b"\1\2\3\4" * 6, 3, 2, "BGRA8")
    path = Path(spec["path"])
    assert path.parent == tmp_path / "transfer"
    assert path.read_bytes() == b"\1\2\3\4" * 6
    assert spec == {"path": str(path), "size_px": [3, 2], "format": "BGRA8"}
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    transfer.remove(spec)
    assert not path.exists()


def test_a_buffer_of_the_wrong_size_is_never_written(tmp_path: Path) -> None:
    with pytest.raises(BridgeError):
        transfer.write(tmp_path, b"\0" * 5, 1, 1, "BGRA8")
    assert list(tmp_path.iterdir()) == []


def _mask(directory: Path, data: bytes, width: int, height: int) -> dict[str, object]:
    directory.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(data).hexdigest()
    path = directory / f"mask-{digest}.a8"
    path.write_bytes(data)
    return {"path": str(path), "size_px": [width, height], "format": "A8", "sha256": digest}


def test_a_mask_is_read_checked_and_deleted(tmp_path: Path) -> None:
    spec = _mask(tmp_path, bytes([0, 255, 255, 0]), 2, 2)
    assert transfer.take_mask(tmp_path, spec) == bytes([0, 255, 255, 0])
    assert list(tmp_path.iterdir()) == []


def test_a_mask_whose_bytes_changed_is_a_hash_mismatch(tmp_path: Path) -> None:
    spec = _mask(tmp_path, bytes([0, 255, 255, 0]), 2, 2)
    Path(str(spec["path"])).write_bytes(bytes([255, 255, 255, 0]))
    with pytest.raises(BridgeError) as refused:
        transfer.take_mask(tmp_path, spec)
    assert refused.value.body["code"] == "RESOURCE_HASH_MISMATCH"


def test_a_mask_outside_the_transfer_folder_is_refused(tmp_path: Path) -> None:
    spec = _mask(tmp_path / "elsewhere", bytes([0, 255]), 2, 1)
    with pytest.raises(BridgeError) as refused:
        transfer.take_mask(tmp_path / "transfer", spec)
    assert refused.value.body["code"] == "INVALID_ARGUMENT"
    assert Path(str(spec["path"])).exists()


def test_a_buffer_is_written_without_a_copy_of_its_own(tmp_path: Path) -> None:
    source = bytearray(b"\1\2\3\4")
    spec = transfer.write(tmp_path, memoryview(source), 1, 1, "BGRA8")
    assert Path(spec["path"]).read_bytes() == b"\1\2\3\4"


def test_a_transfer_folder_that_cannot_be_written_is_an_io_error(tmp_path: Path) -> None:
    blocked = tmp_path / "transfer"
    blocked.write_text("a file where the folder should be")
    with pytest.raises(BridgeError) as refused:
        transfer.write(blocked, b"\0" * 4, 1, 1, "BGRA8")
    assert refused.value.body["code"] == "IO_ERROR"


NOW = 1_000_000.0


def _aged(path: Path, seconds: float) -> Path:
    os.utime(path, (NOW - seconds,) * 2)
    return path


def test_a_file_or_mask_nobody_took_for_an_hour_goes_at_the_next_write(tmp_path: Path) -> None:
    old = transfer.write(tmp_path, b"\0" * 4, 1, 1, "BGRA8", now=NOW)
    recent = transfer.write(tmp_path, b"\0" * 4, 1, 1, "BGRA8", now=NOW)
    _aged(Path(old["path"]), transfer.STALE_S + 1)
    _aged(Path(recent["path"]), 60)
    old_mask = _aged(Path(str(_mask(tmp_path, b"\0", 1, 1)["path"])), transfer.STALE_S + 1)
    recent_mask = _aged(Path(str(_mask(tmp_path, b"\1", 1, 1)["path"])), 60)
    other = tmp_path / "notes.txt"
    other.write_text("not ours")
    _aged(other, transfer.STALE_S + 1)
    transfer.write(tmp_path, b"\0" * 4, 1, 1, "BGRA8", now=NOW)
    assert not Path(old["path"]).exists() and not old_mask.exists()
    assert Path(recent["path"]).exists() and recent_mask.exists() and other.exists()


def test_taking_a_mask_expires_what_nobody_took(tmp_path: Path) -> None:
    stale = _aged(Path(str(_mask(tmp_path, b"\0", 1, 1)["path"])), transfer.STALE_S + 1)
    spec = _mask(tmp_path, b"\0\1", 2, 1)
    assert transfer.take_mask(tmp_path, spec, now=NOW) == b"\0\1"
    assert list(tmp_path.iterdir()) == []
    assert not stale.exists()


def test_a_mask_that_is_gone_is_retryable(tmp_path: Path) -> None:
    spec = {"path": str(tmp_path / f"mask-{'0' * 64}.a8"), "size_px": [1, 1], "format": "A8"}
    with pytest.raises(BridgeError) as refused:
        transfer.take_mask(tmp_path, {**spec, "sha256": "0" * 64})
    assert (refused.value.body["code"], refused.value.body["retryable"]) == ("IO_ERROR", True)
