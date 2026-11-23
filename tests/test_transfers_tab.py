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


def _wait_starts(qapp, tab):
    """I giri ⏰ partono in un thread: aspetta l'esito di tutti gli avvii."""
    assert spin(qapp, 10, until=lambda: not tab._rec_starters)


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
    _wait_starts(qapp, tab)
    d = tab._recurrent[def_id]
    assert d["last_status"] == "err"
    assert "non risponde" in d["last_error"]
    assert d["current_jid"] is None
    assert "ultimo: ✕" in tab._rec_item[def_id].text(4)
    saved = json.loads((settings.config_dir() / "recurring.json").read_text())
    assert saved["definitions"][0]["last_status"] == "err"


def test_recurring_con_valori_sbagliati_si_carica_corretto(qapp):
    """Penetration test Strix (vuln-0006): un campo strano non blocca l'avvio."""
    from clonaut.ui.transfers_tab import TransfersTab
    path = settings.config_dir() / "recurring.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"definitions": [
        {"id": "rec-1", "mode": "copy", "src": "/a", "dst": "/b",
         "interval": "ogni ora", "exclude": "*.log", "last_start": "ieri",
         "last_status": {"x": 1}, "backup_dir": None},
        {"id": "rec-2", "mode": "cancella-tutto", "src": ["/x"], "dst": 5,
         "interval": 1e300, "enabled": "no", "last_start": float("nan")},
        {"id": "rec-٣", "src": "/c", "dst": "/d"},            # cifra non ASCII
        {"id": 7, "src": "/e", "dst": "/f"},
    ]}).replace("NaN", '"NaN"'))
    tab = TransfersTab(_Ctx())
    assert sorted(tab._recurrent) == ["rec-1", "rec-2"]
    one, two = tab._recurrent["rec-1"], tab._recurrent["rec-2"]
    assert (one["interval"], one["exclude"], one["last_start"], one["last_status"],
            one["backup_dir"]) == (3600, [], None, None, "")
    assert (two["mode"], two["src"], two["dst"]) == ("copy", "", "5")
    assert two["interval"] == 999 * 86400
    from clonaut.api import ApiError

    class _ApiGiu(_OfflineApi):
        def start_transfer(self, *_a, **_k):
            raise ApiError("rcd giù")

    tab.ctx = type("Ctx", (_Ctx,), {"api": _ApiGiu()})()
    tab._on_rec_tick()                    # il timer non deve cadere
    _wait_starts(qapp, tab)
    assert tab._recurrent["rec-1"]["last_status"] == "err"
    tab._save_recurring()
    again = TransfersTab(_Ctx())
    assert again._recurrent["rec-1"]["interval"] == 3600


def test_recurring_annidato_all_infinito(qapp):
    from clonaut.ui.transfers_tab import TransfersTab
    path = settings.config_dir() / "recurring.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[" * 100000 + "]" * 100000)
    assert TransfersTab(_Ctx()).tree.topLevelItemCount() == 0


def test_files_panel_lists_files_being_compared(qapp):
    """Una sync con poco da copiare passa il tempo a confrontare: il pannello
    «File in corso» restava vuoto perché leggeva solo «transferring»."""
    from clonaut.ui.transfers_tab import TransfersTab
    tab = TransfersTab(_Ctx())
    assert "Seleziona un job" in tab.lbl_files.text()
    stats = {"checking": ["foto/a.jpg", "foto/b.jpg"], "checks": 40,
             "totalChecks": 300, "transfers": 0, "totalTransfers": 0}
    snap = {"agg": {}, "jobs": {7: {"status": {"finished": False}, "stats": stats}}}
    tab.on_snapshot(snap)
    tab.tree.setCurrentItem(tab.tree.topLevelItem(0))
    assert tab.tree.topLevelItem(0).text(4) == "… Confronto file"
    names = [tab.files.topLevelItem(i).text(0) for i in range(tab.files.topLevelItemCount())]
    assert names == ["foto/a.jpg", "foto/b.jpg"]
    assert tab.files.topLevelItem(0).text(1) == "confronto…"
    assert "confrontati 40 di 300" in tab.lbl_files.text()

    stats.pop("checking")
    tab.on_snapshot(snap)
    assert tab.files.topLevelItemCount() == 0
    assert "nessun file in lavorazione" in tab.lbl_files.text()


