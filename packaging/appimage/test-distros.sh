#!/bin/bash
# Prova un'AppImage già costruita su più distribuzioni, in container Docker.
#
#   packaging/appimage/test-distros.sh dist/Clonaut-X.Y.Z-x86_64.AppImage [immagine…]
#
# In ogni container: le sole librerie di base di un desktop (X11, GL,
# fontconfig, xkbcommon e xkbcommon-x11, D-Bus) più Xvfb, niente rclone e niente FUSE
# (APPIMAGE_EXTRACT_AND_RUN). GLib c'è su ogni desktop ma non nelle immagini
# minime: fa parte della base, come X11 e GL. L'app parte sul plugin X11 vero
# di Qt e deve essere viva dopo 10 secondi, senza errori, con un rclone rcd
# avviato dal rclone incluso. Se il plugin xcb non trova una libreria, la si vede qui
# (ldd), prima che la veda un utente.
#
# Per un'AppImage aarch64 su una macchina x86_64 serve l'emulazione di Docker
# (binfmt + qemu-user-static): le immagini vengono prese per linux/arm64.
set -euo pipefail

APPIMAGE_FILE="$(readlink -f "${1:?uso: test-distros.sh <file .AppImage> [immagine…]}")"
shift
IMAGES=("$@")
[ ${#IMAGES[@]} -gt 0 ] || IMAGES=(debian:12 ubuntu:22.04 ubuntu:24.04 fedora:latest
                                   archlinux:latest opensuse/tumbleweed:latest)
case "$APPIMAGE_FILE" in
    *-aarch64.AppImage) PLATFORM=linux/arm64 ;;
    *) PLATFORM=linux/amd64 ;;
esac

INNER="$(mktemp)"
trap 'rm -f "$INNER"' EXIT
cat > "$INNER" <<'EOF'
#!/bin/sh
set -eu
q() { "$@" >/tmp/install.log 2>&1 || { tail -20 /tmp/install.log; exit 1; }; }
if command -v apt-get >/dev/null; then
    export DEBIAN_FRONTEND=noninteractive
    q apt-get update
    q apt-get install -y --no-install-recommends xvfb libgl1 libegl1 libfontconfig1 \
        libxkbcommon0 libxkbcommon-x11-0 libxcb-render0 libxcb-shape0 libdbus-1-3 libx11-xcb1 libglib2.0-0 procps fonts-dejavu-core
elif command -v dnf >/dev/null; then
    q dnf install -y xorg-x11-server-Xvfb mesa-libGL mesa-libEGL fontconfig \
        libxkbcommon libxkbcommon-x11 dbus-libs glib2 procps-ng findutils dejavu-sans-fonts
elif command -v pacman >/dev/null; then
    q pacman -Syu --noconfirm --needed xorg-server-xvfb mesa fontconfig libxkbcommon \
        libxkbcommon-x11 dbus glib2 procps-ng findutils ttf-dejavu
elif command -v zypper >/dev/null; then
    q zypper --non-interactive install --no-recommends xorg-x11-server-Xvfb Mesa-libGL1 \
        Mesa-libEGL1 fontconfig libxkbcommon0 libxkbcommon-x11-0 \
        libxcb-render0 libxcb-shape0 libdbus-1-3 libX11-xcb1 libglib-2_0-0 libgthread-2_0-0 \
        procps findutils dejavu-fonts
fi
. /etc/os-release
echo "== $PRETTY_NAME, glibc $(ldd --version | head -1 | sed 's/.* //')"
if command -v rclone >/dev/null; then echo "rclone nel sistema: la prova non vale"; exit 1; fi

cd /tmp
cp /app/Clonaut.AppImage ./a.AppImage
./a.AppImage --appimage-extract >/dev/null
missing="$(find squashfs-root -path '*plugins/platforms/libqxcb.so' -exec ldd {} \; | grep 'not found' || true)"
if [ -n "$missing" ]; then echo "librerie mancanti per il plugin X11:"; echo "$missing"; exit 1; fi
rm -rf squashfs-root

Xvfb :99 -nolisten tcp >/dev/null 2>&1 &
sleep 2
export DISPLAY=:99 QT_QPA_PLATFORM=xcb XDG_CONFIG_HOME=/tmp/cfg XDG_CACHE_HOME=/tmp/cache \
       RCLONE_CONFIG=/tmp/rclone.conf APPIMAGE_EXTRACT_AND_RUN=1
set +e
# il codice di uscita su file: in alcune sh «wait <pid>» dà 127 per un
# processo già terminato, e il codice vero si perderebbe
(timeout 10 ./a.AppImage > app.log 2>&1; echo $? > rc) &
pid=$!
sleep 7
exe=""
for p in $(pgrep -x rclone); do
    e="$(readlink -f /proc/$p/exe)"
    case "$e" in /tmp/appimage_extracted_*/usr/bin/rclone) exe="$e" ;; esac
done
wait $pid
rc="$(cat rc)"
set -e
if [ "$rc" -ne 124 ]; then cat app.log; echo "uscita da sola (codice $rc)"; exit 1; fi
if grep -Eq 'Traceback|Error|error|Cannot load|could not' app.log; then cat app.log; exit 1; fi
[ -n "$exe" ] || { echo "rclone incluso non avviato"; exit 1; }
echo "OK: finestra su X11 per 10 s, rclone rcd dall'AppImage"
EOF
chmod 755 "$INNER"

fail=()
for image in "${IMAGES[@]}"; do
    if docker run --rm --platform "$PLATFORM" \
            -v "$APPIMAGE_FILE:/app/Clonaut.AppImage:ro" -v "$INNER:/inner.sh:ro" \
            "$image" /inner.sh; then
        :
    else
        echo "!! $image: FALLITO"
        fail+=("$image")
    fi
done
if [ ${#fail[@]} -gt 0 ]; then
    echo "falliti: ${fail[*]}" >&2
    exit 1
fi
echo "tutte le distribuzioni: OK"
