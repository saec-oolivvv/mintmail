"""Priorités des messages : en-têtes de l'expéditeur, votre choix, tri, en-têtes d'envoi, partage entre machines."""
import os
import sys
import tempfile
import time
from email.message import EmailMessage
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import testenv
from mintmail import priority as PR
from mintmail.models import Message, Outgoing
from mintmail.store import Cache, Config

ACC = {"id": "a1", "name": "Pro", "email": "moi@exemple.be", "username": "moi", "imap_host": "h", "demo": True}


def em(**h):
    m = EmailMessage()
    for k, v in h.items():
        m[k.replace("_", "-")] = v
    return m


def test_from_headers():
    assert PR.from_headers(em(X_Priority="1 (Highest)")) == PR.HIGH and PR.from_headers(em(X_Priority="2")) == PR.HIGH
    assert PR.from_headers(em(Importance="High")) == PR.HIGH and PR.from_headers(em(Priority="urgent")) == PR.HIGH
    assert PR.from_headers(em(X_Priority="5 (Lowest)")) == PR.LOW and PR.from_headers(em(Importance="low")) == PR.LOW
    assert PR.from_headers(em(X_Priority="3 (Normal)")) == PR.NORMAL and PR.from_headers(em()) == PR.NORMAL


def test_headers_round_trip():
    for lv in PR.LEVELS:
        m = em(**{k.replace("-", "_"): v for k, v in PR.headers(lv).items()})
        assert PR.from_headers(m) == lv
    assert PR.headers(PR.NORMAL) == {}


def test_effective_and_sort():
    assert PR.effective(None, PR.HIGH) == PR.HIGH and PR.effective(PR.NORMAL, PR.HIGH) == PR.NORMAL and PR.effective(PR.LOW, PR.HIGH) == PR.LOW
    assert PR.clamp(9) == 1 and PR.clamp(-9) == -1 and PR.clamp("x") == 0
    assert PR.sort_score(PR.HIGH, 1) > PR.sort_score(PR.NORMAL, 3) > PR.sort_score(PR.LOW, 3)
    assert PR.mark(PR.HIGH).strip() and PR.mark(PR.LOW).strip() and PR.mark(PR.NORMAL) == ""


def test_store_priority_by_message_id():
    cache = Cache(os.path.join(tempfile.mkdtemp(), "c.db"))
    a = Message(id="m1", account="a1", folder="inbox", uid=1, sender_email="s@x.be", subject="A", date=time.time(), message_id="<a@x>")
    b = Message(id="m2", account="a1", folder="inbox", uid=2, sender_email="s@x.be", subject="B", date=time.time(), message_id="<b@x>")
    cache.upsert_many([a, b])
    assert cache.priority_map([a, b]) == {}
    cache.set_priority([a], PR.HIGH)
    cache.set_priority([b], PR.NORMAL)
    assert cache.priority_map([a, b]) == {"m1": 1, "m2": 0}
    a.id = "autre-id"                                               # le message a changé de dossier : même Message-ID, même priorité
    assert cache.priority_map([a]) == {"autre-id": 1}
    cache.set_priority([a], PR.LOW)
    assert cache.priority_map([a]) == {"autre-id": -1}


def test_engine_priority_event_and_apply():
    from mintmail.qt import viewmodel as V
    from mintmail import mailevents as ME
    cfg = Config(os.path.join(tempfile.mkdtemp(), "c.json"))
    cfg.data["accounts"] = [ACC]
    cache = Cache(os.path.join(tempfile.mkdtemp(), "c.db"))
    m = Message(id="m1", account="a1", folder="inbox", uid=1, sender_email="s@x.be", subject="A", date=time.time(), message_id="<a@x>")
    cache.upsert_many([m])
    eng = V.Engine(cfg, cache)
    sunk = []
    eng.event_sink = sunk.extend
    eng.set_priority([cache.get_light("m1")], PR.HIGH)
    assert cache.priority_map([m]) == {"m1": 1} and [e["k"] for e in sunk] == ["prio_high"] and cache.ops_count() == 0
    other_cfg = Config(os.path.join(tempfile.mkdtemp(), "c.json"))
    other_cfg.data["accounts"] = [ACC]
    other_cache = Cache(os.path.join(tempfile.mkdtemp(), "c.db"))
    other_cache.upsert_many([m])
    other = V.Engine(other_cfg, other_cache)
    other.event_sink = lambda evs: sunk.append("écho")
    assert other.apply_mail_events(sunk[:1]) == 1 and other_cache.priority_map([m]) == {"m1": 1} and "écho" not in sunk
    old = {"k": "prio_low", "mid": "<a@x>", "acct": "moi@exemple.be", "ts": time.time() - 5}
    assert [e["k"] for e in ME.newest_per_message([sunk[0], old])] == ["prio_high"]


def test_infos_and_models():
    from mintmail.qt import viewmodel as V
    m = Message(id="m1", account="a1", folder="inbox", uid=1, sender_email="s@x.be", subject="A", date=time.time())
    assert not [r for r in V.info_facts(m, [ACC]) if r[1] == PR.label(PR.HIGH)]
    assert (PR.label(PR.HIGH)) in [r[1] for r in V.info_facts(m, [ACC], 0, PR.HIGH)]
    assert Message.from_dict({"id": "x", "account": "a", "importance": 1}).importance == 1 and Outgoing("a", "t", "s", "h").priority == 0


def test_remote_image_urls():
    from mintmail.util import remote_image_urls
    h = '<p><img src="https://a.fr/x.png?a=1&amp;b=2"><img src=\'//b.fr/y.gif\'><img src="cid:z"><img src="data:image/png;base64,AA"><img src="https://a.fr/x.png?a=1&amp;b=2"></p>'
    assert remote_image_urls(h) == ["https://a.fr/x.png?a=1&b=2", "https://b.fr/y.gif"]
    assert remote_image_urls("") == []
