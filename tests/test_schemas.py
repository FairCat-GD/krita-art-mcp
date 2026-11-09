import json
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import amend_schemas
import codex_render
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
        "layer_duplicate",
        "layer_reorder",
        "layer_remove",
        "layer_update",
        "selection_set",
        "protection_set",
        "paint_stroke",
        "paint_fill",
        "history_step",
        "operation_get",
        "operation_cancel",
        "preview_render",
        "document_save",
        "document_duplicate",
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


# The native form (scale 1) and a selection take no background or greyscale.
CAPTURE_FORMS: list[tuple[dict[str, Any], bool]] = [
    ({"scale": 1, "target": "composite"}, True),
    ({"scale": 1, "target": "composite", "background": "checker"}, False),
    ({"scale": 1, "target": "composite", "greyscale": False}, False),
    ({"scale": 0.25, "target": "composite", "background": "checker", "greyscale": True}, True),
    ({"scale": 2, "target": "selection"}, True),
    ({"scale": 2, "target": "selection", "background": "transparent"}, False),
    ({"scale": 2, "target": "selection", "greyscale": True}, False),
    ({"scale": 2, "target": "mask", "layer_id": "mask-1"}, True),
    ({"scale": 2, "target": "mask", "layer_id": None}, False),
    ({"scale": 2, "target": "mask", "layer_id": "mask-1", "background": "checker"}, False),
    ({"scale": 2, "target": "mask", "layer_id": "mask-1", "greyscale": True}, False),
]
STROKE = schemas.load("krita_paint_stroke")["example"]["input"]
FILL = schemas.load("krita_paint_fill")["example"]["input"]
LAYER = schemas.load("krita_layer_create")["example"]["input"]
# Mask paint takes the colour's place, with no blend or alpha lock beside it.
MASK_PAINT: list[tuple[str, dict[str, Any], bool]] = [
    ("krita_paint_stroke", {**STROKE, "brush": {**STROKE["brush"], "mask": "hide"}}, False),
    (
        "krita_paint_stroke",
        {
            **STROKE,
            "brush": {
                **{
                    k: v
                    for k, v in STROKE["brush"].items()
                    if k not in ("color", "blend_mode", "alpha_lock")
                },
                "mask": "hide",
            },
        },
        True,
    ),
    (
        "krita_paint_stroke",
        {
            **STROKE,
            "brush": {
                **{k: v for k, v in STROKE["brush"].items() if k != "color"},
                "mask": "reveal",
                "blend_mode": "normal",
            },
        },
        False,
    ),
    (
        "krita_paint_fill",
        {**{k: v for k, v in FILL.items() if k != "color"}, "mask": "reveal"},
        True,
    ),
    ("krita_paint_fill", {**FILL, "mask": "reveal"}, False),
    (
        "krita_paint_fill",
        {**{k: v for k, v in FILL.items() if k != "color"}, "mask": "show"},
        False,
    ),
    ("krita_layer_create", {**LAYER, "type": "transparency_mask", "coverage": "all"}, True),
    ("krita_layer_create", {**LAYER, "type": "transparency_mask"}, False),
    ("krita_layer_create", {**LAYER, "coverage": "all"}, False),
]
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
    *[
        ("krita_capture", _with("krita_capture", **{"layer_id": None, **fields}), valid)
        for fields, valid in CAPTURE_FORMS
    ],
    *MASK_PAINT,
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


def _objects(schema: Any, path: str = "") -> Iterator[tuple[str, dict[str, Any]]]:
    # Every object an input can hold, however deep, through properties, items and unions.
    if isinstance(schema, dict):
        if schema.get("type") == "object" or "properties" in schema:
            yield path, schema
        for key, value in schema.items():
            yield from _objects(value, f"{path}/{key}")
    elif isinstance(schema, list):
        for index, value in enumerate(schema):
            yield from _objects(value, f"{path}/{index}")


@pytest.mark.parametrize("tool_name", PHASE_1_TOOLS)
def test_input_schema_rejects_unknown_fields(tool_name: str) -> None:
    open_ones = [
        path
        for path, found in _objects(schemas.load(tool_name)["inputSchema"])
        if found.get("type") == "object" and found.get("additionalProperties") is not False
    ]
    assert open_ones == []


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
    assert len(guards) == 13
    assert all(guard == GUARD for guard in guards)


def test_no_schema_or_example_carries_expected_revision() -> None:
    for name in PHASE_1_TOOLS:
        assert _shapes(schemas.load(name), "expected_revision") == [], name


def test_open_inspect_and_duplicate_describe_a_layer_with_one_shape() -> None:
    layers = [
        shape
        for name in ("krita_document_open", "krita_document_inspect", "krita_document_duplicate")
        for shape in _shapes(schemas.load(name)["outputSchema"], "layers")
    ]
    assert len(layers) == 6
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


def _bounded(schema: dict[str, Any], path: str = "") -> Iterator[tuple[str, dict[str, Any]]]:
    # Every property with both a minimum and a maximum, on itself or on its items.
    branches = [*schema.get("anyOf", []), *schema.get("oneOf", [])]
    for name, shape in schema.get("properties", {}).items():
        items = shape.get("items") if isinstance(shape.get("items"), dict) else {}
        if {"minimum", "maximum"} <= shape.keys() or {"minimum", "maximum"} <= items.keys():
            yield f"{path}/{name}", shape
        yield from _bounded(shape, f"{path}/{name}")
    for child in [*branches, schema.get("items")]:
        if isinstance(child, dict):
            yield from _bounded(child, path)


