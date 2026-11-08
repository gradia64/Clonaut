"""Visualizzatore del cestino di sicurezza (backup-dir)."""

from __future__ import annotations

from pathlib import Path

from ..api import is_remote
from ..appctx import AppContext
from ..i18n import tr
from ..qtcompat import QtCore, QtGui, QtWidgets
from ..util import human_size


def _fmt_modtime(value: str) -> str:
    return (value or "")[:16].replace("T", " ")


class TrashDialog(QtWidgets.QDialog):
    """Elenca il contenuto del cestino; recupero con drag & drop dal gestore file."""

    def __init__(self, ctx: AppContext, backup_dir: str, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.backup_dir = backup_dir
        self.setWindowTitle(tr("Cestino di sicurezza"))
        self.resize(780, 470)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(8)

        head = QtWidgets.QLabel(f"<b>{backup_dir}</b>")
        head.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(head)

        note = QtWidgets.QLabel(
            tr("Qui finiscono i file eliminati o sovrascritti dai trasferimenti "
            "(con il loro percorso). Per recuperarli, apri la cartella e "
            "trascinali dove devono stare. Il cestino tiene l'ultima versione "
            "precedente di ciascun file: svuotalo di tanto in tanto."))
        note.setProperty("role", "hint")
        note.setWordWrap(True)
        layout.addWidget(note)

        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderLabels([tr("File"), tr("Dimensione"), tr("Modificato")])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        header = self.tree.header()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.tree.setColumnWidth(1, 110)
        self.tree.setColumnWidth(2, 130)
        layout.addWidget(self.tree, 1)

        bar = QtWidgets.QHBoxLayout()
        btn_refresh = QtWidgets.QPushButton(tr("↻ Aggiorna"))
        btn_refresh.clicked.connect(self.refresh)
        self.btn_open = QtWidgets.QPushButton(tr("📂 Apri nel gestore file"))
        self.btn_open.clicked.connect(self._open_fm)
        btn_empty = QtWidgets.QPushButton(tr("🧹 Svuota cestino"))
        btn_empty.clicked.connect(self._empty)
        bar.addWidget(btn_refresh)
        bar.addWidget(self.btn_open)
        bar.addWidget(btn_empty)
        bar.addStretch(1)
        btn_close = QtWidgets.QPushButton(tr("Chiudi"))
        btn_close.clicked.connect(self.reject)
        bar.addWidget(btn_close)
        layout.addLayout(bar)

        self.refresh()

    # ------------------------------------------------------------------ dati

    def refresh(self) -> None:
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
        try:
            entries = self.ctx.api.operations_list(self.backup_dir)
        except Exception as exc:  # noqa: BLE001 — anche rcd giù: mostra segnaposto
            QtWidgets.QApplication.restoreOverrideCursor()
            msg = str(exc)
            if "not found" in msg or "doesn't exist" in msg or "File o directory" in msg:
                # svuotato (purge rimuove la cartella) o mai creato: è normale
                self._show_placeholder(tr("(cestino vuoto)"))
            else:
                self._show_placeholder(
                    tr("(cestino non raggiungibile: {error})").format(error=msg))
            return
        QtWidgets.QApplication.restoreOverrideCursor()

        self.tree.clear()
        files = sorted((e for e in entries if not e.get("IsDir")),
                       key=lambda e: str(e.get("Path", "")))
        if not files:
            self._show_placeholder(tr("(cestino vuoto)"))
            return
        for entry in files:
            item = QtWidgets.QTreeWidgetItem([
                str(entry.get("Path", "?")),
                human_size(entry.get("Size")),
                _fmt_modtime(str(entry.get("ModTime", ""))),
            ])
            item.setToolTip(0, str(entry.get("Path", "")))
            self.tree.addTopLevelItem(item)

    def _show_placeholder(self, text: str) -> None:
        self.tree.clear()
        item = QtWidgets.QTreeWidgetItem([text, "—", "—"])
        item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsSelectable)
        self.tree.addTopLevelItem(item)

    # ---------------------------------------------------------------- azioni

    def _open_fm(self) -> None:
        if is_remote(self.backup_dir):
            QtWidgets.QMessageBox.information(
                self, tr("Cestino su remote"),
                tr("Il cestino è su un remote: non c'è un gestore file locale. "
                "I file restano consultabili in questa finestra."))
            return
        path = Path(self.backup_dir)
        if not path.is_dir():
            QtWidgets.QMessageBox.information(
                self, tr("Cestino"),
                tr("La cartella cestino non esiste ancora: verrà creata la prima "
                "volta che un trasferimento vi sposta un file."))
            return
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(path)))

    def _empty(self) -> None:
        answer = QtWidgets.QMessageBox.question(
            self, tr("Svuotare il cestino?"),
            tr("Svuotare definitivamente il cestino?\nI file non saranno più "
            "recuperabili."),
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.No)
        if answer != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        try:
            self.ctx.api.purge(self.backup_dir)
        except Exception as exc:  # noqa: BLE001 — anche rcd giù
            QtWidgets.QMessageBox.critical(self, tr("Svuotamento fallito"), str(exc))
            return
        self.refresh()
