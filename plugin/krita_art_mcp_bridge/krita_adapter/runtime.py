import sys
import threading
from typing import Any

from krita import Krita, Node

from .qt import PYQT_VERSION_STR, QT_VERSION_STR


def facts() -> dict[str, Any]:
    # Read once at bridge start, on the main thread, and served from the health snapshot.
    return {
        "krita_version": str(Krita.instance().version()),
        "qt_version": str(QT_VERSION_STR),
        "qt_major": int(str(QT_VERSION_STR).split(".")[0]),
        "pyqt_version": str(PYQT_VERSION_STR),
        "python_version": sys.version.split()[0],
        "setup_on_python_main_thread": threading.current_thread() is threading.main_thread(),
        "paint_polyline_stroke": hasattr(Node, "paintPolylineStroke"),
    }