def _number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


@pytest.mark.parametrize("tool_name", PHASE_1_TOOLS)
def test_a_bounded_input_states_its_range_where_codex_shows_it(tool_name: str) -> None:
    # Codex drops minimum and maximum, and shows a property's description as a comment.
    for path, shape in _bounded(schemas.load(tool_name)["inputSchema"]):
        bounds = shape if "minimum" in shape else shape["items"]
        said = f"{_number(bounds['minimum'])} to {_number(bounds['maximum'])}"
        assert said in shape.get("description", ""), f"{tool_name}{path}"


# Codex's own test of what its renderer writes for a described property.
WEATHER = {
    "type": "object",
    "properties": {
        "weather": {
            "type": "array",
            "description": "look up weather for a given list of locations",
            "items": {
                "type": "object",
                "properties": {"location": {"type": "string"}},
                "required": ["location"],
            },
        }
    },
    "required": ["weather"],
}


def test_the_port_renders_codexs_own_case_as_codex_does() -> None:
    assert codex_render.render_input(WEATHER) == (
        "{\n  // look up weather for a given list of locations\n"
        "  weather: Array<{ location: string; }>;\n}"
    )


@pytest.mark.parametrize("tool_name", PHASE_1_TOOLS)
def test_codex_shows_every_input_and_output_whole(tool_name: str) -> None:
    tool = schemas.load(tool_name)
    # Over 5,000 bytes Codex strips the descriptions, then collapses deeper shapes.
    assert codex_render.normalised_bytes(tool["inputSchema"]) <= codex_render.COMPACT_BYTES
    # Every input field is typed, so none is shown as unknown; over 16,000 bytes all would be.
    shown = codex_render.render_input(tool["inputSchema"])
    types = [line for line in shown.splitlines() if not line.lstrip().startswith("//")]
    assert not any("unknown" in line for line in types)
    assert len(shown.encode()) <= codex_render.RENDER_BYTES
    output = codex_render.render_output(tool["outputSchema"])
    assert output != "unknown" and len(output.encode()) <= codex_render.RENDER_BYTES


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


@pytest.mark.parametrize("name", ["krita_paint_stroke", "krita_paint_fill"])
def test_a_paint_call_reports_its_verification_in_layer_updates_shape(name: str) -> None:
    update = schemas.load("krita_layer_update")["outputSchema"]["properties"]["data"]["anyOf"][0]
    painted = schemas.load(name)["outputSchema"]["properties"]["data"]["anyOf"][0]
    checked = update["properties"]["verification"]["anyOf"]
    assert painted["properties"]["verification"] == checked[0] and checked[1] == {"type": "null"}


def test_a_fill_takes_a_stroke_s_colour_and_a_selection_s_shapes() -> None:
    fill = schemas.load("krita_paint_fill")["inputSchema"]["properties"]
    stroke = schemas.load("krita_paint_stroke")["inputSchema"]["properties"]
    selected = schemas.load("krita_selection_set")["inputSchema"]["properties"]["shape"]["oneOf"]
    assert fill["color"] == stroke["brush"]["properties"]["color"]
    kinds = ("rect", "ellipse", "polygon")
    taken = [branch for branch in selected if branch["properties"]["type"]["const"] in kinds]
    assert fill["shape"]["oneOf"][1:4] == taken


def test_the_schema_files_are_as_the_amendment_script_writes_them() -> None:
    assert amend_schemas.stale() == []


SAMPLE_ITEM: list[str | int] = ["outputSchema", "properties", "data", "anyOf", 0]
SAMPLE_ITEM += ["properties", "samples", "items"]


def test_the_amendment_script_finds_a_shared_shape_that_drifted(tmp_path: Path) -> None:
    folder = tmp_path / "schemas"
    shutil.copytree(amend_schemas.FOLDER, folder, ignore=shutil.ignore_patterns("*.py", "__*"))
    drifts: list[tuple[str, list[str | int]]] = [
        ("krita_sample.json", ["outputSchema", "then"]),
        ("krita_document_close.json", ["inputSchema", "properties", "guard"]),
        ("krita_sample.json", [*SAMPLE_ITEM, "properties", "color", "anyOf", 0]),
    ]
    # Both copies of the stroke's verification, so only the copy from layer_update restores it.
    stroke_data: list[str | int] = ["outputSchema", "properties", "data", "anyOf", 0]
    rule_data: list[str | int] = ["outputSchema", "then", "properties", "data"]
    drifts += [
        ("krita_paint_stroke.json", [*data, "properties", "verification"])
        for data in (stroke_data, rule_data)
    ]
    fill_input: list[str | int] = ["inputSchema", "properties"]
    drifts += [
        ("krita_paint_fill.json", [*fill_input, "color"]),
        ("krita_paint_fill.json", [*fill_input, "shape", "oneOf", 3, "properties", "points"]),
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
        "krita_paint_fill.json",
        "krita_paint_stroke.json",
        "krita_sample.json",
    ]
