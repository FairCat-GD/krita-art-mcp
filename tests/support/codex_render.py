# What Codex shows its model of a tool's schemas, ported from Codex rust-v0.166.0 (the same files
# at main 71a4c070, 2026-11-04): codex-rs/tools/src/json_schema.rs and json_schema/{types,
# compaction}.rs, and codex-rs/code-mode-protocol/src/json_schema_types.rs. Refs and nested
# resources are not ported; no schema here has one, so one that does is refused.

import copy
import json
import re
from typing import Any

# An input whose normalised JSON is longer is compacted: descriptions first, then deeper shapes.
COMPACT_BYTES = 5_000
# A rendered input or output longer than this is shown as `unknown`.
RENDER_BYTES = 16_000
# Rendering charges every intermediate string against this multiple of its limit.
WORK_MULTIPLIER = 4

TYPES = ("string", "number", "boolean", "integer", "object", "array", "null")
# The keywords Codex's schema struct keeps; any other is dropped from an input.
STRUCT_KEYS = (
    "$ref",
    "type",
    "description",
    "encrypted",
    "enum",
    "items",
    "minItems",
    "properties",
    "required",
    "additionalProperties",
    "anyOf",
    "oneOf",
    "allOf",
    "$defs",
    "definitions",
)
UNPORTED = ("$ref", "$defs", "definitions", "$id")
COMPOSITIONS = ("anyOf", "oneOf", "allOf")
IDENTIFIER = re.compile(r"^[_$A-Za-z][_$A-Za-z0-9]*$")


def normalised(input_schema: dict[str, Any]) -> dict[str, Any]:
    # The input as Codex holds it, before any compaction.
    _refuse_unported(input_schema)
    schema = copy.deepcopy(input_schema)
    if schema.get("properties") is None:
        schema["properties"] = {}
    _sanitize(schema)
    kept: dict[str, Any] = _struct(schema)
    return kept


def normalised_bytes(input_schema: dict[str, Any]) -> int:
    # Compact JSON in UTF-8, as serde_json writes it.
    text = json.dumps(normalised(input_schema), separators=(",", ":"), ensure_ascii=False)
    return len(text.encode("utf-8"))


def render_input(input_schema: dict[str, Any]) -> str:
    return render(normalised(input_schema))


def render_output(output_schema: dict[str, Any]) -> str:
    # An output is rendered as the server sent it, never sanitized.
    _refuse_unported(output_schema)
    return render(output_schema)


def render(schema: Any, max_bytes: int = RENDER_BYTES) -> str:
    rendered = _Renderer(max_bytes).render(schema)
    return "unknown" if len(rendered.encode("utf-8")) > max_bytes else rendered


def _refuse_unported(value: Any) -> None:
    if isinstance(value, dict):
        found = [key for key in UNPORTED if key in value]
        if found:
            raise ValueError(f"the port does not render {found}")
        for item in value.values():
            _refuse_unported(item)
    elif isinstance(value, list):
        for item in value:
            _refuse_unported(item)


def _sanitize(value: Any) -> Any:
    # Returns the value to put in place, since a bool schema is replaced.
    if isinstance(value, bool):
        return {"type": "string"}
    if isinstance(value, list):
        value[:] = [_sanitize(item) for item in value]
        return value
    if not isinstance(value, dict):
        return value
    properties = value.get("properties")
    if isinstance(properties, dict):
        for name in properties:
            properties[name] = _sanitize(properties[name])
    if "items" in value:
        value["items"] = _sanitize(value["items"])
    if "additionalProperties" in value and not isinstance(value["additionalProperties"], bool):
        value["additionalProperties"] = _sanitize(value["additionalProperties"])
    for key in ("prefixItems", *COMPOSITIONS):
        if key in value:
            value[key] = _sanitize(value[key])
    if "const" in value:
        value["enum"] = [value.pop("const")]
    types = _types(value)
    if not types and ("$ref" in value or any(key in value for key in COMPOSITIONS)):
        return value
    if not types:
        if value.keys() & {"properties", "required", "additionalProperties"}:
            types = ["object"]
        elif value.keys() & {"items", "prefixItems"}:
            types = ["array"]
        elif value.keys() & {"enum", "format"}:
            types = ["string"]
        elif value.keys() & {
            "minimum",
            "maximum",
            "exclusiveMinimum",
            "exclusiveMaximum",
            "multipleOf",
        }:
            types = ["number"]
        else:
            value.clear()
            return value
    value["type"] = types[0] if len(types) == 1 else types
    if "object" in types and "properties" not in value:
        value["properties"] = {}
    if "array" in types and "items" not in value:
        value["items"] = {"type": "string"}
    return value


