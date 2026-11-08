"""Funzioni di utilità: formattazioni, stile globale, icona dell'app."""

from __future__ import annotations

import html
import re

from .i18n import tr
from .qtcompat import QtCore, QtGui

_TAG_RE = re.compile(r"<[^>]+>")


def human_size(n) -> str:
    """Formatta un numero di byte in forma leggibile (es. "12.3 MiB")."""
    if n is None:
        return "—"
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "—"
    if n < 0:
        return "—"
    for unit in ("B", "KiB", "MiB", "GiB", "TiB", "PiB"):
        if n < 1024 or unit == "PiB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return "—"


def human_speed(n) -> str:
    """Formatta una velocità in byte/s (es. "4.2 MiB/s")."""
    if n is None or float(n or 0) <= 0:
        return "—"
    return f"{human_size(n)}/s"


def fmt_eta(seconds) -> str:
    """Formatta un ETA in secondi (es. "1h 03m")."""
    if seconds is None:
        return "—"
    try:
        seconds = float(seconds)
    except (TypeError, ValueError):
        return "—"
    if seconds < 0 or seconds > 10**9:
        return "—"
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h >= 24:
        d, h = divmod(h, 24)
        return tr("{d}g {h:02d}h").format(d=d, h=h)
    if h:
        return f"{h}h {m:02d}m"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def fmt_duration(seconds) -> str:
    """Formatta la durata di un job finito (es. "12.2s")."""
    if seconds is None:
        return "—"
    try:
        seconds = float(seconds)
    except (TypeError, ValueError):
        return "—"
    if seconds < 0:
        return "—"
    if seconds < 60:
        return f"{seconds:.1f}s"
    return fmt_eta(seconds)


def strip_html(text: str) -> str:
    """Riduce l'help HTML delle opzioni a testo leggibile per i tooltip."""
    if not text:
        return ""
    text = text.replace("<br>", "\n").replace("</p>", "\n")
    text = _TAG_RE.sub("", text)
    text = html.unescape(text)
    lines = [ln.strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)[:500]


APP_QSS = """
* { font-size: 13px; }
QMainWindow, QDialog { background: #f4f5f7; }
QTabWidget::pane {
    border: 1px solid #d9dce1; border-radius: 4px; background: white; top: -1px;
}
QTabBar::tab {
    padding: 7px 18px; margin-right: 2px; border: 1px solid #d9dce1;
    border-bottom: none; border-top-left-radius: 4px; border-top-right-radius: 4px;
    background: #e7e9ec; color: #4b5563;
}
QTabBar::tab:selected { background: white; color: #1f2937; font-weight: 600; }
QPushButton {
    padding: 6px 14px; background: #ffffff; border: 1px solid #c9ccd3; border-radius: 6px;
}
QPushButton:hover { background: #f0f3f8; border-color: #9aa3af; }
QPushButton:pressed { background: #e3e8ef; }
QPushButton:disabled { color: #9ca3af; background: #f3f4f6; border-color: #dde0e5; }
QTreeWidget {
    border: 1px solid #d9dce1; border-radius: 6px; background: white;
    alternate-background-color: #f7f8fa;
}
QTreeWidget::item:selected { background: #dbe7fb; color: #1f2937; }
QHeaderView::section {
    background: #eef0f3; border: none; border-right: 1px solid #dde0e5;
    padding: 5px 8px; font-weight: 600; color: #374151;
}
QProgressBar {
    border: 1px solid #c9ccd3; border-radius: 6px; background: #e9ebef;
    height: 16px; text-align: center; font-size: 10px; color: #374151;
}
QProgressBar::chunk {
    border-radius: 5px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #4f8ef7, stop:1 #2f6fd8);
}
QLineEdit, QComboBox, QSpinBox {
    padding: 5px 8px; border: 1px solid #c9ccd3; border-radius: 6px; background: white;
}
QLineEdit:focus, QComboBox:focus { border-color: #2f6fd8; }
QLabel[role="hint"] { color: #6b7280; }
QLabel[role="warn"] {
    color: #92400e; background: #fef3c7; border: 1px solid #fcd34d;
    border-radius: 6px; padding: 8px;
}
QGroupBox {
    font-weight: 600; border: 1px solid #d9dce1; border-radius: 6px;
    margin-top: 12px; background: white; padding-top: 6px;
}
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
QSplitter::handle { background: #e5e7eb; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #c3c8d0; border-radius: 4px; min-height: 30px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
"""


def app_icon() -> QtGui.QIcon:
    """Icona semplice: quadrato arrotondato blu con due frecce (su/giù)."""
    pm = QtGui.QPixmap(64, 64)
    pm.fill(QtGui.QColor(0, 0, 0, 0))
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    p.setPen(QtGui.QPen(QtGui.QColor("transparent")))
    p.setBrush(QtGui.QColor("#2f6fd8"))
    p.drawRoundedRect(4, 4, 56, 56, 14, 14)
    pen = QtGui.QPen(QtGui.QColor("white"), 6, QtCore.Qt.PenStyle.SolidLine,
                     QtCore.Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    # freccia su
    p.drawLine(24, 44, 24, 24)
    p.drawLine(24, 24, 16, 32)
    p.drawLine(24, 24, 32, 32)
    # freccia giù
    p.drawLine(42, 20, 42, 40)
    p.drawLine(42, 40, 34, 32)
    p.drawLine(42, 40, 50, 32)
    p.end()
    icon = QtGui.QIcon(pm)
    icon.addPixmap(pm)
    return icon
