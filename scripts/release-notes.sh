#!/bin/bash
# Stampa le note di una release GitHub: la sezione «## [X.Y.Z]» di
# CHANGELOG.md, poi come installare e come verificare i file.
#
# Le usa release.yml (--notes-file); il job verify fallisce se la sezione
# manca o è vuota, così un tag non parte senza CHANGELOG.
#
# Uso: scripts/release-notes.sh X.Y.Z     (anche vX.Y.Z)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="${1:?uso: scripts/release-notes.sh <versione>}"
VERSION="${VERSION#v}"
CHANGELOG="${CLONAUT_CHANGELOG:-$ROOT/CHANGELOG.md}"
REPO="https://github.com/gradia64/Clonaut"

# dalla riga «## [X.Y.Z] …» alla prossima «## [», senza le righe vuote ai bordi
section="$(awk -v v="$VERSION" '
    /^## \[/ { inside = index($0, "## [" v "]") == 1; next }
    /^\[[^]]+\]: / { next }
    inside { print }
' "$CHANGELOG" | sed -e '/./,$!d' | sed -e ':a' -e '/^\n*$/{$d;N;ba' -e '}')"

if [ -z "$section" ]; then
    echo "CHANGELOG.md: manca la sezione «## [$VERSION]» (o è vuota)" >&2
    exit 1
fi

# impronta dalla fonte unica, versione di rclone dallo script dell'AppImage
. "$ROOT/scripts/release-keys.sh"
fpr="$(echo "$RELEASE_PRIMARY" | sed -E 's/(.{4})/\1 /g; s/ $//; s/^((.{4} ){5})/\1 /')"
rclone="$(sed -n 's/^RCLONE_VERSION="\(.*\)"/\1/p' "$ROOT/build-appimage.sh")"
prev="$(git -C "$ROOT" describe --tags --abbrev=0 "v$VERSION^" 2>/dev/null || true)"

cat <<EOF
$section

## Install

**Debian / Ubuntu**

\`\`\`bash
sudo apt install ./clonaut_${VERSION}_all.deb
\`\`\`

**Arch Linux (AUR)**

\`\`\`bash
yay -S clonaut
\`\`\`

**AppImage (any distribution, x86_64 or aarch64)**

\`\`\`bash
chmod +x Clonaut-${VERSION}-x86_64.AppImage
./Clonaut-${VERSION}-x86_64.AppImage
\`\`\`

The AppImage includes rclone ${rclone} as a fallback: an rclone
already installed on the system is used first.

## Verify

\`\`\`bash
sha256sum -c SHA256SUMS --ignore-missing
gh attestation verify Clonaut-${VERSION}-x86_64.AppImage -R gradia64/Clonaut
\`\`\`

The tag \`v${VERSION}\` is signed with the Clonaut release key
(\`${fpr}\`), see
[Verifying a release](${REPO}#verifying-a-release).
EOF
if [ -n "$prev" ]; then
    printf '\n**Full Changelog**: %s/compare/%s...v%s\n' "$REPO" "$prev" "$VERSION"
fi
