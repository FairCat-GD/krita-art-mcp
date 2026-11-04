from typing import Any

import pytest
from worlds import World


def refused_alike(
    world: World,
    monkeypatch: pytest.MonkeyPatch,
    tool: str,
    arguments: dict[str, Any],
    rule: tuple[object, str],
) -> dict[str, Any]:
    # One argument rule written on both sides (decision 10). The server refuses before anything is
    # sent; with its rule off, its own translation carries the same arguments to the plugin, which
    # must refuse them alike before its marker. rule is the server's function, by module and name.
    server = world.server()
    ours = server.content(tool, arguments)
    assert ours["status"] == "failed" and ours["operation_id"] is None, ours
    module, name = rule
    monkeypatch.setattr(module, name, lambda *args: None)
    theirs = server.content(tool, arguments)
    assert theirs["status"] == "failed" and theirs["operation_id"] is not None, theirs
    mine, plugin = ours["error"], theirs["error"]
    assert (plugin["code"], plugin["retryable"]) == (mine["code"], mine["retryable"]), plugin
    # A read's refusal on the server states no outcome; the plugin's always does.
    assert plugin["details"]["outcome"] == mine["details"].get("outcome", "not_applied")
    assert plugin["details"]["outcome"] == "not_applied"
    found: dict[str, Any] = plugin
    return found
