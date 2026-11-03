import json
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import amend_schemas
import pytest
from amend_schemas import GUARD, SOURCE
from jsonschema import Draft202012Validator

from krita_art_mcp import imaging, schemas

PHASE_1_TOOLS = sorted(
    f"krita_{name}"
    for name in [
        "server_info",
        "document_list",
        "document_open",
        "document_create",
        "document_inspect",
        "resource_list",
        "capture",
        "sample",
        "layer_create",
        "layer_update",
        "selection_set",
        "protection_set",
        "paint_stroke",
        "history_step",
        "operation_get",
        "operation_cancel",
        "preview_render",
        "document_save",
        "document_close",
    ]
)


OPEN = schemas.load("krita_document_open")["example"]["input"]
NOT_YET_OPEN = {field: value for field, value in OPEN.items() if field != "working_dir"}
READ_ONLY = {**NOT_YET_OPEN, "mode": "read_only"}
LAYER_ID = "6f1c2d3e-4a5b-4c6d-8e9f-0a1b2c3d4e5f"
PREVIEW = schemas.load("krita_preview_render")["example"]["input"]
ERROR = {"code": "BUSY", "message": "Krita is busy.", "retryable": True, "details": {}}


def _with(tool_name: str, **changes: Any) -> dict[str, Any]:
    return {**schemas.load(tool_name)["example"]["input"], **changes}


def _preview(source: dict[str, Any], recipe: dict[str, Any] | None = None) -> dict[str, Any]:
    recipes = [recipe or PREVIEW["recipes"][0]]
    return {**PREVIEW, "sources": [{**PREVIEW["sources"][0], **source}], "recipes": recipes}


INPUT_RULES: list[tuple[str, dict[str, Any], bool]] = [
    *[
        (name, _with(name, target=target, layer_id=layer_id), valid)
        for name in ("krita_capture", "krita_sample")
        for target, layer_id, valid in [
            ("layer", "layer-1", True),
            ("layer", None, False),
            ("composite", None, True),
            ("composite", "layer-1", False),
        ]
    ],
    ("krita_document_open", OPEN, True),
    ("krita_document_open", NOT_YET_OPEN, False),
    ("krita_document_open", READ_ONLY, True),
    ("krita_document_open", {**READ_ONLY, "working_dir": "/projects/demo/work"}, False),
    ("krita_document_open", {**OPEN, "editable_layer_ids": [LAYER_ID]}, True),
    ("krita_document_open", {**READ_ONLY, "editable_layer_ids": [LAYER_ID]}, False),
    ("krita_document_open", {**READ_ONLY, "editable_layer_names": ["paint"]}, False),
    ("krita_preview_render", _preview({"target": "layer", "layer_id": "layer-1"}), True),
    ("krita_preview_render", _preview({"target": "layer"}), False),
    ("krita_preview_render", _preview({"layer_id": "layer-1"}), False),
    ("krita_preview_render", _preview({}, {"id": "r", "target_size_px": [8, 8]}), True),
    ("krita_preview_render", _preview({}, {"id": "r"}), False),
    (
        "krita_preview_render",
        _preview({}, {"id": "r", "target_pixels_per_unit": 2, "target_size_px": [8, 8]}),
        False,
    ),
    ("krita_document_create", _with("krita_document_create", size_px=[32]), False),
    ("krita_document_create", _with("krita_document_create", size_px=[32, 32, 32]), False),
    ("krita_document_create", _with("krita_document_create", size_px=["32", "32"]), False),
    ("krita_document_create", _with("krita_document_create", size_px=[0, 32]), False),
    ("krita_sample", _with("krita_sample", points=[[20]]), False),
    ("krita_sample", _with("krita_sample", points=[[20, 20, 20]]), False),
    *[
        (
            "krita_preview_render",
            {**PREVIEW, "backgrounds": [{"space": "srgb", "rgba": rgba}]},
            False,
        )
        for rgba in ([0, 0, 0], [0, 0, 0, 0, 0], ["0", "0", "0", "0"], [2, 0, 0, 0])
    ],
]
OUTPUT_RULES: list[tuple[dict[str, Any], bool]] = [
    ({}, True),
    ({"data": None}, False),
    ({"error": ERROR}, False),
    ({"status": "failed", "data": None, "error": ERROR}, True),
    ({"status": "failed", "data": None}, False),
    ({"status": "cancelled", "error": ERROR}, False),
    ({"status": "queued", "data": None, "operation_id": "op-1"}, True),
    ({"status": "running", "data": None, "operation_id": None}, False),
    ({"status": "queued", "data": None, "operation_id": "op-1", "error": ERROR}, False),
]