def _types(value: dict[str, Any]) -> list[str]:
    named = value.get("type")
    if isinstance(named, str):
        return [named] if named in TYPES else []
    if isinstance(named, list):
        return [name for name in named if isinstance(name, str) and name in TYPES]
    return []


def _struct(value: dict[str, Any]) -> dict[str, Any]:
    # The round trip through Codex's JsonSchema struct: unknown keywords are dropped.
    kept = {key: value[key] for key in STRUCT_KEYS if key in value}
    if isinstance(kept.get("items"), dict):
        kept["items"] = _struct(kept["items"])
    if isinstance(kept.get("properties"), dict):
        kept["properties"] = {name: _struct(shape) for name, shape in kept["properties"].items()}
    if isinstance(kept.get("additionalProperties"), dict):
        kept["additionalProperties"] = _struct(kept["additionalProperties"])
    for key in COMPOSITIONS:
        if key in kept:
            kept[key] = [_struct(branch) for branch in kept[key]]
    return kept


def _size(text: str) -> int:
    return len(text.encode("utf-8"))


def _literal(value: Any) -> str:
    # serde_json's compact form.
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def _literal_bound(value: Any) -> int:
    # Codex's upper bound on a literal's length, checked before it is written.
    if value is None or value is True:
        return 4
    if value is False:
        return 5
    if isinstance(value, int | float):
        return len(_literal(value))
    if isinstance(value, str):
        return _size(value) * 6 + 2
    if isinstance(value, list):
        return 2 + sum(1 + _literal_bound(item) for item in value)
    return 2 + sum(4 + _size(key) * 6 + _literal_bound(item) for key, item in value.items())


