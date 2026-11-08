"""Fixture comuni: Qt offscreen, ambiente isolato, demone rclone vero.

Le variabili d'ambiente vanno impostate PRIMA di importare clonaut (rcd.py
calcola la cartella dei log all'import). Il binding Qt si sceglie con
CLONAUT_QT=pyqt6|pyside6: lanciare la suite con entrambi.
"""

from __future__ import annotations

import gc
import os
import shutil
import tempfile
import time
from pathlib import Path

import pytest

_ROOT = Path(tempfile.mkdtemp(prefix="clonaut-tests-"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["XDG_CACHE_HOME"] = str(_ROOT / "cache")
os.environ["XDG_CONFIG_HOME"] = str(_ROOT / "xdg-config")
os.environ.pop("CLONAUT_RCLONE", None)
os.environ.pop("APPDIR", None)

from clonaut.qtcompat import QtCore, QtWidgets  # noqa: E402

RCLONE = shutil.which("rclone")
needs_rclone = pytest.mark.skipif(RCLONE is None, reason="rclone non installato")


def pytest_report_header(config):
    from clonaut.qtcompat import BINDING
    return f"clonaut: Qt binding {BINDING}, rclone {RCLONE or 'assente'}"


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_ROOT, ignore_errors=True)


@pytest.fixture(scope="session")
def qapp():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["clonaut"])
    yield app
    # finestre e dialoghi rimasti vanno distrutti finché Qt è vivo: lasciati
    # all'uscita dell'interprete, PySide6 6.12 li cancella dopo la
    # QApplication («shared QObject was deleted directly») e va in segfault
    for widget in QtWidgets.QApplication.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
    app.processEvents()
    gc.collect()


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """Ogni test ha la sua cartella di configurazione della GUI."""
    cfg = tmp_path / "cfg"
    monkeypatch.setenv("CLONAUT_CONFIG_HOME", str(cfg))
    return cfg


@pytest.fixture
def dialogs(monkeypatch):
    """Sostituisce i QMessageBox modali (bloccherebbero offscreen).

    Restituisce la lista dei titoli mostrati; alle domande risponde «Sì».
    """
    shown: list[str] = []
    box = QtWidgets.QMessageBox

    def question(_parent, title, *_a, **_k):
        shown.append(title)
        return box.StandardButton.Yes

    def note(_parent, title, *_a, **_k):
        shown.append(title)
        return box.StandardButton.Ok

    monkeypatch.setattr(box, "question", staticmethod(question))
    for name in ("information", "warning", "critical"):
        monkeypatch.setattr(box, name, staticmethod(note))
    return shown


def spin(app, seconds: float, until=None) -> bool:
    """Fa girare gli eventi Qt per `seconds` o finché `until()` è vero."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        if until is not None and until():
            return True
        time.sleep(0.03)
    return until() if until is not None else True


@pytest.fixture
def rcd(tmp_path, qapp):
    """Un `rclone rcd` vero con configurazione vuota; restituisce il contesto."""
    if RCLONE is None:
        pytest.skip("rclone non installato")
    from clonaut.api import RcloneApi
    from clonaut.appctx import AppContext
    from clonaut.rcd import RcdProcess, free_port, random_creds

    conf = tmp_path / "rclone.conf"
    conf.write_text("")
    port = free_port()
    user, password = random_creds()
    proc = RcdProcess(RCLONE, port, user, password, config_path=str(conf))
    api = RcloneApi(proc.url, user, password)
    proc.start()
    assert proc.wait_ready(api), proc.log_tail()
    ctx = AppContext(api=api, rcd=proc, version="v-test", config_desc="test",
                     config_path=str(conf), rclone_exe=RCLONE, rclone_source="PATH")
    yield ctx
    proc.stop()
    if ctx.rcd_dry is not None:
        ctx.rcd_dry.stop()


@pytest.fixture
def tree(tmp_path):
    """Cartelle di prova: a/ con due file, b/ con due file «extra»."""
    a, b = tmp_path / "a", tmp_path / "b"
    (a / "sub").mkdir(parents=True)
    b.mkdir()
    (a / "new.txt").write_text("nuovo")
    (a / "sub" / "deep.txt").write_text("profondo")
    (a / "skip.tmp").write_text("da escludere")
    (b / "extra1").write_text("x")
    (b / "extra2").write_text("y")
    return tmp_path


@pytest.fixture
def window(rcd, qapp, dialogs):
    """MainWindow completa (con il thread di polling), chiusa a fine test."""
    from clonaut.ui.main_window import MainWindow
    win = MainWindow(rcd, settings={"close_to_tray": False})
    win.show()
    yield win
    win._quitting = True
    win.close()
