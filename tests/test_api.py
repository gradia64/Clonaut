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
