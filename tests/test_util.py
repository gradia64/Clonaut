"""Formattazioni e piccole funzioni pure."""

from clonaut.ui.transfer_dialog import split_interval
from clonaut.util import fmt_duration, fmt_eta, human_size, human_speed, strip_html


def test_human_size():
    assert human_size(None) == "—"
    assert human_size(512) == "512 B"
    assert human_size(1536) == "1.5 KiB"
    assert human_size(5 * 1024**3) == "5.0 GiB"
    assert human_size(-1) == "—"


def test_human_speed():
    assert human_speed(0) == "—"
    assert human_speed(2 * 1024**2) == "2.0 MiB/s"


def test_fmt_eta_includes_days():
    assert fmt_eta(90) == "1m 30s"
    assert fmt_eta(3 * 3600 + 5) == "3h 00m"
    assert fmt_eta(2 * 86400 - 10) == "1g 23h"
    assert fmt_eta(None) == "—"


def test_fmt_duration():
    assert fmt_duration(12.24) == "12.2s"
    assert fmt_duration(125) == "2m 05s"


def test_strip_html():
    assert strip_html("<p>Ciao<br>mondo &amp; altro</p>") == "Ciao\nmondo & altro"


def test_split_interval_picks_largest_exact_unit():
    assert split_interval(6 * 3600) == (6, 3600)
    assert split_interval(2 * 86400) == (2, 86400)
    assert split_interval(90 * 60) == (90, 60)
    assert split_interval(10) == (1, 60)   # minimo un minuto


# --- testo dal cloud mostrato come HTML (penetration test Strix, vuln-0005) ---

def _rich(text):
    from clonaut.qtcompat import QtCore, QtGui
    qt_gui = getattr(QtGui, "Qt", None)            # PySide6: QtGui.Qt, PyQt6: QtCore.Qt
    fn = getattr(qt_gui, "mightBeRichText", None) or QtCore.Qt.mightBeRichText
    return fn(text)


def _as_shown(text):
    """Il testo come lo mostra un QLabel in AutoText (message box, tooltip)."""
    from clonaut.qtcompat import QtGui
    if not _rich(text):
        return text
    doc = QtGui.QTextDocument()
    doc.setHtml(text)
    return doc.toPlainText().replace(" ", "\n").replace(" ", " ")


def test_esc_lascia_stare_il_testo_normale():
    from clonaut.util import esc
    for text in ("normale.txt", "R&D report.pdf", "Tom & Jerry.mp4", "riga 1\nriga 2", ""):
        assert esc(text) == text
    assert esc(None) == ""


def test_esc_niente_html_e_testo_identico(qapp):
    from clonaut.util import esc
    payloads = [
        "relazione <2024>.txt",
        '<a href="https://evil.example">Clicca qui</a>',
        "errore remoto:\nfile <a href=x>clic</a>",            # HTML nella 2ª riga
        '<img src="https://evil.example/x.png" width=500>',
        "a  <b>due  spazi</b>",
    ]
    for text in payloads:
        shown = esc(text)
        assert _rich(shown)
        assert "<a" not in shown and "<img" not in shown and "<b>" not in shown
        assert _as_shown(shown) == text


def test_errore_del_remote_non_diventa_un_link(qapp, monkeypatch):
    from clonaut.qtcompat import QtWidgets
    from clonaut.ui import remotes_tab
    seen = []
    monkeypatch.setattr(QtWidgets.QMessageBox, "critical",
                        staticmethod(lambda _p, title, text, *a, **k: seen.append(text)))
    remotes_tab._show_error(None, RuntimeError(
        'config/delete → HTTP 500: <a href="https://evil.example">dettagli</a>'))
    assert seen and "<a " not in seen[0]
    assert "https://evil.example" in _as_shown(seen[0])
