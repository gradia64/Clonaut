"""scripts/publish-aur.sh contro un finto AUR fatto di repository git locali."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "publish-aur.sh"
PACKAGES = ("clonaut", "clonaut-git")


@pytest.fixture
def aur(tmp_path):
    """Repository AUR vuoti (come quelli di un pacchetto nuovo) e ambiente."""
    base = tmp_path / "aur"
    for name in PACKAGES:
        subprocess.run(["git", "init", "-q", "--bare", "-b", "master",
                        str(base / f"{name}.git")], check=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith("AUR_")}
    env.update(AUR_REMOTE_BASE=f"file://{base}", AUR_SKIP_SOURCE_CHECK="1",
               GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    return base, env


def _run(env, *dirs):
    return subprocess.run([str(SCRIPT), *map(str, dirs)], env=env,
                          capture_output=True, text=True)


def _files(base, name):
    out = subprocess.run(["git", "--git-dir", str(base / f"{name}.git"),
                          "ls-tree", "--name-only", "master"],
                         capture_output=True, text=True)
    return out.stdout.split()   # repository ancora vuoto: nessun file


def test_publishes_both_packages_then_nothing_to_do(aur):
    base, env = aur
    dirs = [ROOT / "packaging" / "aur" / n for n in PACKAGES]
    first = _run(env, *dirs)
    assert first.returncode == 0, first.stderr
    for name in PACKAGES:
        assert f"pubblicato su AUR: {name}" in first.stdout
        assert _files(base, name) == [".SRCINFO", "PKGBUILD"]
    again = _run(env, *dirs)
    assert again.returncode == 0, again.stderr
    assert again.stdout.count("AUR già aggiornato") == 2


def test_a_stale_srcinfo_is_refused(aur, tmp_path):
    base, env = aur
    pkg = tmp_path / "clonaut"
    shutil.copytree(ROOT / "packaging" / "aur" / "clonaut", pkg)
    text = (pkg / "PKGBUILD").read_text()
    (pkg / "PKGBUILD").write_text(text.replace("pkgver=", "pkgver=9.9.9\n#", 1))
    res = _run(env, pkg)
    assert res.returncode == 1
    assert "rigeneralo" in res.stderr
    assert _files(base, "clonaut") == []   # niente pubblicato


def test_srcinfo_in_the_repo_matches_the_pkgbuild():
    for name in PACKAGES:
        d = ROOT / "packaging" / "aur" / name
        ver = [line.split("=", 1)[1] for line in (d / "PKGBUILD").read_text().splitlines()
               if line.startswith("pkgver=")]
        assert f"\tpkgver = {ver[0]}" in (d / ".SRCINFO").read_text(), name


def test_pkgbuild_check_skips_the_aur_publishing_tests():
    """Il check() dei PKGBUILD non deve dipendere dal .SRCINFO.

    test-in-docker.sh rigenera il .SRCINFO solo dopo makepkg: se il check()
    eseguisse i test che lo confrontano col PKGBUILD, dopo un cambio di
    versione la build fallirebbe prima di poterlo rigenerare.
    """
    for name in ("clonaut", "clonaut-git"):
        text = (ROOT / "packaging" / "aur" / name / "PKGBUILD").read_text()
        check = text.split("check() {", 1)[1].split("\n}", 1)[0]
        for test in ("tests/test_publish_aur.py", "tests/test_aur_release.py"):
            assert f"--ignore={test}" in check, (name, test)
