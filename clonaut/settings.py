"""Impostazioni persistenti della GUI (settings.json accanto a recurring.json)."""

from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULTS = {
    "close_to_tray": True,      # chiudere la finestra la nasconde nella tray
    "minimize_to_tray": False,  # minimizzare la nasconde nella tray
    "start_in_tray": False,     # all'avvio resta ridotta nella tray
    "notify_finished": True,    # notifica a ogni trasferimento terminato
}


def config_dir() -> Path:
    """Cartella di configurazione della GUI (override test: CLONAUT_CONFIG_HOME).

    Al primo avvio dopo la rinomina, i file della vecchia cartella
    «rclone-gui» (settings.json, recurring.json) vengono copiati qui.
    """
    base = os.environ.get("CLONAUT_CONFIG_HOME")
    if not base:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    path = Path(base) / "clonaut"
    _migrate_legacy(Path(base) / "rclone-gui", path)
    return path


def cache_dir() -> Path:
    """Cartella cache (log del demone), secondo XDG_CACHE_HOME."""
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "clonaut"


def _migrate_legacy(old: Path, new: Path) -> None:
    """Copia i file del vecchio nome «GUI rclone» se la nuova cartella non esiste."""
    if new.exists() or not old.is_dir():
        return
    try:
        new.mkdir(parents=True, exist_ok=True)
        for name in ("settings.json", "recurring.json"):
            src = old / name
            if src.is_file():
                (new / name).write_bytes(src.read_bytes())
    except OSError:
        pass


def settings_path() -> Path:
    return config_dir() / "settings.json"


def load() -> dict:
    data = dict(DEFAULTS)
    try:
        stored = json.loads(settings_path().read_text())
    except (OSError, ValueError):
        return data
    if isinstance(stored, dict):
        for key in DEFAULTS:
            if key in stored:
                data[key] = bool(stored[key])
    return data


def save(values: dict) -> None:
    data = {key: bool(values.get(key, DEFAULTS[key])) for key in DEFAULTS}
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))
