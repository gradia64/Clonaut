"""Avvio di Clonaut: argomenti da riga di comando, QApplication, demone rclone.

È il punto d'ingresso del comando `clonaut` (vedi pyproject.toml), di
`python -m clonaut` e del vecchio `main.py`.

Avvio normale (avvia da solo rclone rcd in locale):
    clonaut

Aggancio a un rclone rcd già in esecuzione:
    CLONAUT_RC_PASS=segreta clonaut --url http://127.0.0.1:5572 --user utente

La password dell'API rc arriva dalla variabile CLONAUT_RC_PASS o, da
terminale, viene chiesta a schermo. `--password` resta accettata, ma sulla
riga di comando è leggibile da ogni utente con `ps`.
"""

from __future__ import annotations

import argparse
import gc
import getpass
import os
import sys

from clonaut.api import RcloneApi
from clonaut.appctx import AppContext
from clonaut import i18n
from clonaut.i18n import tr
from clonaut.qtcompat import QtCore, QtWidgets
from clonaut import settings as app_settings
from clonaut.rcd import RcdStartError, find_rclone, launch_rcd
from clonaut.ui.main_window import MainWindow
from clonaut.util import esc


def collect_garbage_in_main_thread(app: QtWidgets.QApplication,
                                   interval_ms: int = 2000) -> QtCore.QTimer:
    """Il garbage collector di Python gira solo nel thread della GUI.

    Automatico, partirebbe in qualunque thread che alloca (il polling, le
    prove a vuoto): se lì raccoglie un dialogo chiuso, PySide6 6.12.0 ne
    rimanda la cancellazione al thread principale e va in segfault
    (Shiboken::BindingManager::runDeletionInMainThread). Spento e richiamato
    da un timer della GUI, raccoglie sempre nel thread giusto.
    """
    gc.disable()
    timer = QtCore.QTimer(app)
    timer.setInterval(interval_ms)
    timer.timeout.connect(gc.collect)
    timer.start()
    return timer


def make_app() -> QtWidgets.QApplication:
    """Crea la QApplication con stile, foglio di stile e icona dell'app."""
    # argv[0] determina il WM_CLASS su X11: deve coincidere con StartupWMClass
    app = QtWidgets.QApplication(["clonaut"])
    app.setApplicationName("Clonaut")
    app.setDesktopFileName("io.github.gradia64.Clonaut")   # = nome del file .desktop
    app.setStyle("Fusion")
    from clonaut.util import APP_QSS, app_icon
    app.setStyleSheet(APP_QSS)
    app.setWindowIcon(app_icon())
    i18n.install_qt_translator(app)
    collect_garbage_in_main_thread(app)
    return app


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="clonaut", description=tr("Interfaccia grafica per rclone (rcd REST API)"))
    parser.add_argument("--url", help=tr("aggancia un rcd già avviato (es. http://127.0.0.1:5572)"))
    parser.add_argument("--user", default="", help=tr("utente per l'API rc"))
    parser.add_argument("--password", default="", help=tr(
        "password per l'API rc (visibile a ogni utente con `ps`: meglio la "
        "variabile CLONAUT_RC_PASS, oppure niente per digitarla)"))
    parser.add_argument("--config", help=tr("file di configurazione rclone da usare"))
    parser.add_argument("--port", type=int, help=tr("porta per il rcd locale (default: casuale)"))
    return parser.parse_args(argv)


RC_PASS_ENV = "CLONAUT_RC_PASS"


def _resolve_rc_password(args: argparse.Namespace) -> str:
    """Password rc per l'aggancio: variabile d'ambiente o prompt, non argv.

    Gli argomenti del processo sono leggibili da ogni utente con `ps` (per
    questo anche il rcd locale riceve le credenziali dall'ambiente, vedi
    rcd.py). Senza --password si usa CLONAUT_RC_PASS; se manca, da terminale
    la password viene chiesta a schermo.
    """
    if not args.url or not args.user:
        return args.password
    if args.password:
        print(tr("Attenzione: la password passata con --password è visibile a ogni "
                 "utente con `ps`; usa la variabile CLONAUT_RC_PASS."), file=sys.stderr)
        return args.password
    password = os.environ.get(RC_PASS_ENV, "")
    if password:
        return password
    if sys.stdin is not None and sys.stdin.isatty():
        return getpass.getpass(tr("Password per l'API rc:") + " ")
    raise RuntimeError(
        tr("Manca la password dell'API rc: indicala con la variabile d'ambiente "
           "CLONAUT_RC_PASS (quella sulla riga di comando è leggibile da ogni "
           "utente con `ps`)."))


def _build_context(args: argparse.Namespace, values: dict) -> AppContext:
    """Crea il contesto: o aggancia un rcd esistente o ne avvia uno locale."""
    exe, source, tried = find_rclone(values.get("rclone_path", ""))
    if args.url:
        api = RcloneApi(args.url, args.user, args.password)
        version = str(api.ping().get("version", "?")).lstrip("v")
        config_desc = tr("gestito dal rcd esterno")
        # rclone locale serve solo per le prove a vuoto: può anche mancare
        return AppContext(api=api, version=f"v{version}", config_desc=config_desc,
                          config_path=args.config, rclone_exe=exe,
                          rclone_source=source)

    if not exe:
        raise RuntimeError(
            tr("rclone non trovato. Fonti provate:") + "\n  • " + "\n  • ".join(tried)
            + "\n\n" + tr("Installalo (es. `sudo apt install rclone`, `sudo pacman -S "
                          "rclone` o da https://rclone.org), oppure indica il percorso con "
                          "la variabile CLONAUT_RCLONE."))

    try:
        rcd, api = launch_rcd(exe, port=args.port, config_path=args.config)
    except RcdStartError as exc:
        raise RuntimeError(
            tr("rclone rcd non si è avviato.") + "\n\n" + tr("Log recente:") + "\n"
            + str(exc)) from exc
    version = str(api.ping().get("version", "?")).lstrip("v")
    config_desc = args.config if args.config else tr("predefinito (~/.config/rclone/rclone.conf)")
    return AppContext(api=api, rcd=rcd, version=f"v{version}", config_desc=config_desc,
                      config_path=args.config, rclone_exe=exe, rclone_source=source)


def main(argv: list[str] | None = None) -> int:
    values = app_settings.load()
    i18n.setup(i18n.detect(values.get("language", "")))
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    # il prompt della password va chiesto prima che compaiano le finestre
    password_error: RuntimeError | None = None
    try:
        args.password = _resolve_rc_password(args)
    except RuntimeError as exc:
        password_error = exc

    app = make_app()

    # -- avvio del backend con finestra di attesa
    progress = QtWidgets.QProgressDialog()
    progress.setLabelText(tr("Avvio di rclone rcd…"))
    progress.setRange(0, 0)
    progress.setCancelButton(None)
    progress.setWindowFlag(QtCore.Qt.WindowType.WindowCloseButtonHint, False)
    progress.setMinimumDuration(0)
    progress.show()
    QtWidgets.QApplication.processEvents()

    try:
        if password_error is not None:
            raise password_error
        ctx = _build_context(args, values)
    except Exception as exc:  # noqa: BLE001 — errore di avvio mostrato all'utente
        progress.cancel()
        QtWidgets.QMessageBox.critical(None, tr("Avvio fallito"), esc(exc))
        return 1
    progress.cancel()

    win = MainWindow(ctx, settings=values)
    if values.get("start_in_tray") and win.tray is not None:
        pass   # resta ridotta nella tray (l'icona è già attiva)
    else:
        win.show()
    return app.exec()
