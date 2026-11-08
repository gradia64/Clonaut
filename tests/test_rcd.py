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
