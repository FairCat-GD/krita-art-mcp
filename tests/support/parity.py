import copy
from typing import Any

import pytest
from worlds import World

from krita_art_mcp import schemas


def refused_alike(
    world: World,
    monkeypatch: pytest.MonkeyPatch,
    tool: str,
    arguments: dict[str, Any],
    rule: tuple[object, str] | None = None,
    *,
    schema: tuple[str | int, ...] | None = None,
    off: Any = None,
) -> dict[str, Any]:
    # Decision 10: with the server's half off, the plugin must refuse alike. A rule in a named
    # function (module, name) is switched off, answering off, what it answers when it finds
    # nothing; a rule in the schema, the keyword at that path from the tool's schema, is cut
    # from the copy a second server is built with.
    server = world.server()
    ours = server.content(tool, arguments)
    assert ours["status"] == "failed" and ours["operation_id"] is None, ours
    if rule is not None:
        module, name = rule
        monkeypatch.setattr(module, name, lambda *args: off)
    if schema is not None:
        monkeypatch.setattr(schemas, "load", _without(schemas.load, tool, schema))
        server = world.server()
    theirs = server.content(tool, arguments)
    assert theirs["status"] == "failed" and theirs["operation_id"] is not None, theirs
    mine, plugin = ours["error"], theirs["error"]
    assert (plugin["code"], plugin["retryable"]) == (mine["code"], mine["retryable"]), plugin
    # A read's refusal on the server states no outcome; the plugin's always does.
    assert plugin["details"]["outcome"] == mine["details"].get("outcome", "not_applied")
    assert plugin["details"]["outcome"] == "not_applied"
    return dict(plugin)


def _without(load: Any, tool: str, path: tuple[str | int, ...]) -> Any:
    def cut(name: str) -> dict[str, Any]:
        found: dict[str, Any] = copy.deepcopy(load(name))
        if name == tool:
            *parents, key = path
            node: Any = found
            for part in parents:
                node = node[part]
            del node[key]
        return found

    return cut
