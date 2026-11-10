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


# --- permessi dei file di stato (penetration test Strix, vuln-0003) ---

def _mode(path):
    import stat
    return stat.S_IMODE(path.stat().st_mode)


def test_settings_e_programmazioni_solo_per_il_proprietario(qapp):
    from clonaut.ui.transfers_tab import TransfersTab
    import test_transfers_tab as ttt
    settings.save(dict(settings.DEFAULTS))
    assert _mode(settings.settings_path()) == 0o600
    tab = TransfersTab(ttt._Ctx())
    tab._save_recurring()
    assert _mode(settings.config_dir() / "recurring.json") == 0o600


def test_file_vecchi_larghi_vengono_sistemati():
    path = settings.settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}")
    path.chmod(0o644)
    settings.save(dict(settings.DEFAULTS))
    assert _mode(path) == 0o600


def test_log_del_demone_solo_per_il_proprietario(tmp_path):
    from clonaut.rcd import RcdProcess
    proc = RcdProcess("/bin/true", 1, "u", "p", log_path=tmp_path / "rcd-1.log")
    proc.start()
    proc.proc.wait()
    assert _mode(tmp_path / "rcd-1.log") == 0o600
