import asyncio
import io
import json
import re
import shutil
import stat
from pathlib import Path
from typing import Any, cast

import pytest

from krita_art_mcp import doctor, install, paths, plugin_files, probe, roots
from krita_art_mcp.bridge_client import BeforeSend, BridgeClient, Done, Failed, Outcome
from krita_art_mcp.errors import error_body
from krita_art_mcp.probe import opening
from krita_art_mcp.probe.report import Report
from krita_art_mcp.setup_checks import Setup

REPO_PLUGIN = paths.plugin_source()
ENABLED = "[General]\nx=1\n\n[python]\nenable_krita_art_mcp_bridge=true\n"


@pytest.fixture
def plugin_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    # A copy of the repo's plugin with a bytecode cache planted in it.
    source = tmp_path / "repo-plugin"
    shutil.copytree(REPO_PLUGIN, source, ignore=shutil.ignore_patterns("__pycache__"))
    cache = source / paths.PLUGIN_NAME / "bridge_core" / "__pycache__"
    cache.mkdir()
    (cache / "jobs.cpython-313.pyc").write_bytes(b"\0")
    monkeypatch.setattr(paths, "plugin_source", lambda: source)
    return source


def _krita_dir(tmp_path: Path) -> Path:
    krita = tmp_path / "Krita"
    (krita / "pykrita" / "other_plugin").mkdir(parents=True)
    (krita / "pykrita" / "other_plugin.desktop").write_text("[Desktop Entry]\n")
    stale = krita / "pykrita" / paths.PLUGIN_NAME
    stale.mkdir()
    (stale / "stale.py").write_text("STALE = True\n")
    return krita


def test_install_plugin_replaces_the_plugin_and_leaves_the_rest(
    tmp_path: Path, plugin_source: Path
) -> None:
    krita = _krita_dir(tmp_path)
    out = io.StringIO()
    assert install.run(krita, tmp_path / "kritarc", out) == 0
    installed = krita / "pykrita" / paths.PLUGIN_NAME
    assert plugin_files.source_hash(installed) == plugin_files.source_hash(
        plugin_source / paths.PLUGIN_NAME
    )
    assert not (installed / "stale.py").exists()
    assert [path for path in installed.rglob("*") if "__pycache__" in path.parts] == []
    desktop = plugin_files.desktop_name()
    assert (krita / "pykrita" / desktop).read_bytes() == (plugin_source / desktop).read_bytes()
    assert sorted(path.name for path in (krita / "pykrita").iterdir()) == [
        paths.PLUGIN_NAME,
        desktop,
        "other_plugin",
        "other_plugin.desktop",
    ]
    text = out.getvalue()
    assert "Python Plugin Manager" in text
    assert text.count("Quit Krita and start it again.") == 2


def test_install_plugin_asks_only_for_a_restart_once_enabled(
    tmp_path: Path, plugin_source: Path
) -> None:
    kritarc = tmp_path / "kritarc"
    kritarc.write_text(ENABLED)
    out = io.StringIO()
    assert install.run(_krita_dir(tmp_path), kritarc, out) == 0
    assert "Next: restart Krita so it loads this version." in out.getvalue()
    assert "Python Plugin Manager" not in out.getvalue()


def test_install_plugin_refuses_a_missing_krita_folder(tmp_path: Path) -> None:
    out = io.StringIO()
    assert install.run(tmp_path / "missing", tmp_path / "kritarc", out) == 1
    assert "does not exist" in out.getvalue()


class _Client(BridgeClient):
    def __init__(self, health: Done | Failed, documents: Outcome | None = None) -> None:
        super().__init__()
        self._health = health
        self._documents = documents or Done({"open": 2, "unsaved": 1}, "op-1")

    def health(self) -> Done | Failed:
        return self._health

    def call(
        self,
        op: str,
        args: dict[str, Any] | None = None,
        *,
        request_id: str | None = None,
        before_send: BeforeSend | None = None,
    ) -> Outcome:
        assert op == "bridge.unsaved_documents"
        return self._documents


def _healthy(plugin_hash: str) -> Done:
    return Done({"protocol": 1, "plugin_hash": plugin_hash, "krita_version": "5.3.4"}, None)


def _setup(
    tmp_path: Path, *, installed: bool, enabled: bool, running: bool, rooted: bool = True
) -> Setup:
    krita = tmp_path / "Krita"
    (krita / "pykrita").mkdir(parents=True)
    if installed:
        plugin_files.install(REPO_PLUGIN, krita)
    kritarc = tmp_path / "kritarc"
    kritarc.write_text(ENABLED if enabled else "[python]\nenable_krita_art_mcp_bridge=false\n")
    config = tmp_path / "data" / "config.json"
    if rooted:
        (tmp_path / "art").mkdir()
        roots.save(config, [str(tmp_path / "art")])
    return Setup(
        plugin_source=REPO_PLUGIN,
        krita_data_dir=krita,
        kritarc=kritarc,
        krita_running=lambda: running,
        config_file=config,
    )


