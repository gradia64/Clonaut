"""Gestione del processo locale `rclone rcd` (il "backend" della GUI)."""

from __future__ import annotations

import os
import secrets
import shutil
import socket
import subprocess
import time
from pathlib import Path

from .api import RcloneApi
from .settings import cache_dir

LOG_DIR = cache_dir()
LOG_KEEP_DAYS = 7      # i log dei demoni più vecchi di così vengono rimossi


def prune_logs(log_dir: Path = LOG_DIR, keep_days: float = LOG_KEEP_DAYS) -> None:
    """Rimuove i vecchi rcd-<porta>.log (uno per avvio: si accumulerebbero)."""
    limit = time.time() - keep_days * 86400
    try:
        for log in log_dir.glob("rcd-*.log"):
            if log.stat().st_mtime < limit:
                log.unlink()
    except OSError:
        pass


RCLONE_ENV = "CLONAUT_RCLONE"


def _is_exe(path: str) -> bool:
    return os.path.isfile(path) and os.access(path, os.X_OK)


def find_rclone(setting_path: str = "") -> tuple[str | None, str, list[str]]:
    """Cerca l'eseguibile rclone; restituisce (percorso, origine, tentativi).

    Ordine: variabile d'ambiente CLONAUT_RCLONE → percorso scelto nelle
    impostazioni → `rclone` nel PATH → copia inclusa nell'AppImage
    ($APPDIR/usr/bin/rclone), usata solo come riserva. `tentativi` descrive
    ogni fonte provata, per il messaggio d'errore.
    """
    tried: list[str] = []
    candidates = (
        (os.environ.get(RCLONE_ENV, "").strip(), f"variabile {RCLONE_ENV}"),
        ((setting_path or "").strip(), "impostazioni"),
    )
    for raw, source in candidates:
        if not raw:
            tried.append(f"{source}: non impostato")
            continue
        path = os.path.expanduser(raw)
        if _is_exe(path):
            return path, source, tried
        tried.append(f"{source}: {path} non esiste o non è eseguibile")

    found = shutil.which("rclone")
    if found:
        return found, "PATH", tried
    tried.append("PATH: rclone non trovato")

    appdir = os.environ.get("APPDIR", "")
    bundled = os.path.join(appdir, "usr", "bin", "rclone") if appdir else ""
    if bundled and _is_exe(bundled):
        return bundled, "incluso nell'AppImage", tried
    tried.append("AppImage: nessuna copia inclusa" if not appdir
                 else f"AppImage: {bundled} assente")
    return None, "", tried


def which_rclone() -> str | None:
    """Compatibilità: solo il percorso trovato da find_rclone()."""
    return find_rclone()[0]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def random_creds() -> tuple[str, str]:
    """Credenziali usa-e-getta per il demone locale (autenticazione Basic)."""
    return secrets.token_hex(8), secrets.token_urlsafe(15)


def _pdeathsig() -> None:  # pragma: no cover — gira nel figlio appena creato
    """Su Linux: chiede al kernel di uccidere rcd se il processo GUI muore."""
    try:
        import ctypes
        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        libc.prctl(1, 9)  # PR_SET_PDEATHSIG, SIGKILL
    except Exception:
        pass


class RcdProcess:
    """Avvia e gestisce un'istanza di `rclone rcd` su 127.0.0.1:<port>."""

    def __init__(self, exe: str, port: int, user: str, password: str,
                 config_path: str | None = None, extra_args: list[str] | None = None,
                 log_path: Path | None = None, cwd: str | None = None):
        self.exe = exe
        self.port = port
        self.user = user
        self.password = password
        self.config_path = config_path
        self.extra_args = extra_args or []
        self.log_path = Path(log_path) if log_path else LOG_DIR / f"rcd-{port}.log"
        self.cwd = cwd
        self.proc: subprocess.Popen | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        prune_logs(self.log_path.parent)
        cmd = [
            self.exe, "rcd",
            f"--rc-addr=127.0.0.1:{self.port}",
            f"--log-file={self.log_path}", "--log-level=INFO",
            *self.extra_args,
        ]
        env = os.environ.copy()
        # credenziali via ambiente, non sulla riga di comando: gli argomenti
        # sono leggibili da tutti gli utenti con `ps`, l'ambiente no
        env["RCLONE_RC_USER"] = self.user
        env["RCLONE_RC_PASS"] = self.password
        if self.config_path:
            env["RCLONE_CONFIG"] = str(self.config_path)
        kwargs: dict = {}
        if os.name == "posix":
            kwargs["preexec_fn"] = _pdeathsig  # noqa: PLW1509 — necessario per non lasciare orfani
        self.proc = subprocess.Popen(cmd, env=env, cwd=self.cwd,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     **kwargs)

    def wait_ready(self, api: RcloneApi, timeout: float = 20.0) -> bool:
        """Attendere che l'API risponda; False se il processo muore o scade il tempo."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.proc is not None and self.proc.poll() is not None:
                return False
            try:
                api.ping()
                return True
            except Exception:
                time.sleep(0.2)
        return False

    def log_tail(self, lines: int = 15) -> str:
        try:
            content = self.log_path.read_text(errors="replace").splitlines()
            return "\n".join(content[-lines:])
        except OSError:
            return "(nessun log disponibile)"

    def stop(self) -> None:
        if self.proc is None or self.proc.poll() is not None:
            return
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=5)
