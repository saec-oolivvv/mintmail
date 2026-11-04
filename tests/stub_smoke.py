"""Test de fumée sans GTK : remplace gi par des doublures pour attraper
fautes de nom / attributs manquants dans la logique Python de l'application."""
import os, sys, tempfile, types, time
tmp = tempfile.mkdtemp()
os.environ["XDG_DATA_HOME"] = tmp
os.environ["XDG_CONFIG_HOME"] = tmp
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class M(type):
    def __getattr__(cls, n):
        if n.startswith("__"):
            raise AttributeError(n)
        return D()


class D(metaclass=M):
    def __init__(self, *a, **k): pass
    def __getattr__(self, n):
        if n.startswith("__"):
            raise AttributeError(n)
        return D()
    def __call__(self, *a, **k): return D()
    def __iter__(self): return iter(())
    def __len__(self): return 0
    def __bool__(self): return True
    def __getitem__(self, i): return D()
    def __lt__(self, o): return False
    def __le__(self, o): return False
    def __gt__(self, o): return False
    def __ge__(self, o): return False
    def __or__(self, o): return D()
    def __and__(self, o): return 0
    def __int__(self): return 0
    def __index__(self): return 0
    def __format__(self, spec): return ""
    def __str__(self): return ""
    def get_text(self, *a): return ""
    def get_active(self): return False
    def get_active_id(self): return 'all'
    def get_active_text(self): return ''
    def get_selected_rows(self): return []
    def get_children(self): return []
    def get_size(self): return (800, 600)


class Mod(types.ModuleType):
    def __getattr__(self, n):
        if n.startswith("__"):
            raise AttributeError(n)
        c = type(n, (D,), {})
        setattr(self, n, c)
        return c


gi = types.ModuleType("gi")
gi.require_version = lambda *a, **k: None
repo = types.ModuleType("gi.repository")
for name in ("Gtk", "Gdk", "Gio", "GLib", "GObject", "Pango", "WebKit2"):
    setattr(repo, name, Mod(name))
repo.GLib.idle_add = lambda f, *a: None
repo.GLib.timeout_add_seconds = lambda *a: 1
repo.GLib.timeout_add = lambda *a: 1
repo.GLib.source_remove = lambda *a: None
class SigFlags: RUN_FIRST = 1
repo.GObject.SignalFlags = SigFlags
sys.modules.update({"gi": gi, "gi.repository": repo})
gi.repository = repo

from mintmail.store import Config, Cache
from mintmail import window as W, compose as C, settings as S, reader as R, widgets as WD
from mintmail.models import Message, Outgoing

win = W.MainWindow.__new__(W.MainWindow)
# __init__ complet : app factice
win.__init__(D(), Config(), Cache())
assert win.cache.query("inbox") == []   # sync asynchrone désactivé (idle_add neutralisé)

# sync démo exécutée de façon synchrone
acc = win.accounts()[0]
be = win.backend(acc["id"])
msgs, flags, present, mn = be.sync("inbox", {})
win.cache.upsert_many(msgs)
win._sync_done([(acc["id"], "inbox", (msgs, flags, present, mn), None)], None, {(acc["id"], "inbox"): {}}, True)
win.reload_list()
assert len(win.rows) == len(msgs), (len(win.rows), len(msgs))
win.update_counts()
m = msgs[0]
win.set_unread([m], False); win.set_flag([m], "starred", True); win.set_flag([m], "pinned", True)
win.move_messages([msgs[1]], "archive")
assert win.cache.get(msgs[1].id).folder == "archive"
win.toast._finish(expired=False)
win.snooze_selected(time.time() + 3600) if False else None
win.reply(m); win.reply(m, True); win.forward(m); win.open_draft(m)
win.reader.msg = m; win.quick_reply("Merci !")
assert win.cache.outbox_count() == 1
for oid, out in [(1, None)]: pass
win.build_snooze_menu(); win.show_palette = win.show_palette
win._nav_selected(D(), types.SimpleNamespace(view="starred"))
win._reader_action(win.reader, "star"); win._reader_action(win.reader, "pin")
win._on_size(None, types.SimpleNamespace(width=700)); win._on_size(None, types.SimpleNamespace(width=1400))
win.apply_settings(); win.toggle_theme(); win.mark_all_read()
print("SMOKE OK")