REPO_HASH = plugin_files.source_hash(REPO_PLUGIN / paths.PLUGIN_NAME)
UNREACHABLE = Failed(error_body("KRITA_NOT_RUNNING", "no bridge", details={"fix": "Restart."}))
OTHER_PROTOCOL = Failed(
    error_body("PROTOCOL_MISMATCH", details={"bridge_protocol": 2, "server_protocol": 1})
)


@pytest.mark.parametrize(
    ("installed", "enabled", "running", "health", "failing_step"),
    [
        (False, True, True, _healthy(REPO_HASH), 1),
        (True, False, True, _healthy(REPO_HASH), 2),
        (True, True, False, _healthy(REPO_HASH), 3),
        (True, True, True, UNREACHABLE, 4),
        (True, True, True, _healthy("0" * 64), 5),
        (True, True, True, OTHER_PROTOCOL, 5),
    ],
    ids=["not installed", "not enabled", "Krita closed", "no bridge", "stale plugin", "protocol"],
)
def test_doctor_names_the_first_failing_step(
    tmp_path: Path,
    installed: bool,
    enabled: bool,
    running: bool,
    health: Done | Failed,
    failing_step: int,
) -> None:
    out = io.StringIO()
    setup = _setup(tmp_path, installed=installed, enabled=enabled, running=running)
    assert doctor.run(setup, _Client(health), out) == 1
    lines = out.getvalue().splitlines()
    assert [line.split(".")[0] for line in lines if "PASS (" in line] == [
        str(step) for step in range(1, failing_step)
    ]
    assert f"{failing_step}. " in lines[failing_step - 1] and "FAIL" in lines[failing_step - 1]
    assert lines[failing_step].startswith("   Fix: ")
    if failing_step == 5:
        assert "install-plugin" in lines[failing_step]
    assert lines[failing_step + 1] == f"doctor: stopped at step {failing_step} of 6."
    # The restart check is reported whichever step failed.
    assert lines[-1] == "Krita has 2 open document(s), 1 unsaved."


@pytest.mark.parametrize("stale", ["bridge_core/jobs.py", "../krita_art_mcp_bridge.desktop"])
def test_doctor_finds_a_stale_installed_copy(tmp_path: Path, stale: str) -> None:
    setup = _setup(tmp_path, installed=True, enabled=True, running=True)
    installed = setup.krita_data_dir / "pykrita" / paths.PLUGIN_NAME / stale
    installed.write_text(installed.read_text() + "\n# edited by hand\n")
    out = io.StringIO()
    assert doctor.run(setup, _Client(_healthy(REPO_HASH)), out) == 1
    assert out.getvalue().startswith("1. the plugin files are installed and current: FAIL")


def test_doctor_says_nothing_of_documents_when_krita_is_closed(tmp_path: Path) -> None:
    out = io.StringIO()
    setup = _setup(tmp_path, installed=True, enabled=True, running=False)
    assert doctor.run(setup, _Client(UNREACHABLE, UNREACHABLE), out) == 1
    assert out.getvalue().splitlines()[-1] == "doctor: stopped at step 3 of 6."


def test_doctor_passes_and_reports_unsaved_documents(tmp_path: Path) -> None:
    out = io.StringIO()
    setup = _setup(tmp_path, installed=True, enabled=True, running=True)
    assert doctor.run(setup, _Client(_healthy(REPO_HASH)), out) == 0
    text = out.getvalue()
    assert "doctor: all 6 steps pass." in text
    assert "6. at least one root is allowed: PASS (1 root)" in text
    assert "Krita has 2 open document(s), 1 unsaved." in text


@pytest.mark.parametrize(
    ("config", "detail"),
    [
        (None, "no roots, so agents can open nothing"),
        ({"v": 1, "roots": ["/nonexistent-root-for-a-test"]}, "1 of 1 roots are no longer folders"),
        ({"v": 2, "roots": []}, "config.json is version 2"),
        ({"v": 1, "roots": ["/"]}, "1 of 1 roots reach too far"),
    ],
    ids=["no roots", "a root gone", "a newer config", "a root too wide"],
)
def test_doctor_step_6_needs_a_root_that_is_still_a_folder(
    tmp_path: Path, config: dict[str, Any] | None, detail: str
) -> None:
    fixes = {
        "no roots": "roots add",
        "1 of 1 roots": "roots remove",
        "config.json is version 2": "delete it and add the roots again",
        "1 of 1 roots reach": "roots remove",
    }
    setup = _setup(tmp_path, installed=True, enabled=True, running=True, rooted=False)
    if config is not None:
        setup.config_file.parent.mkdir(parents=True)
        setup.config_file.write_text(json.dumps(config))
    out = io.StringIO()
    assert doctor.run(setup, _Client(_healthy(REPO_HASH)), out) == 1
    lines = out.getvalue().splitlines()
    assert lines[5].startswith("6. at least one root is allowed: FAIL (") and detail in lines[5]
    assert lines[6].startswith("   Fix: ") and lines[7] == "doctor: stopped at step 6 of 6."
    # roots add refuses a broken config, so the fix for one is never to run it.
    assert next(fix for key, fix in fixes.items() if key in detail) in lines[6]
    # Counts only: a root names one of the owner's folders.
    assert "nonexistent-root" not in out.getvalue()


