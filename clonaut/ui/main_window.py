"""Finestra principale: tab, polling, tray, menu, impostazioni, status bar."""

from __future__ import annotations

from .. import settings as app_settings
from ..appctx import AppContext
from ..qtcompat import QtCore, QtGui, QtWidgets
from ..util import app_icon
from ..worker import PollWorker
from .remotes_tab import RemotesTab
from .settings_dialog import SettingsDialog
from .transfers_tab import TransfersTab


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, ctx: AppContext, settings: dict | None = None):
        super().__init__()
        self.ctx = ctx
        self.settings = settings or app_settings.load()
        self._quitting = False
        self.setWindowTitle("Clonaut")
        self.setWindowIcon(app_icon())
        self.resize(1150, 720)

        # -- contenuti
        self.remotes_tab = RemotesTab(ctx)
        self.transfers_tab = TransfersTab(ctx)
        tabs = QtWidgets.QTabWidget()
        tabs.addTab(self.remotes_tab, "Remote")
        tabs.addTab(self.transfers_tab, "Trasferimenti")
        self.setCentralWidget(tabs)

        # -- menu
        menu = self.menuBar().addMenu("&File")
        act_settings = QtGui.QAction("⚙ Impostazioni…", self)
        act_settings.triggered.connect(self._open_settings)
        act_quit = QtGui.QAction("Esci", self)
        act_quit.triggered.connect(self.quit)
        menu.addAction(act_settings)
        menu.addAction(act_quit)

        # -- status bar
        self._status_lbl = QtWidgets.QLabel()
        self.statusBar().addWidget(self._status_lbl)
        self._set_status(ok=True)

        # -- polling
        self.worker = PollWorker(ctx.api)
        self.transfers_tab.job_started.connect(self.worker.register)
        self.transfers_tab.job_dismissed.connect(self.worker.forget)
        self.worker.ready.connect(self.transfers_tab.on_snapshot)
        self.worker.ready.connect(self._on_snapshot)
        self.worker.failed.connect(self.transfers_tab.on_worker_error)
        self.worker.failed.connect(lambda _msg: self._set_status(ok=False))
        self.worker.start()

        # -- tray
        self.transfers_tab.job_finished.connect(self._on_job_finished)
        self.tray = None
        self._setup_tray()

    # ------------------------------------------------------------- menu/tray

    def _setup_tray(self, force: bool = False) -> None:
        """Crea l'icona nella tray (se l'ambiente la supporta, o forzato nei test)."""
        self.tray = None
        if not force and not QtWidgets.QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QtWidgets.QSystemTrayIcon(app_icon(), self)
        self.tray.setToolTip("Clonaut")
        menu = QtWidgets.QMenu(self)
        self._tray_menu = menu   # il tray non ne prende possesso: teniamo il riferimento
        act_show = menu.addAction("Mostra / Nascondi")
        act_show.triggered.connect(self._toggle_visible)
        menu.addSeparator()
        act_quit = menu.addAction("Esci")
        act_quit.triggered.connect(self.quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _on_tray_activated(self, reason) -> None:
        reasons = QtWidgets.QSystemTrayIcon.ActivationReason
        if reason == reasons.Trigger:
            # clic sinistro: porta in primo piano, o nasconde se lo è già
            if self.isVisible() and not self.isMinimized() and self.isActiveWindow():
                self.hide()
            else:
                self._bring_to_front()
        elif reason == reasons.DoubleClick:
            # alcuni ambienti inviano anche Trigger: il doppio clic mostra soltanto,
            # così non si ottiene un «mostra e subito nascondi»
            self._bring_to_front()

    def _bring_to_front(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _toggle_visible(self) -> None:
        if self.isVisible() and not self.isMinimized():
            self.hide()
        else:
            self._bring_to_front()

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self.settings, self)
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            self.settings = dlg.values()
            app_settings.save(self.settings)

    def quit(self) -> None:
        """Uscita vera (dal menu File o dalla tray): ferma worker e rcd."""
        self._quitting = True
        self.close()
        # con la finestra nascosta nella tray, close() non fa scattare
        # «ultima finestra chiusa»: l'uscita va chiesta esplicitamente
        QtWidgets.QApplication.quit()

    # ------------------------------------------------------------- slot worker

    def _on_snapshot(self, snap: dict) -> None:
        self._set_status(ok=True)
        active = sum(1 for p in snap.get("jobs", {}).values()
                     if not p["status"].get("finished"))
        if self.tray is not None:
            self.tray.setToolTip("Clonaut · " + (
                f"{active} trasferimenti attivi" if active
                else "nessun trasferimento attivo"))

    def _on_job_finished(self, title: str, ok: bool) -> None:
        if self.tray is not None and self.settings.get("notify_finished"):
            icon = (QtWidgets.QSystemTrayIcon.MessageIcon.Information if ok
                    else QtWidgets.QSystemTrayIcon.MessageIcon.Critical)
            self.tray.showMessage("Clonaut", title, icon, 6000)

    def _set_status(self, ok: bool) -> None:
        if ok:
            dot, extra = "#1a7f37", self.ctx.version
        else:
            dot, extra = "#c62828", "in attesa di rclone rcd…"
        self._status_lbl.setText(
            f'<span style="color:{dot}; font-weight:600">●</span> '
            f"rclone {extra} · rcd su {self.ctx.api.url} · "
            f"config: {self.ctx.config_desc}")

    # ------------------------------------------------------------- chiusura

    def changeEvent(self, event) -> None:  # noqa: N802 — API Qt
        super().changeEvent(event)
        if (event.type() == QtCore.QEvent.Type.WindowStateChange
                and self.isMinimized()
                and self.settings.get("minimize_to_tray")
                and self.tray is not None):
            self.hide()   # scompare dalla barra: si riapre dalla tray

    def closeEvent(self, event) -> None:  # noqa: N802 — API Qt
        if (not self._quitting
                and self.settings.get("close_to_tray")
                and self.tray is not None):
            event.ignore()
            self.hide()   # continua a lavorare nella tray
            return
        self.worker.stop()
        self.worker.wait(2500)
        for dry in list(self.transfers_tab.dry_workers()):
            dry.stop()
            dry.wait(1500)
        if self.ctx.rcd is not None:
            self.ctx.rcd.stop()
        if self.ctx.rcd_dry is not None:
            self.ctx.rcd_dry.stop()
        super().closeEvent(event)
        event.accept()
