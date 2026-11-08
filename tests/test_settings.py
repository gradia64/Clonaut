"""Impostazioni persistenti e migrazione dal vecchio nome «GUI rclone»."""

import json

from clonaut import settings


def test_defaults_when_missing():
    values = settings.load()
    assert values == settings.DEFAULTS


def test_roundtrip_with_text_value():
    values = settings.load()
    values.update(close_to_tray=False, rclone_path="  /opt/rclone  ")
    settings.save(values)
    loaded = settings.load()
    assert loaded["close_to_tray"] is False
    assert loaded["rclone_path"] == "/opt/rclone"


def test_corrupted_file_falls_back_to_defaults(isolated_config):
    settings.settings_path().parent.mkdir(parents=True, exist_ok=True)
    settings.settings_path().write_text("{non è json")
    assert settings.load() == settings.DEFAULTS


def test_migration_from_rclone_gui(tmp_path, monkeypatch):
    monkeypatch.delenv("CLONAUT_CONFIG_HOME")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    old = tmp_path / "rclone-gui"
    old.mkdir()
    (old / "settings.json").write_text(json.dumps({"close_to_tray": False}))
    (old / "recurring.json").write_text(json.dumps({"definitions": []}))

    new = settings.config_dir()
    assert new == tmp_path / "clonaut"
    assert (new / "recurring.json").exists()
    assert settings.load()["close_to_tray"] is False
