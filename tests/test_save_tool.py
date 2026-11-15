import hashlib
import io
import os
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from bridge_core.errors import BridgeError
from fake_krita import bgra, png
from PIL import Image, PngImagePlugin
from worlds import B, World, running_world

from krita_art_mcp import imaging, roots
from krita_art_mcp.bridge_client import Done
from krita_art_mcp.tools import saving


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    with running_world(tmp_path) as running:
        yield running


def _art(world: World) -> Path:
    art = world.tmp_path / "art"
    (art / "accepted").mkdir(parents=True, exist_ok=True)
    roots.save(world.data / "config.json", [str(art)])
    return art


def _opened(world: World) -> str:
    art = _art(world)
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
    document_id: str = opened["document_id"]
    return document_id


def _save(document_id: str, path: Path, request_id: str = "req-save") -> dict[str, Any]:
    return {
        "guard": {"document_id": document_id, "request_id": request_id},
        "path": str(path),
        "overwrite": False,
        "verify_reopen": True,
    }


def _saves(world: World) -> list[str]:
    folder = world.tmp_path / "art" / "revisions"
    return sorted(os.listdir(folder)) if folder.exists() else []


def _dirty(world: World, document_id: str) -> bool:
    listed = world.server().content("krita_document_list", {})["data"]["documents"]
    return bool(next(entry for entry in listed if entry["document_id"] == document_id)["dirty"])


def _mark_dirty(world: World, document_id: str) -> None:
    # Adding a layer is a change through the bridge, so the document is dirty after it.
    inspected = world.server().content(
        "krita_document_inspect", {"document_id": document_id, "frame": 0}
    )
    arguments = {
        "guard": {"document_id": document_id, "request_id": f"req-layer-{document_id}"},
        "parent_id": inspected["data"]["root_layer_id"],
        "above_id": None,
        "type": "paint",
        "name": "mine",
    }
    created = world.server().content("krita_layer_create", arguments)
    assert created["status"] == "completed", created
    assert _dirty(world, document_id)


def test_a_save_lands_verified_and_clears_the_dirt(world: World) -> None:
    document_id = _opened(world)
    _mark_dirty(world, document_id)
    target = world.tmp_path / "art" / "revisions" / "hero-r02.kra"
    result = world.server().call("krita_document_save", _save(document_id, target))
    content = result.structured_content or {}
    assert content["status"] == "completed", content
    data = content["data"]
    inspected = world.server().content(
        "krita_document_inspect", {"document_id": document_id, "frame": 0}
    )["data"]
    # The export leaves Krita's own flag set, and the document on its working copy (K39, K45).
    working_copy = inspected["path"]
    assert working_copy.startswith(str(world.tmp_path / "art" / "work"))
    assert data == {
        "path": str(target),
        "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "reopened_verified": True,
        "layers_preserved": True,
        "baseline_untouched": True,
        "composite_preserved": True,
        "recompose": {"changed_px": 0, "visible_changed_px": 0, "changed_bounds_px": None},
        "expected_losses": [],
        "dirty": False,
        "krita_modified": True,
        "document_path": working_copy,
    }
    assert (inspected["dirty"], inspected["krita_modified"]) == (False, True)
    listed = world.server().content("krita_document_list", {})["data"]["documents"]
    assert [(entry["dirty"], entry["krita_modified"]) for entry in listed] == [(False, True)]
    assert content["document_id"] == document_id
    assert _saves(world) == ["hero-r02.kra"] and not _dirty(world, document_id)
    text = str(result.content[0].model_dump().get("text"))
    assert "verified by reopening" in text
    assert "recompose" not in text
    assert f"Krita still marks the document modified; it points at {working_copy}." in text
    closed = world.server().content(
        "krita_document_close",
        {
            "guard": {"document_id": document_id, "request_id": "req-close"},
            "dirty_policy": "refuse",
        },
    )
    assert closed["status"] == "completed"


def test_a_save_over_a_stale_projection_reports_and_says_what_its_recompose_changed(
    world: World,
) -> None:
    document_id = _opened(world)
    # Krita's projection before the save redraws it: one colour under alpha 0, one pixel shown.
    fresh = bytearray(8 * 4 * 4)
    fresh[(1 * 8 + 2) * 4 : (1 * 8 + 2) * 4 + 4] = bytes([5, 6, 7, 0])
    fresh[(3 * 8 + 6) * 4 : (3 * 8 + 6) * 4 + 4] = bytes([9, 9, 9, 255])
    [key] = world.port.live
    world.port.render[key] = lambda tree: bytes(fresh)
    world.port.projection[key] = bytes(len(fresh))
    target = world.tmp_path / "art" / "revisions" / "hero-r02.kra"
    result = world.server().call("krita_document_save", _save(document_id, target))
    content = result.structured_content or {}
    assert content["status"] == "completed", content
    assert content["data"]["composite_preserved"] is True
    assert content["data"]["recompose"] == {
        "changed_px": 2,
        "visible_changed_px": 1,
        "changed_bounds_px": {"x": 2, "y": 1, "width": 5, "height": 3},
    }
    text = str(result.content[0].model_dump().get("text"))
    assert (
        "Its recompose first changed 2 pixels of the live composite, 1 with alpha above 0." in text
    )


