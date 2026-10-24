import os
import subprocess
import unicodedata
from collections.abc import Callable
from pathlib import Path

import hygiene
import pytest

OWNERS_LIST = hygiene.TERMS_FILE
PROBE = "zqxhygieneprobe"
CYRILLIC = "йоквыщ"
DEVANAGARI = "झिफोरु"
# Assembled from pieces so that this file never holds what the stage bans.
TRAILER = "Co" + "-authored-by: Someone <someone@example.invalid>"
GENERATED = "Gener" + "ated with [Clau" + "de Code](https://example.invalid)"
SESSION_LINK = "https://clau" + "de.ai/code/session_0123"

Terms = Callable[..., frozenset[str]]


@pytest.fixture(autouse=True)
def _never_the_owners_list(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(hygiene, "TERMS_FILE", tmp_path_factory.mktemp("list") / "missing.txt")


@pytest.fixture
def terms(tmp_path_factory: pytest.TempPathFactory) -> Terms:
    # A list of fictional words, kept outside every repository a test scans.
    def load(*words: str) -> frozenset[str]:
        path = tmp_path_factory.mktemp("terms") / "terms.txt"
        path.write_text("".join(f"{word}\n" for word in words), encoding="utf-8")
        return hygiene.load_terms(path)

    return load


def _git(repo: Path, *args: str) -> None:
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    identity = ["-c", "user.name=Test", "-c", "user.email=test@example.invalid"]
    subprocess.run(["git", *identity, *args], cwd=repo, env=env, check=True, capture_output=True)


def test_the_list_is_read_from_outside_the_repository() -> None:
    assert OWNERS_LIST == Path.home() / ".config" / "hygiene" / "terms.txt"
    assert hygiene.ROOT not in OWNERS_LIST.parents


def test_a_missing_list_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(hygiene.TermsError, match="no term list"):
        hygiene.load_terms(tmp_path / "absent.txt")
    assert hygiene.main([]) == 1
    assert f"no term list at {hygiene.TERMS_FILE}" in capsys.readouterr().out


def test_an_empty_list_passes(terms: Terms) -> None:
    assert terms() == frozenset()
    assert terms("", "  ") == frozenset()


def test_a_byte_order_mark_and_comment_lines_are_not_terms(tmp_path: Path) -> None:
    path = tmp_path / "terms.txt"
    path.write_text(f"\ufeff{PROBE}\n# a note on this list\n{CYRILLIC}\n", encoding="utf-8")
    assert hygiene.load_terms(path) == frozenset({PROBE, CYRILLIC})


def test_a_path_under_home_is_shown_with_a_tilde() -> None:
    absent = Path.home() / ".config" / "hygiene-absent-zqx" / "terms.txt"
    with pytest.raises(hygiene.TermsError) as error:
        hygiene.load_terms(absent)
    assert str(error.value).startswith("no term list at ~/.config/hygiene-absent-zqx/terms.txt;")
    assert str(Path.home()) not in str(error.value)


def test_a_line_that_is_not_one_word_fails_without_printing_it(tmp_path: Path) -> None:
    path = tmp_path / "terms.txt"
    path.write_text(f"{PROBE}\n{PROBE}-{PROBE}\n", encoding="utf-8")
    with pytest.raises(hygiene.TermsError) as error:
        hygiene.load_terms(path)
    assert str(error.value) == f"{path}:2: not one word"


def test_a_term_in_a_file_is_reported_by_file_and_line_never_by_name(
    tmp_path: Path, terms: Terms
) -> None:
    (tmp_path / "notes.txt").write_text(f"first line\nsecond line, {PROBE.upper()}!\n")
    (tmp_path / "clean.txt").write_text("nothing to see\n")
    problems = hygiene.scan_files(tmp_path, ["notes.txt", "clean.txt"], terms(PROBE))
    assert problems == ["notes.txt:2: private term"]
    assert PROBE not in "".join(problems).lower()


def test_a_term_joined_to_a_word_or_number_is_reported(tmp_path: Path, terms: Terms) -> None:
    text = f"my{PROBE.capitalize()}Notes\n{PROBE}2026\nmy{CYRILLIC.capitalize()}\n"
    (tmp_path / "joined.txt").write_text(text, encoding="utf-8")
    problems = hygiene.scan_files(tmp_path, ["joined.txt"], terms(PROBE, CYRILLIC))
    assert problems == [f"joined.txt:{n}: private term" for n in (1, 2, 3)]


def test_a_cyrillic_term_is_found_however_it_is_encoded(tmp_path: Path, terms: Terms) -> None:
    decomposed = unicodedata.normalize("NFD", CYRILLIC)
    assert decomposed != CYRILLIC
    text = f"x {decomposed} y\nx {CYRILLIC.upper()} y\n"
    (tmp_path / "notes.txt").write_text(text, encoding="utf-8")
    for term in (CYRILLIC, decomposed):
        problems = hygiene.scan_files(tmp_path, ["notes.txt"], terms(term))
        assert problems == ["notes.txt:1: private term", "notes.txt:2: private term"]


def test_a_word_with_combining_marks_is_one_token(tmp_path: Path, terms: Terms) -> None:
    assert any(unicodedata.category(c).startswith("M") for c in DEVANAGARI)
    (tmp_path / "notes.txt").write_text(f"क {DEVANAGARI} ख\n", encoding="utf-8")
    problems = hygiene.scan_files(tmp_path, ["notes.txt"], terms(DEVANAGARI))
    assert problems == ["notes.txt:1: private term"]


def test_a_term_in_a_path_is_reported(tmp_path: Path, terms: Terms) -> None:
    name = f"{PROBE}-notes.txt"
    (tmp_path / name).write_text("nothing to see\n")
    problems = hygiene.scan_files(tmp_path, [name], terms(PROBE))
    assert problems == [f"{name}: private term in the path"]


def test_binary_files_are_skipped(tmp_path: Path, terms: Terms) -> None:
    (tmp_path / "image.bin").write_bytes(b"\0" + PROBE.encode())
    assert hygiene.scan_files(tmp_path, ["image.bin"], terms(PROBE)) == []


def test_attribution_and_terms_in_commit_messages_are_reported(
    tmp_path: Path, terms: Terms
) -> None:
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "commit", "-q", "--allow-empty", "-m", "feat: clean\n\nA plain body.")
    _git(tmp_path, "commit", "-q", "--allow-empty", "-m", f"fix: one\n\n{TRAILER}")
    _git(tmp_path, "commit", "-q", "--allow-empty", "-m", f"fix: two\n\n{GENERATED}")
    _git(tmp_path, "commit", "-q", "--allow-empty", "-m", f"fix: three\n\nSee {SESSION_LINK}")
    _git(tmp_path, "commit", "-q", "--allow-empty", "-m", f"fix: four\n\nAbout {PROBE}.")
    problems = hygiene.scan_messages(hygiene.commit_messages(tmp_path), terms(PROBE))
    kinds = sorted(problem.split(": ", 1)[1] for problem in problems)
    assert kinds == ["AI session link", "co-author trailer", "generated-with line", "private term"]
    assert all(", message line 3: " in problem for problem in problems)


