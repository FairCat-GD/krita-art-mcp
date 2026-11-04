import base64
import io
import os
from pathlib import Path
from typing import Any

import numpy as np
from mcp import Client
from mcp.types import CallToolResult, ImageContent, TextContent
from PIL import Image

from krita_art_mcp.bridge_client import BridgeClient, Done
from krita_art_mcp.probe import fixtures
from krita_art_mcp.probe.common import close, harness_call, open_args
from krita_art_mcp.probe.report import Report, call, code, differs, tool
from krita_art_mcp.tools.documents import SRGB_PROFILE
from krita_art_mcp.tools.observe import BLEND_MODES

WIDTH, HEIGHT = fixtures.WIDTH, fixtures.HEIGHT
FULL = {"x": 0, "y": 0, "width": WIDTH, "height": HEIGHT}
UNKNOWN_LAYER = "00000000-0000-4000-8000-000000000000"
SHAPE_LAB = (75.12, -19.96, 28.26)


def _capture(document_id: str, **changes: Any) -> dict[str, Any]:
    return {
        "source": {"document_id": document_id, "frame": 0},
        "target": "composite",
        "layer_id": None,
        "rect": dict(FULL),
        "scale": 1,
        "filter": "nearest",
        **changes,
    }


def _sample(document_id: str, points: list[list[int]], **changes: Any) -> dict[str, Any]:
    return {
        "source": {"document_id": document_id, "frame": 0},
        "target": "composite",
        "layer_id": None,
        "points": points,
        **changes,
    }


def _decoded(data: bytes) -> np.ndarray:
    with Image.open(io.BytesIO(data)) as image:
        return np.asarray(image)


def _file(content: dict[str, Any]) -> np.ndarray | None:
    path = ((content.get("data") or {}).get("image") or {}).get("path")
    return None if path is None else _decoded(Path(path).read_bytes())


def _ids(layers: list[dict[str, Any]]) -> dict[str, str]:
    return {layer["name"]: layer["id"] for layer in layers}


async def run(report: Report, a: Client, client: BridgeClient, harness: Path) -> None:
    harness = Path(os.path.realpath(harness))
    folder = harness / "pixels"
    folder.mkdir(exist_ok=True)
    ora, png = folder / "pixels.ora", folder / "front.png"
    stack = fixtures.probe_stack()
    composite = fixtures.write_ora(ora, stack)
    fixtures.write_png(png, composite)
    opened = await tool(a, "krita_document_open", open_args(ora, "read_only"))
    if opened.get("status") != "completed":
        report.check("the pixel checks' fixture opens", False, str(opened.get("error")))
        return
    document_id = opened["document_id"]
    layers = _ids(opened["data"]["layers"])
    try:
        await _captures(report, a, document_id, layers, stack, composite)
        await _refusals(report, a, document_id, layers)
        await _samples(report, a, document_id, layers)
    finally:
        await close(a, document_id)
    await _resources(report, a)
    await _k46(report, a, client, ora, png, harness, composite)


async def _captures(
    report: Report,
    a: Client,
    document_id: str,
    layers: dict[str, str],
    stack: tuple[fixtures.Layer, ...],
    composite: np.ndarray,
) -> None:
    result = await call(a, "krita_capture", _capture(document_id))
    content = result.structured_content or {}
    found = _file(content)
    problems = []
    if found is None:
        problems.append(f"{code(content)}: {(content.get('error') or {}).get('message')}")
    else:
        problems += [f"file: {differs(found, composite)}"] if differs(found, composite) else []
        problems += _image_problems(result, composite, content)
    report.check(
        "a native capture's file and inline image equal the fixture, with the image _meta",
        not problems,
        "; ".join(problems),
    )
    rect = {"x": 8, "y": 10, "width": 20, "height": 20}
    part = await tool(a, "krita_capture", _capture(document_id, rect=rect))
    crop = composite[10:30, 8:28]
    data = part.get("data") or {}
    found = _file(part)
    report.check(
        "a native sub-rect equals the fixture's crop, mapped by [1, 0, -x, 0, 1, -y]",
        found is not None
        and not differs(found, crop)
        and data.get("source_to_image") == [1, 0, -8, 0, 1, -10],
        "" if found is None else differs(found, crop),
    )
    hidden = await tool(
        a, "krita_capture", _capture(document_id, target="layer", layer_id=layers["probe hidden"])
    )
    own = stack[0].pixels
    found = _file(hidden)
    clip_rect = {"x": 16, "y": 6, "width": 32, "height": 32}
    clipped = await tool(
        a,
        "krita_capture",
        _capture(document_id, target="layer", layer_id=layers["probe clip"], rect=clip_rect),
    )
    expected_clip = np.zeros((32, 32, 4), dtype=np.uint8)
    expected_clip[4:28, 4:28] = (240, 30, 60, 255)
    found_clip = _file(clipped)
    report.check(
        "a layer capture is the layer's own pixels: no opacity, visibility or inherit-alpha (K12)",
        own is not None
        and found is not None
        and found_clip is not None
        and not differs(found, own)
        and not differs(found_clip, expected_clip),
        f"hidden {code(hidden)}, clip {code(clipped)}",
    )
    scaled = await tool(a, "krita_capture", _capture(document_id, scale=0.5, filter="bilinear"))
    data = scaled.get("data") or {}
    found = _file(scaled)
    report.check(
        "scale 0.5 bilinear lands on an opaque checker at 32 x 24, with its transform",
        found is not None
        and found.shape == (24, 32, 3)
        and data.get("source_to_image") == [0.5, 0, 0, 0, 0.5, 0]
        and (data.get("filter"), data.get("background")) == ("bilinear", "checker"),
        str(None if found is None else found.shape),
    )


