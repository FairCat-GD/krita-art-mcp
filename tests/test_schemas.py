import json
import shutil
from pathlib import Path
from typing import Any

import amend_schemas
import pytest
from amend_schemas import GUARD, SOURCE
from jsonschema import Draft202012Validator

from krita_art_mcp import schemas

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


def test_no_example_source_carries_revision() -> None:
    for name in PHASE_1_TOOLS:
        for source in _shapes(schemas.load(name)["example"]["input"], "source"):
            assert "revision" not in source, name


@pytest.mark.parametrize("tool_name", PHASE_1_TOOLS)
def test_the_two_copies_of_data_in_an_output_schema_agree(tool_name: str) -> None:
    output = schemas.load(tool_name)["outputSchema"]
    assert (
        output["properties"]["data"]["anyOf"][0] == output["allOf"][0]["then"]["properties"]["data"]
    )


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
        ("krita_sample.json", ["outputSchema", "allOf", 0, "then"]),
        ("krita_document_close.json", ["inputSchema", "properties", "guard"]),
    ]
    # Both copies of the stroke's verification, so only the copy from layer_update restores it.
    stroke_data: list[str | int] = ["outputSchema", "properties", "data", "anyOf", 0]
    rule_data: list[str | int] = ["outputSchema", "allOf", 0, "then", "properties", "data"]
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
