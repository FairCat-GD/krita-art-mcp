import hashlib
import os
import re
import subprocess
from pathlib import Path

import hygiene

PROBE = "zqxhygieneprobe"
PROBE_HASH = hashlib.sha256(PROBE.encode()).hexdigest()
TERMS = frozenset({PROBE_HASH})
# Assembled from pieces so that this file never holds what the stage bans.
TRAILER = "Co" + "-authored-by: Someone <someone@example.invalid>"
GENERATED = "Gener" + "ated with some tool"
SESSION_LINK = "https://clau" + "de.ai/code/session_0123"


def _git(repo: Path, *args: str) -> None:
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    identity = ["-c", "user.name=Test", "-c", "user.email=test@example.invalid"]
    subprocess.run(["git", *identity, *args], cwd=repo, env=env, check=True, capture_output=True)


def test_the_terms_file_holds_at_least_the_seven_hashes() -> None:
    terms = hygiene.load_terms()
    assert len(terms) >= 7
    assert all(re.fullmatch(r"[0-9a-f]{64}", term) for term in terms)


def test_a_term_in_a_file_is_reported_by_file_and_line_never_by_name(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text(f"first line\nsecond line, {PROBE.upper()}!\n")
    (tmp_path / "clean.txt").write_text("nothing to see\n")
    problems = hygiene.scan_files(tmp_path, ["notes.txt", "clean.txt"], TERMS)
    assert problems == [f"notes.txt:2: private term (hash {PROBE_HASH[:12]})"]
    assert PROBE not in "".join(problems)


def test_a_term_in_a_path_is_reported(tmp_path: Path) -> None:
    name = f"{PROBE}-notes.txt"
    (tmp_path / name).write_text("nothing to see\n")
    problems = hygiene.scan_files(tmp_path, [name], TERMS)
    assert problems == [f"{name}: private term in the path (hash {PROBE_HASH[:12]})"]


def test_binary_files_are_skipped(tmp_path: Path) -> None:
    (tmp_path / "image.bin").write_bytes(b"\0" + PROBE.encode())
    assert hygiene.scan_files(tmp_path, ["image.bin"], TERMS) == []


def test_attribution_in_commit_messages_is_reported(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "commit", "-q", "--allow-empty", "-m", "feat: clean\n\nA plain body.")
    _git(tmp_path, "commit", "-q", "--allow-empty", "-m", f"fix: one\n\n{TRAILER}")
    _git(tmp_path, "commit", "-q", "--allow-empty", "-m", f"fix: two\n\n{GENERATED}")
    _git(tmp_path, "commit", "-q", "--allow-empty", "-m", f"fix: three\n\nSee {SESSION_LINK}")
    _git(tmp_path, "commit", "-q", "--allow-empty", "-m", f"fix: four\n\nAbout {PROBE}.")
    problems = hygiene.scan_messages(hygiene.commit_messages(tmp_path), TERMS)
    kinds = sorted(problem.split(": ", 1)[1] for problem in problems)
    assert kinds == [
        "AI session link",
        "co-author trailer",
        "generated-with line",
        f"private term (hash {PROBE_HASH[:12]})",
    ]
    assert all(", message line 3: " in problem for problem in problems)


def test_a_clean_repository_passes(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("A fictional project.\n")
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "add", "README.md")
    _git(tmp_path, "commit", "-q", "-m", "docs: a readme\n\nA plain body.")
    (tmp_path / "untracked.txt").write_text(f"{PROBE}\n")
    assert hygiene.check(tmp_path, frozenset()) == []
    assert hygiene.check(tmp_path, TERMS) == [
        f"untracked.txt:1: private term (hash {PROBE_HASH[:12]})"
    ]
