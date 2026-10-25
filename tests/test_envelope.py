import json
import logging
from typing import Any

import bridge_core
import pytest
from bridge_core import documents as bridge_documents
from bridge_core import errors as bridge_errors
from bridge_core import history as bridge_history
from bridge_core import pixels as bridge_pixels
from bridge_core import processes as bridge_processes
from bridge_core import protection as bridge_protection
from bridge_core import resources as bridge_resources
from bridge_core import selections as bridge_selections
from bridge_core import verification as bridge_verification
from bridge_core.jobs import Jobs
from bridge_core.source_hash import source_hash as plugin_source_hash
from jsonschema import Draft202012Validator

from krita_art_mcp import envelope, errors, paths, plugin_files, processes, schemas, verification
from krita_art_mcp.bridge_client import WAIT_BUDGET_S
from krita_art_mcp.instructions import INSTRUCTIONS
from krita_art_mcp.tools import documents as tool_documents
from krita_art_mcp.tools import observe

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
    assert processes.PS_ENV == bridge_processes.PS_ENV
    assert (tool_documents.SRGB_PROFILE, tool_documents.DEPTH) == (
        bridge_documents.SRGB_PROFILE,
        bridge_documents.DEPTH,
    )
    assert observe.BLEND_MODES == tuple(mode for mode, _ in bridge_resources.BLEND_MODES)
    flags = (verification.CHANGED, verification.OUTSIDE, verification.ALPHA)
    assert flags == (
        bridge_verification.CHANGED,
        bridge_verification.OUTSIDE,
        bridge_verification.ALPHA,
    )


def test_the_blend_enum_agents_send_is_the_whitelist() -> None:
    update = schemas.load("krita_layer_update")["inputSchema"]["properties"]
    assert tuple(update["properties"]["properties"]["blend_mode"]["enum"]) == observe.BLEND_MODES
    assert update["verify"]["enum"] == list(bridge_verification.MODES)


def test_the_plugins_bounds_are_the_schemas_limits() -> None:
    sample = schemas.load("krita_sample")["inputSchema"]["properties"]
    assert sample["points"]["maxItems"] == bridge_pixels.MAX_POINTS
    assert sample["radius"]["maximum"] == bridge_pixels.MAX_RADIUS
    listing = schemas.load("krita_resource_list")["inputSchema"]["properties"]
    assert listing["limit"]["maximum"] == bridge_resources.MAX_LIMIT
    selection = schemas.load("krita_selection_set")["inputSchema"]["properties"]
    for field in ("grow_px", "shrink_px", "feather_px"):
        assert selection[field]["maximum"] == bridge_selections.MAX_MODIFIER_PX
    history = schemas.load("krita_history_step")["inputSchema"]["properties"]
    assert history["steps"]["maximum"] == bridge_history.MAX_STEPS
    protection = schemas.load("krita_protection_set")["inputSchema"]["properties"]
    assert protection["protected_layer_ids"]["maxItems"] == bridge_protection.MAX_PROTECTED
    assert bridge_verification.MAX_IMAGE_PIXELS == observe.LIMITS["capture_pixels"]


def test_a_cancelled_call_is_retryable_alike_on_both_sides() -> None:
    # It never ran, whether cancelled or failed at stop, so a retry under its request_id runs.
    client = {"pid": 1, "started_at": "test"}
    log = logging.getLogger("test_envelope")
    jobs = Jobs({"record": lambda args, call: {}}, lambda: None, lambda: True, log)
    jobs.submit("op-1", "req-1", "record", {}, client)
    jobs.submit("op-2", "req-2", "record", {}, client)
    cancelled = jobs.cancel("op-1")
    jobs.stop()
    stopped = jobs.wait("op-2", 0)
    assert cancelled is not None and stopped is not None
    found = {cancelled[0]["error"]["retryable"], stopped["error"]["retryable"]}
    assert found == {errors.CODES["CANCELLED"][0]} == {True}


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


def test_the_instructions_fit_in_4096_characters_and_name_the_wait_budget() -> None:
    assert 0 < len(INSTRUCTIONS) <= 4096
    assert f"{WAIT_BUDGET_S:.0f}-second wait" in INSTRUCTIONS
