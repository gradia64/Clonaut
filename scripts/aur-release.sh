#!/bin/bash
# Pubblica su AUR clonaut e clonaut-git di una release, dalla macchina del
# maintainer.
#
# La chiave SSH dell'account AUR non sta nella CI: vale per tutti i pacchetti
# dell'account, e chi ottenesse i secret potrebbe pubblicare un PKGBUILD
# qualsiasi. La CI costruisce e prova il PKGBUILD dal tag (job «arch» di
# release.yml); il push lo fa il maintainer con questo script:
#
# 1. verifica il tag con scripts/verify-tag.sh (firmato da una sottochiave
#    dei tag);
# 2. prende PKGBUILD e .SRCINFO di entrambi i pacchetti dal contenuto del tag,
#    non dalla cartella di lavoro: si pubblica ciò che il tag firmato contiene;
# 3. controlla che il pkgver del pacchetto stabile sia la versione del tag;
# 4. controlla che nella run di release.yml per quel tag il job «arch» sia
#    riuscito (CLONAUT_SKIP_CI_CHECK=1 lo salta, per i test);
# 5. pubblica con scripts/publish-aur.sh e la chiave SSH dell'utente
#    (~/.ssh/config, Host aur.archlinux.org).
#
# Uso: scripts/aur-release.sh vX.Y.Z
# CLONAUT_REPO e le variabili di scripts/verify-tag.sh esistono per i test.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TAG="${1:?uso: scripts/aur-release.sh vX.Y.Z}"
REPO="${CLONAUT_REPO:-$ROOT}"
VERSION="${TAG#v}"
[[ $TAG =~ ^v[0-9]+(\.[0-9]+)*$ ]] || { echo "tag non valido: $TAG" >&2; exit 1; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# 1. il tag è del maintainer
"$ROOT/scripts/verify-tag.sh" "$TAG"

# 2. i PKGBUILD del tag
git -C "$REPO" archive "refs/tags/$TAG" packaging/aur/clonaut packaging/aur/clonaut-git \
    | tar -x -C "$TMP"
AUR="$TMP/packaging/aur"

# 3. il pacchetto stabile è alla versione del tag
pkgver="$(sed -n 's/^pkgver=//p' "$AUR/clonaut/PKGBUILD")"
if [ "$pkgver" != "$VERSION" ]; then
    echo "il PKGBUILD di $TAG dice pkgver=$pkgver, non $VERSION" >&2
    exit 1
fi

# 4. la CI ha costruito e provato quel PKGBUILD su Arch
if [ -z "${CLONAUT_SKIP_CI_CHECK:-}" ]; then
    sha="$(git -C "$REPO" rev-parse "refs/tags/$TAG^{commit}")"
    run="$(cd "$REPO" && gh run list --workflow release.yml --branch "$TAG" --event push \
            --json databaseId,headSha --jq "map(select(.headSha == \"$sha\"))[0].databaseId")"
    if [ -z "$run" ] || [ "$run" = "null" ]; then
        echo "nessuna run di release.yml per $TAG ($sha): il tag è stato pubblicato?" >&2
        exit 1
    fi
    arch="$(cd "$REPO" && gh run view "$run" --json jobs \
            --jq '.jobs[] | select(.name == "Pacchetto AUR su Arch") | .conclusion')"
    if [ "$arch" != "success" ]; then
        echo "job «Pacchetto AUR su Arch» della run $run: ${arch:-assente}, non success" >&2
        exit 1
    fi
fi

# 5. pubblicazione con la chiave SSH dell'utente
"$ROOT/scripts/publish-aur.sh" "$AUR/clonaut" "$AUR/clonaut-git"
