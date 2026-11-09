"""Traduzione dell'interfaccia: catalogo inglese, scelta della lingua, UI in inglese."""

import importlib.util
import re

import pytest

from clonaut import i18n
from clonaut.qtcompat import QtWidgets
from conftest import needs_rclone, spin

_spec = importlib.util.spec_from_file_location(
    "update_po", i18n.LOCALE_DIR.parent.parent / "scripts" / "update-po.py")
update_po = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(update_po)

CATALOG = i18n.load_po(i18n.LOCALE_DIR / "en.po")


@pytest.fixture
def english():
    """Interfaccia in inglese per un test, poi di nuovo in italiano."""
    i18n.setup("en")
    yield
    i18n.setup("it")


def _placeholders(text: str) -> list[str]:
    return sorted(re.findall(r"\{[^}]*\}", text))


# ---------------------------------------------------------------- catalogo

def test_catalog_is_up_to_date_and_complete(capsys):
    """Ogni tr()/N_() del codice ha la sua traduzione, e nessuna voce è avanzata.

    Se fallisce: python3 scripts/update-po.py, poi traduci i msgstr vuoti.
    """
    assert update_po.main(["--check"]) == 0, capsys.readouterr().out


def test_translations_keep_placeholders_and_line_breaks():
    for source, english_text in CATALOG.items():
        assert _placeholders(source) == _placeholders(english_text), source
        assert source.count("\n") == english_text.count("\n"), source


def test_po_parser_reads_multiline_entries_and_skips_fuzzy(tmp_path):
    po = tmp_path / "xx.po"
    po.write_text('msgid ""\nmsgstr "Language: xx\\n"\n\n'
                  '#: a.py:1\nmsgid ""\n"Riga uno\\n"\n"riga «due»"\nmsgstr ""\n'
                  '"Line one\\n"\n"line \\"two\\""\n\n'
                  '#, fuzzy\nmsgid "Bozza"\nmsgstr "Draft"\n\n'
                  'msgid "Vuoto"\nmsgstr ""\n', encoding="utf-8")
    assert i18n.load_po(po) == {"Riga uno\nriga «due»": 'Line one\nline "two"'}


def test_f_strings_in_tr_are_rejected(tmp_path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "m.py").write_text('x = 1\nprint(tr(f"testo {x}"))\n')
    with pytest.raises(SystemExit, match="f-string"):
        update_po.extract(pkg)


# ---------------------------------------------------------- scelta lingua

@pytest.mark.parametrize("env, setting, expected", [
    ({"LANG": "it_IT.UTF-8"}, "", "it"),
    ({"LANG": "de_DE.UTF-8"}, "", "en"),                       # lingua senza catalogo
    ({"LANG": "C"}, "", "en"),
    ({}, "", "en"),
    ({"LANGUAGE": "en_GB:it", "LANG": "it_IT.UTF-8"}, "", "en"),
    ({"LC_ALL": "it_CH.UTF-8", "LANG": "en_US.UTF-8"}, "", "it"),
    ({"LANG": "en_US.UTF-8"}, "it", "it"),                     # impostazione > sistema
    ({"LANG": "it_IT.UTF-8", "CLONAUT_LANG": "en"}, "it", "en"),  # variabile > tutto
])
def test_detect(monkeypatch, env, setting, expected):
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG", "CLONAUT_LANG"):
        monkeypatch.delenv(var, raising=False)
    for var, value in env.items():
        monkeypatch.setenv(var, value)
    assert i18n.detect(setting) == expected


def test_italian_is_the_source_and_needs_no_catalog():
    i18n.setup("it")
    assert i18n.language() == "it"
    assert i18n.tr("Trasferimenti") == "Trasferimenti"
    assert i18n.tr("testo che non esiste") == "testo che non esiste"


def test_setup_english(english):
    assert i18n.language() == "en"
    assert i18n.tr("Trasferimenti") == "Transfers"
    from clonaut.util import fmt_eta
    assert fmt_eta(2 * 86400 - 10) == "1d 23h"


