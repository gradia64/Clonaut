#!/bin/bash
# Costruisce l'AppImage di Clonaut: dist/Clonaut-<versione>-<arch>.AppImage
# (+ .zsync per l'aggiornamento con AppImageUpdate / Gear Lever).
#
#   ./build-appimage.sh              x86_64
#   ./build-appimage.sh aarch64      ARM64, costruita anche da una macchina x86_64
#   ./build-appimage.sh --lock       rigenera packaging/appimage/requirements-*.txt
#
# Contenuto (AppDir):
#   AppRun                           avvio (packaging/appimage/AppRun)
#   usr/python/                      Python portatile (python-build-standalone)
#                                    con PyQt6 (Qt ridotto a ciò che serve) e requests
#   usr/share/clonaut/clonaut/       pacchetto Python
#   usr/share/clonaut/launcher.py    avvio senza -m (vedi il file)
#   usr/bin/rclone                   rclone ufficiale, statico: solo di RISERVA,
#                                    un rclone nel PATH o nelle impostazioni vince
#   usr/share/{applications,icons,metainfo,doc}/  e in cima .desktop e icona
#
# Tutto ciò che si scarica ha versione e SHA-256 fissati qui o nei
# requirements-<arch>.txt (pip --require-hashes) e passa per
# build/appimage/downloads/. La versione è letta da clonaut/__init__.py.
#
# Stesso schema dell'AppImage di Plico (stesso autore): stesso Python, stesse
# librerie xcb, stessi controlli. pip e compileall girano sempre con il Python
# x86_64 della macchina che costruisce (pip --platform per l'aarch64): così
# l'AppImage ARM si costruisce senza emulazione. Si costruisce solo su x86_64.
# Strumenti richiesti: curl, sha256sum, dpkg-deb, readelf (binutils), file
# (per appimagetool), git; appstreamcli è facoltativo (validazione metadati).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

APP_ID="io.github.gradia64.Clonaut"
HOST_ARCH="x86_64"

PBS_RELEASE="20260929"
PBS_PYTHON="3.12.14"
pbs_file() { echo "cpython-${PBS_PYTHON}+${PBS_RELEASE}-$1-unknown-linux-gnu-install_only_stripped.tar.gz"; }
pbs_url() { echo "https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_RELEASE}/$(pbs_file "$1")"; }
declare -A PBS_SHA256=(
    [x86_64]="ef605200f8174e87ecfc308e52a88127543f85dd5c940dc5e92cab244b98a003"
    [aarch64]="706111f834ae1557314f48b7293ddc72cc96e952aa75c5d31f56c2b7ddeac3d3"
)

APPIMAGETOOL_VERSION="1.9.1"
APPIMAGETOOL_URL="https://github.com/AppImage/appimagetool/releases/download/${APPIMAGETOOL_VERSION}/appimagetool-${HOST_ARCH}.AppImage"
APPIMAGETOOL_SHA256="ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0"

# runtime type2 statico: l'AppImage non chiede libfuse2 al sistema
RUNTIME_VERSION="20251108"
declare -A RUNTIME_SHA256=(
    [x86_64]="2fca8b443c92510f1483a883f60061ad09b46b978b2631c807cd873a47ec260d"
    [aarch64]="00cbdfcf917cc6c0ff6d3347d59e0ca1f7f45a6df1a428a0d6d8a78664d87444"
)

# rclone ufficiale (SHA256SUMS di downloads.rclone.org) e la sua licenza MIT
RCLONE_VERSION="1.76.0"
declare -A RCLONE_ARCH=([x86_64]="amd64" [aarch64]="arm64")
declare -A RCLONE_SHA256=(
    [x86_64]="b00f00b3266c3764413afe599d3ec316f6f43b3e0ea8a0bc1d186d2133e46df7"
    [aarch64]="ee169016675e23a69d77240565133ff7dbc9b33d16fa8f7053d4af39f1eaeb78"
)
RCLONE_COPYING_SHA256="8cd2e9e750b90a04b7d82dbbca3930c696ae0309d7c10464f90a44f45754cd04"