def test_schedule_buttons_in_the_bar(qapp, dialogs):
    """Avvia ora / Modifica / Pausa / Rimuovi anche nella barra, non solo col tasto destro."""
    from clonaut.ui.transfers_tab import TransfersTab
    tab = TransfersTab(_Ctx())
    tab._rec_timer.stop()   # niente giri veri: l'API è finta
    buttons = (tab.btn_run_now, tab.btn_edit, tab.btn_pause, tab.btn_unschedule)
    def_id = tab.add_recurring("copy", "/a", "/b", [], 3600)
    assert not any(b.isEnabled() for b in buttons)

    tab.tree.setCurrentItem(tab._rec_item[def_id])
    assert all(b.isEnabled() for b in buttons)
    assert "Programmazione in attesa" in tab.lbl_files.text()

    tab.btn_pause.click()
    d = tab._recurrent[def_id]
    assert not d["enabled"] and tab.btn_pause.text() == "▶ Riattiva"
    assert tab._rec_item[def_id].text(4).startswith("⏸ In pausa")
    tab.btn_pause.click()
    assert d["enabled"] and tab.btn_pause.text() == "⏸ Metti in pausa"

    tab.btn_run_now.click()
    assert d["run_now"] and not tab.btn_run_now.isEnabled()

    tab.btn_unschedule.click()
    assert dialogs == ["Rimuovere la programmazione?"]
    assert def_id not in tab._recurrent and tab.tree.topLevelItemCount() == 0
    assert not any(b.isEnabled() for b in buttons)


def test_run_now_button_comes_back_when_the_daemon_is_down(qapp):
    """Con il rcd giù non arrivano snapshot: dopo un «Avvia ora» fallito il
    pulsante deve tornare attivo dal tick stesso."""
    from clonaut.api import ApiError
    from clonaut.ui.transfers_tab import TransfersTab

    class _DeadApi(_OfflineApi):
        def start_transfer(self, *_a, **_k):
            raise ApiError("rclone rcd non risponde")

    ctx = _Ctx()
    ctx.api = _DeadApi()
    tab = TransfersTab(ctx)
    tab._rec_timer.stop()
    def_id = tab.add_recurring("copy", "/a", "/b", [], 3600)
    tab._recurrent[def_id]["last_start"] = 10**12   # niente giro automatico
    tab.tree.setCurrentItem(tab._rec_item[def_id])
    tab.btn_run_now.click()
    assert not tab.btn_run_now.isEnabled()
    tab._on_rec_tick()
    _wait_starts(qapp, tab)
    assert tab._recurrent[def_id]["last_status"] == "err"
    assert tab.btn_run_now.isEnabled()


def _running_schedule(tab, jid=42):
    """Programmazione ⏰ con un giro (finto) in corso sul job `jid`."""
    def_id = tab.add_recurring("sync", "/a", "/b", [], 3600)
    d = tab._recurrent[def_id]
    d.update(current_jid=jid, last_start=10**12)
    tab._rec_of_jid[jid] = def_id
    tab._meta[jid] = {"mode": "sync", "src": "/a", "dst": "/b", "rec": def_id}
    return def_id, d


def _job(finished, success=True):
    return {"agg": {}, "jobs": {42: {"status": {"finished": finished, "success": success},
                                     "stats": {"totalChecks": 3, "checks": 1}}}}


def test_removing_a_running_schedule_keeps_the_job_in_the_queue(qapp, dialogs):
    """Il giro in corso restava orfano: niente riga, niente notifica, non annullabile."""
    from clonaut.ui.transfers_tab import TransfersTab
    tab = TransfersTab(_Ctx())
    tab._rec_timer.stop()
    finished = []
    tab.job_finished.connect(lambda text, ok: finished.append((text, ok)))
    def_id, _d = _running_schedule(tab)
    tab.on_snapshot(_job(False))
    tab.tree.setCurrentItem(tab._rec_item[def_id])
    tab.btn_unschedule.click()
    assert dialogs == ["Rimuovere la programmazione?"]
    assert def_id not in tab._recurrent
    rows = [tab.tree.topLevelItem(i) for i in range(tab.tree.topLevelItemCount())]
    assert [r.text(0) for r in rows] == ["42"]   # riga normale, subito
    tab.tree.setCurrentItem(rows[0])
    assert tab.btn_stop.isEnabled()
    tab.on_snapshot(_job(True))
    assert finished == [("Sincronizza completato: /a → /b", True)]


def test_end_of_run_notice_uses_the_paths_of_the_run(qapp):
    """Programmazione modificata durante il giro: la notifica descrive il giro eseguito."""
    from clonaut.ui.transfers_tab import TransfersTab
    tab = TransfersTab(_Ctx())
    tab._rec_timer.stop()
    finished = []
    tab.job_finished.connect(lambda text, ok: finished.append(text))
    def_id, d = _running_schedule(tab)
    tab.on_snapshot(_job(False))
    assert tab.update_recurring(def_id, "copy", "/nuova", "/altra", [], 3600)
    tab.on_snapshot(_job(True))
    assert finished == ["Programmato Sincronizza completato: /a → /b"]
    assert tab._rec_item[def_id].text(2) == "/nuova"   # il prossimo giro


