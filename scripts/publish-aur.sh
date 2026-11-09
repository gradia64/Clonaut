#!/bin/bash
# Pubblica PKGBUILD e .SRCINFO di un pacchetto (packaging/aur/<nome>/) nel
# suo repository AUR. Stesso schema di Plico e OllaDesk.
#
# Chiave SSH dell'account AUR:
#   AUR_SSH_PRIVATE_KEY   chiave privata (secret della CI), scritta in un file
#                         temporaneo 0600 e cancellata alla fine
#   altrimenti            la configurazione SSH dell'utente (uso locale)
#
# La chiave host di aur.archlinux.org è fissata qui sotto (impronte pubblicate
# su https://aur.archlinux.org): niente fiducia al primo contatto. Il primo
# push crea il pacchetto su AUR.
#
# Uso: scripts/publish-aur.sh packaging/aur/clonaut [packaging/aur/clonaut-git]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
[ "$#" -gt 0 ] || { echo "uso: scripts/publish-aur.sh packaging/aur/<nome>…" >&2; exit 2; }
AUR_HOSTKEY="aur.archlinux.org ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIEuBKrPzbawxA/k2g6NcyV5jmqwJ2s+zpgZGZ7tpLIcN"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
printf '%s\n' "$AUR_HOSTKEY" > "$TMP/known_hosts"
SSH_CMD="ssh -o UserKnownHostsFile=$TMP/known_hosts -o StrictHostKeyChecking=yes"
if [ -n "${AUR_SSH_PRIVATE_KEY:-}" ]; then
    (umask 077 && printf '%s\n' "$AUR_SSH_PRIVATE_KEY" > "$TMP/id_aur")
    SSH_CMD="$SSH_CMD -i $TMP/id_aur -o IdentitiesOnly=yes"
fi
export GIT_SSH_COMMAND="$SSH_CMD"

for dir in "$@"; do
    for f in PKGBUILD .SRCINFO; do
        [ -f "$dir/$f" ] || { echo "manca $dir/$f" >&2; exit 1; }
    done
    name="$(sed -n 's/^pkgname=//p' "$dir/PKGBUILD")"
    version="$(sed -n 's/^pkgver=//p' "$dir/PKGBUILD")"
    # .SRCINFO è quello che l'AUR mostra e che gli helper leggono: deve dire
    # la stessa versione del PKGBUILD (lo rigenera test-in-docker.sh)
    srcinfo="$(sed -n 's/^\tpkgver = //p' "$dir/.SRCINFO")"
    if [ "$srcinfo" != "$version" ]; then
        echo "$dir/.SRCINFO dice $srcinfo, il PKGBUILD $version: rigeneralo" >&2
        exit 1
    fi
    # un pacchetto che si costruisce da un tag: il tag deve essere clonabile
    # da CHIUNQUE, senza credenziali, o sull'AUR nessuno riuscirebbe a
    # costruirlo
    # shellcheck disable=SC2016  # $pkgver letterale, come nel PKGBUILD
    if grep -qF '#tag=v$pkgver' "$dir/PKGBUILD" && [ -z "${AUR_SKIP_SOURCE_CHECK:-}" ]; then
        url="$(sed -n "s/^url='\(.*\)'$/\1/p" "$dir/PKGBUILD")"
        if ! GIT_TERMINAL_PROMPT=0 git -c credential.helper= ls-remote --exit-code --tags \
                "$url.git" "refs/tags/v$version" >/dev/null 2>&1; then
            echo "tag v$version non clonabile pubblicamente da $url.git" >&2
            exit 1
        fi
    fi

    remote="${AUR_REMOTE_BASE:-ssh://aur@aur.archlinux.org}/$name.git"   # override solo per i test
    repo="$TMP/$name"
    git clone --quiet "$remote" "$repo"
    cp "$dir/PKGBUILD" "$dir/.SRCINFO" "$repo/"
    git -C "$repo" add PKGBUILD .SRCINFO
    if git -C "$repo" diff --cached --quiet; then
        echo "AUR già aggiornato: $name $version"
        continue
    fi
    git -C "$repo" -c user.name="${AUR_GIT_NAME:-gradia}" \
        -c user.email="${AUR_GIT_EMAIL:-gradia@disroot.org}" \
        commit --quiet -m "$name $version"
    git -C "$repo" push --quiet origin HEAD:master
    echo "pubblicato su AUR: $name $version"
done
