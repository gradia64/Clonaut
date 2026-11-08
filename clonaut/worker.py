"""Thread di polling: raccoglie lo stato dei job «osservati» e le statistiche.

Nota architetturale importante: in rclone OGNI chiamata rc crea un job (anche
`job/status` e `core/stats`); usare `job/list` come fonte della coda farebbe
esplodere l'elenco con le chiamate del polling stesso. Si osservano quindi
solo i job che conosciamo:
  - quelli avviati dalla GUI (register(), chiamato a ogni nuovo trasferimento)
  - quelli trovati in `job/list` al primo tick (sessione precedente)
  - quelli rilevati come attivi dai gruppi presenti nelle stats aggregate
    (così vengono visti anche i job avviati da altri client mentre girano)
"""

from __future__ import annotations

import threading
import time

import requests

from .api import ApiError, RcloneApi
from .qtcompat import Signal, QThread
from .util import fmt_duration, human_size

INTERVAL = 0.9          # secondi tra un tick e l'altro
MAX_WATCHED = 200       # quanti job osservati tenere nello snapshot (i più recenti)


class DryRunWorker(QThread):
    """Prova a vuoto su un rcd dedicato avviato con --dry-run globale.

    Il job parte in async sul backend delle prove e il thread ne segue lo
    stato finché non è finito; al termine pubblica un riepilogo (file, byte,
    durata). Nessuna scrittura è possibile su quel backend.
    """

    done = Signal(str, bool, str)   # key, ok, riepilogo o messaggio d'errore

    POLL = 0.3
    TIMEOUT = 3600.0

    def __init__(self, api: RcloneApi, key: str, mode: str, src: str, dst: str,
                 exclude: list[str] | None = None, backup_dir: str | None = None):
        super().__init__()
        self._api = api
        self._key = key
        self._mode = mode
        self._src = src
        self._dst = dst
        self._exclude = exclude
        self._backup_dir = backup_dir
        self._stop = False

    def stop(self) -> None:
        """Interrompe l'attesa (uscita dall'app): il risultato non viene emesso."""
        self._stop = True

    def run(self) -> None:
        try:
            jobid = self._api.start_transfer(self._mode, self._src, self._dst,
                                             exclude=self._exclude,
                                             backup_dir=self._backup_dir)
        except Exception as exc:  # noqa: BLE001 — l'errore va mostrato in coda
            self.done.emit(self._key, False, str(exc))
            return

        deadline = time.monotonic() + self.TIMEOUT
        errors_in_row = 0
        while time.monotonic() < deadline and not self._stop:
            try:
                status = self._api.job_status(jobid)
                errors_in_row = 0
            except Exception:  # noqa: BLE001 — transitori: riproviamo
                errors_in_row += 1
                if errors_in_row >= 30:
                    self.done.emit(self._key, False,
                                   "il backend delle prove non risponde")
                    return
                time.sleep(self.POLL)
                continue
            if status.get("finished"):
                if status.get("success"):
                    try:
                        stats = self._api.stats(f"job/{jobid}")
                    except Exception:  # noqa: BLE001 — stats non critiche
                        stats = {}
                    riepilogo = (f"{int(stats.get('transfers') or 0)} file, "
                                 f"{human_size(stats.get('bytes'))}")
                    deletes = int(stats.get("deletes") or 0)
                    if deletes:
                        riepilogo += f", {deletes} da eliminare"
                    riepilogo += f" in {fmt_duration(status.get('duration'))}"
                    self.done.emit(self._key, True, riepilogo)
                else:
                    self.done.emit(self._key, False,
                                   status.get("error") or "errore sconosciuto")
                return
            time.sleep(self.POLL)
        if not self._stop:
            self.done.emit(self._key, False, "timeout della prova (1h)")


