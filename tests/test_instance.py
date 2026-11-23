"""Istanza unica: lock sulla cartella di configurazione e richiamo della finestra."""

import os
import signal

from clonaut.instance import InstanceLock, RaiseListener, ask_owner_to_raise
from conftest import spin


def test_seconda_istanza_non_prende_il_lock(tmp_path):
    first, second = InstanceLock(tmp_path / "c.lock"), InstanceLock(tmp_path / "c.lock")
    assert first.acquire()
    assert not second.acquire()
    assert second.owner_pid() == os.getpid()
    assert (tmp_path / "c.lock").stat().st_mode & 0o777 == 0o600
    first.release()
    assert second.acquire()          # la prima è uscita: si riparte
    second.release()


def test_senza_pid_leggibile_non_si_manda_nulla(tmp_path):
    lock = InstanceLock(tmp_path / "c.lock")
    (tmp_path / "c.lock").write_text("niente")
    assert not ask_owner_to_raise(lock)


def test_sigusr1_porta_in_primo_piano(qapp):
    calls = []
    listener = RaiseListener(lambda: calls.append(1))
    try:
        os.kill(os.getpid(), signal.SIGUSR1)
        assert spin(qapp, 5, until=lambda: calls)
    finally:
        listener.close()
