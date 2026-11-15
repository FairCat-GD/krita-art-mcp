from typing import Any

from mcp.types import CallToolResult

from krita_art_mcp import __version__
from krita_art_mcp.bridge_client import WAIT_BUDGET_S, Outcome
from krita_art_mcp.tools.dispatch import ToolCall, from_outcome

LIMITS: dict[str, Any] = {
    "stroke_points": 4096,
    # The largest capture image: max_px is 4096 at most.
    "capture_pixels": 4096 * 4096,
    # The largest area one capture reads, a whole 8k master; the plugin holds an equal copy.
    "capture_source_pixels": 8192 * 8192,
    "wait_budget_seconds": int(WAIT_BUDGET_S),
    # The plugin enforces these four; a test holds each to its constant there.
    "brush_size_px": {"min": 1, "max": 1000},
    "resource_page_size": 100,
    "stroke_overhang_size_fraction": 0.5,
    "dynamics_knots": {"min": 2, "max": 16},
}
RESOURCE_DATA = ("kind", "total", "resources", "next_cursor")
# The blend modes paint calls accept, as Krita's composite-op ids (K21); the plugin holds an equal
# list (`bridge_core.resources.BLEND_MODES`), with their names.
BLEND_MODES = (
    "normal",
    "multiply",
    "screen",
    "overlay",
    "soft_light_svg",
    "darken",
    "lighten",
    "color",
    "luminize",
    "behind",
)


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
        "allowed_roots": health["allowed_roots"],
    }


def _text(health: dict[str, Any]) -> str:
    return (
        f"Krita {health['krita_version']}, plugin {health['plugin_version']}, "
        f"server {__version__}, protocol {health['protocol']}."
    )


def resource_list(call: ToolCall, arguments: dict[str, Any]) -> CallToolResult:
    op_args = {key: arguments[key] for key in ("kind", "cursor", "limit")}
    return resource_receipt(call.bridge.call("resource.list", op_args))


def resource_receipt(outcome: Outcome) -> CallToolResult:
    def data(result: dict[str, Any]) -> dict[str, Any]:
        return {key: result[key] for key in RESOURCE_DATA}

    def text(result: dict[str, Any]) -> str:
        shown = len(result["resources"])
        return f"{shown} of {result['total']} {result['kind']} resources."

    return from_outcome(outcome, data, text)