def test_files_summary_without_comparisons(qapp):
    from clonaut.ui.transfers_tab import TransfersTab
    tab = TransfersTab(_Ctx())
    stats = {"transfers": 1, "totalTransfers": 2, "checks": 0, "totalChecks": 0}
    tab.on_snapshot({"agg": {}, "jobs": {9: {"status": {"finished": False}, "stats": stats}}})
    tab.tree.setCurrentItem(tab.tree.topLevelItem(0))
    assert tab.lbl_files.text().startswith("Copiati 1 di 2 file")
    assert "confrontati" not in tab.lbl_files.text()


def test_recurring_corrotto_viene_conservato(qapp):
    """Un recurring.json illeggibile veniva sovrascritto in silenzio al primo salvataggio."""
    from clonaut.ui.transfers_tab import TransfersTab
    path = settings.config_dir() / "recurring.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"definitions": [{"id": "rec-1", "src": "/a"')   # troncato
    tab = TransfersTab(_Ctx())
    tab._rec_timer.stop()
    kept = list(path.parent.glob("recurring.json.corrupt-*"))
    assert len(kept) == 1
    assert kept[0].read_text().startswith('{"definitions"')
    assert kept[0].name in tab.lbl_rec_warn.text()
    tab.add_recurring("copy", "/x", "/y", [], 3600)   # salva il file nuovo
    assert kept[0].exists()


def test_salvataggio_programmazioni_fallito_avvisa(qapp, monkeypatch):
    """Gli OSError di _save_recurring venivano ignorati: modifiche perse senza avviso."""
    from clonaut.ui.transfers_tab import TransfersTab
    tab = TransfersTab(_Ctx())
    tab._rec_timer.stop()

    def fail(*_a, **_k):
        raise OSError(13, "permesso negato")
    monkeypatch.setattr(settings, "write_private", fail)
    tab.add_recurring("copy", "/x", "/y", [], 3600)
    assert "programmazioni non salvate" in tab.lbl_rec_warn.text()
    assert not tab.lbl_rec_warn.isHidden()
    tab.on_snapshot({"agg": {}, "jobs": {}})   # le statistiche non lo cancellano
    assert "programmazioni non salvate" in tab.lbl_rec_warn.text()
    monkeypatch.undo()
    tab._save_recurring()
    assert tab.lbl_rec_warn.isHidden()


def test_giro_programmato_perso_non_blocca_la_programmazione(qapp):
    """Se il job di un giro spariva dagli snapshot, current_jid restava impostato per sempre."""
    from clonaut.ui import transfers_tab as tt
    tab = tt.TransfersTab(_Ctx())
    tab._rec_timer.stop()
    finished = []
    tab.job_finished.connect(lambda text, ok: finished.append(ok))
    def_id, d = _running_schedule(tab)
    tab.on_snapshot(_job(False))
    empty = {"agg": {}, "jobs": {}}
    for _ in range(tt._LOST_AFTER - 1):
        tab.on_snapshot(empty)
    assert d["current_jid"] == 42          # un buco breve non basta
    tab.on_snapshot(_job(False))           # ricompare: il conteggio riparte
    for _ in range(tt._LOST_AFTER - 1):
        tab.on_snapshot(empty)
    assert d["current_jid"] == 42
    tab.on_snapshot(empty)
    assert d["current_jid"] is None
    assert d["last_status"] == "err" and "#42" in d["last_error"]
    assert finished == [False]
    assert "ultimo: ✕ giro perso" in tab._rec_item[def_id].text(4)
    tab.tree.setCurrentItem(tab._rec_item[def_id])
    assert tab.btn_run_now.isEnabled()     # il giro successivo è consentito


class _SlowApi(_OfflineApi):
    """rcd lento: ogni chiamata dura `delay` secondi."""

    def __init__(self, delay=1.5):
        self.delay = delay
        self.purged = False

    def start_transfer(self, *_a, **_k):
        import time
        time.sleep(self.delay)
        return 77

    def operations_list(self, _fs):
        import time
        time.sleep(self.delay)
        return [] if self.purged else [{"Path": "doc/a.txt", "Size": 5,
                                        "ModTime": "2026-11-20T10:00:00Z"}]

    def purge(self, _fs):
        import time
        time.sleep(self.delay)
        self.purged = True


