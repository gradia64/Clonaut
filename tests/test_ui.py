"""Finestra principale, dialog e tray."""

import pytest

from clonaut import __version__
from clonaut.qtcompat import QtWidgets
from clonaut.ui.settings_dialog import SettingsDialog
from clonaut.ui.transfer_dialog import TransferDialog
from conftest import needs_rclone

pytestmark = needs_rclone


def test_title_menus_and_about(window):
    assert window.windowTitle() == f"Clonaut {__version__}"
    menus = [a.text() for a in window.menuBar().actions()]
    assert menus == ["&File", "&Aiuto"]
    about = window.about_text()
    assert f"Clonaut {__version__}" in about
    assert "(PATH)" in about and "Python" in about
    assert "ℹ" not in about


def test_tray_left_click_brings_window_back(window, qapp):
    window._setup_tray(force=True)
    reason = QtWidgets.QSystemTrayIcon.ActivationReason
    window.hide()
    window._on_tray_activated(reason.Trigger)
    assert window.isVisible()
    window.showMinimized()
    window._on_tray_activated(reason.Trigger)
    assert not window.isMinimized()
    window.hide()
    window._on_tray_activated(reason.Trigger)     # alcuni ambienti: Trigger…
    window._on_tray_activated(reason.DoubleClick)  # …poi DoubleClick
    assert window.isVisible()


def test_trash_checkbox_proposes_folder(rcd, qapp):
    dlg = TransferDialog(rcd, None)
    dlg.ed_dst.setText("/dati/destinazione/")
    dlg.chk_trash.setChecked(True)
    assert dlg.ed_trash.text() == "/dati/destinazione-cestino"
    assert dlg.btn_trash.isEnabled()


def test_trash_inside_destination_is_refused(rcd, qapp, dialogs, tree):
    dlg = TransferDialog(rcd, None)
    dlg.ed_src.setText(str(tree / "a"))
    dlg.ed_dst.setText(str(tree / "b"))
    dlg.chk_trash.setChecked(True)
    dlg.ed_trash.setText(str(tree / "b" / "cestino"))
    dlg.accept()
    assert dialogs == ["Cestino dentro la destinazione"]


def _select_type(dlg, prefix):
    for i in range(dlg.cb_type.count()):
        if dlg.cb_type.itemText(i).startswith(prefix):
            dlg.cb_type.setCurrentIndex(i)
            return
    pytest.fail(f"tipo {prefix} non trovato")


def test_remote_dialog_form(rcd, qapp, dialogs):
    from clonaut.ui.remote_dialog import RemoteDialog, combo_value
    dlg = RemoteDialog(rcd)
    dlg.show()

    _select_type(dlg, "s3 ")
    endpoint = dlg._fields["endpoint"][0]
    assert endpoint.isEditable()                 # esempi solo suggeriti
    endpoint.setEditText("https://minio.local:9000")
    assert combo_value(endpoint) == "https://minio.local:9000"

    _select_type(dlg, "koofr")
    assert list(dlg._fields).count("password") == 1

    _select_type(dlg, "nextcloud")
    qapp.processEvents()
    visible = [w.text() for w in dlg._form_host.findChildren(QtWidgets.QLabel)
               if w.isVisible()]
    assert "remote *" not in visible             # niente etichette del tipo precedente
    assert combo_value(dlg._fields["vendor"][0]) == "nextcloud"

    dlg.ed_name.setText("casa")
    dlg._fields["url"][0].setText("https://cloud.example/remote.php/dav/files/u")
    dlg.accept()
    assert rcd.api.dump_config()["casa"] == {
        "type": "webdav", "url": "https://cloud.example/remote.php/dav/files/u",
        "vendor": "nextcloud"}


def test_settings_dialog_validates_rclone_path(qapp, dialogs, tmp_path):
    dlg = SettingsDialog({"close_to_tray": True}, rclone_in_use="/usr/bin/rclone (PATH)")
    dlg.ed_rclone.setText(str(tmp_path / "non-esiste"))
    dlg.accept()
    assert dialogs == ["rclone non valido"]
    dlg.ed_rclone.setText("")
    dlg.accept()
    assert dlg.values()["rclone_path"] == ""
    assert dlg.values()["close_to_tray"] is True


def test_closing_without_tray_option_quits_the_app(window, qapp, monkeypatch):
    """«Chiudi nella tray» disattivo: la X ferma il demone e chiude davvero l'app.

    Prima l'icona nella tray (KDE) teneva in vita l'app senza demone: i
    programmati non partivano più e «Avvia ora» falliva in silenzio.
    """
    quits = []
    monkeypatch.setattr(QtWidgets.QApplication, "quit", staticmethod(lambda: quits.append(1)))
    window._setup_tray(force=True)
    window.settings["close_to_tray"] = False
    window.close()
    assert window.ctx.rcd.proc.poll() is not None   # demone fermato
    assert quits, "la X deve chiudere anche l'app, non solo il demone"


def test_closing_to_tray_keeps_daemon_and_app(window, qapp, monkeypatch):
    quits = []
    monkeypatch.setattr(QtWidgets.QApplication, "quit", staticmethod(lambda: quits.append(1)))
    window._setup_tray(force=True)
    window.settings["close_to_tray"] = True
    window.close()
    assert not window.isVisible()
    assert window.ctx.rcd.proc.poll() is None
    assert not quits
