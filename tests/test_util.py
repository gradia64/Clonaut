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
