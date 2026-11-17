import asyncio
import dataclasses
import errno
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import pytest

from krita_art_mcp import doctor, install, paths, plugin_files, probe, roots, setup_checks
from krita_art_mcp.bridge_client import BeforeSend, BridgeClient, Done, Failed, Outcome
from krita_art_mcp.errors import PROTOCOL, error_body
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


def _tree(folder: Path) -> dict[str, bytes | None]:
    return {
        path.relative_to(folder).as_posix(): path.read_bytes() if path.is_file() else None
        for path in sorted(folder.rglob("*"))
    }


def test_install_plugin_copies_nothing_from_a_source_without_its_desktop(
    tmp_path: Path, plugin_source: Path
) -> None:
    (plugin_source / plugin_files.desktop_name()).unlink()
    krita = _krita_dir(tmp_path)
    before = _tree(krita)
    out = io.StringIO()
    assert install.run(krita, tmp_path / "kritarc", out) == 1
    assert _tree(krita) == before
    assert out.getvalue() == (
        "install-plugin: no plugin source beside this copy of the server "
        f"({plugin_source} has no krita_art_mcp_bridge.desktop). {setup_checks.CHECKOUT}\n"
    )


def test_a_failed_install_leaves_the_old_plugin_whole(tmp_path: Path, plugin_source: Path) -> None:
    krita = tmp_path / "Krita"
    (krita / "pykrita").mkdir(parents=True)
    plugin_files.install(REPO_PLUGIN, krita)
    old = _tree(krita / "pykrita")
    (plugin_source / paths.PLUGIN_NAME / "bridge_core" / "jobs.py").write_text("NEW = True\n")
    (plugin_source / plugin_files.desktop_name()).unlink()
    with pytest.raises(FileNotFoundError):
        plugin_files.install(plugin_source, krita)
    assert _tree(krita / "pykrita") == old