class PollWorker(QThread):
    """Esegue il polling in un thread separato e pubblica snapshot alla UI.

    Per ogni job osservato lo snapshot contiene:
      - "status": job/status (per i finiti viene richiesto una sola volta)
      - "stats":  core/stats del gruppo "job/<id>" (per i finiti, una sola volta)
    """

    ready = Signal(dict)    # snapshot {"agg": ..., "jobs": {jid: {...}}}
    failed = Signal(str)    # rcd irraggiungibile / errore di polling

    def __init__(self, api: RcloneApi):
        super().__init__()
        self._api = api
        self._stop = False
        self._watched: set[int] = set()
        self._unvalidated: set[int] = set()   # adottati al primo tick: da validare
        self._started_once = False
        self._status_cache: dict[int, dict] = {}
        self._stats_cache: dict[int, dict] = {}
        self._final_stats: set[int] = set()   # job finiti di cui abbiamo le stats finali
        self._forgotten: set[int] = set()     # tolti dalla UI: non riadottarli
        # la watch-list è toccata sia dal thread GUI (register/forget) sia da qui
        self._lock = threading.Lock()

    def register(self, jobid: int) -> None:
        """Aggiunge un job alla watch-list (chiamato dalla UI a ogni avvio)."""
        with self._lock:
            self._watched.add(int(jobid))

    def forget(self, jobid: int) -> None:
        """Smette di osservare un job finito (es. «Rimuovi completati»)."""
        jid = int(jobid)
        with self._lock:
            self._watched.discard(jid)
            self._unvalidated.discard(jid)
            self._forgotten.add(jid)
            self._status_cache.pop(jid, None)
            self._stats_cache.pop(jid, None)
            self._final_stats.discard(jid)

    def stop(self) -> None:
        self._stop = True

    # ------------------------------------------------------------------ raccolta

    def _discover_initial(self) -> None:
        """Al primo tick: adotta i job già presenti nel rcd (sessione precedente).

        Vengono validati al primo snapshot: i job «interni» del rcd (ogni
        chiamata rc ne crea uno) con 0 byte trasferiti e nessun errore vengono
        scartati per non riempire la coda di rumore.
        """
        if self._started_once:
            return
        self._started_once = True
        try:
            ids = self._api.job_list().get("jobids", [])
            adopted = {int(i) for i in ids[-MAX_WATCHED:]}
            with self._lock:
                self._watched |= adopted
                self._unvalidated |= adopted
        except ApiError:
            pass

    def _snapshot(self) -> dict:
        self._discover_initial()

        # stats aggregate: servono per l'header e per scovare job esterni attivi
        agg: dict = {}
        try:
            agg = self._api.stats()
        except ApiError:
            pass
        for tf in agg.get("transferring") or []:
            grp = str(tf.get("group") or "")
            if grp.startswith("job/"):
                try:
                    jid = int(grp.split("/", 1)[1])
                except ValueError:
                    continue
                with self._lock:
                    if jid not in self._forgotten:
                        self._watched.add(jid)

        with self._lock:
            watched = sorted(self._watched)[-MAX_WATCHED:]
        jobs: dict[int, dict] = {}
        for jid in watched:
            status = self._status_cache.get(jid)
            if status is None:
                try:
                    status = self._api.job_status(jid)
                except ApiError:
                    continue  # race transitoria: riproveremo al prossimo tick
                if status.get("finished"):
                    self._status_cache[jid] = status

            if status.get("finished"):
                # un'ultima lettura al termine, per i numeri finali (100%)
                if jid not in self._final_stats:
                    self._final_stats.add(jid)
                    try:
                        self._stats_cache[jid] = self._api.stats(f"job/{jid}")
                    except ApiError:
                        pass   # conserviamo l'ultimo campione noto
                stats = self._stats_cache.get(jid) or {}
            else:
                try:
                    stats = self._api.stats(f"job/{jid}")
                except ApiError:
                    stats = self._stats_cache.get(jid) or {}
                self._stats_cache[jid] = stats

            if jid in self._unvalidated:
                self._unvalidated.discard(jid)
                if (status.get("finished") and status.get("success")
                        and not (stats.get("totalBytes") or 0)
                        and not (stats.get("bytes") or 0)):
                    with self._lock:
                        self._watched.discard(jid)   # rumore interno: non mostrarlo
                    continue

            jobs[jid] = {"status": status, "stats": stats}

        return {"agg": agg, "jobs": jobs}

    # ---------------------------------------------------------------------- run

    def run(self) -> None:
        while not self._stop:
            try:
                self.ready.emit(self._snapshot())
            except (requests.RequestException, ApiError) as exc:
                self.failed.emit(str(exc))
            except Exception as exc:  # non lasciare che il thread muoia in silenzio
                self.failed.emit(f"{type(exc).__name__}: {exc}")
            end = time.monotonic() + INTERVAL
            while not self._stop and time.monotonic() < end:
                time.sleep(0.05)
