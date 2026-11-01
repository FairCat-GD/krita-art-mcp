import contextlib
import time
from collections.abc import Iterator
from typing import Any, TextIO

import numpy as np
from mcp import Client
from mcp.types import CallToolResult
from PIL import Image


class Report:
    def __init__(self, out: TextIO) -> None:
        self._out = out
        self.passed = 0
        self.failed = 0
        self.measured_count = 0
        # Read before the probe opens anything: its document times depend on what is open.
        self.open_documents: int | None = None

    def check(self, name: str, passed: bool, detail: str = "") -> bool:
        if passed:
            self.passed += 1
        else:
            self.failed += 1
        self._line("PASS" if passed else "FAIL", name, detail)
        return passed

    def measured(self, name: str, detail: str) -> None:
        self.measured_count += 1
        self._line("MEASURED", name, detail)

    @contextlib.contextmanager
    def timed(self, stage: str) -> Iterator[None]:
        started = time.perf_counter()
        try:
            yield
        finally:
            self.measured(f"the {stage} stage", f"{time.perf_counter() - started:.1f} s")

    def note(self, text: str) -> None:
        print(text, file=self._out, flush=True)

    def summary(self, seconds: float) -> int:
        documents = self.open_documents
        condition = "" if documents is None else f", with {documents} document(s) open"
        self.note(
            f"probe: {self.passed} PASS, {self.failed} FAIL, {self.measured_count} MEASURED "
            f"in {seconds:.1f} s{condition}"
        )
        return 1 if self.failed or not self.passed else 0

    def _line(self, outcome: str, name: str, detail: str) -> None:
        self.note(f"{outcome:<8} {name}" + (f": {detail}" if detail else ""))


async def call(mcp: Client, name: str, arguments: dict[str, Any]) -> CallToolResult:
    # The whole result, images included.
    return await mcp.call_tool(name, arguments)


async def tool(mcp: Client, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    result = await mcp.call_tool(name, arguments)
    content: dict[str, Any] = result.structured_content or {}
    return content


def code(content: dict[str, Any]) -> str | None:
    error = content.get("error") or {}
    return error.get("code")


def differs(found: np.ndarray | None, expected: np.ndarray | None) -> str:
    if found is None or expected is None:
        return "nothing to compare"
    if found.shape != expected.shape:
        return f"shape {found.shape}, not {expected.shape}"
    different = int(np.any(found != expected, axis=-1).sum())
    worst = int(np.abs(found.astype(int) - expected.astype(int)).max())
    return "" if different == 0 else f"{different} pixels differ, by up to {worst}"


def sheet_cell(sheet: dict[str, Any], column: int, row: int = 0, clean: bool = False) -> np.ndarray:
    # One cell of a krita_preview_render sheet, read from its PNG, as RGBA.
    with Image.open(sheet["clean_image" if clean else "image"]["path"]) as image:
        pixels = np.asarray(image.convert("RGBA"))
    x, y = sheet["columns"][column]["x_px"], sheet["rows"][row]["y_px"]
    width, height = sheet["cell_px"]
    return pixels[y : y + height, x : x + width]
