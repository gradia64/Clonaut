"""Ricerca di rclone, avvio del demone, credenziali e log."""

import os
import time

import pytest

from clonaut import rcd as rcd_mod
from conftest import needs_rclone


def _fake_exe(path):
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(0o755)
    return str(path)


@pytest.fixture
def empty_path(monkeypatch, tmp_path):
    """PATH senza rclone e senza AppImage."""
    monkeypatch.setenv("PATH", str(tmp_path / "nulla"))
    monkeypatch.delenv("CLONAUT_RCLONE", raising=False)
    monkeypatch.delenv("APPDIR", raising=False)


def test_not_found_lists_every_source(empty_path):
    exe, source, tried = rcd_mod.find_rclone("")
    assert exe is None and source == ""
    text = "\n".join(tried)
    for word in ("CLONAUT_RCLONE", "impostazioni", "PATH", "AppImage"):
        assert word in text


def test_priority_env_setting_path_appdir(empty_path, tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    in_path = _fake_exe(bindir / "rclone")
    appdir = tmp_path / "AppDir"
    (appdir / "usr" / "bin").mkdir(parents=True)
    bundled = _fake_exe(appdir / "usr" / "bin" / "rclone")
    chosen = _fake_exe(tmp_path / "rclone-scelto")
    env_exe = _fake_exe(tmp_path / "rclone-env")

    monkeypatch.setenv("APPDIR", str(appdir))
    assert rcd_mod.find_rclone("")[:2] == (bundled, "incluso nell'AppImage")

    monkeypatch.setenv("PATH", str(bindir))
    assert rcd_mod.find_rclone("")[:2] == (in_path, "PATH")   # il sistema vince

    assert rcd_mod.find_rclone(chosen)[:2] == (chosen, "impostazioni")

    monkeypatch.setenv("CLONAUT_RCLONE", env_exe)
    assert rcd_mod.find_rclone(chosen)[:2] == (env_exe, "variabile CLONAUT_RCLONE")


def test_invalid_setting_is_skipped(empty_path, tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    in_path = _fake_exe(bindir / "rclone")
    monkeypatch.setenv("PATH", str(bindir))
    exe, source, tried = rcd_mod.find_rclone(str(tmp_path / "non-esiste"))
    assert (exe, source) == (in_path, "PATH")
    assert any("non esiste" in t for t in tried)


def test_prune_logs_keeps_recent(tmp_path):
    old, new = tmp_path / "rcd-1.log", tmp_path / "rcd-2.log"
    old.write_text("x")
    new.write_text("y")
    ten_days = time.time() - 10 * 86400
    os.utime(old, (ten_days, ten_days))
    rcd_mod.prune_logs(tmp_path, keep_days=7)
    assert not old.exists() and new.exists()


@needs_rclone
def test_password_not_on_command_line(rcd):
    cmdline = open(f"/proc/{rcd.rcd.proc.pid}/cmdline").read()
    assert rcd.rcd.password not in cmdline
    assert rcd.rcd.user not in cmdline
    assert rcd.api.ping()["version"]


# --- porta presa da un altro processo (penetration test Strix, vuln-0004) ---

_MINI_RCD = """\
import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
port = int([a for a in sys.argv if a.startswith('--rc-addr=')][0].rsplit(':', 1)[1])
class H(BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers.get('Content-Length') or 0))
        body = json.dumps({'version': 'v-nostro'}).encode()
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *a):
        pass
HTTPServer(('127.0.0.1', port), H).serve_forever()
"""


class _Impostore:
    """Server HTTP che occupa una porta e si finge rclone rcd."""

    def __init__(self, port=0):
        import json
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                body = json.dumps({"version": "v6.6.6-finto"}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.server = HTTPServer(("127.0.0.1", port), H)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def _stub(tmp_path, name, body):
    import sys
    script = tmp_path / name
    if body is None:
        script.write_text("#!/bin/sh\nexec sleep 60\n")          # non apre la porta
    else:
        mini = tmp_path / f"{name}.py"
        mini.write_text(body)
        script.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{mini}" "$@"\n')
    script.chmod(0o755)
    return str(script)


def test_wait_ready_rifiuta_chi_ha_preso_la_porta(tmp_path):
    from clonaut.api import RcloneApi
    impostore = _Impostore()
    proc = rcd_mod.RcdProcess(_stub(tmp_path, "dorme", None), impostore.port, "u", "p",
                              log_path=tmp_path / "rcd.log")
    api = RcloneApi(proc.url, "u", "p", timeout=3)
    proc.start()
    try:
        assert not proc.wait_ready(api, timeout=3)
    finally:
        proc.stop()
        impostore.close()


def test_wait_ready_accetta_il_demone_nostro(tmp_path):
    from clonaut.api import RcloneApi
    proc = rcd_mod.RcdProcess(_stub(tmp_path, "mini", _MINI_RCD), rcd_mod.free_port(),
                              "u", "p", log_path=tmp_path / "rcd.log")
    api = RcloneApi(proc.url, "u", "p", timeout=3)
    proc.start()
    try:
        assert proc.wait_ready(api, timeout=10)
        assert api.ping()["version"] == "v-nostro"
    finally:
        proc.stop()


def test_demone_lanciato_da_script_con_fork(tmp_path):
    """Uno script che avvia rclone senza exec: la porta è di un figlio."""
    import sys
    from clonaut.api import RcloneApi
    mini = tmp_path / "mini.py"
    mini.write_text(_MINI_RCD)
    script = tmp_path / "wrapper"
    script.write_text(f'#!/bin/sh\n"{sys.executable}" "{mini}" "$@"\n')
    script.chmod(0o755)
    proc = rcd_mod.RcdProcess(str(script), rcd_mod.free_port(), "u", "p",
                              log_path=tmp_path / "rcd.log")
    api = RcloneApi(proc.url, "u", "p", timeout=3)
    proc.start()
    try:
        assert proc.wait_ready(api, timeout=10)
    finally:
        proc.stop()
        import subprocess
        subprocess.run(["pkill", "-f", str(mini)], check=False)


def test_launch_rcd_riprova_con_un_altra_porta(tmp_path, monkeypatch):
    impostore = _Impostore()
    porte = iter([impostore.port, rcd_mod.free_port()])
    monkeypatch.setattr(rcd_mod, "free_port", lambda: next(porte))
    monkeypatch.setattr(rcd_mod, "LOG_DIR", tmp_path)
    try:
        proc, api = rcd_mod.launch_rcd(_stub(tmp_path, "mini", _MINI_RCD), timeout=10)
        try:
            assert proc.port != impostore.port
            assert api.ping()["version"] == "v-nostro"
        finally:
            proc.stop()
    finally:
        impostore.close()


def test_launch_rcd_porta_fissa_un_solo_tentativo(tmp_path):
    impostore = _Impostore()
    try:
        with pytest.raises(rcd_mod.RcdStartError):
            rcd_mod.launch_rcd(_stub(tmp_path, "dorme", None), port=impostore.port,
                               timeout=3)
    finally:
        impostore.close()