def test_language_setting_roundtrip(isolated_config):
    from clonaut import settings
    assert settings.load()["language"] == ""
    settings.save({"language": "en"})
    assert settings.load()["language"] == "en"


def test_settings_dialog_language_choice(qapp):
    from clonaut.ui.settings_dialog import SettingsDialog
    dlg = SettingsDialog({"language": "en"})
    assert dlg.cb_lang.currentData() == "en"
    dlg.cb_lang.setCurrentIndex(dlg.cb_lang.findData(""))
    assert dlg.values()["language"] == ""


def test_qt_translator_for_italian(qapp):
    """In italiano anche i pulsanti di Qt (Sì/No) sono tradotti, se c'è qtbase_it."""
    from clonaut.qtcompat import QtCore
    i18n.setup("it")
    i18n.install_qt_translator(qapp)
    translator = getattr(qapp, "_clonaut_qt_translator", None)
    if translator is None:
        pytest.skip("catalogo qtbase_it non installato con questo Qt")
    try:
        assert QtCore.QCoreApplication.translate("QPlatformTheme", "&Yes") == "&Sì"
    finally:
        qapp.removeTranslator(translator)
        del qapp._clonaut_qt_translator


# ------------------------------------------------------------ UI in inglese

def _texts(root: QtWidgets.QWidget) -> list[str]:
    """Tutti i testi visibili di una finestra: etichette, pulsanti, menu, intestazioni."""
    texts = []
    for w in [root, *root.findChildren(QtWidgets.QWidget)]:
        for attr in ("text", "title", "placeholderText", "windowTitle", "toolTip"):
            value = getattr(w, attr, None)
            if callable(value):
                try:
                    texts.append(str(value()))
                except TypeError:
                    pass
        if isinstance(w, QtWidgets.QComboBox):
            texts += [w.itemText(i) for i in range(w.count())]
        if isinstance(w, QtWidgets.QTreeWidget):
            header = w.headerItem()
            texts += [header.text(i) for i in range(header.columnCount())]
            for i in range(w.topLevelItemCount()):
                item = w.topLevelItem(i)
                texts += [item.text(c) for c in range(w.columnCount())]
        if isinstance(w, QtWidgets.QTabWidget):
            texts += [w.tabText(i) for i in range(w.count())]
        for action in w.actions():
            texts.append(action.text())
            if action.menu():
                texts += [a.text() for a in action.menu().actions()]
    return [t for t in texts if t]


def _untranslated(texts: list[str]) -> list[str]:
    italian = {k for k, v in CATALOG.items() if k != v}
    return [t for t in texts if t in italian]


@needs_rclone
def test_main_window_in_english(english, rcd, qapp, dialogs):
    from clonaut.ui.main_window import MainWindow
    win = MainWindow(rcd, settings={"close_to_tray": False})
    win.show()
    try:
        spin(qapp, 0.5)
        texts = _texts(win)
        assert "Remotes" in texts and "Transfers" in texts
        assert "＋ New transfer" in texts and "No remotes configured" in texts
        assert _untranslated(texts) == []
        assert "rcd at" in win._status_lbl.text()
        assert "The graphical pilot for rclone." in win.about_text()
    finally:
        win._quitting = True
        win.close()


@needs_rclone
def test_dialogs_in_english(english, rcd, qapp, dialogs):
    from clonaut.ui.remote_dialog import RemoteDialog
    from clonaut.ui.settings_dialog import SettingsDialog
    from clonaut.ui.transfer_dialog import TransferDialog
    from clonaut.ui.transfers_tab import TransfersTab
    tab = TransfersTab(rcd)
    for dlg, title in ((TransferDialog(rcd, tab), "New transfer"),
                       (RemoteDialog(rcd), "New remote"),
                       (SettingsDialog({}, rclone_in_use="/usr/bin/rclone"), "Settings")):
        assert dlg.windowTitle() == title
        assert _untranslated(_texts(dlg)) == [], title


def test_default_config_description_follows_the_language(english):
    # il predefinito si traduce alla creazione, non all'import del modulo
    from clonaut.appctx import AppContext
    assert AppContext(api=None).config_desc == CATALOG["predefinito (~/.config/rclone/rclone.conf)"]
