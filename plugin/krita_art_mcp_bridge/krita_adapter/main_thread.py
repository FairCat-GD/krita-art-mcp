import logging
import threading
from collections.abc import Callable

from ..bridge_core.jobs import drain_in_slot
from .qt import QObject, pyqtSignal, pyqtSlot


class Waker(QObject):
    # Emitted from the HTTP thread; Qt queues it to the main thread, where this object lives.
    # A queued signal, unlike a polling timer, costs nothing while Krita is idle (K41).
    wake = pyqtSignal()

    def __init__(self, drain: Callable[[], None], log: logging.Logger) -> None:
        super().__init__()
        self._drain = drain
        self._log = log
        self.wake.connect(self._run)

    @pyqtSlot()
    def _run(self) -> None:
        drain_in_slot(self._drain, self._log)

    def emit(self) -> None:
        try:
            self.wake.emit()
        except RuntimeError:
            # The Qt object is gone: Krita is quitting, and stop() fails the queue.
            self._log.warning("a job arrived while Krita was quitting")


def main_thread_check() -> Callable[[], bool]:
    # Called from Extension.setup(), which Krita runs on its main thread.
    main = threading.get_ident()
    return lambda: threading.get_ident() == main
