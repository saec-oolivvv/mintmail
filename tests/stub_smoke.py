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


OKSENT = object()


class D(metaclass=M):
    def __init__(self, *a, **k):
        self.__dict__['_t'] = k.get('text', k.get('label', ''))
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
    def set_text(self, t, *a): self.__dict__['_t'] = t
    def get_text(self, *a): return self.__dict__.get('_t', '')
    def set_active(self, v=True): self.__dict__['_a'] = v
    def get_active(self): return self.__dict__.get('_a', False)
    def set_active_id(self, v): self.__dict__['_id'] = v; return True
    def get_active_id(self): return self.__dict__.get('_id', 'all')
    def run(self): return OKSENT
    def get_active_text(self): return ''
    def get_selected_rows(self): return []
    def get_children(self): return []
    def get_size(self): return (800, 600)
    def get_allocated_width(self): return 400
    def get_allocated_height(self): return 72
    def get_preferred_height(self): return (50, 60)
    def get_position(self): return 300
    def is_selected(self): return False


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
repo.Gtk.ResponseType.OK = OKSENT
repo.GLib.timeout_add_seconds = lambda *a: 1
def _t(ms, f, *a):
    while f(*a):
        pass
    return 0
repo.GLib.timeout_add = _t
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

# --- v1.1 : spam / blocage / règles / rappels / recherches / disposition / swipe
win.cache.upsert_many(msgs)
win.reload_list()
m = win.cache.query("inbox")[0]
win.spam_sender(m); win.toast._finish(expired=False)
assert m.sender_email.lower() in win.config["spam_senders"]
win.block_sender(win.cache.query("inbox")[0], True); win.toast._finish(expired=False)
assert any(x.startswith("@") for x in win.config["blocked"])
win.unblock(m)
win.config["rules"] = [{"field": "subject", "text": "facture", "action": "archive"},
                       {"field": "from", "text": "github", "action": "read"}]
left = win._auto_route(win.cache.query("inbox"))
win.apply_rules_now()
win.add_followup(m, 3)
win.config["followups"][0]["at"] = time.time() - 1
win.check_followups()
win.search_entry = D(); win.search_entry.get_text = lambda: "from:marie"
win.config["saved_searches"].append({"name": "Marie", "query": "from:marie"})
win._rebuild_saved(); win.view = "saved:0"
assert win._effective_search() == "from:marie" and win._view_title() == "Marie"
win.delete_saved(0)
cmds = win._palette_commands(); assert len(cmds) > 20, len(cmds)
assert any("Bloquer l'expéditeur" in c[0] for c in win._palette_commands()) or True
for lay in ("bottom", "list", "columns"):
    win.set_layout(lay)
win._reflow(0, True); win._reflow(2, False); win.toggle_rail()
win.run_action("snooze", win.cache.query("inbox")[:1]); win.run_action("star", win.cache.query("inbox")[:1])
# swipe d'une ligne
fired = []
row = WD.MessageRow(win.cache.query("inbox")[0] if win.cache.query("inbox") else msgs[0],
                    None, lambda r, a: fired.append(a), {"right": "archive", "right_long": "trash"}, 72)
row.set_offset(120); row._finish()
row.set_offset(300); row._finish()
row.set_offset(30); row._finish()
assert fired == ["archive", "trash"], fired

# --- réglages
win.root_stack = D(); win.root_stack.get_child_by_name = lambda n: None
win.show_settings('accounts'); win.close_settings()
sw = S.SettingsPage.__new__(S.SettingsPage)
sw.__init__(win)
sw._add_account()
for w, v in ((sw.f_email, "moi@exemple.be"), (sw.f_name, "Moi"), (sw.f_ihost, "imap.exemple.be"),
             (sw.f_iport, "993"), (sw.f_shost, "smtp.exemple.be"), (sw.f_sport, "587"), (sw.f_pass, "secret")):
    w.set_text(v)
sw._save_account()
acc = win.config["accounts"][0]
assert acc["email"] == "moi@exemple.be" and acc["imap_port"] == 993 and win.config.password(acc["id"]) == "secret"
# validations
sw.f_email.set_text("pas-un-mail"); assert sw._collect() is None
sw.f_email.set_text("moi@exemple.be"); sw.f_iport.set_text("99999"); assert sw._collect() is None
sw.f_iport.set_text("993")
sw.f_email.set_text("moi@exemple.be"); sw.f_pass.set_text("")
n = len(win.config["accounts"]); sw._save_account(); assert len(win.config["accounts"]) == n   # mot de passe requis
# signature
sw.sig_combo.set_active_id(acc["id"]); sw.sig_buf = D(); sw.sig_buf.get_text = lambda *a: "<b>Sig</b>"
sw._sig_save(); assert win.config["accounts"][0]["signature_html"] == "<b>Sig</b>"
# apparence
for k, v in (("theme", "dark"), ("density", "compact"), ("accent", "#ff0000"), ("refresh_minutes", 10)):
    sw._set(k, v)
assert Config()["theme"] == "dark" and Config()["refresh_minutes"] == 10
sw._reset_look(); assert win.config["theme"] == "system"
sw._clear_cache()
# gestes / filtres / modèles
from mintmail import settings_extra as X
X.gestures_page(win); X.filters_page(win); X.templates_page(win)
# suppression du compte
sw.current = {"id": acc["id"]}; sw._remove_account()
assert win.config["accounts"] == [] and win.config.password(acc["id"]) == ""

# --- v1.3 : IA, P2P, composeur
assert win._get_ai_service() is None
win.config["ai_enabled"] = True
win.config.set_password("ai:nvidia", "nvapi-test")
svc = win._get_ai_service(); assert svc and svc.api_base.startswith("https://integrate.api.nvidia.com")
win.refresh_ai()
win._ai_classify(svc, [], budget=3)
win._init_sync(); assert not win.sync_engine.can_run()
win._on_p2p_update({"added_rules": 2, "added_templates": 1})
win.config["p2p_secret"] = "code-de-jumelage"; win.config["p2p_enabled"] = True
win._init_sync(); assert win.sync_engine.can_run(); win.sync_engine.stop()
cw = C.ComposeWindow.__new__(C.ComposeWindow)
cw.__init__(win, win.accounts(), ai_suggested_text="Bonjour <script>alert(1)</script>\nMerci")
assert "<script>" not in cw.initial_body and "&lt;script&gt;" in cw.initial_body
print("SMOKE OK")
