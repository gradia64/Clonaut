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

## Publishing (from the maintainer's machine)

The release workflow `.github/workflows/release.yml` tests, the maintainer
publishes:

- the `arch` job builds the real `PKGBUILD` in a clean `archlinux:base-devel`
  container: `makepkg` clones the tag from GitHub and **verifies its
  signature** with the release key, runs the tests in `check()`, then namcap
  (errors only), install, a test start, and a check that `.SRCINFO` in the
  repository matches the `PKGBUILD`;
- after the GitHub release, publish both packages from your machine:

  ```bash
  scripts/aur-release.sh vX.Y.Z
  ```

  It verifies the tag with `scripts/verify-tag.sh`, takes `PKGBUILD` and
  `.SRCINFO` of both packages from the **tagged content** (not the working
  tree), checks that the stable `pkgver` is the tag's version and that the
  `arch` job of the tag's run succeeded (via `gh`), then pushes with
  `scripts/publish-aur.sh` (pinned AUR host key; a package whose files did
  not change is skipped, so it can be re-run).

The AUR SSH key is not in CI: an AUR key gives access to every package of the
account, so whoever read a CI secret could publish any PKGBUILD. The key lives
on your machine, preferably with a passphrase, in `~/.ssh/config`:

```
Host aur.archlinux.org
    User aur
    IdentityFile ~/.ssh/<your AUR key>
    IdentitiesOnly yes
```

Up to 0.4.0 the workflow pushed with the secret `AUR_SSH_PRIVATE_KEY`
(`~/.ssh/aur_clonaut_ci`); that secret and the key on the AUR account are
gone.

`gh workflow run release.yml -R gradia64/Clonaut -f aur_tag=vX.Y.Z` still
runs `verify` and `arch` on an already published tag, without publishing:
useful to re-test a PKGBUILD. For a tag whose run predates the `arch` job
(0.4.0), `CLONAUT_SKIP_CI_CHECK=1 scripts/aur-release.sh v0.4.0` skips that
check.

## On every release (stable package)

The source is the signed git tag, so there is no checksum to update
(`sha256sums=('SKIP')` is correct: the tag signature covers it) and
`validpgpkeys` holds the release key's primary fingerprint, which a subkey
rotation does not change. Before tagging `vX.Y.Z`:

```bash
sed -i 's/^pkgver=.*/pkgver=X.Y.Z/; s/^pkgrel=.*/pkgrel=1/' packaging/aur/clonaut/PKGBUILD
packaging/aur/test-in-docker.sh      # also refreshes .SRCINFO
```

`scripts/check-version.sh` (job `verify`) refuses a tag whose `pkgver`
differs, and `scripts/publish-aur.sh` refuses a stale `.SRCINFO`. Users need
the public key once: `gpg --import packaging/clonaut-release-key.asc` (or
`gpg --recv-keys` from a keyserver, once it is published there).