def test_a_mergedimage_that_differs_fails_and_leaves_nothing(world: World) -> None:
    document_id = _opened(world)
    _mark_dirty(world, document_id)

    def darken(merged: bytearray) -> None:
        merged[0] ^= 1

    world.port.merged_change = darken
    target = world.tmp_path / "art" / "revisions" / "hero-r02.kra"
    content = world.server().content("krita_document_save", _save(document_id, target))
    assert content["status"] == "failed"
    assert content["error"]["code"] == "SAVE_VERIFY_FAILED"
    [mismatch] = content["error"]["details"]["mismatches"]
    assert mismatch["field"] == "mergedimage" and mismatch["problem"] is None
    assert _saves(world) == [] and _dirty(world, document_id)


def test_a_poll_of_a_save_that_failed_its_mergedimage_check_says_so(world: World) -> None:
    document_id = _opened(world)

    def darken(merged: bytearray) -> None:
        merged[0] ^= 1

    world.port.merged_change = darken
    target = world.tmp_path / "art" / "revisions" / "hero-r02.kra"
    failed = world.server().content("krita_document_save", _save(document_id, target))
    assert failed["error"]["code"] == "SAVE_VERIFY_FAILED"
    # Another server has no journal line; the file is gone, so only the finish's outcome tells.
    polled = world.server(B, "b").content(
        "krita_operation_get", {"operation_id": failed["operation_id"]}
    )
    assert polled["data"]["receipt"] == failed


def test_a_finish_has_an_operation_id_a_poll_can_derive() -> None:
    derived = saving.finish_operation_id("op-" + "1" * 32)
    assert imaging.OPERATION_ID.match(derived) and derived != "op-" + "1" * 32
    assert derived == saving.finish_operation_id("op-" + "1" * 32)


def test_a_retry_returns_the_receipt_and_saves_once(world: World) -> None:
    document_id = _opened(world)
    target = world.tmp_path / "art" / "revisions" / "hero-r02.kra"
    first = world.server().content("krita_document_save", _save(document_id, target))
    again = world.server().content("krita_document_save", _save(document_id, target))
    # Another server process has no journal line: the bridge answers both halves.
    from_b = world.server(B, "b").content("krita_document_save", _save(document_id, target))
    assert first["status"] == "completed" and again == first and from_b == first
    assert world.port.calls.count("export") == 1 and _saves(world) == ["hero-r02.kra"]


def test_a_retry_after_the_file_went_returns_the_original_receipt(world: World) -> None:
    document_id = _opened(world)
    target = world.tmp_path / "art" / "revisions" / "hero-r02.kra"
    first = world.server().content("krita_document_save", _save(document_id, target))
    assert first["status"] == "completed"
    target.unlink()
    # Its finish ran; the bridge still holds that outcome, so the receipt is the original one.
    from_b = world.server(B, "b").content("krita_document_save", _save(document_id, target))
    assert from_b == first and world.port.calls.count("export") == 1


def _held(world: World) -> None:
    # The save waits in Krita until the gate opens, past a short wait.
    world.gate.clear()

    def slow(saved: dict[str, Any]) -> None:
        world.gate.wait(10)

    world.port.on_export.append(slow)


def _settled(server: Any, operation_id: str) -> dict[str, Any]:
    # Polled until the call is no longer queued or running.
    for _ in range(40):
        got = server.content("krita_operation_get", {"operation_id": operation_id})
        if got["data"]["state"] not in ("queued", "running"):
            return dict(got["data"])
    raise AssertionError(f"{operation_id} never settled")


def _in_place(world: World) -> list[str]:
    return [name for name in _saves(world) if not name.startswith(".")]


def test_a_save_that_runs_past_the_wait_is_finished_by_operation_get(world: World) -> None:
    # Only the server process that made the call finishes it from a poll.
    document_id = _opened(world)
    _held(world)
    target = world.tmp_path / "art" / "revisions" / "hero-r02.kra"
    server = world.server(budget_s=0.5)
    running = server.content("krita_document_save", _save(document_id, target))
    assert running["status"] == "running" and _saves(world) == []
    world.gate.set()
    receipt = _settled(server, running["operation_id"])["receipt"]
    assert receipt["status"] == "completed" and receipt["operation_id"] == running["operation_id"]
    assert _saves(world) == ["hero-r02.kra"]
    again = world.server().content("krita_document_save", _save(document_id, target))
    assert again == receipt