def test_a_generated_line_counts_only_when_it_names_an_ai_tool() -> None:
    plain = [
        "The tables are " + "gener" + "ated with the codegen script.",
        "Tables re" + "gener" + "ated with\n- AI-free fixtures.",
        "Files " + "gener" + "ated with\n- Codex notes.",
        "The config writ" + "ten by doctor now works with Codex.",
    ]
    for body in plain:
        assert hygiene.scan_draft(f"fix: one\n\n{body}", frozenset()) == []
    credits = [
        GENERATED,
        "Writ" + "ten by Codex.",
        "Gener" + "ated with the help of Claude.",
        "Creat" + "ed using an AI.",
    ]
    for body in credits:
        assert hygiene.scan_draft(f"fix: one\n\n{body}", frozenset()) == [
            "commit message draft, line 3: generated-with line"
        ]


def test_a_term_or_a_trailer_in_the_draft_fails(tmp_path: Path, terms: Terms) -> None:
    listed = terms(PROBE)
    _git(tmp_path, "init", "-q", "-b", "main")
    assert hygiene.check(tmp_path, listed, f"fix: one\n\nAbout {PROBE}.") == [
        "commit message draft, line 3: private term"
    ]
    assert hygiene.check(tmp_path, listed, f"fix: one\n\n{TRAILER}") == [
        "commit message draft, line 3: co-author trailer"
    ]
    assert hygiene.check(tmp_path, listed, "fix: one\n\nA plain body.") == []


def test_main_checks_the_draft(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, listed = tmp_path / "repo", tmp_path / "terms.txt"
    repo.mkdir()
    listed.write_text("")
    _git(repo, "init", "-q", "-b", "main")
    monkeypatch.setattr(hygiene, "ROOT", repo)
    draft = tmp_path / "COMMIT_DRAFT"
    draft.write_text(f"fix: one\n\n{TRAILER}\n")
    assert hygiene.main(["--terms", str(listed), "--message", str(draft)]) == 1
    assert "commit message draft, line 3: co-author trailer" in capsys.readouterr().out
    draft.write_text("fix: one\n\nA plain body.\n")
    assert hygiene.main(["--terms", str(listed), "--message", str(draft)]) == 0


def test_an_unreadable_draft_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "terms.txt").write_text("")
    argv = ["--terms", str(tmp_path / "terms.txt"), "--message", str(tmp_path / "absent")]
    assert hygiene.main(argv) == 1
    assert "cannot read the message draft" in capsys.readouterr().out


def test_a_term_staged_but_gone_from_the_working_tree_is_reported(
    tmp_path: Path, terms: Terms
) -> None:
    _git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "notes.txt").write_text(f"a {PROBE}\n")
    _git(tmp_path, "add", "notes.txt")
    (tmp_path / "notes.txt").write_text("clean again\n")
    assert hygiene.check(tmp_path, terms(PROBE)) == ["notes.txt (staged):1: private term"]


def test_a_clean_repository_passes(tmp_path: Path, terms: Terms) -> None:
    (tmp_path / "README.md").write_text("A fictional project.\n")
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "add", "README.md")
    _git(tmp_path, "commit", "-q", "-m", "docs: a readme\n\nA plain body.")
    (tmp_path / "untracked.txt").write_text(f"{PROBE}\n")
    assert hygiene.check(tmp_path, frozenset()) == []
    assert hygiene.check(tmp_path, terms(PROBE)) == ["untracked.txt:1: private term"]
