#!/usr/bin/env python3
"""Clonaut — interfaccia grafica per rclone tramite la sua REST API (`rclone rcd`).

Avvio normale (avvia da solo rclone rcd in locale):
    python3 main.py

Aggancio a un rclone rcd già in esecuzione:
    python3 main.py --url http://127.0.0.1:5572 --user utente --password segreta
"""

from __future__ import annotations

import argparse
import sys

from clonaut.api import RcloneApi
from clonaut.appctx import AppContext
from clonaut.qtcompat import QtCore, QtWidgets
from clonaut.rcd import RcdProcess, free_port, random_creds, which_rclone
from clonaut.ui.main_window import MainWindow


def make_app() -> QtWidgets.QApplication:
    """Crea la QApplication con stile, foglio di stile e icona dell'app."""
    # argv[0] determina il WM_CLASS su X11: deve coincidere con StartupWMClass
    app = QtWidgets.QApplication(["clonaut"])
    app.setApplicationName("Clonaut")
    app.setDesktopFileName("clonaut")   # associa la finestra al file .desktop
    app.setStyle("Fusion")
    from clonaut.util import APP_QSS, app_icon
    app.setStyleSheet(APP_QSS)
    app.setWindowIcon(app_icon())
    return app


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="clonaut", description="Interfaccia grafica per rclone (rcd REST API)")
    parser.add_argument("--url", help="aggancia un rcd già avviato (es. http://127.0.0.1:5572)")
    parser.add_argument("--user", default="", help="utente per l'API rc")
    parser.add_argument("--password", default="", help="password per l'API rc")
    parser.add_argument("--config", help="file di configurazione rclone da usare")
    parser.add_argument("--port", type=int, help="porta per il rcd locale (default: casuale)")
    return parser.parse_args(argv)


def _build_context(args: argparse.Namespace) -> AppContext:
    """Crea il contesto: o aggancia un rcd esistente o ne avvia uno locale."""
    if args.url:
        api = RcloneApi(args.url, args.user, args.password)
        version = api.ping().get("version", "?")
        config_desc = "gestito dal rcd esterno"
        return AppContext(api=api, version=f"v{version}", config_desc=config_desc,
                          config_path=args.config)

    exe = which_rclone()
    if not exe:
        raise RuntimeError(
            "rclone non trovato nel PATH: installalo (es. `apt install rclone` "
            "o scaricalo da https://rclone.org) e riprova.")

    port = args.port or free_port()
    user, password = random_creds()
    rcd = RcdProcess(exe, port, user, password, config_path=args.config)
    api = RcloneApi(rcd.url, user, password)
    rcd.start()
    if not rcd.wait_ready(api):
        tail = rcd.log_tail(15)
        raise RuntimeError(
            "rclone rcd non si è avviato.\n\nLog recente:\n" + tail)
    version = api.ping().get("version", "?")
    config_desc = args.config if args.config else "predefinito (~/.config/rclone/rclone.conf)"
    return AppContext(api=api, rcd=rcd, version=f"v{version}", config_desc=config_desc,
                      config_path=args.config)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])

    app = make_app()

    # -- avvio del backend con finestra di attesa
    progress = QtWidgets.QProgressDialog()
    progress.setLabelText("Avvio di rclone rcd…")
    progress.setRange(0, 0)
    progress.setCancelButton(None)
    progress.setWindowFlag(QtCore.Qt.WindowType.WindowCloseButtonHint, False)
    progress.setMinimumDuration(0)
    progress.show()
    QtWidgets.QApplication.processEvents()

    try:
        ctx = _build_context(args)
    except Exception as exc:  # noqa: BLE001 — errore di avvio mostrato all'utente
        progress.cancel()
        QtWidgets.QMessageBox.critical(None, "Avvio fallito", str(exc))
        return 1
    progress.cancel()

    from clonaut import settings as app_settings
    values = app_settings.load()
    win = MainWindow(ctx, settings=values)
    if values.get("start_in_tray") and win.tray is not None:
        pass   # resta ridotta nella tray (l'icona è già attiva)
    else:
        win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
