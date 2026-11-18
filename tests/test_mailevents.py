"""Événements de messagerie entre machines : validation, application locale sans écho, envoi chiffré en direct."""
import os
import sys
import tempfile
import time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import testenv
from mintmail import mailevents as ME
from mintmail.models import Message
from mintmail.store import Cache, Config

ACC = {"id": "a1", "name": "Pro", "email": "Moi@Exemple.be", "username": "moi", "imap_host": "h", "demo": True}


def msg(i, folder="inbox", unread=True, mid=None):
    return Message(id="m%d" % i, account="a1", folder=folder, uid=i, sender_email="s@x.be", subject="S%d" % i, date=time.time() - i,
                   message_id=mid or "<id%d@x>" % i, unread=unread)


def test_make_and_sanitize():
    m = msg(1)
    assert ME.make("read", m, "moi@x.be")["k"] == "read" and ME.make("move", m, "moi@x.be") is None and ME.make("move", m, "moi@x.be", "trash")["to"] == "trash"
    assert ME.make("read", Message(id="z", account="a", message_id=""), "moi@x.be") is None and ME.make("bidon", m, "moi@x.be") is None
    now = 10_000.0
    good = {"k": "star", "mid": "<a@x>", "acct": "Moi@X.be", "ts": now - 5}
    bad = [{"k": "star", "mid": "", "acct": "a@x.be", "ts": now}, {"k": "rm -rf", "mid": "<a>", "acct": "a@x.be", "ts": now}, "texte", 5,
           {"k": "star", "mid": "<a>", "acct": "pas-une-adresse", "ts": now}, {"k": "star", "mid": "<a>", "acct": "a@x.be", "ts": now - 99999},
           {"k": "star", "mid": "<a>", "acct": "a@x.be", "ts": now + 99999}, {"k": "star", "mid": "<a>", "acct": "a@x.be", "ts": True},
           {"k": "move", "mid": "<a>", "acct": "a@x.be", "ts": now}]
    out = ME.sanitize([good] + bad, now)
    assert out == [{"k": "star", "mid": "<a@x>", "acct": "moi@x.be", "ts": now - 5}] and ME.sanitize("n'importe quoi", now) == []
    assert len(ME.sanitize([good] * 2000, now)) == ME.MAX_EVENTS


def test_newest_event_wins_per_family():
    a = {"k": "read", "mid": "<1>", "acct": "a@x.be", "ts": 1.0}
    b = {"k": "unread", "mid": "<1>", "acct": "a@x.be", "ts": 2.0}
    c = {"k": "star", "mid": "<1>", "acct": "a@x.be", "ts": 1.5}
    d = {"k": "move", "mid": "<1>", "acct": "a@x.be", "ts": 3.0, "to": "trash"}
    got = {e["k"] for e in ME.newest_per_message([b, a, c, d])}
    assert got == {"unread", "star", "move"}


def engine():
    from mintmail.qt import viewmodel as V
    cfg = Config(os.path.join(tempfile.mkdtemp(), "c.json"))
    cfg.data["accounts"] = [ACC]
    cache = Cache(os.path.join(tempfile.mkdtemp(), "c.db"))
    cache.upsert_many([msg(1), msg(2), msg(3, folder="trash")])
    return V.Engine(cfg, cache), cache


def test_apply_events_updates_cache_without_echo():
    eng, cache = engine()
    sunk = []
    eng.event_sink = sunk.extend
    now = time.time()
    n = eng.apply_mail_events([{"k": "read", "mid": "<id1@x>", "acct": "moi@exemple.be", "ts": now},
                               {"k": "star", "mid": "<id1@x>", "acct": "moi@exemple.be", "ts": now},
                               {"k": "move", "mid": "<id2@x>", "acct": "moi@exemple.be", "ts": now, "to": "archive"},
                               {"k": "delete", "mid": "<id3@x>", "acct": "moi@exemple.be", "ts": now},
                               {"k": "read", "mid": "<inconnu@x>", "acct": "moi@exemple.be", "ts": now},
                               {"k": "read", "mid": "<id1@x>", "acct": "autre@boite.be", "ts": now}])
    assert n == 4 and not cache.get("m1").unread and cache.get("m1").starred and cache.get("m2").folder == "archive" and cache.get("m3") is None
    assert sunk == [] and cache.ops_count() == 0                     # rien renvoyé aux autres machines ni au serveur


def test_local_actions_emit_events_for_other_machines():
    eng, cache = engine()
    sunk = []
    eng.event_sink = sunk.extend
    m1, m2 = cache.get_light("m1"), cache.get_light("m2")
    eng.set_flag([m1], "unread", False)
    eng.set_flag([m1, m2], "starred", True)
    eng.move([m2], "trash")
    eng.delete_forever([cache.get_light("m3")])
    kinds = [(e["k"], e["mid"], e.get("to")) for e in sunk]
    assert kinds == [("read", "<id1@x>", None), ("star", "<id1@x>", None), ("star", "<id2@x>", None), ("move", "<id2@x>", "trash"), ("delete", "<id3@x>", None)]
    assert {e["acct"] for e in sunk} == {"moi@exemple.be"}


def test_queue_batches_a_burst_into_one_delivery():
    got = []
    q = ME.Queue(got.append, delay=0.05)
    for i in range(30):
        q.push([{"k": "read", "mid": "<%d>" % i}])
    time.sleep(0.4)
    assert len(got) == 1 and len(got[0]) == 30


def test_events_travel_encrypted_between_two_machines():
    import socket
    from mintmail.p2p import SyncEngine
    sent = []
    orig = socket.socket.send
    socket.socket.send = lambda self, data, *a: (sent.append(bytes(data)), orig(self, data, *a))[1]

    def mk(name, tcp, disc, peers):
        c = Config(os.path.join(tempfile.mkdtemp(), name + ".json"))
        c.data.update(p2p_enabled=True, p2p_secret="code-de-jumelage-solide", p2p_port=tcp, p2p_disc_port=disc, p2p_static_peers=peers)
        return SyncEngine(c)
    a, b = mk("A", 55541, 55551, ["127.0.0.1:55542"]), mk("B", 55542, 55552, ["127.0.0.1:55541"])
    received = []
    b.events_cb = lambda evs, node: (received.extend(evs), len(evs))[1]
    try:
        assert b.start() and a.start()
        end = time.time() + 12
        while time.time() < end and not a._peers:
            time.sleep(0.15)
        assert a._peers, "pair non découvert"
        ev = {"k": "read", "mid": "<secret-id@x>", "acct": "moi@exemple.be", "ts": time.time()}
        a.push_events([ev])
        end = time.time() + 8
        while time.time() < end and not received:
            time.sleep(0.1)
        assert received == [ev]
        assert b"secret-id" not in b"".join(sent)                   # rien d'intelligible sur le réseau
    finally:
        socket.socket.send = orig
        a.stop(); b.stop()
