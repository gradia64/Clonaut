"""Trasferimenti veri via rc: copia, file singolo, esclusioni, cestino, prova a vuoto."""

import pytest

from clonaut.api import ApiError, is_remote
from clonaut.worker import DryRunWorker
from conftest import needs_rclone, spin

pytestmark = needs_rclone


def _wait_job(ctx, jobid, timeout=20):
    import time
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        status = ctx.api.job_status(jobid)
        if status.get("finished"):
            return status
        time.sleep(0.1)
    raise AssertionError(f"job {jobid} non finito")


def test_is_remote():
    assert is_remote("gdrive:Documenti")
    assert is_remote("nas:")
    assert not is_remote("/home/utente/cartella")
    assert not is_remote("./relativo/a:b")


def test_copy_directory_with_exclude(rcd, tree):
    jid = rcd.api.start_transfer("copy", str(tree / "a"), str(tree / "c"),
                                 exclude=["*.tmp"])
    assert _wait_job(rcd, jid)["success"]
    assert (tree / "c" / "sub" / "deep.txt").read_text() == "profondo"
    assert not (tree / "c" / "skip.tmp").exists()


def test_copy_single_file_into_dir_and_renamed(rcd, tree):
    (tree / "c").mkdir()
    jid = rcd.api.start_transfer("copy", str(tree / "a" / "new.txt"), str(tree / "c"))
    assert _wait_job(rcd, jid)["success"]
    assert (tree / "c" / "new.txt").exists()
    jid = rcd.api.start_transfer("copy", str(tree / "a" / "new.txt"),
                                 str(tree / "c" / "rinominato.txt"))
    assert _wait_job(rcd, jid)["success"]
    assert (tree / "c" / "rinominato.txt").read_text() == "nuovo"


def test_move_single_file_is_refused(rcd, tree):
    with pytest.raises(ApiError):
        rcd.api.start_transfer("move", str(tree / "a" / "new.txt"), str(tree / "b"))


def test_sync_moves_deleted_files_to_trash(rcd, tree):
    trash = tree / "b-cestino"
    jid = rcd.api.start_transfer("sync", str(tree / "a"), str(tree / "b"),
                                 backup_dir=str(trash))
    assert _wait_job(rcd, jid)["success"]
    assert not (tree / "b" / "extra1").exists()
    assert (trash / "extra1").read_text() == "x"      # nel cestino, non perso


def test_dry_run_counts_deletions_and_writes_nothing(rcd, tree, qapp):
    api = rcd.ensure_dry_backend()
    results = []
    worker = DryRunWorker(api, "k", "sync", str(tree / "a"), str(tree / "b"),
                          exclude=["*.tmp"])
    worker.done.connect(lambda key, ok, msg: results.append((ok, msg)))
    worker.start()
    assert spin(qapp, 20, until=lambda: results)
    worker.wait(2000)
    ok, message = results[0]
    assert ok, message
    assert "2 da eliminare" in message
    assert sorted(p.name for p in (tree / "b").iterdir()) == ["extra1", "extra2"]


def test_dead_daemon_is_an_api_error():
    """rcd chiuso: ApiError (gestito da timer e dialoghi), non ConnectionError."""
    from clonaut.api import ApiError, RcloneApi
    from clonaut.rcd import free_port
    api = RcloneApi(f"http://127.0.0.1:{free_port()}", "u", "p", timeout=2)
    with pytest.raises(ApiError, match="non risponde"):
        api.start_transfer("copy", "/tmp", "/tmp/x")


def test_demone_locale_ignora_proxy_e_netrc(monkeypatch):
    """Il rcd locale non passa da un proxy dell'ambiente né usa ~/.netrc."""
    from clonaut.api import RcloneApi
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.invalid:3128")
    assert RcloneApi("http://127.0.0.1:5572", "u", "p").session.trust_env is False
    assert RcloneApi("http://localhost:5572").session.trust_env is False
    # un rcd agganciato altrove segue le impostazioni dell'utente (proxy, CA)
    assert RcloneApi("https://nas.example:5572", "u", "p").session.trust_env is True


# --- chiusura: il polling non deve tenere ferma l'uscita (revisioni esterne) ---

class _SlowApi:
    """API finta: registra le chiamate e i timeout chiesti."""

    def __init__(self, worker_box):
        self.calls = []
        self.box = worker_box

    def job_list(self, timeout=None):
        self.calls.append(("job/list", timeout))
        return {"jobids": []}

    def stats(self, group=None, timeout=None):
        self.calls.append(("core/stats", timeout))
        return {}

    def job_status(self, jid, timeout=None):
        self.calls.append(("job/status", timeout))
        self.box[0].stop()   # l'uscita arriva durante il primo job
        return {"finished": False}


def test_poll_snapshot_si_ferma_tra_un_job_e_l_altro():
    """Con 200 job osservati, l'uscita aspettava fino a 400 chiamate da 20 s."""
    from clonaut.worker import POLL_TIMEOUT, PollWorker
    box = []
    api = _SlowApi(box)
    worker = PollWorker(api)
    box.append(worker)
    for jid in range(1, 51):
        worker.register(jid)
    worker._snapshot()
    assert [c for c, _t in api.calls].count("job/status") == 1
    assert all(t is not None and t <= POLL_TIMEOUT < 20 for _c, t in api.calls)


def test_thread_ancora_in_esecuzione_non_viene_distrutto(qapp):
    import gc
    import time
    from clonaut.qtcompat import QThread
    from clonaut import worker as worker_mod

    class Busy(QThread):
        def run(self):
            time.sleep(0.5)   # una chiamata rc che non ritorna subito

    thread = Busy()
    thread.start()
    assert not worker_mod.stop_thread(thread, 10)
    del thread
    gc.collect()                       # senza riferimento: abort del processo
    assert worker_mod._lingering and worker_mod._lingering[0].isRunning()
    assert worker_mod.wait_lingering(3000)
    assert worker_mod._lingering == []


