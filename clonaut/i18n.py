"""Lingua dell'interfaccia: italiano (i testi nel codice) o inglese.

I testi dell'interfaccia sono scritti in italiano dentro `tr("…")`; per le
altre lingue `tr` li cerca nel catalogo gettext `clonaut/locale/<lingua>.po`.
Il .po si legge così com'è, senza compilarlo in .mo: niente strumenti di
build e lo stesso file per PyQt6 e PySide6. `N_("…")` marca un testo da
tradurre più tardi (costanti di modulo, valutate prima di `setup`): chi lo
mostra lo passa a `tr`.

La lingua: variabile d'ambiente CLONAUT_LANG → impostazione «Lingua» →
lingua del sistema (LANGUAGE, LC_ALL, LC_MESSAGES, LANG). Italiano se la
lingua è «it», altrimenti inglese. Senza `setup` (test, moduli usati da soli)
`tr` restituisce il testo italiano.

Per aggiornare il catalogo dopo aver cambiato dei testi:
    python3 scripts/update-po.py
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

LANG_ENV = "CLONAUT_LANG"
LANGUAGES = {"it": "Italiano", "en": "English"}   # nomi nella loro lingua
SOURCE_LANGUAGE = "it"
LOCALE_DIR = Path(__file__).resolve().parent / "locale"

_catalog: dict[str, str] = {}
_language = SOURCE_LANGUAGE


def tr(text: str) -> str:
    """Il testo nella lingua scelta (l'originale se manca la traduzione)."""
    return _catalog.get(text) or text


def N_(text: str) -> str:  # noqa: N802 — nome convenzionale di gettext
    """Marca un testo per il catalogo senza tradurlo ora."""
    return text


def language() -> str:
    return _language


def _normalize(value: str) -> str:
    """«it_IT.UTF-8» → «it»; «C», «POSIX» e vuoto → «»."""
    value = (value or "").strip().split(":")[0].split(".")[0].split("@")[0]
    lang = value.replace("-", "_").split("_")[0].lower()
    return "" if lang in ("", "c", "posix") else lang


def system_language() -> str:
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        lang = _normalize(os.environ.get(var, ""))
        if lang:
            return lang
    return ""


def detect(setting: str = "") -> str:
    """La lingua da usare: «it» o «en» (vedi il docstring del modulo)."""
    for value in (os.environ.get(LANG_ENV, ""), setting, system_language()):
        lang = _normalize(value)
        if lang:
            return lang if lang in LANGUAGES else "en"
    return "en"


def setup(lang: str) -> str:
    """Attiva una lingua per tutto il processo; restituisce quella attiva."""
    global _catalog, _language
    lang = lang if lang in LANGUAGES else "en"
    _catalog = {} if lang == SOURCE_LANGUAGE else load_po(LOCALE_DIR / f"{lang}.po")
    _language = lang
    return lang


def install_qt_translator(app) -> None:
    """Testi di Qt (pulsanti Sì/No, finestre dei file…) nella stessa lingua.

    Qt è già in inglese: serve solo il catalogo qtbase_<lingua> per le altre.
    """
    if _language == "en":
        return
    from .qtcompat import QtCore
    path = QtCore.QLibraryInfo.path(QtCore.QLibraryInfo.LibraryPath.TranslationsPath)
    translator = QtCore.QTranslator(app)
    if translator.load(f"qtbase_{_language}", path):
        app.installTranslator(translator)
        app._clonaut_qt_translator = translator   # resta vivo quanto l'app


# ------------------------------------------------------------------ file .po

def _unquote(token: str) -> str:
    return ast.literal_eval(token) if token.startswith('"') else ""


def parse_po(text: str) -> list[dict]:
    """Voci di un .po: msgid, msgstr, flags (es. «fuzzy»), riferimenti «#:»."""
    entries: list[dict] = []
    cur: dict = {}
    field = None

    def flush():
        nonlocal cur
        if "msgid" in cur:
            entries.append(cur)
        cur = {}

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            flush()
            field = None
        elif line.startswith("#,"):
            if "msgid" in cur:
                flush()
            cur.setdefault("flags", set()).update(
                f.strip() for f in line[2:].split(",") if f.strip())
        elif line.startswith("#:"):
            if "msgid" in cur:
                flush()
            cur.setdefault("refs", []).extend(line[2:].split())
        elif line.startswith("#"):
            continue
        elif line.startswith(("msgid ", "msgstr ")):
            field, _sep, rest = line.partition(" ")
            if field == "msgid" and "msgid" in cur:
                flush()
            cur[field] = _unquote(rest)
        elif line.startswith('"') and field:
            cur[field] += _unquote(line)
    flush()
    for e in entries:
        e.setdefault("msgstr", "")
        e.setdefault("flags", set())
        e.setdefault("refs", [])
    return entries


def load_po(path: Path) -> dict[str, str]:
    """Catalogo {originale: traduzione}; salta intestazione, vuote e «fuzzy»."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return {}
    return {e["msgid"]: e["msgstr"] for e in parse_po(text)
            if e["msgid"] and e["msgstr"] and "fuzzy" not in e["flags"]}
