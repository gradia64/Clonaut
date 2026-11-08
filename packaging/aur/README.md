# AUR packages

Two packages for the [Arch User Repository](https://aur.archlinux.org):

| Package | Builds from | Version |
|---|---|---|
| [`clonaut`](clonaut/PKGBUILD) | the signed release tag `v$pkgver` (`?signed`) | the release, e.g. `0.4.0` |
| [`clonaut-git`](clonaut-git/PKGBUILD) | the latest commit on `main` | from `git describe`, e.g. `0.4.0.r3.gabc1234` |

Both build a wheel with `python-build`, run the test suite in `check()`
(Qt offscreen, PyQt6, the system `rclone`) and install the desktop entry,
AppStream metadata, icons, man page and license.

## Test locally (any distribution with Docker)

```bash
packaging/aur/test-in-docker.sh              # both packages
packaging/aur/test-in-docker.sh clonaut      # only the stable one
```

It runs `makepkg` (with tests), `namcap`, installs the package with `pacman`
and starts `clonaut --help` in a clean `archlinux:latest` container. For the
stable package a throw-away key signs `v<version>` on a clone of the local
repository and takes the release key's place in `validpgpkeys`, so the
signature check really runs and this works before the real tag exists. At the end it refreshes `.SRCINFO` next to
each `PKGBUILD`.

## First publication (once)

1. Create an account on <https://aur.archlinux.org> and add your **SSH public
   key** in *My Account*.
2. Configure SSH for the AUR (`~/.ssh/config`):

   ```
   Host aur.archlinux.org
     IdentityFile ~/.ssh/aur
     User aur
   ```

3. For each package, clone the (empty) AUR repository and copy the files:

   ```bash
   git clone ssh://aur@aur.archlinux.org/clonaut.git aur-clonaut
   cp packaging/aur/clonaut/{PKGBUILD,.SRCINFO} aur-clonaut/
   cd aur-clonaut && git add PKGBUILD .SRCINFO
   git commit -m "Initial release 0.4.0" && git push
   ```

   Same for `clonaut-git` (its `pkgver` is refreshed by `makepkg`, no need to
   bump it by hand).

## On every release (stable package)

The source is the signed git tag, so there is no checksum to update
(`sha256sums=('SKIP')` is correct: the tag signature covers it) and
`validpgpkeys` holds the release key's primary fingerprint, which a subkey
rotation does not change. After the signed tag `vX.Y.Z` is pushed to GitHub:

```bash
cd packaging/aur/clonaut
sed -i 's/^pkgver=.*/pkgver=X.Y.Z/; s/^pkgrel=.*/pkgrel=1/' PKGBUILD
makepkg --printsrcinfo > .SRCINFO
```

Then copy `PKGBUILD` and `.SRCINFO` to the AUR clone, commit and push. Users
need the public key once: `gpg --import packaging/clonaut-release-key.asc`
(or `gpg --recv-keys` from a keyserver, once it is published there).
