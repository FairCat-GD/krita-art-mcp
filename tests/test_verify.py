import shutil
import sys
from pathlib import Path

import pytest
import verify


def test_every_command_in_a_stage_runs_after_one_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = tmp_path / "ran"
    commands = [
        [sys.executable, "-c", "raise SystemExit(1)"],
        [sys.executable, "-c", f"open({str(marker)!r}, 'w').close()"],
    ]
    monkeypatch.setitem(verify.STAGES, "probe", lambda: commands)
    passed, _ = verify._run("probe", verify.STAGES)
    assert passed is False
    assert marker.exists()


def test_plugin_tests_cannot_start_without_uv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("UV", raising=False)
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(verify.SetupError):
        verify._plugin_tests()


def test_a_stage_that_cannot_start_fails_alone(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def cannot_start() -> list[list[str]]:
        raise verify.SetupError("uv not found")

    monkeypatch.setitem(verify.STAGES, "broken", cannot_start)
    monkeypatch.setitem(verify.STAGES, "fine", lambda: [[sys.executable, "-c", "pass"]])
    assert verify.main(["broken", "fine"]) == 1
    summary = capsys.readouterr().out.split("== summary ==")[1].splitlines()
    assert [line.split()[:2] for line in summary if line.split()[:1] in (["broken"], ["fine"])] == [
        ["broken", "FAIL"],
        ["fine", "PASS"],
    ]


def _record_calls(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    calls: list[list[str]] = []

    def call(command: list[str]) -> bool:
        calls.append(command)
        return True

    monkeypatch.setattr(verify, "_call", call)
    return calls


def test_the_draft_reaches_the_hygiene_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _record_calls(monkeypatch)
    draft = tmp_path / "COMMIT_DRAFT"
    assert verify.main(["hygiene"]) == 0
    assert verify.main(["hygiene", "--message", str(draft)]) == 0
    assert calls == [
        [verify.PYTHON, "scripts/hygiene.py"],
        [verify.PYTHON, "scripts/hygiene.py", "--message", str(draft.resolve())],
    ]


def test_a_draft_without_the_hygiene_stage_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _record_calls(monkeypatch)
    assert verify.main(["tests", "--message", str(tmp_path / "COMMIT_DRAFT")]) == 2
    assert calls == []
