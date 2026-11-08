"""Tab «Trasferimenti»: coda job con progressi, annullamento e file in corso."""

from __future__ import annotations

import json
import time

from pathlib import Path

from ..api import ApiError
from ..appctx import AppContext
from ..i18n import N_, tr
from ..qtcompat import QtCore, QtGui, QtWidgets, Signal
from .. import settings as app_settings
from ..util import fmt_duration, fmt_eta, human_size, human_speed
from ..worker import DryRunWorker
from .transfer_dialog import TransferDialog
from .trash_dialog import TrashDialog

_COLS = [N_("Job"), N_("Tipo"), N_("Sorgente"), N_("Destinazione"), N_("Stato"),
         N_("Progresso"), N_("Velocità"), N_("ETA"), N_("Trasferito")]

_GREEN = QtGui.QColor("#1a7f37")
_RED = QtGui.QColor("#c62828")
_BLUE = QtGui.QColor("#1565c0")
_GRAY = QtGui.QColor("#6b7280")

_ROLE_JID = QtCore.Qt.ItemDataRole.UserRole          # jobid corrente della riga
_ROLE_REC = QtCore.Qt.ItemDataRole.UserRole + 1      # def_id per le righe ⏰
_ROLE_BACKUP = QtCore.Qt.ItemDataRole.UserRole + 2   # cartella cestino della riga


def _rec_path() -> Path:
    return app_settings.config_dir() / "recurring.json"


_MODE_LABEL = {"copy": N_("Copia"), "move": N_("Sposta"), "sync": N_("Sincronizza")}


def _mode(mode: str, default: str | None = None) -> str:
    """Nome della modalità nella lingua dell'interfaccia (o `default`)."""
    label = _MODE_LABEL.get(mode)
    if label:
        return tr(label)
    return mode if default is None else default


