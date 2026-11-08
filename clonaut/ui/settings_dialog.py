"""Dialog impostazioni: comportamento della tray e notifiche."""

from __future__ import annotations

from ..qtcompat import QtWidgets

_KEYS = (
    ("close_to_tray",
     "Chiudi nella tray — la finestra si nasconde invece di uscire "
     "(i trasferimenti programmati ⏰ continuano)"),
    ("minimize_to_tray", "Minimizza nella tray"),
    ("start_in_tray", "All'avvio resta ridotta nella tray"),
    ("notify_finished", "Mostra una notifica quando un trasferimento termina"),
)


class SettingsDialog(QtWidgets.QDialog):
    """Caselle legate alle chiavi di settings.json; il chiamante le salva."""

    def __init__(self, values: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Impostazioni")
        self.setMinimumWidth(560)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(8)
        self._checks: dict[str, QtWidgets.QCheckBox] = {}
        for key, label in _KEYS:
            box = QtWidgets.QCheckBox(label)
            box.setChecked(bool(values.get(key)))
            layout.addWidget(box)
            self._checks[key] = box

        hint = QtWidgets.QLabel(
            "La tray richiede il supporto dell'ambiente desktop (su GNOME serve "
            "un'estensione tipo AppIndicator). «All'avvio nella tray» vale dalla "
            "prossima apertura dell'app.")
        hint.setProperty("role", "hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        btns = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        btns.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).setText("Salva")
        btns.button(QtWidgets.QDialogButtonBox.StandardButton.Cancel).setText("Annulla")
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def values(self) -> dict:
        return {key: box.isChecked() for key, box in self._checks.items()}