# patchelf (wheel PyPI con il binario statico): dà RUNPATH $ORIGIN alle
# librerie xcb-util prese dai pacchetti Ubuntu, che non ne hanno
PATCHELF_URL="https://files.pythonhosted.org/packages/e7/03/afd9bdd2ba5f96997196109f25dadbe5141bc6e70dffd85f3f84cc85d69c/patchelf-0.19.1.0-py3-none-manylinux1_x86_64.manylinux_2_5_x86_64.musllinux_1_1_x86_64.whl"
PATCHELF_SHA256="a8f6331ccf40c345507279f755f4a38c2cb00b9efda746fd43c17713cce0aba4"

# glibc massima richiesta dai file dell'AppImage: quella delle wheel di PyQt6
declare -A GLIBC_MAX=([x86_64]="2.34" [aarch64]="2.39")

# Il plugin X11 di Qt 6 vuole le librerie xcb-util, che mancano in molte
# installazioni (libxcb-cursor0 su Ubuntu 22.04, per esempio): vanno nella
# cartella delle librerie Qt, dove il RUNPATH dei plugin le trova. Vengono
# dai pacchetti di Ubuntu 22.04 (simboli fino a glibc 2.34), non dal sistema
# che costruisce. Le librerie di base (libxcb, libX11, libxkbcommon, GL,
# fontconfig, Wayland, GLib…) restano quelle del sistema, come in ogni
# AppImage, e con loro le estensioni che nascono dagli stessi sorgenti
# (libxcb-render/-shape/-xkb, libxkbcommon-x11): una libxkbcommon-x11 1.4
# accanto alla libxkbcommon più recente di Arch o Fedora manda in crash il
# plugin X11 (provato con packaging/appimage/test-distros.sh).
XCB_DEBS_x86_64=(
    "https://archive.ubuntu.com/ubuntu/pool/universe/x/xcb-util-cursor/libxcb-cursor0_0.1.1-4ubuntu1_amd64.deb c9b5d1ad4af57397b1bd77e0a92750e34419def134c0282a0836ae9efc07cf64 libxcb-cursor.so.0"
    "https://archive.ubuntu.com/ubuntu/pool/main/x/xcb-util-wm/libxcb-icccm4_0.4.1-1.1build2_amd64.deb 4dfe14a0ce681b823b740dabb3de84b3ce0958c9a404af61823b11f64047b0ef libxcb-icccm.so.4"
    "https://archive.ubuntu.com/ubuntu/pool/main/x/xcb-util-image/libxcb-image0_0.4.0-2_amd64.deb b52babc3b4f2aa5241cac3a7888ce3b37d25a7f18867cae180e8cd11ec945cb9 libxcb-image.so.0"
    "https://archive.ubuntu.com/ubuntu/pool/main/x/xcb-util-keysyms/libxcb-keysyms1_0.4.0-1build3_amd64.deb 1d62f96a793cc1aa0df860de3f7d83edea2fa461d97e2b3d4d7f7e7a10e55f42 libxcb-keysyms.so.1"
    "https://archive.ubuntu.com/ubuntu/pool/main/x/xcb-util-renderutil/libxcb-render-util0_0.3.9-1build3_amd64.deb f87659a2369430ed2acb1cdae54a06fa9d60727a6545594e213173ddb4377727 libxcb-render-util.so.0"
    "https://archive.ubuntu.com/ubuntu/pool/main/x/xcb-util/libxcb-util1_0.4.0-1build2_amd64.deb 237d51a378b93c1669ff193084ebeb6422fe1e2ea96c2e9a0099eac40992a345 libxcb-util.so.1"
)
XCB_DEBS_aarch64=(
    "https://ports.ubuntu.com/ubuntu-ports/pool/universe/x/xcb-util-cursor/libxcb-cursor0_0.1.1-4ubuntu1_arm64.deb cd51860d7a40be6fe72bf9f69aac60e7cf7ae70994d5a7ea3aa82dfe0232f96a libxcb-cursor.so.0"
    "https://ports.ubuntu.com/ubuntu-ports/pool/main/x/xcb-util-wm/libxcb-icccm4_0.4.1-1.1build2_arm64.deb c9717fa2b7bbf77fd013094443e9fd6254a6400951c2f322f35bbd58c5ca3a08 libxcb-icccm.so.4"
    "https://ports.ubuntu.com/ubuntu-ports/pool/main/x/xcb-util-image/libxcb-image0_0.4.0-2_arm64.deb 5a66b078bcc423768c26422db0f3acb0556d06ec8266a472a6352153600f0e42 libxcb-image.so.0"
    "https://ports.ubuntu.com/ubuntu-ports/pool/main/x/xcb-util-keysyms/libxcb-keysyms1_0.4.0-1build3_arm64.deb f2ccc3dbfd81b409a43a72488e1f8ac2f65e46723e71ab408d94d50a21628374 libxcb-keysyms.so.1"
    "https://ports.ubuntu.com/ubuntu-ports/pool/main/x/xcb-util-renderutil/libxcb-render-util0_0.3.9-1build3_arm64.deb 6b6d181a909aa96287d90498a49ccfad41a9837326986936e9b53ec385e5b7e2 libxcb-render-util.so.0"
    "https://ports.ubuntu.com/ubuntu-ports/pool/main/x/xcb-util/libxcb-util1_0.4.0-1build2_arm64.deb ee67ecc591a1aab0490b74adf188e1d4ed509077a1c7b84f68dc6fddeb1fb2c0 libxcb-util.so.1"
)
declare -A DEB_LIBDIR=([x86_64]="x86_64-linux-gnu" [aarch64]="aarch64-linux-gnu")

