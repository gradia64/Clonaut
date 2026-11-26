"""Controllo degli aggiornamenti: API di GitHub finta, versioni, avviso nella finestra."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from clonaut import __version__, updates
from conftest import needs_rclone, spin


# ------------------------------------------------------------ server finto

class _Server:
    """Risponde a ogni GET con lo stato e il corpo impostati; ricorda gli header."""

    def __init__(self):
        self.status, self.body, self.headers = 200, b"{}", []
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 — API http.server
                server.headers.append(dict(self.headers))
                self.send_response(server.status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(server.body)

            def log_message(self, *_a):
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}/latest"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def reply(self, status=200, **data):
        self.status, self.body = status, json.dumps(data).encode()


@pytest.fixture
def github():
    server = _Server()
    yield server
    server.httpd.shutdown()
    server.httpd.server_close()


def _release(tag, **extra):
    return {"tag_name": tag, "html_url": f"https://github.com/gradia64/Clonaut/releases/tag/{tag}",
            "draft": False, "prerelease": False, **extra}


# --------------------------------------------------------------- versioni

@pytest.mark.parametrize("new,old,expected", [
    ("0.10.0", "0.9.9", True),       # confronto numerico, non di testo
    ("v0.5.2", "0.5.1", True),
    ("0.5.1", "0.5.1", False),
    ("0.5.1.0", "0.5.1", False),     # 0.5.1.0 == 0.5.1
    ("0.5.0", "0.5.1", False),
    ("1.0.0-rc1", "0.5.1", False),   # non è una versione di rilascio
    ("", "0.5.1", False),
])
def test_is_newer(new, old, expected):
    assert updates.is_newer(new, old) is expected


# ------------------------------------------------------------- richiesta

def test_versione_piu_nuova(github):
    github.reply(**_release("v99.0.0"))
    release = updates.check(url=github.url)
    assert release == updates.Release("99.0.0", "https://github.com/gradia64/Clonaut/releases/tag/v99.0.0")
    # una sola richiesta, anonima: solo nome e versione dell'app
    assert len(github.headers) == 1
    assert github.headers[0]["User-Agent"] == f"Clonaut/{__version__}"
    assert "Authorization" not in github.headers[0]


@pytest.mark.parametrize("tag", [f"v{__version__}", "v0.0.1"])
def test_stessa_versione_o_piu_vecchia(github, tag):
    github.reply(**_release(tag))
    assert updates.check(url=github.url) is None


def test_versione_saltata(github):
    github.reply(**_release("v99.0.0"))
    assert updates.check(skip_version="99.0.0", url=github.url) is None
    assert updates.check(skip_version="98.0.0", url=github.url).version == "99.0.0"


@pytest.mark.parametrize("status,match", [(403, "limitato"), (429, "limitato"), (500, "HTTP 500")])
def test_errori_http(github, status, match):
    github.reply(status, message="no")
    with pytest.raises(updates.UpdateError, match=match):
        updates.check(url=github.url)


@pytest.mark.parametrize("data", [
    {"tag_name": "nightly"}, {"html_url": "x"}, _release("v99.0.0", prerelease=True),
    _release("v99.0.0", draft=True),
])
def test_risposte_non_valide(github, data):
    github.reply(**data)
    with pytest.raises(updates.UpdateError, match="non valida"):
        updates.check(url=github.url)


def test_json_rotto(github):
    github.status, github.body = 200, b"<html>"
    with pytest.raises(updates.UpdateError, match="non valida"):
        updates.check(url=github.url)


def test_offline():
    from clonaut.rcd import free_port
    with pytest.raises(updates.UpdateError, match="non raggiungibile"):
        updates.fetch_latest(f"http://127.0.0.1:{free_port()}/latest", timeout=2)


def test_link_solo_verso_github(github):
    github.reply(**_release("v99.0.0", html_url="https://evil.example/x"))
    assert updates.check(url=github.url).url == \
        "https://github.com/gradia64/Clonaut/releases/tag/v99.0.0"


def test_variabile_d_ambiente(monkeypatch):
    for value in ("0", "false", "OFF", "no"):
        monkeypatch.setenv(updates.ENV_SWITCH, value)
        assert not updates.enabled_by_env()
    monkeypatch.setenv(updates.ENV_SWITCH, "1")
    assert updates.enabled_by_env()
    monkeypatch.delenv(updates.ENV_SWITCH)
    assert updates.enabled_by_env()


# --------------------------------------------------- tipo di installazione

def test_install_method(tmp_path, monkeypatch):
    monkeypatch.delenv("APPIMAGE", raising=False)
    monkeypatch.delenv("APPDIR", raising=False)
    deb = tmp_path / "usr/share/clonaut/clonaut/updates.py"
    site = tmp_path / "usr/lib/python3.13/site-packages/clonaut/updates.py"
    for f in (deb, site):
        f.parent.mkdir(parents=True)
        f.touch()
    root = str(tmp_path)
    assert updates.install_method(str(deb), root) == "source"   # senza dpkg
    (tmp_path / "var/lib/dpkg/info").mkdir(parents=True)
    (tmp_path / "var/lib/dpkg/info/clonaut.list").touch()
    assert updates.install_method(str(deb), root) == "deb"
    assert updates.install_method(str(site), root) == "source"  # pip
    (tmp_path / "var/lib/pacman/local/clonaut-0.5.1-1").mkdir(parents=True)
    assert updates.install_method(str(site), root) == "aur"
    (tmp_path / "var/lib/pacman/local/clonaut-0.5.1-1").rmdir()
    (tmp_path / "var/lib/pacman/local/clonaut-git-0.5.1.r0.g74ef27e-1").mkdir()
    assert updates.install_method(str(site), root) == "aur-git"
    monkeypatch.setenv("APPIMAGE", "/home/u/Clonaut.AppImage")
    monkeypatch.setenv("APPDIR", str(tmp_path / "usr"))
    assert updates.install_method(str(deb), root) == "appimage"
    for method in ("appimage", "deb", "aur", "aur-git", "source"):
        assert updates.how_to_update(method)


# ------------------------------------------------------ nella finestra

@needs_rclone
def test_avviso_nella_barra_salta_e_non_controllare(window, qapp, monkeypatch):
    from clonaut import settings as app_settings
    found = updates.Release("99.0.0", "https://github.com/gradia64/Clonaut/releases/tag/v99.0.0")
    asked = []
    monkeypatch.setattr(updates, "check", lambda skip="": asked.append(skip) or found)
    window.settings.update(check_updates=True, skip_version="98.0.0")
    window._auto_check_updates()
    assert spin(qapp, 5, until=lambda: window._update_lbl.isVisibleTo(window))
    assert asked == ["98.0.0"]
    text = window._update_lbl.text()
    assert "Clonaut 99.0.0 disponibile" in text and "Salta questa versione" in text
    assert "Non controllare più" in text
    assert window._update_lbl.toolTip()

    window._on_update_link("skip")
    assert not window._update_lbl.isVisibleTo(window)
    assert app_settings.load()["skip_version"] == "99.0.0"

    spin(qapp, 1, until=lambda: window._update_worker is None)
    window._auto_check_updates()
    assert spin(qapp, 5, until=lambda: window._update_lbl.isVisibleTo(window))
    window._on_update_link("off")
    assert app_settings.load()["check_updates"] is False
    spin(qapp, 1, until=lambda: window._update_worker is None)
    asked.clear()
    window._auto_check_updates()            # spento: nessuna richiesta
    assert asked == []


@needs_rclone
def test_controllo_a_mano(window, qapp, monkeypatch, dialogs):
    window.settings["check_updates"] = False
    window.settings["skip_version"] = "99.0.0"
    asked = []
    monkeypatch.setattr(updates, "check", lambda skip="": asked.append(skip) or None)
    window.check_updates_now()                # anche con il controllo spento
    assert spin(qapp, 5, until=lambda: dialogs)
    assert asked == [""]                      # a mano non salta nulla
    assert dialogs == ["Aggiornamenti"]

    def offline(skip=""):
        raise updates.UpdateError("GitHub non raggiungibile")
    spin(qapp, 1, until=lambda: window._update_worker is None)
    monkeypatch.setattr(updates, "check", offline)
    window.check_updates_now()
    assert spin(qapp, 5, until=lambda: len(dialogs) == 2)
    # in automatico lo stesso errore non mostra nulla
    spin(qapp, 1, until=lambda: window._update_worker is None)
    window.settings["check_updates"] = True
    window._auto_check_updates()
    spin(qapp, 1, until=lambda: window._update_worker is None)
    assert len(dialogs) == 2


@needs_rclone
def test_impostazioni_non_perdono_la_versione_saltata(window, monkeypatch):
    from clonaut.ui import main_window
    window.settings["skip_version"] = "99.0.0"

    class Dlg:
        def __init__(self, *_a, **_k):
            pass

        def exec(self):
            return main_window.QtWidgets.QDialog.DialogCode.Accepted

        def values(self):
            return {"check_updates": True, "language": ""}

    monkeypatch.setattr(main_window, "SettingsDialog", Dlg)
    window._open_settings()
    assert window.settings["skip_version"] == "99.0.0"