class _Renderer:
    def __init__(self, max_bytes: int) -> None:
        self.remaining = max_bytes * WORK_MULTIPLIER
        self.exhausted = False

    def render(self, schema: Any) -> str:
        if self.exhausted:
            return "unknown"
        if schema is True:
            rendered = "unknown"
        elif schema is False:
            rendered = "never"
        elif isinstance(schema, dict):
            rendered = self._map(schema)
        else:
            rendered = "unknown"
        return rendered if self._consume(_size(rendered)) else "unknown"

    def _consume(self, size: int) -> bool:
        if size > self.remaining:
            self.exhausted = True
            return False
        self.remaining -= size
        return True

    def _push(self, lines: list[str], line: str) -> bool:
        if not self._consume(_size(line)):
            return False
        lines.append(line)
        return True

    def _literal(self, value: Any) -> str:
        if _literal_bound(value) > self.remaining:
            self.exhausted = True
            return "unknown"
        return _literal(value)

    def _map(self, schema: dict[str, Any]) -> str:
        if self.exhausted:
            return "unknown"
        if "const" in schema:
            return self._literal(schema["const"])
        values = schema.get("enum")
        if isinstance(values, list) and values:
            literals = []
            for value in values:
                literal = self._literal(value)
                if self.exhausted or not self._consume(_size(literal)):
                    return "unknown"
                literals.append(literal)
            return " | ".join(literals)
        for key in ("anyOf", "oneOf"):
            branches = schema.get(key)
            if isinstance(branches, list) and branches:
                rendered = []
                for branch in branches:
                    if self.exhausted:
                        return "unknown"
                    rendered.append(self.render(branch))
                return " | ".join(rendered)
        branches = schema.get("allOf")
        if isinstance(branches, list) and branches:
            rendered = []
            for branch in branches:
                if self.exhausted:
                    return "unknown"
                one = self.render(branch)
                rendered.append(f"({one})" if " | " in one else one)
            return " & ".join(rendered)
        named = schema.get("type")
        if isinstance(named, list):
            rendered = []
            for name in (name for name in named if isinstance(name, str)):
                if self.exhausted:
                    return "unknown"
                rendered.append(self._type(schema, name))
            if rendered:
                return " | ".join(rendered)
        if isinstance(named, str):
            return self._type(schema, named)
        if schema.keys() & {"properties", "additionalProperties", "required"}:
            return self._object(schema)
        if schema.keys() & {"items", "prefixItems"}:
            return self._array(schema)
        return "unknown"

    def _type(self, schema: dict[str, Any], name: str) -> str:
        simple = {
            "string": "string",
            "number": "number",
            "integer": "number",
            "boolean": "boolean",
            "null": "null",
        }
        if name in simple:
            return simple[name]
        if name == "array":
            return self._array(schema)
        if name == "object":
            return self._object(schema)
        return "unknown"

    def _array(self, schema: dict[str, Any]) -> str:
        if "items" in schema:
            item = self.render(schema["items"])
            return "unknown" if self.exhausted else f"Array<{item}>"
        items = schema.get("prefixItems")
        if isinstance(items, list) and items:
            rendered = []
            for one in items:
                if self.exhausted:
                    return "unknown"
                rendered.append(self.render(one))
            return f"[{', '.join(rendered)}]"
        return "unknown[]"

    def _index_line(
        self, lines: list[str], schema: dict[str, Any], properties: dict[str, Any], prefix: str
    ) -> bool:
        if "additionalProperties" in schema:
            extra = schema["additionalProperties"]
            if extra is False:
                return True
            shown = "unknown" if extra is True else self.render(extra)
            return self._push(lines, f"{prefix}[key: string]: {shown};")
        if not properties:
            return self._push(lines, f"{prefix}[key: string]: unknown;")
        return True

    def _property(self, name: str, shape: Any, required: list[str]) -> str:
        if _size(name) > self.remaining:
            self.exhausted = True
            return "unknown"
        optional = "" if name in required else "?"
        shown = name if IDENTIFIER.match(name) else _literal(name)
        rendered = self.render(shape)
        return "unknown" if self.exhausted else f"{shown}{optional}: {rendered};"

    def _object(self, schema: dict[str, Any]) -> str:
        required = [name for name in schema.get("required", []) if isinstance(name, str)]
        properties = schema.get("properties")
        properties = properties if isinstance(properties, dict) else {}
        ordered = sorted(properties.items(), key=lambda pair: pair[0].encode("utf-8"))
        if any(_described(shape) for _, shape in ordered):
            lines: list[str] = []
            if not self._push(lines, "{"):
                return "unknown"
            for name, shape in ordered:
                description = shape.get("description") if isinstance(shape, dict) else None
                if isinstance(description, str):
                    for line in (part.strip() for part in description.split("\n")):
                        if not line:
                            continue
                        if _size(line) + 5 > self.remaining or not self._push(
                            lines, f"  // {line}"
                        ):
                            return "unknown"
                rendered = self._property(name, shape, required)
                if self.exhausted or not self._push(lines, f"  {rendered}"):
                    return "unknown"
            if not self._index_line(lines, schema, properties, "  ") or not self._push(lines, "}"):
                return "unknown"
            return "\n".join(lines)
        lines = []
        for name, shape in ordered:
            rendered = self._property(name, shape, required)
            if self.exhausted or not self._push(lines, rendered):
                return "unknown"
        if not self._index_line(lines, schema, properties, ""):
            return "unknown"
        return "{ " + " ".join(lines) + " }" if lines else "{}"


def _described(shape: Any) -> bool:
    return (
        isinstance(shape, dict)
        and isinstance(shape.get("description"), str)
        and bool(shape["description"])
    )
