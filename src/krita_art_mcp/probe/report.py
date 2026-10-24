import uuid
from typing import Any, TextIO

import numpy as np
from mcp import Client
from mcp.types import CallToolResult


class Report:
    def __init__(self, out: TextIO) -> None:
        self._out = out
        self.passed = 0
        self.failed = 0

    def check(self, name: str, passed: bool, detail: str = "") -> bool:
        if passed:
            self.passed += 1
        else:
            self.failed += 1
        self._line("PASS" if passed else "FAIL", name, detail)
        return passed

    def measured(self, name: str, detail: str) -> None:
        self._line("MEASURED", name, detail)

    def note(self, text: str) -> None:
        print(text, file=self._out, flush=True)

    def summary(self) -> int:
        self.note(f"probe: {self.passed} PASS, {self.failed} FAIL")
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


async def close(mcp: Client, document_id: str, policy: str = "discard") -> dict[str, Any]:
    guard = {"document_id": document_id, "request_id": str(uuid.uuid4())}
    return await tool(mcp, "krita_document_close", {"guard": guard, "dirty_policy": policy})


def differs(found: np.ndarray | None, expected: np.ndarray | None) -> str:
    if found is None or expected is None:
        return "nothing to compare"
    if found.shape != expected.shape:
        return f"shape {found.shape}, not {expected.shape}"
    different = int(np.any(found != expected, axis=-1).sum())
    worst = int(np.abs(found.astype(int) - expected.astype(int)).max())
    return "" if different == 0 else f"{different} pixels differ, by up to {worst}"
