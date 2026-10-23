"""The gate: six named stages, each failing on its own, then a summary.

Usage: uv run scripts/verify.py [stage ...]
"""

import os
import shutil
import subprocess
import sys
import time
import tomllib
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable
PLUGIN_PACKAGES = ["-p", "krita_art_mcp_bridge"]


class SetupError(Exception):
    pass


def _uv() -> str:
    uv = os.environ.get("UV") or shutil.which("uv")
    if uv is None:
        raise SetupError("uv not found: set UV or put uv on PATH")
    return uv


def _locked_version(package: str) -> str:
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    versions = [str(p["version"]) for p in lock["package"] if p["name"] == package]
    if not versions:
        raise SetupError(f"{package} is not in uv.lock")
    return versions[0]


def _plugin_tests() -> list[list[str]]:
    # Plugin core runs on 3.10 with pytest as its only package, at the lockfile's pytest version.
    pytest = f"pytest=={_locked_version('pytest')}"
    isolated = ["run", "--isolated", "--no-project", "--python", "3.10", "--with", pytest]
    return [[_uv(), *isolated, "python", "-m", "pytest", "tests/plugin", "-p", "no:cacheprovider"]]


STAGES: dict[str, Callable[[], list[list[str]]]] = {
    "format": lambda: [[PYTHON, "-m", "ruff", "format", "--check", "."]],
    "lint": lambda: [[PYTHON, "-m", "ruff", "check", "."]],
    "types": lambda: [
        [PYTHON, "-m", "mypy", "src", "scripts", "tests", "--exclude", "^tests/plugin/"],
        # mypy takes packages or files in one run, never both.
        [PYTHON, "-m", "mypy", "--python-version", "3.10", *PLUGIN_PACKAGES],
        [PYTHON, "-m", "mypy", "--python-version", "3.10", "tests/plugin"],
    ],
    "tests": lambda: [[PYTHON, "-m", "pytest", "tests", "--ignore=tests/plugin"]],
    "plugin-tests": _plugin_tests,
    "hygiene": lambda: [[PYTHON, "scripts/hygiene.py"]],
}


def _call(command: list[str]) -> bool:
    try:
        return subprocess.run(command, cwd=ROOT).returncode == 0
    except OSError as error:
        print(f"verify: cannot run {command[0]}: {error}")
        return False


def _run(name: str) -> tuple[bool, float]:
    print(f"\n== {name} ==", flush=True)
    start = time.monotonic()
    try:
        commands = STAGES[name]()
    except SetupError as error:
        print(f"verify: {name} cannot start: {error}")
        return False, time.monotonic() - start
    # Every command runs, even after one fails, so each reports its own errors.
    results = [_call(command) for command in commands]
    return all(results), time.monotonic() - start


def main(argv: list[str]) -> int:
    unknown = [name for name in argv if name not in STAGES]
    if unknown:
        print(f"verify: unknown stage(s) {', '.join(unknown)}; stages: {', '.join(STAGES)}")
        return 2
    results = {name: _run(name) for name in argv or STAGES}
    print("\n== summary ==")
    for name, (passed, seconds) in results.items():
        print(f"{name:<13} {'PASS' if passed else 'FAIL'}  {seconds:6.1f}s")
    failed = [name for name, (passed, _) in results.items() if not passed]
    print(f"verify: {'FAIL (' + ', '.join(failed) + ')' if failed else 'PASS'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