def test_one_schema_file_per_phase_1_tool() -> None:
    assert schemas.tool_names() == PHASE_1_TOOLS


@pytest.mark.parametrize("tool_name", PHASE_1_TOOLS)
def test_example_validates_against_its_schemas(tool_name: str) -> None:
    tool = schemas.load(tool_name)
    assert tool["name"] == tool_name
    for schema_key, example_key in [
        ("inputSchema", "input"),
        ("outputSchema", "structuredContent"),
    ]:
        schema: dict[str, Any] = tool[schema_key]
        Draft202012Validator.check_schema(schema)
        errors = list(Draft202012Validator(schema).iter_errors(tool["example"][example_key]))
        assert errors == [], [error.message for error in errors]


@pytest.mark.parametrize("tool_name", PHASE_1_TOOLS)
def test_input_schema_rejects_unknown_fields(tool_name: str) -> None:
    assert schemas.load(tool_name)["inputSchema"]["additionalProperties"] is False


def _shapes(value: Any, key: str) -> list[Any]:
    if isinstance(value, dict):
        found = [value[key]] if key in value else []
        return found + [shape for item in value.values() for shape in _shapes(item, key)]
    if isinstance(value, list):
        return [shape for item in value for shape in _shapes(item, key)]
    return []


def test_every_copy_of_guard_is_the_phase_1_guard() -> None:
    guards = [
        guard
        for name in PHASE_1_TOOLS
        for guard in _shapes(schemas.load(name)["inputSchema"].get("properties", {}), "guard")
    ]
    assert len(guards) == 8
    assert all(guard == GUARD for guard in guards)


def test_no_schema_or_example_carries_expected_revision() -> None:
    for name in PHASE_1_TOOLS:
        assert _shapes(schemas.load(name), "expected_revision") == [], name


def test_open_and_inspect_describe_a_layer_with_one_shape() -> None:
    layers = [
        shape
        for name in ("krita_document_open", "krita_document_inspect")
        for shape in _shapes(schemas.load(name)["outputSchema"], "layers")
    ]
    assert len(layers) == 4
    assert all(layer == layers[0] for layer in layers)
    entry = layers[0]["items"]
    assert entry["additionalProperties"] is False
    assert set(entry["required"]) == set(entry["properties"]) >= {"id", "parent_id", "protected"}


def test_every_copy_of_source_is_the_phase_1_source() -> None:
    found = {
        name: _shapes(schemas.load(name)["inputSchema"].get("properties", {}), "source")
        for name in PHASE_1_TOOLS
    }
    assert len(found["krita_capture"]) == len(found["krita_sample"]) == 1
    assert all(source == SOURCE for copies in found.values() for source in copies)


def test_every_filter_enum_is_the_filters_imaging_applies() -> None:
    enums = [
        shape["enum"] if "enum" in shape else shape["anyOf"][0]["enum"]
        for name in ("krita_capture", "krita_preview_render")
        for key in ("inputSchema", "outputSchema")
        for shape in _shapes(schemas.load(name)[key], "filter")
    ]
    assert len(enums) == 10
    assert all(enum == list(imaging.FILTERS) for enum in enums)


def test_no_example_source_carries_revision() -> None:
    for name in PHASE_1_TOOLS:
        for source in _shapes(schemas.load(name)["example"]["input"], "source"):
            assert "revision" not in source, name


@pytest.mark.parametrize("tool_name", PHASE_1_TOOLS)
def test_the_two_copies_of_data_in_an_output_schema_agree(tool_name: str) -> None:
    output = schemas.load(tool_name)["outputSchema"]
    assert output["properties"]["data"]["anyOf"][0] == output["then"]["properties"]["data"]


