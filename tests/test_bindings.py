"""Ogni modulo si importa con entrambi i binding Qt (il .deb dipende da PyQt6)."""

import importlib.util
import os
import subprocess
import sys

import pytest

_CODE = (
    "import clonaut.app, clonaut.ui.main_window as m; "
    "from clonaut.qtcompat import BINDING; print(BINDING)"
)


@pytest.mark.parametrize("binding,module", [("pyqt6", "PyQt6"), ("pyside6", "PySide6")])
def test_imports_with_binding(binding, module):
    if importlib.util.find_spec(module) is None:
        pytest.skip(f"{module} non installato")
    env = dict(os.environ, CLONAUT_QT=binding)
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = subprocess.run([sys.executable, "-c", _CODE], env=env, cwd=root,
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert out.stdout.startswith(module)
