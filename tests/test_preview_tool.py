import hashlib
import io
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from bridge_core import documents
from fake_krita import bgra
from mcp.types import CallToolResult, ImageContent, TextContent
from PIL import Image
from worlds import World, running_world

from krita_art_mcp import baselines, imaging, roots, sheets
from krita_art_mcp.bridge_client import Done, Failed
from krita_art_mcp.envelope import MAX_RESULT_BYTES
from krita_art_mcp.probe.report import sheet_cell
from krita_art_mcp.tools import preview
from krita_art_mcp.tools.preview import resolve_preview

SRGB = documents.SRGB_PROFILE
RIVER = {"space": "srgb", "rgba": [0.2, 0.4, 0.6, 1]}
BLUE = bytes([200, 40, 10, 255])


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    with running_world(tmp_path) as running:
        yield running


def _opened(world: World) -> tuple[dict[str, Any], int]:
    art = world.tmp_path / "art"
    (art / "accepted").mkdir(parents=True, exist_ok=True)
    roots.save(world.data / "config.json", [str(art)])
    source = art / "accepted" / "hero.kra"
    source.write_bytes(b"accepted art")
    arguments = {
        "source_path": str(source),
        "source_sha256": hashlib.sha256(b"accepted art").hexdigest(),
        "mode": "working_copy",
        "working_dir": str(art / "work"),
        "request_id": "req-open",
    }
    opened = world.server().content("krita_document_open", arguments)
    assert opened["status"] == "completed"
    return opened, max(world.port.live)


def _created(world: World, name: str = "sketch", width: int = 64, height: int = 32) -> str:
    arguments = {
        "name": name,
        "size_px": [width, height],
        "color_model": "RGBA",
        "depth": "U8",
        "profile_id": SRGB,
        "background": "transparent",
        "request_id": f"req-{name}",
    }
    created = world.server().content("krita_document_create", arguments)
    assert created["status"] == "completed"
    document_id: str = created["document_id"]
    return document_id


def _render(sources: list[dict[str, Any]], **changes: Any) -> dict[str, Any]:
    return {
        "recipes": [{"id": "native", "target_size_px": [8, 4]}],
        "filter": "nearest",
        "sources": sources,
        "overlays": [],
        "backgrounds": ["transparent"],
        **changes,
    }


def _source(document_id: str, **changes: Any) -> dict[str, Any]:
    return {"document_id": document_id, "frame": 0, "target": "composite", **changes}


def _rgba(data: bytes, width: int, height: int) -> np.ndarray:
    return np.frombuffer(data, dtype=np.uint8).reshape(height, width, 4)[..., [2, 1, 0, 3]]


def _images(result: CallToolResult) -> list[ImageContent]:
    return [item for item in result.content if isinstance(item, ImageContent)]


def _transfer(world: World) -> list[Path]:
    return sorted((world.data / "transfer").iterdir())


def test_the_first_render_reads_the_baseline_and_later_ones_keep_it(world: World) -> None:
    opened, key = _opened(world)
    copy = opened["data"]["path"]
    # The document has changed since it was opened; its file has not.
    world.port.canvas[key] = BLUE * 32
    source = _source(opened["document_id"], baseline_id=opened["data"]["baseline_id"])
    first = world.server().content("krita_preview_render", _render([source]))
    assert first["status"] == "completed" and first["document_id"] == opened["document_id"]
    [sheet] = first["data"]["sheets"]
    assert [column["state"] for column in sheet["columns"]] == ["as_opened", "current"]
    assert (sheet_cell(sheet, 0) == _rgba(bgra(8, 4), 8, 4)).all()
    assert (sheet_cell(sheet, 1) == _rgba(BLUE * 32, 8, 4)).all()
    # Read once from the working copy's file, opened without a view and closed again.
    assert world.port.opened == [copy, copy] and list(world.port.live) == [key]
    assert world.port.front_key == key
    again = world.server().content("krita_preview_render", _render([source]))
    [kept] = again["data"]["sheets"]
    assert world.port.opened == [copy, copy]
    assert (sheet_cell(kept, 0) == _rgba(bgra(8, 4), 8, 4)).all()
    assert _transfer(world) == []


def test_a_baseline_that_is_not_the_documents_is_refused_in_the_bridge(world: World) -> None:
    opened, _ = _opened(world)
    source = _source(opened["document_id"], baseline_id="baseline-000000000000")
    refused = world.server().content("krita_preview_render", _render([source]))
    assert refused["error"]["code"] == "INVALID_ARGUMENT"
    assert refused["error"]["details"]["baseline_id"] == opened["data"]["baseline_id"]
    assert _transfer(world) == []


