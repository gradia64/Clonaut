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

## Publishing (from the release workflow)

The AUR repositories are updated by `.github/workflows/release.yml`, the
same way as the maintainer's other projects (Plico, OllaDesk):

- the `arch` job builds the real `PKGBUILD` in a clean `archlinux:base-devel`
  container: `makepkg` clones the tag from GitHub and **verifies its
  signature** with the release key, runs the tests in `check()`, then namcap
  (errors only), install, a test start, and a check that `.SRCINFO` in the
  repository matches the `PKGBUILD`;
- after your approval in the `release` environment, `publish` creates the
  GitHub release and then pushes `PKGBUILD` and `.SRCINFO` of both packages
  with `scripts/publish-aur.sh` (pinned AUR host key; a package whose files
  did not change is skipped).

The SSH key is a dedicated one, `~/.ssh/aur_clonaut_ci`, stored only as the
secret `AUR_SSH_PRIVATE_KEY` of the `release` environment. Without the secret
the step is skipped with a notice. One-time setup:

1. Add `~/.ssh/aur_clonaut_ci.pub` to your AUR account (*My Account* → *SSH
   Public Key*, one key per line next to the existing ones).
2. Store the private key in the environment:

   ```bash
   gh secret set AUR_SSH_PRIVATE_KEY --env release -R gradia64/Clonaut < ~/.ssh/aur_clonaut_ci
   ```

The key gives access to the whole AUR account: the environment approval is
the last check before anything reaches the AUR. If it leaks, remove it from
the AUR account and generate a new one.

To put an **already released** tag on the AUR (e.g. the first publication),
run the workflow by hand with `aur_tag` set to the tag:

```bash
gh workflow run release.yml -R gradia64/Clonaut -f aur_tag=v0.4.0
```

It runs `verify`, `arch` and, after approval, only the AUR upload.

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

Publishing by hand still works: `scripts/publish-aur.sh packaging/aur/clonaut
packaging/aur/clonaut-git` uses your own SSH configuration when
`AUR_SSH_PRIVATE_KEY` is not set.
