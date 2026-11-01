from pathlib import Path

import pytest

from krita_art_mcp.probe import writes
from krita_art_mcp.probe.writes import Place


def _data(tmp_path: Path) -> Place:
    folder = tmp_path / "data"
    (folder / "logs").mkdir(parents=True)
    (folder / "config.json").write_text("{}")
    (folder / "logs" / "plugin.log").write_text("started\n")
    return Place(folder, deep=True, allowed=writes.DATA_FILES)


def _write(folder: Path, name: str, text: str = "new") -> None:
    path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.mark.parametrize(
    "name",
    [
        "bridge.json",
        "logs/plugin.log",
        "logs/plugin.log.1",
        "transfer/op-1.raw",
        "harness/work/deep/copy.ora",
        "captures/2026-10-31/op-1.png",
        "baselines/.tmp.npy.tmp",
        "journal/2026-10-31.jsonl",
        "journal/args/2026-10-31/op-1.json",
    ],
)
def test_the_data_directory_takes_what_the_list_names(tmp_path: Path, name: str) -> None:
    place = _data(tmp_path)
    before = writes.take([place])
    _write(place.folder, name)
    assert writes.strays(before, writes.take([place])) == []


def test_any_other_file_in_the_data_directory_is_stray_by_its_full_path(tmp_path: Path) -> None:
    place = _data(tmp_path)
    before = writes.take([place])
    _write(place.folder, "elsewhere/copy.kra")
    assert writes.strays(before, writes.take([place])) == [str(place.folder / "elsewhere/copy.kra")]


def test_a_changed_config_is_stray_even_at_its_old_size(tmp_path: Path) -> None:
    place = _data(tmp_path)
    before = writes.take([place])
    (place.folder / "config.json").write_text("[]")
    assert writes.strays(before, writes.take([place])) == [str(place.folder / "config.json")]


def test_a_removed_config_is_stray(tmp_path: Path) -> None:
    place = _data(tmp_path)
    before = writes.take([place])
    (place.folder / "config.json").unlink()
    assert writes.strays(before, writes.take([place])) == [str(place.folder / "config.json")]


def test_a_place_that_lists_names_counts_only_new_ones(tmp_path: Path) -> None:
    place = Place(tmp_path)
    _write(tmp_path, "there.txt")
    before = writes.take([place])
    _write(tmp_path, "there.txt", "changed by someone else")
    assert writes.strays(before, writes.take([place])) == []
    _write(tmp_path, "new.txt")
    assert writes.strays(before, writes.take([place])) == [str(tmp_path / "new.txt")]


def test_a_shared_folder_counts_only_our_names_and_never_kritas_own(tmp_path: Path) -> None:
    place = Place(tmp_path, allowed=writes.KRITA_FILES, ours=writes.OUR_NAMES)
    before = writes.take([place])
    for name in (
        "com.other.app",
        "KRITA_SWAP_FILE_1a2b",
        "KritaFrameCache9",
        ".krita-1-autosave.kra",
    ):
        _write(tmp_path, name)
    assert writes.strays(before, writes.take([place])) == []
    for name in ("stray.kra", ".copy.ab12.saving.ora", "krita-art-mcp", "probe.png"):
        _write(tmp_path, name)
    found = {Path(path).name for path in writes.strays(before, writes.take([place]))}
    assert found == {"stray.kra", ".copy.ab12.saving.ora", "krita-art-mcp", "probe.png"}


def test_the_places_catch_our_names_in_every_folder_and_leave_other_processes_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, temp, work = tmp_path / "home", tmp_path / "temp", tmp_path / "work"
    support = home / "Library" / "Application Support"
    preferences = home / "Library" / "Preferences"
    data = support / "krita-art-mcp"
    for folder in (temp, work, data, preferences):
        folder.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(work)
    monkeypatch.setattr(writes, "_krita_temp", lambda: temp)
    places = writes.places(data)
    before = writes.take(places)
    for folder, name in (
        (work, "notes.txt"),
        (home, ".claude.json.tmp.1"),
        (home, ".krita-1-document_2-autosave.kra"),
        (temp, "com.other.app"),
        (temp, "KRITA_SWAP_FILE_1a2b"),
        (preferences, "com.other.plist"),
        (data, ".DS_Store"),
        (data, "logs/.DS_Store"),
    ):
        _write(folder, name)
    assert writes.strays(before, writes.take(places)) == []
    strays = [
        data / "stray.txt",
        work / "op-1.png",
        home / "copy.kra",
        temp / ".copy.ab12.saving.ora",
        support / "krita-art-mcp-2",
        preferences / "probe.plist",
    ]
    for path in strays:
        _write(path.parent, path.name)
    assert writes.strays(before, writes.take(places)) == sorted(map(str, strays))


def test_a_folder_that_is_not_there_lists_empty(tmp_path: Path) -> None:
    assert writes.take([Place(tmp_path / "gone")]) == {Place(tmp_path / "gone"): {}}