def test_backend_delle_prove_morto_viene_riavviato(rcd, tree):
    """P2-9: se il rcd delle prove muore, la prova successiva ne avvia un altro."""
    first = rcd.ensure_dry_backend()
    assert rcd.ensure_dry_backend() is first          # vivo: riusato
    rcd.rcd_dry.proc.kill()
    rcd.rcd_dry.proc.wait(5)
    second = rcd.ensure_dry_backend()
    assert second is not first
    assert rcd.rcd_dry.proc.poll() is None
    assert second.ping().get("version")


# --- PollWorker sotto carico (P2-12) ---

class _FakeApi:
    """API finta per il PollWorker: job finiti, stats che possono fallire."""

    def __init__(self, finished=(), failing_stats=0):
        self.finished = set(finished)
        self.failing_stats = failing_stats   # quante letture di stats fallire
        self.stats_calls = []

    def job_list(self, timeout=None):
        return {"jobids": []}

    def job_status(self, jid, timeout=None):
        return {"finished": jid in self.finished, "success": True}

    def stats(self, group=None, timeout=None):
        from clonaut.api import ApiError
        if group is None:
            return {}
        self.stats_calls.append(group)
        if self.failing_stats:
            self.failing_stats -= 1
            raise ApiError("lento")
        return {"bytes": 10, "totalBytes": 10}


def test_stats_finali_ritentate_se_falliscono():
    from clonaut.worker import PollWorker
    api = _FakeApi(finished={7}, failing_stats=1)
    worker = PollWorker(api)
    worker.register(7)
    assert worker._snapshot()["jobs"][7]["stats"] == {}      # lettura fallita
    assert worker._snapshot()["jobs"][7]["stats"]["bytes"] == 10   # ritentata
    worker._snapshot()
    assert api.stats_calls.count("job/7") == 2               # poi più nulla


def test_stats_finali_non_ritentate_all_infinito():
    from clonaut.worker import FINAL_STATS_TRIES, PollWorker
    api = _FakeApi(finished={7}, failing_stats=100)
    worker = PollWorker(api)
    worker.register(7)
    for _ in range(FINAL_STATS_TRIES + 3):
        worker._snapshot()
    assert api.stats_calls.count("job/7") == FINAL_STATS_TRIES


def test_job_finiti_vecchi_potati_quelli_in_corso_restano():
    from clonaut.worker import MAX_WATCHED, PollWorker
    total = MAX_WATCHED + 50
    api = _FakeApi(finished=set(range(2, total + 1)))   # il job 1 è ancora in corso
    worker = PollWorker(api)
    for jid in range(1, total + 1):
        worker.register(jid)
    worker._snapshot()                       # legge e mette in cache i finiti
    jobs = worker._snapshot()["jobs"]
    assert 1 in jobs                         # in corso: mai potato
    assert len(jobs) == MAX_WATCHED + 1
    assert len(worker._watched) == MAX_WATCHED + 1
    assert len(worker._status_cache) == MAX_WATCHED
    assert len(worker._stats_cache) <= MAX_WATCHED + 1


def test_job_dimenticato_durante_la_lettura_non_torna_in_cache():
    from clonaut.worker import PollWorker

    class Api(_FakeApi):
        def job_status(self, jid, timeout=None):
            worker.forget(jid)               # «Rimuovi completati» a metà lettura
            return super().job_status(jid, timeout)

    api = Api(finished={5})
    worker = PollWorker(api)
    worker.register(5)
    assert 5 not in worker._snapshot()["jobs"]
    assert 5 not in worker._status_cache and 5 not in worker._stats_cache


def test_elenco_dei_dimenticati_limitato():
    from clonaut.worker import MAX_FORGOTTEN, PollWorker
    worker = PollWorker(_FakeApi())
    for jid in range(1, MAX_FORGOTTEN + 101):
        worker.forget(jid)
    assert len(worker._forgotten) <= MAX_FORGOTTEN
    assert MAX_FORGOTTEN + 100 in worker._forgotten


def test_cestino_con_tilde_espanso(monkeypatch, tmp_path):
    from clonaut.api import RcloneApi
    monkeypatch.setenv("HOME", str(tmp_path))
    api = RcloneApi("http://127.0.0.1:1")
    sent = []
    monkeypatch.setattr(api, "call", lambda ep, payload=None, timeout=None:
                        sent.append(payload) or {"jobid": 1})
    api.start_transfer("sync", str(tmp_path), str(tmp_path / "b"), backup_dir="~/Cestino")
    api.start_transfer("sync", str(tmp_path), "demo:b", backup_dir="demo:~cestino")
    assert sent[0]["_config"]["BackupDir"] == str(tmp_path / "Cestino")
    assert sent[1]["_config"]["BackupDir"] == "demo:~cestino"


def test_backend_delle_prove_usa_il_percorso_delle_impostazioni(monkeypatch):
    from clonaut import appctx, settings
    seen = []
    monkeypatch.setattr(settings, "load", lambda: {"rclone_path": "/opt/rclone"})
    monkeypatch.setattr(appctx, "find_rclone", lambda path="": seen.append(path) or (None, "", []))
    ctx = appctx.AppContext(api=None)
    with pytest.raises(RuntimeError, match="rclone non trovato"):
        ctx.ensure_dry_backend()
    assert seen == ["/opt/rclone"]
