import hashlib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from bridge_core import documents
from parity import refused_alike
from worlds import World, running_world

from krita_art_mcp import roots
from krita_art_mcp.tools import changes, painting, pixels, saving
from krita_art_mcp.tools import documents as documents_tools
from krita_art_mcp.tools.observe import LIMITS

ACCEPTED = b"accepted art"
CREATE = {
    "name": "sketch",
    "size_px": [64, 32],
    "color_model": "RGBA",
    "depth": "U8",
    "profile_id": documents.SRGB_PROFILE,
    "background": "transparent",
}
A_LAYER = "00000000-0000-4000-8000-000000000001"


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    with running_world(tmp_path) as running:
        yield running


def _art(world: World) -> Path:
    art = world.tmp_path / "art"
    (art / "accepted").mkdir(parents=True, exist_ok=True)
    roots.save(world.data / "config.json", [str(art)])
    return art


def _open(world: World, name: str = "hero.kra", **changes_: Any) -> dict[str, Any]:
    art = _art(world)
    source = art / "accepted" / name
    source.write_bytes(ACCEPTED)
    return {
        "source_path": str(source),
        "source_sha256": hashlib.sha256(ACCEPTED).hexdigest(),
        "mode": "working_copy",
        "working_dir": str(art / "work"),
        "request_id": "req-open",
        **changes_,
    }


def _document(world: World) -> str:
    created = world.server().content("krita_document_create", {**CREATE, "request_id": "req-new"})
    return str(created["document_id"])


@pytest.mark.parametrize(
    ("name", "changes_"),
    [
        ("hero.psd", {}),
        ("hero.ora", {"editable_layer_ids": [A_LAYER]}),
        ("hero.kra", {"editable_layer_names": ["rim"]}),
    ],
    ids=["another format", "ids for an ORA", "names for a KRA"],
)
def test_both_sides_hold_the_open_rules(
    world: World, monkeypatch: pytest.MonkeyPatch, name: str, changes_: dict[str, Any]
) -> None:
    arguments = _open(world, name, **changes_)
    rule = (documents_tools, "_open_rules")
    refused_alike(world, monkeypatch, "krita_document_open", arguments, rule)
    assert world.port.opened == []


@pytest.mark.parametrize("through", ["itself", "a link"])
def test_both_sides_keep_the_working_dir_out_of_the_sources_folder(
    world: World, monkeypatch: pytest.MonkeyPatch, through: str
) -> None:
    art = _art(world)
    folder = art / "accepted"
    if through == "a link":
        (art / "link").symlink_to(folder)
        folder = art / "link"
    arguments = _open(world, working_dir=str(folder))
    rule = (documents_tools, "_working_dir_rule")
    refused = refused_alike(world, monkeypatch, "krita_document_open", arguments, rule)
    assert refused["details"]["field"] == "working_dir"
    assert world.port.opened == [] and sorted(path.name for path in art.iterdir()) == sorted(
        ["accepted"] + (["link"] if through == "a link" else [])
    )


@pytest.mark.parametrize(
    "modifier",
    [{"grow_px": 2}, {"shrink_px": 2}, {"feather_px": 2}, {"invert": True}, {"combine": "add"}],
    ids=["grow", "shrink", "feather", "invert", "combine"],
)
def test_both_sides_clear_a_selection_with_no_modifiers(
    world: World, monkeypatch: pytest.MonkeyPatch, modifier: dict[str, Any]
) -> None:
    document_id = _document(world)
    arguments = {
        "guard": {"document_id": document_id, "request_id": "req-clear"},
        "combine": "replace",
        "shape": {"type": "none"},
        "feather_px": 0,
        "invert": False,
        **modifier,
    }
    rule = (changes, "_clear_rules")
    refused_alike(world, monkeypatch, "krita_selection_set", arguments, rule)
    assert world.port.recipes == []


@pytest.mark.parametrize(
    "changes_", [{"depth": "U16"}, {"profile_id": "sRGB-elle-V2-g10.icc"}], ids=["depth", "profile"]
)
def test_both_sides_create_only_u8_srgb(
    world: World, monkeypatch: pytest.MonkeyPatch, changes_: dict[str, Any]
) -> None:
    arguments = {**CREATE, **changes_, "request_id": "req-create"}
    rule = (documents_tools, "_create_rules")
    refused_alike(world, monkeypatch, "krita_document_create", arguments, rule)
    assert world.port.created == 0


def test_both_sides_save_only_kra_and_ora(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    document_id = _document(world)
    target = _art(world) / "revisions" / "hero.png"
    arguments = {
        "guard": {"document_id": document_id, "request_id": "req-save"},
        "path": str(target),
        "overwrite": False,
        "verify_reopen": True,
    }
    rule = (saving, "_save_rules")
    refused_alike(world, monkeypatch, "krita_document_save", arguments, rule)
    assert not target.parent.exists()


def test_both_sides_bound_a_capture_s_area(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    document_id = _document(world)
    side = 8192
    assert side * (side + 1) > LIMITS["capture_source_pixels"]
    arguments = {
        "source": {"document_id": document_id, "frame": 0},
        "target": "composite",
        "layer_id": None,
        "rect": {"x": 0, "y": 0, "width": side, "height": side + 1},
        "scale": 1,
        "filter": "nearest",
    }
    rule = (pixels, "_capture_rules")
    refused_alike(world, monkeypatch, "krita_capture", arguments, rule)


@pytest.mark.parametrize(
    "fields",
    [
        {"color": {"space": "srgb", "rgba": [0.8, 0.2, 0.4, 0.5]}},
        {"shape": {"type": "polygon", "points": [[0, 0], [10, 10], [4, 4]]}},
        {"shape": {"type": "path", "points": [[0, 0], [3, 1], [6, 2], [9.3, 3.1]]}},
    ],
    ids=["a colour with alpha", "a flat polygon", "a flat path"],
)
def test_both_sides_hold_the_fill_rules(
    world: World, monkeypatch: pytest.MonkeyPatch, fields: dict[str, Any]
) -> None:
    document_id = _document(world)
    arguments = {
        "guard": {"document_id": document_id, "request_id": "req-fill"},
        "layer_id": "00000000-0000-4000-8000-000000000002",
        "shape": {"type": "rect", "rect": {"x": 1, "y": 1, "width": 4, "height": 4}},
        "color": {"space": "srgb", "rgba": [0.8, 0.2, 0.4, 1]},
        "opacity": 1,
        **fields,
    }
    refused_alike(world, monkeypatch, "krita_paint_fill", arguments, (painting, "_fill_rules"))