def test_a_working_copy_changed_on_disk_no_longer_holds_its_baseline(world: World) -> None:
    opened, _ = _opened(world)
    Path(opened["data"]["path"]).write_bytes(b"saved over by hand")
    source = _source(opened["document_id"], baseline_id=opened["data"]["baseline_id"])
    refused = world.server().content("krita_preview_render", _render([source]))
    assert refused["error"]["code"] == "SOURCE_HASH_MISMATCH"
    assert len(world.port.opened) == 1 and _transfer(world) == []


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"sources": [_source("doc-1", target="layer", layer_id="l", baseline_id="b")]}, "pairs"),
        ({"recipes": [{"id": "game", "target_pixels_per_unit": 2.95}]}, "World-unit recipes"),
        ({"recipes": [{"id": "a", "target_size_px": [8, 4]}] * 2}, "its own id"),
        ({"sources": [_source("doc-1", frame=1)]}, "frame 0 only"),
        (
            {
                "sources": [
                    _source(
                        "doc-1",
                        crop_rect={"x": 0, "y": 0, "width": 4, "height": 4},
                        anchor_px=[5, 1],
                    )
                ]
            },
            "outside its crop",
        ),
        ({"tints": [{"id": "t", "multiply": [1, 1, 1], "add": [0, 0, 0]}] * 2}, "its own id"),
    ],
    ids=[
        "a layer's baseline",
        "no units",
        "a recipe id twice",
        "frame 1",
        "an anchor outside",
        "a tint id twice",
    ],
)
def test_the_server_refuses_what_the_arguments_alone_rule_out(
    world: World, changes: dict[str, Any], message: str
) -> None:
    arguments = {**_render([_source("doc-1")]), **changes}
    refused = world.server().content("krita_preview_render", arguments)
    assert refused["status"] == "failed" and refused["operation_id"] is None
    assert message in refused["error"]["message"]


def test_overlays_are_drawn_into_the_sheet_and_kept_out_of_the_clean_one(world: World) -> None:
    document_id = _created(world)
    key = max(world.port.live)
    mask = bytes([255] * 6 * 4)
    world.port.live[key]["selection"] = ({"x": 4, "y": 2, "width": 6, "height": 4}, mask)
    arguments = _render(
        [_source(document_id)],
        recipes=[{"id": "native", "target_pixels_per_unit": 4}],
        export_pixels_per_unit=4,
        master_to_export_scale=1,
        overlays=["selection", "allowed_mask"],
        backgrounds=[RIVER],
    )
    result = world.server().content("krita_preview_render", arguments)
    [sheet] = result["data"]["sheets"]
    assert sheet["clean_image"] is not None and sheet["columns"][0]["overlays"] == ["selection"]
    with Image.open(sheet["image"]["path"]) as drawn, Image.open(sheet["clean_image"]["path"]) as c:
        image, clean = np.asarray(drawn), np.asarray(c)
    changed = (image != clean).any(axis=-1)
    assert changed.sum() == 2 * 6 + 2 * 2
    assert (image[changed] == sheets.OVERLAY_RGB["selection"]).all()
    assert result["data"]["source_pixels_changed"] == 0 and _transfer(world) == []


def test_a_hamming_render_resamples_the_cell_with_hamming(world: World) -> None:
    document_id = _created(world)
    arguments = _render(
        [_source(document_id)],
        recipes=[{"id": "small", "target_size_px": [16, 8]}],
        filter="hamming",
    )
    [sheet] = world.server().content("krita_preview_render", arguments)["data"]["sheets"]
    assert (sheet["filter"], sheet["columns"][0]["filter"]) == ("hamming", "hamming")
    native = Image.fromarray(_rgba(bgra(64, 32), 64, 32))
    hamming = np.asarray(native.resize((16, 8), Image.Resampling.HAMMING))
    assert (sheet_cell(sheet, 0) == hamming).all()
    assert (hamming != np.asarray(native.resize((16, 8), Image.Resampling.BICUBIC))).any()


def test_operation_get_finishes_a_render_that_came_back_running(world: World) -> None:
    document_id = _created(world)
    world.gate.clear()
    world.port.on_read.append(lambda: world.gate.wait(10))
    running = world.server(budget_s=0.6).content(
        "krita_preview_render", _render([_source(document_id)])
    )
    assert running["status"] == "running"
    world.gate.set()
    arguments = {"operation_id": running["operation_id"]}
    got = world.server().call("krita_operation_get", arguments)
    content = got.structured_content or {}
    receipt = content["data"]["receipt"]
    assert content["data"]["tool"] == "krita_preview_render" and receipt["status"] == "completed"
    assert len(_images(got)) == 1
    # Twice: the sheets on disk are found before anything is made again.
    again = world.server().content("krita_operation_get", arguments)
    assert again["data"]["receipt"] == receipt