WORK="$ROOT/build/appimage"
DOWNLOADS="$WORK/downloads"
REQ_IN="packaging/appimage/requirements.in"
req_txt() { echo "packaging/appimage/requirements-$1.txt"; }

if [ "$(uname -m)" != "$HOST_ARCH" ]; then
    echo "l'AppImage si costruisce solo su una macchina $HOST_ARCH (anche quella aarch64)" >&2
    exit 1
fi

sha_ok() {   # sha_ok <sha256> <file>
    echo "$1  $2" | sha256sum -c --quiet - >/dev/null 2>&1
}

# scarica una volta sola e verifica lo SHA-256 a ogni uso: un file in cache
# con l'hash sbagliato si riscarica una volta, un download con l'hash
# sbagliato non entra mai in cache
fetch() {   # fetch <url> <sha256> [nome in cache]
    local url="$1" sha="$2" out="$DOWNLOADS/${3:-$(basename "$1")}"
    mkdir -p "$DOWNLOADS"
    if [ -f "$out" ] && ! sha_ok "$sha" "$out"; then
        echo "$(basename "$out") in cache con SHA-256 errato: lo riscarico" >&2
        rm -f "$out"
    fi
    if [ ! -f "$out" ]; then
        curl -fsSL --proto '=https' --tlsv1.2 -o "$out.part" "$url"
        if ! sha_ok "$sha" "$out.part"; then
            rm -f "$out.part"
            echo "SHA-256 errato per $url: download rifiutato" >&2
            exit 1
        fi
        mv "$out.part" "$out"
    fi
    printf '%s\n' "$out"
}

unpack_python() {   # unpack_python <arch> <cartella>
    local tarball
    tarball="$(fetch "$(pbs_url "$1")" "${PBS_SHA256[$1]}")"
    rm -rf "$2"
    mkdir -p "$2"
    tar -xzf "$tarball" -C "$2" --strip-components=1
}

# Python della macchina che costruisce: pip, compileall e i controlli
HOSTPY_DIR="$WORK/hostpython"
if [ ! -x "$HOSTPY_DIR/bin/python3" ]; then
    unpack_python "$HOST_ARCH" "$HOSTPY_DIR"
fi
HOSTPY="$HOSTPY_DIR/bin/python3"

