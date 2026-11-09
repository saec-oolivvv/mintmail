"""Test fidèle de la liste : un clic ouvre toujours le message, actions instantanées, sélection du suivant."""
import sys, time, os, types
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gtkstub   # noqa: F401  (installe les doublures de gi)
from mintmail.store import Config, Cache
from mintmail import window as W, widgets as WD
from mintmail.models import Message


class FakeLB:
    """ListBox minimale : mode simple, tri par épingle puis date, signaux row-selected."""
    def __init__(self):
        self.rows, self.sel, self.h = [], None, {}

    def connect(self, sig, fn, *a): self.h[sig] = fn
    def add(self, row): self.rows.append(row); row._lb = self
    def get_children(self): return list(self.rows)
    def _sorted(self): return sorted(self.rows, key=lambda r: (not r.msg.pinned, -r.msg.date))
    def remove(self, row):
        self.rows.remove(row)
        if self.sel is row:
            self.sel = None
            self.h["row-selected"](self, None)
    def select_row(self, row): self.sel = row; self.h["row-selected"](self, row)
    def unselect_all(self): self.sel = None
    def get_selected_row(self): return self.sel
    def get_selected_rows(self): return [self.sel] if self.sel else []
    def get_row_at_index(self, i):
        s = self._sorted()
        return s[i] if 0 <= i < len(s) else None
    def invalidate_sort(self): pass
    def invalidate_headers(self): pass
    def set_selection_mode(self, m): pass


class FakeReader:
    def __init__(self): self.msg, self.shown, self.opened = None, [], True
    def show_message(self, m, load_images=None): self.msg = m; self.shown.append(m.id)
    def show_empty(self, *a): self.msg = None
    def show_multi(self, n): self.msg = None
    def is_open(self): return self.opened
    def refresh_flags(self): pass
    def __getattr__(self, n): return lambda *a, **k: None


WD.MessageRow.get_index = lambda self: self._lb._sorted().index(self)


def make_window(n=300):
    cfg, cache = Config(os.path.join(gtkstub.tmp, "c%d.json" % n)), Cache(os.path.join(gtkstub.tmp, "c%d.db" % n))
    now = time.time()
    cache.upsert_many([Message(id="m%d" % i, account="demo", folder="inbox", uid=i + 1, sender_name="Exp %d" % i,
                               sender_email="e%d@x.be" % (i % 7), subject="Sujet %d" % i, date=now - i * 60,
                               snippet="aperçu", text="corps %d" % i, html="<p>corps</p>", unread=(i % 2 == 0))
                       for i in range(n)])
    w = W.MainWindow.__new__(W.MainWindow)
    w.config, w.cache = cfg, cache
    w.view, w.account, w.category, w.search = "inbox", "all", None, ""
    w.unread_only = w.att_only = w.select_mode = False
    w.narrow = w.reader_open = False
    w._limit, w._loading, w._pending, w.rows = 100, False, 0, {}
    w.listbox, w.reader = FakeLB(), FakeReader()
    w.listbox.connect("row-selected", w._on_row_selected)
    w.list_stack, w.empty_lbl, w.status, w.toast = gtkstub.D(), gtkstub.D(), gtkstub.D(), gtkstub.D()
    w.toast.popup = lambda *a, **k: w.__dict__.setdefault("toasts", []).append(a)
    w.bulk_rev, w.bulk_lbl, w.digest_box = gtkstub.D(), gtkstub.D(), gtkstub.D()
    w.ai_open_message = lambda m: None
    w.refresh_digest_visibility = lambda: None
    w.update_counts = lambda: None
    w._layout = lambda: None
    w.run_bg = lambda fn, done=None: None
    w._effective_search = lambda: ""
    w._view_title = lambda: "Boîte"
    w._backends = {}
    w.backend = lambda aid: gtkstub.D()
    return w


