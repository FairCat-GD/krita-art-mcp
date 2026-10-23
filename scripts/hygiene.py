"""Keeps private terms and AI attribution out of the repository's files and commit messages."""

import hashlib
import re
import subprocess
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TERMS_FILE = Path(__file__).with_name("hygiene_terms.txt")
_RUN = re.compile(r"[a-z0-9]+")
# Assembled from pieces so that this file never holds what it bans.
_ATTRIBUTION = {
    "co-author trailer": re.compile(r"^[ \t]*co" + "-author" + r"ed-by[ \t]*:", re.I | re.M),
    "generated-with line": re.compile(r"gener" + r"ated\s+with", re.I),
    "AI session link": re.compile(
        r"https?://(?:[a-z0-9-]+\.)*(?:clau" + r"de\.ai|chat" + r"gpt\.com)/", re.I
    ),
}


def load_terms(path: Path = TERMS_FILE) -> frozenset[str]:
    lines = (line.strip() for line in path.read_text(encoding="utf-8").splitlines())
    return frozenset(line for line in lines if line and not line.startswith("#"))


def _term_hits(text: str, terms: frozenset[str]) -> Iterator[tuple[int, str]]:
    for number, line in enumerate(text.lower().splitlines(), 1):
        for run in _RUN.findall(line):
            digest = hashlib.sha256(run.encode()).hexdigest()
            if digest in terms:
                yield number, digest


def scan_files(root: Path, paths: Iterable[str], terms: frozenset[str]) -> list[str]:
    problems = []
    for path in paths:
        for _, digest in _term_hits(path, terms):
            problems.append(f"{path}: private term in the path (hash {digest[:12]})")
        file = root / path
        if not file.is_file():
            continue
        data = file.read_bytes()
        if b"\0" in data:
            continue
        for number, digest in _term_hits(data.decode("utf-8", "replace"), terms):
            problems.append(f"{path}:{number}: private term (hash {digest[:12]})")
    return problems


def scan_messages(commits: Iterable[tuple[str, str]], terms: frozenset[str]) -> list[str]:
    problems = []
    for sha, message in commits:
        for kind, pattern in _ATTRIBUTION.items():
            for match in pattern.finditer(message):
                number = message.count("\n", 0, match.start()) + 1
                problems.append(f"commit {sha[:12]}, message line {number}: {kind}")
        for number, digest in _term_hits(message, terms):
            problems.append(
                f"commit {sha[:12]}, message line {number}: private term (hash {digest[:12]})"
            )
    return problems


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=True
    ).stdout


def repository_files(root: Path) -> list[str]:
    # Untracked files count too, so a new file is checked before it is staged.
    listing = _git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    return sorted(set(filter(None, listing.split("\0"))))


def commit_messages(root: Path) -> list[tuple[str, str]]:
    log = _git(root, "log", "--format=%H%x00%B%x1e", "HEAD")
    records = (record.strip("\n") for record in log.split("\x1e"))
    return [(sha, message) for sha, _, message in (r.partition("\0") for r in records if r)]


def check(root: Path, terms: frozenset[str]) -> list[str]:
    return scan_files(root, repository_files(root), terms) + scan_messages(
        commit_messages(root), terms
    )


def main() -> int:
    problems = check(ROOT, load_terms())
    for problem in problems:
        print(problem)
    print(f"hygiene: {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
