"""Attribuer / partager : tâche suivie, relance, fenêtre de rédaction préparée."""
import datetime
import os
import sys
import time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import testenv
from mintmail.models import Message
from mintmail.qt import delegation as D
from mintmail.qt import organizer as O


class Cfg(dict):
    def save(self): pass


def cfg():
    return Cfg(tasks=[], followups=[])


def msg():
    return Message(id="m1", account="a1", folder="inbox", sender_name="Client", sender_email="client@x.be", subject="Devis à valider", to="moi@x.be",
                   message_id="<1@x>", text="Bonjour", html="<p>Bonjour</p>", date=time.time() - 100)


def test_clean_recipients():
    assert D.clean_recipients("a@x.be; b@y.be") == "a@x.be, b@y.be" and D.clean_recipients("pas une adresse") == "" and D.clean_recipients("") == ""


def test_assign_creates_task_and_followup():
    c, m = cfg(), msg()
    t, note = D.assign(c, m, "collegue@x.be", "Merci de chiffrer", "15/12/2030", 3, now=1000.0)
    assert t and t["assignee"] == "collegue@x.be" and t["due"] == "2030-12-15" and "collegue@x.be" in t["text"] and "Devis" in t["text"]
    assert c["followups"] == [{"id": "m1:assign:collegue@x.be", "at": 1000.0 + 3 * 86400, "subject": "Devis à valider", "date": 1000.0, "to": "collegue@x.be"}]
    assert D.assigned_open(c) == [t] and "2030" in note
    assert D.assign(c, m, "collegue@x.be", "", "", 3)[0] is None                       # pas de doublon
    assert D.assign(c, m, "n'importe quoi")[0] is None and len(c["tasks"]) == 1
    O.task_set_done(c, t["id"])
    assert D.assigned_open(c) == []


def test_no_followup_when_zero_days():
    c = cfg()
    D.assign(c, msg(), "x@y.be", follow_days=0)
    assert c["followups"] == []


def test_compose_args_forward_with_intro():
    kw = D.compose_args({"identities": []}, [{"id": "a1", "email": "moi@x.be"}], msg(), "collegue@x.be", "Merci de chiffrer", datetime.date(2030, 12, 15), "a1")
    assert kw["to"] == "collegue@x.be" and kw["subject"] == "Fwd: Devis à valider" and "Bonjour" in kw["quote_html"]
    assert "Peux-tu t'en occuper" in kw["ai_suggested_text"] and "Merci de chiffrer" in kw["ai_suggested_text"] and "15/12/2030" in kw["ai_suggested_text"]
    share = D.compose_args({"identities": []}, [{"id": "a1", "email": "moi@x.be"}], msg(), "p@x.be", assign_=False)
    assert share["ai_suggested_text"].startswith("Pour information")


def test_followup_fires_only_without_reply():
    from mintmail.store import Cache
    import tempfile
    c, m = cfg(), msg()
    t0 = time.time() - 10 * 86400
    D.assign(c, m, "collegue@x.be", now=t0)
    cache = Cache(os.path.join(tempfile.mkdtemp(), "d.db"))
    due = O.due_followups(c, cache)
    assert len(due) == 1 and due[0]["to"] == "collegue@x.be"
    c2 = cfg()
    D.assign(c2, Message(id="m2", account="a1", folder="inbox", sender_email="c@x.be", subject="Autre"), "collegue@x.be", now=t0)
    cache.upsert_many([Message(id="r1", account="a1", folder="inbox", uid=1, sender_email="collegue@x.be", subject="Re: Fwd: Autre", date=time.time() - 86400)])
    assert O.due_followups(c2, cache) == [] and c2["followups"] == []                  # réponse reçue : pas de relance, l'entrée est retirée
