"""The gate: six named stages, each failing on its own, then a summary.

Usage: uv run scripts/verify.py [stage ...] [--message DRAFT]
"""

import argparse
import functools
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
Stage = Callable[[], list[list[str]]]


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


def _hygiene(message: Path | None = None) -> list[list[str]]:
    draft = [] if message is None else ["--message", str(message)]
    return [[PYTHON, "scripts/hygiene.py", *draft]]


STAGES: dict[str, Stage] = {
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
    "hygiene": _hygiene,
}


def _call(command: list[str]) -> bool:
    try:
        return subprocess.run(command, cwd=ROOT).returncode == 0
    except OSError as error:
        print(f"verify: cannot run {command[0]}: {error}")
        return False


def _run(name: str, stages: dict[str, Stage]) -> tuple[bool, float]:
    print(f"\n== {name} ==", flush=True)
    start = time.monotonic()
    try:
        commands = stages[name]()
    except SetupError as error:
        print(f"verify: {name} cannot start: {error}")
        return False, time.monotonic() - start
    # Every command runs, even after one fails, so each reports its own errors.
    results = [_call(command) for command in commands]
    return all(results), time.monotonic() - start


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="The gate: six named stages, then a summary.")
    parser.add_argument("stages", nargs="*", metavar="stage")
    parser.add_argument("--message", type=Path, help="the drafted commit message, for hygiene")
    args = parser.parse_args(argv)
    unknown = [name for name in args.stages if name not in STAGES]
    if unknown:
        print(f"verify: unknown stage(s) {', '.join(unknown)}; stages: {', '.join(STAGES)}")
        return 2
    names = args.stages or list(STAGES)
    # A draft given to a run without hygiene would go unchecked.
    if args.message is not None and "hygiene" not in names:
        print("verify: --message is checked by the hygiene stage; name it too")
        return 2
    stages = dict(STAGES)
    if args.message is not None:
        stages["hygiene"] = functools.partial(_hygiene, args.message.resolve())
    results = {name: _run(name, stages) for name in names}
    print("\n== summary ==")
    for name, (passed, seconds) in results.items():
        print(f"{name:<13} {'PASS' if passed else 'FAIL'}  {seconds:6.1f}s")
    failed = [name for name, (passed, _) in results.items() if not passed]
    print(f"verify: {'FAIL (' + ', '.join(failed) + ')' if failed else 'PASS'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