class TransfersTab(QtWidgets.QWidget):
    """Coda dei trasferimenti con barre di avanzamento aggiornate dal PollWorker."""

    job_started = Signal(int)          # un nuovo job è in coda: registrarli nel worker
    job_finished = Signal(str, bool)   # titolo, ok — per le notifiche tray
    job_dismissed = Signal(int)        # riga tolta dalla coda: il worker smette di seguirla

    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self._rows: dict[int, tuple[QtWidgets.QTreeWidgetItem, QtWidgets.QProgressBar]] = {}
        self._meta: dict[int, dict] = {}   # jobid -> {mode, src, dst, ...}
        self._last: dict | None = None
        self._dry_rows: dict[str, QtWidgets.QTreeWidgetItem] = {}
        self._dry_workers: dict[str, DryRunWorker] = {}
        self._dry_seq = 0
        self._prev_finished: set[int] | None = None   # per le notifiche di fine job
        # trasferimenti ripetuti (programmazioni ⏰)
        self._recurrent: dict[str, dict] = {}
        self._rec_item: dict[str, QtWidgets.QTreeWidgetItem] = {}
        self._rec_bars: dict[str, QtWidgets.QProgressBar] = {}
        self._rec_of_jid: dict[int, str] = {}   # jobid del giro in corso -> def_id
        self._rec_next_id = 1
        self._dismissed: set[int] = set()   # job tolti con «Rimuovi completati»

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # -- barra azioni
        bar = QtWidgets.QHBoxLayout()
        btn_new = QtWidgets.QPushButton(tr("＋ Nuovo trasferimento"))
        btn_new.clicked.connect(self._on_new)
        self.btn_stop = QtWidgets.QPushButton(tr("⏹ Annulla"))
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._on_stop)
        btn_clear = QtWidgets.QPushButton(tr("🧹 Rimuovi completati"))
        btn_clear.clicked.connect(self._on_clear)
        self.btn_trash = QtWidgets.QPushButton(tr("🗑 Cestino"))
        self.btn_trash.setEnabled(False)
        self.btn_trash.clicked.connect(self._on_open_trash)
        self.btn_trash.setToolTip(tr("Apre il cestino di sicurezza del trasferimento "
                                  "selezionato (richiede il campo «Cestino»)"))
        bar.addWidget(btn_new)
        bar.addWidget(self.btn_stop)
        bar.addWidget(btn_clear)
        bar.addWidget(self.btn_trash)
        bar.addStretch(1)
        self.lbl_agg = QtWidgets.QLabel("")
        self.lbl_agg.setProperty("role", "hint")
        bar.addWidget(self.lbl_agg)
        layout.addLayout(bar)

        # -- coda job
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderLabels([tr(c) for c in _COLS])
        self.tree.setRootIsDecorated(False)
        self.tree.setAllColumnsShowFocus(True)
        self.tree.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        header = self.tree.header()
        for col, width in ((0, 55), (1, 110), (4, 150), (5, 170),
                           (6, 100), (7, 80), (8, 260)):
            header.setSectionResizeMode(col, QtWidgets.QHeaderView.ResizeMode.Interactive)
            self.tree.setColumnWidth(col, width)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.tree.itemSelectionChanged.connect(self._update_files)
        self.tree.itemDoubleClicked.connect(self._on_double_click)
        layout.addWidget(self.tree, 3)

        # -- file in corso del job selezionato
        group = QtWidgets.QGroupBox(tr("File in corso (job selezionato)"))
        g_layout = QtWidgets.QVBoxLayout(group)
        self.files = QtWidgets.QTreeWidget()
        self.files.setHeaderLabels([tr("File"), tr("Completato"), tr("Dimensione"), tr("Velocità")])
        self.files.setRootIsDecorated(False)
        self.files.setAlternatingRowColors(True)
        fh = self.files.header()
        fh.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        for col, width in ((1, 170), (2, 110), (3, 110)):
            fh.setSectionResizeMode(col, QtWidgets.QHeaderView.ResizeMode.Interactive)
            self.files.setColumnWidth(col, width)
        self.files.setMinimumHeight(110)
        g_layout.addWidget(self.files)
        layout.addWidget(group, 1)

        hint = QtWidgets.QLabel(
            tr("I percorsi remoti si scrivono «nome:cartella»; quelli locali come "
            "percorso del filesystem (anche un singolo file). I programmati ⏰ "
            "si gestiscono col tasto destro: avvia ora, modifica, pausa, "
            "rimuovi (doppio clic per modificarli)."))
        hint.setProperty("role", "hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        # -- programmazioni ⏰ salvate + timer di avvio (dopo la creazione di tree)
        self._load_recurring()
        self.tree.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        self._rec_timer = QtCore.QTimer(self)
        self._rec_timer.setInterval(1000)
        self._rec_timer.timeout.connect(self._on_rec_tick)
        self._rec_timer.start()

    # ------------------------------------------------------------- avvio job

    def start_transfer(self, mode: str, src: str, dst: str,
                       exclude: list[str] | None = None,
                       backup_dir: str | None = None) -> int:
        """Avvia un job tramite l'API e registra i metadati per la tabella."""
        jobid = self.ctx.api.start_transfer(mode, src, dst, exclude=exclude,
                                            backup_dir=backup_dir)
        self._meta[jobid] = {"mode": mode, "src": src, "dst": dst,
                             "exclude": exclude or [],
                             "backup_dir": backup_dir or ""}
        self.job_started.emit(jobid)
        return jobid

    def start_dry(self, mode: str, src: str, dst: str,
                  exclude: list[str] | None = None,
                  backup_dir: str | None = None) -> str:
        """Prova a vuoto sul backend dedicato (--dry-run), con riga in coda."""
        self._dry_seq += 1
        key = f"dry-{self._dry_seq}"
        self._new_dry_row(key, mode, src, dst, backup_dir)
        try:
            api = self.ctx.ensure_dry_backend()
        except Exception as exc:  # noqa: BLE001 — mostra l'errore sulla riga
            self._on_dry_done(key, False, str(exc))
            return key
        worker = DryRunWorker(api, key, mode, src, dst, exclude, backup_dir)
        worker.done.connect(self._on_dry_done)
        worker.finished.connect(worker.deleteLater)
        self._dry_workers[key] = worker
        worker.start()
        return key

    def dry_workers(self) -> list[DryRunWorker]:
        """Prove a vuoto ancora in corso (da fermare all'uscita)."""
        return list(self._dry_workers.values())

    def _new_dry_row(self, key: str, mode: str, src: str, dst: str,
                     backup_dir: str | None = None) -> None:
        item = QtWidgets.QTreeWidgetItem()
        item.setText(0, "—")
        item.setText(1, tr("Prova · {mode}").format(mode=_mode(mode)))
        for col, path in ((2, src), (3, dst)):
            item.setText(col, path)
            item.setToolTip(col, path)
        item.setText(4, tr("🧪 Prova in corso…"))
        item.setForeground(4, _BLUE)
        item.setToolTip(4, tr("La prova è un trasferimento vero senza scritture: "
                           "può durare quanto il trasferimento stesso."))
        if backup_dir:
            item.setData(0, _ROLE_BACKUP, backup_dir)
        bar = QtWidgets.QProgressBar()
        bar.setRange(0, 1000)
        bar.setFormat(tr("anteprima"))
        item.setSizeHint(5, QtCore.QSize(0, 24))
        self.tree.addTopLevelItem(item)
        self.tree.setItemWidget(item, 5, bar)
        self._rows[key] = (item, bar)
        self._dry_rows[key] = item

    def _on_dry_done(self, key: str, ok: bool, message: str) -> None:
        self._dry_workers.pop(key, None)
        item = self._dry_rows.pop(key, None)
        entry = self._rows.get(key)
        if item is None or entry is None:
            return
        _item, bar = entry
        if ok:
            item.setText(4, tr("🧪 Prova completata — {summary}").format(summary=message)
                         if message else tr("🧪 Prova completata"))
            item.setForeground(4, _GREEN)
            item.setToolTip(4, tr("Anteprima a vuoto: nessun file scritto o eliminato."))
            bar.setValue(1000)
            bar.setFormat("%p%")
        else:
            item.setText(4, tr("✕ Prova fallita"))
            item.setForeground(4, _RED)
            item.setToolTip(4, message)
            bar.setStyleSheet("QProgressBar::chunk { background: #d05a5a; }")
        # marcata come finita: «Rimuovi completati» può toglierla
        item.setData(4, QtCore.Qt.ItemDataRole.UserRole, True)

    def _on_new(self) -> None:
        TransferDialog(self.ctx, self).exec()

    # ------------------------------------------------------------ slot worker

    def on_snapshot(self, snap: dict) -> None:
        self._last = snap
        self._update_tree(snap)
        self._update_recurring(snap)
        self._update_files()
        self._update_agg(snap)
        self._notify_finished(snap)

    def _notify_finished(self, snap: dict) -> None:
        """Emette job_finished per i job appena terminati (notifiche tray)."""
        jobs = snap.get("jobs", {})
        if self._prev_finished is None:
            # primo snapshot: i job già finiti non generano notifiche
            self._prev_finished = {jid for jid, p in jobs.items()
                                   if p["status"].get("finished")}
            return
        for jid, payload in jobs.items():
            status = payload.get("status") or {}
            if not status.get("finished") or jid in self._prev_finished:
                continue
            self._prev_finished.add(jid)
            meta = self._meta.get(jid)
            if meta is None or meta.get("rec"):
                continue   # i giri programmati notificano da _update_recurring
            ok = bool(status.get("success"))
            text = (tr("{mode} completato: {src} → {dst}") if ok
                    else tr("{mode} in errore: {src} → {dst}"))
            self.job_finished.emit(text.format(
                mode=_mode(meta.get("mode", ""), tr("Trasferimento")),
                src=meta.get("src", "?"), dst=meta.get("dst", "?")), ok)

    def on_worker_error(self, message: str) -> None:
        self.lbl_agg.setText(tr("⚠ rcd non raggiungibile ({error})").format(error=message))

    def _update_agg(self, snap: dict) -> None:
        jobs = snap.get("jobs", {})
        active = sum(1 for p in jobs.values() if not p["status"].get("finished"))
        failed = sum(1 for p in jobs.values()
                     if p["status"].get("finished") and not p["status"].get("success"))
        speed = human_speed(snap.get("agg", {}).get("speed")) if active else "—"
        self.lbl_agg.setText(
            tr("⇅ {speed}   ·   {active} job attivi   ·   falliti: {failed}").format(
                speed=speed, active=active, failed=failed))

    # ------------------------------------------------------------------ tabella

    def _update_tree(self, snap: dict) -> None:
        for jid in sorted(snap.get("jobs", {})):
            if jid in self._dismissed:
                continue   # tolto dall'utente con «Rimuovi completati»
            if jid in self._rec_of_jid or self._meta.get(jid, {}).get("rec"):
                continue   # i giri dei programmati ⏰ si dipingono sulla loro riga
            self._update_row(jid, snap["jobs"][jid])

    def _make_row(self, jid: int) -> tuple[QtWidgets.QTreeWidgetItem,
                                           QtWidgets.QProgressBar]:
        entry = self._rows.get(jid)
        if entry is not None:
            return entry
        item = QtWidgets.QTreeWidgetItem()
        self.tree.addTopLevelItem(item)
        bar = QtWidgets.QProgressBar()
        bar.setRange(0, 1000)
        bar.setTextVisible(True)
        bar.setFormat("%p%")
        item.setSizeHint(5, QtCore.QSize(0, 24))
        self.tree.setItemWidget(item, 5, bar)
        self._rows[jid] = (item, bar)
        return item, bar

    def _update_row(self, jid: int, payload: dict) -> None:
        status = payload.get("status") or {}
        stats = payload.get("stats") or {}
        meta = self._meta.get(jid, {})
        item, bar = self._make_row(jid)
        item.setText(0, str(jid))
        item.setData(0, _ROLE_JID, jid)
        if meta.get("backup_dir"):
            item.setData(0, _ROLE_BACKUP, meta["backup_dir"])
        self._paint_state(item, bar, meta, status, stats)

    def _paint_state(self, item: QtWidgets.QTreeWidgetItem,
                     bar: QtWidgets.QProgressBar, meta: dict,
                     status: dict, stats: dict) -> None:
        """Colonne 1–8 della riga, comuni a job normali e giri programmati."""
        item.setText(1, _mode(meta.get("mode", ""), "—"))
        item.setText(2, meta.get("src", "—"))
        item.setText(3, meta.get("dst", "—"))
        item.setToolTip(2, meta.get("src", ""))
        item.setToolTip(3, meta.get("dst", ""))

        finished = bool(status.get("finished"))
        success = bool(status.get("success"))
        error = status.get("error") or ""

        if finished and success:
            state, color = tr("✓ Completato"), _GREEN
        elif finished and "context canceled" in error:
            state, color = tr("■ Annullato"), _GRAY
        elif finished:
            state, color = tr("✕ Errore"), _RED
        elif stats.get("totalBytes"):
            state, color = tr("⇅ In corso"), _BLUE
        else:
            state, color = tr("… Preparazione"), _BLUE

        item.setText(4, state)
        item.setForeground(4, color)
        item.setToolTip(4, error or state)

        bytes_done = stats.get("bytes") or 0
        total = stats.get("totalBytes") or 0
        if total:
            bar.setValue(min(1000, int(bytes_done * 1000 / total)))
        elif finished and success:
            bar.setValue(1000)
        elif finished:
            bar.setValue(bar.value())  # lascia l'ultimo valore noto
        else:
            bar.setValue(0)
        # barra rossa per gli errori, colore normale altrimenti
        bar.setStyleSheet("QProgressBar::chunk { background: #d05a5a; }"
                          if finished and not success else "")

        if finished:
            item.setText(6, "—")
            item.setText(7, "—")
            item.setText(8, f"{human_size(bytes_done)} / {human_size(total)}"
                            f"  ({fmt_duration(status.get('duration'))})")
        else:
            item.setText(6, human_speed(stats.get("speed")))
            item.setText(7, fmt_eta(stats.get("eta")))
            item.setText(8, f"{human_size(bytes_done)} / {human_size(total)}")

        # abilitazione annulla
        if self.tree.currentItem() is item:
            self.btn_stop.setEnabled(not finished)

    # --------------------------------------------------- trasferimenti ripetuti

    def add_recurring(self, mode: str, src: str, dst: str,
                      exclude: list[str] | None, interval_sec: int,
                      backup_dir: str | None = None) -> str:
        """Registra una programmazione ⏰ (il primo giro parte dal prossimo tick)."""
        def_id = f"rec-{self._rec_next_id}"
        self._rec_next_id += 1
        self._recurrent[def_id] = {
            "mode": mode, "src": src, "dst": dst,
            "exclude": list(exclude or []), "interval": int(interval_sec),
            "backup_dir": backup_dir or "",
            "enabled": True, "last_start": None,
            "last_status": None, "last_error": "", "current_jid": None,
        }
        self._new_rec_row(def_id, self._recurrent[def_id])
        self._save_recurring()
        return def_id

    def update_recurring(self, def_id: str, mode: str, src: str, dst: str,
                         exclude: list[str] | None, interval_sec: int,
                         backup_dir: str | None = None) -> bool:
        """Modifica una programmazione ⏰; True se un giro è in corso.

        Stato (attiva/in pausa), ultimo avvio ed esito vengono conservati:
        il prossimo giro parte da ultimo avvio + nuovo intervallo.
        """
        d = self._recurrent.get(def_id)
        if d is None:
            return False
        d.update({"mode": mode, "src": src, "dst": dst,
                  "exclude": list(exclude or []),
                  "interval": max(60, int(interval_sec)),
                  "backup_dir": backup_dir or ""})
        item = self._rec_item.get(def_id)
        running = d.get("current_jid") is not None
        if item is not None:
            item.setData(0, _ROLE_BACKUP, d["backup_dir"] or None)
            if not running:   # il giro in corso mostra ancora i suoi percorsi
                self._paint_rec_paths(item, d)
                self._paint_rec_idle(def_id, d)
        self._save_recurring()
        self._update_files()
        return running

    def _paint_rec_paths(self, item: QtWidgets.QTreeWidgetItem, d: dict) -> None:
        item.setText(1, _mode(d["mode"]))
        item.setText(2, d["src"])
        item.setText(3, d["dst"])
        item.setToolTip(2, d["src"])
        item.setToolTip(3, d["dst"])

    def _edit_recurring(self, def_id: str) -> None:
        d = self._recurrent.get(def_id)
        if d is not None:
            TransferDialog(self.ctx, self, self, schedule=d, def_id=def_id).exec()

    def _load_recurring(self) -> None:
        try:
            data = json.loads(_rec_path().read_text())
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            return   # file estraneo o corrotto: si riparte da zero
        for d in data.get("definitions") or []:
            if not isinstance(d, dict):
                continue
            def_id = str(d.get("id") or "")
            if not def_id.startswith("rec-") or not def_id[4:].isdigit():
                continue
            self._recurrent[def_id] = {
                "mode": d.get("mode", "copy"), "src": d.get("src", ""),
                "dst": d.get("dst", ""), "exclude": d.get("exclude") or [],
                "interval": max(60, int(d.get("interval") or 3600)),
                "backup_dir": d.get("backup_dir", ""),
                "enabled": bool(d.get("enabled", True)),
                "last_start": d.get("last_start"),
                "last_status": d.get("last_status"),
                "last_error": d.get("last_error", ""),
                "current_jid": None,   # il rcd è nuovo: nessun giro in corso
            }
        if self._recurrent:
            self._rec_next_id = max(int(k.rsplit("-", 1)[-1])
                                    for k in self._recurrent) + 1
        for def_id, d in self._recurrent.items():
            self._new_rec_row(def_id, d)

    def _save_recurring(self) -> None:
        keys = ("mode", "src", "dst", "exclude", "interval", "backup_dir",
                "enabled", "last_start", "last_status", "last_error")
        data = {"next_id": self._rec_next_id,
                "definitions": [{"id": k, **{f: d[f] for f in keys}}
                                for k, d in self._recurrent.items()]}
        try:
            path = _rec_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        except OSError:
            pass

    def _new_rec_row(self, def_id: str, d: dict) -> None:
        item = QtWidgets.QTreeWidgetItem()
        self._paint_rec_paths(item, d)
        item.setToolTip(4, tr("Programmazione: doppio clic per modificarla; tasto "
                           "destro per avviare ora, modificare, mettere in "
                           "pausa o rimuovere."))
        bar = QtWidgets.QProgressBar()
        bar.setRange(0, 1000)
        bar.setFormat("%p%")
        item.setSizeHint(5, QtCore.QSize(0, 24))
        self.tree.addTopLevelItem(item)
        self.tree.setItemWidget(item, 5, bar)
        item.setData(0, _ROLE_REC, def_id)
        if d.get("backup_dir"):
            item.setData(0, _ROLE_BACKUP, d["backup_dir"])
        self._rec_item[def_id] = item
        self._rec_bars[def_id] = bar
        self._paint_rec_idle(def_id, d)

    def _paint_rec_idle(self, def_id: str, d: dict) -> None:
        item = self._rec_item.get(def_id)
        if item is None:
            return
        enabled = d.get("enabled", True)
        if not enabled:
            stato = tr("⏸ In pausa")
        elif d.get("last_start") is None:
            stato = tr("⏰ Primo avvio tra poco…")
        else:
            left = max(0.0, d["last_start"] + d["interval"] - time.time())
            stato = tr("⏰ Prossimo giro tra {time}").format(time=fmt_eta(left))
        last = d.get("last_status")
        if last == "ok":
            stato += "  ·  " + tr("ultimo: ✓")
        elif last == "cancel":
            stato += "  ·  " + tr("ultimo: ■ annullato")
        elif last == "err":
            stato += "  ·  " + tr("ultimo: ✕ {error}").format(
                error=d.get("last_error", "")[:60])
        item.setText(0, "⏰")
        item.setData(0, _ROLE_JID, None)
        item.setText(4, stato)
        item.setForeground(4, _GRAY if not enabled else _BLUE)
        self._rec_bars[def_id].setValue(0)

    def _on_rec_tick(self) -> None:
        now = time.time()
        for def_id, d in self._recurrent.items():
            if d.get("current_jid") is not None:
                continue   # un giro è in corso: lo aggiorna lo snapshot
            self._paint_rec_idle(def_id, d)
            run_now = d.pop("run_now", False)   # «Avvia ora», anche se in pausa
            if not run_now:
                if not d.get("enabled", True):
                    continue
                if (d.get("last_start") is not None
                        and now - d["last_start"] < d["interval"]):
                    continue
            try:
                jid = self.ctx.api.start_transfer(d["mode"], d["src"], d["dst"],
                                                  exclude=d.get("exclude") or None,
                                                  backup_dir=d.get("backup_dir") or None)
            except ApiError as exc:
                d["last_start"] = now   # riprova al prossimo intervallo
                d["last_status"], d["last_error"] = "err", str(exc)
                self._save_recurring()
                continue
            d["current_jid"] = jid
            d["last_start"] = now
            self._meta[jid] = {"mode": d["mode"], "src": d["src"],
                               "dst": d["dst"], "rec": def_id,
                               "exclude": d.get("exclude") or [],
                               "backup_dir": d.get("backup_dir") or ""}
            self.job_started.emit(jid)   # registra il job nella watch-list
            self._rec_of_jid[jid] = def_id
            item = self._rec_item.get(def_id)
            if item is not None:
                item.setText(0, f"#{jid}")
                item.setData(0, _ROLE_JID, jid)
            self._save_recurring()

    def _update_recurring(self, snap: dict) -> None:
        for jid, def_id in list(self._rec_of_jid.items()):
            d = self._recurrent.get(def_id)
            item = self._rec_item.get(def_id)
            if d is None or item is None:
                self._rec_of_jid.pop(jid, None)
                continue
            payload = (snap.get("jobs") or {}).get(jid)
            if not payload:
                continue
            status = payload.get("status") or {}
            self._paint_state(item, self._rec_bars[def_id],
                              self._meta.get(jid, {}),
                              status, payload.get("stats") or {})
            item.setText(0, f"#{jid}")
            item.setData(0, _ROLE_JID, jid)
            if status.get("finished"):
                err = status.get("error") or ""
                if status.get("success"):
                    d["last_status"], d["last_error"] = "ok", ""
                elif "context canceled" in err:
                    d["last_status"], d["last_error"] = "cancel", ""
                else:
                    d["last_status"], d["last_error"] = "err", err
                d["current_jid"] = None
                self._paint_rec_paths(item, d)
                self._rec_of_jid.pop(jid, None)
                self._dismissed.add(jid)
                self.job_dismissed.emit(jid)
                self._save_recurring()
                ok = d["last_status"] == "ok"
                text = (tr("Programmato {mode} completato: {src} → {dst}") if ok
                        else tr("Programmato {mode} annullato: {src} → {dst}")
                        if d["last_status"] == "cancel"
                        else tr("Programmato {mode} in errore: {src} → {dst}"))
                self.job_finished.emit(text.format(
                    mode=_mode(d["mode"], ""), src=d["src"], dst=d["dst"]), ok)

    def _context_menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        if item is None:
            return
        def_id = item.data(0, _ROLE_REC)
        backup = item.data(0, _ROLE_BACKUP)
        is_rec = bool(def_id) and def_id in self._recurrent
        if not is_rec and not backup:
            return
        menu = QtWidgets.QMenu(self)
        act_run = act_edit = act_pause = act_del = None
        if is_rec:
            d = self._recurrent[def_id]
            act_run = menu.addAction(tr("▶ Avvia ora"))
            act_edit = menu.addAction(tr("✏ Modifica…"))
            act_pause = menu.addAction(tr("⏸ Metti in pausa") if d.get("enabled", True)
                                       else tr("▶ Riattiva"))
            menu.addSeparator()
            act_del = menu.addAction(tr("🗑 Rimuovi programmazione"))
            menu.addSeparator()
        act_open = menu.addAction(tr("📂 Apri cestino")) if backup else None
        chosen = menu.exec(self.tree.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        if chosen is act_open:
            self._open_trash(backup)
        elif is_rec:
            d = self._recurrent[def_id]
            if chosen is act_edit:
                self._edit_recurring(def_id)
            elif chosen is act_run and d.get("current_jid") is None:
                d["run_now"] = True   # parte al prossimo tick, anche se in pausa
            elif chosen is act_pause:
                d["enabled"] = not d.get("enabled", True)
                self._save_recurring()
            elif chosen is act_del:
                self._remove_recurring(def_id)

    def _on_double_click(self, item: QtWidgets.QTreeWidgetItem, _col: int) -> None:
        def_id = item.data(0, _ROLE_REC)
        if def_id and def_id in self._recurrent:
            self._edit_recurring(def_id)

    def _remove_recurring(self, def_id: str) -> None:
        answer = QtWidgets.QMessageBox.question(
            self, tr("Rimuovere la programmazione?"),
            tr("Rimuovere il giro automatico? I file già sincronizzati "
            "restano dove sono."),
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.No)
        if answer != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        self._recurrent.pop(def_id, None)
        for jid in [j for j, dd in self._rec_of_jid.items() if dd == def_id]:
            self._rec_of_jid.pop(jid, None)
        removed = self._rec_item.pop(def_id, None)
        if removed is not None:
            index = self.tree.indexOfTopLevelItem(removed)
            if index >= 0:
                self.tree.takeTopLevelItem(index)
        self._rec_bars.pop(def_id, None)
        self._save_recurring()

    def _on_open_trash(self) -> None:
        item = self.tree.currentItem()
        backup = item.data(0, _ROLE_BACKUP) if item else None
        if backup:
            self._open_trash(backup)

    def _open_trash(self, backup_dir: str) -> None:
        TrashDialog(self.ctx, backup_dir, self).exec()

    # ------------------------------------------------------------------ file

    def _update_files(self) -> None:
        self.files.clear()
        item = self.tree.currentItem()
        backup = item.data(0, _ROLE_BACKUP) if item else None
        self.btn_trash.setEnabled(bool(backup))
        if item is None:
            self.btn_stop.setEnabled(False)
            return
        jid = item.data(0, _ROLE_JID)
        if jid is None:
            self.btn_stop.setEnabled(False)
            return
        self.btn_stop.setEnabled(
            not (self._last or {}).get("jobs", {}).get(jid, {}).get("status", {})
            .get("finished", False))
        payload = (self._last or {}).get("jobs", {}).get(jid)
        transferring = ((payload or {}).get("stats") or {}).get("transferring") or []
        for tf in transferring:
            row = QtWidgets.QTreeWidgetItem([
                str(tf.get("name", "?")),
                f"{human_size(tf.get('bytes'))} ({tf.get('percentage', '?')}%)",
                human_size(tf.get("size")),
                human_speed(tf.get("speedAvg") or tf.get("speed")),
            ])
            self.files.addTopLevelItem(row)

    # ---------------------------------------------------------------- azioni

    def _on_stop(self) -> None:
        item = self.tree.currentItem()
        if item is None:
            return
        jid = item.data(0, _ROLE_JID)
        if jid is None:
            return
        answer = QtWidgets.QMessageBox.question(
            self, tr("Annullare il trasferimento?"),
            tr("Annullare il job #{job}? I file già trasferiti restano dove sono.").format(
                job=jid),
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.No)
        if answer != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        try:
            self.ctx.api.stop_job(jid)
        except ApiError as exc:
            QtWidgets.QMessageBox.critical(self, tr("Annullamento fallito"), str(exc))

    def _on_clear(self) -> None:
        for jid, (item, _bar) in list(self._rows.items()):
            payload = (self._last or {}).get("jobs", {}).get(jid) or {}
            finished = payload.get("status", {}).get("finished")
            dry_done = item.data(4, QtCore.Qt.ItemDataRole.UserRole) is True
            if finished or dry_done:
                index = self.tree.indexOfTopLevelItem(item)
                if index >= 0:
                    self.tree.takeTopLevelItem(index)
                del self._rows[jid]
                if isinstance(jid, int):   # le prove hanno chiavi «dry-N»
                    self._dismissed.add(jid)
                    self._meta.pop(jid, None)
                    self.job_dismissed.emit(jid)
        self._update_files()