def _shown(schema: dict[str, Any]) -> Iterator[dict[str, Any]]:
    yield schema
    branches = [*schema.get("anyOf", []), *schema.get("oneOf", [])]
    children = [*schema.get("properties", {}).values(), *branches]
    for child in [*children, schema.get("items"), schema.get("additionalProperties")]:
        if isinstance(child, dict):
            yield from _shown(child)


def _hidden_from_codex(schema: dict[str, Any]) -> list[str]:
    # Codex renders a composition ahead of the `type` beside it, drops `if`, `then` and `else` and
    # `prefixItems`, and turns `items: false` into a list of strings.
    hidden: list[str] = []
    for node in _shown(schema):
        hidden += [key for key in ("allOf", "prefixItems") if key in node]
        hidden += ["items: false"] if node.get("items") is False else []
        branches = [*node.get("anyOf", []), *node.get("oneOf", [])]
        hidden += (
            ["a union beside a type"] if branches and node.keys() & {"type", "properties"} else []
        )
        hidden += [
            "an untyped branch" for branch in branches if not branch.keys() & {"type", "const"}
        ]
    return hidden


@pytest.mark.parametrize("tool_name", PHASE_1_TOOLS)
@pytest.mark.parametrize("schema_key", ["inputSchema", "outputSchema"])
def test_a_schema_keeps_to_the_forms_codex_shows_its_model(tool_name: str, schema_key: str) -> None:
    assert _hidden_from_codex(schemas.load(tool_name)[schema_key]) == []


@pytest.mark.parametrize(("tool_name", "arguments", "valid"), INPUT_RULES)
def test_the_input_rules_outside_a_schemas_properties_hold(
    tool_name: str, arguments: dict[str, Any], valid: bool
) -> None:
    schema = schemas.load(tool_name)["inputSchema"]
    assert Draft202012Validator(schema).is_valid(arguments) is valid


@pytest.mark.parametrize(("changes", "valid"), OUTPUT_RULES)
def test_the_output_rules_hold_for_every_status(changes: dict[str, Any], valid: bool) -> None:
    tool = schemas.load("krita_capture")
    result = {**tool["example"]["structuredContent"], **changes}
    assert Draft202012Validator(tool["outputSchema"]).is_valid(result) is valid


def test_a_stroke_reports_its_verification_in_layer_updates_shape() -> None:
    update = schemas.load("krita_layer_update")["outputSchema"]["properties"]["data"]["anyOf"][0]
    stroke = schemas.load("krita_paint_stroke")["outputSchema"]["properties"]["data"]["anyOf"][0]
    checked = update["properties"]["verification"]["anyOf"]
    assert stroke["properties"]["verification"] == checked[0] and checked[1] == {"type": "null"}


def test_the_schema_files_are_as_the_amendment_script_writes_them() -> None:
    assert amend_schemas.stale() == []


def test_the_amendment_script_finds_a_shared_shape_that_drifted(tmp_path: Path) -> None:
    folder = tmp_path / "schemas"
    shutil.copytree(amend_schemas.FOLDER, folder, ignore=shutil.ignore_patterns("*.py", "__*"))
    drifts: list[tuple[str, list[str | int]]] = [
        ("krita_sample.json", ["outputSchema", "then"]),
        ("krita_document_close.json", ["inputSchema", "properties", "guard"]),
    ]
    # Both copies of the stroke's verification, so only the copy from layer_update restores it.
    stroke_data: list[str | int] = ["outputSchema", "properties", "data", "anyOf", 0]
    rule_data: list[str | int] = ["outputSchema", "then", "properties", "data"]
    drifts += [
        ("krita_paint_stroke.json", [*data, "properties", "verification"])
        for data in (stroke_data, rule_data)
    ]
    for name, path in drifts:
        tool = json.loads((folder / name).read_text(encoding="utf-8"))
        shape = tool
        for key in path:
            shape = shape[key]
        shape.clear()
        text = json.dumps(tool, indent=2, ensure_ascii=False) + "\n"
        (folder / name).write_text(text, encoding="utf-8")
    assert amend_schemas.stale(folder) == [
        "krita_document_close.json",
        "krita_paint_stroke.json",
        "krita_sample.json",
    ]
