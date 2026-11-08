"""Dialog «Nuovo trasferimento»: sorgente, destinazione, modalità, dry-run."""

from __future__ import annotations

import os

from ..api import ApiError, is_remote
from ..appctx import AppContext
from ..qtcompat import QtCore, QtWidgets


_UNITS = (("ore", 3600), ("minuti", 60), ("giorni", 86400))


def split_interval(seconds: int) -> tuple[int, int]:
    """Intervallo in secondi → (valore, unità in secondi) nell'unità più grande esatta."""
    seconds = max(60, int(seconds))
    for unit in (86400, 3600, 60):
        if seconds % unit == 0 and seconds // unit <= 999:
            return seconds // unit, unit
    return min(999, max(1, round(seconds / 60))), 60


class TransferDialog(QtWidgets.QDialog):
    """Raccoglie i parametri e avvia il job tramite TransfersTab.

    Con `schedule` e `def_id` diventa «Modifica programmazione»: i campi sono
    precompilati e «Salva» aggiorna la programmazione ⏰ esistente.
    """

    def __init__(self, ctx: AppContext, transfers_tab, parent=None,
                 schedule: dict | None = None, def_id: str | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self.tab = transfers_tab
        self._def_id = def_id if schedule is not None else None
        self._orig = dict(schedule or {})
        self.setWindowTitle("Modifica programmazione" if self._def_id
                            else "Nuovo trasferimento")
        self.setMinimumWidth(720)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(10)

        grid = QtWidgets.QGridLayout()
        grid.addWidget(QtWidgets.QLabel("Modalità"), 0, 0)
        self.cb_mode = QtWidgets.QComboBox()
        self.cb_mode.addItem("Copia — lascia l'origine intatta", "copy")
        self.cb_mode.addItem("Sposta — elimina i file di origine dopo il trasferimento",
                             "move")
        self.cb_mode.addItem("Sincronizza — la destinazione diventa identica "
                             "all'origine (elimina gli extra!)", "sync")
        grid.addWidget(self.cb_mode, 0, 1, 1, 2)

        grid.addWidget(QtWidgets.QLabel("Sorgente"), 1, 0)
        self.ed_src = QtWidgets.QLineEdit()
        self.ed_src.setPlaceholderText(
            "es. gdrive:Documenti  oppure  /home/utente/cartella")
        grid.addWidget(self.ed_src, 1, 1)
        btn_src = QtWidgets.QPushButton("Sfoglia…")
        btn_src.clicked.connect(lambda: self._browse(self.ed_src))
        grid.addWidget(btn_src, 1, 2)

        grid.addWidget(QtWidgets.QLabel("Destinazione"), 2, 0)
        self.ed_dst = QtWidgets.QLineEdit()
        self.ed_dst.setPlaceholderText("es. /media/backup  oppure  dropbox:Backup")
        grid.addWidget(self.ed_dst, 2, 1)
        btn_dst = QtWidgets.QPushButton("Sfoglia…")
        btn_dst.clicked.connect(lambda: self._browse(self.ed_dst))
        grid.addWidget(btn_dst, 2, 2)

        grid.addWidget(QtWidgets.QLabel("Escludi"), 3, 0)
        self.ed_exclude = QtWidgets.QLineEdit()
        self.ed_exclude.setPlaceholderText(
            "pattern rclone separati da virgola, es. .sync_*, .nextcloudsync.log, *.log")
        grid.addWidget(self.ed_exclude, 3, 1, 1, 2)
        grid.setColumnStretch(1, 1)
        # ripetizione automatica
        grid.addWidget(QtWidgets.QLabel("Ripeti"), 4, 0)
        rep = QtWidgets.QWidget()
        rep_lay = QtWidgets.QHBoxLayout(rep)
        rep_lay.setContentsMargins(0, 0, 0, 0)
        rep_lay.setSpacing(8)
        self.chk_repeat = QtWidgets.QCheckBox("automaticamente ogni")
        self.spn_repeat = QtWidgets.QSpinBox()
        self.spn_repeat.setRange(1, 999)
        self.spn_repeat.setValue(6)
        self.cb_unit = QtWidgets.QComboBox()
        for label, secs in _UNITS:
            self.cb_unit.addItem(label, secs)
        rep_lay.addWidget(self.chk_repeat)
        rep_lay.addWidget(self.spn_repeat)
        rep_lay.addWidget(self.cb_unit)
        rep_lay.addStretch(1)
        grid.addWidget(rep, 4, 1, 1, 2)
        self.spn_repeat.setEnabled(False)
        self.cb_unit.setEnabled(False)
        self.chk_repeat.toggled.connect(self._repeat_toggled)

        # cestino di sicurezza (backup-dir)
        grid.addWidget(QtWidgets.QLabel("Cestino"), 5, 0)
        trash_widget = QtWidgets.QWidget()
        trash_lay = QtWidgets.QHBoxLayout(trash_widget)
        trash_lay.setContentsMargins(0, 0, 0, 0)
        trash_lay.setSpacing(8)
        self.chk_trash = QtWidgets.QCheckBox("di sicurezza")
        self.chk_trash.setToolTip(
            "I file che verrebbero eliminati o sovrascritti in destinazione "
            "vengono SPOSTATI qui invece che cancellati. Non deve stare DENTRO "
            "la destinazione (il sync lo cancellerebbe).")
        self.ed_trash = QtWidgets.QLineEdit()
        self.ed_trash.setPlaceholderText(
            "attiva la spunta: viene proposta <destinazione>-cestino")
        self.btn_trash = QtWidgets.QPushButton("Sfoglia…")
        self.btn_trash.clicked.connect(self._browse_trash)
        trash_lay.addWidget(self.chk_trash)
        trash_lay.addWidget(self.ed_trash, 1)
        trash_lay.addWidget(self.btn_trash)
        grid.addWidget(trash_widget, 5, 1, 1, 2)
        self.ed_trash.setEnabled(False)
        self.btn_trash.setEnabled(False)
        self.chk_trash.toggled.connect(self._trash_toggled)
        layout.addLayout(grid)

        self.chk_dry = QtWidgets.QCheckBox(
            "Prova a vuoto: esegue il trasferimento davvero ma senza scrivere "
            "o eliminare nulla (l'esito appare nella coda)")
        layout.addWidget(self.chk_dry)

        hint = QtWidgets.QLabel(
            "«Sfoglia…» sceglie una cartella locale; per i remoti digita "
            "nome:percorso (i remoti esistenti vengono suggeriti mentre scrivi). "
            "Puoi anche indicare un singolo file digitandone il percorso. "
            "«Escludi» salta i file corrispondenti (utile per i journal dei "
            "client di sync) e vale anche per la prova a vuoto. "
            "Il cestino tiene l'ultima versione precedente dei file eliminati "
            "o sovrascritti: svuotalo tu di tanto in tanto. "
            "La ripetizione sopravvive alla chiusura dell'app.")
        hint.setProperty("role", "hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        btns = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        btns.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).setText("Avvia")
        btns.button(QtWidgets.QDialogButtonBox.StandardButton.Cancel).setText("Annulla")
        self._btn_ok = btns.button(QtWidgets.QDialogButtonBox.StandardButton.Ok)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        self._add_completers()
        self.ed_src.setFocus()
        if self._def_id:
            self._fill_from_schedule(self._orig)

    def _fill_from_schedule(self, d: dict) -> None:
        """Precompila il dialog con una programmazione esistente."""
        index = self.cb_mode.findData(d.get("mode", "copy"))
        self.cb_mode.setCurrentIndex(max(0, index))
        self.ed_src.setText(d.get("src", ""))
        self.ed_dst.setText(d.get("dst", ""))
        self.ed_exclude.setText(", ".join(d.get("exclude") or []))
        value, unit = split_interval(d.get("interval") or 3600)
        self.chk_repeat.setChecked(True)
        self.chk_repeat.setEnabled(False)   # una programmazione si ripete sempre
        self.spn_repeat.setValue(value)
        self.cb_unit.setCurrentIndex(max(0, self.cb_unit.findData(unit)))
        if d.get("backup_dir"):
            self.ed_trash.setText(d["backup_dir"])
            self.chk_trash.setChecked(True)
        self.chk_dry.setChecked(False)
        self.chk_dry.hide()
        self._btn_ok.setText("Salva")

    # ------------------------------------------------------------------ helper

    def _repeat_toggled(self, on: bool) -> None:
        self.spn_repeat.setEnabled(on)
        self.cb_unit.setEnabled(on)
        if self._btn_ok is not None and not getattr(self, "_def_id", None):
            self._btn_ok.setText("Programma" if on else "Avvia")

    def _trash_toggled(self, on: bool) -> None:
        self.ed_trash.setEnabled(on)
        self.btn_trash.setEnabled(on)
        if on and not self.ed_trash.text().strip():
            dst = self.ed_dst.text().strip().rstrip("/")
            if dst:
                self.ed_trash.setText(dst + "-cestino")

    def _browse_trash(self) -> None:
        path = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Scegli la cartella cestino", os.path.expanduser("~"))
        if path:
            self.ed_trash.setText(path)

    def _add_completers(self) -> None:
        try:
            remotes = [f"{r}:" for r in self.ctx.api.list_remotes()]
        except Exception:  # noqa: BLE001 — i suggerimenti non devono bloccare
            remotes = []
        for edit in (self.ed_src, self.ed_dst):
            completer = QtWidgets.QCompleter(remotes, edit)
            completer.setCaseSensitivity(QtCore.Qt.CaseSensitivity.CaseInsensitive)
            edit.setCompleter(completer)

    def _browse(self, edit: QtWidgets.QLineEdit) -> None:
        path = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Scegli cartella locale", os.path.expanduser("~"))
        if path:
            edit.setText(path)

    # ------------------------------------------------------------------ accept

    def accept(self) -> None:  # noqa: D102 — validazione prima di chiudere
        src = self.ed_src.text().strip()
        dst = self.ed_dst.text().strip()
        mode = self.cb_mode.currentData()
        dry = self.chk_dry.isChecked()
        exclude = [p.strip() for p in self.ed_exclude.text().split(",") if p.strip()]
        trash = self.ed_trash.text().strip() if self.chk_trash.isChecked() else ""

        if not src or not dst:
            QtWidgets.QMessageBox.warning(
                self, "Dati mancanti", "Indica sorgente e destinazione.")
            return
        if os.path.expanduser(src) == os.path.expanduser(dst):
            QtWidgets.QMessageBox.warning(
                self, "Percorsi identici", "Sorgente e destinazione coincidono.")
            return
        if trash and not is_remote(trash) and not is_remote(dst):
            td = os.path.abspath(os.path.expanduser(trash))
            dd = os.path.abspath(os.path.expanduser(dst))
            if td == dd or td.startswith(dd + os.sep):
                QtWidgets.QMessageBox.warning(
                    self, "Cestino dentro la destinazione",
                    "Il cestino non può stare dentro la destinazione: il sync "
                    "lo cancellerebbe al primo giro. Scegli un percorso fuori "
                    "dalla destinazione (es. una cartella gemella «-cestino»).")
                return

        # in modifica si richiede conferma solo se cambia ciò che verrà eliminato
        changed_scope = not self._def_id or (
            mode != self._orig.get("mode") or src != self._orig.get("src")
            or dst != self._orig.get("dst"))
        if mode in ("move", "sync") and not dry and changed_scope:
            what = ("I file di ORIGINE verranno eliminati dopo il trasferimento"
                    if mode == "move" else
                    "La DESTINAZIONE verrà resa identica alla sorgente: i file "
                    "presenti solo in destinazione verranno ELIMINATI")
            answer = QtWidgets.QMessageBox.question(
                self, f"Conferma «{mode}»", f"{what}.\n\nContinuare?",
                QtWidgets.QMessageBox.StandardButton.Yes
                | QtWidgets.QMessageBox.StandardButton.No)
            if answer != QtWidgets.QMessageBox.StandardButton.Yes:
                return

        if dry:
            try:
                self.tab.start_dry(mode, src, dst, exclude, trash)
            except ApiError as exc:
                QtWidgets.QMessageBox.critical(self, "Prova non riuscita", str(exc))
                return
            QtWidgets.QMessageBox.information(
                self, "Prova a vuoto avviata",
                "La prova è in corso (senza scritture): l'esito apparirà nella coda "
                "tra i trasferimenti, marcato «Prova».")
            super().accept()
            return

        if self._def_id:
            interval = self.spn_repeat.value() * self.cb_unit.currentData()
            running = self.tab.update_recurring(
                self._def_id, mode, src, dst, exclude, interval, backup_dir=trash)
            if running:
                QtWidgets.QMessageBox.information(
                    self, "Programmazione aggiornata",
                    "Un giro è in corso con le impostazioni precedenti: le "
                    "modifiche valgono dal prossimo giro.")
            super().accept()
            return

        if self.chk_repeat.isChecked():
            interval = self.spn_repeat.value() * self.cb_unit.currentData()
            self.tab.add_recurring(mode, src, dst, exclude, interval, backup_dir=trash)
            QtWidgets.QMessageBox.information(
                self, "Trasferimento programmato",
                f"Si ripeterà automaticamente ogni {self.spn_repeat.value()} "
                f"{self.cb_unit.currentText()}: il primo giro parte adesso "
                "(riga ⏰ nella coda; tasto destro per pausa/rimozione).")
            super().accept()
            return

        try:
            jobid = self.tab.start_transfer(mode, src, dst, exclude=exclude,
                                            backup_dir=trash or None)
        except ApiError as exc:
            QtWidgets.QMessageBox.critical(self, "Avvio fallito", str(exc))
            return
        QtWidgets.QMessageBox.information(
            self, "Trasferimento avviato",
            f"Job #{jobid} avviato: guarda la coda per i progressi.")
        super().accept()