# pip per un'altra piattaforma: wheel per <arch> e il Python dell'AppImage
pip_target() {   # pip_target <arch> <argomenti di pip install…>
    local arch="$1" y platforms=()
    shift
    # con --platform pip non scende da solo alle etichette più vecchie: tutte
    # le manylinux_2_y fino alla glibc massima, più i vecchi alias
    for ((y = ${GLIBC_MAX[$arch]#2.}; y >= 5; y--)); do
        platforms+=(--platform "manylinux_2_${y}_${arch}")
    done
    platforms+=(--platform "manylinux2014_${arch}")
    [ "$arch" = x86_64 ] && platforms+=(--platform manylinux2010_x86_64 --platform manylinux1_x86_64)
    "$HOSTPY" -m pip install --isolated --quiet --disable-pip-version-check \
        --root-user-action=ignore --no-cache-dir --only-binary=:all: \
        "${platforms[@]}" --python-version "${PBS_PYTHON%.*}" \
        --implementation cp --abi cp312 --abi abi3 --abi none "$@"
}

if [ "${1:-}" = "--lock" ]; then
    TMP="$(mktemp -d)"
    trap 'rm -rf "$TMP"' EXIT
    for arch in x86_64 aarch64; do
        # stessa piattaforma dell'AppImage: il report di pip ha lo SHA-256
        # di ogni wheel scelta
        pip_target "$arch" --dry-run --ignore-installed --target "$TMP/t-$arch" \
            --report "$TMP/report-$arch.json" -r "$REQ_IN"
        "$HOSTPY" - "$TMP/report-$arch.json" "$arch" > "$(req_txt "$arch")" <<'EOF'
import json, sys
report = json.load(open(sys.argv[1]))
print("# Generato da ./build-appimage.sh --lock: non modificare a mano.")
print(f"# {sys.argv[2]}: versioni da requirements.in, dipendenze risolte da pip.")
for item in sorted(report["install"], key=lambda i: i["metadata"]["name"].lower()):
    meta, info = item["metadata"], item["download_info"]
    sha = info["archive_info"]["hashes"]["sha256"]
    print(f'{meta["name"]}=={meta["version"]} \\\n    --hash=sha256:{sha}')
EOF
        echo "scritto $(req_txt "$arch")"
    done
    exit 0
fi

ARCH="${1:-x86_64}"
case "$ARCH" in
    x86_64) XCB_DEBS=("${XCB_DEBS_x86_64[@]}") ;;
    aarch64) XCB_DEBS=("${XCB_DEBS_aarch64[@]}") ;;
    *) echo "architettura non supportata: $ARCH (x86_64 o aarch64)" >&2; exit 1 ;;
esac

VERSION="$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' clonaut/__init__.py)"
if [ -z "$VERSION" ]; then
    echo "versione non trovata in clonaut/__init__.py" >&2
    exit 1
fi

# build riproducibile: mtime, .pyc e squashfs dall'ultimo commit
if [ -z "${SOURCE_DATE_EPOCH:-}" ]; then
    SOURCE_DATE_EPOCH="$(git log -1 --format=%ct 2>/dev/null || date +%s)"
fi
export SOURCE_DATE_EPOCH

APPDIR="$WORK/AppDir-$ARCH"
rm -rf "$APPDIR"
mkdir -p "$APPDIR"

# --- Python e dipendenze ----------------------------------------------------
unpack_python "$ARCH" "$APPDIR/usr/python"
PYDIR="$APPDIR/usr/python"
PYVER="${PBS_PYTHON%.*}"
SITE="$PYDIR/lib/python$PYVER/site-packages"
STDLIB="$PYDIR/lib/python$PYVER"
pip_target "$ARCH" --no-compile --require-hashes --no-deps --upgrade \
    --target "$SITE" -r "$(req_txt "$ARCH")"

# pip, Tk, IDLE e i test servono solo a costruire o non servono affatto
rm -rf "$SITE"/pip "$SITE"/pip-*.dist-info "$SITE"/bin \
       "$STDLIB"/{ensurepip,idlelib,tkinter,turtledemo,test,unittest/test,lib2to3} \
       "$STDLIB"/lib-dynload/_tkinter*.so \
       "$STDLIB"/lib-dynload/_crypt*.so "$STDLIB"/crypt.py \
       "$PYDIR"/lib/{tcl,tk,itcl,thread}* \
       "$PYDIR"/lib/libtcl* "$PYDIR"/lib/libtk* \
       "$PYDIR"/share "$PYDIR"/include
