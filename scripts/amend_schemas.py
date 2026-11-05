"""Writes the shapes the tool schemas share, so each has one home.

Usage: uv run scripts/amend_schemas.py [--check]

A tool's session edits its schema's input, the `data` under its output's properties, and its
example. This script then writes the envelope, `guard` and `source` into every schema, copies
each `data` into the completed rule, open's `layers` into inspect's, layer_update's
`verification` object into paint_stroke's and paint_fill's, the stroke's colour into sample's
`color` and the fill's, selection_set's rect, ellipse and polygon shapes into the fill's, and
formats the files.
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
                    "details": {
                        "type": "object",
                        "properties": {
                            "outcome": {"type": "string", "enum": list(errors.OUTCOMES)}
                        },
                    },
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
    # A stroke always reports its verification, so it takes only the object branch.
    checked = _data(tools["krita_layer_update"])["properties"]["verification"]["anyOf"][0]
    _data(tools["krita_paint_stroke"])["properties"]["verification"] = copy.deepcopy(checked)
    _data(tools["krita_paint_fill"])["properties"]["verification"] = copy.deepcopy(checked)
    # A mask's create reports its verification; a paint or group layer's is null.
    _data(tools["krita_layer_create"])["properties"]["verification"] = copy.deepcopy(
        _data(tools["krita_layer_update"])["properties"]["verification"]
    )
    # A sample's color is exactly what a stroke's brush.color and a fill's color take.
    taken = tools["krita_paint_stroke"]["inputSchema"]["properties"]["brush"]["properties"]["color"]
    sampled = _data(tools["krita_sample"])["properties"]["samples"]["items"]["properties"]["color"]
    sampled["anyOf"][0] = copy.deepcopy(taken)
    fill = tools["krita_paint_fill"]["inputSchema"]["properties"]
    fill["color"] = copy.deepcopy(taken)
    # A fill's mask paint is a stroke's.
    fill["mask"] = copy.deepcopy(
        tools["krita_paint_stroke"]["inputSchema"]["properties"]["brush"]["properties"]["mask"]
    )
    # A fill takes a selection's rect, ellipse and polygon as the selection does.
    selected = tools["krita_selection_set"]["inputSchema"]["properties"]["shape"]["oneOf"]
    by_type = {branch["properties"]["type"]["const"]: branch for branch in selected}
    fill["shape"]["oneOf"] = [
        copy.deepcopy(by_type.get(branch["properties"]["type"]["const"], branch))
        for branch in fill["shape"]["oneOf"]
    ]
    said = _data(tools["krita_operation_get"])["properties"]["outcome"]["anyOf"][0]
    said["enum"] = list(errors.OUTCOMES)
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
        # One chain, not an allOf: Codex renders an allOf ahead of the `type` beside it.
        output["if"] = {"properties": {"status": {"const": "completed"}}}
        output["then"] = {
            "properties": {"data": copy.deepcopy(_data(tool)), "error": {"type": "null"}}
        }
        output["else"] = {**copy.deepcopy(FAILED_RULE), "else": copy.deepcopy(PENDING_RULE)}
    return tools


def _text(tool: dict[str, Any]) -> str:
    return json.dumps(tool, indent=2, ensure_ascii=False) + "\n"


def stale(folder: Path = FOLDER) -> list[str]:
    return [path.name for path in _changes(folder)]


def _changes(folder: Path) -> dict[Path, str]:
    # Each file this script would change, with the text it would write.
    paths = {path.stem: path for path in sorted(folder.glob("*.json"))}
    current = {name: path.read_text(encoding="utf-8") for name, path in paths.items()}
    tools = amended({name: json.loads(text) for name, text in current.items()})
    rendered = {name: _text(tool) for name, tool in tools.items()}
    return {paths[name]: text for name, text in rendered.items() if text != current[name]}


def main(argv: list[str]) -> int:
    if argv not in ([], ["--check"]):
        print("usage: uv run scripts/amend_schemas.py [--check]")
        return 2
    changes = _changes(FOLDER)
    if argv:
        for path in changes:
            print(f"amend_schemas: {path.name} is not as this script writes it")
        return 1 if changes else 0
    for path, text in changes.items():
        path.write_text(text, encoding="utf-8")
        print(f"amend_schemas: wrote {path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
