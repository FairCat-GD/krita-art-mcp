# Krita 5.x ships PyQt5 and 6.x PyQt6; the bridge needs only names both share.
try:
    from PyQt6.QtCore import PYQT_VERSION_STR, QT_VERSION_STR, QObject, pyqtSignal, pyqtSlot
    from PyQt6.QtWidgets import QApplication
except ImportError:
    from PyQt5.QtCore import PYQT_VERSION_STR, QT_VERSION_STR, QObject, pyqtSignal, pyqtSlot
    from PyQt5.QtWidgets import QApplication

__all__ = [
    "PYQT_VERSION_STR",
    "QT_VERSION_STR",
    "QApplication",
    "QObject",
    "pyqtSignal",
    "pyqtSlot",
]
