import asyncio
import json
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

import numpy as np
from mcp import Client
from PIL import Image

from krita_art_mcp import paths
from krita_art_mcp.bridge_client import BridgeClient
from krita_art_mcp.probe import fixtures
from krita_art_mcp.probe.report import tool
from krita_art_mcp.tools.saving import file_sha256


def guard(document_id: str, request_id: str | None = None) -> dict[str, str]:
    return {"document_id": document_id, "request_id": request_id or str(uuid.uuid4())}


def by_name(layers: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {layer["name"]: layer for layer in layers}


async def add_layer(a: Client, document_id: str, parent_id: str, name: str) -> str | None:
    arguments = {
        "guard": guard(document_id),
        "parent_id": parent_id,
        "above_id": None,
        "type": "paint",
        "name": f"krita-art-mcp probe {name}",
    }
    made = await tool(a, "krita_layer_create", arguments)
    layer_id: str | None = (made.get("data") or {}).get("layer_id")
    return layer_id


async def protect(
    a: Client,
    document_id: str,
    layers: list[dict[str, Any]],
    mask: dict[str, Any] | None,
    preserve_alpha: bool = False,
) -> dict[str, Any]:
    arguments = {
        "guard": guard(document_id),
        "protected_layer_ids": [layer["id"] for layer in layers],
        "allowed_change_mask": mask,
        "preserve_composite_alpha": preserve_alpha,
        "preserve_canvas": False,
    }
    return await tool(a, "krita_protection_set", arguments)


async def select(a: Client, document_id: str, shape: dict[str, Any]) -> dict[str, Any]:
    arguments = {
        "guard": guard(document_id),
        "combine": "replace",
        "shape": shape,
        "feather_px": 0,
        "invert": False,
    }
    return await tool(a, "krita_selection_set", arguments)


async def close(mcp: Client, document_id: str, policy: str = "discard") -> dict[str, Any]:
    arguments = {"guard": guard(document_id), "dirty_policy": policy}
    return await tool(mcp, "krita_document_close", arguments)


def history_args(document_id: str, action: str, steps: int = 1) -> dict[str, Any]:
    return {"guard": guard(document_id), "action": action, "steps": steps}


def harness_call(client: BridgeClient, op: str, **args: Any) -> Any:
    return client.call(op, args, request_id=str(uuid.uuid4()))


def open_args(source: Path, mode: str, work: Path | None = None, **extra: Any) -> dict[str, Any]:
    arguments: dict[str, Any] = {
        "source_path": str(source),
        "source_sha256": file_sha256(source),
        "mode": mode,
        "request_id": str(uuid.uuid4()),
    }
    if work is not None:
        arguments["working_dir"] = str(work)
    return {**arguments, **extra}


async def open_working(
    a: Client, source: Path, harness: Path, folder: str, **extra: Any
) -> dict[str, Any]:
    arguments = open_args(source, "working_copy", harness / "work" / folder, **extra)
    return await tool(a, "krita_document_open", arguments)


async def inspect_data(a: Client, document_id: str) -> dict[str, Any]:
    found = await tool(a, "krita_document_inspect", {"document_id": document_id, "frame": 0})
    data: dict[str, Any] = found.get("data") or {}
    return data


async def listed_entry(a: Client, document_id: str) -> dict[str, Any]:
    listed = (await tool(a, "krita_document_list", {})).get("data") or {}
    entries = listed.get("documents", [])
    return next((entry for entry in entries if entry["document_id"] == document_id), {})


async def document_dirty(a: Client, document_id: str) -> bool | None:
    entry = await listed_entry(a, document_id)
    return bool(entry["dirty"]) if entry else None


async def capture(
    a: Client,
    document_id: str,
    rect: dict[str, int],
    target: str = "composite",
    layer_id: str | None = None,
) -> np.ndarray | None:
    # The file at scale 1: RGBA bytes, or a selection's one channel.
    arguments = {
        "source": {"document_id": document_id, "frame": 0},
        "target": target,
        "layer_id": layer_id,
        "rect": rect,
        "scale": 1,
        "filter": "nearest",
    }
    data = (await tool(a, "krita_capture", arguments)).get("data") or {}
    if "image" not in data:
        return None
    with Image.open(data["image"]["path"]) as image:
        return np.asarray(image if target == "selection" else image.convert("RGBA"))


async def capture_composite(
    a: Client, document_id: str, width: int = fixtures.WIDTH, height: int = fixtures.HEIGHT
) -> np.ndarray | None:
    return await capture(a, document_id, {"x": 0, "y": 0, "width": width, "height": height})


async def capture_selection(a: Client, document_id: str) -> np.ndarray | None:
    rect = {"x": 0, "y": 0, "width": fixtures.WIDTH, "height": fixtures.HEIGHT}
    return await capture(a, document_id, rect, "selection")


def brush_colour(rgb: tuple[int, int, int]) -> dict[str, Any]:
    return {"space": "srgb", "rgba": [channel / 255 for channel in rgb] + [1]}


def brush_args(preset: dict[str, Any], **changes: Any) -> dict[str, Any]:
    return {
        "preset_id": preset["id"],
        "preset_sha256": preset["sha256"],
        "size_px": 12,
        "opacity": 1,
        "flow": 1,
        "color": brush_colour((200, 60, 90)),
        "eraser": False,
        **changes,
    }


def stroke_args(
    document_id: str,
    layer_id: str,
    brush: dict[str, Any],
    points: list[dict[str, Any]],
    request_id: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "guard": guard(document_id, request_id),
        "layer_id": layer_id,
        "brush": brush,
        "points": points,
        **extra,
    }


def line_points(x0: float, y0: float, x1: float, y1: float, count: int = 8) -> list[dict[str, Any]]:
    return [
        {"x": x0 + (x1 - x0) * index / (count - 1), "y": y0 + (y1 - y0) * index / (count - 1)}
        for index in range(count)
    ]


def turned(view: dict[str, Any]) -> dict[str, Any]:
    # A second view of the canvas, zoomed, rotated and panned away from the first.
    moved: dict[str, Any] = {"zoom": view["zoom"] * 2.5, "rotation_deg": 30.0}
    if view.get("pan_px") is not None:
        moved["pan_px"] = [view["pan_px"][0] + 40, view["pan_px"][1] + 25]
    return moved


async def finished(a: Client, content: dict[str, Any], limit_s: float) -> dict[str, Any]:
    # A call that ran past the server's wait is followed to its receipt.
    deadline = time.monotonic() + limit_s
    while content.get("status") in ("queued", "running") and time.monotonic() < deadline:
        await asyncio.sleep(1.0)
        got = await tool(a, "krita_operation_get", {"operation_id": content["operation_id"]})
        receipt = (got.get("data") or {}).get("receipt")
        if receipt is not None:
            return dict(receipt)
    return content


def krita_rss_kb() -> int | None:
    try:
        pid = json.loads(paths.bridge_file().read_text(encoding="utf-8"))["pid"]
        out = subprocess.run(
            ["ps", "-o", "rss=", "-p", str(int(pid))],
            capture_output=True,
            text=True,
            check=True,
            stdin=subprocess.DEVNULL,
        ).stdout
        return int(out.strip())
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError):
        return None


def megabytes(kilobytes: int | None) -> str:
    return "unread" if kilobytes is None else f"{kilobytes / 1024:.0f} MB"


def held_bounds(pixels: np.ndarray) -> dict[str, int] | None:
    # Where a layer captured from empty holds anything: each changed byte, as the receipt counts.
    found = np.any(pixels != 0, axis=2)
    rows, columns = np.flatnonzero(found.any(axis=1)), np.flatnonzero(found.any(axis=0))
    if rows.size == 0:
        return None
    left, top = int(columns[0]), int(rows[0])
    return {
        "x": left,
        "y": top,
        "width": int(columns[-1]) + 1 - left,
        "height": int(rows[-1]) + 1 - top,
    }
