"""Client REST per l'API di `rclone rcd` (autenticazione HTTP Basic)."""

from __future__ import annotations

import os
import re

import requests

from .i18n import tr


class ApiError(Exception):
    """Errore restituito dall'API rclone (HTTP != 200 o risposta non valida)."""


_ENDPOINTS = {
    "copy": "sync/copy",
    "move": "sync/move",
    "sync": "sync/sync",
}

# "nome:" all'inizio → remote; su Linux un ":" prima di ogni "/" non esiste nei percorsi
_REMOTE_RE = re.compile(r"^[^/:]+:")


def is_remote(path: str) -> bool:
    """True se il percorso sembra un remote («nome:...»)."""
    return bool(_REMOTE_RE.match(path))


class RcloneApi:
    """Sottile wrapper attorno agli endpoint usati dalla GUI."""

    def __init__(self, url: str, user: str = "", password: str = "", timeout: float = 20.0):
        self.url = url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        if user:
            self.session.auth = (user, password)

    # ------------------------------------------------------------------ base

    def call(self, endpoint: str, payload: dict | None = None,
             timeout: float | None = None) -> dict:
        try:
            resp = self.session.post(f"{self.url}/{endpoint}", json=payload or {},
                                     timeout=timeout or self.timeout)
        except requests.RequestException as exc:
            # demone chiuso o bloccato: per chi chiama è un errore dell'API come
            # gli altri (il timer dei programmati e i dialoghi gestiscono ApiError)
            raise ApiError(tr("rclone rcd non risponde ({endpoint}): {error}").format(
                endpoint=endpoint, error=exc)) from exc
        if resp.status_code != 200:
            try:
                msg = resp.json().get("error") or resp.text
            except ValueError:
                msg = resp.text
            raise ApiError(f"{endpoint} → HTTP {resp.status_code}: {str(msg).strip()}")
        try:
            return resp.json()
        except ValueError as exc:
            raise ApiError(tr("{endpoint}: risposta non JSON ({error})").format(
                endpoint=endpoint, error=exc)) from exc

    def ping(self) -> dict:
        """Verifica la connessione; restituisce le info di versione."""
        return self.call("core/version", timeout=6)

    # ----------------------------------------------------------- config remote

    def list_remotes(self) -> list[str]:
        data = self.call("config/listremotes")
        return sorted(str(r).rstrip(":") for r in data.get("remotes", []))

    def dump_config(self) -> dict:
        """Config completa; i valori sensibili sono mascherati da rclone (XXX)."""
        return self.call("config/dump")

    def providers(self) -> list[dict]:
        return self.call("config/providers").get("providers", [])

    def create_remote(self, name: str, type_: str, parameters: dict) -> None:
        self.call("config/create", {"name": name, "type": type_, "parameters": parameters})

    def delete_remote(self, name: str) -> None:
        self.call("config/delete", {"name": name})

    # ------------------------------------------------------------ trasferimenti

    def start_transfer(self, mode: str, src: str, dst: str,
                       exclude: list[str] | None = None,
                       backup_dir: str | None = None) -> int:
        """Avvia un trasferimento asincrono; restituisce il jobid.

        Le stats del job finiscono nel gruppo di default "job/<id>".
        I file locali singoli usano operations/copyfile: l'endpoint sync/copy,
        diversamente dal CLI, accetta solo filesystem di directory.
        `exclude` è una lista di pattern rclone (es. ["*.log", ".sync_*"]).
        `backup_dir` è il cestino di sicurezza: i file che verrebbero eliminati
        o sovrascritti in destinazione vengono SPOSTATI lì invece (via
        _config.BackupDir — le altre vie rc sono ignorate da rclone 1.75).
        """
        endpoint = _ENDPOINTS.get(mode)
        if not endpoint:
            raise ApiError(tr("modalità di trasferimento sconosciuta: {mode}").format(mode=mode))
        if not _REMOTE_RE.match(src):
            src = os.path.expanduser(src)
        if not _REMOTE_RE.match(dst):
            dst = os.path.expanduser(dst)

        if not _REMOTE_RE.match(src) and os.path.isfile(src):
            if mode != "copy":
                raise ApiError(
                    tr("«Sposta» e «Sincronizza» operano su cartelle: per un file "
                    "singolo usa la modalità «Copia»."))
            payload = {
                "srcFs": os.path.dirname(os.path.abspath(src)) or "/",
                "srcRemote": os.path.basename(src),
                "_async": True,
            }
            # copyfile vuole il nome completo del file di destinazione:
            # su una directory (locale o remota) manteniamo il nome sorgente
            if _REMOTE_RE.match(dst) or os.path.isdir(dst):
                payload["dstFs"], payload["dstRemote"] = dst, os.path.basename(src)
            else:
                payload["dstFs"] = os.path.dirname(os.path.abspath(dst)) or "/"
                payload["dstRemote"] = os.path.basename(dst)   # file → file rinominato
            if backup_dir:
                payload["_config"] = {"BackupDir": backup_dir}
            return int(self.call("operations/copyfile", payload)["jobid"])

        payload: dict = {"srcFs": src, "dstFs": dst, "_async": True}
        if exclude:
            # i filtri per-chiamata passano dal blocco _filter (filter.Options)
            payload["_filter"] = {"ExcludeRule": list(exclude)}
        if backup_dir:
            # il cestino passa dal blocco _config: _filter.BackupDir e
            # _backup_dir vengono ignorati da rclone 1.75
            payload["_config"] = {"BackupDir": backup_dir}
        return int(self.call(endpoint, payload)["jobid"])

    def job_list(self) -> dict:
        """Tutti i job: {jobids, runningIds, finishedIds, executeId}."""
        return self.call("job/list")

    def job_status(self, jobid: int) -> dict:
        return self.call("job/status", {"jobid": int(jobid)})

    def stop_job(self, jobid: int) -> None:
        self.call("job/stop", {"jobid": int(jobid)})

    def stats(self, group: str | None = None) -> dict:
        return self.call("core/stats", {"group": group} if group else None)

    # ------------------------------------------------------------ cestino/dettagli

    def operations_list(self, fs: str, remote: str = "",
                        recurse: bool = True) -> list[dict]:
        """Elenca i file di un filesystem (usato per il cestino)."""
        data = self.call("operations/list",
                         {"fs": fs, "remote": remote,
                          "opt": {"recurse": recurse}}, timeout=60)
        return data.get("list", [])

    def purge(self, fs: str, remote: str = "") -> None:
        """Cancella un'intera cartella (usato per svuotare il cestino)."""
        self.call("operations/purge", {"fs": fs, "remote": remote}, timeout=120)
