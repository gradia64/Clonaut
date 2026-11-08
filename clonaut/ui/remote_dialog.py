"""Dialog per creare un nuovo remote con form dinamico da `config/providers`."""

from __future__ import annotations

import re

from ..api import ApiError
from ..appctx import AppContext
from ..qtcompat import QtCore, QtWidgets
from ..util import strip_html

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")

# opzioni da mostrare sempre nel form principale (oltre alle Required)
_MAIN_HINTS = {
    "user", "pass", "host", "port", "url", "endpoint", "region", "bucket",
    "root", "key_file", "token", "shareurl", "vendor",
}
# opzioni nascoste del tutto (rumore per un MVP)
_HIDDEN = {"name", "type", "description", "encoding", "metadata", "config_fs_encoding"}

# alias comuni che l'API non espone (rclone li gestisce come altri backend);
# rendono trovabili nel menu Tipo voci come "nextcloud" → webdav + vendor
_ALIASES = {
    "nextcloud": "webdav",
    "owncloud": "webdav",
    "gdrive": "drive",
    "google drive": "drive",
    "amazon s3": "s3",
    "aws s3": "s3",
    "ssh": "sftp",
    "google photos": "gphotos",
}


def combo_value(editor: QtWidgets.QComboBox) -> str:
    """Valore di un menu di esempi: la voce scelta o, se modificabile, il testo libero."""
    index = editor.currentIndex()
    text = editor.currentText().strip()
    if index >= 0 and editor.itemText(index) == editor.currentText():
        return str(editor.itemData(index) or "")
    return text   # digitato a mano (es. endpoint S3 personalizzato)


