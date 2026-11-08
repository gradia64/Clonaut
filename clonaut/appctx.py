"""Contesto applicativo condiviso tra le schermate."""

from __future__ import annotations

from dataclasses import dataclass, field

from .api import RcloneApi
from .rcd import RcdProcess, free_port, random_creds, which_rclone


@dataclass
class AppContext:
    api: RcloneApi
    rcd: RcdProcess | None = None      # presente solo se il processo è nostro
    version: str = ""
    config_desc: str = "predefinito (~/.config/rclone/rclone.conf)"
    config_path: str | None = None     # per creare il backend delle prove
    extras: dict = field(default_factory=dict)
    # backend dedicato alle prove a vuoto (--dry-run globale), creato al primo uso
    rcd_dry: RcdProcess | None = None
    api_dry: RcloneApi | None = None

    def ensure_dry_backend(self) -> RcloneApi:
        """API di un rcd effimero avviato con --dry-run globale.

        Il flag _dry_run non è applicabile chiamata per chiamata via rc (rclone
        lo ignora), quindi le prove a vuoto girano su un processo separato che
        NON PUÒ scrivere nulla. Il processo resta attivo per tutta la sessione.
        """
        if self.api_dry is not None:
            return self.api_dry
        exe = which_rclone()
        if not exe:
            raise RuntimeError("rclone non trovato nel PATH.")
        port = free_port()
        user, password = random_creds()
        self.rcd_dry = RcdProcess(exe, port, user, password,
                                  config_path=self.config_path,
                                  extra_args=["--dry-run"])
        api = RcloneApi(self.rcd_dry.url, user, password)
        self.rcd_dry.start()
        if not self.rcd_dry.wait_ready(api, timeout=20):
            tail = self.rcd_dry.log_tail(10)
            self.rcd_dry = None
            raise RuntimeError("Il backend delle prove non si è avviato.\n\n" + tail)
        self.api_dry = api
        return api
