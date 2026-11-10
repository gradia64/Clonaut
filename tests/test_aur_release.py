"""scripts/aur-release.sh: pubblica sull'AUR solo i PKGBUILD di un tag del maintainer.

La chiave SSH dell'AUR non sta nella CI: il push lo fa il maintainer con
questo script. I test firmano tag con una chiave usa e getta fatta come
quella vera (primaria [C], sottochiavi [S]) e pubblicano su un finto AUR di
repository git locali.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "aur-release.sh"
PACKAGES = ("clonaut", "clonaut-git")

pytestmark = pytest.mark.skipif(
    shutil.which("gpg") is None or shutil.which("git") is None, reason="servono gpg e git"
)


def _run(cmd, **kwargs) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, check=True, **kwargs).stdout


def _pkgver() -> str:
    text = (ROOT / "packaging" / "aur" / "clonaut" / "PKGBUILD").read_text()
    return next(line.split("=", 1)[1] for line in text.splitlines() if line.startswith("pkgver="))


@pytest.fixture
def release(tmp_path):
    """Chiave di prova, repository con i PKGBUILD veri e finto AUR."""
    home = tmp_path / "g"
    home.mkdir(mode=0o700)
    genv = {"GNUPGHOME": str(home), "PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}

    def gpg(*args):
        return _run(["gpg", "--batch", "--passphrase", "", "--pinentry-mode", "loopback", *args],
                    env=genv)

    def fingerprints(uid):
        out = gpg("--with-colons", "--with-subkey-fingerprints", "--list-keys", uid)
        return [line.split(":")[9] for line in out.splitlines() if line.startswith("fpr")]

    gpg("--quick-generate-key", "Release <release@example.org>", "ed25519", "cert", "1y")
    primary = fingerprints("release@example.org")[0]
    gpg("--quick-add-key", primary, "ed25519", "sign", "1y")
    gpg("--quick-add-key", primary, "ed25519", "sign", "1y")
    _, tag_subkey, other_subkey = fingerprints("release@example.org")
    public = tmp_path / "release.asc"
    public.write_text(gpg("--armor", "--export", primary))

    repo = tmp_path / "repo"
    shutil.copytree(ROOT / "packaging" / "aur", repo / "packaging" / "aur",
                    ignore=shutil.ignore_patterns("*.sh", "README.md"))

    def git(*args):
        return _run(["git", "-C", str(repo), *args], env=genv)

    git("init", "-q")
    git("config", "user.name", "T")
    git("config", "user.email", "release@example.org")
    git("add", ".")
    git("commit", "-q", "-m", "release")

    base = tmp_path / "aur"
    for name in PACKAGES:
        subprocess.run(["git", "init", "-q", "--bare", "-b", "master", str(base / f"{name}.git")],
                       check=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("AUR_", "CLONAUT_", "GNUPG"))}
    env.update(
        HOME=str(tmp_path), GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
        CLONAUT_REPO=str(repo), CLONAUT_RELEASE_KEY=str(public),
        CLONAUT_RELEASE_PRIMARY=primary, CLONAUT_TAG_SIGNING_SUBKEYS=tag_subkey,
        CLONAUT_SKIP_CI_CHECK="1", AUR_REMOTE_BASE=f"file://{base}", AUR_SKIP_SOURCE_CHECK="1",
    )

    def tag(name, key):
        git("-c", f"user.signingkey={key}!", "tag", "-s", name, "-m", name)

    def publish(name):
        return subprocess.run([str(SCRIPT), name], env=env, capture_output=True, text=True)

    def published(name):
        out = subprocess.run(["git", "--git-dir", str(base / f"{name}.git"), "ls-tree",
                              "--name-only", "master"], capture_output=True, text=True)
        return out.stdout.split()

    return {"tag": tag, "git": git, "publish": publish, "published": published, "repo": repo,
            "keys": {"tag": tag_subkey, "other": other_subkey}}


def test_a_maintainer_tag_publishes_the_pkgbuilds_of_the_tag(release):
    version = _pkgver()
    release["tag"](f"v{version}", release["keys"]["tag"])
    # una modifica dopo il tag non deve finire sull'AUR
    pkg = release["repo"] / "packaging" / "aur" / "clonaut" / "PKGBUILD"
    pkg.write_text(pkg.read_text() + "\n# dopo il tag\n")
    release["git"]("commit", "-q", "-am", "dopo il tag")
    res = release["publish"](f"v{version}")
    assert res.returncode == 0, res.stderr
    for name in PACKAGES:
        assert f"pubblicato su AUR: {name}" in res.stdout
        assert release["published"](name) == [".SRCINFO", "PKGBUILD"]
    pushed = subprocess.run(
        ["git", "--git-dir", str(release["repo"].parent / "aur" / "clonaut.git"),
         "show", "master:PKGBUILD"], capture_output=True, text=True, check=True).stdout
    assert "# dopo il tag" not in pushed


def test_a_tag_signed_by_another_subkey_publishes_nothing(release):
    version = _pkgver()
    release["tag"](f"v{version}", release["keys"]["other"])
    res = release["publish"](f"v{version}")
    assert res.returncode != 0
    assert all(release["published"](name) == [] for name in PACKAGES)


def test_a_tag_that_does_not_match_pkgver_publishes_nothing(release):
    release["tag"]("v99.0.0", release["keys"]["tag"])
    res = release["publish"]("v99.0.0")
    assert res.returncode != 0
    assert "pkgver=" in res.stderr
    assert all(release["published"](name) == [] for name in PACKAGES)