class RemoteDialog(QtWidgets.QDialog):
    """Creazione guidata: nome + tipo, poi i campi generati dal provider."""

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("Nuovo remote")
        self.resize(660, 660)
        self._fields: dict[str, tuple[QtWidgets.QWidget, dict]] = {}
        self._adv_rows: list[QtWidgets.QWidget] = []

        try:
            self._providers = sorted(ctx.api.providers(), key=lambda p: p.get("Name", ""))
            self._existing = set(ctx.api.list_remotes())
        except ApiError as exc:
            QtWidgets.QMessageBox.critical(self, "Errore", str(exc))
            self._providers, self._existing = [], set()

        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(10)

        # -- identità del remote
        grid = QtWidgets.QGridLayout()
        grid.addWidget(QtWidgets.QLabel("Nome"), 0, 0)
        self.ed_name = QtWidgets.QLineEdit()
        self.ed_name.setPlaceholderText("es. gdrive-personale (senza «:»)")
        grid.addWidget(self.ed_name, 0, 1)
        grid.addWidget(QtWidgets.QLabel("Tipo"), 1, 0)
        self.cb_type = QtWidgets.QComboBox()
        self.cb_type.setEditable(True)
        self.cb_type.setInsertPolicy(QtWidgets.QComboBox.InsertPolicy.NoInsert)
        entries = []   # (chiave di ordinamento, etichetta, dati)
        for p in self._providers:
            desc = strip_html(p.get("Description", "")).split("\n")[0][:48]
            label = f"{p['Name']} — {desc}" if desc else p["Name"]
            entries.append((p["Name"], label, {"type": p["Name"], "alias": ""}))
        for alias, prov in _ALIASES.items():
            if any(p.get("Name") == prov for p in self._providers):
                entries.append((alias, f"{alias} — alias di {prov}",
                                {"type": prov, "alias": alias}))
        for _key, label, data in sorted(entries, key=lambda e: e[0].lower()):
            self.cb_type.addItem(label, data)
        completer = self.cb_type.completer()
        if completer:
            completer.setCaseSensitivity(QtCore.Qt.CaseSensitivity.CaseInsensitive)
            completer.setFilterMode(QtCore.Qt.MatchFlag.MatchContains)
        grid.addWidget(self.cb_type, 1, 1)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)

        # -- suggerimento contestuale (OAuth ecc.)
        self.lbl_hint = QtWidgets.QLabel("")
        self.lbl_hint.setProperty("role", "warn")
        self.lbl_hint.setWordWrap(True)
        self.lbl_hint.hide()
        layout.addWidget(self.lbl_hint)

        # -- form dinamico
        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self._form_host = QtWidgets.QWidget()
        self._form_layout = QtWidgets.QFormLayout(self._form_host)
        self._form_layout.setFieldGrowthPolicy(
            QtWidgets.QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.scroll.setWidget(self._form_host)
        layout.addWidget(self.scroll, 1)

        self.btn_adv = QtWidgets.QToolButton()
        self.btn_adv.setText("Mostra opzioni avanzate")
        self.btn_adv.setCheckable(True)
        self.btn_adv.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.btn_adv.toggled.connect(self._toggle_advanced)
        layout.addWidget(self.btn_adv)

        btns = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        btns.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).setText("Crea remote")
        btns.button(QtWidgets.QDialogButtonBox.StandardButton.Cancel).setText("Annulla")
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        self.cb_type.currentIndexChanged.connect(self._rebuild)
        # selezione iniziale: il primo provider non nascosto
        if self.cb_type.count():
            self.cb_type.setCurrentIndex(0)
            self._rebuild()

    # ------------------------------------------------------------------ form

    def _provider_by_name(self, name: str) -> dict | None:
        return next((p for p in self._providers if p.get("Name") == name), None)

    def _current_type(self) -> str:
        """Nome del provider scelto (direttamente, digitato o tramite alias)."""
        text = self.cb_type.currentText().split(" — ")[0].strip().lower()
        for p in self._providers:
            if p.get("Name", "").lower() == text:
                return p["Name"]
        data = self.cb_type.currentData()
        if isinstance(data, dict):
            return str(data.get("type") or "")
        return str(data or "")

    def _current_provider(self) -> dict | None:
        return self._provider_by_name(self._current_type())

    def _rebuild(self) -> None:
        # svuota il form
        while self._form_layout.count():
            item = self._form_layout.takeAt(0)
            if widget := item.widget():
                widget.deleteLater()
        self._fields.clear()
        self._adv_rows.clear()

        provider = self._current_provider()
        if not provider:
            return

        options = [o for o in provider.get("Options", [])
                   if o.get("Name") and o.get("Name") not in _HIDDEN
                   and not o.get("Hide")]
        # alcuni backend ripetono la stessa opzione per provider diversi
        # (es. koofr: tre «password»): ne basta una, i valori finirebbero
        # comunque nella stessa chiave di configurazione
        unique, seen = [], set()
        for o in options:
            if o["Name"] not in seen:
                seen.add(o["Name"])
                unique.append(o)
        options = unique
        main = [o for o in options
                if o.get("Required") or o["Name"] in _MAIN_HINTS]
        advanced = [o for o in options if o not in main]

        for opt in main:
            self._add_row(opt, advanced=False)
        for opt in advanced:
            self._add_row(opt, advanced=True)

        # suggerimento OAuth
        names = {o.get("Name") for o in options}
        if "token" in names:
            self.lbl_hint.setText(
                "Backend con login OAuth (Google Drive, Dropbox, OneDrive…): la prima "
                "volta serve l'autorizzazione del browser. Crea il remote e poi esegui "
                "nel terminale   rclone authorize \"tipo\"   e incolla il token JSON "
                "nel campo «token».")
            self.lbl_hint.show()
        else:
            self.lbl_hint.hide()
        self._toggle_advanced(self.btn_adv.isChecked())

        # alias scelto (es. «nextcloud»): preseleziona i campi corrispondenti
        data = self.cb_type.currentData()
        alias = data.get("alias", "") if isinstance(data, dict) else ""
        if alias:
            for _name, (editor, _opt) in self._fields.items():
                if isinstance(editor, QtWidgets.QComboBox):
                    index = editor.findData(alias)
                    if index > 0:
                        editor.setCurrentIndex(index)

    def _add_row(self, opt: dict, advanced: bool) -> None:
        name = opt["Name"]
        label = QtWidgets.QLabel(name + (" *" if opt.get("Required") else ""))
        tooltip = strip_html(opt.get("Help", ""))
        if tooltip:
            label.setToolTip(tooltip)

        default = opt.get("DefaultStr") or opt.get("Default")
        placeholder = str(default) if default not in ("", None) else ""
        if placeholder.startswith(("[", "{", "map[")):   # default strutturati: rumore
            placeholder = ""
        examples = [e for e in (opt.get("Examples") or []) if e.get("Value")]
        if examples:
            editor: QtWidgets.QWidget = QtWidgets.QComboBox()
            editor.addItem("(predefinito)", "")
            for ex in examples:
                help_txt = strip_html(str(ex.get("Help", ""))).split("\n")[0]
                editor.addItem(f"{ex['Value']} — {help_txt}" if help_txt
                               else str(ex["Value"]), str(ex["Value"]))
            index = editor.findData(placeholder)
            if index > 0:
                editor.setCurrentIndex(index)
            if not opt.get("Exclusive"):
                # gli esempi sono solo suggerimenti: si può scrivere altro
                editor.setEditable(True)
                editor.setInsertPolicy(QtWidgets.QComboBox.InsertPolicy.NoInsert)
                if tooltip:
                    editor.setToolTip(tooltip)
        elif opt.get("Type") == "bool":
            editor: QtWidgets.QWidget = QtWidgets.QCheckBox()
            if str(default).lower() == "true":
                editor.setChecked(True)
            if tooltip:
                editor.setToolTip(tooltip)
        else:
            editor = QtWidgets.QLineEdit()
            if opt.get("IsPassword"):
                editor.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
            if placeholder:
                editor.setPlaceholderText(f"predefinito: {placeholder}")

        self._form_layout.addRow(label, editor)
        self._fields[name] = (editor, opt)
        if advanced:
            for w in (label, editor):
                self._adv_rows.append(w)

    def _toggle_advanced(self, visible: bool) -> None:
        for w in self._adv_rows:
            w.setVisible(visible)
        self.btn_adv.setText("Nascondi opzioni avanzate" if visible
                             else "Mostra opzioni avanzate")

    def _collect_params(self) -> dict:
        params: dict = {}
        for name, (editor, opt) in self._fields.items():
            if isinstance(editor, QtWidgets.QCheckBox):
                checked = editor.isChecked()
                if checked != (str(opt.get("Default", "")).lower() == "true"):
                    params[name] = "true" if checked else "false"
            elif isinstance(editor, QtWidgets.QComboBox):
                value = combo_value(editor)
                if value:
                    params[name] = value
            else:
                text = editor.text().strip()
                if text:
                    params[name] = text
        return params

    # ---------------------------------------------------------------- accept

    def accept(self) -> None:  # noqa: D102 — validazione prima di chiudere
        name = self.ed_name.text().strip()
        provider = self._current_provider()
        type_ = provider.get("Name") if provider else ""

        if not _NAME_RE.match(name):
            QtWidgets.QMessageBox.warning(
                self, "Nome non valido",
                "Il nome può contenere lettere, numeri, punto, trattino e "
                "trattino basso, e non può contenere «:».")
            return
        if name in self._existing:
            answer = QtWidgets.QMessageBox.question(
                self, "Remote esistente",
                f"Il remote «{name}» esiste già: sovrascriverlo?",
                QtWidgets.QMessageBox.StandardButton.Yes
                | QtWidgets.QMessageBox.StandardButton.No)
            if answer != QtWidgets.QMessageBox.StandardButton.Yes:
                return
        if not type_:
            QtWidgets.QMessageBox.warning(self, "Tipo mancante",
                                          "Scegli il tipo di remote.")
            return

        missing = []
        for fname, (editor, opt) in self._fields.items():
            if not opt.get("Required"):
                continue
            if isinstance(editor, QtWidgets.QComboBox):
                empty = not combo_value(editor)
            elif isinstance(editor, QtWidgets.QCheckBox):
                empty = False   # un booleano ha sempre un valore (anche «false»)
            else:
                empty = editor.text().strip() == ""
            if empty:
                missing.append(fname)
        if missing and QtWidgets.QMessageBox.question(
                self, "Campi obbligatori vuoti",
                "Questi campi sono marcati obbligatori ma sono vuoti:\n  • "
                + "\n  • ".join(missing)
                + "\n\nCreare comunque il remote?",
                QtWidgets.QMessageBox.StandardButton.Yes
                | QtWidgets.QMessageBox.StandardButton.No
                ) != QtWidgets.QMessageBox.StandardButton.Yes:
            return

        try:
            self.ctx.api.create_remote(name, type_, self._collect_params())
        except ApiError as exc:
            QtWidgets.QMessageBox.critical(self, "Creazione fallita", str(exc))
            return
        super().accept()
