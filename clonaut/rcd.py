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
from .i18n import tr
from .settings import cache_dir, make_private

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
        (os.environ.get(RCLONE_ENV, "").strip(), tr("variabile {name}").format(name=RCLONE_ENV)),
        ((setting_path or "").strip(), tr("impostazioni")),
    )
    for raw, source in candidates:
        if not raw:
            tried.append(tr("{source}: non impostato").format(source=source))
            continue
        path = os.path.expanduser(raw)
        if _is_exe(path):
            return path, source, tried
        tried.append(tr("{source}: {path} non esiste o non è eseguibile").format(
            source=source, path=path))

    found = shutil.which("rclone")
    if found:
        return found, "PATH", tried
    tried.append(tr("PATH: rclone non trovato"))

    appdir = os.environ.get("APPDIR", "")
    bundled = os.path.join(appdir, "usr", "bin", "rclone") if appdir else ""
    if bundled and _is_exe(bundled):
        return bundled, tr("incluso nell'AppImage"), tried
    tried.append(tr("AppImage: nessuna copia inclusa") if not appdir
                 else tr("AppImage: {path} assente").format(path=bundled))
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


def _process_tree(pid: int) -> set[int]:
    """Il processo <pid> e tutti i suoi discendenti (letti da /proc).

    rclone può essere lanciato da uno script che fa fork invece di exec: il
    socket in ascolto sta allora in un processo figlio di quello avviato.
    """
    children: dict[int, list[int]] = {}
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/stat") as stat:
                # il nome del comando sta fra parentesi e può contenerne altre
                ppid = int(stat.read().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            continue
        children.setdefault(ppid, []).append(int(entry))
    tree, todo = set(), [pid]
    while todo:
        current = todo.pop()
        if current not in tree:
            tree.add(current)
            todo.extend(children.get(current, []))
    return tree


def _socket_inodes(pid: int) -> set[str]:
    inodes = set()
    try:
        names = os.listdir(f"/proc/{pid}/fd")
    except OSError:
        return inodes   # processo finito o non leggibile
    for name in names:
        try:
            link = os.readlink(f"/proc/{pid}/fd/{name}")
        except OSError:
            continue    # descrittore chiuso un istante fa
        if link.startswith("socket:["):
            inodes.add(link[len("socket:["):-1])
    return inodes


def port_owned_by(pid: int, port: int) -> bool:
    """True se il socket in ascolto su 127.0.0.1:<porta> è del processo <pid>.

    free_port() occupa la porta e la libera subito: prima che rclone la
    prenda, un altro processo della macchina potrebbe occuparla e fingersi
    il demone. Si legge quindi l'inode del socket in ascolto da
    /proc/net/tcp e si controlla che stia fra i descrittori del processo
    avviato da noi (o di un suo discendente). Senza /proc non c'è nulla da
    controllare e si prosegue come prima.
    """
    local = f"0100007F:{port:04X}"        # 127.0.0.1 come lo scrive /proc
    try:
        with open("/proc/net/tcp") as table:
            listening = {parts[9] for parts in map(str.split, table)
                         if len(parts) > 9 and parts[3] == "0A"   # 0A = LISTEN
                         and parts[1] == local}
    except OSError:
        return True    # niente /proc: controllo impossibile
    if not listening:
        return False   # risponde qualcuno che /proc non mostra: meglio fermarsi
    owned: set[str] = set()
    for member in _process_tree(pid):
        owned |= _socket_inodes(member)
    return listening <= owned   # ogni socket in ascolto dev'essere nostro


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
        # creato qui a 0600: rclone scrive in un file esistente senza
        # cambiarne i permessi (il log elenca ogni file sincronizzato)
        make_private(self.log_path)
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
        """Attende che l'API risponda.

        False se il processo muore, se a rispondere è un altro processo che
        ha preso la porta prima di rclone, o se scade il tempo.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.proc is not None and self.proc.poll() is not None:
                return False
            try:
                api.ping()
            except Exception:
                time.sleep(0.2)
                continue
            return self.proc is not None and port_owned_by(self.proc.pid, self.port)
        return False

    def log_tail(self, lines: int = 15) -> str:
        try:
            content = self.log_path.read_text(errors="replace").splitlines()
            return "\n".join(content[-lines:])
        except OSError:
            return tr("(nessun log disponibile)")

    def stop(self) -> None:
        if self.proc is None or self.proc.poll() is not None:
            return
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=5)


def launch_rcd(exe: str, *, port: int | None = None, config_path: str | None = None,
               extra_args: list[str] | None = None, timeout: float = 20.0,
               attempts: int = 3) -> tuple[RcdProcess, RcloneApi]:
    """Avvia un rcd locale e attende che sia pronto; restituisce (processo, API).

    Con la porta scelta a caso, se rclone non parte (per esempio perché un
    altro processo ha preso la porta) si riprova con porta e credenziali
    nuove. Con una porta fissa (--port) il tentativo è uno solo. Se
    nessun tentativo riesce solleva RcdStartError con il log dell'ultimo.
    """
    tries = 1 if port else max(1, attempts)
    proc: RcdProcess | None = None
    for _ in range(tries):
        user, password = random_creds()
        proc = RcdProcess(exe, port or free_port(), user, password,
                          config_path=config_path, extra_args=extra_args)
        api = RcloneApi(proc.url, user, password)
        proc.start()
        if proc.wait_ready(api, timeout=timeout):
            return proc, api
        proc.stop()
    raise RcdStartError(proc.log_tail(15) if proc is not None else "")


class RcdStartError(RuntimeError):
    """rclone rcd non è partito; l'argomento è la coda del suo log."""
