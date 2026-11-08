"""Note di rilascio e controllo della versione usati da release.yml.

scripts/release-notes.sh prende la sezione del CHANGELOG; scripts/check-version.sh
ferma un tag che non corrisponde alla versione del codice.
"""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NOTES = ROOT / "scripts" / "release-notes.sh"
CHECK = ROOT / "scripts" / "check-version.sh"

CHANGELOG = """# Changelog

## [Unreleased]

### Added
- non ancora uscito

## [1.2.0] — 2026-01-02

Prima riga.

### Fixed
- corretto qualcosa

## [1.1.0] — 2026-01-01

- vecchio

[1.2.0]: https://example.invalid/v1.2.0
"""


def _run(script, *args, **env):
    return subprocess.run(["bash", str(script), *args], capture_output=True, text=True,
                          env={"PATH": "/usr/bin:/bin", **env})


def test_notes_take_only_the_section_of_the_version(tmp_path):
    """Solo la sezione richiesta, senza Unreleased, versioni vecchie e link."""
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(CHANGELOG)
    out = _run(NOTES, "v1.2.0", CLONAUT_CHANGELOG=str(changelog))
    assert out.returncode == 0, out.stderr
    assert out.stdout.startswith("Prima riga.\n")
    assert "corretto qualcosa" in out.stdout
    for other in ("non ancora uscito", "vecchio", "example.invalid", "## [1.1.0]"):
        assert other not in out.stdout
    assert "sudo apt install ./clonaut_1.2.0_all.deb" in out.stdout
    assert "Clonaut-1.2.0-x86_64.AppImage" in out.stdout


def test_notes_show_the_fingerprint_from_the_single_source(tmp_path):
    """L'impronta nelle note è quella di scripts/release-keys.sh."""
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(CHANGELOG)
    fpr = "0123456789ABCDEF0123456789ABCDEF01234567"
    out = _run(NOTES, "1.2.0", CLONAUT_CHANGELOG=str(changelog), CLONAUT_RELEASE_PRIMARY=fpr)
    assert "0123 4567 89AB CDEF 0123  4567 89AB CDEF 0123 4567" in out.stdout


def test_notes_fail_without_a_section(tmp_path):
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(CHANGELOG)
    out = _run(NOTES, "9.9.9", CLONAUT_CHANGELOG=str(changelog))
    assert out.returncode != 0
    assert "9.9.9" in out.stderr


def test_the_real_changelog_has_notes_for_the_last_release():
    """Il CHANGELOG del repository: l'ultima versione uscita ha le sue note."""
    out = _run(NOTES, "0.3.1")
    assert out.returncode == 0, out.stderr
    assert "First public release." in out.stdout


def test_check_version_rejects_bad_tags():
    for tag in ("0.3.1", "v0.3", "v0.3.1-rc1", "vX.Y.Z"):
        out = _run(CHECK, tag)
        assert out.returncode != 0, tag
        assert "tag non valido" in out.stderr


def test_check_version_reports_every_mismatch():
    """Un tag che il codice non conosce: ogni file che non torna è elencato."""
    out = _run(CHECK, "v99.0.0")
    assert out.returncode != 0
    for where in ("clonaut/__init__.py", "metainfo", "packaging/changelog", "PKGBUILD"):
        assert f"NO  {where}" in out.stderr
