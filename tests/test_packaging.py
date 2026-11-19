"""Metadati del pacchetto (pyproject.toml)."""

import re
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def test_setuptools_abbastanza_recente_per_la_licenza_spdx():
    """`license = "GPL-3.0-only"` (PEP 639) richiede setuptools 77: con >=64 la build fallisce."""
    text = PYPROJECT.read_text()
    assert re.search(r'^license = "GPL-3\.0-only"$', text, re.M)
    minimum = re.search(r'^requires = \["setuptools>=(\d+)', text, re.M)
    assert minimum and int(minimum.group(1)) >= 77