def _image_problems(
    result: CallToolResult, composite: np.ndarray, content: dict[str, Any]
) -> list[str]:
    images = [item for item in result.content if isinstance(item, ImageContent)]
    if len(images) != 1:
        return [f"{len(images)} images"]
    problems = []
    if images[0].meta != {"codex/imageDetail": "original"}:
        problems.append(f"_meta {images[0].meta}")
    shown = _decoded(base64.b64decode(images[0].data))
    if differs(shown, composite):
        problems.append(f"inline: {differs(shown, composite)}")
    text = result.content[0]
    if not isinstance(text, TextContent) or content["data"]["image"]["path"] not in text.text:
        problems.append("no path in the text")
    return problems


async def _refusals(report: Report, a: Client, document_id: str, layers: dict[str, str]) -> None:
    group = layers["probe group"]
    cases = {
        "a rect off the canvas": (
            _capture(document_id, rect={"x": 60, "y": 0, "width": 5, "height": 1}),
            "INVALID_ARGUMENT",
            True,
        ),
        "an image over max_px": (_capture(document_id, scale=40), "INVALID_ARGUMENT", False),
        "a background at scale 1": (
            _capture(document_id, background="checker"),
            "INVALID_ARGUMENT",
            False,
        ),
        "revision in source": (
            _capture(document_id, source={"document_id": document_id, "frame": 0, "revision": 1}),
            "INVALID_ARGUMENT",
            False,
        ),
        "a group layer": (
            _capture(document_id, target="layer", layer_id=group),
            "UNSUPPORTED_CAPABILITY",
            True,
        ),
        "an unknown layer": (
            _capture(document_id, target="layer", layer_id=UNKNOWN_LAYER),
            "LAYER_NOT_FOUND",
            True,
        ),
        "a selection when there is none": (
            _capture(document_id, target="selection"),
            "INVALID_ARGUMENT",
            True,
        ),
    }
    wrong = []
    for name, (arguments, expected, sent) in cases.items():
        answer = await tool(a, "krita_capture", arguments)
        # The server's own refusals send nothing, so carry no operation_id.
        if code(answer) != expected or bool(answer.get("operation_id")) != sent:
            wrong.append(f"{name}: {code(answer)}, operation_id {answer.get('operation_id')}")
    report.check(
        "captures refuse: off the canvas, over max_px, background at scale 1, revision, a group, "
        "an unknown layer, no selection",
        not wrong,
        "; ".join(wrong),
    )


async def _samples(report: Report, a: Client, document_id: str, layers: dict[str, str]) -> None:
    points = [[5, 45], [10, 14], [50, 35], [2, 2], [25, 15]]
    found = await tool(a, "krita_sample", _sample(document_id, points))
    samples = (found.get("data") or {}).get("samples") or []
    expected = [
        [10, 120, 220, 255],
        [167, 194, 132, 255],
        [32, 64, 200, 255],
        [0, 0, 0, 0],
        [240, 30, 60, 255],
    ]
    hidden = await tool(
        a,
        "krita_sample",
        _sample(document_id, [[2, 2]], target="layer", layer_id=layers["probe hidden"]),
    )
    layer = ((hidden.get("data") or {}).get("samples") or [{}])[0]
    shape = samples[1] if len(samples) == 5 else {}
    lab = shape.get("lab") or [0, 0, 0]
    report.check(
        "samples at known pixels are exact, the shape #A7C284 with its L*a*b*, and a layer sample",
        [sample["rgba_255"] for sample in samples] == expected
        and shape.get("hex") == "#A7C284"
        and max(abs(x - y) for x, y in zip(lab, SHAPE_LAB, strict=True)) <= 0.05
        and samples[3]["hex"] is None
        and layer.get("rgba_255") == [90, 40, 200, 255],
        f"{[sample.get('rgba_255') for sample in samples]}, layer {layer.get('rgba_255')}",
    )
    discs = await tool(a, "krita_sample", _sample(document_id, [[30, 44], [0, 47]], radius=3))
    inside, edge = ((discs.get("data") or {}).get("samples") or [{}, {}])[:2]
    edge_two = await tool(a, "krita_sample", _sample(document_id, [[0, 47]], radius=2))
    corner = ((edge_two.get("data") or {}).get("samples") or [{}])[0]
    report.check(
        "a radius-3 disc in the base is 29 exact pixels with stdev_l 0; an edge disc is clipped",
        inside.get("pixel_count") == 29
        and inside.get("rgba_255") == [10, 120, 220, 255]
        and inside.get("stdev_l") == 0
        and corner.get("pixel_count") == 6
        and edge.get("pixel_count", 0) < 29,
        f"{inside.get('pixel_count')} / {corner.get('pixel_count')} pixels",
    )


