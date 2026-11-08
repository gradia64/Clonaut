#!/usr/bin/env bash
# Prova i PKGBUILD AUR in un container Arch Linux pulito (funziona anche da Debian).
#
#   packaging/aur/test-in-docker.sh            # entrambi: clonaut e clonaut-git
#   packaging/aur/test-in-docker.sh clonaut    # solo il pacchetto stabile
#
# Il pacchetto stabile clona il repository locale e verifica davvero un tag
# firmato: nel container una chiave usa e getta firma v<versione> su HEAD e
# prende il posto della chiave di rilascio in validpgpkeys. Il -git clona il
# repository locale. Per ciascuno: makepkg con check() (suite pytest),
# namcap su PKGBUILD e pacchetto, installazione con pacman e avvio di prova.
# Alla fine copia in packaging/aur/<nome>/ il .SRCINFO generato dal PKGBUILD vero.
set -euo pipefail
cd "$(dirname "$0")/../.."
ROOT="$PWD"
TARGETS=("${@:-clonaut clonaut-git}")
read -r -a TARGETS <<< "${TARGETS[*]}"
VER=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' clonaut/__init__.py)
IMAGE="${IMAGE:-archlinux:latest}"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/out"
for t in "${TARGETS[@]}"; do cp -r "packaging/aur/$t" "$WORK/$t"; done

cat > "$WORK/inner.sh" <<'INNER'
#!/usr/bin/env bash
set -euo pipefail
VER="$1"; shift
pacman -Syu --noconfirm --needed base-devel git namcap sudo >/dev/null
useradd -m builder
echo 'builder ALL=(ALL) NOPASSWD: ALL' > /etc/sudoers.d/builder
sudo -u builder git config --global safe.directory '*'
sudo -u builder git config --global user.name 'Prova'
sudo -u builder git config --global user.email 'prova@example.org'

for t in "$@"; do
  echo "================ $t"
  dir=/home/builder/$t
  cp -r /work/$t "$dir"
  cp /work/$t/PKGBUILD /work/out/$t.PKGBUILD.orig
  if [ "$t" = clonaut ]; then
    # chiave usa e getta, tag firmato su un clone: makepkg deve verificarlo
    sudo -u builder gpg --batch --quiet --passphrase '' --quick-generate-key \
      'Prova <prova@example.org>' ed25519 sign 1d
    fpr=$(sudo -u builder gpg --with-colons --list-keys prova@example.org | awk -F: '$1=="fpr"{print $10; exit}')
    sudo -u builder git clone -q file:///repo /home/builder/src
    sudo -u builder git -C /home/builder/src -c gpg.format=openpgp \
      -c user.signingkey="$fpr" tag -f -s "v$VER" -m "Clonaut $VER"
    sed -i -e "s/^pkgver=.*/pkgver=$VER/" \
      -e "s|^source=.*|source=(\"\$pkgname::git+file:///home/builder/src#tag=v\$pkgver?signed\")|" \
      -e "s/^validpgpkeys=.*/validpgpkeys=('$fpr')/" "$dir/PKGBUILD"
  else
    sed -i 's|^source=.*|source=("$pkgname::git+file:///repo")|' "$dir/PKGBUILD"
  fi
  chown -R builder: "$dir"
  cd "$dir"
  sudo -u builder makepkg -s --noconfirm 2>&1 | grep -E "==>|passed|failed|error|signature|firma|PGP" || true
  pkg=$(ls "$dir"/*.pkg.tar.zst)
  echo "--- namcap PKGBUILD"; sudo -u builder namcap PKGBUILD || true
  echo "--- namcap pacchetto"; namcap "$pkg" || true
  pacman -U --noconfirm "$pkg" >/dev/null
  echo "--- installato: $(pacman -Q "$t")"
  QT_QPA_PLATFORM=offscreen clonaut --help | head -1
  python -c "import clonaut; print('versione Python:', clonaut.__version__)"
  pacman -Ql "$t" | grep -E "bin/clonaut|applications|metainfo|256x256|man1|licenses" | sed 's/^/    /'
  # .SRCINFO dal PKGBUILD originale (versione e sorgente veri)
  cp /work/out/$t.PKGBUILD.orig "$dir/PKGBUILD"
  sudo -u builder makepkg --printsrcinfo > /work/out/$t.SRCINFO
  pacman -R --noconfirm "$t" >/dev/null
done
INNER
chmod +x "$WORK/inner.sh"
chmod -R a+rX "$WORK"; chmod a+rwx "$WORK/out"

docker run --rm -v "$WORK:/work" -v "$ROOT/.git:/repo:ro" "$IMAGE" \
  /work/inner.sh "$VER" "${TARGETS[@]}"

for t in "${TARGETS[@]}"; do
  cp "$WORK/out/$t.SRCINFO" "packaging/aur/$t/.SRCINFO"
  echo "Aggiornato packaging/aur/$t/.SRCINFO"
done
