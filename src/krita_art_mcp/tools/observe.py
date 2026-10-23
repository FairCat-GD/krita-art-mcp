from typing import Any

from mcp.types import CallToolResult

from krita_art_mcp import __version__
from krita_art_mcp.bridge_client import WAIT_BUDGET_S, Outcome
from krita_art_mcp.tools.dispatch import ToolCall, from_outcome

LIMITS = {
    "stroke_points": 4096,
    "capture_pixels": 4096 * 4096,
    "wait_budget_seconds": int(WAIT_BUDGET_S),
}


def server_info(call: ToolCall, arguments: dict[str, Any]) -> CallToolResult:
    return server_info_receipt(call.bridge.call("server_info"))


def server_info_receipt(outcome: Outcome) -> CallToolResult:
    return from_outcome(outcome, _data, _text)


def _data(health: dict[str, Any]) -> dict[str, Any]:
    return {
        "session_id": health["session_id"],
        "server_version": __version__,
        "plugin_version": health["plugin_version"],
        "protocol": health["protocol"],
        "krita_version": health["krita_version"],
        "qt_major": health["qt_major"],
        "capabilities": health["capabilities"],
        "limits": dict(LIMITS),
    }


def _text(health: dict[str, Any]) -> str:
    return (
        f"Krita {health['krita_version']}, plugin {health['plugin_version']}, "
        f"server {__version__}, protocol {health['protocol']}."
    )
