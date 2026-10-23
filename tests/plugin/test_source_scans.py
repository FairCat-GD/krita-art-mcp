import ast
import importlib.util
import sys
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[2] / "plugin"
PACKAGE = "krita_art_mcp_bridge"
CORE = f"{PACKAGE}.bridge_core"
ADAPTER = f"{PACKAGE}.krita_adapter"
# Calls that write raw pixels or overwrite a file. Filter.apply cannot be told apart by type, so
# every .apply is refused.
KRITA_CALLS = {"setPixelData", "saveAs", "apply"}
# Built-ins that run code, import by name, or reach the other built-ins.
CODE_BUILTINS = {"exec", "eval", "compile", "__import__", "vars", "__builtins__"}
CODE_MODULES = {"builtins", "importlib", "runpy", "code", "codeop"}
INDIRECT_ACCESS = {"attrgetter", "methodcaller", "__dict__", "__getattribute__"}
ATTRIBUTE_FUNCTIONS = {"getattr", "setattr", "delattr", "hasattr"}
KRITA_AND_QT = {"krita", "PyQt5", "PyQt6"}
# Removed by Python 3.12 or 3.13: the plugin runs on 3.10 and on Krita's bundled 3.13.
REMOVED_SINCE_3_10 = {
    "aifc", "asynchat", "asyncore", "audioop", "cgi", "cgitb", "chunk", "crypt", "distutils",
    "imghdr", "imp", "lib2to3", "mailcap", "msilib", "nis", "nntplib", "ossaudiodev", "pipes",
    "smtpd", "sndhdr", "spwd", "sunau", "telnetlib", "uu", "xdrlib",
}  # fmt: skip
STDLIB = set(sys.stdlib_module_names) - REMOVED_SINCE_3_10


def _sources() -> Iterator[tuple[str, bool, ast.Module]]:
    for path in sorted(PLUGIN.rglob("*.py")):
        parts = list(path.relative_to(PLUGIN).with_suffix("").parts)
        is_package = parts[-1] == "__init__"
        module = ".".join(parts[:-1] if is_package else parts)
        yield module, is_package, ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imports(tree: ast.Module, module: str, is_package: bool) -> Iterator[tuple[int, str, bool]]:
    package = module if is_package else module.rpartition(".")[0]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name, False
        elif isinstance(node, ast.ImportFrom):
            relative = "." * node.level + (node.module or "")
            try:
                base = importlib.util.resolve_name(relative, package) if node.level else relative
            except (ImportError, ValueError):
                yield node.lineno, f"{relative} (beyond the plugin)", True
                continue
            names = [f"{base}.{alias.name}" for alias in node.names] if not node.module else [base]
            for name in names:
                yield node.lineno, name, node.level > 0


def _top(name: str) -> str:
    return name.split(".")[0]


def _within(name: str, package: str) -> bool:
    return name == package or name.startswith(f"{package}.")


def _banned_uses(tree: ast.Module) -> list[str]:
    hits = []
    for node in ast.walk(tree):
        line = getattr(node, "lineno", 0)
        if isinstance(node, ast.Name) and node.id in KRITA_CALLS | CODE_BUILTINS | INDIRECT_ACCESS:
            hits.append(f"{line}: {node.id}")
        elif isinstance(node, ast.Attribute) and node.attr in KRITA_CALLS | INDIRECT_ACCESS:
            hits.append(f"{line}: .{node.attr}")
        elif isinstance(node, ast.Constant) and node.value in KRITA_CALLS:
            hits.append(f"{line}: string {node.value!r}")
        elif isinstance(node, ast.Import):
            if any(_top(alias.name) in CODE_MODULES for alias in node.names):
                hits.append(f"{line}: import of a code-running module")
        elif isinstance(node, ast.ImportFrom):
            names = {alias.name for alias in node.names}
            if _top(node.module or "") in CODE_MODULES:
                hits.append(f"{line}: import from {node.module}")
            elif names & (KRITA_CALLS | CODE_BUILTINS | INDIRECT_ACCESS):
                hits.append(f"{line}: import of {', '.join(sorted(names))}")
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in ATTRIBUTE_FUNCTIONS
            and not (len(node.args) >= 2 and isinstance(node.args[1], ast.Constant))
        ):
            hits.append(f"{line}: {node.func.id} with a computed name")
    return hits


def _unknown_imports(tree: ast.Module, module: str, is_package: bool) -> list[str]:
    # Own modules are imported relatively or through the package, as Krita loads them.
    allowed = STDLIB | KRITA_AND_QT | {PACKAGE}
    imports = _imports(tree, module, is_package)
    return [f"{line}: {name}" for line, name, _ in imports if _top(name) not in allowed]


def _misplaced_krita_imports(tree: ast.Module, module: str, is_package: bool) -> list[str]:
    if _within(module, ADAPTER):
        return []
    imports = _imports(tree, module, is_package)
    return [f"{line}: {name}" for line, name, _ in imports if _top(name) in KRITA_AND_QT]