def test_slow_daemon_does_not_block_the_scheduler(qapp):
    """P2-6: l'avvio di un giro ⏰ girava nel timer della GUI (fino a 20 s)."""
    import time
    from clonaut.ui.transfers_tab import TransfersTab
    ctx = _Ctx()
    ctx.api = _SlowApi()
    tab = TransfersTab(ctx)
    tab._rec_timer.stop()
    started = []
    tab.job_started.connect(started.append)
    def_id = tab.add_recurring("copy", "/a", "/b", [], 3600)
    tab.tree.setCurrentItem(tab._rec_item[def_id])
    t0 = time.monotonic()
    tab._on_rec_tick()
    assert time.monotonic() - t0 < 0.5
    assert tab._rec_item[def_id].text(4) == "… Avvio del giro"
    assert not tab.btn_run_now.isEnabled()
    tab._on_rec_tick()                       # nessun secondo avvio in parallelo
    assert len(tab._rec_starters) == 1
    _wait_starts(qapp, tab)
    d = tab._recurrent[def_id]
    assert d["current_jid"] == 77 and "starting" not in d
    assert tab._rec_item[def_id].text(0) == "#77"
    assert tab._meta[77]["rec"] == def_id and started == [77]


def test_schedule_removed_while_starting_keeps_the_run(qapp, dialogs):
    from clonaut.ui.transfers_tab import TransfersTab
    ctx = _Ctx()
    ctx.api = _SlowApi(0.5)
    tab = TransfersTab(ctx)
    tab._rec_timer.stop()
    started = []
    tab.job_started.connect(started.append)
    def_id = tab.add_recurring("copy", "/a", "/b", [], 3600)
    tab._on_rec_tick()
    tab._remove_recurring(def_id)
    _wait_starts(qapp, tab)
    assert started == [77] and "rec" not in tab._meta[77]
    tab.on_snapshot({"agg": {}, "jobs": {77: {"status": {"finished": False},
                                               "stats": {}}}})
    assert tab.tree.topLevelItem(0).text(0) == "77"   # riga normale in coda


def test_trash_dialog_does_not_block(qapp, dialogs):
    """P2-11: elenco e svuotamento del cestino giravano nel thread della GUI."""
    import time
    from clonaut.ui.trash_dialog import TrashDialog
    ctx = _Ctx()
    ctx.api = _SlowApi(1.0)
    t0 = time.monotonic()
    dlg = TrashDialog(ctx, "/backup-cestino")
    assert time.monotonic() - t0 < 0.5
    assert dlg.tree.topLevelItem(0).text(0) == "(lettura del cestino…)"
    assert dlg.busy() and not dlg.btn_empty.isEnabled()
    assert spin(qapp, 5, until=lambda: not dlg.busy())
    assert dlg.tree.topLevelItem(0).text(0) == "doc/a.txt"

    t0 = time.monotonic()
    dlg._empty()
    assert time.monotonic() - t0 < 0.5
    assert dialogs == ["Svuotare il cestino?"]
    assert dlg.tree.topLevelItem(0).text(0) == "(svuotamento in corso…)"
    assert spin(qapp, 8, until=lambda: dlg.tree.topLevelItem(0).text(0)
                == "(cestino vuoto)")
    assert ctx.api.purged and not dlg.busy() and dlg.btn_refresh.isEnabled()


def test_closing_the_trash_dialog_while_busy(qapp):
    """Chiusa durante un'operazione: niente blocco, thread tenuto in vita."""
    from clonaut import worker as worker_mod
    from clonaut.ui.trash_dialog import TrashDialog
    ctx = _Ctx()
    ctx.api = _SlowApi(1.0)
    dlg = TrashDialog(ctx, "/backup-cestino")
    running = dlg._worker
    dlg.reject()
    assert not dlg.busy() and running in worker_mod._lingering
    assert worker_mod.wait_lingering(5000)


def test_files_summary_dice_annullato_o_con_errori(qapp):
    from clonaut.ui.transfers_tab import TransfersTab
    tab = TransfersTab(_Ctx())
    tab._rec_timer.stop()
    stats = {"transfers": 1, "totalTransfers": 3}
    cases = {
        "Job terminato.": {"finished": True, "success": True},
        "Job annullato.": {"finished": True, "success": False, "error": "context canceled"},
        "Job terminato con errori.": {"finished": True, "success": False, "error": "boom"},
    }
    for head, status in cases.items():
        assert tab._files_summary({"status": status, "stats": stats}, True).startswith(head)


def test_programmazioni_che_usano_un_remote(qapp):
    from clonaut.ui.transfers_tab import TransfersTab
    tab = TransfersTab(_Ctx())
    tab._rec_timer.stop()
    tab.add_recurring("copy", "/casa", "demo:backup", [], 3600)
    tab.add_recurring("sync", "/a", "/b", [], 3600, backup_dir="demo:cestino")
    tab.add_recurring("copy", "demox:x", "/c", [], 3600)    # altro remote
    assert tab.schedules_using_remote("demo") == ["/casa → demo:backup", "/a → /b"]
    assert tab.schedules_using_remote("nessuno") == []
