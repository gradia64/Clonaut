#!/bin/bash
# Controlla che un tag di rilascio corrisponda a ciò che il codice dichiara:
#   - clonaut/__init__.py (la sola fonte della versione)
#   - la prima <release> della metainfo AppStream
#   - la prima voce di packaging/changelog (Debian)
#   - una sezione «## [X.Y.Z]» in CHANGELOG.md (scripts/release-notes.sh)
#   - pkgver del PKGBUILD AUR stabile
# Lo usa il job verify di release.yml; si può lanciare a mano prima del tag.
#
# Uso: scripts/check-version.sh vX.Y.Z
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TAG="${1:?uso: scripts/check-version.sh vX.Y.Z}"
[[ "$TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "tag non valido: $TAG (serve vX.Y.Z)" >&2; exit 1; }
VERSION="${TAG#v}"

fail=0
check() {   # check <dove> <versione trovata>
    if [ "$2" = "$VERSION" ]; then
        echo "ok  $1: $2"
    else
        echo "NO  $1: «$2», il tag dice $VERSION" >&2
        fail=1
    fi
}

check clonaut/__init__.py "$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$ROOT/clonaut/__init__.py")"
check "metainfo <release>" "$(grep -m1 -o '<release version="[^"]*"' \
    "$ROOT/packaging/io.github.gradia64.Clonaut.metainfo.xml" | cut -d'"' -f2)"
check packaging/changelog "$(sed -n '1s/^clonaut (\([^)]*\)).*/\1/p' "$ROOT/packaging/changelog")"
check "PKGBUILD AUR" "$(sed -n 's/^pkgver=//p' "$ROOT/packaging/aur/clonaut/PKGBUILD")"
if "$ROOT/scripts/release-notes.sh" "$VERSION" >/dev/null; then
    echo "ok  CHANGELOG.md: sezione [$VERSION]"
else
    fail=1
fi
exit "$fail"
