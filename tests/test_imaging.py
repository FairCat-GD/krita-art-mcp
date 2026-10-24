import base64
import datetime
import io
import os
import stat
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from bridge_core import transfer as plugin_transfer
from PIL import Image

from krita_art_mcp import imaging, transfer
from krita_art_mcp.bridge_client import Done, Failed
from krita_art_mcp.imaging import Render
from krita_art_mcp.paths import Places
from krita_art_mcp.tools import pixels as pixel_tools

OP = "op-" + "a" * 32
NATIVE = Render(1, "nearest", None, False, 1600)


@pytest.fixture
def places(tmp_path: Path) -> Places:
    return Places.under(tmp_path / "data", tmp_path / "server")


def _rgba(height: int, width: int, seed: int = 1) -> np.ndarray:
    return np.random.default_rng(seed).integers(0, 256, (height, width, 4), dtype=np.uint8)


def _decoded(data: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(data))
    image.load()
    return image


def test_output_sides_round_half_up() -> None:
    assert imaging.output_size(64, 48, 0.5, 1600) == (32, 24)
    # 5 x 0.5 = 2.5 rounds up to 3; Python's round() would give 2.
    assert imaging.output_size(5, 3, 0.5, 1600) == (3, 2)
    assert imaging.output_size(10, 10, 1.25, 1600) == (13, 13)


@pytest.mark.parametrize(
    ("width", "height", "scale", "max_px"),
    [
        (1, 1, 0.4, 1600),
        (2000, 10, 1, 1600),
        (10, 10, 1e308, 4096),
        (4097, 1, 1, 4096),
        (10, 10, float("nan"), 1600),
        (10, 10, float("inf"), 1600),
    ],
)
def test_sizes_under_1_px_or_over_max_px_are_refused_never_clamped(
    width: int, height: int, scale: float, max_px: int
) -> None:
    with pytest.raises(imaging.GeometryError):
        imaging.output_size(width, height, scale, max_px)


def test_max_px_bounds_the_long_edge_exactly() -> None:
    assert imaging.output_size(1600, 900, 1, 1600) == (1600, 900)
    assert imaging.output_size(3200, 10, 0.5, 1600) == (1600, 5)


def test_the_transform_maps_the_rect_onto_the_image_after_rounding() -> None:
    rect = {"x": 16, "y": 8, "width": 5, "height": 3}
    assert imaging.transform(rect, (5, 3)) == [1, 0, -16, 0, 1, -8]
    found = imaging.transform(rect, (3, 2))
    assert found == [3 / 5, 0, -16 * 3 / 5, 0, 2 / 3, -8 * 2 / 3]
    # The rect's far corner lands on the image's far corner.
    assert found[0] * (16 + 5) + found[2] == pytest.approx(3)
    assert found[4] * (8 + 3) + found[5] == pytest.approx(2)


def test_scale_1_is_the_native_bytes_alpha_included() -> None:
    pixels = _rgba(3, 4)
    image, applied = imaging.render(pixels, (4, 3), NATIVE)
    assert applied is None and image.mode == "RGBA"
    assert np.array_equal(np.asarray(_decoded(imaging.encode(image))), pixels)


def test_a_resample_on_checker_is_opaque_rgb_with_visible_cells() -> None:
    pixels = np.zeros((32, 32, 4), dtype=np.uint8)
    how = Render(0.5, "bilinear", "checker", False, 1600)
    image, applied = imaging.render(pixels, (16, 16), how)
    assert applied == "bilinear" and image.mode == "RGB"
    values = np.asarray(image)
    # Cells of 8 output pixels, whatever the scale.
    assert values[0, 0].tolist() == [255, 255, 255] and values[0, 8].tolist() == [204, 204, 204]
    assert values[8, 8].tolist() == [255, 255, 255]


def test_a_colour_background_with_alpha_keeps_alpha() -> None:
    pixels = np.zeros((4, 4, 4), dtype=np.uint8)
    pixels[0, 0] = (255, 0, 0, 255)
    background = {"space": "srgb", "rgba": [0, 0, 1, 0.5]}
    image, _ = imaging.render(pixels, (2, 2), Render(0.5, "box", background, False, 1600))
    values = np.asarray(image)
    assert image.mode == "RGBA"
    assert values[1, 1].tolist() == [0, 0, 255, 128]
    opaque = {"space": "srgb", "rgba": [0, 1, 0, 1]}
    image, _ = imaging.render(pixels, (2, 2), Render(0.5, "box", opaque, False, 1600))
    assert image.mode == "RGB" and np.asarray(image)[1, 1].tolist() == [0, 255, 0]