async def brushes(a: Client) -> list[dict[str, Any]] | None:
    entries: list[dict[str, Any]] = []
    cursor = None
    while True:
        page = await tool(
            a, "krita_resource_list", {"kind": "brush", "cursor": cursor, "limit": 100}
        )
        data = page.get("data")
        if not data:
            return None
        entries += data["resources"]
        cursor = data["next_cursor"]
        if cursor is None:
            return entries


async def _resources(report: Report, a: Client) -> None:
    first, second = await brushes(a), await brushes(a)
    hashed = [entry for entry in first or [] if entry["sha256"]]
    report.check(
        "every brush page through the cursor, each preset fingerprinted; two reads agree",
        bool(first) and first == second and len(hashed) == len(first or []),
        f"{len(first or [])} presets, {len(hashed)} fingerprinted",
    )
    lists = {
        kind: (
            await tool(a, "krita_resource_list", {"kind": kind, "cursor": None, "limit": 100})
        ).get("data")
        or {}
        for kind in ("blend_mode", "profile", "palette")
    }
    modes = {entry["id"] for entry in lists["blend_mode"].get("resources", [])}
    profiles = {entry["id"] for entry in lists["profile"].get("resources", [])}
    report.check(
        "the blend modes are the whitelist; the sRGB profile and a palette are listed",
        modes == set(BLEND_MODES)
        and SRGB_PROFILE in profiles
        and lists["palette"].get("total", 0) > 0,
        f"{len(modes)} modes, {len(profiles)} profiles, {lists['palette'].get('total')} palettes",
    )


async def _k46(
    report: Report,
    a: Client,
    client: BridgeClient,
    ora: Path,
    png: Path,
    harness: Path,
    composite: np.ndarray,
) -> None:
    name = (
        "K46: a capture of a document behind, with its selection mask active, makes the mask's "
        "layer active, matches the fixture, and puts the view in front back"
    )
    work = harness / "work" / "k46"
    opened = await tool(a, "krita_document_open", open_args(ora, "working_copy", work))
    if opened.get("status") != "completed":
        report.check(name, False, f"the working copy did not open: {code(opened)}")
        return
    masked = opened["document_id"]
    base = _ids(opened["data"]["layers"])["probe base"]
    front_id = None
    try:
        arguments = {
            "document_id": masked,
            "layer_id": base,
            "rect": {"x": 4, "y": 40, "width": 8, "height": 6},
        }
        made = harness_call(client, "harness.select_mask", **arguments)
        if not isinstance(made, Done):
            report.check(name, False, f"harness.select_mask: {made}")
            return
        # The overlay enters the image only in the mask display mode, not with marching ants.
        report.measured(
            "an active selection mask's overlay in the composite",
            f"seen: {made.result.get('overlay_seen')}",
        )
        front = await tool(a, "krita_document_open", open_args(png, "read_only"))
        front_id = front.get("document_id")
        captured = await tool(a, "krita_capture", _capture(masked))
        found = _file(captured)
        seen = await tool(a, "krita_document_inspect", {"document_id": masked, "frame": 0})
        active = (seen.get("data") or {}).get("active_layer_id")
        in_front = client.call("harness.front_document")
        still = in_front.result.get("document_id") if isinstance(in_front, Done) else None
        problems = []
        if found is None or differs(found, composite):
            problems.append(
                f"capture: {code(captured) if found is None else differs(found, composite)}"
            )
        if active != base:
            problems.append("the mask's layer is not active")
        if front_id is None or still != front_id:
            problems.append(f"in front: {still}, not {front_id}")
        report.check(name, not problems, "; ".join(problems))
    finally:
        await close(a, masked)
        if front_id:
            await close(a, front_id)
