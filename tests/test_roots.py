import io
import json
import os
import stat
from pathlib import Path

import pytest
from bridge_core import roots as plugin_roots
from bridge_core.errors import BridgeError

from krita_art_mcp import roots


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    # A root, a folder beside it, and the links an agent might use to leave the root.
    (tmp_path / "art" / "accepted").mkdir(parents=True)
    (tmp_path / "art" / "accepted" / "hero.kra").write_bytes(b"kra")
    (tmp_path / "artwork").mkdir()
    (tmp_path / "outside").mkdir()
    (tmp_path / "art" / "to-outside").symlink_to(tmp_path / "outside")
    (tmp_path / "art" / "dangling.png").symlink_to(tmp_path / "outside" / "gone.png")
    (tmp_path / "art-link").symlink_to(tmp_path / "art")
    return tmp_path


CASES = [
    ("art/accepted/hero.kra", True),
    ("art", True),
    ("art/new/not-yet.ora", True),
    ("art-link/accepted/hero.kra", True),
    ("art/../outside/x.png", False),
    ("art/accepted/../../outside/x.png", False),
    ("art/to-outside/x.png", False),
    ("art/dangling.png", False),
    ("artwork/x.png", False),
    ("outside", False),
]


@pytest.mark.parametrize(("relative", "allowed"), CASES)
def test_both_sides_resolve_every_path_before_judging_it(
    tree: Path, relative: str, allowed: bool
) -> None:
    # The server and the plugin each check (invariant 3), and must agree on every case.
    data = tree / "data"
    roots.save(data / "config.json", [str(tree / "art")])
    path = f"{tree}/{relative}"
    server = roots.allowed(data / "config.json", data / "harness")
    real = roots.resolve(path)
    assert real is not None and roots.inside(real, server) is allowed
    if allowed:
        assert plugin_roots.check(data, path, "source_path") == os.path.realpath(path)
    else:
        with pytest.raises(BridgeError) as refused:
            plugin_roots.check(data, path, "source_path")
        assert refused.value.body["code"] == "PATH_NOT_ALLOWED"
        assert refused.value.body["details"] == {"field": "source_path"}


def test_the_harness_folder_is_always_allowed_and_nothing_else_by_default(tmp_path: Path) -> None:
    data = tmp_path / "data"
    (data / "harness").mkdir(parents=True)
    harness_file = str(data / "harness" / "fixture.ora")
    assert roots.inside(harness_file, roots.allowed(data / "config.json", data / "harness"))
    assert plugin_roots.check(data, harness_file, "source_path") == harness_file
    with pytest.raises(BridgeError):
        plugin_roots.check(data, str(data / "config.json"), "source_path")


@pytest.mark.parametrize("path", ["relative/hero.kra", "/art/he\0ro.kra", "", 7])
def test_a_relative_path_or_a_nul_byte_is_an_invalid_argument(tmp_path: Path, path: object) -> None:
    if isinstance(path, str):
        assert roots.resolve(path) is None
    with pytest.raises(BridgeError) as refused:
        plugin_roots.check(tmp_path, path, "working_dir")
    assert refused.value.body["code"] == "INVALID_ARGUMENT"


def test_a_root_of_slash_allows_every_absolute_path() -> None:
    assert roots.inside("/anything/at/all", ["/"])
    assert plugin_roots.inside("/anything/at/all", ["/"])


def test_config_json_is_private_versioned_and_written_whole(tmp_path: Path) -> None:
    config = tmp_path / "data" / "config.json"
    roots.save(config, ["/art"])
    assert json.loads(config.read_text()) == {"v": roots.VERSION, "roots": ["/art"]}
    assert stat.S_IMODE(config.stat().st_mode) == 0o600
    assert stat.S_IMODE(config.parent.stat().st_mode) == 0o700
    assert [entry.name for entry in config.parent.iterdir()] == ["config.json"]


def test_the_config_versions_agree_on_both_sides() -> None:
    assert plugin_roots.CONFIG_VERSION == roots.VERSION


@pytest.mark.parametrize(
    ("content", "problem"),
    [
        ('{"v": 2, "roots": []}', "version 2"),
        ("not json", "not valid JSON"),
        ('{"roots": []}', "no version"),
        ('{"v": 1, "roots": ["relative"]}', "roots wrongly"),
    ],
)
def test_a_newer_or_malformed_config_is_refused_on_both_sides(
    tmp_path: Path, content: str, problem: str
) -> None:
    config = tmp_path / "config.json"
    config.write_text(content)
    with pytest.raises(roots.ConfigError, match=problem):
        roots.load(config)
    with pytest.raises(BridgeError) as refused:
        plugin_roots.load(config)
    assert (
        refused.value.body["code"] == "INTERNAL_ERROR" and problem in refused.value.body["message"]
    )


def test_an_older_config_is_read(tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    config.write_text('{"v": 0, "roots": ["/art"]}')
    assert roots.load(config) == plugin_roots.load(config) == ["/art"]


def _roots(action: str, directory: str | None, config: Path) -> tuple[int, str]:
    out = io.StringIO()
    status = roots.run(action, directory, config, out)
    return status, out.getvalue()


def test_roots_add_list_and_remove(tree: Path) -> None:
    config = tree / "data" / "config.json"
    assert _roots("list", None, config) == (
        0,
        f"No roots yet, so agents can open nothing. {roots.ADD}\n",
    )
    real = os.path.realpath(tree / "art")
    assert _roots("add", str(tree / "art-link"), config) == (0, f"Agents may now use {real}.\n")
    assert _roots("add", str(tree / "art"), config) == (0, f"{real} is already allowed.\n")
    assert _roots("list", None, config) == (0, f"{real}\n")
    assert _roots("remove", str(tree / "art-link"), config)[0] == 0
    assert roots.load(config) == []
    assert _roots("remove", str(tree / "art"), config) == (1, f"{tree / 'art'} is not a root.\n")


def test_roots_add_needs_a_folder_and_never_overwrites_a_broken_config(tree: Path) -> None:
    config = tree / "data" / "config.json"
    hero = str(tree / "art" / "accepted" / "hero.kra")
    assert _roots("add", hero, config) == (1, f"{hero} is not a folder.\n")
    config.parent.mkdir()
    config.write_text("{broken")
    status, text = _roots("add", str(tree / "art"), config)
    assert status == 1 and "not valid JSON" in text
    assert config.read_text() == "{broken"
