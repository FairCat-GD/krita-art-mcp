import hashlib
import os
import stat
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

# Bytes per pixel of each layout a transfer file holds; the plugin holds an equal copy.
FORMATS = {"BGRA8": 4, "A8": 1}

Pixels = NDArray[np.uint8]


class TransferError(Exception):
    pass


def take(directory: Path, spec: Any) -> Pixels:
    # Reads a file the plugin wrote; the caller deletes it once what it made is on disk.
    path, width, height, depth = _checked(directory, spec)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as problem:
        raise TransferError(f"the transfer file cannot be read: {problem}") from problem
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_size != width * height * depth:
        os.close(fd)
        raise TransferError("the transfer file is not the size its description gives")
    with os.fdopen(fd, "rb") as stream:
        if info.st_size == 0:
            return np.zeros((height, width, depth), dtype=np.uint8)
        mapped = np.memmap(stream, dtype=np.uint8, mode="r", shape=(height, width, depth))
        # Integer RGBA arrives B, G, R, A (K12). Both branches copy, so the mapping can close.
        if spec["format"] == "BGRA8":
            pixels = np.asarray(mapped[..., [2, 1, 0, 3]])
        else:
            pixels = np.array(mapped)
        del mapped
    return pixels


def discard(directory: Path, spec: Any) -> None:
    path, _, _, _ = _checked(directory, spec)
    path.unlink(missing_ok=True)


def put_mask(directory: Path, mask: Pixels) -> dict[str, Any]:
    # Named by its SHA-256, so the op that sends it is a pure function of the tool's arguments.
    if mask.ndim != 2 or mask.dtype != np.uint8:
        raise TransferError("a mask is a 2-D array of 8-bit values")
    data = np.ascontiguousarray(mask).tobytes()
    digest = hashlib.sha256(data).hexdigest()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = directory / f"mask-{digest}.a8"
    if not path.exists():
        temp = directory / f".mask-{digest}.{os.getpid()}.tmp"
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
            os.replace(temp, path)
        except BaseException:
            temp.unlink(missing_ok=True)
            raise
    height, width = mask.shape
    return {"path": str(path), "size_px": [width, height], "format": "A8", "sha256": digest}


def _checked(directory: Path, spec: Any) -> tuple[Path, int, int, int]:
    # A path from the bridge is trusted only directly inside the transfer folder.
    if not isinstance(spec, dict) or spec.get("format") not in FORMATS:
        raise TransferError("the transfer description is malformed")
    size, raw = spec.get("size_px"), spec.get("path")
    if (
        not isinstance(raw, str)
        or not isinstance(size, list)
        or len(size) != 2
        or not all(
            isinstance(side, int) and not isinstance(side, bool) and side >= 0 for side in size
        )
    ):
        raise TransferError("the transfer description is malformed")
    path = Path(raw)
    if not path.is_absolute() or path.parent.resolve() != directory.resolve():
        raise TransferError("the transfer file is not in the transfer folder")
    return path, size[0], size[1], FORMATS[spec["format"]]
