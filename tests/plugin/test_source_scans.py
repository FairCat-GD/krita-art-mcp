import ast
import sys
from collections.abc import Iterator
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[2] / "plugin"
BANNED_NAMES = {"setPixelData", "saveAs", "exec", "eval"}
# Filter.apply cannot be told apart by type, so every .apply is refused.
BANNED_ATTRIBUTES = BANNED_NAMES | {"apply"}
KRITA_AND_QT = {"krita", "PyQt5", "PyQt6"}
OWN_PACKAGES = {"krita_art_mcp_bridge", "bridge_core", "krita_adapter"}


def _sources() -> Iterator[tuple[Path, ast.Module]]:
    for path in sorted(PLUGIN.rglob("*.py")):
        yield path, ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _absolute_imports(tree: ast.Module) -> Iterator[tuple[int, str]]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.lineno, node.module.split(".")[0]


def test_plugin_sources_are_found() -> None:
    assert [path.name for path, _ in _sources()]


def test_plugin_never_names_a_banned_call() -> None:
    hits = []
    for path, tree in _sources():
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in BANNED_NAMES:
                hits.append(f"{path}:{node.lineno}: {node.id}")
            elif isinstance(node, ast.Attribute) and node.attr in BANNED_ATTRIBUTES:
                hits.append(f"{path}:{node.lineno}: .{node.attr}")
            elif isinstance(node, ast.alias) and node.name.split(".")[-1] in BANNED_NAMES:
                hits.append(f"{path}:{node.lineno}: import of {node.name}")
            elif isinstance(node, ast.Constant) and node.value in BANNED_ATTRIBUTES:
                hits.append(f"{path}:{node.lineno}: string {node.value!r}")
    assert hits == []


def test_plugin_imports_only_the_standard_library_qt_and_krita() -> None:
    allowed = set(sys.stdlib_module_names) | KRITA_AND_QT | OWN_PACKAGES
    hits = []
    for path, tree in _sources():
        for line, module in _absolute_imports(tree):
            if module not in allowed:
                hits.append(f"{path}:{line}: {module}")
    assert hits == []


def test_only_the_adapter_imports_krita_or_qt() -> None:
    hits = []
    for path, tree in _sources():
        if "krita_adapter" in path.relative_to(PLUGIN).parts:
            continue
        for line, module in _absolute_imports(tree):
            if module in KRITA_AND_QT:
                hits.append(f"{path}:{line}: {module}")
    assert hits == []
