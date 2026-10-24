import hashlib
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