def test_install_plugin_refuses_a_copy_that_differs_from_its_source(
    tmp_path: Path, plugin_source: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    copy = plugin_files.install

    def altered(source: Path, krita_data_dir: Path) -> Path:
        target = copy(source, krita_data_dir)
        (target / "added_in_transit.py").write_text("ADDED = True\n")
        return target

    monkeypatch.setattr(plugin_files, "install", altered)
    out = io.StringIO()
    assert install.run(_krita_dir(tmp_path), tmp_path / "kritarc", out) == 1
    assert "differs from the source" in out.getvalue() and "Installed" not in out.getvalue()


class _Client(BridgeClient):
    def __init__(self, health: Done | Failed, documents: Outcome | None = None) -> None:
        super().__init__()
        self._health = health
        self._documents = documents or Done({"open": 2, "unsaved": 1}, "op-1")

    def health(self, timeout_s: float = 5.0) -> Done | Failed:
        return self._health

    def call(
        self,
        op: str,
        args: dict[str, Any] | None = None,
        *,
        request_id: str | None = None,
        before_send: BeforeSend | None = None,
        budget_s: float | None = None,
        operation_id: str | None = None,
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
OTHER_PROTOCOL = Done({"protocol": 2, "plugin_hash": REPO_HASH, "krita_version": "5.3.4"}, None)


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


STEP_1_CASES = [
    "nothing installed",
    "no source",
    "no .desktop",
    "no package",
    "source is a file",
    "a module that cannot be found",
    "installed .desktop differs",
    "hash differs",
    "exact match",
]


def _source_copy(tmp_path: Path) -> Path:
    source = tmp_path / "checkout" / "plugin"
    shutil.copytree(REPO_PLUGIN, source, ignore=shutil.ignore_patterns("__pycache__"))
    return source


@pytest.mark.parametrize(
    ("case", "detail", "fix"),
    [
        ("nothing installed", "nothing is installed in {krita}/pykrita", "install-plugin"),
        (
            "no source",
            "no plugin source beside this copy of the server ({source} does not exist)",
            "checkout",
        ),
        (
            "no .desktop",
            "no plugin source beside this copy of the server "
            "({source} has no krita_art_mcp_bridge.desktop)",
            "checkout",
        ),
        (
            "no package",
            "no plugin source beside this copy of the server "
            "({source} has no krita_art_mcp_bridge/__init__.py)",
            "checkout",
        ),
        (
            "source is a file",
            "no plugin source beside this copy of the server ({source} is not a folder)",
            "checkout",
        ),
        (
            "a module that cannot be found",
            "the plugin source in {source} is incomplete: "
            "{source}/krita_art_mcp_bridge/dangling.py is missing",
            "checkout",
        ),
        (
            "installed .desktop differs",
            "the installed .desktop file differs from the repo's",
            "install-plugin",
        ),
        ("hash differs", "installed {installed}, repo {repo}", "install-plugin"),
        ("exact match", "hash {repo}", ""),
    ],
    ids=STEP_1_CASES,
)
def test_step_1_tells_its_failures_apart(tmp_path: Path, case: str, detail: str, fix: str) -> None:
    setup = _setup(tmp_path, installed=case != "nothing installed", enabled=True, running=True)
    source = _source_copy(tmp_path)
    setup = dataclasses.replace(setup, plugin_source=source)
    target = plugin_files.installed(setup.krita_data_dir)
    if case == "no source":
        shutil.rmtree(source)
    elif case == "no .desktop":
        (source / plugin_files.desktop_name()).unlink()
    elif case == "no package":
        shutil.rmtree(source / paths.PLUGIN_NAME)
    elif case == "source is a file":
        shutil.rmtree(source)
        source.write_text("not a plugin\n")
    elif case == "a module that cannot be found":
        (source / paths.PLUGIN_NAME / "dangling.py").symlink_to(tmp_path / "nowhere.py")
    elif case == "installed .desktop differs":
        desktop = target.parent / plugin_files.desktop_name()
        desktop.write_bytes(desktop.read_bytes() + b"\n")
    elif case == "hash differs":
        (target / "bridge_core" / "jobs.py").write_text("EDITED = True\n")
    out = io.StringIO()
    status = doctor.run(setup, _Client(_healthy(REPO_HASH)), out)
    lines = out.getvalue().splitlines()
    expected = detail.format(
        krita=setup.krita_data_dir,
        source=source,
        repo=REPO_HASH[:12],
        installed=plugin_files.source_hash(target)[:12] if target.is_dir() else "",
    )
    outcome = "PASS" if not fix else "FAIL"
    assert lines[0] == f"1. the plugin files are installed and current: {outcome} ({expected})"
    if not fix:
        assert status == 0
        return
    assert status == 1 and lines[2] == "doctor: stopped at step 1 of 6."
    # A source problem is never cured by install-plugin, which would have nothing to copy.
    assert lines[1].startswith("   Fix: ") and fix in lines[1]
    assert ("install-plugin" in lines[1]) == (fix == "install-plugin")


@pytest.mark.parametrize(
    "locked",
    ["the source's .desktop", "a source folder", "the installed .desktop"],
)
def test_step_1_names_a_plugin_it_cannot_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, locked: str
) -> None:
    setup = _setup(tmp_path, installed=True, enabled=True, running=True)
    source = _source_copy(tmp_path)
    setup = dataclasses.replace(setup, plugin_source=source)
    pykrita = setup.krita_data_dir / "pykrita"
    path, detail, fix = {
        "the source's .desktop": (
            source / plugin_files.desktop_name(),
            f"cannot read the plugin source in {source}",
            setup_checks.CHECKOUT,
        ),
        "a source folder": (
            source / paths.PLUGIN_NAME / "bridge_core",
            f"cannot read the plugin source in {source}",
            setup_checks.CHECKOUT,
        ),
        "the installed .desktop": (
            pykrita / plugin_files.desktop_name(),
            f"cannot read the installed plugin in {pykrita}",
            setup_checks.INSTALL,
        ),
    }[locked]
    mode = path.stat().st_mode
    path.chmod(0)
    try:
        if os.access(path, os.R_OK):
            pytest.skip("this platform lets the owner read what has no permissions")
        out = io.StringIO()
        assert doctor.run(setup, _Client(_healthy(REPO_HASH)), out) == 1
        lines = out.getvalue().splitlines()
        assert lines[0] == (
            "1. the plugin files are installed and current: FAIL "
            f"({detail}: {os.strerror(errno.EACCES)})"
        )
        assert lines[1] == f"   Fix: {fix}"
        if locked == "a source folder":
            # The hash alone would skip the folder and pass a source the copy then fails on.
            krita = _krita_dir(tmp_path / "other")
            before = _tree(krita)
            monkeypatch.setattr(paths, "plugin_source", lambda: source)
            assert install.run(krita, tmp_path / "kritarc", io.StringIO()) == 1
            assert _tree(krita) == before
    finally:
        path.chmod(stat.S_IMODE(mode))


def test_a_missing_plugin_source_never_matches_the_running_plugin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = tmp_path / "plugin"
    # A missing folder hashes as the empty digest, which a bare compare would pass.
    empty = plugin_files.source_hash(missing / paths.PLUGIN_NAME)
    step = setup_checks.plugin_current({"protocol": PROTOCOL, "plugin_hash": empty}, missing)
    detail = f"no plugin source beside this copy of the server ({missing} does not exist)"
    assert (step.passed, step.detail, step.fix) == (False, detail, setup_checks.CHECKOUT)
    monkeypatch.setattr(paths, "plugin_source", lambda: missing)
    out = io.StringIO()
    healthy = Done({"protocol": PROTOCOL, "plugin_hash": empty, "krita_version": "5.3.4"}, None)
    assert probe.run(out, _Client(healthy), tmp_path / "harness", ["/nonexistent"]) == 1
    lines = out.getvalue().splitlines()
    assert lines[0].startswith("FAIL     the running plugin is the repo's") and detail in lines[0]
    assert lines[1] == f"Stopped: {setup_checks.CHECKOUT}"


PACKAGE = Path(__file__).resolve().parents[1] / "src" / "krita_art_mcp"


@pytest.mark.parametrize(
    "command", [["install-plugin", "--krita-data-dir", "{krita}"], ["doctor"]], ids=lambda c: c[0]
)
def test_a_copy_with_no_plugin_beside_it_exits_1_without_a_traceback(
    tmp_path: Path, command: list[str]
) -> None:
    # An installed wheel has the server's package alone; its plugin source would sit here.
    site = tmp_path / "env" / "site"
    shutil.copytree(PACKAGE, site / "krita_art_mcp", ignore=shutil.ignore_patterns("__pycache__"))
    home, krita = tmp_path / "home", tmp_path / "krita"
    home.mkdir()
    krita.mkdir()
    env = {
        **os.environ,
        "PYTHONPATH": str(site),
        "HOME": str(home),
        "KRITA_ART_MCP_DATA_DIR": str(tmp_path / "data"),
    }
    main = "import sys; from krita_art_mcp.cli import main; sys.exit(main(sys.argv[1:]))"
    arguments = [argument.format(krita=krita) for argument in command]
    result = subprocess.run(
        [sys.executable, "-c", main, *arguments],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 1
    assert "Traceback" not in result.stdout + result.stderr
    # The copy, not this checkout, was imported: only it has no source beside it.
    source = (tmp_path / "env" / "plugin").resolve()
    assert f"no plugin source beside this copy of the server ({source} does not exist)" in (
        result.stdout
    )
    assert setup_checks.CHECKOUT in result.stdout
    assert list(krita.iterdir()) == []


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
        def health(self, timeout_s: float = 5.0) -> Done | Failed:
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


def test_doctor_and_the_probe_reach_a_stale_plugin_to_judge_it_by_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    made: list[dict[str, Any]] = []

    class Recording(_Client):
        def __init__(self, **options: Any) -> None:
            made.append(options)
            super().__init__(UNREACHABLE)

    monkeypatch.setattr(doctor, "BridgeClient", Recording)
    monkeypatch.setattr(probe, "BridgeClient", Recording)
    setup = _setup(tmp_path, installed=True, enabled=True, running=True)
    doctor.run(setup, out=io.StringIO())
    probe.run(io.StringIO(), harness=tmp_path / "harness", serve=["/nonexistent"])
    assert [options.get("any_plugin") for options in made] == [True, True]


def test_the_probe_closes_its_leftovers_before_it_counts_unsaved_documents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    order: list[str] = []

    async def nothing(*args: Any) -> None:
        pass

    async def leftovers(*args: Any) -> None:
        order.append("leftovers")

    def unsaved(*args: Any) -> bool:
        order.append("unsaved")
        return False

    monkeypatch.setattr(probe, "_over_stdio", nothing)
    monkeypatch.setattr(probe, "_close_leftovers", leftovers)
    monkeypatch.setattr(probe, "_no_unsaved_documents", unsaved)
    probe._probe(Report(io.StringIO()), _Client(_healthy(REPO_HASH)), ["/nonexistent"], tmp_path)
    assert order == ["leftovers", "unsaved"]


@pytest.mark.parametrize(
    ("unsaved", "flags", "closable"),
    [
        (2, [(True, True), (True, True)], True),
        (0, [(False, False)], True),
        (1, [(False, True)], True),
        (2, [(True, True)], False),
        (1, [(True, False)], False),
    ],
    ids=[
        "only ours",
        "none",
        "ours after a verified save",
        "one of the owner's too",
        "the owner's beside a clean one",
    ],
)
def test_leftovers_close_only_when_every_unsaved_document_is_the_probes(
    unsaved: int, flags: list[tuple[bool, bool]], closable: bool
) -> None:
    # Krita's unsaved count reads its own flag, which a verified save leaves set.
    client = _Client(_healthy(REPO_HASH), Done({"open": 3, "unsaved": unsaved}, "op-1"))
    own = [{"dirty": dirty, "krita_modified": held} for dirty, held in flags]
    assert probe._only_ours_unsaved(client, own) is closable


def test_leftovers_stay_when_the_unsaved_count_cannot_be_read() -> None:
    assert probe._only_ours_unsaved(_Client(_healthy(REPO_HASH), UNREACHABLE), []) is False


def test_the_probe_prints_the_open_documents_it_read_beside_its_time() -> None:
    out = io.StringIO()
    report = Report(out)
    documents = Done({"open": 87, "unsaved": 0}, "op-1")
    assert probe._no_unsaved_documents(report, _Client(_healthy(REPO_HASH), documents))
    report.summary(95.6)
    assert out.getvalue().splitlines()[-1] == (
        "probe: 1 PASS, 0 FAIL, 0 MEASURED in 95.6 s, with 87 document(s) open"
    )


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
            budget_s: float | None = None,
            operation_id: str | None = None,
        ) -> Outcome:
            assert op == "harness.export_kra"
            sent.append(request_id)
            answer = answers[len(sent) - 1]
            if answer == "done":
                return Done({"sha256": "0" * 64}, "op-1")
            return Failed(error_body(answer, "refused", retryable=answer == "BUSY"), "op-1", True)

    outcome = opening.harness_export(Exporting(UNREACHABLE), "doc-1", tmp_path / "probe.kra")
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
