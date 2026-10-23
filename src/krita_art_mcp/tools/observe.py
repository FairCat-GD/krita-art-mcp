from typing import Any

from mcp.types import CallToolResult

from krita_art_mcp import __version__, envelope
from krita_art_mcp.bridge_client import WAIT_BUDGET_S, BridgeClient, Failed, Pending

LIMITS = {
    "stroke_points": 4096,
    "capture_pixels": 4096 * 4096,
    "wait_budget_seconds": int(WAIT_BUDGET_S),
}


def server_info(client: BridgeClient, arguments: dict[str, Any]) -> CallToolResult:
    outcome = client.call("server_info")
    if isinstance(outcome, Pending):
        return envelope.pending(outcome.status, outcome.operation_id)
    if isinstance(outcome, Failed):
        return envelope.failed(outcome.error, operation_id=outcome.operation_id)
    health = outcome.result
    data = {
        "session_id": health["session_id"],
        "server_version": __version__,
        "plugin_version": health["plugin_version"],
        "protocol": health["protocol"],
        "krita_version": health["krita_version"],
        "qt_major": health["qt_major"],
        "capabilities": health["capabilities"],
        "limits": dict(LIMITS),
    }
    text = (
        f"Krita {data['krita_version']}, plugin {data['plugin_version']}, "
        f"server {__version__}, protocol {data['protocol']}."
    )
    return envelope.completed(data, text, operation_id=outcome.operation_id)
