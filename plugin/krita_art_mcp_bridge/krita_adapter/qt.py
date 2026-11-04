# Krita 5.x ships PyQt5 and 6.x PyQt6; the bridge needs only names both share.
try:
    from PyQt6.QtCore import (
        PYQT_VERSION_STR,
        QT_VERSION_STR,
        QCoreApplication,
        QEventLoop,
        QObject,
        QPointF,
        QRectF,
        pyqtSignal,
        pyqtSlot,
    )
    from PyQt6.QtGui import QIcon, QPainterPath
    from PyQt6.QtWidgets import QAbstractScrollArea, QApplication, QMdiArea

    # The one enum the bridge needs, scoped in PyQt6 and flat in PyQt5.
    EXCLUDE_USER_INPUT = QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents
except ImportError:
    from PyQt5.QtCore import (
        PYQT_VERSION_STR,
        QT_VERSION_STR,
        QCoreApplication,
        QEventLoop,
        QObject,
        QPointF,
        QRectF,
        pyqtSignal,
        pyqtSlot,
    )
    from PyQt5.QtGui import QIcon, QPainterPath
    from PyQt5.QtWidgets import QAbstractScrollArea, QApplication, QMdiArea

    EXCLUDE_USER_INPUT = QEventLoop.ExcludeUserInputEvents

__all__ = [
    "EXCLUDE_USER_INPUT",
    "PYQT_VERSION_STR",
    "QT_VERSION_STR",
    "QAbstractScrollArea",
    "QApplication",
    "QCoreApplication",
    "QIcon",
    "QMdiArea",
    "QObject",
    "QPainterPath",
    "QPointF",
    "QRectF",
    "pyqtSignal",
    "pyqtSlot",
]
