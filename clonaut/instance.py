"""Una sola istanza di Clonaut per cartella di configurazione.

Due istanze scriverebbero le stesse impostazioni e programmazioni
(`settings.json`, `recurring.json`): l'ultima a salvare cancellerebbe le
modifiche dell'altra, e i giri ⏰ partirebbero due volte. La prima istanza
tiene un lock (flock) su `clonaut.lock` con dentro il suo PID; un secondo
avvio le manda SIGUSR1 ed esce, e lei porta in primo piano la finestra. Così
l'app resta raggiungibile anche se è ridotta in una tray che non si vede.

Niente QLocalServer: vive in QtNetwork, che l'AppImage non include.
"""

from __future__ import annotations

import fcntl
import os
import signal
import socket
from pathlib import Path

from .qtcompat import QtCore

RAISE_SIGNAL = signal.SIGUSR1


class InstanceLock:
    """Lock esclusivo su un file; resta preso finché l'oggetto vive."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._fd: int | None = None

    def acquire(self) -> bool:
        """True se questa è la prima istanza (lock preso)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            return False
        os.ftruncate(fd, 0)
        os.write(fd, str(os.getpid()).encode())
        self._fd = fd
        return True

    def owner_pid(self) -> int | None:
        """PID dell'istanza che tiene il lock, se leggibile."""
        try:
            pid = int(self.path.read_text().strip())
        except (OSError, ValueError):
            return None
        return pid if pid > 0 else None

    def release(self) -> None:
        if self._fd is not None:
            os.close(self._fd)   # chiudere il descrittore rilascia il flock
            self._fd = None


def ask_owner_to_raise(lock: InstanceLock) -> bool:
    """Dal secondo avvio: chiede alla prima istanza di mostrarsi. True se inviato."""
    pid = lock.owner_pid()
    if pid is None or pid == os.getpid():
        return False
    try:
        os.kill(pid, RAISE_SIGNAL)
    except OSError:
        return False
    return True


class RaiseListener(QtCore.QObject):
    """Nella prima istanza: chiama `callback` (thread GUI) a ogni SIGUSR1.

    Il gestore Python di un segnale gira solo quando l'interprete esegue
    codice, non mentre Qt aspetta eventi: con set_wakeup_fd il numero del
    segnale arriva su un socket, che Qt sorveglia come ogni altro evento.
    """

    def __init__(self, callback, parent=None):
        super().__init__(parent)
        self._callback = callback
        self._rsock, self._wsock = socket.socketpair()
        self._rsock.setblocking(False)
        self._wsock.setblocking(False)
        self._old_fd = signal.set_wakeup_fd(self._wsock.fileno())
        self._old_handler = signal.signal(RAISE_SIGNAL, lambda *_: None)
        self._notifier = QtCore.QSocketNotifier(
            self._rsock.fileno(), QtCore.QSocketNotifier.Type.Read, self)
        self._notifier.activated.connect(self._on_ready)

    def _on_ready(self, *_args) -> None:
        try:
            data = self._rsock.recv(64)
        except OSError:
            return
        if bytes([int(RAISE_SIGNAL)]) in data:
            self._callback()

    def close(self) -> None:
        self._notifier.setEnabled(False)
        signal.signal(RAISE_SIGNAL, self._old_handler)
        signal.set_wakeup_fd(self._old_fd)
        self._rsock.close()
        self._wsock.close()
