"""Controlli dentro l'AppImage, eseguiti con il suo Python (smoke-test.sh).

APPDIR viene dall'ambiente, come lo imposta il runtime (e l'AppRun).
"""
import os
import subprocess
import sys
from pathlib import Path

APPDIR = Path(os.environ["APPDIR"])
sys.path.insert(0, str(APPDIR / "usr" / "share" / "clonaut"))
os.environ["CLONAUT_QT"] = "pyqt6"

from clonaut import __version__, rcd  # noqa: E402
from clonaut.qtcompat import BINDING, QtGui, QtWidgets  # noqa: E402

app = QtWidgets.QApplication(["clonaut"])

from clonaut.ui.main_window import MainWindow  # noqa: E402,F401
from clonaut.util import app_icon  # noqa: E402

assert BINDING.startswith("PyQt6"), BINDING
assert not app_icon().pixmap(64, 64).isNull(), "icona non disegnata"
icon = APPDIR / "usr/share/icons/hicolor/scalable/apps/io.github.gradia64.Clonaut.svg"
assert not QtGui.QIcon(str(icon)).pixmap(64, 64).isNull(), "icona SVG non caricata"
formats = {bytes(f).decode() for f in QtGui.QImageReader.supportedImageFormats()}
assert {"svg", "png", "jpeg"} <= formats, formats

# rclone di riserva: usato solo se non c'è altro (PATH vuoto, nessuna impostazione)
os.environ.pop("CLONAUT_RCLONE", None)
os.environ["PATH"] = "/nonexistent"
path, source, tried = rcd.find_rclone("")
assert path == str(APPDIR / "usr/bin/rclone"), (path, tried)
assert source == "incluso nell'AppImage", source
version = subprocess.run([path, "version"], capture_output=True, text=True,
                         check=True).stdout.splitlines()[0]

# TLS per requests (certifi) e per Qt
import requests  # noqa: E402,F401
import certifi  # noqa: E402
assert Path(certifi.where()).is_file()

print(f"AppImage di Clonaut {__version__} ({BINDING}): controlli OK, riserva {version}")
