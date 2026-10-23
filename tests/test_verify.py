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
    passed, _ = verify._run("probe")
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
