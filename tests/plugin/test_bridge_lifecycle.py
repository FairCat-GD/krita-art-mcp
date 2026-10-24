import json
import logging
import logging.handlers
import os
import stat
import threading
from pathlib import Path
from typing import Any

import pytest
from bridge_core import bridge_file, log
from bridge_core.bridge import Bridge
from bridge_core.server import BridgeHTTPServer

PLUGIN_PACKAGE = Path(__file__).resolve().parents[2] / "plugin" / "krita_art_mcp_bridge"
FACTS = {"krita_version": "5.3.4", "qt_major": 5}


def _bridge(data_dir: Path, is_live: bool = False, logger: logging.Logger | None = None) -> Bridge:
    return Bridge(
        data_dir=data_dir,
        package_dir=PLUGIN_PACKAGE,
        facts=FACTS,
        handlers={},
        wake=lambda: None,
        on_main_thread=lambda: True,
        is_live_krita=lambda pid: is_live,
        log=logger or logging.getLogger("test_bridge_lifecycle"),
    )


def test_bridge_json_is_private_and_names_a_serving_bridge(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    bridge = _bridge(data_dir)
    assert bridge.start()
    try:
        assert stat.S_IMODE(data_dir.stat().st_mode) == 0o700
        path = data_dir / "bridge.json"
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        written = json.loads(path.read_text())
        assert set(written) == {
            "port",
            "token",
            "pid",
            "session_id",
            "protocol",
            "plugin_version",
            "plugin_hash",
            "krita_version",
            "qt_major",
        }
        assert written["pid"] == os.getpid()
        assert len(bytes.fromhex(written["token"])) == 32
    finally:
        bridge.stop()
    assert not (data_dir / "bridge.json").exists()


def test_the_data_folder_is_private_even_when_the_log_created_it(tmp_path: Path) -> None:
    # Krita's order: the log first, which creates the data folder as its parent.
    data_dir = tmp_path / "data"
    logger = log.setup(data_dir / "logs")
    bridge = _bridge(data_dir, logger=logger)
    assert bridge.start()
    try:
        assert stat.S_IMODE(data_dir.stat().st_mode) == 0o700
        assert stat.S_IMODE((data_dir / "logs").stat().st_mode) == 0o700
    finally:
        bridge.stop()


def test_bridge_json_is_replaced_atomically_from_a_private_temp_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    replaced: list[tuple[Path, Path, int]] = []
    real_replace = os.replace

    def spy(source: Any, target: Any) -> None:
        replaced.append((Path(source), Path(target), stat.S_IMODE(os.stat(source).st_mode)))
        real_replace(source, target)

    monkeypatch.setattr(os, "replace", spy)
    target = tmp_path / "bridge.json"
    target.write_text("{}")
    bridge_file.write(target, {"pid": 1})
    [(source, destination, mode)] = replaced
    assert source.parent == destination.parent == tmp_path
    assert source != destination
    assert destination == target
    assert mode == 0o600
    assert json.loads(target.read_text()) == {"pid": 1}
    assert [path.name for path in tmp_path.iterdir()] == ["bridge.json"]


@pytest.mark.parametrize(
    ("pid", "live", "starts"),
    [(4242, True, False), (4242, False, True), (os.getpid(), True, True)],
    ids=["another live Krita", "a dead pid", "this process"],
)
def test_only_one_krita_runs_the_bridge(tmp_path: Path, pid: int, live: bool, starts: bool) -> None:
    other = {"pid": pid, "session_id": "other"}
    (tmp_path / "bridge.json").write_text(json.dumps(other))
    bridge = _bridge(tmp_path, is_live=live)
    try:
        assert bridge.start() is starts
        written = json.loads((tmp_path / "bridge.json").read_text())
        assert (written == other) is not starts
    finally:
        bridge.stop()
    # Stopping never deletes a file another session wrote.
    assert (tmp_path / "bridge.json").exists() is not starts


def test_stop_leaves_a_bridge_file_another_session_wrote(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    assert bridge.start()
    (tmp_path / "bridge.json").write_text(json.dumps({"pid": 4242, "session_id": "newer"}))
    bridge.stop()
    assert json.loads((tmp_path / "bridge.json").read_text())["session_id"] == "newer"


def test_a_bridge_that_cannot_publish_itself_stops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def full_disk(path: Path, content: dict[str, Any]) -> None:
        raise OSError("no space left")

    monkeypatch.setattr(bridge_file, "write", full_disk)
    bridge = _bridge(tmp_path)
    with pytest.raises(OSError):
        bridge.start()
    assert bridge._thread is not None and bridge._httpd is not None
    bridge._thread.join(5)
    assert not bridge._thread.is_alive()
    assert bridge._httpd.socket.fileno() == -1


def test_stop_runs_in_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bridge = _bridge(tmp_path)
    assert bridge.start()
    calls: list[str] = []
    httpd = bridge._httpd
    assert httpd is not None

    def spy(name: str, real: Any) -> Any:
        def record(*args: Any) -> Any:
            calls.append(name)
            return real(*args)

        return record

    monkeypatch.setattr(bridge.jobs, "stop", spy("stop accepting, cancel queued", bridge.jobs.stop))
    monkeypatch.setattr(httpd, "wait_idle", spy("wait for requests", httpd.wait_idle))
    monkeypatch.setattr(httpd, "shutdown", spy("shutdown", httpd.shutdown))
    monkeypatch.setattr(httpd, "server_close", spy("server_close", httpd.server_close))
    remove = spy("delete bridge.json", bridge_file.remove_if_ours)
    monkeypatch.setattr(bridge_file, "remove_if_ours", remove)
    bridge.stop()
    bridge.stop()
    assert calls == [
        "stop accepting, cancel queued",
        "wait for requests",
        "shutdown",
        "server_close",
        "delete bridge.json",
    ]


def test_stop_returns_when_the_serve_thread_never_ran(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(BridgeHTTPServer, "serve_forever", lambda self, poll_interval=0.5: None)
    bridge = _bridge(tmp_path)
    assert bridge.start()
    assert bridge._thread is not None
    bridge._thread.join(5)
    stopper = threading.Thread(target=bridge.stop, daemon=True)
    stopper.start()
    stopper.join(5)
    assert not stopper.is_alive()


def test_the_token_never_reaches_the_log(tmp_path: Path) -> None:
    logger = log.setup(tmp_path / "logs")
    bridge = _bridge(tmp_path, logger=logger)
    assert bridge.start()
    token = json.loads((tmp_path / "bridge.json").read_text())["token"]
    try:
        logger.info("token %s in a message", token)
        try:
            raise RuntimeError(f"token {token} in a traceback")
        except RuntimeError:
            logger.exception("failure")
    finally:
        bridge.stop()
    text = (tmp_path / "logs" / "plugin.log").read_text()
    assert token not in text
    assert text.count("[token]") >= 2


def test_the_log_rotates_at_5_mb(tmp_path: Path) -> None:
    logger = log.setup(tmp_path / "logs")
    [handler] = logger.handlers
    assert isinstance(handler, logging.handlers.RotatingFileHandler)
    assert (handler.maxBytes, handler.backupCount) == (5 * 1024 * 1024, 1)
    assert Path(handler.baseFilename) == tmp_path / "logs" / "plugin.log"


def test_the_log_is_private_and_stays_private_when_it_rotates(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    older = log_dir / "plugin.log"
    older.write_text("written by an older plugin\n")
    older.chmod(0o644)
    logger = log.setup(log_dir)
    [handler] = logger.handlers
    assert isinstance(handler, logging.handlers.RotatingFileHandler)
    assert stat.S_IMODE(older.stat().st_mode) == 0o600
    logger.info("before the rotation")
    handler.doRollover()
    logger.info("after the rotation")
    handler.close()
    for name in ("plugin.log", "plugin.log.1"):
        assert stat.S_IMODE((log_dir / name).stat().st_mode) == 0o600
    assert "after the rotation" in older.read_text()


def test_a_log_deleted_while_krita_runs_rotates_into_a_fresh_one(tmp_path: Path) -> None:
    logger = log.setup(tmp_path / "logs")
    [handler] = logger.handlers
    assert isinstance(handler, logging.handlers.RotatingFileHandler)
    (tmp_path / "logs" / "plugin.log").unlink()
    handler.doRollover()
    logger.info("after the rotation")
    handler.close()
    path = tmp_path / "logs" / "plugin.log"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert "after the rotation" in path.read_text()


def test_start_sweeps_the_transfer_files_an_ended_session_left(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    leftover = data_dir / "transfer" / "0123.raw"
    leftover.parent.mkdir(parents=True)
    leftover.write_bytes(b"pixels nobody will read")
    bridge = _bridge(data_dir)
    assert bridge.start()
    try:
        assert list((data_dir / "transfer").iterdir()) == []
    finally:
        bridge.stop()


def test_a_second_instance_leaves_the_live_bridge_transfer_files_alone(tmp_path: Path) -> None:
    (tmp_path / "bridge.json").write_text(json.dumps({"pid": 4242, "session_id": "other"}))
    in_flight = tmp_path / "transfer" / "0123.raw"
    in_flight.parent.mkdir()
    in_flight.write_bytes(b"pixels a server is reading")
    bridge = _bridge(tmp_path, is_live=True)
    try:
        assert not bridge.start()
        assert in_flight.exists()
    finally:
        bridge.stop()