def test_a_poll_from_another_process_finishes_no_save_and_says_how_to(world: World) -> None:
    document_id = _opened(world)
    _held(world)
    target = world.tmp_path / "art" / "revisions" / "hero-r02.kra"
    a = world.server(budget_s=0.5)
    running = a.content("krita_document_save", _save(document_id, target))
    operation_id = running["operation_id"]
    b = world.server(B, "b", budget_s=0.5)
    # B's own wait runs out while the save runs, as A's did.
    early = b.content("krita_operation_get", {"operation_id": operation_id})
    assert early["data"]["state"] == "running"
    world.gate.set()
    polled = _settled(b, operation_id)
    assert (polled["state"], polled["outcome"]) == ("failed", "uncertain")
    error = polled["receipt"]["error"]
    assert error["retryable"] is False and "the same request_id finishes it" in error["message"]
    assert saving.finish_operation_id(operation_id) not in world.bridge.jobs._operations
    assert _in_place(world) == [] and _saves(world) != []
    done = _settled(a, operation_id)
    assert done["receipt"]["status"] == "completed" and _saves(world) == ["hero-r02.kra"]
    # Once A has finished it, B reads the finish the bridge holds.
    assert _settled(b, operation_id)["receipt"] == done["receipt"]


def test_a_retry_from_another_process_leaves_the_finish_to_the_lease_holder(
    world: World,
) -> None:
    document_id = _opened(world)
    _held(world)
    target = world.tmp_path / "art" / "revisions" / "hero-r02.kra"
    a = world.server(budget_s=0.5)
    running = a.content("krita_document_save", _save(document_id, target))
    world.gate.set()
    retried = world.server(B, "b").content("krita_document_save", _save(document_id, target))
    error = retried["error"]
    assert (error["code"], error["retryable"]) == ("DOCUMENT_IN_USE", False)
    assert error["details"]["outcome"] == "uncertain" and "process 101" in error["message"]
    assert retried["operation_id"] == running["operation_id"] and _in_place(world) == []
    # The refusal changed nothing, so the finish runs for the process that holds the document.
    done = _settled(a, running["operation_id"])
    assert done["receipt"]["status"] == "completed" and _saves(world) == ["hero-r02.kra"]


def test_a_finish_that_met_a_dialog_runs_when_the_save_is_retried(world: World) -> None:
    document_id = _opened(world)

    def dialog(saved: dict[str, Any]) -> None:
        world.port.refuse = BridgeError("KRITA_MODAL_DIALOG", "A dialog is open.", True)

    world.port.on_export.append(dialog)
    target = world.tmp_path / "art" / "revisions" / "hero-r02.kra"
    first = world.server().content("krita_document_save", _save(document_id, target))
    error = first["error"]
    assert (error["code"], error["retryable"]) == ("KRITA_MODAL_DIALOG", False)
    assert error["details"]["outcome"] == "uncertain" and "same request_id" in error["message"]
    assert _in_place(world) == []
    world.port.on_export.clear()
    world.port.refuse = None
    again = world.server().content("krita_document_save", _save(document_id, target))
    assert again["status"] == "completed" and again["operation_id"] == first["operation_id"]
    assert world.port.calls.count("export") == 1 and _saves(world) == ["hero-r02.kra"]


@pytest.mark.parametrize(
    "path, code",
    [
        ("revisions/hero.kra", "INVALID_ARGUMENT"),
        ("/elsewhere/hero.kra", "PATH_NOT_ALLOWED"),
        ("{art}/hero.png", "UNSUPPORTED_CAPABILITY"),
    ],
)
def test_the_server_refuses_a_path_before_krita_sees_it(world: World, path: str, code: str) -> None:
    document_id = _opened(world)
    world.port.calls.clear()
    before = world.bridge.jobs.retention()["operations"]
    filled = path.format(art=world.tmp_path / "art")
    content = world.server().content("krita_document_save", _save(document_id, Path(filled)))
    assert content["status"] == "failed" and content["error"]["code"] == code
    # Nothing reached the bridge: the plugin, which checks again, never saw the call.
    assert world.bridge.jobs.retention()["operations"] == before and world.port.calls == []


def test_the_finish_never_reads_a_file_outside_the_roots(world: World, tmp_path: Path) -> None:
    _art(world)
    outside = tmp_path / "outside.kra"
    result = {"written": str(outside), "path": str(outside), "sha256": "0" * 64, "size_px": [8, 4]}
    assert saving._merged(world.places(), result) == (
        None,
        "The saved file is outside every allowed root.",
    )


