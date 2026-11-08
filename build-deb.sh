#!/usr/bin/env bash
# Costruisce build/clonaut_<versione>_all.deb dall'albero del progetto.
# Impostazioni opzionali:
#   MAINTAINER="Nome Cognome <email@dominio>"   (metadati del pacchetto)
set -euo pipefail
cd "$(dirname "$0")"

VER=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' clonaut/__init__.py)
APP_ID=io.github.gradia64.Clonaut
MAINTAINER="${MAINTAINER:-Gradia <gradia@disroot.org>}"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

mkdir -p "$STAGE/DEBIAN" \
         "$STAGE/usr/share/clonaut" \
         "$STAGE/usr/bin" \
         "$STAGE/usr/share/applications" \
         "$STAGE/usr/share/icons/hicolor/scalable/apps" \
         "$STAGE/usr/share/metainfo" \
         "$STAGE/usr/share/doc/clonaut" \
         "$STAGE/usr/share/man/man1"
chmod 0755 "$STAGE" "$STAGE/DEBIAN"

# applicazione
cp -r clonaut "$STAGE/usr/share/clonaut/clonaut"
cp main.py "$STAGE/usr/share/clonaut/main.py"
find "$STAGE/usr/share/clonaut" -type d -name '__pycache__' -prune -exec rm -rf {} +
find "$STAGE/usr/share/clonaut" -type d -exec chmod 0755 {} +
find "$STAGE/usr/share/clonaut" -type f -exec chmod 0644 {} +

# metadati e integrazione desktop
sed -e "s/@VERSION@/$VER/" -e "s|@MAINTAINER@|$MAINTAINER|" \
    packaging/control > "$STAGE/DEBIAN/control"
install -m 0755 packaging/clonaut         "$STAGE/usr/bin/clonaut"
install -m 0644 "packaging/$APP_ID.desktop" "$STAGE/usr/share/applications/$APP_ID.desktop"
install -m 0644 "packaging/$APP_ID.metainfo.xml" "$STAGE/usr/share/metainfo/$APP_ID.metainfo.xml"
install -m 0644 "packaging/icons/$APP_ID.svg" "$STAGE/usr/share/icons/hicolor/scalable/apps/$APP_ID.svg"
for size in 48 64 128 256; do
    install -D -m 0644 "packaging/icons/$APP_ID-$size.png" \
        "$STAGE/usr/share/icons/hicolor/${size}x${size}/apps/$APP_ID.png"
done
install -m 0644 README.md                    "$STAGE/usr/share/doc/clonaut/README"
install -m 0644 README.it.md                 "$STAGE/usr/share/doc/clonaut/README.it"
install -m 0644 CHANGELOG.md                 "$STAGE/usr/share/doc/clonaut/CHANGELOG.md"
install -m 0644 packaging/copyright          "$STAGE/usr/share/doc/clonaut/copyright"
sed -e "s|@MAINTAINER@|$MAINTAINER|" packaging/changelog \
    | gzip -9n > "$STAGE/usr/share/doc/clonaut/changelog.gz"
sed "s/@VERSION@/$VER/" packaging/clonaut.1 \
    | gzip -9n > "$STAGE/usr/share/man/man1/clonaut.1.gz"

# permessi canonici (la umask utente può lasciare 775/664)
find "$STAGE" -type d -exec chmod 0755 {} +
find "$STAGE" -type f -exec chmod 0644 {} +
chmod 0755 "$STAGE/usr/bin/clonaut"

mkdir -p build
dpkg-deb --root-owner-group --build "$STAGE" "build/clonaut_${VER}_all.deb"
echo "Creato: build/clonaut_${VER}_all.deb"
