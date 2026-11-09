"""Barre d'actions au survol : plus de clignotement (masquage différé), toujours cliquable."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gtkstub   # noqa: F401
from mintmail import widgets as WD
from mintmail.models import Message


def make_row():
    m = Message(id="1", account="a", sender_name="A", sender_email="a@b.be", subject="S", date=1.0, snippet="x")
    return WD.MessageRow(m, None, None, {}, 72, {})


def test_no_flicker_when_pointer_moves_between_card_and_bar():
    timers, removed, shown = {}, [], []
    WD.GLib.timeout_add = lambda ms, fn, *a: timers.setdefault(len(timers) + 1, fn) and len(timers)
    WD.GLib.source_remove = lambda tid: removed.append(tid)
    row = make_row()
    row.hover_ev = type("E", (), {"show": lambda s: shown.append("show"), "hide": lambda s: shown.append("hide")})()
    row._hover_enter(row.card, None)
    assert shown == ["show"]
    # le pointeur quitte la carte pour entrer dans la barre : aucun « hide » entre les deux
    row._hover_leave(row.card, None)
    assert shown == ["show"] and row._hover_timer                 # masquage seulement programmé
    row._hover_enter(row.hover_ev, None)
    assert removed and row._hover_timer == 0 and shown == ["show", "show"]
    # passage barre -> bouton -> barre : toujours rien de masqué
    row._hover_leave(row.hover_ev, None)
    row._hover_enter(row.hover_ev, None)
    assert "hide" not in shown
    # le pointeur quitte vraiment la ligne : la barre se masque une fois le délai écoulé
    row._hover_leave(row.card, None)
    timers[max(timers)]()
    assert shown[-1] == "hide" and row._hover_timer == 0

