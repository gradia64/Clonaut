"""Avvio da riga di comando: la password del rcd esterno non deve finire in argv."""

from __future__ import annotations

import io

import pytest

from clonaut import app as app_mod


def _args(*argv):
    return app_mod._parse_args(list(argv))


class _Tty(io.StringIO):
    def isatty(self):
        return True


def test_password_presa_dalla_variabile(monkeypatch):
    monkeypatch.setenv("CLONAUT_RC_PASS", "dall-ambiente")
    args = _args("--url", "http://127.0.0.1:5572", "--user", "utente")
    assert app_mod._resolve_rc_password(args) == "dall-ambiente"


def test_password_chiesta_da_terminale(monkeypatch):
    monkeypatch.delenv("CLONAUT_RC_PASS", raising=False)
    monkeypatch.setattr(app_mod.sys, "stdin", _Tty())
    monkeypatch.setattr(app_mod.getpass, "getpass", lambda prompt: "digitata")
    args = _args("--url", "http://127.0.0.1:5572", "--user", "utente")
    assert app_mod._resolve_rc_password(args) == "digitata"


def test_password_mancante_senza_terminale(monkeypatch):
    monkeypatch.delenv("CLONAUT_RC_PASS", raising=False)
    monkeypatch.setattr(app_mod.sys, "stdin", io.StringIO())
    args = _args("--url", "http://127.0.0.1:5572", "--user", "utente")
    with pytest.raises(RuntimeError, match="CLONAUT_RC_PASS"):
        app_mod._resolve_rc_password(args)


def test_flag_password_accettato_con_avviso(monkeypatch, capsys):
    monkeypatch.setenv("CLONAUT_RC_PASS", "ignorata")
    args = _args("--url", "http://127.0.0.1:5572", "--user", "utente",
                 "--password", "esplicita")
    assert app_mod._resolve_rc_password(args) == "esplicita"
    assert "ps" in capsys.readouterr().err


def test_senza_aggancio_nessuna_password(monkeypatch):
    monkeypatch.delenv("CLONAUT_RC_PASS", raising=False)
    monkeypatch.setattr(app_mod.sys, "stdin", io.StringIO())
    assert app_mod._resolve_rc_password(_args()) == ""
    # senza utente rclone non usa l'autenticazione: niente da chiedere
    assert app_mod._resolve_rc_password(_args("--url", "http://127.0.0.1:5572")) == ""
