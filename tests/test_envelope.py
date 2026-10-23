import json
from typing import Any

import bridge_core
import pytest
from bridge_core import errors as bridge_errors
from bridge_core.source_hash import source_hash as plugin_source_hash
from jsonschema import Draft202012Validator

from krita_art_mcp import envelope, errors, paths, plugin_files, schemas
from krita_art_mcp.instructions import INSTRUCTIONS

ENVELOPE_FIELDS = ["api_version", "status", "document_id", "revision", "operation_id", "error"]


def _shared_shape(tool_name: str) -> dict[str, Any]:
    # Everything in the output schema but each tool's own `data`.
    output = schemas.load(tool_name)["outputSchema"]
    rules = json.loads(json.dumps(output["allOf"]))
    for rule in rules:
        rule["then"].get("properties", {}).pop("data", None)
    return {
        "properties": {field: output["properties"][field] for field in ENVELOPE_FIELDS},
        "required": output["required"],
        "additionalProperties": output["additionalProperties"],
        "rules": rules,
        "data_may_be_null": {"type": "null"} in output["properties"]["data"]["anyOf"],
    }


def test_every_schema_carries_the_same_envelope_at_this_api_version() -> None:
    shapes = {name: _shared_shape(name) for name in schemas.tool_names()}
    first = shapes["krita_server_info"]
    assert [name for name, shape in shapes.items() if shape != first] == []
    assert first["properties"]["api_version"] == {"const": errors.API_VERSION}
    assert first["properties"]["revision"] == {"type": "null"}
    code = first["properties"]["error"]["anyOf"][0]["properties"]["code"]
    assert code["enum"] == list(errors.CODES)


def test_the_server_and_plugin_constants_agree() -> None:
    assert errors.PROTOCOL == bridge_core.PROTOCOL
    assert list(errors.CODES) == list(bridge_errors.CODES)


def test_the_server_and_plugin_hash_the_plugin_alike() -> None:
    package = paths.plugin_source() / paths.PLUGIN_NAME
    assert plugin_files.source_hash(package) == plugin_source_hash(package)


@pytest.mark.parametrize("tool_name", schemas.tool_names())
def test_every_error_and_pending_envelope_validates(tool_name: str) -> None:
    validator = Draft202012Validator(schemas.load(tool_name)["outputSchema"])
    results = [envelope.failure(code, details={"why": "test"}) for code in errors.CODES]
    results += [envelope.pending(status, "op-1") for status in ("queued", "running")]
    for result in results:
        assert result.structured_content is not None
        found = [error.message for error in validator.iter_errors(result.structured_content)]
        assert found == [], result.structured_content


def test_a_cancelled_operation_reports_status_cancelled() -> None:
    result = envelope.failure("CANCELLED")
    assert result.is_error is True
    assert result.structured_content is not None
    assert result.structured_content["status"] == "cancelled"
    assert result.content[0].type == "text"
    assert result.content[0].text == f"CANCELLED: {errors.CODES['CANCELLED'][1]}"


def test_the_instructions_fit_in_4096_characters() -> None:
    assert 0 < len(INSTRUCTIONS) <= 4096