def test_one_click_always_opens():
    w = make_window()
    w.reload_list(full=True)
    assert len(w.rows) == 100                      # pagination : 100 lignes d'abord
    a, b, c = (w.listbox.get_row_at_index(i) for i in (0, 1, 2))
    w.listbox.select_row(a); assert w.reader.msg.id == a.msg.id
    w.listbox.select_row(b); assert w.reader.msg.id == b.msg.id      # 1 seul clic suffit même si un message est chargé
    w.listbox.select_row(c); assert w.reader.msg.id == c.msg.id
    assert w.reader.shown[-3:] == [a.msg.id, b.msg.id, c.msg.id]
    assert not w.reader.msg.light and w.reader.msg.text               # le lecteur reçoit le message complet


def test_archive_is_instant_and_selects_next():
    w = make_window()
    w.reload_list(full=True)
    row = w.listbox.get_row_at_index(3)
    w.listbox.select_row(row)
    t = time.perf_counter()
    w.move_messages([row.msg], "archive")
    ms = (time.perf_counter() - t) * 1000
    assert row.msg.id not in w.rows and len(w.rows) == 99
    assert w.cache.get(row.msg.id).folder == "archive"
    assert w.reader.msg is not None and w.reader.msg.id == w.listbox.get_selected_row().msg.id != row.msg.id
    print("archivage d'un message : %.1f ms" % ms)
    assert ms < 150


def test_bulk_spam_sender_is_one_transaction():
    w = make_window()
    w.reload_list(full=True)
    target = w.listbox.get_row_at_index(0).msg
    w.config["spam_senders"] = []
    t = time.perf_counter()
    w.spam_sender(target)
    ms = (time.perf_counter() - t) * 1000
    spam = w.cache.query("spam", limit=1000)
    same = [m for m in w.cache.query("archive") + w.cache.query("inbox", limit=1000)
            if m.sender_email == target.sender_email]
    assert len(spam) > 30 and not same and target.sender_email in w.config["spam_senders"]
    assert all(m.id not in w.rows for m in spam)
    print("expéditeur en spam (%d messages) : %.1f ms" % (len(spam), ms))
    assert ms < 400


def test_incremental_reload_keeps_selection_and_rows():
    w = make_window()
    w.reload_list(full=True)
    row = w.listbox.get_row_at_index(5)
    w.listbox.select_row(row)
    ids = set(w.rows)
    shown = len(w.reader.shown)
    w.cache.update_many(["m50"], starred=True)           # changement ailleurs (synchro) : pas de reconstruction
    w.reload_list()
    assert set(w.rows) == ids and w.rows[row.msg.id] is row and w.listbox.get_selected_row() is row
    assert len(w.reader.shown) == shown                   # le message affiché n'est pas rechargé inutilement
    assert w.rows["m50"].msg.starred


def test_unselected_removal_keeps_current_message():
    w = make_window()
    w.reload_list(full=True)
    cur = w.listbox.get_row_at_index(2)
    w.listbox.select_row(cur)
    other = w.listbox.get_row_at_index(7).msg
    w.move_messages([other], "trash")                     # action « au survol » sur une autre ligne
    assert w.reader.msg.id == cur.msg.id and w.listbox.get_selected_row() is cur


def test_sender_menus_block_and_spam_by_address_and_domain():
    w = make_window(60)
    w.reload_list(full=True)
    msg = w.listbox.get_row_at_index(0).msg
    who, dom = msg.sender_email, "@" + msg.sender_email.split("@")[-1]
    items = w.sender_menu_items("spam", msg)
    assert [lab for lab, _ in items] == ["Signaler ce message comme spam", "Mettre %s en spam" % who,
                                         "Mettre tout le domaine %s en spam" % dom]
    items[1][1]()                                                       # expéditeur en spam
    assert who in w.config["spam_senders"] and w.cache.query("spam", limit=500)
    assert all(m.sender_email != who for m in w.cache.query("inbox", limit=500))
    items[2][1]()                                                       # tout le domaine en spam
    assert dom in w.config["spam_senders"] and not w.cache.query("inbox", limit=500)
    w2 = make_window(61)
    w2.reload_list(full=True)
    m2 = w2.listbox.get_row_at_index(0).msg
    b = w2.sender_menu_items("block", m2)
    assert b[0][0] == "Bloquer %s" % m2.sender_email and b[1][0].startswith("Bloquer tout le domaine @")
    b[0][1]()
    assert m2.sender_email in w2.config["blocked"] and w2.cache.query("trash", limit=500)
    assert w2.sender_menu_items("block", m2)[-1][0] == "Débloquer %s" % m2.sender_email   # l'entrée de déblocage apparaît
    more = [lab for lab, _ in w2.sender_menu_items("more", m2)]
    assert any(l.startswith("Marquer comme") for l in more) and any("Copier l'adresse" in l for l in more)


