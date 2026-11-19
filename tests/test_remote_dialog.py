"""Dialogo dei remote senza rclone: menu Tipo modificabile e alias digitati."""

from clonaut.qtcompat import QtWidgets

_PROVIDERS = [
    {"Name": "webdav", "Description": "WebDAV", "Options": [
        {"Name": "url", "Required": True},
        {"Name": "vendor", "Examples": [{"Value": "nextcloud"}, {"Value": "owncloud"},
                                        {"Value": "other"}]}]},
    {"Name": "s3", "Description": "Amazon S3", "Options": [
        {"Name": "endpoint"}, {"Name": "bucket"}]},
    {"Name": "local", "Description": "Local Disk", "Options": [
        {"Name": "nounc"}]},
]


class _Api:
    def __init__(self):
        self.created = []

    def providers(self):
        return _PROVIDERS

    def list_remotes(self):
        return []

    def create_remote(self, name, type_, params):
        self.created.append((name, type_, params))


class _Ctx:
    def __init__(self):
        self.api = _Api()


def _dialog():
    """Dialogo con la voce «local» scelta dall'elenco."""
    from clonaut.ui.remote_dialog import RemoteDialog
    dlg = RemoteDialog(_Ctx())
    dlg.ed_name.setText("casa")
    dlg.cb_type.setCurrentIndex(
        next(i for i in range(dlg.cb_type.count())
             if dlg.cb_type.itemText(i).startswith("local")))
    assert "nounc" in dlg._fields
    return dlg


def test_alias_digitato_ricostruisce_il_modulo(qapp, dialogs):
    """«nextcloud» scritto a mano lasciava il modulo e il tipo della voce precedente."""
    from clonaut.ui.remote_dialog import combo_value
    dlg = _dialog()
    dlg.cb_type.setEditText("nextcloud")
    assert "url" in dlg._fields and "nounc" not in dlg._fields
    assert combo_value(dlg._fields["vendor"][0]) == "nextcloud"
    dlg._fields["url"][0].setText("https://cloud.example/dav")
    dlg.accept()
    assert dialogs == []
    assert dlg.ctx.api.created == [
        ("casa", "webdav", {"url": "https://cloud.example/dav", "vendor": "nextcloud"})]


def test_nome_del_tipo_digitato(qapp, dialogs):
    dlg = _dialog()
    dlg.cb_type.setEditText("S3")
    assert set(dlg._fields) == {"endpoint", "bucket"}
    dlg.accept()
    assert dlg.ctx.api.created[0][1] == "s3"


def test_tipo_sconosciuto_rifiutato(qapp, dialogs):
    """Un tipo inesistente usava in silenzio quello della voce selezionata prima."""
    dlg = _dialog()
    dlg.cb_type.setEditText("dropboxx")
    assert dlg._fields == {}
    visible = [w for w in dlg._form_host.findChildren(QtWidgets.QLabel) if w.isVisible()]
    assert visible == []
    dlg.accept()
    assert dialogs == ["Tipo sconosciuto"]
    assert dlg.ctx.api.created == []
