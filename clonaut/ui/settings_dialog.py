"""Dialog impostazioni: tray, notifiche e percorso di rclone."""

from __future__ import annotations

import os

from ..qtcompat import QtWidgets

_KEYS = (
    ("close_to_tray",
     "Chiudi nella tray: la finestra si nasconde, i programmati ⏰ continuano"),
    ("minimize_to_tray", "Minimizza nella tray"),
    ("start_in_tray", "All'avvio resta ridotta nella tray"),
    ("notify_finished", "Mostra una notifica quando un trasferimento termina"),
)


class SettingsDialog(QtWidgets.QDialog):
    """Caselle e campi legati alle chiavi di settings.json; il chiamante le salva."""

    def __init__(self, values: dict, parent=None, rclone_in_use: str = ""):
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

        # -- eseguibile rclone
        group = QtWidgets.QGroupBox("Programma rclone")
        g_lay = QtWidgets.QVBoxLayout(group)
        row = QtWidgets.QHBoxLayout()
        self.ed_rclone = QtWidgets.QLineEdit(str(values.get("rclone_path") or ""))
        self.ed_rclone.setPlaceholderText("automatico: rclone nel PATH")
        btn_browse = QtWidgets.QPushButton("Sfoglia…")
        btn_browse.clicked.connect(self._browse_rclone)
        row.addWidget(self.ed_rclone, 1)
        row.addWidget(btn_browse)
        g_lay.addLayout(row)
        in_use = f"In uso ora: {rclone_in_use}. " if rclone_in_use else ""
        r_hint = QtWidgets.QLabel(
            f"{in_use}Lascia vuoto per usare rclone del sistema. La modifica "
            "vale dal prossimo avvio; la variabile d'ambiente CLONAUT_RCLONE, "
            "se impostata, ha la precedenza.")
        r_hint.setProperty("role", "hint")
        r_hint.setWordWrap(True)
        layout.addWidget(group)
        # la nota sta fuori dal riquadro: dentro, Qt sbaglia l'altezza del testo a capo
        layout.addWidget(r_hint)

        btns = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        btns.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).setText("Salva")
        btns.button(QtWidgets.QDialogButtonBox.StandardButton.Cancel).setText("Annulla")
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _browse_rclone(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Scegli l'eseguibile rclone", os.path.expanduser("~"))
        if path:
            self.ed_rclone.setText(path)

    def accept(self) -> None:  # noqa: D102 — verifica il percorso prima di salvare
        path = os.path.expanduser(self.ed_rclone.text().strip())
        if path and not (os.path.isfile(path) and os.access(path, os.X_OK)):
            QtWidgets.QMessageBox.warning(
                self, "rclone non valido",
                f"«{path}» non esiste o non è un file eseguibile.\n"
                "Lascia il campo vuoto per usare rclone del sistema.")
            return
        super().accept()

    def values(self) -> dict:
        data: dict = {key: box.isChecked() for key, box in self._checks.items()}
        data["rclone_path"] = self.ed_rclone.text().strip()
        return data
