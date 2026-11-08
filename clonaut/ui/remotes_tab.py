"""Tab «Remote»: elenco, creazione, eliminazione e dettagli dei remote."""

from __future__ import annotations

import json

from ..api import ApiError
from ..appctx import AppContext
from ..i18n import N_, tr
from ..qtcompat import QtCore, QtWidgets, Signal
from .remote_dialog import RemoteDialog

# campi "interessanti" da mostrare nella colonna Riepilogo, in ordine di preferenza
_SUMMARY_KEYS = ("root", "host", "url", "endpoint", "region", "bucket", "user", "shareurl")


def _summary(params: dict) -> str:
    parts = []
    for key in _SUMMARY_KEYS:
        value = params.get(key)
        if value and value != "XXX":
            parts.append(f"{key}={value}")
        if len(parts) == 3:
            break
    return ", ".join(parts) if parts else "—"


def _show_error(parent, exc: Exception, title: str = N_("Errore")) -> None:
    QtWidgets.QMessageBox.critical(parent, tr(title), str(exc))


class RemoteDetailsDialog(QtWidgets.QDialog):
    """Mostra la config di un remote (valori sensibili mascherati da rclone)."""

    def __init__(self, name: str, params: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Remote «{name}»").format(name=name))
        self.resize(520, 420)
        layout = QtWidgets.QVBoxLayout(self)

        note = QtWidgets.QLabel(
            tr("Nota: rclone maschera i valori sensibili con XXX; per modificarli "
            "usa <code>rclone config</code> da terminale."))
        note.setProperty("role", "hint")
        note.setWordWrap(True)
        layout.addWidget(note)

        text = QtWidgets.QPlainTextEdit()
        text.setReadOnly(True)
        text.setPlainText(json.dumps(params, indent=2, ensure_ascii=False))
        layout.addWidget(text, 1)

        btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(self.reject)
        btns.clicked.connect(self.accept)
        layout.addWidget(btns)


class RemotesTab(QtWidgets.QWidget):
    """Elenco dei remote con azioni di gestione."""

    changed = Signal()  # la lista remote è cambiata (per i completer)

    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self._dump: dict = {}

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # -- barra azioni
        bar = QtWidgets.QHBoxLayout()
        btn_add = QtWidgets.QPushButton(tr("＋ Aggiungi…"))
        btn_add.clicked.connect(self._on_add)
        btn_del = QtWidgets.QPushButton(tr("🗑 Elimina"))
        btn_del.clicked.connect(self._on_delete)
        btn_details = QtWidgets.QPushButton(tr("Dettagli…"))
        btn_details.clicked.connect(self._on_details)
        btn_refresh = QtWidgets.QPushButton(tr("↻ Aggiorna"))
        btn_refresh.clicked.connect(self.refresh)
        bar.addWidget(btn_add)
        bar.addWidget(btn_del)
        bar.addWidget(btn_details)
        bar.addStretch(1)
        bar.addWidget(btn_refresh)
        layout.addLayout(bar)

        # -- elenco
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderLabels([tr("Nome"), tr("Tipo"), tr("Riepilogo")])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        header = self.tree.header()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.tree.setColumnWidth(0, 200)
        self.tree.setColumnWidth(1, 110)
        self.tree.itemDoubleClicked.connect(lambda *_: self._on_details())
        layout.addWidget(self.tree, 1)

        hint = QtWidgets.QLabel(
            tr("Doppio clic su un remote per i dettagli. I remoti si usano nei "
            "trasferimenti come «nome:percorso»."))
        hint.setProperty("role", "hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.refresh()

    # ------------------------------------------------------------------ dati

    def _selected_name(self) -> str | None:
        item = self.tree.currentItem()
        return item.data(0, QtCore.Qt.ItemDataRole.UserRole) if item else None

    def refresh(self) -> None:
        try:
            QtWidgets.QApplication.setOverrideCursor(
                QtCore.Qt.CursorShape.WaitCursor)
            self._dump = self.ctx.api.dump_config()
        except Exception as exc:  # noqa: BLE001 — mostra tutto all'utente
            QtWidgets.QApplication.restoreOverrideCursor()
            _show_error(self, exc, tr("Impossibile leggere la configurazione"))
            return
        QtWidgets.QApplication.restoreOverrideCursor()

        self.tree.clear()
        for name in sorted(self._dump):
            params = self._dump[name] or {}
            item = QtWidgets.QTreeWidgetItem(
                [name, params.get("type", "?"), _summary(params)])
            item.setData(0, QtCore.Qt.ItemDataRole.UserRole, name)
            self.tree.addTopLevelItem(item)
        if not self._dump:
            empty = QtWidgets.QTreeWidgetItem(
                [tr("Nessun remote configurato"), "—", tr("clicca «＋ Aggiungi…» per crearne uno")])
            empty.setFlags(empty.flags() & ~QtCore.Qt.ItemFlag.ItemIsSelectable)
            self.tree.addTopLevelItem(empty)

    # ---------------------------------------------------------------- azioni

    def _on_add(self) -> None:
        dlg = RemoteDialog(self.ctx, self)
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            self.refresh()
            self.changed.emit()

    def _on_delete(self) -> None:
        name = self._selected_name()
        if not name:
            return
        answer = QtWidgets.QMessageBox.question(
            self, tr("Eliminare il remote?"),
            tr("Eliminare il remote «{name}» dalla configurazione di rclone?\n\n"
               "I file sui servizi remoti NON vengono cancellati: viene rimossa "
               "solo la voce di configurazione.").format(name=name),
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.No)
        if answer != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        try:
            self.ctx.api.delete_remote(name)
        except ApiError as exc:
            _show_error(self, exc, tr("Eliminazione fallita"))
            return
        self.refresh()
        self.changed.emit()

    def _on_details(self) -> None:
        name = self._selected_name()
        if not name:
            return
        RemoteDetailsDialog(name, self._dump.get(name, {}), self).exec()
