"""Cache : conversations, apprentissage, actions en attente, contacts, envois réservables."""
import json, os, sqlite3, sys, tempfile, time
tmp = tempfile.mkdtemp()
os.environ["XDG_DATA_HOME"] = tmp
os.environ["XDG_CONFIG_HOME"] = tmp
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mintmail.models import Message, Outgoing
from mintmail.store import Cache


def cache(name):
    return Cache(os.path.join(tmp, name + ".db"))


def msg(i, subject, refs="", mid=None, folder="inbox", date=None, unread=True, sender="a@x.be", name="A", to="moi@x.be"):
    return Message(id="m%s" % i, account="acc", folder=folder, uid=i, sender_name=name, sender_email=sender, to=to, subject=subject,
                   date=date or (1000 + i), message_id=mid if mid is not None else "<m%s@x>" % i, references=refs, unread=unread,
                   text="corps %s" % i, snippet="x")


def test_conversations_grouping_members_and_subject_fallback():
    c = cache("t1")
    c.upsert_many([msg(1, "Projet CRM"), msg(2, "Re: Projet CRM", refs="<m1@x>", unread=False), msg(3, "Re: Projet CRM", refs="<m1@x> <m2@x>"),
                   msg(4, "Autre sujet"), msg(5, "Re: Projet CRM", mid="", refs="", folder="sent", sender="moi@x.be")])
    threads = c.query("inbox", threads=True)
    assert [m.subject for m in threads] == ["Autre sujet", "Re: Projet CRM"]              # une ligne par conversation, la plus récente d'abord
    top = threads[1]
    assert top.id == "m3" and top.thread_count == 3 and top.thread_unread is True         # m1, m2, m3 (m5 est dans « envoyés »)
    assert [m.id for m in c.thread_members("acc", "<m1@x>")] == ["m1", "m2", "m3", "m5"]  # m5 rattaché par l'objet, ordre chronologique
    flat = c.query("inbox", threads=False)
    assert len(flat) == 4
    c.update_many(["m1", "m3"], unread=False)
    assert c.query("inbox", threads=True)[1].thread_unread is False


def test_old_rows_get_thread_keys_on_backfill():
    path = os.path.join(tmp, "old2.db")
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE messages (id TEXT PRIMARY KEY, account TEXT, folder TEXT, uid INTEGER, date REAL, unread INTEGER, starred INTEGER, pinned INTEGER, snoozed REAL, has_att INTEGER, category TEXT, sender TEXT, search TEXT, data TEXT)")
    d = msg(1, "Ancien", refs="<racine@x>").to_dict()
    db.execute("INSERT INTO messages VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", ("m1", "acc", "inbox", 1, 1.0, 1, 0, 0, 0, 0, "people", "a", "a", json.dumps(d)))
    db.commit(); db.close()
    c = Cache(path)
    c.backfill_meta()
    assert c.thread_members("acc", "<racine@x>")[0].id == "m1"


def test_learning_counts_and_suggests_after_two_moves():
    c = cache("t3")
    assert c.learn_best("acc", "alice@x.be") is None
    assert c.learn_record("acc", "alice@x.be", "Factures") == 1 and c.learn_best("acc", "alice@x.be") is None
    assert c.learn_record("acc", "alice@x.be", "Factures") == 2 and c.learn_best("acc", "alice@x.be") == "Factures"
    c.learn_record("acc", "@x.be", "Clients"); c.learn_record("acc", "@x.be", "Clients")
    assert c.learn_best("acc", "bob@x.be") == "Clients"                                  # repli sur le domaine
    assert c.learn_examples("acc") and c.learn_examples("acc")[0][1] in ("Factures", "Clients")
    c.learn_clear()
    assert c.learn_best("acc", "alice@x.be") is None


def test_ops_queue_lifecycle():
    c = cache("t4")
    a = c.ops_add("acc", "move", {"dest": "trash", "items": [{"uid": 1, "real": "INBOX"}]})
    b = c.ops_add("acc", "flags", {"seen": True, "items": []})
    assert c.ops_count() == 2 and [o["id"] for o in c.ops_pending()] == [a, b]
    c.ops_fail(a)
    assert c.ops_pending()[0]["tries"] == 1 and c.ops_pending()[0]["payload"]["dest"] == "trash"
    c.ops_done(a)
    assert c.ops_count() == 1


def test_contacts_rebuild_manual_lock_search_and_completion():
    c = cache("t5")
    c.upsert_many([msg(1, "s", sender="marie@x.be", name="Marie Dupont", to="moi@x.be, \"Paul\" <paul@y.be>"),
                   msg(2, "s2", sender="marie@x.be", name="Marie Dupont")])
    assert c.contacts_rebuild() >= 3
    lst = {x["email"]: x for x in c.contacts_list()}
    assert lst["marie@x.be"]["name"] == "Marie Dupont" and lst["marie@x.be"]["n"] == 2 and lst["paul@y.be"]["name"] == "Paul"
    c.contact_upsert("marie@x.be", "Marie D. (Alpha)", "+32 475", "Alpha", "VIP", source="manual")
    c.contacts_rebuild()                                                                  # la saisie manuelle n'est jamais écrasée
    m = [x for x in c.contacts_list() if x["email"] == "marie@x.be"][0]
    assert m["source"] == "manual" and m["name"] == "Marie D. (Alpha)" and m["phone"] == "+32 475"
    assert c.contacts_list()[0]["email"] == "marie@x.be"                                  # les fiches manuelles d'abord
    assert [x["email"] for x in c.contacts_list(query="alpha")] == ["marie@x.be"]
    assert ("Marie D. (Alpha)", "marie@x.be") in c.contacts()
    c.contact_delete("marie@x.be")
    assert all(x["email"] != "marie@x.be" for x in c.contacts_list())


def test_outbox_claim_is_atomic_and_reschedules():
    c = cache("t6")
    c.outbox_add("o1", time.time() - 1, Outgoing(account="acc", to="a@b.be", subject="S", html="<p>x</p>"))
    due = c.outbox_due()
    assert len(due) == 1
    assert c.outbox_claim("o1") is True and c.outbox_claim("o1") is False                # un seul processus gagne
    assert c.outbox_claim("o1", ttl=1) is False
    c.outbox_reschedule("o1", time.time() - 1)                                            # échec réseau : nouvel essai, réservation levée
    assert c.outbox_claim("o1") is True
    assert c.outbox_list()[0][3] == 1                                                     # une tentative comptée
    c.outbox_remove("o1")
    assert c.outbox_count() == 0
