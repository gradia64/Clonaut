"""Contesto applicativo condiviso tra le schermate."""

from __future__ import annotations

from dataclasses import dataclass, field

from .api import RcloneApi
from .i18n import tr
from .rcd import RcdProcess, RcdStartError, find_rclone, launch_rcd


@dataclass
class AppContext:
    api: RcloneApi
    rcd: RcdProcess | None = None      # presente solo se il processo è nostro
    version: str = ""
    # tradotto alla creazione, non all'import: la lingua è scelta dopo
    config_desc: str = field(
        default_factory=lambda: tr("predefinito (~/.config/rclone/rclone.conf)"))
    config_path: str | None = None     # per creare il backend delle prove
    extras: dict = field(default_factory=dict)
    # backend dedicato alle prove a vuoto (--dry-run globale), creato al primo uso
    rcd_dry: RcdProcess | None = None
    api_dry: RcloneApi | None = None
    # eseguibile rclone in uso e da dove viene (PATH, impostazioni, AppImage…)
    rclone_exe: str | None = None
    rclone_source: str = ""

    def ensure_dry_backend(self) -> RcloneApi:
        """API di un rcd effimero avviato con --dry-run globale.

        Il flag _dry_run non è applicabile chiamata per chiamata via rc (rclone
        lo ignora), quindi le prove a vuoto girano su un processo separato che
        NON PUÒ scrivere nulla. Il processo resta attivo per tutta la sessione.
        """
        if self.api_dry is not None:
            return self.api_dry
        exe = self.rclone_exe or find_rclone()[0]
        if not exe:
            raise RuntimeError(tr("rclone non trovato: indicane il percorso in "
                               "File → Impostazioni."))
        try:
            self.rcd_dry, api = launch_rcd(exe, config_path=self.config_path,
                                           extra_args=["--dry-run"])
        except RcdStartError as exc:
            raise RuntimeError(
                tr("Il backend delle prove non si è avviato.\n\n") + str(exc)) from exc
        self.api_dry = api
        return api
