"""Vue « Non lus » : le message ouvert reste affiché (liste + lecteur) tant qu'on n'est pas passé à un autre ; il part alors, ou si on agit dessus."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gtkstub   # noqa: F401
from test_listing import make_window


def _unread_window(n):
    w = make_window(n)
    w.view = "unread"
    w.reload_list(full=True)
    return w


def _open(w, idx):
    row = w.listbox.get_row_at_index(idx)
    w.listbox.select_row(row)
    return row.msg.id


def test_opened_unread_message_stays_even_after_it_became_read_and_the_list_reloads():
    w = _unread_window(60)
    first = _open(w, 0)
    assert w.cache.get(first).unread is False                      # ouvert = lu côté cache et serveur
    for _ in range(3):
        w.reload_list()                                            # synchro, minuterie, compteurs… : plusieurs rechargements
    assert first in w.rows and w.reader.msg is not None and w.reader.msg.id == first      # toujours dans la liste ET dans le lecteur
    assert w.listbox.get_selected_row().msg.id == first


def test_it_leaves_the_list_only_when_you_move_to_the_next_one():
    w = _unread_window(61)
    first = _open(w, 0)
    w.reload_list()
    second = _open(w, 1)
    assert second != first and first not in w.rows and second in w.rows        # le précédent part, le nouveau reste affiché
    assert w.reader.msg.id == second
    w.reload_list()
    assert second in w.rows and first not in w.rows


def test_deselecting_removes_it():
    w = _unread_window(62)
    first = _open(w, 0)
    w._on_row_selected(None, None)                                  # plus rien de sélectionné
    assert first not in w.rows


def test_an_action_on_the_message_removes_it_at_once():
    w = _unread_window(63)
    first = _open(w, 0)
    w.move_messages([w.rows[first].msg], "archive")
    assert first not in w.rows
    w.reload_list()
    assert first not in w.rows                                      # et il ne revient pas : il est classé


def test_other_views_and_search_are_unaffected():
    w = make_window(64)
    w.view = "inbox"
    w.reload_list(full=True)
    first = _open(w, 0)
    assert getattr(w, "_unread_keep", set()) == set()
    w.view = "unread"
    w.reload_list(full=True)
    assert first not in w.rows                                      # lu dans la boîte : n'apparaît pas dans « Non lus »


def test_startup_survives_a_last_view_that_is_not_a_smart_box():
    """Dernière vue = Envoyés, Archives, un dossier… : la barre latérale ne définissait alors jamais la ligne initiale (AttributeError au démarrage)."""
    src_f = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mintmail", "folders.py"), encoding="utf-8").read()
    src_w = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mintmail", "window.py"), encoding="utf-8").read()
    assert "self._nav_initial = None" in src_f and src_f.index("self._nav_initial = None") < src_f.index("for vid in SMART_VIEWS:")
    assert "if self._nav_initial is not None:" in src_w
