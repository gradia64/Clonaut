"""Coda dei trasferimenti: pulizia, programmazioni ⏰ e loro modifica."""

import json

from clonaut import settings
from clonaut.ui.transfer_dialog import TransferDialog
from conftest import needs_rclone, spin


class _OfflineApi:
    url = "http://offline"

    def list_remotes(self):
        return []

    def __getattr__(self, name):
        def fail(*_a, **_k):
            raise OSError("offline")
        return fail


class _Ctx:
    api = _OfflineApi()
    rcd = rcd_dry = None
    rclone_exe = None


def _snap(*finished_jids):
    return {"agg": {}, "jobs": {j: {"status": {"finished": True, "success": True},
                                    "stats": {}} for j in finished_jids}}


def test_clear_finished_stays_cleared(qapp):
    from clonaut.ui.transfers_tab import TransfersTab
    tab = TransfersTab(_Ctx())
    forgotten = []
    tab.job_dismissed.connect(forgotten.append)
    tab.on_snapshot(_snap(5, 6))
    assert tab.tree.topLevelItemCount() == 2
    tab._on_clear()
    tab.on_snapshot(_snap(5, 6))          # il worker li manda ancora
    assert tab.tree.topLevelItemCount() == 0
    assert sorted(forgotten) == [5, 6]


def test_corrupted_recurring_file_does_not_block(qapp):
    from clonaut.ui.transfers_tab import TransfersTab
    path = settings.config_dir() / "recurring.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"definitions": [{"id": "rotto"}, 3, {"id": "rec-x"}]')
    TransfersTab(_Ctx())
    path.write_text(json.dumps({"definitions": [{"id": "rotto"}, 3]}))
    assert TransfersTab(_Ctx()).tree.topLevelItemCount() == 0


@needs_rclone
def test_schedule_runs_once_without_duplicate_rows(window, tree, qapp):
    tab = window.transfers_tab
    def_id = tab.add_recurring("copy", str(tree / "a"), str(tree / "r"), [], 3600)
    d = tab._recurrent[def_id]
    assert spin(qapp, 15, until=lambda: d.get("last_status") == "ok")
    spin(qapp, 2.5)                          # un paio di snapshot dopo la fine
    states = [tab.tree.topLevelItem(i).text(4) for i in range(tab.tree.topLevelItemCount())]
    assert len(states) == 1 and states[0].startswith("⏰ Prossimo giro"), states


@needs_rclone
def test_edit_schedule(window, tree, qapp, dialogs):
    tab = window.transfers_tab
    def_id = tab.add_recurring("copy", str(tree / "a"), str(tree / "r1"), ["*.tmp"], 6 * 3600)
    d = tab._recurrent[def_id]
    assert spin(qapp, 15, until=lambda: d.get("last_status") == "ok")
    last = d["last_start"]

    dlg = TransferDialog(window.ctx, tab, window, schedule=d, def_id=def_id)
    assert dlg.windowTitle() == "Modifica programmazione"
    assert (dlg.spn_repeat.value(), dlg.cb_unit.currentText()) == (6, "ore")
    assert not dlg.chk_repeat.isEnabled() and not dlg.chk_dry.isVisibleTo(dlg)

    # solo intervallo ed esclusioni: nessuna conferma, stato conservato
    dlg.spn_repeat.setValue(2)
    dlg.cb_unit.setCurrentIndex(dlg.cb_unit.findData(86400))
    dlg.ed_exclude.setText("*.tmp, .lock")
    dlg.accept()
    assert dialogs == []
    assert d["interval"] == 2 * 86400 and d["exclude"] == ["*.tmp", ".lock"]
    assert d["last_start"] == last and d["enabled"]

    # passaggio a «Sincronizza»: chiede conferma e salva su disco
    dlg = TransferDialog(window.ctx, tab, window, schedule=d, def_id=def_id)
    dlg.cb_mode.setCurrentIndex(dlg.cb_mode.findData("sync"))
    dlg.ed_dst.setText(str(tree / "r2"))
    dlg.chk_trash.setChecked(True)
    dlg.accept()
    assert dialogs == ["Conferma «sync»"]
    saved = json.loads((settings.config_dir() / "recurring.json").read_text())
    saved = saved["definitions"][0]
    assert saved["mode"] == "sync" and saved["dst"].endswith("r2")
    assert saved["backup_dir"].endswith("r2-cestino")
    assert tab._rec_item[def_id].text(1) == "Sincronizza"


@needs_rclone
def test_edit_while_running_warns(window, tree, qapp, dialogs):
    tab = window.transfers_tab
    def_id = tab.add_recurring("copy", str(tree / "a"), str(tree / "r"), [], 3600)
    d = tab._recurrent[def_id]
    assert spin(qapp, 5, until=lambda: d.get("current_jid") is not None)
    dlg = TransferDialog(window.ctx, tab, window, schedule=d, def_id=def_id)
    dlg.ed_exclude.setText("x")
    dlg.accept()
    assert dialogs == ["Programmazione aggiornata"]


def test_schedule_with_dead_daemon_records_the_error(rcd, qapp, tree):
    """Il demone muore: il giro programmato segna l'errore invece di sparire."""
    from clonaut.ui.transfers_tab import TransfersTab
    tab = TransfersTab(rcd)
    def_id = tab.add_recurring("sync", str(tree / "a"), str(tree / "b"), [], 3600)
    rcd.rcd.stop()
    tab._on_rec_tick()
    d = tab._recurrent[def_id]
    assert d["last_status"] == "err"
    assert "non risponde" in d["last_error"]
    assert d["current_jid"] is None
    assert "ultimo: ✕" in tab._rec_item[def_id].text(4)
    saved = json.loads((settings.config_dir() / "recurring.json").read_text())
    assert saved["definitions"][0]["last_status"] == "err"
