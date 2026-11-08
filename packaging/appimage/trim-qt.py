"""Riduce PyQt6 nell'AppDir a ciò che Clonaut usa.

Uso: python3 trim-qt.py <cartella PyQt6 nell'AppDir>

Si tengono i moduli Python importati da Clonaut (clonaut/qtcompat.py: QtCore,
QtGui, QtWidgets), il modulo sip e i plugin Qt utili su un desktop Linux (X11,
Wayland, portali, immagini, metodi di input). Le librerie in Qt6/lib
restano solo se servono a qualcosa di ciò che resta: le dipendenze si leggono
dalle voci NEEDED degli ELF (readelf -d, che legge anche gli ELF aarch64),
così un plugin non può perdere una libreria per errore. Il resto (QML, Quick,
Designer, Multimedia, strumenti, stub .pyi) se ne va. Dei cataloghi di Qt
resta qtbase_it: i pulsanti e i dialoghi che Qt disegna da sé.

Ripreso dall'AppImage di Plico, adattato alla struttura delle wheel PyQt6.
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

MODULES = {"QtCore", "QtGui", "QtWidgets"}
QT_CATALOGS = {"qtbase_it.qm", "qtbase_en.qm"}
PLUGINS = {
    "platforms": {"libqxcb.so", "libqwayland.so", "libqoffscreen.so", "libqminimal.so"},
    "wayland-decoration-client": None,           # None: tutta la cartella
    "wayland-shell-integration": None,
    "wayland-graphics-integration-client": None,
    "xcbglintegrations": None,
    "platformthemes": {"libqxdgdesktopportal.so", "libqgtk3.so"},  # finestre dei file
    "platforminputcontexts": {"libcomposeplatforminputcontextplugin.so",
                              "libibusplatforminputcontextplugin.so"},
    "iconengines": None,                          # icone SVG del tema
    "imageformats": {"libqsvg.so", "libqjpeg.so", "libqgif.so", "libqico.so"},
    # niente "tls": Clonaut parla con rclone via requests, non con QtNetwork,
    # e i plugin TLS si porterebbero dietro QtNetwork con Kerberos e brotli
}
KEEP_TOP = {"__init__.py", "py.typed", "Qt6"}


def needed(elf: Path) -> set[str]:
    out = subprocess.run(["readelf", "-d", str(elf)], capture_output=True,
                         text=True, check=True).stdout
    return set(re.findall(r"\(NEEDED\).*\[(.+)\]", out))


def remove(p: Path) -> None:
    if p.is_dir() and not p.is_symlink():
        shutil.rmtree(p)
    else:
        p.unlink()


def main(root: Path) -> None:
    qt = root / "Qt6"
    keep_mods = {f"{m}.abi3.so" for m in MODULES}
    for p in root.iterdir():
        if p.name in KEEP_TOP or p.name in keep_mods or (
                p.name.startswith("sip.") and p.suffix == ".so"):
            continue
        remove(p)

    plugins = qt / "plugins"
    for d in plugins.iterdir():
        allowed = PLUGINS.get(d.name, set())
        if allowed is None:
            continue
        for f in d.iterdir():
            if f.name not in allowed:
                remove(f)
        if not any(d.iterdir()):
            d.rmdir()
    for name in ("qml", "qsci", "metatypes", "libexec", "bin", "mkspecs"):
        if (qt / name).exists():
            remove(qt / name)
    translations = qt / "translations"
    if translations.exists():
        for f in translations.iterdir():
            if f.name not in QT_CATALOGS:
                remove(f)

    # chiusura delle dipendenze dentro Qt6/lib, partendo da moduli e plugin
    lib = qt / "lib"
    available = {p.name for p in lib.iterdir()}
    todo = [p for p in root.iterdir() if p.suffix == ".so"]
    todo += list(plugins.rglob("*.so"))
    keep, seen = set(), set()
    while todo:
        elf = todo.pop()
        if elf in seen:
            continue
        seen.add(elf)
        for dep in needed(elf) & available:
            if dep not in keep:
                keep.add(dep)
                todo.append(lib / dep)
    for p in lib.iterdir():
        if p.name not in keep:
            remove(p)
    print("Qt6/lib:", " ".join(sorted(keep)))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
