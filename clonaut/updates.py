"""Controllo degli aggiornamenti: c'è una release di Clonaut più nuova?

Una sola richiesta anonima all'API delle release di GitHub, senza dati
dell'utente (User-Agent generico «Clonaut/<versione>»): nessun altro dato
lascia la macchina. Clonaut non sostituisce mai i propri file: l'avviso dice
come aggiornare secondo il modo in cui è installato (apt, AUR, AppImage).

Si disattiva in *Impostazioni* o, per tutti gli utenti di un'installazione,
con la variabile d'ambiente CLONAUT_UPDATE_CHECK=0.
"""

from __future__ import annotations

import glob
import os
import re
from dataclasses import dataclass
from pathlib import Path

import requests

from . import __version__
from .i18n import tr

RELEASES_URL = "https://api.github.com/repos/gradia64/Clonaut/releases/latest"
TIMEOUT = 10.0
CHECK_EVERY_MS = 24 * 3600 * 1000   # un controllo al giorno finché l'app resta aperta
FIRST_CHECK_MS = 15 * 1000          # il primo poco dopo l'avvio, non durante
ENV_SWITCH = "CLONAUT_UPDATE_CHECK"

_VERSION_RE = re.compile(r"^v?(\d+(?:\.\d+)*)$")


class UpdateError(Exception):
    """Controllo non riuscito (rete, limite di GitHub, risposta inattesa)."""


@dataclass(frozen=True)
class Release:
    version: str      # «0.6.0», senza la «v» del tag
    url: str          # pagina della release (note di rilascio)


def parse_version(text: str) -> tuple[int, ...] | None:
    """«v0.10.2» → (0, 10, 2); None se non è una versione di rilascio."""
    match = _VERSION_RE.match(str(text or "").strip())
    if not match:
        return None
    parts = [int(p) for p in match.group(1).split(".")]
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()   # 1.0 == 1.0.0
    return tuple(parts)


def is_newer(candidate: str, current: str = __version__) -> bool:
    """True se `candidate` è una versione successiva a `current` (0.10 > 0.9)."""
    new, old = parse_version(candidate), parse_version(current)
    return new is not None and old is not None and new > old


def enabled_by_env() -> bool:
    """False se CLONAUT_UPDATE_CHECK=0/false/no/off (pacchetti, ambienti senza rete)."""
    return os.environ.get(ENV_SWITCH, "").strip().lower() not in {"0", "false", "no", "off"}


def fetch_latest(url: str = RELEASES_URL, timeout: float = TIMEOUT) -> Release:
    """Ultima release pubblicata (GitHub esclude già bozze e pre-release)."""
    headers = {"Accept": "application/vnd.github+json",
               "User-Agent": f"Clonaut/{__version__}"}
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
    except requests.RequestException as exc:
        raise UpdateError(tr("GitHub non raggiungibile: {error}").format(error=exc)) from exc
    if resp.status_code in (403, 429):
        raise UpdateError(tr("GitHub ha limitato le richieste: riprova più tardi."))
    if resp.status_code != 200:
        raise UpdateError(tr("GitHub ha risposto HTTP {status}.").format(
            status=resp.status_code))
    try:
        data = resp.json()
    except ValueError as exc:
        raise UpdateError(tr("Risposta di GitHub non valida.")) from exc
    if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
        raise UpdateError(tr("Risposta di GitHub non valida."))
    tag = str(data.get("tag_name") or "")
    if parse_version(tag) is None:
        raise UpdateError(tr("Risposta di GitHub non valida."))
    page = str(data.get("html_url") or "")
    if not page.startswith("https://github.com/"):
        # il link si apre nel browser: solo pagine di GitHub
        page = f"https://github.com/gradia64/Clonaut/releases/tag/{tag}"
    return Release(version=tag.lstrip("v"), url=page)


def check(skip_version: str = "", url: str = RELEASES_URL) -> Release | None:
    """La release da segnalare, o None se non ce n'è una più nuova (o è saltata)."""
    release = fetch_latest(url)
    if not is_newer(release.version):
        return None
    if skip_version and release.version == skip_version:
        return None
    return release


# ------------------------------------------------------- come è installato

def install_method(module_file: str | None = None, root: str = "/") -> str:
    """«appimage», «deb», «aur», «aur-git» o «source» (pip, cartella del codice)."""
    here = Path(module_file or __file__).resolve()
    appdir = os.environ.get("APPDIR")
    if os.environ.get("APPIMAGE") and appdir and here.is_relative_to(Path(appdir).resolve()):
        return "appimage"
    base = Path(root)
    if here.is_relative_to(base / "usr/share/clonaut") and \
            (base / "var/lib/dpkg/info/clonaut.list").exists():
        return "deb"
    if here.is_relative_to(base / "usr/lib"):
        local = str(base / "var/lib/pacman/local")
        if glob.glob(f"{glob.escape(local)}/clonaut-git-*"):
            return "aur-git"
        if glob.glob(f"{glob.escape(local)}/clonaut-[0-9]*"):
            return "aur"
    return "source"


def how_to_update(method: str) -> str:
    """Una frase che dice come aggiornare con quel tipo di installazione."""
    if method == "appimage":
        return tr("Scarica la nuova AppImage dalla pagina della release, oppure "
                  "aggiornala con Gear Lever o AppImageUpdate.")
    if method == "deb":
        return tr("Scarica il nuovo pacchetto .deb dalla pagina della release e "
                  "installalo con «sudo apt install ./clonaut_<versione>_all.deb».")
    if method == "aur":
        return tr("Aggiorna il pacchetto «clonaut» con il tuo helper AUR "
                  "(es. «yay -Syu»).")
    if method == "aur-git":
        return tr("Ricostruisci il pacchetto «clonaut-git» con il tuo helper AUR "
                  "(es. «yay -Syu --devel»).")
    return tr("Aggiorna il codice (es. «git pull» o «pip install --upgrade»).")
