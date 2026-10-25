import logging
import os
import secrets
import threading
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from . import PLUGIN_VERSION, PROTOCOL, bridge_file, capabilities, paths, roots, transfer
from . import log as bridge_log
from .errors import no_arguments
from .jobs import Call, Handler, Jobs
from .server import BridgeHTTPServer
from .source_hash import source_hash

STOP_WAIT_S = 2.0


class Bridge:
    def __init__(
        self,
        data_dir: Path,
        package_dir: Path,
        facts: dict[str, Any],
        handlers: Mapping[str, Handler],
        wake: Callable[[], None],
        on_main_thread: Callable[[], bool],
        is_live_krita: Callable[[int], bool],
        log: logging.Logger,
    ) -> None:
        self._data_dir = data_dir
        self._path = paths.bridge_file(data_dir)
        self._is_live_krita = is_live_krita
        self._log = log
        self.session_id = uuid.uuid4().hex
        self._token = secrets.token_hex(32)
        bridge_log.redact(log, self._token)
        self.health: dict[str, Any] = {
            "protocol": PROTOCOL,
            "plugin_version": PLUGIN_VERSION,
            "plugin_hash": source_hash(package_dir),
            "session_id": self.session_id,
            **facts,
            "capabilities": capabilities.matrix(),
        }
        ops = {"server_info": self._server_info, "probe.retention": self._retention, **handlers}
        self.jobs = Jobs(ops, wake, on_main_thread, log)
        self._httpd: BridgeHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._stopped = False

    def _server_info(self, args: dict[str, Any], call: Call) -> dict[str, Any]:
        # A job, not a cached read, so the answer proves Krita's main thread is free.
        no_arguments(args)
        # Read on every call, so a root added while Krita runs shows at once.
        return {**self.health, "allowed_roots": roots.load(paths.config_file(self._data_dir))}

    def _retention(self, args: dict[str, Any], call: Call) -> dict[str, Any]:
        no_arguments(args)
        return self.jobs.retention()

    def drain(self) -> None:
        self.jobs.drain()

    def start(self) -> bool:
        paths.private_dir(self._data_dir)
        other = bridge_file.other_instance(self._path, os.getpid(), self._is_live_krita)
        if other is not None:
            self._log.warning("Krita %d already runs the bridge, so this one stays off", other)
            return False
        transfer.sweep(paths.transfer_dir(self._data_dir))
        httpd = BridgeHTTPServer(self._token, self.session_id, self.jobs, self.health, self._log)
        serving = threading.Event()

        def serve() -> None:
            serving.set()
            httpd.serve_forever()

        thread = threading.Thread(target=serve, name="krita-art-mcp-bridge", daemon=True)
        self._httpd, self._thread = httpd, thread
        thread.start()
        serving.wait()
        try:
            self._publish(httpd.port)
        except BaseException:
            # A bridge nobody can find must not outlive this call.
            self.stop()
            raise
        self._log.info("bridge %s listening on 127.0.0.1:%d", self.session_id, httpd.port)
        return True

    def _publish(self, port: int) -> None:
        # Written last, so a client that finds the file finds a bridge that answers.
        bridge_file.write(
            self._path,
            {
                "port": port,
                "token": self._token,
                "pid": os.getpid(),
                "session_id": self.session_id,
                "protocol": PROTOCOL,
                "plugin_version": PLUGIN_VERSION,
                "plugin_hash": self.health["plugin_hash"],
                "krita_version": self.health.get("krita_version"),
                "qt_major": self.health.get("qt_major"),
                # Calls may carry `ephemeral`; a server sends it only to a bridge that says so.
                "ephemeral_reads": True,
            },
        )

    def stop(self) -> None:
        # Runs before Python is finalised (K48); every step must return promptly.
        if self._stopped:
            return
        self._stopped = True
        self.jobs.stop()
        httpd, thread = self._httpd, self._thread
        if httpd is not None:
            if not httpd.wait_idle(STOP_WAIT_S):
                self._log.warning("requests were still in flight when the bridge stopped")
            # shutdown() waits for serve_forever, so it would hang if that never ran.
            if thread is not None and thread.is_alive():
                httpd.shutdown()
            httpd.server_close()
            bridge_file.remove_if_ours(self._path, self.session_id)
        self._log.info("bridge %s stopped", self.session_id)