find "$PYDIR/bin" -mindepth 1 ! -name python3 ! -name "python$PYVER" -delete

# --- Qt: solo ciò che Clonaut usa -------------------------------------------
"$HOSTPY" -E -s packaging/appimage/trim-qt.py "$SITE/PyQt6"

PATCHELF="$WORK/tools/patchelf"
if [ ! -x "$PATCHELF" ]; then
    whl="$(fetch "$PATCHELF_URL" "$PATCHELF_SHA256")"
    mkdir -p "$WORK/tools"
    "$HOSTPY" -E -s - "$whl" "$PATCHELF" <<'EOF'
import shutil, sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as z:
    name = next(n for n in z.namelist() if n.endswith("/scripts/patchelf"))
    with z.open(name) as src, open(sys.argv[2], "wb") as dst:
        shutil.copyfileobj(src, dst)
EOF
    chmod 755 "$PATCHELF"
fi

LIBDIR="${DEB_LIBDIR[$ARCH]}"
XCB_TMP="$WORK/xcb-$ARCH"
rm -rf "$XCB_TMP"
for entry in "${XCB_DEBS[@]}"; do
    read -r url sha so <<< "$entry"
    deb="$(fetch "$url" "$sha")"
    dpkg-deb -x "$deb" "$XCB_TMP"
    install -m 644 "$(readlink -f "$XCB_TMP/usr/lib/$LIBDIR/$so")" "$SITE/PyQt6/Qt6/lib/$so"
    # senza RUNPATH una di queste che ne vuole un'altra (libxcb-image →
    # libxcb-util) la cerca solo nel sistema: su x86_64 la trova perché Qt
    # l'ha già caricata, sulle wheel aarch64 no
    "$PATCHELF" --set-rpath '$ORIGIN' "$SITE/PyQt6/Qt6/lib/$so"
done
rm -rf "$XCB_TMP"

# --- Clonaut ------------------------------------------------------------------
SHARE="$APPDIR/usr/share/clonaut"
mkdir -p "$SHARE"
cp -r clonaut "$SHARE/clonaut"
find "$SHARE" -type d -name __pycache__ -prune -exec rm -rf {} +
install -m 644 packaging/appimage/launcher.py "$SHARE/launcher.py"
install -m 755 packaging/appimage/AppRun "$APPDIR/AppRun"
install -D -m 644 LICENSE "$APPDIR/usr/share/doc/clonaut/LICENSE"

# --- rclone di riserva --------------------------------------------------------
RCLONE_NAME="rclone-v${RCLONE_VERSION}-linux-${RCLONE_ARCH[$ARCH]}"
zip="$(fetch "https://downloads.rclone.org/v${RCLONE_VERSION}/${RCLONE_NAME}.zip" "${RCLONE_SHA256[$ARCH]}")"
mkdir -p "$APPDIR/usr/bin"
"$HOSTPY" -E -s - "$zip" "$RCLONE_NAME/rclone" "$APPDIR/usr/bin/rclone" <<'EOF'
import shutil, sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as z, z.open(sys.argv[2]) as src, open(sys.argv[3], "wb") as dst:
    shutil.copyfileobj(src, dst)
EOF
chmod 755 "$APPDIR/usr/bin/rclone"
copying="$(fetch "https://raw.githubusercontent.com/rclone/rclone/v${RCLONE_VERSION}/COPYING" \
    "$RCLONE_COPYING_SHA256" "rclone-${RCLONE_VERSION}-COPYING")"
install -D -m 644 "$copying" "$APPDIR/usr/share/doc/rclone/COPYING"

# --- integrazione desktop -----------------------------------------------------
install -D -m 644 "packaging/$APP_ID.desktop" "$APPDIR/usr/share/applications/$APP_ID.desktop"
install -D -m 644 "packaging/icons/$APP_ID.svg" \
    "$APPDIR/usr/share/icons/hicolor/scalable/apps/$APP_ID.svg"
