"""Keeps private terms and AI attribution out of the repository's files and commit messages."""

import argparse
import re
import subprocess
import sys
import unicodedata
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Outside every repository: a hash of a short word is reversed by hashing a dictionary of names.
TERMS_FILE = Path.home() / ".config" / "hygiene" / "terms.txt"


def _mark_ranges() -> str:
    ranges: list[list[int]] = []
    for code in range(sys.maxunicode + 1):
        if unicodedata.category(chr(code))[0] != "M":
            continue
        if ranges and ranges[-1][1] == code - 1:
            ranges[-1][1] = code
        else:
            ranges.append([code, code])
    return "".join(f"{re.escape(chr(first))}-{re.escape(chr(last))}" for first, last in ranges)


# Combining marks join a run, so a word in a script with vowel signs stays one token.
_RUN = re.compile(f"(?:[^\\W_]|[{_mark_ranges()}])+")
# Camel-case words and digit groups inside a run, so a term joined to another word is still seen.
_SUBTOKEN = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+")
_GITLINK = "160000"
# A "generated" line counts only when it names an AI tool, so a codegen script's note passes.
_TOOLS = r"(?:claude|chatgpt|gpt|openai|codex|copilot|gemini|cursor|ai)\b"
# Assembled from pieces so that this file never holds what it bans.
_ATTRIBUTION = {
    "co-author trailer": re.compile(r"^[ \t]*co" + "-author" + r"ed-by[ \t]*:", re.I | re.M),
    "generated-with line": re.compile(
        r"gener" + r"ated\s+(?:with|by|using)\s+\W*(?:an?\s+)?" + _TOOLS, re.I
    ),
    "AI session link": re.compile(
        r"https?://(?:[a-z0-9-]+\.)*(?:clau" + r"de\.ai|chat" + r"gpt\.com)/", re.I
    ),
}


class TermsError(Exception):
    pass


def _fold(text: str) -> str:
    return unicodedata.normalize("NFC", unicodedata.normalize("NFC", text).lower())


def load_terms(path: Path) -> frozenset[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise TermsError(
            f"no term list at {path}; create it, empty if nothing is private"
        ) from None
    terms = set()
    for number, line in enumerate(text.splitlines(), 1):
        word = _fold(line.strip())
        if not word:
            continue
        # A line that is not one token could never match, so it fails instead of passing silently.
        if not _RUN.fullmatch(word):
            raise TermsError(f"{path}:{number}: not one word")
        terms.add(word)
    return frozenset(terms)


def _shape(run: str) -> str:
    # Each letter's case in ASCII, so _SUBTOKEN splits camel case in any script.
    return "".join("A" if c.isupper() else "0" if c.isdecimal() else "a" for c in run)


def _tokens(line: str) -> set[str]:
    tokens = set()
    for run in _RUN.findall(unicodedata.normalize("NFC", line)):
        tokens.add(_fold(run))
        shape = run if run.isascii() else _shape(run)
        tokens.update(_fold(run[m.start() : m.end()]) for m in _SUBTOKEN.finditer(shape))
    return tokens


def _term_lines(text: str, terms: frozenset[str]) -> Iterator[int]:
    for number, line in enumerate(text.splitlines(), 1):
        if not terms.isdisjoint(_tokens(line)):
            yield number


def scan_files(root: Path, paths: Iterable[str], terms: frozenset[str]) -> list[str]:
    problems = []
    for path in paths:
        if any(_term_lines(path, terms)):
            problems.append(f"{path}: private term in the path")
        file = root / path
        if not file.is_file():
            continue
        data = file.read_bytes()
        if b"\0" in data:
            continue
        for number in _term_lines(data.decode("utf-8", "replace"), terms):
            problems.append(f"{path}:{number}: private term")
    return problems


def scan_staged(root: Path, staged: Mapping[str, bytes], terms: frozenset[str]) -> list[str]:
    problems = []
    for path, data in staged.items():
        file = root / path
        if b"\0" in data or (file.is_file() and file.read_bytes() == data):
            continue
        for number in _term_lines(data.decode("utf-8", "replace"), terms):
            problems.append(f"{path} (staged):{number}: private term")
    return problems


def _message_hits(message: str, terms: frozenset[str]) -> list[tuple[int, str]]:
    hits = []
    for kind, pattern in _ATTRIBUTION.items():
        for match in pattern.finditer(message):
            hits.append((message.count("\n", 0, match.start()) + 1, kind))
    hits.extend((number, "private term") for number in _term_lines(message, terms))
    return hits


def scan_messages(commits: Iterable[tuple[str, str]], terms: frozenset[str]) -> list[str]:
    return [
        f"commit {sha[:12]}, message line {number}: {kind}"
        for sha, message in commits
        for number, kind in _message_hits(message, terms)
    ]


def scan_draft(message: str, terms: frozenset[str]) -> list[str]:
    return [
        f"commit message draft, line {number}: {kind}"
        for number, kind in _message_hits(message, terms)
    ]


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=True
    ).stdout


def repository_files(root: Path) -> list[str]:
    # Untracked files count too, so a new file is checked before it is staged.
    listing = _git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    return sorted(set(filter(None, listing.split("\0"))))


def staged_contents(root: Path) -> dict[str, bytes]:
    # The index is what a commit records, and it can differ from the working tree.
    entries = {}
    listing = _git(root, "ls-files", "-z", "--stage")
    for entry in filter(None, listing.split("\0")):
        info, _, path = entry.partition("\t")
        mode, sha, _ = info.split(" ")
        if mode != _GITLINK:
            entries[path] = sha
    batch = subprocess.run(
        ["git", "cat-file", "--batch"],
        cwd=root,
        input="".join(f"{sha}\n" for sha in entries.values()).encode(),
        capture_output=True,
        check=True,
    ).stdout
    contents, offset = {}, 0
    for path in entries:
        header_end = batch.index(b"\n", offset)
        size = int(batch[offset:header_end].split()[2])
        contents[path] = batch[header_end + 1 : header_end + 1 + size]
        offset = header_end + 1 + size + 1
    return contents


def commit_messages(root: Path) -> list[tuple[str, str]]:
    has_commits = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", "HEAD"], cwd=root, capture_output=True
    )
    if has_commits.returncode != 0:
        return []
    log = _git(root, "log", "--format=%H%x00%B%x1e", "HEAD")
    records = (record.strip("\n") for record in log.split("\x1e"))
    return [(sha, message) for sha, _, message in (r.partition("\0") for r in records if r)]


def check(root: Path, terms: frozenset[str], draft: str | None = None) -> list[str]:
    problems = (
        scan_files(root, repository_files(root), terms)
        + scan_staged(root, staged_contents(root), terms)
        + scan_messages(commit_messages(root), terms)
    )
    return problems if draft is None else problems + scan_draft(draft, terms)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--terms", type=Path, help="the term list (default: ~/.config/hygiene/terms.txt)"
    )
    parser.add_argument("--message", type=Path, help="a drafted commit message to check too")
    args = parser.parse_args(argv)
    try:
        terms = load_terms(args.terms or TERMS_FILE)
    except (TermsError, OSError, UnicodeDecodeError) as error:
        print(f"hygiene: {error}")
        return 1
    try:
        draft = None if args.message is None else args.message.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        print(f"hygiene: cannot read the message draft: {error}")
        return 1
    problems = check(ROOT, terms, draft)
    for problem in problems:
        print(problem)
    print(f"hygiene: {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
