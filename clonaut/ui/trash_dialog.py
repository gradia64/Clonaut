"""Visualizzatore del cestino di sicurezza (backup-dir)."""

from __future__ import annotations

from pathlib import Path

from ..api import is_remote
from ..appctx import AppContext
from ..i18n import tr
from ..qtcompat import QtCore, QtGui, QtWidgets
from ..util import esc, human_size
from ..worker import CallWorker, stop_thread


def _fmt_modtime(value: str) -> str:
    return (value or "")[:16].replace("T", " ")


class TrashDialog(QtWidgets.QDialog):
    """Elenca il contenuto del cestino; recupero con drag & drop dal gestore file."""

    def __init__(self, ctx: AppContext, backup_dir: str, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.backup_dir = backup_dir
        # elenco e svuotamento possono durare (fino a 60 e 120 s con un remote
        # lento): girano in un thread, la finestra resta usabile e chiudibile
        self._worker: CallWorker | None = None
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
        self.btn_refresh = btn_refresh = QtWidgets.QPushButton(tr("↻ Aggiorna"))
        btn_refresh.clicked.connect(self.refresh)
        self.btn_open = QtWidgets.QPushButton(tr("📂 Apri nel gestore file"))
        self.btn_open.clicked.connect(self._open_fm)
        self.btn_empty = btn_empty = QtWidgets.QPushButton(tr("🧹 Svuota cestino"))
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

    def busy(self) -> bool:
        """True mentre un elenco o uno svuotamento è in corso."""
        return self._worker is not None

    def _run(self, what: str, placeholder: str, fn, *args) -> None:
        """Esegue `fn` in un thread; l'esito arriva a _on_done/_on_failed."""
        self._show_placeholder(placeholder)
        self.btn_refresh.setEnabled(False)
        self.btn_empty.setEnabled(False)
        worker = CallWorker(what, fn, *args)
        worker.succeeded.connect(self._on_done)
        worker.failed.connect(self._on_failed)
        self._worker = worker
        worker.start()

    def _release(self) -> None:
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.wait()   # ha appena emesso l'esito: finisce subito
        self.btn_refresh.setEnabled(True)
        self.btn_empty.setEnabled(True)

    def refresh(self) -> None:
        if self.busy():
            return
        self._run("list", tr("(lettura del cestino…)"),
                  self.ctx.api.operations_list, self.backup_dir)

    def _on_done(self, what, result) -> None:
        self._release()
        if what == "purge":
            self.refresh()
        else:
            self._show_entries(result)

    def _on_failed(self, what, msg: str) -> None:
        self._release()
        if what == "purge":
            QtWidgets.QMessageBox.critical(self, tr("Svuotamento fallito"), esc(msg))
            self.refresh()
        elif "not found" in msg or "doesn't exist" in msg or "File o directory" in msg:
            # svuotato (purge rimuove la cartella) o mai creato: è normale
            self._show_placeholder(tr("(cestino vuoto)"))
        else:   # anche rcd giù: mostra il motivo al posto dell'elenco
            self._show_placeholder(
                tr("(cestino non raggiungibile: {error})").format(error=msg))

    def _show_entries(self, entries) -> None:
        self.tree.clear()
        files = sorted((e for e in entries or [] if not e.get("IsDir")),
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
            item.setToolTip(0, esc(entry.get("Path", "")))
            self.tree.addTopLevelItem(item)

    def done(self, result: int) -> None:  # noqa: D401 — API Qt
        """Chiusura con un'operazione in corso: il suo esito viene ignorato.

        rclone porta comunque a termine la chiamata; il thread non va
        distrutto mentre aspetta, quindi resta in vita fino alla sua fine
        (o fino all'uscita dall'app, che lo aspetta).
        """
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.stop()
            stop_thread(worker, 0)
        super().done(result)

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
        if answer != QtWidgets.QMessageBox.StandardButton.Yes or self.busy():
            return
        self._run("purge", tr("(svuotamento in corso…)"),
                  self.ctx.api.purge, self.backup_dir)