def test_a_transparent_resample_is_premultiplied() -> None:
    # A transparent red pixel must not bleed red into its opaque neighbour's colour.
    pixels = np.zeros((1, 2, 4), dtype=np.uint8)
    pixels[0, 0] = (255, 0, 0, 0)
    pixels[0, 1] = (0, 0, 255, 255)
    image, _ = imaging.render(pixels, (1, 1), Render(0.5, "box", "transparent", False, 1600))
    assert np.asarray(image)[0, 0].tolist()[:3] == [0, 0, 255]


def test_greyscale_is_cie_lightness_and_keeps_alpha() -> None:
    pixels = np.zeros((2, 2, 4), dtype=np.uint8)
    pixels[...] = (167, 194, 132, 255)
    image, _ = imaging.render(pixels, (1, 1), Render(0.5, "box", "checker", True, 1600))
    assert image.mode == "L"
    # L* 75.12 x 2.55 = 191.6.
    assert np.asarray(image)[0, 0] == 192
    # At the crop's own size, so premultiplied resampling cannot move the colour.
    pixels[..., 3] = 128
    image, _ = imaging.render(pixels, (2, 2), Render(1.1, "box", "transparent", True, 1600))
    assert image.mode == "LA" and np.asarray(image)[0, 0].tolist() == [192, 128]


def test_a_selection_is_an_8_bit_grey_image() -> None:
    mask = np.array([[[0], [255]], [[128], [7]]], dtype=np.uint8)
    image, _ = imaging.render(mask, (2, 2), NATIVE)
    assert image.mode == "L" and np.asarray(image).tolist() == [[0, 255], [128, 7]]


def test_the_same_size_off_scale_1_applies_no_filter() -> None:
    how = Render(1.1, "lanczos", "checker", False, 1600)
    size = imaging.output_size(3, 3, 1.1, 1600)
    _, applied = imaging.render(_rgba(3, 3), size, how)
    assert size == (3, 3) and applied is None and imaging.filter_for((3, 3), size, how) is None


def test_a_preview_is_rendered_from_the_crop_and_halved_until_it_fits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pixels = _rgba(40, 80)
    rect = {"x": 0, "y": 0, "width": 80, "height": 40}
    # A resampled image, so a preview made from it would differ from one made from the crop.
    how = Render(0.9, "bilinear", "transparent", False, 1600)
    monkeypatch.setattr(imaging, "INLINE_BYTES", 2000)
    data, size, applied = imaging.preview(pixels, rect, (72, 36), how)
    assert max(size) < 36 and len(data) <= 2000 and applied == "bilinear"
    # Exactly what rendering the native crop at that size gives: never a resample of a resample.
    direct, _ = imaging.render(pixels, size, how)
    assert np.array_equal(np.asarray(_decoded(data)), np.asarray(direct))


def test_a_large_image_previews_at_1600_px() -> None:
    pixels = np.zeros((10, 4000, 4), dtype=np.uint8)
    rect = {"x": 0, "y": 0, "width": 4000, "height": 10}
    _, size, _ = imaging.preview(pixels, rect, (4000, 10), NATIVE)
    assert size == (1600, 4)


def test_files_are_private_and_written_whole(tmp_path: Path) -> None:
    target = tmp_path / "captures" / "2026-10-24" / f"{OP}.png"
    imaging.write(target, b"png")
    assert target.read_bytes() == b"png"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert stat.S_IMODE(target.parent.stat().st_mode) == 0o700
    # mkdir's mode reaches only the last folder; captures/ itself is private too.
    assert stat.S_IMODE(target.parent.parent.stat().st_mode) == 0o700
    assert os.listdir(target.parent) == [target.name]


def test_captures_older_than_7_days_are_swept(tmp_path: Path) -> None:
    captures = tmp_path / "captures"
    # 2026-02-30 looks like a date and is not; it must not stop the sweep.
    for day in ("2026-02-30", "2026-10-16", "2026-10-17", "2026-10-24", "notes"):
        (captures / day).mkdir(parents=True)
    imaging.sweep(captures, datetime.date(2026, 10, 24))
    assert sorted(os.listdir(captures)) == ["2026-02-30", "2026-10-17", "2026-10-24", "notes"]
    imaging.sweep(tmp_path / "missing", datetime.date(2026, 10, 24))


