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


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:5572", "http://localhost:5572", "http://[::1]:5572",
    "https://nas.example:5572",
])
def test_aggancio_ammesso(url):
    app_mod._check_attach_url(_args("--url", url, "--user", "utente"))


def test_aggancio_in_chiaro_verso_altra_macchina_rifiutato():
    """P2-10: HTTP Basic su http:// in rete manda le credenziali in chiaro."""
    with pytest.raises(RuntimeError, match="insecure-http"):
        app_mod._check_attach_url(_args("--url", "http://192.168.1.5:5572",
                                        "--user", "utente"))
    # scelta esplicita, oppure nessuna credenziale da proteggere
    app_mod._check_attach_url(_args("--url", "http://192.168.1.5:5572", "--user",
                                    "utente", "--insecure-http"))
    app_mod._check_attach_url(_args("--url", "http://192.168.1.5:5572"))


@pytest.mark.parametrize("url", ["192.168.1.5:5572", "ftp://nas:5572", "http://"])
def test_aggancio_indirizzo_non_valido(url):
    with pytest.raises(RuntimeError, match="non valido"):
        app_mod._check_attach_url(_args("--url", url))
