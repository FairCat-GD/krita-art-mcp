import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image

from krita_art_mcp import transfer
from krita_art_mcp.bridge_client import BridgeClient, Done, Failed
from krita_art_mcp.paths import Places

BASELINE_ID = re.compile(r"^baseline-[0-9a-f]{12}$")

log = logging.getLogger(__name__)


def path_of(directory: Path, baseline_id: Any) -> Path | None:
    # The id comes from the bridge; only one of the plugin's own shape names a file.
    if not isinstance(baseline_id, str) or not BASELINE_ID.match(baseline_id):
        return None
    return directory / f"{baseline_id}.png"


def adopt(places: Places, baseline_id: Any, spec: Any) -> None:
    # The as_opened composite, from the transfer file into baselines/. Never raises: the
    # document is open either way, and a retry must return the same receipt.
    try:
        target = path_of(places.baselines_dir, baseline_id)
        if target is None:
            raise transfer.TransferError(f"{baseline_id!r} is not a baseline id")
        if not target.exists():
            _write_png(target, transfer.take(places.transfer_dir, spec))
        transfer.discard(places.transfer_dir, spec)
    except transfer.TransferError as problem:
        # Expected when a server with another data folder took the same outcome first.
        log.warning("the baseline %s was not kept: %s", baseline_id, problem)
    except Exception:
        log.exception("the baseline %s was not kept", baseline_id)


def remove(places: Places, baseline_id: Any) -> None:
    target = path_of(places.baselines_dir, baseline_id)
    if target is not None:
        target.unlink(missing_ok=True)


def sweep(client: BridgeClient, directory: Path) -> int:
    # Listed before the bridge is asked, so a baseline written meanwhile is never taken.
    listed = [path for path in directory.glob("baseline-*.png") if BASELINE_ID.match(path.stem)]
    if not listed:
        return 0
    outcome = client.call("document.baselines")
    if isinstance(outcome, Done):
        live = set(outcome.result.get("baseline_ids", []))
    elif isinstance(outcome, Failed) and outcome.error["code"] == "KRITA_NOT_RUNNING":
        live = set()
    else:
        return 0
    orphans = [path for path in listed if path.stem not in live]
    for path in orphans:
        path.unlink(missing_ok=True)
    return len(orphans)


def _write_png(target: Path, pixels: transfer.Pixels) -> None:
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=target.parent, prefix=".", suffix=".png.tmp")
    try:
        with os.fdopen(fd, "wb") as stream:
            Image.fromarray(pixels).save(stream, "PNG", compress_level=1)
        os.replace(temp, target)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise
