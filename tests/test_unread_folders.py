"""Vue « Non lus » : elle couvre aussi les messages rangés dans les dossiers (règles, IA, rangement manuel) — sauf Spam, Corbeille, Envoyés,
Brouillons — et ces non lus sont resynchronisés depuis le serveur, sans télécharger tout le dossier."""
import os, sys, time, types
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gtkstub   # noqa: F401
from test_listing import make_window
from test_folder_replication import _win
from mintmail.models import Message
from mintmail import backend as B


def _msg(i, folder, unread=True, uid=None, acct="a1"):
    return Message(id="u%d" % i, account=acct, folder=folder, uid=uid if uid is not None else 100 + i, real_folder=folder, sender_name="S",
                   sender_email="s%d@x.be" % i, subject="Sujet %d" % i, date=time.time() - i, snippet="x", text="x", html="<p>x</p>", unread=unread)


def _mine(w):
    return {m.id for m in w.cache.query("unread", "all", limit=500) if m.id.startswith("u")}


def _fill(w):
    w.cache.upsert_many([_msg(1, "inbox"), _msg(2, "f:LTD"), _msg(3, "archive"), _msg(4, "spam"), _msg(5, "trash"), _msg(6, "sent"),
                         _msg(7, "drafts"), _msg(8, "f:LTD", unread=False), _msg(9, "f:Clients")])


def test_unread_view_includes_folders_but_not_spam_trash_sent_drafts():
    w, _ = _win(11)
    base = w.cache.counts()
    _fill(w)
    ids = _mine(w)
    assert ids == {"u1", "u2", "u3", "u9"}, ids                       # boîte + dossiers de rangement + archives ; pas spam/corbeille/envoyés/brouillons/lus
    c = w.cache.counts()
    assert c["unread"] - base["unread"] == 4 and c["inbox"] - base["inbox"] == 1     # le badge « Non lus » compte tout ; celui de la boîte reste la boîte


def test_snoozed_unread_in_a_folder_stays_hidden_until_it_wakes():
    w, _ = _win(12)
    m = _msg(2, "f:LTD"); w.cache.upsert_many([m]); w.cache.update_many([m.id], snoozed_until=time.time() + 3600)
    assert not _mine(w)


def test_jobs_cover_folders_with_server_unread_or_cached_unread_only():
    w, _ = _win(13)
    w.folder_tree = {"a1": [
        {"name": "INBOX", "path": "INBOX", "label": "INBOX", "depth": 0, "delim": "/", "special": "inbox", "selectable": True},
        {"name": "[Gmail]/Spam", "path": "Spam", "label": "Spam", "depth": 0, "delim": "/", "special": "spam", "selectable": True},
        {"name": "LTD", "path": "LTD", "label": "LTD", "depth": 0, "delim": "/", "special": "", "selectable": True},
        {"name": "Clients", "path": "Clients", "label": "Clients", "depth": 0, "delim": "/", "special": "", "selectable": True},
        {"name": "Vide", "path": "Vide", "label": "Vide", "depth": 0, "delim": "/", "special": "", "selectable": True},
        {"name": "Archives", "path": "Archives", "label": "Archives", "depth": 0, "delim": "/", "special": "archive", "selectable": True}]}
    w.folder_unread = {("a1", "LTD"): 3, ("a1", "[Gmail]/Spam"): 40}
    w.cache.upsert_many([_msg(9, "f:Clients")])                       # le cache connaît un non lu dans Clients : à revérifier (lu ailleurs ?)
    jobs = w._unread_jobs()
    assert sorted(jobs["a1"]) == ["f:Clients", "f:LTD"], jobs        # ni Spam, ni la boîte, ni « Vide » (rien de non lu), ni Archives (rien)


def test_sync_other_unread_stores_new_unread_and_forgets_what_was_read_or_moved_elsewhere():
    w, _ = _win(14)
    w.folder_tree = {"a1": [{"name": "LTD", "path": "LTD", "label": "LTD", "depth": 0, "delim": "/", "special": "", "selectable": True}]}
    w.folder_unread = {("a1", "LTD"): 2}
    old_read_elsewhere, gone = _msg(1, "f:LTD", uid=11), _msg(2, "f:LTD", uid=12)
    w.cache.upsert_many([old_read_elsewhere, gone])
    new = _msg(3, "f:LTD", uid=13)
    calls = []
    be = types.SimpleNamespace(demo=False, sync=lambda f, kn, limit, unseen: (calls.append((f, sorted(kn), unseen)) or ([new], {11: (False, False, None)}, {11, 13}, 0)))
    w.backend = lambda aid: be
    w.run_bg = lambda fn, done=None: done(*(fn(), None))
    w.accounts = lambda: [{"id": "a1"}]
    w.sync_other_unread()
    assert calls == [("f:LTD", [11, 12], True)]
    ids = _mine(w)
    assert ids == {"u3"}, ids              # u1 lu ailleurs, u2 supprimé / déplacé ailleurs, u3 nouveau non lu : bien là


def test_server_side_unseen_mode_downloads_only_unread_unknown_messages():
    be = B.IMAPBackend({"id": "a1", "email": "a@b.c"}, "")
    log = []

    class Imap:
        capabilities = ()
        def uid(self, cmd, *a):
            log.append((cmd,) + a)
            if cmd == "SEARCH":
                return "OK", [(b"10 11 12 13 14" if a[-1] == "ALL" else b"12 14")]
            if cmd == "FETCH":
                return "OK", [b"1 (UID 10 FLAGS (\\Seen))", b"2 (UID 11 FLAGS ())"] if "FLAGS" in a[-1] and "BODY" not in a[-1] else []
            return "OK", []
    be._run = lambda kind, fn: fn(types.SimpleNamespace(imap=Imap()))
    be._resolve = lambda imap, logical: "LTD"
    be._select = lambda c, real, readonly=False: None
    fetched = []
    be._fetch_batch = lambda imap, chunk, logical, real: (fetched.append(list(chunk)) or [])
    msgs, flags, present, minuid = be.sync("f:LTD", {10: "x10", 11: "x11", 12: "x12"}, limit=2, unseen=True)
    assert fetched == [[14]], fetched                                   # 12 est déjà connu ; 13 est lu et inconnu : pas téléchargé
    assert present == {10, 11, 12, 13, 14} and minuid == 0             # liste complète : sert à retirer ce qui a disparu
    assert flags[10][0] is False and flags[11][0] is True              # l'état des messages connus est relu (10 lu, 11 non lu)
