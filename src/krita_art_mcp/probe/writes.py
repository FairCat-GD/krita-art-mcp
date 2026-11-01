import fnmatch
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

# N-04's list of what may be written: the data directory's own files, by path below it.
DATA_FILES = (
    "bridge.json",
    "logs/plugin.log*",
    "transfer/*",
    "harness/*",
    "captures/*",
    "baselines/*",
    "journal/*",
)
# What Krita itself leaves in its temp folder and beside a document it has never saved.
KRITA_FILES = (
    "KRITA_SWAP_FILE_*",
    "KritaFrameCache*",
    "krita-stderr.log",
    "krita-opengl.txt",
    "qtsingleapp*",
    ".krita-*-autosave.kra",
    "krita-*-autosave.kra",
)
# Names that can only be this project's or the documents it handles.
OUR_NAMES = ("*krita-art*", "*krita_art*", "*probe*", "*.saving*", "*.ora", "*.kra")


@dataclass(frozen=True)
class Place:
    folder: Path
    # Every file below it with its stat, or only its own entries' names.
    deep: bool = False
    allowed: tuple[str, ...] = ()
    # Other apps write here too and a listing cannot say who wrote what, so only these names
    # count; None counts every name.
    ours: tuple[str, ...] | None = None


Listing = dict[Place, dict[str, tuple[int, int]]]


def places(data_dir: Path) -> list[Place]:
    home = Path.home()
    library = home / "Library"
    return [
        Place(data_dir, deep=True, allowed=DATA_FILES),
        # A relative path lands here.
        Place(Path.cwd()),
        # Other apps keep hidden files in the home folder, and rarely anything else.
        Place(home, allowed=KRITA_FILES, ours=("[!.]*", *OUR_NAMES)),
        Place(_krita_temp(), allowed=KRITA_FILES, ours=OUR_NAMES),
        Place(library / "Application Support", ours=OUR_NAMES),
        Place(library / "Preferences", ours=OUR_NAMES),
    ]


def _krita_temp() -> Path:
    # Krita started from the Dock uses this folder, whatever this shell's TMPDIR says.
    out = subprocess.run(
        ["getconf", "DARWIN_USER_TEMP_DIR"],
        capture_output=True,
        text=True,
        check=True,
        stdin=subprocess.DEVNULL,
    ).stdout
    return Path(out.strip())


def take(wanted: list[Place]) -> Listing:
    return {place: _listed(place) for place in wanted}


def strays(before: Listing, after: Listing) -> list[str]:
    # New names anywhere; in a deep place, changed and removed files too.
    found = []
    for place, now in after.items():
        was = before.get(place, {})
        moved = {name for name in now if name not in was}
        if place.deep:
            moved |= {name for name, stat in now.items() if was.get(name, stat) != stat}
            moved |= set(was) - set(now)
        found += [str(place.folder / name) for name in moved if _stray(place, name)]
    return sorted(found)


def _stray(place: Place, name: str) -> bool:
    if _matches(name, place.allowed):
        return False
    return place.ours is None or _matches(name, place.ours)


def _matches(name: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatchcase(name, pattern) for pattern in patterns)


def _listed(place: Place) -> dict[str, tuple[int, int]]:
    if not place.folder.is_dir():
        return {}
    if not place.deep:
        return {entry.name: (0, 0) for entry in os.scandir(place.folder)}
    listed = {}
    for folder, _, files in os.walk(place.folder):
        for name in files:
            path = Path(folder) / name
            # A transfer file can go between the walk and the stat.
            try:
                stat = path.stat()
            except FileNotFoundError:
                continue
            listed[str(path.relative_to(place.folder))] = (stat.st_mtime_ns, stat.st_size)
    return listed
