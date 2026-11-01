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
# The one exception (invariant 1, amended 2026-10-24): one adapter function loads a mask into a
# Selection it has just built, which writes no layer (K11).
SELECTION_MODULE = f"{ADAPTER}.selections"
SELECTION_FUNCTION = "_from_mask"
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


def _banned_uses(tree: ast.Module, allowed: frozenset[int] = frozenset()) -> list[str]:
    hits = []
    for node in ast.walk(tree):
        line = getattr(node, "lineno", 0)
        if isinstance(node, ast.Name) and node.id in KRITA_CALLS | CODE_BUILTINS | INDIRECT_ACCESS:
            hits.append(f"{line}: {node.id}")
        elif (
            isinstance(node, ast.Attribute)
            and node.attr in KRITA_CALLS | INDIRECT_ACCESS
            and id(node) not in allowed
        ):
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


def _bindings(scope: ast.AST, name: str) -> tuple[int, int]:
    # How often scope binds name as `name = Selection()`, and in every other way.
    good: set[int] = set()
    other = 0
    for node in ast.walk(scope):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == name
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "Selection"
            and not node.value.args
            and not node.value.keywords
        ):
            good.add(id(node.targets[0]))
    for node in ast.walk(scope):
        bound: list[str | None] = []
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            if id(node) in good:
                continue
            bound = [node.id]
        elif isinstance(node, ast.arg):
            bound = [node.arg]
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            bound = list(node.names)
        elif isinstance(node, ast.ExceptHandler):
            bound = [node.name]
        elif isinstance(node, (ast.MatchAs, ast.MatchStar)):
            bound = [node.name]
        elif isinstance(node, ast.MatchMapping):
            bound = [node.rest]
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            bound = [alias.asname or alias.name.split(".")[0] for alias in node.names]
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound = [node.name] if node is not scope else []
        other += bound.count(name)
    return len(good), other


def _selection_from_krita(tree: ast.Module) -> bool:
    # Selection is bound once in the module, by `from krita import Selection`.
    imports = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "krita"
        and node.level == 0
        and any(alias.name == "Selection" and alias.asname is None for alias in node.names)
    ]
    good, other = _bindings(tree, "Selection")
    return len(imports) == 1 and good == 0 and other == 1


def _allowed_selection_writes(tree: ast.Module, module: str) -> frozenset[int]:
    # The setPixelData attribute of the one allowed call, or nothing.
    if module != SELECTION_MODULE or not _selection_from_krita(tree):
        return frozenset()
    functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == SELECTION_FUNCTION
    ]
    if len(functions) != 1:
        return frozenset()
    function = functions[0]
    nested = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)
    if any(isinstance(node, nested) for node in ast.walk(function) if node is not function):
        return frozenset()
    calls = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "setPixelData"
    ]
    # Only the first is exempt, so a second site is always banned.
    if not calls or not isinstance(calls[0].func, ast.Attribute):
        return frozenset()
    receiver = calls[0].func.value
    if not isinstance(receiver, ast.Name) or _bindings(function, receiver.id) != (1, 0):
        return frozenset()
    return frozenset({id(calls[0].func)})


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


# Every read libkis offers; never setPixelData, whose one allowed site writes without a wait.
PIXEL_READS = ("pixelData", "projectionPixelData", "pixelDataAtTime")


def _reads_before_waiting(tree: ast.Module) -> list[str]:
    # Invariant 6: a function that reads pixels calls waitForDone() before its first read.
    hits = []
    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        calls = sorted(
            (node.lineno, node.col_offset, node.func.attr)
            for node in ast.walk(function)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in (*PIXEL_READS, "waitForDone")
        )
        names = [name for _, _, name in calls]
        first = next((index for index, name in enumerate(names) if name in PIXEL_READS), None)
        if first is not None and "waitForDone" not in names[:first]:
            hits.append(f"{function.lineno}: {function.name}")
    return hits


Rule = Callable[[ast.Module, str, bool], list[str]]


def test_plugin_sources_are_found() -> None:
    assert [module for module, _, _ in _sources()]


def test_plugin_never_names_a_banned_call() -> None:
    hits = [
        f"{m}:{hit}"
        for m, _, tree in _sources()
        for hit in _banned_uses(tree, _allowed_selection_writes(tree, m))
    ]
    assert hits == []


def test_exactly_one_selection_write_is_allowed_and_it_is_the_adapters() -> None:
    allowed = [(m, len(_allowed_selection_writes(tree, m))) for m, _, tree in _sources()]
    assert [(m, n) for m, n in allowed if n] == [(SELECTION_MODULE, 1)]


ALLOWED_WRITE = """
from krita import Selection


def _from_mask(data, x, y, width, height):
    selection = Selection()
    selection.setPixelData(data, x, y, width, height)
    return selection
"""