def test_find_looks_in_every_day_folder(tmp_path: Path) -> None:
    captures = tmp_path / "captures"
    imaging.write(captures / "2026-10-23" / f"{OP}.png", b"png")
    assert imaging.find(captures, OP, ".png") == captures / "2026-10-23" / f"{OP}.png"
    assert imaging.find(captures, OP, ".json") is None


# The resolver, against real transfer files.


def _outcome(places: Places, pixels: np.ndarray, render: dict[str, Any], **changes: Any) -> Done:
    height, width = pixels.shape[:2]
    bgra = pixels[..., [2, 1, 0, 3]].tobytes()
    spec = plugin_transfer.write(places.transfer_dir, bgra, width, height, "BGRA8")
    result = {
        "document_id": "doc-1",
        "target": "composite",
        "layer_id": None,
        "rect": {"x": 0, "y": 0, "width": width, "height": height},
        "profile_id": "sRGB-elle-V2-srgbtrc.icc",
        "pixels": spec,
        "render": render,
        **changes,
    }
    return Done(result, OP, "capture.read")


def _render(**changes: Any) -> dict[str, Any]:
    return {
        "scale": 1,
        "filter": "nearest",
        "background": None,
        "greyscale": False,
        "max_px": 1600,
        **changes,
    }


def test_a_fresh_capture_is_not_read_back_from_disk(
    places: Places, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_reads(self: Path) -> bytes:
        raise AssertionError(f"{self} was read back")

    monkeypatch.setattr(Path, "read_bytes", no_reads)
    resolved = pixel_tools.resolve_capture(places, _outcome(places, _rgba(3, 4), _render()))
    assert isinstance(resolved, Done)


def test_the_resolver_writes_the_png_then_removes_the_transfer_file(places: Places) -> None:
    pixels = _rgba(3, 4)
    outcome = _outcome(places, pixels, _render())
    resolved = pixel_tools.resolve_capture(places, outcome)
    assert isinstance(resolved, Done)
    path = Path(resolved.result["image"]["path"])
    assert path.name == f"{OP}.png" and path.parent.parent == places.captures_dir
    assert np.array_equal(np.asarray(_decoded(path.read_bytes())), pixels)
    assert not Path(outcome.result["pixels"]["path"]).exists()
    assert base64.b64decode(resolved.result["inline_png"]) == path.read_bytes()
    assert resolved.result["inline"]["preview"] is False


def test_a_second_resolve_reuses_the_png(places: Places) -> None:
    outcome = _outcome(places, _rgba(3, 4), _render())
    first = pixel_tools.resolve_capture(places, outcome)
    again = pixel_tools.resolve_capture(places, outcome)
    assert isinstance(first, Done) and isinstance(again, Done)
    assert again.result == first.result


def test_a_png_written_before_its_preview_is_never_made_into_one(
    places: Places, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(imaging, "INLINE_BYTES", 200)
    outcome = _outcome(places, _rgba(20, 20), _render())
    first = pixel_tools.resolve_capture(places, outcome)
    assert isinstance(first, Done) and first.result["inline"]["preview"] is True
    preview = Path(first.result["image"]["path"]).with_name(f"{OP}.preview.png")
    preview.unlink()
    again = pixel_tools.resolve_capture(places, outcome)
    assert isinstance(again, Failed) and again.error["retryable"] is True


def test_a_capture_that_cannot_be_written_keeps_its_transfer_file(
    places: Places, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(target: Path, data: bytes) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(imaging, "write", refuse)
    outcome = _outcome(places, _rgba(3, 4), _render())
    failed = pixel_tools.resolve_capture(places, outcome)
    assert isinstance(failed, Failed)
    assert (failed.error["code"], failed.error["retryable"]) == ("IO_ERROR", True)
    assert Path(outcome.result["pixels"]["path"]).exists()


def test_a_crash_between_the_two_writes_leaves_nothing_a_retry_trusts(
    places: Places, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(imaging, "INLINE_BYTES", 200)
    real = imaging.write
    written: list[Path] = []

    def second_fails(target: Path, data: bytes) -> None:
        written.append(target)
        if len(written) == 2:
            raise OSError("disk full")
        real(target, data)

    monkeypatch.setattr(imaging, "write", second_fails)
    outcome = _outcome(places, _rgba(20, 20), _render())
    assert isinstance(pixel_tools.resolve_capture(places, outcome), Failed)
    monkeypatch.setattr(imaging, "write", real)
    again = pixel_tools.resolve_capture(places, outcome)
    assert isinstance(again, Done) and again.result["inline"]["preview"] is True


def test_a_png_another_server_finishes_meanwhile_is_found(
    places: Places, monkeypatch: pytest.MonkeyPatch
) -> None:
    outcome = _outcome(places, _rgba(3, 4), _render())
    real_take = transfer.take

    def taken_meanwhile(directory: Path, spec: Any) -> Any:
        made = real_take(directory, spec)
        image, _ = imaging.render(made, (4, 3), NATIVE)
        folder = imaging.folder_for(places.captures_dir, pixel_tools.today())
        imaging.write(folder / f"{OP}.png", imaging.encode(image))
        raise transfer.TransferError("taken")

    monkeypatch.setattr(transfer, "take", taken_meanwhile)
    assert isinstance(pixel_tools.resolve_capture(places, outcome), Done)


def test_pixels_another_server_took_are_found_or_retried(places: Places, tmp_path: Path) -> None:
    outcome = _outcome(places, _rgba(3, 4), _render())
    elsewhere = Places.under(tmp_path / "data", tmp_path / "other")
    assert isinstance(pixel_tools.resolve_capture(elsewhere, outcome), Done)
    gone = pixel_tools.resolve_capture(places, outcome)
    assert isinstance(gone, Failed) and gone.error["retryable"] is True
    # A server sharing the data folder finds what the first one made.
    assert isinstance(pixel_tools.resolve_capture(elsewhere, outcome), Done)


def test_greyscale_outside_srgb_is_refused_and_its_pixels_discarded(places: Places) -> None:
    render = _render(scale=0.5, filter="box", background="checker", greyscale=True)
    outcome = _outcome(places, _rgba(4, 4), render, profile_id="AdobeRGB")
    failed = pixel_tools.resolve_capture(places, outcome)
    assert isinstance(failed, Failed) and failed.error["code"] == "COLOR_PROFILE_MISMATCH"
    assert not Path(outcome.result["pixels"]["path"]).exists()


@pytest.mark.parametrize(
    "changes",
    [{"render": {"scale": 1}}, {"render": _render(max_px=10)}, {"rect": {"x": 0}}],
)
def test_a_malformed_outcome_is_an_internal_error_never_a_raise(
    places: Places, changes: dict[str, Any]
) -> None:
    outcome = _outcome(places, _rgba(20, 20), _render())
    broken = Done({**outcome.result, **changes}, OP, "capture.read")
    failed = pixel_tools.resolve_capture(places, broken)
    assert isinstance(failed, Failed) and failed.error["code"] == "INTERNAL_ERROR"
    # No retry can use the pixels, so they go now, not at the plugin's one-hour expiry.
    assert not Path(outcome.result["pixels"]["path"]).exists()


def test_an_operation_id_of_another_shape_names_no_file(places: Places) -> None:
    outcome = _outcome(places, _rgba(3, 4), _render())
    strange = Done(outcome.result, "op-../../escape", "capture.read")
    failed = pixel_tools.resolve_capture(places, strange)
    assert isinstance(failed, Failed)
    assert not places.captures_dir.exists()


def test_a_sample_that_cannot_be_computed_discards_its_pixels(places: Places) -> None:
    spec = plugin_transfer.write(places.transfer_dir, bytes(4 * 4), 4, 1, "BGRA8")
    result = {
        "document_id": "doc-1",
        "target": "composite",
        "layer_id": None,
        "profile_id": "sRGB-elle-V2-srgbtrc.icc",
        "points": [[0, 0]],
        "radius": 0,
        # One pixel's square, but four pixels in the file.
        "squares": [{"x": 0, "y": 0, "width": 1, "height": 1}],
        "pixels": spec,
    }
    failed = pixel_tools.resolve_sample(places, Done(result, OP, "sample.read"))
    assert isinstance(failed, Failed) and failed.error["code"] == "INTERNAL_ERROR"
    assert not Path(spec["path"]).exists()
