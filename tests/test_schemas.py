from typing import Any

import pytest
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