def test_the_allowed_write_passes_the_scan() -> None:
    tree = ast.parse(ALLOWED_WRITE)
    allowed = _allowed_selection_writes(tree, SELECTION_MODULE)
    assert len(allowed) == 1 and _banned_uses(tree, allowed) == []


@pytest.mark.parametrize(
    ("module", "source"),
    [
        (f"{ADAPTER}.documents", ALLOWED_WRITE),
        (SELECTION_MODULE, ALLOWED_WRITE.replace("_from_mask", "_paint")),
        (
            SELECTION_MODULE,
            ALLOWED_WRITE.replace("width, height):", "width, height, selection):").replace(
                "    selection = Selection()\n", ""
            ),
        ),
        (
            SELECTION_MODULE,
            ALLOWED_WRITE.replace(
                "    selection = Selection()\n",
                "    selection = Selection()\n    selection = layer\n",
            ),
        ),
        (SELECTION_MODULE, ALLOWED_WRITE.replace("Selection()", "Selection(layer)")),
        (
            SELECTION_MODULE,
            ALLOWED_WRITE.replace(
                "    return selection", "    selection.setPixelData(data, 0, 0, 1, 1)"
            ),
        ),
        (
            SELECTION_MODULE,
            ALLOWED_WRITE.replace("    return selection", "    (selection := layer)"),
        ),
        (
            SELECTION_MODULE,
            ALLOWED_WRITE.replace(
                "    return selection", "    for selection in layers:\n        pass"
            ),
        ),
        (
            SELECTION_MODULE,
            ALLOWED_WRITE.replace("    return selection", "    run = lambda: selection"),
        ),
        (SELECTION_MODULE, ALLOWED_WRITE + "\nSelection = Node\n"),
        (SELECTION_MODULE, ALLOWED_WRITE.replace("from krita import", "from other import")),
        (SELECTION_MODULE, ALLOWED_WRITE + "\n\ndef _from_mask(data):\n    pass\n"),
    ],
    ids=[
        "another module",
        "another function",
        "a parameter receiver",
        "a reassigned receiver",
        "Selection with an argument",
        "a second site",
        "a walrus",
        "a loop target",
        "a lambda inside",
        "a shadowed Selection",
        "Selection from elsewhere",
        "two functions of the name",
    ],
)
def test_any_other_selection_write_is_banned(module: str, source: str) -> None:
    tree = ast.parse(source)
    assert _banned_uses(tree, _allowed_selection_writes(tree, module))


def test_plugin_imports_only_the_standard_library_qt_and_krita() -> None:
    hits = [f"{m}:{hit}" for m, p, tree in _sources() for hit in _unknown_imports(tree, m, p)]
    assert hits == []


def test_only_the_adapter_imports_krita_or_qt() -> None:
    hits = [f"{m}:{h}" for m, p, tree in _sources() for h in _misplaced_krita_imports(tree, m, p)]
    assert hits == []


def test_the_adapter_waits_for_krita_before_every_pixel_read() -> None:
    hits = [
        f"{m}:{h}"
        for m, _, tree in _sources()
        if _within(m, ADAPTER)
        for h in _reads_before_waiting(tree)
    ]
    assert hits == []


@pytest.mark.parametrize(
    ("source", "refused"),
    [
        ("def read(doc):\n    return doc.pixelData(0, 0, 1, 1)", True),
        ("def read(doc):\n    data = doc.pixelData(0, 0, 1, 1)\n    doc.waitForDone()", True),
        (
            "def read(doc):\n    doc.waitForDone()\n    return [doc.pixelData(*r) for r in rs]",
            False,
        ),
        ("def name(doc):\n    return doc.name()", False),
        ("def read(node):\n    return node.projectionPixelData(0, 0, 1, 1)", True),
        ("def read(node):\n    return node.pixelDataAtTime(0, 0, 1, 1, 3)", True),
        ("def read(node, doc):\n    doc.waitForDone()\n    return node.pixelDataAtTime()", False),
        ("def write(selection):\n    selection.setPixelData(b'', 0, 0, 0, 0)", False),
    ],
)
def test_a_read_before_the_wait_is_found(source: str, refused: bool) -> None:
    assert bool(_reads_before_waiting(ast.parse(source))) is refused


def test_the_adapter_adds_one_bridge_op() -> None:
    tree = ast.parse((PLUGIN / PACKAGE / "krita_adapter" / "ops.py").read_text(encoding="utf-8"))
    [handlers] = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "HANDLERS"
    ]
    assert isinstance(handlers, ast.Dict)
    names = [key.value for key in handlers.keys if isinstance(key, ast.Constant)]
    assert names == ["bridge.unsaved_documents"]


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
