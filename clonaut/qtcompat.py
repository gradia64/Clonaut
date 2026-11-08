"""Import Qt con fallback PySide6 -> PyQt6 (API identiche usando enum con scope).

La variabile d'ambiente CLONAUT_QT=pyqt6 (o pyside6) sceglie il binding da
provare per primo: utile per i test e se uno dei due dà problemi.
"""

import os

_ORDER = ("pyqt6", "pyside6") if os.environ.get("CLONAUT_QT", "").lower() == "pyqt6" \
    else ("pyside6", "pyqt6")

_errors = []
for _name in _ORDER:
    try:
        if _name == "pyside6":
            import PySide6 as _binding
            from PySide6 import QtCore, QtGui, QtWidgets  # noqa: F401
            from PySide6.QtCore import Signal, QThread, QTimer  # noqa: F401
            BINDING = f"PySide6 {_binding.__version__}"
        else:
            from PyQt6 import QtCore, QtGui, QtWidgets  # noqa: F401
            from PyQt6.QtCore import pyqtSignal as Signal, QThread, QTimer  # noqa: F401
            BINDING = f"PyQt6 {QtCore.PYQT_VERSION_STR}"
        break
    except ImportError as exc:
        # il motivo vero (spesso una libreria di sistema mancante) va mostrato
        _errors.append(f"{_name}: {exc}")
        continue
else:
    raise ImportError("Serve un binding Qt per Python: PyQt6 oppure PySide6.\n"
                      + "\n".join(_errors))
