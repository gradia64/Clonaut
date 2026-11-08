"""Import Qt con fallback PySide6 -> PyQt6 (API identiche usando enum con scope)."""

try:  # PySide6 è la scelta preferita
    import PySide6 as _binding
    from PySide6 import QtCore, QtGui, QtWidgets  # noqa: F401
    from PySide6.QtCore import Signal, QThread, QTimer  # noqa: F401
    BINDING = f"PySide6 {_binding.__version__}"
except ImportError:  # pragma: no cover
    from PyQt6 import QtCore, QtGui, QtWidgets  # noqa: F401
    from PyQt6.QtCore import pyqtSignal as Signal, QThread, QTimer  # noqa: F401
    BINDING = f"PyQt6 {QtCore.PYQT_VERSION_STR}"