def test_sheets_too_large_to_show_together_stay_on_disk_at_full_size(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    document_id = _created(world)
    shown = world.server().call("krita_preview_render", _render([_source(document_id)]))
    assert len(_images(shown)) == 1
    monkeypatch.setattr(preview, "RESERVED_BYTES", MAX_RESULT_BYTES)
    kept = world.server().call("krita_preview_render", _render([_source(document_id)]))
    content = kept.structured_content or {}
    [sheet] = content["data"]["sheets"]
    assert sheet["inline"] is False and _images(kept) == []
    [line] = [item.text for item in kept.content if isinstance(item, TextContent)]
    assert "on disk only" in line and sheet["image"]["path"] in line
    with Image.open(io.BytesIO(Path(sheet["image"]["path"]).read_bytes())) as image:
        assert list(image.size) == sheet["size_px"]


def test_greyscale_needs_srgb_bytes(world: World) -> None:
    document_id = _created(world)
    world.port.space = ("RGBA", "U8", "Some-Other-Profile.icc")
    refused = world.server().content(
        "krita_preview_render", _render([_source(document_id)], greyscale=True)
    )
    assert refused["error"]["code"] == "COLOR_PROFILE_MISMATCH" and _transfer(world) == []


def test_siblings_from_two_documents_share_a_sheet_and_name_no_one_document(world: World) -> None:
    first, second = _created(world, "hero"), _created(world, "sibling", 32, 32)
    arguments = _render(
        [_source(first), _source(second)], recipes=[{"id": "icon", "target_size_px": [16, 16]}]
    )
    result = world.server().call("krita_preview_render", arguments)
    content = result.structured_content or {}
    assert content["status"] == "completed" and content["document_id"] is None
    [sheet] = content["data"]["sheets"]
    assert [column["image_px"] for column in sheet["columns"]] == [[16, 8], [16, 16]]
    assert [column["offset_px"] for column in sheet["columns"]] == [[0, 4], [0, 0]]
    [line] = [item.text for item in result.content if isinstance(item, TextContent)]
    assert line.startswith("Rendered 1 sheet of 2 documents: icon, ")


@pytest.mark.parametrize("kept", [b"not an array", "wrong shape"], ids=["unreadable", "mis-shaped"])
def test_a_baseline_file_that_cannot_serve_is_read_anew_on_retry(world: World, kept: Any) -> None:
    opened, _ = _opened(world)
    baseline = opened["data"]["baseline_id"]
    source = _source(opened["document_id"], baseline_id=baseline)
    assert (
        world.server().content("krita_preview_render", _render([source]))["status"] == "completed"
    )
    path = baselines.path_of(world.tmp_path / "a" / "baselines", baseline)
    assert path is not None
    if isinstance(kept, bytes):
        path.write_bytes(kept)
    else:
        np.save(path, np.zeros((2, 2, 4), dtype=np.uint8))
    refused = world.server().content("krita_preview_render", _render([source]))
    assert refused["error"]["code"] == "INTERNAL_ERROR" and refused["error"]["retryable"]
    assert not path.exists() and _transfer(world) == []
    retried = world.server().content("krita_preview_render", _render([source]))
    [sheet] = retried["data"]["sheets"]
    assert (sheet_cell(sheet, 0) == _rgba(bgra(8, 4), 8, 4)).all()
    # Read once for the first render and once again for the retry.
    assert len(world.port.opened) == 3


def _read(world: World, document_id: str) -> Done:
    arguments = _render([_source(document_id)])
    source = {
        "document_id": document_id,
        "frame": 0,
        "target": "composite",
        "layer_id": None,
        "rect": None,
        "baseline_id": None,
        "read_baseline": False,
        "overlays": [],
    }
    outcome = world.client().call("preview.read", {"sources": [source], "render": arguments})
    assert isinstance(outcome, Done)
    return outcome


def test_pixels_already_taken_ask_for_another_render(world: World) -> None:
    outcome = _read(world, _created(world))
    Path(outcome.result["sources"][0]["pixels"]["path"]).unlink()
    gone = resolve_preview(world.places(), outcome)
    assert isinstance(gone, Failed)
    assert gone.error["code"] == "INTERNAL_ERROR" and gone.error["retryable"] is True
    assert "render again" in gone.error["message"]


def test_sheets_another_server_made_meanwhile_are_used_as_they_are(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    outcome = _read(world, _created(world))
    made = resolve_preview(world.places("b"), outcome)
    assert isinstance(made, Done) and _transfer(world) == []
    # Server a shares server b's captures: it looks first and finds nothing, then the pixels
    # are gone, and the sheets b made are there.
    real = imaging.find
    looked: list[str] = []

    def first_finds_nothing(*args: Any) -> Any:
        looked.append(args[2])
        return None if len(looked) == 1 else real(*args)

    monkeypatch.setattr(imaging, "find", first_finds_nothing)
    shared = world.places("b")
    again = resolve_preview(shared, outcome)
    assert isinstance(again, Done) and again.result["sheets"] == made.result["sheets"]
    assert again.result["inline_pngs"] == made.result["inline_pngs"]
    assert looked == [".json", ".json"]