def test_the_probe_stops_at_a_stale_plugin_and_sweeps_its_folder(tmp_path: Path) -> None:
    harness = tmp_path / "harness"
    harness.mkdir()
    (harness / "leftover.ora").write_bytes(b"old run")
    seen_at_start: list[list[Path]] = []

    class Watching(_Client):
        def health(self) -> Done | Failed:
            seen_at_start.append(list(harness.iterdir()))
            (harness / "made-by-this-run.ora").write_bytes(b"new")
            return super().health()

    out = io.StringIO()
    status = probe.run(out, Watching(_healthy("0" * 64)), harness, ["/nonexistent", "serve"])
    assert status == 1
    # Leftovers go before the checks start, and this run's files go when it ends.
    assert seen_at_start == [[]]
    lines = out.getvalue().splitlines()
    assert lines[0].startswith("FAIL     the running plugin is the repo's")
    assert re.fullmatch(r"probe: 0 PASS, 1 FAIL, 0 MEASURED in \d+\.\d s", lines[-1])
    assert list(harness.iterdir()) == []
    # Its folder sits in the private data folder and is private itself.
    assert stat.S_IMODE(harness.stat().st_mode) == 0o700


def test_the_probe_fails_when_the_bridge_does_not_answer(tmp_path: Path) -> None:
    out = io.StringIO()
    status = probe.run(out, _Client(UNREACHABLE), tmp_path / "harness", ["/nonexistent"])
    assert status == 1
    assert out.getvalue().startswith("FAIL     the bridge answers its health check: no bridge")


@pytest.mark.parametrize(
    ("answers", "found"),
    [(["BUSY", "done"], None), (["BUSY", "BUSY"], "BUSY"), (["FILE_EXISTS"], "FILE_EXISTS")],
)
def test_the_probe_s_export_retries_one_busy_with_a_fresh_request_id(
    tmp_path: Path, answers: list[str], found: str | None
) -> None:
    sent: list[str | None] = []

    class Exporting(_Client):
        def call(
            self,
            op: str,
            args: dict[str, Any] | None = None,
            *,
            request_id: str | None = None,
            before_send: BeforeSend | None = None,
        ) -> Outcome:
            assert op == "harness.export_kra"
            sent.append(request_id)
            answer = answers[len(sent) - 1]
            if answer == "done":
                return Done({"sha256": "0" * 64}, "op-1")
            return Failed(error_body(answer, "refused", retryable=answer == "BUSY"), "op-1", True)

    outcome = opening._harness_export(Exporting(UNREACHABLE), "doc-1", tmp_path / "probe.kra")
    assert len(sent) == len(answers) and len(set(sent)) == len(sent)
    assert opening._failed_code(outcome) == found


@pytest.mark.parametrize(
    ("documents", "files", "passed"),
    [
        ([], [], True),
        (["krita-art-mcp probe left open"], [], False),
        ([], ["leaked.raw"], False),
        ([], ["there-before.raw"], True),
        ([], ["read-meanwhile.raw"], True),
    ],
    ids=["clean", "a document left", "a file left", "a file from before", "another client's"],
)
def test_the_probe_checks_its_leftovers_before_it_sweeps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    documents: list[str],
    files: list[str],
    passed: bool,
) -> None:
    harness, transfer = tmp_path / "harness", tmp_path / "transfer"
    transfer.mkdir()
    for name in files:
        (transfer / name).write_bytes(b"")

    async def settle() -> None:
        # Another client's server reads its file while the probe pauses.
        (transfer / "read-meanwhile.raw").unlink(missing_ok=True)

    monkeypatch.setattr(probe, "_settle", settle)
    entries = [{"name": name, "mode": "new", "path": None} for name in documents]
    entries.append({"name": "the owner's own", "mode": "read_only", "path": "/art/hero.kra"})

    async def listed(mcp: Any, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        assert name == "krita_document_list"
        return {"data": {"documents": entries}}

    monkeypatch.setattr(probe, "tool", listed)
    out = io.StringIO()
    report = Report(out)
    before = {"there-before.raw"}
    asyncio.run(probe._no_leftovers(report, cast(Any, None), harness, before))
    assert (report.passed, report.failed) == (int(passed), int(not passed))
    count = len(files) if not passed else 0
    assert f"{len(documents)} document(s) open, {count} transfer file(s)" in out.getvalue()
