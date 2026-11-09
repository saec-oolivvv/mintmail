"""Dossiers : arborescence IMAP (Gmail / Dovecot), mUTF-7, STATUS, CRUD, synchro d'un dossier quelconque, arbre de la barre latérale."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gtkstub
from mintmail.backend import IMAPBackend, utf7_decode, utf7_encode
from mintmail.models import Message
from test_backend import FakeIMAP, backend, msgs

GMAIL = [b'(\\HasNoChildren) "/" "INBOX"', b'(\\HasChildren \\Noselect) "/" "[Gmail]"',
         b'(\\HasNoChildren \\Sent) "/" "[Gmail]/Messages envoy&AOk-s"', b'(\\HasNoChildren \\Trash) "/" "[Gmail]/Corbeille"',
         b'(\\HasNoChildren \\Junk) "/" "[Gmail]/Spam"', b'(\\HasNoChildren \\Drafts) "/" "[Gmail]/Brouillons"',
         b'(\\HasChildren \\HasNoChildren) "/" "Clients"', b'(\\HasNoChildren) "/" "Clients/Alpha"',
         b'(\\HasNoChildren) "/" "Factures &AMk-mises"', b'(\\HasNoChildren) "/" "Archive"']
DOVECOT = [b'(\\HasChildren) "." "INBOX"', b'(\\HasNoChildren \\Sent) "." "INBOX.Sent"', b'(\\HasNoChildren) "." "INBOX.Projets.CRM"']


class ListIMAP(FakeIMAP):
    def __init__(self, log, lines, **kw):
        super().__init__(log, **kw)
        self.lines = lines

    def list(self): return "OK", self.lines

    def status(self, name, items):
        self.log.append(("status", name))
        return "OK", [("%s (MESSAGES 12 UNSEEN 3)" % name).encode()]

    def create(self, name): self.log.append(("create", name)); return "OK", []
    def rename(self, a, b): self.log.append(("rename", a, b)); return "OK", []
    def delete(self, name): self.log.append(("delete", name)); return "OK", []
    def unselect(self): return "OK", []


def be_with(lines):
    log = []
    be = backend(log)
    be._connect = lambda: ListIMAP(log, lines)
    return be, log


def test_gmail_tree():
    be, _ = be_with(GMAIL)
    tree = be.list_folders()
    names = [e["path"] for e in tree]
    assert names[0] == "INBOX" and tree[0]["special"] == "inbox"
    by = {e["name"]: e for e in tree}
    assert by["[Gmail]"]["selectable"] is False                                   # parent non sélectionnable mais visible
    assert by["[Gmail]/Messages envoy&AOk-s"]["label"] == "Messages envoyés"        # accent décodé pour l'affichage
    assert by["[Gmail]/Messages envoy&AOk-s"]["special"] == "sent" and by["[Gmail]/Messages envoy&AOk-s"]["depth"] == 1
    assert by["Factures &AMk-mises"]["label"] == "Factures Émises"
    assert by["Archive"]["special"] == "archive"                                     # deviné par le nom
    assert [e["name"] for e in tree if e["name"].startswith("Clients")] == ["Clients", "Clients/Alpha"]
    assert be._folders_cache["sent"] == "[Gmail]/Messages envoy&AOk-s" and be._folders_cache["trash"] == "[Gmail]/Corbeille"
    assert tree.index(by["Clients"]) < tree.index(by["Clients/Alpha"])             # parents avant enfants


def test_dovecot_namespace_is_flattened():
    be, _ = be_with(DOVECOT)
    tree = {e["name"]: e for e in be.list_folders()}
    assert tree["INBOX.Sent"]["depth"] == 0 and tree["INBOX.Sent"]["special"] == "sent"
    assert tree["INBOX.Projets.CRM"]["path"] == "Projets › CRM" and tree["INBOX.Projets.CRM"]["depth"] == 1


def test_status_crud_and_custom_sync_move():
    be, log = be_with(GMAIL)
    be.list_folders()
    assert be.folder_status(["Clients/Alpha", "INBOX"]) == {"Clients/Alpha": (12, 3), "INBOX": (12, 3)}
    be.create_folder("Été 2026")
    assert ("create", '"&AMk-t&AOk- 2026"') in log                                   # nom encodé en mUTF-7
    be.rename_folder("Clients/Alpha", "Clients/Alpha Corp")
    be.delete_folder("Factures &AMk-mises")
    assert ("rename", '"Clients/Alpha"', '"Clients/Alpha Corp"') in log and ("delete", '"Factures &AMk-mises"') in log
    res = be.sync("f:Clients/Alpha", {}, limit=5)[0]                                 # un dossier quelconque se synchronise
    assert len(res) == 5 and ("select", '"Clients/Alpha"', True) in log
    be.move_many(msgs([3]), "f:Clients/Alpha")
    assert ("MOVE", "3", '"Clients/Alpha"') in log


def test_sidebar_tree_collapse_and_titles():
    from mintmail import window as W, folders as F
    w = W.MainWindow.__new__(W.MainWindow)
    w.config = {"saved_searches": [{"name": "Marie", "query": "from:marie"}], "folders": {}, "collapsed_folders": []}
    w.accounts = lambda: [{"id": "a1", "name": "Pro", "email": "p@x.be"}, {"id": "a2", "name": "Perso", "email": "q@x.be"}]
    w._init_folders = lambda: None
    w.folder_tree, w.folder_unread, w._folder_badges = {}, {("a1", "Clients"): 4}, {}
    w._dyn_rows, w._nav_guard, w._collapsed, w.nav_labels = [], False, set(), []
    w.nav, w.cache = gtkstub.D(), gtkstub.D()
    w.cache.counts = lambda aid: {"inbox": 2, "drafts": 0, "snoozed": 0}
    w._reselect_nav = lambda: None
    w.view, w.account = "inbox", "all"
    w.folder_tree["a1"] = [dict(name="INBOX", path="INBOX", label="INBOX", depth=0, delim="/", special="inbox", selectable=True),
                           dict(name="Clients", path="Clients", label="Clients", depth=0, delim="/", special="", selectable=True),
                           dict(name="Clients/Alpha", path="Clients › Alpha", label="Alpha", depth=1, delim="/", special="", selectable=True),
                           dict(name="Clients/Beta", path="Clients › Beta", label="Beta", depth=1, delim="/", special="", selectable=True)]
    g = lambda r, k: r.__dict__.get(k)          # (les doublures renvoient un objet pour tout attribut absent)
    F.FolderMixin._rebuild_nav_dynamic(w)
    entries = [g(r, "entry") for r in w._dyn_rows if g(r, "entry")]
    assert [e["name"] for e in entries][:4] == ["INBOX", "Clients", "Clients/Alpha", "Clients/Beta"]
    assert len([r for r in w._dyn_rows if g(r, "toggle_key")]) == 2        # un en-tête repliable par compte
    w._collapsed.add("a1|Clients")                                                      # replier « Clients »
    F.FolderMixin._rebuild_nav_dynamic(w)
    names = [g(r, "entry")["name"] for r in w._dyn_rows if g(r, "entry") and g(r, "account") == "a1"]
    assert "Clients" in names and "Clients/Alpha" not in names
    w._collapsed.add("acc:a2")                                                          # compte 2 replié : plus de dossiers
    F.FolderMixin._rebuild_nav_dynamic(w)
    assert not [r for r in w._dyn_rows if g(r, "account") == "a2" and g(r, "entry")]
    assert F.dest_of(entries[0]) == "inbox" and F.dest_of(entries[2]) == "f:Clients/Alpha"
    w.tree_of = lambda aid: w.folder_tree.get(aid) or F.DEFAULT_TREE
    got = F.FolderMixin.find_folder(w, "clients › beta", "a1")
    assert got and got[1]["name"] == "Clients/Beta" and F.FolderMixin.find_folder(w, "inconnu", "a1") is None
    w.TITLES = W.TITLES
    w.view, w.account = "f:Clients/Alpha", "a1"
    assert F.FolderMixin._view_title(w).startswith("Clients › Alpha")
