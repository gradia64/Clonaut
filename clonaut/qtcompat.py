"""Import Qt con fallback PySide6 -> PyQt6 (API identiche usando enum con scope)."""

try:  # PySide6 è la scelta preferita (presente sul sistema)
    from PySide6 import QtCore, QtGui, QtWidgets  # noqa: F401
    from PySide6.QtCore import Signal, QThread, QTimer  # noqa: F401
except ImportError:  # pragma: no cover
    from PyQt6 import QtCore, QtGui, QtWidgets  # noqa: F401
    from PyQt6.QtCore import pyqtSignal as Signal, QThread, QTimer  # noqa: F401
