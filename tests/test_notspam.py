"""« Ce n'est pas du spam » : le message ET tous ceux du même expéditeur quittent Spam pour la boîte de réception,
le serveur est prévenu ($NotJunk, sortie du dossier), l'expéditeur sort de la liste « en spam », et l'IA suggère l'action."""
import os, sys, time, types
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gtkstub   # noqa: F401
from test_listing import make_window
from mintmail.models import Message
from mintmail import backend as B, offline as O


def _spam_window(tag):
    w = make_window(20 + tag)
    now = time.time()
    w.cache.upsert_many([
        Message(id="s%d" % i, account="demo", folder="spam", uid=900 + i, sender_name="N", sender_email=em, subject="S%d" % i,
                date=now - i, snippet="x", text="x", html="<p>x</p>", unread=True)
        for i, em in enumerate(["ami@boite.be", "ami@boite.be", "ami@boite.be", "autre@boite.be", "pub@ailleurs.com"])])
    w.config["spam_senders"] = ["ami@boite.be", "pub@ailleurs.com"]
    return w


def _folders(w):
    return {m.id: m.folder for m in w.cache.query("spam", limit=100) + w.cache.query("inbox", limit=100)
            if m.id.startswith("s")}


def test_not_spam_moves_every_message_of_the_sender_and_forgets_the_sender():
    w = _spam_window(1)
    w.not_spam(w.cache.get("s0"))
    f = _folders(w)
    assert [f["s0"], f["s1"], f["s2"]] == ["inbox"] * 3, f                 # les 3 messages de ami@boite.be
    assert f["s3"] == "spam" and f["s4"] == "spam", f                        # les autres expéditeurs ne bougent pas
    assert "ami@boite.be" not in w.config["spam_senders"] and "pub@ailleurs.com" in w.config["spam_senders"]
    assert "remis en boîte de réception" in w.toasts[-1][0] and "3 messages" in w.toasts[-1][0]


def test_not_spam_by_domain_and_toast_has_undo():
    w = _spam_window(2)
    w.not_spam(w.cache.get("s0"), domain=True)
    f = _folders(w)
    assert [f["s0"], f["s1"], f["s2"], f["s3"]] == ["inbox"] * 4 and f["s4"] == "spam", f
    assert w.toasts[-1][1] == "Annuler"                                       # on peut revenir en arrière


def test_not_spam_clears_the_red_spam_marker():
    w = _spam_window(3)
    w.cache.ai_set("s1", "triage", {"summary": "", "priority": 1, "spam": True})
    w.cache.ai_set("s1", "analysis", {"suspicious": True, "summary": "x"})
    w.not_spam(w.cache.get("s1"))
    assert not w.cache.ai_get("s1", "triage")["spam"] and not w.cache.ai_get("s1", "analysis")["suspicious"]


def test_menus_offer_not_spam_only_in_the_spam_folder():
    w = _spam_window(4)
    labels = [lab for lab, _ in w.sender_menu_items("spam", w.cache.get("s0"))]
    assert labels[0].startswith("✔ Ce n'est pas du spam : ami@boite.be") and "tout le domaine @boite.be" in labels[1]
    inbox = w.cache.query("inbox", limit=1)[0]
    assert not any("pas du spam" in lab for lab, _ in w.sender_menu_items("spam", inbox))


def test_server_gets_notjunk_flags_then_the_message_leaves_spam():
    be = B.IMAPBackend({"id": "a", "email": "a@b.c"}, "")
    log = []

    class Imap:
        capabilities = ("MOVE",)
        def uid(self, *a): log.append(a); return ("OK", [b"done"])
    conn = types.SimpleNamespace(imap=Imap())
    be._run = lambda kind, fn: fn(conn)
    be._resolve = lambda imap, dest: "INBOX"
    be._select = lambda c, real: log.append(("SELECT", real))
    msgs = [types.SimpleNamespace(uid=11, real_folder="[Gmail]/Spam"), types.SimpleNamespace(uid=12, real_folder="[Gmail]/Spam")]
    be.move_many(msgs, "inbox", notjunk=True)
    assert log == [("SELECT", "[Gmail]/Spam"), ("STORE", "11,12", "-FLAGS", "($Junk)"), ("STORE", "11,12", "+FLAGS", "($NotJunk)"),
                   ("MOVE", "11,12", '"INBOX"')], log
    log.clear()
    be.move_many(msgs, "inbox")                                               # sans l'option : comportement inchangé
    assert log == [("SELECT", "[Gmail]/Spam"), ("MOVE", "11,12", '"INBOX"')], log


