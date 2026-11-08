#!/bin/bash
# Prova di un'AppImage già costruita, senza FUSE e senza rete (salvo pytest,
# vedi sotto).
#
#   1. controlli con il Python dell'AppImage (smoke_check.py): binding, icone,
#      formati immagine, rclone di riserva scelto solo quando manca il resto
#   2. l'intera suite di test eseguita con il Python, il Qt e il pacchetto
#      clonaut dell'AppImage, e con il suo rclone
#   3. avvio dell'app completa (offscreen e, con xvfb-run, su X11) senza
#      rclone nel PATH: deve essere ancora viva dopo qualche secondo
#
# pytest non è nell'AppImage: lo installa per l'occasione in una cartella
# temporanea il pip di sistema (rete o cache), e passa per PYTHONPATH.
# Impostazioni e config di rclone sempre in una cartella temporanea.
#
# Uso: packaging/appimage/smoke-test.sh dist/Clonaut-X.Y.Z-x86_64.AppImage
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
APPIMAGE_FILE="$(readlink -f "${1:?uso: smoke-test.sh <file .AppImage>}")"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export QT_QPA_PLATFORM=offscreen
export XDG_CONFIG_HOME="$TMP/config" XDG_CACHE_HOME="$TMP/cache" \
       RCLONE_CONFIG="$TMP/rclone.conf"

# Sotto emulazione qemu (AppImage aarch64 provata su x86_64) la regola binfmt
# vuole a zero i byte 8-10 dell'intestazione ELF, dove le AppImage scrivono
# «AI\x02»: con APPIMAGE_ZERO_MAGIC=1 si prova una copia con quei byte azzerati
# (il runtime non li legge). Su una macchina ARM vera non serve.
if [ "${APPIMAGE_ZERO_MAGIC:-}" = 1 ]; then
    cp "$APPIMAGE_FILE" "$TMP/Clonaut.AppImage"
    printf '\000\000\000' | dd of="$TMP/Clonaut.AppImage" bs=1 seek=8 conv=notrunc status=none
    APPIMAGE_FILE="$TMP/Clonaut.AppImage"
fi

cd "$TMP"
"$APPIMAGE_FILE" --appimage-extract >/dev/null
APPDIR_X="$TMP/squashfs-root"
PY="$APPDIR_X/usr/python/bin/python3"

echo "== controlli nell'AppImage"
APPDIR="$APPDIR_X" "$PY" -E -s "$ROOT/packaging/appimage/smoke_check.py"

echo "== suite di test con il Python dell'AppImage"
python3 -m pip install --quiet --disable-pip-version-check --target "$TMP/pytest" \
    "pytest>=8.0"
cd "$ROOT"
# il clonaut dell'AppImage davanti a tutto: si prova quello che si spedisce;
# rclone: quello incluso
CLONAUT_QT=pyqt6 TMPDIR="$TMP" PATH="$APPDIR_X/usr/bin:/usr/bin:/bin" \
    PYTHONPATH="$APPDIR_X/usr/share/clonaut:$TMP/pytest" \
    "$PY" -s -m pytest -q -p no:cacheprovider --basetemp="$TMP/pytest-tmp" tests \
    > "$TMP/pytest.log" 2>&1 || {
        tail -40 "$TMP/pytest.log"
        echo "suite fallita con il Python dell'AppImage" >&2
        exit 1
    }
echo "suite: $(tail -1 "$TMP/pytest.log")"

# un PATH con tutti i comandi del sistema tranne rclone: /bin non basta, su
# molte distribuzioni è un collegamento a /usr/bin
mkdir -p "$TMP/bin"
for f in /usr/bin/* /bin/*; do
    case "$(basename "$f")" in rclone) continue ;; esac
    ln -s "$f" "$TMP/bin/" 2>/dev/null || true   # i doppioni di /bin restano a /usr/bin
done

# avvia l'AppImage per 10 secondi (SMOKE_RUN/SMOKE_WAIT: tempi più lunghi
# sotto emulazione): deve essere ancora aperta e senza errori
run_app() {   # run_app <descrizione> [prefisso del comando…]
    local what="$1" rc
    shift
    echo "== avvio dell'app completa ($what, senza rclone nel PATH)"
    mkdir -p "$TMP/run"
    set +e
    # TMPDIR: la copia estratta dal runtime resta se il processo viene ucciso
    APPIMAGE_EXTRACT_AND_RUN=1 TMPDIR="$TMP/run" PATH="$TMP/bin" \
        "$@" timeout "${SMOKE_RUN:-10}" "$APPIMAGE_FILE" > "$TMP/app.log" 2>&1 &
    local pid=$! exe="" d e c
    # a metà strada: quale rclone ha avviato l'app? Deve essere quello incluso.
    # /proc/<pid>/exe, oppure la riga di comando sotto qemu (lì exe è
    # l'interprete e il programma vero è tra gli argomenti)
    sleep "${SMOKE_WAIT:-6}"
    for d in /proc/[0-9]*; do
        e="$(readlink -f "$d/exe" 2>/dev/null || true)"
        c="$(tr '\000' ' ' < "$d/cmdline" 2>/dev/null || true)"
        case "$e $c" in
            *"$TMP/run/"*/usr/bin/rclone*rcd*) exe="$TMP/run/${c##*"$TMP/run/"}"; exe="${exe%% rcd*}" ;;
        esac
    done
    wait "$pid"
    rc=$?
    set -e
    if [ "$rc" -ne 124 ]; then
        cat "$TMP/app.log"
        echo "l'app è uscita da sola (codice $rc) invece di restare aperta" >&2
        exit 1
    fi
    if grep -Eq 'Traceback|Error|error' "$TMP/app.log"; then
        cat "$TMP/app.log"
        echo "errori nell'output dell'app" >&2
        exit 1
    fi
    if [ -z "$exe" ]; then
        pgrep -a rclone >&2 || true
        echo "l'app non ha avviato il rclone incluso nell'AppImage" >&2
        exit 1
    fi
    echo "rclone rcd avviato: ${exe#"$TMP/run/"}"
    echo "avvio OK"
}

run_app offscreen

# con un server X virtuale si carica davvero il plugin X11 di Qt, con le
# librerie xcb-util incluse nell'AppImage: offscreen non le tocca
if command -v xvfb-run >/dev/null; then
    QT_QPA_PLATFORM=xcb run_app "X11, xvfb" \
        xvfb-run -a sh -c '"$@"; rc=$?; sleep 3; exit $rc' sh
else
    echo "== X11 saltato: xvfb-run non installato (pacchetto xvfb)"
fi