def test_message_rows_have_no_hover_action_bar():
    """La barre d'actions au survol des cadres de messages est supprimée (actions : clic droit, raccourcis, balayage)."""
    import inspect
    src = inspect.getsource(WD.MessageRow)
    assert "hover" not in src.lower() and "_quick" not in src
    w = make_window(10)
    w.reload_list(full=True)
    assert "hover_ev" not in w.listbox.get_row_at_index(0).__dict__


def _click_env(w, index):
    """Un clic reçu par un widget INTERNE de la carte du message n° index ; y est relatif à la carte (petit), comme dans GTK."""
    rows = w.listbox._sorted()
    target = rows[index]

    class Child:
        def get_parent(self_): return target
    WD.Gtk.get_event_widget = lambda e: e.widget
    FakeLB.get_row_at_y = lambda self, y: self._sorted()[int(y) // 72]          # ancien comportement : y relatif à la carte -> ligne 0
    FakeLB.unselect_row = lambda self, row: setattr(self, "sel", None)
    return rows, target, types.SimpleNamespace(button=3, x=40.0, y=12.0, widget=Child())


def test_right_click_targets_the_clicked_message_not_the_latest_one():
    """Régression : le menu clic droit (et donc toutes les actions IA) visait toujours le dernier message reçu."""
    w = make_window(30)
    w.reload_list(full=True)
    rows, target, ev = _click_env(w, 9)
    assert target is not rows[0]
    seen = []
    w.ai_menu_items = lambda m: (seen.append(m.id), [])[1]
    w.build_snooze_menu = lambda cb=None: gtkstub.D()
    w.build_move_menu = lambda msgs=None: gtkstub.D()
    w._on_list_context(w.listbox, ev)
    assert w.listbox.get_selected_row() is target and seen == [target.msg.id]          # le message cliqué, pas le premier
    # clic sur un autre message : le menu suit
    _rows, target2, ev2 = _click_env(w, 3)
    seen.clear()
    w._on_list_context(w.listbox, ev2)
    assert seen == [target2.msg.id] and w.listbox.get_selected_row() is target2


def test_selection_mode_click_toggles_the_clicked_row():
    w = make_window(30)
    w.reload_list(full=True)
    rows, target, ev = _click_env(w, 5)
    w.select_mode = True
    target.is_selected = lambda: False
    ev.button = 1
    assert w._on_list_click(w.listbox, ev) is True and w.listbox.get_selected_row() is target


def test_row_at_event_falls_back_to_coordinate_translation():
    w = make_window(10)
    w.reload_list(full=True)
    rows = w.listbox._sorted()

    class Orphan:                                    # widget sans ligne parente : conversion de coordonnées vers la liste
        def get_parent(self_): return None
        def translate_coordinates(self_, dest, x, y): return (x, y + 72 * 4)
    WD.Gtk.get_event_widget = lambda e: e.widget
    FakeLB.get_row_at_y = lambda self, y: self._sorted()[int(y) // 72]
    ev = types.SimpleNamespace(button=3, x=5.0, y=10.0, widget=Orphan())
    assert WD.row_at_event(w.listbox, ev) is rows[4]