def _impure_core_imports(tree: ast.Module, module: str, is_package: bool) -> list[str]:
    # The core imports the standard library, and itself relatively, so it loads outside Krita.
    if not _within(module, CORE):
        return []
    return [
        f"{line}: {name}"
        for line, name, relative in _imports(tree, module, is_package)
        if not (_within(name, CORE) if relative else _top(name) in STDLIB)
    ]


Rule = Callable[[ast.Module, str, bool], list[str]]


def test_plugin_sources_are_found() -> None:
    assert [module for module, _, _ in _sources()]


def test_plugin_never_names_a_banned_call() -> None:
    assert [f"{m}:{hit}" for m, _, tree in _sources() for hit in _banned_uses(tree)] == []


def test_plugin_imports_only_the_standard_library_qt_and_krita() -> None:
    hits = [f"{m}:{hit}" for m, p, tree in _sources() for hit in _unknown_imports(tree, m, p)]
    assert hits == []


def test_only_the_adapter_imports_krita_or_qt() -> None:
    hits = [f"{m}:{h}" for m, p, tree in _sources() for h in _misplaced_krita_imports(tree, m, p)]
    assert hits == []


def test_bridge_core_imports_only_the_standard_library_and_itself() -> None:
    hits = [f"{m}:{h}" for m, p, tree in _sources() for h in _impure_core_imports(tree, m, p)]
    assert hits == []


@pytest.mark.parametrize(
    "source",
    [
        "doc.saveAs(path)",
        "node.setPixelData(data, 0, 0, 1, 1)",
        "Filter().apply(node, 0, 0, 1, 1)",
        "exec(source)",
        "eval(source)",
        "compile(source, 'stroke', 'exec')",
        "__import__('krita')",
        "getattr(doc, 'save' + 'As')(path)",
        "getattr(doc, 'saveAs')",
        "setattr(doc, name, value)",
        "import builtins",
        "from builtins import open",
        "import importlib",
        "from importlib import import_module",
        "import runpy",
        "from operator import attrgetter",
        "operator.methodcaller(name)",
        "type(doc).__dict__[name]",
        "vars(doc)[name]",
        "__builtins__['open']",
    ],
)
def test_banned_uses_are_found(source: str) -> None:
    assert _banned_uses(ast.parse(source))


@pytest.mark.parametrize(
    "source",
    [
        "loop.exec()",
        "run = getattr(loop, 'exec', None) or loop.exec_",
        "pattern = re.compile('x')",
        "hasattr(node, 'paintPolylineStroke')",
        "doc.exportImage(path, info)",
        "Filter().startFilter(doc, node, 0, 0, 1, 1)",
    ],
)
def test_allowed_uses_pass(source: str) -> None:
    assert _banned_uses(ast.parse(source)) == []


@pytest.mark.parametrize(
    ("module", "source", "rule"),
    [
        (f"{CORE}.jobs", "from ..krita_adapter import main_thread", _impure_core_imports),
        (f"{CORE}.jobs", "from .. import krita_adapter", _impure_core_imports),
        (f"{CORE}.jobs", f"from {ADAPTER} import main_thread", _impure_core_imports),
        (f"{CORE}.jobs", f"import {PACKAGE}", _impure_core_imports),
        (f"{CORE}.jobs", f"from {CORE}.registry import Registry", _impure_core_imports),
        (f"{CORE}.jobs", "from ... import outside", _unknown_imports),
        (f"{CORE}.jobs", "import imp", _unknown_imports),
        (f"{CORE}.jobs", "import numpy", _unknown_imports),
        (f"{ADAPTER}.canvas", "import bridge_core", _unknown_imports),
        (f"{CORE}.jobs", "from PyQt5.QtCore import QObject", _misplaced_krita_imports),
        (PACKAGE, "from krita import Krita", _misplaced_krita_imports),
    ],
)
def test_import_rules_refuse(module: str, source: str, rule: Rule) -> None:
    assert rule(ast.parse(source), module, module == PACKAGE)


@pytest.mark.parametrize(
    ("module", "source"),
    [
        (f"{CORE}.jobs", "import json\nfrom . import registry\nfrom .registry import Registry"),
        (f"{ADAPTER}.canvas", "from krita import Krita\nfrom ..bridge_core import jobs"),
        (f"{ADAPTER}.canvas", f"from {CORE}.jobs import Job"),
        (PACKAGE, "from .krita_adapter import extension"),
    ],
)
def test_import_rules_allow(module: str, source: str) -> None:
    tree = ast.parse(source)
    rules: list[Rule] = [_unknown_imports, _misplaced_krita_imports, _impure_core_imports]
    assert [hit for rule in rules for hit in rule(tree, module, module == PACKAGE)] == []
