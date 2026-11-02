import datetime
import errno
import hashlib
import os

from .errors import BridgeError, cleaned

CHUNK = 1 << 20
Stat = tuple[int, int, int, int]


def sha256_of(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_stat(path: str) -> Stat | None:
    # What a write moves; ctime too, which a restored modification time cannot hide from.
    try:
        found = os.stat(path)
    except OSError:
        return None
    return found.st_ino, found.st_size, found.st_mtime_ns, found.st_ctime_ns


def unchanged(path: str, expected: str, stat: Stat | None = None) -> bool:
    # A stat as it was taken answers at once; only one that moved costs a hash.
    if stat is not None and source_stat(path) == stat:
        return True
    try:
        return sha256_of(path) == expected
    except OSError:
        return False


def copy_name(source: str, now: datetime.datetime) -> str:
    stamp = now.astimezone(datetime.timezone.utc)
    return f"{stamp:%Y%m%dT%H%M%S}.{stamp.microsecond // 1000:03d}Z-{os.path.basename(source)}"


def make_folder(folder: str, field: str) -> list[str]:
    # The folders it made, deepest first; a failure removes what it made.
    missing = []
    while not os.path.isdir(folder):
        missing.append(folder)
        folder = os.path.dirname(folder)
    if not missing:
        return missing
    try:
        os.makedirs(missing[0], exist_ok=True)
    except OSError as problem:
        failure = BridgeError("IO_ERROR", f"{field} cannot be made: {problem}")
        cleaned(failure, unmake(missing))
        raise failure from problem
    return missing


def unmake(made: list[str]) -> bool:
    # Deepest first. A folder something else has filled stays, and is no longer ours to remove;
    # False only when one that is ours stays. A file in the path means there never was a folder.
    for folder in made:
        try:
            os.rmdir(folder)
        except (FileNotFoundError, NotADirectoryError):
            continue
        except OSError as problem:
            return problem.errno == errno.ENOTEMPTY
    return True


def remove(path: str) -> bool:
    # Whether nothing is left at the path.
    try:
        os.unlink(path)
    except OSError:
        pass
    return not os.path.lexists(path)


def working_copy(source: str, folder: str, expected: str, now: datetime.datetime) -> str:
    # The copy is made under its final name and never over another file; a failure removes it.
    target = os.path.join(folder, copy_name(source, now))
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
    except FileExistsError as problem:
        message = "A working copy of that name exists already; retry."
        raise BridgeError("FILE_EXISTS", message, True, {"path": target}) from problem
    except OSError as problem:
        raise BridgeError("IO_ERROR", f"The working copy cannot be made: {problem}") from problem
    try:
        digest = hashlib.sha256()
        # The descriptor is wrapped first, so a source that will not open never leaks it.
        with os.fdopen(fd, "wb") as writing, open(source, "rb") as reading:
            for chunk in iter(lambda: reading.read(CHUNK), b""):
                digest.update(chunk)
                writing.write(chunk)
        _matches(digest.hexdigest(), expected, "the source")
        _matches(sha256_of(target), expected, "the working copy")
    except OSError as problem:
        failure = BridgeError("IO_ERROR", f"The source cannot be copied: {problem}")
        cleaned(failure, remove(target))
        raise failure from problem
    except BaseException as raised:
        cleaned(raised, remove(target))
        raise
    return target


def check_source(path: str, expected: str) -> None:
    try:
        actual = sha256_of(path)
    except OSError as problem:
        raise BridgeError("IO_ERROR", f"The source cannot be read: {problem}") from problem
    _matches(actual, expected, "the source")


def _matches(actual: str, expected: str, which: str) -> None:
    if actual != expected:
        details = {"file": which, "expected": expected, "actual": actual}
        message = f"The SHA-256 of {which} differs from source_sha256."
        raise BridgeError("SOURCE_HASH_MISMATCH", message, False, details)
