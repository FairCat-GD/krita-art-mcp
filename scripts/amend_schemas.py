"""Writes the shapes the tool schemas share, so each has one home.

Usage: uv run scripts/amend_schemas.py [--check]

A tool's session edits its schema's input, the `data` under its output's properties, and its
example. This script then writes the envelope, `guard` and `source` into every schema, copies
each `data` into the completed rule and open's `layers` into inspect's, and formats the files.
With --check it changes nothing and exits 1 if any file would change.
"""

import copy
import json
import sys
from pathlib import Path
from typing import Any

from krita_art_mcp import errors

FOLDER = Path(__file__).resolve().parent.parent / "src" / "krita_art_mcp" / "schemas"

_ID = {"anyOf": [{"type": "string", "minLength": 1}, {"type": "null"}]}
ENVELOPE: dict[str, Any] = {
    "api_version": {"const": errors.API_VERSION},
    "status": {"type": "string", "enum": ["completed", "queued", "running", "failed", "cancelled"]},
    "document_id": _ID,
    "revision": {"type": "null"},
    "operation_id": _ID,
    "error": {
        "anyOf": [
            {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "enum": list(errors.CODES)},
                    "message": {"type": "string", "minLength": 1},
                    "retryable": {"type": "boolean"},
                    "details": {"type": "object"},
                },
                "required": ["code", "message", "retryable", "details"],
                "additionalProperties": False,
            },
            {"type": "null"},
        ]
    },
}
REQUIRED = ["api_version", "status", "document_id", "revision", "operation_id", "data", "error"]
FAILED_RULE = {
    "if": {"properties": {"status": {"enum": ["failed", "cancelled"]}}},
    "then": {
        "properties": {"data": {"type": "null"}, "error": {"type": "object"}},
        "required": ["error"],
    },
}
PENDING_RULE = {
    "if": {"properties": {"status": {"enum": ["queued", "running"]}}},
    "then": {
        "properties": {
            "operation_id": {"type": "string", "minLength": 1},
            "data": {"type": "null"},
            "error": {"type": "null"},
        }
    },
}
GUARD = {
    "type": "object",
    "properties": {
        "document_id": {"type": "string", "minLength": 1},
        "request_id": {"type": "string", "minLength": 1},
    },
    "required": ["document_id", "request_id"],
    "additionalProperties": False,
}
SOURCE = {
    "type": "object",
    "properties": {
        "document_id": {"type": "string", "minLength": 1},
        "frame": {"type": "integer", "minimum": 0},
    },
    "required": ["document_id", "frame"],
    "additionalProperties": False,
}
# Inputs that take one of these fields take it in this one shape.
SHARED_INPUTS = {"guard": GUARD, "source": SOURCE}


def _data(tool: dict[str, Any]) -> dict[str, Any]:
    shape: dict[str, Any] = tool["outputSchema"]["properties"]["data"]["anyOf"][0]
    return shape


def amended(tools: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    tools = copy.deepcopy(tools)
    layers = _data(tools["krita_document_open"])["properties"]["layers"]
    _data(tools["krita_document_inspect"])["properties"]["layers"] = copy.deepcopy(layers)
    for tool in tools.values():
        inputs = tool["inputSchema"]["properties"]
        for field, shape in SHARED_INPUTS.items():
            if field in inputs:
                inputs[field] = copy.deepcopy(shape)
        output = tool["outputSchema"]
        for field, shape in ENVELOPE.items():
            output["properties"][field] = copy.deepcopy(shape)
        output["required"] = list(REQUIRED)
        output["additionalProperties"] = False
        completed = {
            "if": {"properties": {"status": {"const": "completed"}}},
            "then": {"properties": {"data": copy.deepcopy(_data(tool)), "error": {"type": "null"}}},
        }
        output["allOf"] = [completed, copy.deepcopy(FAILED_RULE), copy.deepcopy(PENDING_RULE)]
    return tools


def _text(tool: dict[str, Any]) -> str:
    return json.dumps(tool, indent=2, ensure_ascii=False) + "\n"


def stale(folder: Path = FOLDER) -> list[str]:
    # The files this script would change.
    return [path.name for path, text in _rendered(folder).items() if path.read_text() != text]


def _rendered(folder: Path) -> dict[Path, str]:
    paths = {path.stem: path for path in sorted(folder.glob("*.json"))}
    tools = {name: json.loads(path.read_text()) for name, path in paths.items()}
    return {paths[name]: _text(tool) for name, tool in amended(tools).items()}


def main(argv: list[str]) -> int:
    if argv not in ([], ["--check"]):
        print("usage: uv run scripts/amend_schemas.py [--check]")
        return 2
    changed = stale()
    if argv:
        for name in changed:
            print(f"amend_schemas: {name} is not as this script writes it")
        return 1 if changed else 0
    for path, text in _rendered(FOLDER).items():
        if path.name in changed:
            path.write_text(text)
            print(f"amend_schemas: wrote {path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
