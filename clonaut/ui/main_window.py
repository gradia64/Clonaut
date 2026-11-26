"""Finestra principale: tab, polling, tray, menu, impostazioni, status bar."""

from __future__ import annotations

import html
import os
import platform

from .. import __version__
from .. import settings as app_settings
from .. import updates
from ..appctx import AppContext
from ..i18n import tr
from ..qtcompat import BINDING, QtCore, QtGui, QtWidgets
from ..util import app_icon, esc
from ..worker import POLL_TIMEOUT, CallWorker, PollWorker, stop_thread
from .remotes_tab import RemotesTab
from .settings_dialog import SettingsDialog
from .transfers_tab import TransfersTab


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, ctx: AppContext, settings: dict | None = None):
        super().__init__()
        self.ctx = ctx
        self.settings = settings or app_settings.load()
        self._quitting = False
        self._shut_down = False   # worker e demoni già fermati da closeEvent
        self.setWindowTitle(f"Clonaut {__version__}")
        self.setWindowIcon(app_icon())
        self.resize(1150, 720)

        # -- contenuti
        self.remotes_tab = RemotesTab(ctx)
        self.transfers_tab = TransfersTab(ctx)
        self.remotes_tab.schedules_using = self.transfers_tab.schedules_using_remote
        tabs = QtWidgets.QTabWidget()
        tabs.addTab(self.remotes_tab, tr("Remote"))
        tabs.addTab(self.transfers_tab, tr("Trasferimenti"))
        self.setCentralWidget(tabs)

        # -- menu
        menu = self.menuBar().addMenu(tr("&File"))
        act_settings = QtGui.QAction(tr("⚙ Impostazioni…"), self)
        act_settings.triggered.connect(self._open_settings)
        act_quit = QtGui.QAction(tr("Esci"), self)
        act_quit.triggered.connect(self.quit)
        menu.addAction(act_settings)
        menu.addSeparator()
        menu.addAction(act_quit)

        help_menu = self.menuBar().addMenu(tr("&Aiuto"))
        act_about = QtGui.QAction(tr("Informazioni su Clonaut…"), self)
        act_about.triggered.connect(self._show_about)
        act_about_qt = QtGui.QAction(tr("Informazioni su Qt…"), self)
        act_about_qt.triggered.connect(QtWidgets.QApplication.aboutQt)
        act_updates = QtGui.QAction(tr("Controlla aggiornamenti…"), self)
        act_updates.triggered.connect(self.check_updates_now)
        help_menu.addAction(act_updates)
        help_menu.addSeparator()
        help_menu.addAction(act_about)
        help_menu.addAction(act_about_qt)

        # -- status bar
        self._status_lbl = QtWidgets.QLabel()
        self.statusBar().addWidget(self._status_lbl)
        self._set_status(ok=True)
        # avviso di una nuova versione, a destra; nascosto finché non serve
        self._update_lbl = QtWidgets.QLabel()
        self._update_lbl.setTextFormat(QtCore.Qt.TextFormat.RichText)
        self._update_lbl.linkActivated.connect(self._on_update_link)
        self._update_lbl.hide()
        self.statusBar().addPermanentWidget(self._update_lbl)
        self._update_worker: CallWorker | None = None
        self._update_release: updates.Release | None = None
        self._update_timer = QtCore.QTimer(self)
        self._update_timer.setInterval(updates.CHECK_EVERY_MS)
        self._update_timer.timeout.connect(self._auto_check_updates)
        if updates.enabled_by_env():
            self._update_timer.start()
            QtCore.QTimer.singleShot(updates.FIRST_CHECK_MS, self._auto_check_updates)

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
        act_show = menu.addAction(tr("Mostra / Nascondi"))
        act_show.triggered.connect(self._toggle_visible)
        menu.addSeparator()
        act_quit = menu.addAction(tr("Esci"))
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
        dlg = SettingsDialog(self.settings, self, rclone_in_use=self.rclone_desc())
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            # il dialogo non mostra tutto (es. la versione saltata): si unisce
            self.settings = {**self.settings, **dlg.values()}
            app_settings.save(self.settings)

    def rclone_desc(self) -> str:
        """Percorso dell'eseguibile rclone in uso, con la sua origine."""
        exe = getattr(self.ctx, "rclone_exe", None)
        if not exe:
            return ""
        home = os.path.expanduser("~")
        source = getattr(self.ctx, "rclone_source", "")
        return exe.replace(home, "~", 1) + (f" ({source})" if source else "")

    def about_text(self) -> str:
        """Testo (HTML) della finestra «Informazioni su Clonaut»."""
        home = os.path.expanduser("~")
        cfg = str(app_settings.config_dir()).replace(home, "~", 1)
        rclone = self.ctx.version or "?"
        if self.rclone_desc():
            rclone += f" — {self.rclone_desc()}"
        rows = (("rclone", rclone),
                ("Qt", f"{QtCore.qVersion()} ({BINDING})"),
                ("Python", platform.python_version()),
                ("Config", self.ctx.config_desc),
                (tr("Dati app"), cfg))
        # percorsi e descrizioni possono contenere «<» o «&»: testo, non HTML
        table = "".join(
            f"<tr><td style='white-space:nowrap; padding-right:10px'><b>{html.escape(k)}</b>"
            f"</td><td>{html.escape(str(v))}</td></tr>" for k, v in rows)
        return (
            f"<h2 style='margin-bottom:0'>Clonaut {__version__}</h2>"
            "<p style='margin-top:2px'><i>" + tr("Il pilota grafico per rclone.")
            + "</i></p><p>" + tr(
                "Interfaccia desktop per <a href='https://rclone.org'>rclone</a>: "
                "remote, trasferimenti con progressi, prove a vuoto, cestino di "
                "sicurezza e programmazioni. Tutto il lavoro sui file lo fa rclone.")
            + f"</p><table cellspacing='0' cellpadding='2'>{table}</table><p>"
            + tr("Licenza")
            + " <a href='https://www.gnu.org/licenses/gpl-3.0.html'>GPL-3.0</a> "
            "· © 2026 Gradia<br>"
            "<a href='https://github.com/gradia64/Clonaut'>github.com/gradia64/Clonaut</a>"
            " · <a href='https://github.com/gradia64/Clonaut/issues'>"
            + tr("segnala un problema") + "</a></p>")

    def _show_about(self) -> None:
        QtWidgets.QMessageBox.about(self, tr("Informazioni su Clonaut"), self.about_text())

    # ---------------------------------------------------------- aggiornamenti

    def _auto_check_updates(self) -> None:
        if self.settings.get("check_updates") and not self._shut_down:
            self._start_update_check(manual=False)

    def check_updates_now(self) -> None:
        """«Aiuto → Controlla aggiornamenti…»: anche con il controllo spento."""
        self._start_update_check(manual=True)

    def _start_update_check(self, manual: bool) -> None:
        if self._update_worker is not None:
            return   # già in corso
        # chiesto a mano mostra anche una versione saltata
        skip = "" if manual else str(self.settings.get("skip_version") or "")
        worker = CallWorker(manual, updates.check, skip)
        worker.succeeded.connect(self._on_update_checked)
        worker.failed.connect(self._on_update_failed)
        worker.finished.connect(self._release_update_worker)
        self._update_worker = worker
        worker.start()

    def _release_update_worker(self) -> None:
        self._update_worker = None

    def _on_update_checked(self, manual, release) -> None:
        if release is None:
            if manual:
                QtWidgets.QMessageBox.information(
                    self, tr("Aggiornamenti"),
                    tr("Clonaut {version} è la versione più recente.").format(
                        version=__version__))
            return
        self._show_update(release)
        if manual:
            QtWidgets.QMessageBox.information(
                self, tr("Aggiornamenti"), self._update_message(release))

    def _on_update_failed(self, manual, message: str) -> None:
        if manual:   # il controllo automatico fallisce in silenzio (es. offline)
            QtWidgets.QMessageBox.warning(
                self, tr("Aggiornamenti"),
                esc(tr("Controllo non riuscito.") + "\n\n" + message))

    def _update_message(self, release: "updates.Release") -> str:
        """Testo (HTML) dell'avviso: versione, link alle note e come aggiornare."""
        return ("<p>" + tr("È disponibile Clonaut {new} (ora usi la {current}).").format(
                    new=html.escape(release.version), current=__version__)
                + f" <a href='{html.escape(release.url, quote=True)}'>"
                + tr("Novità della versione") + "</a></p><p>"
                + html.escape(updates.how_to_update(updates.install_method())) + "</p>")

    def _show_update(self, release: "updates.Release") -> None:
        first = self._update_release is None or self._update_release != release
        self._update_release = release
        self._update_lbl.setText(
            "⬆ <a href='open'>" + html.escape(
                tr("Clonaut {version} disponibile").format(version=release.version))
            + "</a> · <a href='skip'>" + tr("Salta questa versione")
            + "</a> · <a href='off'>" + tr("Non controllare più") + "</a>")
        self._update_lbl.setToolTip(updates.how_to_update(updates.install_method()))
        self._update_lbl.show()
        if first and self.tray is not None and self.settings.get("notify_finished"):
            self.tray.showMessage(
                "Clonaut", tr("È disponibile Clonaut {version}.").format(
                    version=release.version),
                QtWidgets.QSystemTrayIcon.MessageIcon.Information, 8000)

    def _on_update_link(self, link: str) -> None:
        release = self._update_release
        if release is None:
            return
        if link == "open":
            QtGui.QDesktopServices.openUrl(QtCore.QUrl(release.url))
            return
        if link == "skip":
            self.settings["skip_version"] = release.version
        elif link == "off":
            self.settings["check_updates"] = False
        app_settings.save(self.settings)
        self._update_lbl.hide()
        self._update_release = None

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
                tr("{n} trasferimenti attivi").format(n=active) if active
                else tr("nessun trasferimento attivo")))

    def _on_job_finished(self, title: str, ok: bool) -> None:
        if self.tray is not None and self.settings.get("notify_finished"):
            icon = (QtWidgets.QSystemTrayIcon.MessageIcon.Information if ok
                    else QtWidgets.QSystemTrayIcon.MessageIcon.Critical)
            self.tray.showMessage("Clonaut", title, icon, 6000)

    def _set_status(self, ok: bool) -> None:
        if ok:
            dot, extra = "#1a7f37", self.ctx.version
        else:
            dot, extra = "#c62828", tr("in attesa di rclone rcd…")
        self._status_lbl.setText(
            f'<span style="color:{dot}; font-weight:600">●</span> '
            + tr("rclone {version} · rcd su {url} · config: {config}").format(
                version=html.escape(str(extra)), url=html.escape(self.ctx.api.url),
                config=html.escape(str(self.ctx.config_desc))))

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
        if self._shut_down:
            # seconda chiusura (es. «Esci» dopo la X): worker e demoni sono
            # già fermi, rifermarli con PySide6 6.12 può andare in segfault
            super().closeEvent(event)
            event.accept()
            return
        self._shut_down = True
        self._update_timer.stop()
        threads = [self.worker, *self.transfers_tab.background_threads()]
        if self._update_worker is not None:
            threads.append(self._update_worker)
        for thread in threads:
            thread.stop()
        # di solito il thread è in pausa tra due tick e finisce subito; se è
        # dentro una chiamata rc, fermare i demoni locali la fa fallire al
        # volo, altrimenti (demone esterno) scade al più in POLL_TIMEOUT
        self.worker.wait(500)
        if self.ctx.rcd is not None:
            self.ctx.rcd.stop()
        if self.ctx.rcd_dry is not None:
            self.ctx.rcd_dry.stop()
        for thread in threads:
            # se non basta, il thread non viene distrutto mentre gira:
            # app.main lo aspetta dopo la fine del ciclo degli eventi
            stop_thread(thread, int((POLL_TIMEOUT + 1) * 1000))
        super().closeEvent(event)
        event.accept()
        # senza demone l'app non serve più: si esce anche se l'icona nella
        # tray (KDE, Wayland) la terrebbe in vita come finestra senza backend
        QtWidgets.QApplication.quit()