def test_a_finished_save_is_finished_again_from_its_target(world: World) -> None:
    # After the finish moved the file, a retry hashes the same bytes from the target.
    art = _art(world)
    target = art / "hero.kra"
    with zipfile.ZipFile(target, "x") as archive:
        archive.writestr("mergedimage.png", png(8, 4, bgra(8, 4)))
    sha = hashlib.sha256(target.read_bytes()).hexdigest()
    result = {
        "written": str(art / ".gone.kra"),
        "path": str(target),
        "sha256": sha,
        "size_px": [8, 4],
    }
    assert saving._merged(world.places(), result) == (hashlib.sha256(bgra(8, 4)).hexdigest(), None)
    other = {**result, "sha256": "0" * 64}
    assert saving._merged(world.places(), other)[1] == (
        "The saved file is gone from where it was written."
    )
    wider = {**result, "size_px": [9, 4]}
    assert saving._merged(world.places(), wider) == (
        None,
        "mergedimage.png is 8 x 4 px; the document is 9 x 4.",
    )


def test_an_unfinished_save_is_never_a_receipt() -> None:
    # The save's own result describes a file not yet in place; only the finish's is a receipt.
    unfinished = Done({"document_id": "doc-1", "path": "/x.kra"}, "op-1", "document.save")
    content = saving.save_receipt(unfinished).structured_content or {}
    assert content["status"] == "failed" and content["error"]["code"] == "INTERNAL_ERROR"


def _zip(path: Path, data: bytes) -> Path:
    with zipfile.ZipFile(path, "x") as archive:
        archive.writestr("mergedimage.png", data)
    return path


def _png(image: Image.Image, **options: Any) -> bytes:
    stream = io.BytesIO()
    image.save(stream, format="PNG", **options)
    return stream.getvalue()


def test_mergedimage_is_decoded_with_no_colour_conversion(tmp_path: Path) -> None:
    rgba = np.zeros((4, 8, 4), dtype=np.uint8)
    rgba[...] = (200, 30, 10, 128)
    rgba[0, 0] = (17, 34, 51, 0)
    info = PngImagePlugin.PngInfo()
    # A gamma and a profile that would move every value if either were applied.
    info.add(b"gAMA", (100000).to_bytes(4, "big"))
    profile = imaging.MERGED.encode()
    data = _png(Image.fromarray(rgba, "RGBA"), pnginfo=info, icc_profile=profile)
    decoded = imaging.merged_image(_zip(tmp_path / "a.kra", data), [8, 4])
    assert (decoded == rgba).all()
    expected = hashlib.sha256(np.ascontiguousarray(rgba[..., [2, 1, 0, 3]]).tobytes()).hexdigest()
    assert imaging.bgra_sha256(decoded) == expected


def test_the_bgra_hash_matches_the_plugins_over_many_bands(tmp_path: Path) -> None:
    width, height = 3, imaging.HASH_ROWS * 2 + 5
    composite = bgra(width, height)
    decoded = imaging.merged_image(
        _zip(tmp_path / "a.ora", png(width, height, composite)), [width, height]
    )
    assert imaging.bgra_sha256(decoded) == hashlib.sha256(composite).hexdigest()


@pytest.mark.parametrize(
    "data",
    [
        _png(Image.new("RGB", (8, 4))),
        _png(Image.new("LA", (8, 4))),
        b"not a png at all",
    ],
)
def test_mergedimage_must_be_8_bit_rgba(tmp_path: Path, data: bytes) -> None:
    with pytest.raises(imaging.MergedError):
        imaging.merged_image(_zip(tmp_path / "a.kra", data), [8, 4])


def test_a_16_bit_mergedimage_is_refused(tmp_path: Path) -> None:
    header = png(8, 4, bgra(8, 4))
    # The IHDR's bit depth, at byte 24, made 16.
    sixteen = header[:24] + b"\x10" + header[25:]
    with pytest.raises(imaging.MergedError, match="8-bit RGBA"):
        imaging.merged_image(_zip(tmp_path / "a.kra", sixteen), [8, 4])


def test_a_mergedimage_of_another_size_is_refused_before_it_is_decoded(tmp_path: Path) -> None:
    with pytest.raises(imaging.MergedError, match="8 x 4 px; the document is 9 x 4"):
        imaging.merged_image(_zip(tmp_path / "a.kra", png(8, 4, bgra(8, 4))), [9, 4])


def test_a_file_without_mergedimage_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "a.kra"
    with zipfile.ZipFile(path, "x") as archive:
        archive.writestr("maindoc.xml", "<DOC/>")
    with pytest.raises(imaging.MergedError, match="cannot be read"):
        imaging.merged_image(path, [8, 4])
