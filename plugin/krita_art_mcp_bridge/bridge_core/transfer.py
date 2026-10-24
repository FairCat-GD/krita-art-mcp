import hashlib
import os
import re
import secrets
import stat
from pathlib import Path
from typing import Any

from .errors import BridgeError
from .paths import private_dir

# Bytes per pixel of each layout a transfer file holds.
FORMATS = {"BGRA8": 4, "A8": 1}
MASK_NAME = re.compile(r"^mask-([0-9a-f]{64})\.a8$")


def sweep(directory: Path) -> None:
    # Whatever is left belongs to an ended Krita session, whose server will never read it.
    private_dir(directory)
    for entry in os.scandir(directory):
        if entry.is_symlink() or entry.is_file(follow_symlinks=False):
            os.unlink(entry.path)


def write(directory: Path, data: bytes, width: int, height: int, fmt: str) -> dict[str, Any]:
    expected = width * height * FORMATS[fmt]
    if len(data) != expected:
        details = {"bytes": len(data), "expected": expected}
        raise BridgeError(
            "INTERNAL_ERROR", "Krita returned a buffer of the wrong size.", False, details
        )
    private_dir(directory)
    path = directory / f"{secrets.token_hex(16)}.raw"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return {"path": str(path), "size_px": [width, height], "format": fmt}


def remove(spec: dict[str, Any] | None) -> None:
    if spec is not None:
        Path(spec["path"]).unlink(missing_ok=True)


def take_mask(directory: Path, spec: Any) -> bytes:
    # A mask from the server, named by its SHA-256; read once, checked, then deleted.
    if (
        not isinstance(spec, dict)
        or set(spec) != {"path", "size_px", "format", "sha256"}
        or spec["format"] != "A8"
        or not isinstance(spec["path"], str)
        or not _size_ok(spec["size_px"])
    ):
        raise BridgeError("INVALID_ARGUMENT", "The mask's transfer description is malformed.")
    real = os.path.realpath(spec["path"])
    name = MASK_NAME.match(os.path.basename(real))
    if os.path.dirname(real) != os.path.realpath(directory) or name is None:
        raise BridgeError("INVALID_ARGUMENT", "A mask must be a transfer file the server wrote.")
    width, height = spec["size_px"]
    try:
        fd = os.open(real, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as problem:
        raise BridgeError("IO_ERROR", f"The mask cannot be read: {problem}") from problem
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_size != width * height:
        os.close(fd)
        raise BridgeError("INVALID_ARGUMENT", "The mask file is not width x height bytes.")
    with os.fdopen(fd, "rb") as stream:
        data = stream.read()
    os.unlink(real)
    if hashlib.sha256(data).hexdigest() != spec["sha256"] or name.group(1) != spec["sha256"]:
        details = {"sha256": spec["sha256"]}
        raise BridgeError(
            "RESOURCE_HASH_MISMATCH", "The mask differs from its SHA-256.", False, details
        )
    return data


def _size_ok(size: Any) -> bool:
    return (
        isinstance(size, list)
        and len(size) == 2
        and all(isinstance(side, int) and not isinstance(side, bool) and side >= 0 for side in size)
    )
