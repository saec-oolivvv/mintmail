"""Doublures de GTK (module gi) pour tester la logique Python sans interface graphique."""
import os, sys, tempfile, types, time
tmp = tempfile.mkdtemp()
os.environ["XDG_DATA_HOME"] = tmp
os.environ["XDG_CONFIG_HOME"] = tmp
os.environ["MINTMAIL_NO_KEYRING"] = "1"       # les tests ne touchent JAMAIS au trousseau réel (clés d'API, mots de passe de l'utilisateur)
os.environ["HOME"] = tmp                      # ni à son dossier personnel
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
    def get_selected_row(self): return None
    def get_row_at_index(self, i): return None
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

