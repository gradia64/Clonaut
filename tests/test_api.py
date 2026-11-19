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
