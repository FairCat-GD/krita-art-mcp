import json
from importlib.resources import files
from typing import Any


def tool_names() -> list[str]:
    return sorted(
        entry.name.removesuffix(".json")
        for entry in files(__name__).iterdir()
        if entry.name.endswith(".json")
    )


def load(tool_name: str) -> dict[str, Any]:
    tool: dict[str, Any] = json.loads(files(__name__).joinpath(f"{tool_name}.json").read_text())
    return tool