def test_server_without_free_keywords_still_moves_the_message():
    be = B.IMAPBackend({"id": "a", "email": "a@b.c"}, "")
    log = []

    class Imap:
        capabilities = ()
        def uid(self, *a):
            log.append(a[0] + (a[2] if a[0] == "STORE" else ""))
            if a[0] == "STORE" and "Junk" in a[3]:
                raise RuntimeError("NO [CANNOT] keyword refused")
        def expunge(self): log.append("EXPUNGE")
    be._run = lambda kind, fn: fn(types.SimpleNamespace(imap=Imap()))
    be._resolve = lambda imap, dest: "INBOX"
    be._select = lambda c, real: None
    be.move_many([types.SimpleNamespace(uid=5, real_folder="Junk")], "inbox", notjunk=True)
    assert log[-3:] == ["COPY", "STORE+FLAGS", "EXPUNGE"], log               # COPY + suppression : le déplacement a bien eu lieu


def test_offline_queue_keeps_the_notjunk_intention():
    w = _spam_window(5)
    msgs = [types.SimpleNamespace(id="s0", account="a1", uid=7, real_folder="Junk")]
    got = {}
    w.cache.ops_add = lambda aid, kind, payload: got.update(kind=kind, payload=payload) or 1
    O_mix = O.OfflineMixin if hasattr(O, "OfflineMixin") else None
    enqueue = (O_mix or type(w)).op_enqueue
    enqueue(w, "move", msgs, dest="inbox", notjunk=True)
    assert got["kind"] == "move" and got["payload"]["notjunk"] is True and got["payload"]["dest"] == "inbox"
    calls = []
    be = types.SimpleNamespace(demo=False, move_many=lambda items, dest, **kw: calls.append((dest, kw)))
    w.backend = lambda aid: be
    (O_mix or type(w))._op_exec(w, {"account": "a1", "kind": "move", "payload": dict(got["payload"])})
    assert calls == [("inbox", {"notjunk": True})], calls
    calls.clear()                                                             # anciennes actions en file : appel inchangé
    (O_mix or type(w))._op_exec(w, {"account": "a1", "kind": "move", "payload": {"dest": "archive", "items": got["payload"]["items"]}})
    assert calls == [("archive", {})], calls


def test_reader_suggests_not_spam_only_for_a_legitimate_ai_verdict_in_spam():
    from mintmail import reader as R
    class Btns:
        def __init__(s): s.n = []
        def add(s, b): s.n.append(b)
        def show_all(s): pass
        def get_children(s): return list(s.n)
        def remove(s, c): s.n.remove(c)
    r = R.Reader.__new__(R.Reader)
    r.ai_sug, r.ai_sug_lbl, r.ai_sug_btns = gtkstub.D(), gtkstub.D(), Btns()
    sug = lambda msg, res: (r.ai_sug_btns.n.clear(), setattr(r, "msg", msg), R.Reader.ai_spam_suggestion(r, res))[2]
    spam, inbox = types.SimpleNamespace(folder="spam"), types.SimpleNamespace(folder="inbox")
    sug(spam, {"suspicious": True}); assert not r.ai_sug_btns.n                 # l'IA confirme le spam : rien à suggérer
    sug(inbox, {"suspicious": False}); assert not r.ai_sug_btns.n               # pas dans Spam
    sug(spam, {"suspicious": False, "local": True}); assert not r.ai_sug_btns.n   # analyse locale : pas d'avis fiable
    sug(spam, {"suspicious": False}); assert len(r.ai_sug_btns.n) == 1          # légitime : « Ce n'est pas du spam »
    sug(spam, {"suspicious": False, "folder": "Factures"}); assert len(r.ai_sug_btns.n) == 2   # + rangement dans un dossier


def test_ai_menu_and_assistant_know_not_spam():
    from mintmail import ai_engine as E
    assert "not_spam" in E.QUERY_ACTIONS
    w = _spam_window(7)
    w.cache.ai_set("s0", "triage", {"spam": True})
    w.selected_msgs = lambda: [w.cache.get("s0")]
    items = w._plan_items({"actions": [{"type": "not_spam", "query": ""}]})
    assert items[0][0] == "Ce n'est pas du spam (retour en boîte de réception) (1)", items


def test_assistant_action_not_spam_frees_each_sender_once():
    w = _spam_window(6)
    w.exec_action({"type": "not_spam", "query": ""}, [w.cache.get("s0"), w.cache.get("s1"), w.cache.get("s3")])
    f = _folders(w)
    assert [f["s0"], f["s1"], f["s2"], f["s3"]] == ["inbox"] * 4 and f["s4"] == "spam", f
