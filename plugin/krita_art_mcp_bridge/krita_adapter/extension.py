import logging
from pathlib import Path
from typing import Any

from krita import Extension, Krita

from ..bridge_core import log, paths
from ..bridge_core.bridge import Bridge
from ..bridge_core.bridge_file import is_live_krita
from . import ops, runtime
from .main_thread import Waker, main_thread_check

PACKAGE_DIR = Path(__file__).resolve().parent.parent


class KritaArtMcpExtension(Extension):
    def __init__(self, parent: Any) -> None:
        super().__init__(parent)
        self._log = logging.getLogger(log.NAME)
        self._bridge: Bridge | None = None
        self._waker: Waker | None = None

    def setup(self) -> None:
        data_dir = paths.data_dir()
        self._log = log.setup(paths.log_dir(data_dir))
        # A plugin that fails here says little in Krita, so the reason goes to plugin.log.
        try:
            self._start(data_dir)
        except Exception:
            self._log.exception("the bridge did not start")

    def createActions(self, window: Any) -> None:
        pass

    def _start(self, data_dir: Path) -> None:
        self._waker = Waker(self._drain, self._log)
        bridge = Bridge(
            data_dir=data_dir,
            package_dir=PACKAGE_DIR,
            facts=runtime.facts(),
            handlers=ops.HANDLERS,
            wake=self._waker.emit,
            on_main_thread=main_thread_check(),
            is_live_krita=is_live_krita,
            log=self._log,
        )
        self._bridge = bridge
        notifier = Krita.instance().notifier()
        # The notifier blocks its signals until something activates it.
        if not notifier.active():
            notifier.setActive(True)
        # Hooked before the start, so whatever part of it ran is stopped at quit.
        notifier.applicationClosing.connect(self._stop)
        bridge.start()

    def _drain(self) -> None:
        if self._bridge is not None:
            self._bridge.drain()

    def _stop(self) -> None:
        try:
            if self._bridge is not None:
                self._bridge.stop()
        except Exception:
            self._log.exception("the bridge did not stop cleanly")


def register() -> None:
    app = Krita.instance()
    app.addExtension(KritaArtMcpExtension(app))