for size in 48 64 128 256; do
    install -D -m 644 "packaging/icons/$APP_ID-$size.png" \
        "$APPDIR/usr/share/icons/hicolor/${size}x${size}/apps/$APP_ID.png"
done
install -D -m 644 "packaging/$APP_ID.metainfo.xml" "$APPDIR/usr/share/metainfo/$APP_ID.metainfo.xml"
# appimagetool (e AppImageHub) cercano ancora il vecchio nome .appdata.xml
ln -s "$APP_ID.metainfo.xml" "$APPDIR/usr/share/metainfo/$APP_ID.appdata.xml"
ln -s "usr/share/applications/$APP_ID.desktop" "$APPDIR/$APP_ID.desktop"
ln -s "usr/share/icons/hicolor/scalable/apps/$APP_ID.svg" "$APPDIR/$APP_ID.svg"
ln -s "usr/share/icons/hicolor/256x256/apps/$APP_ID.png" "$APPDIR/.DirIcon"

# --- bytecode e date --------------------------------------------------------
# l'immagine è in sola lettura: senza .pyc Python ricompilerebbe tutto a ogni
# avvio. Stesso Python (3.12) della macchina che costruisce, quindi .pyc
# validi anche per l'aarch64. unchecked-hash: .pyc identici a ogni build;
# -s/-p: nei .pyc il percorso è /usr/…, non la cartella della build.
find "$APPDIR" -type d -name __pycache__ -prune -exec rm -rf {} +
"$HOSTPY" -B -E -s -m compileall -q -f -j 0 --invalidation-mode unchecked-hash \
    -s "$APPDIR" -p / "$PYDIR/lib" "$SHARE"
# RECORD serve solo a pip uninstall
find "$SITE" -path '*.dist-info/RECORD' -delete
# permessi indipendenti dall'umask di chi costruisce (squashfs li conserva)
chmod -R u+rwX,go+rX,go-w "$APPDIR"
find "$APPDIR" -exec touch -h -d "@$SOURCE_DATE_EPOCH" {} +

# --- compatibilità: nessun file oltre la glibc delle wheel di PyQt6 ----------
"$HOSTPY" -E -s packaging/appimage/check-glibc.py "$APPDIR" "${GLIBC_MAX[$ARCH]}"

# --- immagine -----------------------------------------------------------------
TOOL="$(fetch "$APPIMAGETOOL_URL" "$APPIMAGETOOL_SHA256")"
RUNTIME="$(fetch "https://github.com/AppImage/type2-runtime/releases/download/${RUNTIME_VERSION}/runtime-${ARCH}" \
    "${RUNTIME_SHA256[$ARCH]}")"
chmod +x "$TOOL"
mkdir -p dist
# percorso assoluto: appimagetool fa chdir($OWD) se OWD è nell'ambiente
OUT="$ROOT/dist/Clonaut-${VERSION}-${ARCH}.AppImage"
rm -f "$OUT" "$OUT.zsync"
# metadati validati qui senza rete: gli screenshot su GitHub esistono solo
# dopo il push
if command -v appstreamcli >/dev/null; then
    appstreamcli validate-tree --no-net "$APPDIR" >/dev/null
fi
# extract-and-run: niente FUSE richiesto per appimagetool (CI, container).
# -u: informazioni di aggiornamento nell'immagine + file .zsync accanto
rm -rf "$WORK/tmp"
mkdir -p "$WORK/tmp"
(cd "$ROOT/dist" && ARCH="$ARCH" APPIMAGE_EXTRACT_AND_RUN=1 TMPDIR="$WORK/tmp" "$TOOL" --no-appstream \
    --runtime-file "$RUNTIME" \
    -u "gh-releases-zsync|gradia64|Clonaut|latest|Clonaut-*-${ARCH}.AppImage.zsync" \
    "$APPDIR" "$OUT" >/dev/null)
rm -rf "$WORK/tmp"
echo "dist/$(basename "$OUT") ($(du -h "$OUT" | cut -f1))"
[ -f "$OUT.zsync" ] && echo "dist/$(basename "$OUT").zsync"
exit 0
