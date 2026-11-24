"""Journal d'activité, frein anti-blocage des connexions, messages supprimés qui ne doivent pas revenir."""
import os
import sys
import tempfile
import time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import testenv
from mintmail import activity as AC, throttle as TH
from mintmail.backend import BackendError
from mintmail.models import Message
from mintmail.store import Cache, Config

ACC = {"id": "a1", "name": "Pro", "email": "moi@exemple.be", "username": "moi", "imap_host": "h", "demo": True}


def test_log_current_and_busy():
    log = AC.Log()
    assert log.current() == (None, "")
    log.add(AC.OK, "fini")
    assert log.current() == (AC.OK, "fini")
    log.start("k", "Relève…")
    log.start("k2", "Autre…")
    lvl, txt = log.current()
    assert lvl == AC.BUSY and "(+1)" in txt and len(log.busy()) == 2
    log.finish("k", AC.OK, "relevé")
    log.finish("k2")
    assert log.current() == (AC.OK, "relevé") and [e["text"] for e in log.entries(2)] == ["relevé", "fini"]
    seen = []
    log.subscribe(lambda: seen.append(1))
    log.add(AC.INFO, "x")
    assert seen == [1] and "x" in AC.line(log.entries(1)[0])
    log.clear()
    assert log.entries() == []


def test_log_is_bounded():
    log = AC.Log(maxlen=5)
    for i in range(20):
        log.add(AC.INFO, str(i))
    assert len(log.entries(100)) == 5 and log.entries(1)[0]["text"] == "19"


def test_sync_summary():
    assert AC.sync_summary("a@b", 0, 0, 0).endswith("rien de nouveau")
    assert "3" in AC.sync_summary("a@b", 3, 1, 0) and "1" in AC.sync_summary("a@b", 3, 1, 0)


def test_classify():
    assert TH.classify("[AUTHENTICATIONFAILED] Invalid credentials") == TH.AUTH
    assert TH.classify("b'LOGIN failed.'") == TH.AUTH
    assert TH.classify("Too many login attempts, account blocked") == TH.AUTH
    assert TH.classify("[UNAVAILABLE] Maximum number of connections exceeded") == TH.BUSY
    assert TH.classify("Too many simultaneous connections") == TH.BUSY
    assert TH.classify("[Errno 111] Connection refused") is None and TH.classify("timed out") is None


def test_breaker_backoff_and_password_change():
    t = [1000.0]
    br = TH.Breaker(clock=lambda: t[0])
    fp = TH.fingerprint("secret")
    assert br.left("a", fp) == 0
    w1 = br.failed("a", TH.AUTH, fp)
    assert w1 == 120 and br.left("a", fp) == 120
    t[0] += 121
    assert br.left("a", fp) == 0
    w2 = br.failed("a", TH.AUTH, fp)
    assert w2 == 300                                              # de plus en plus long
    assert br.left("a", TH.fingerprint("nouveau")) == 0           # mot de passe corrigé : on réessaie tout de suite
    br.failed("b", TH.BUSY, "")
    assert br.left("b", "") == 30 and br.left("a", "x") == 0
    br.ok("b")
    assert br.left("b", "") == 0
    for _ in range(12):
        w = br.failed("c", TH.AUTH, fp)
    assert w == 3600 and TH.human_wait(30) == "30 s" and TH.human_wait(300) == "5 min"
    assert fp != "secret" and "secret" not in fp


def test_backend_breaker_blocks_reconnect():
    from mintmail import backend as B
    be = B.IMAPBackend({"id": "zz9", "email": "x@y.be", "username": "x", "imap_host": "h", "imap_port": 993}, "pw")
    calls = []

    def raw():
        calls.append(1)
        import imaplib
        raise imaplib.IMAP4.error("[AUTHENTICATIONFAILED] Invalid credentials")
    be._connect_raw = lambda pw=None: raw()
    B.IMAPBackend.BREAKER.reset()
    for _ in range(3):
        try:
            be._connect()
            assert False
        except BackendError as e:
            assert e.cooldown and e.retryable and e.wait > 0
    assert len(calls) == 1                                        # un seul vrai essai : les suivants sont retenus par le frein
    assert be.cooldown_left() > 0
    B.IMAPBackend.BREAKER.reset()


def _engine():
    from mintmail.qt import viewmodel as V
    cfg = Config(os.path.join(tempfile.mkdtemp(), "c.json"))
    cfg.data["accounts"] = [ACC]
    cache = Cache(os.path.join(tempfile.mkdtemp(), "c.db"))
    return V.Engine(cfg, cache), cache


def test_held_ids_covers_race_and_expires():
    eng, cache = _engine()
    eng.mark_gone(["m1"])
    now = time.time()
    assert "m1" in eng.held_ids(now) and "m2" not in eng.held_ids(now)
    assert "m1" not in eng.held_ids(now + eng.GONE_TTL + 5)


def test_move_marks_gone_and_logs():
    eng, cache = _engine()
    m = Message(id="m1", account="a1", folder="inbox", uid=5, real_folder="INBOX", sender_email="s@x.be", subject="A", date=time.time(), message_id="<a@x>")
    cache.upsert_many([m])
    AC.LOG.clear()
    eng.move([m], "trash")
    assert "m1" in eng.held_ids() and any("→" in e["text"] for e in AC.LOG.entries(5))
    eng.delete_forever([m])
    assert "m1" in eng.held_ids()


def test_cooldown_does_not_burn_op_tries_or_drop_op():
    eng, cache = _engine()
    m = Message(id="m1", account="a1", folder="inbox", uid=5, real_folder="INBOX", sender_email="s@x.be", subject="A", date=time.time(), message_id="<a@x>")
    cache.upsert_many([m])
    eng.op_enqueue("delete", [m])

    def boom(op):
        raise BackendError("suspendue", retryable=True, cooldown=True, wait=120)
    eng._op_exec = boom
    for _ in range(12):
        done, errors, offline = eng.op_run(cache.ops_pending())
        assert offline and not errors
    assert cache.ops_count() == 1 and cache.ops_pending()[0]["tries"] == 0
    AC.LOG.clear()

    def refuse(op):
        raise BackendError("Suppression refusée", retryable=False)
    eng._op_exec = refuse
    done, errors, offline = eng.op_run(cache.ops_pending())
    assert errors and cache.ops_count() == 0 and any(e["level"] == AC.ERR for e in AC.LOG.entries(5))


def test_sync_does_not_resurrect_message_deleted_during_fetch():
    eng, cache = _engine()
    m = Message(id="m1", account="a1", folder="inbox", uid=5, real_folder="INBOX", sender_email="s@x.be", subject="A", date=time.time(), message_id="<a@x>")
    cache.upsert_many([m])

    class Slow:
        demo = False

        def sync(self, f, kn, limit=60, **kw):
            if f != "inbox":
                return [], {}, {5}, 0
            eng.move([cache.get("m1")], "trash")                  # l'utilisateur supprime PENDANT la réponse du serveur
            again = Message(id="m1", account="a1", folder="inbox", uid=5, real_folder="INBOX", sender_email="s@x.be", subject="A", date=time.time(), message_id="<a@x>")
            return [again], {}, {5}, 0
    eng._backends["a1"] = Slow()
    AC.LOG.clear()
    eng.sync(folders=("inbox",))
    assert cache.get("m1").folder == "trash"
    assert any("ramené" in e["text"] or "ramenés" in e["text"] for e in AC.LOG.entries(10))


def test_badge_label():
    from mintmail import notifyrules as NR
    assert [NR.badge_label(n) for n in (0, -3, None, 1, 9, 99, 100, 5000)] == ["", "", "", "1", "9", "99", "99+", "99+"]


def test_new_message_decision_is_logged_in_plain_words():
    from mintmail.qt import automation as AU
    from mintmail import groups as G
    cfg = Config(os.path.join(tempfile.mkdtemp(), "c.json"))
    cfg.data["accounts"] = [ACC]
    gr = G.Grouper(cfg, None, [ACC])
    pub = Message(id="p1", account="a1", folder="inbox", uid=1, sender_name="Boutique", sender_email="promo@shop.be", subject="-50% aujourd'hui", date=time.time(), category="news", unread=True)
    perso = Message(id="p2", account="a1", folder="inbox", uid=2, sender_name="Paul", sender_email="paul@x.be", subject="Salut", date=time.time(), category="people", unread=True, to="a@b.be, c@d.be")
    t = AU.decision_text(pub, None, gr)
    assert "Newsletters" in t and "regroupé" in t and "non lu" in t and "-50%" in t
    assert "boîte de réception" in AU.decision_text(perso, None, gr)
    assert "spam" in AU.decision_text(pub, "spam", gr)


def test_poll_plan_is_gentler_for_gmail_and_with_idle():
    from mintmail import pollplan as PP
    gm = {"id": "g", "imap_host": "imap.gmail.com"}
    ov = {"id": "o", "imap_host": "mail.ovh.net"}
    assert PP.is_prone(gm) and not PP.is_prone(ov)
    base = PP.plan([ov], {})
    idle = PP.plan([ov], {"o": "ok"})
    assert idle["live"] > base["live"] and base["live"] >= 8000 and base["folders"] >= 90000          # bien moins que 6 s / 20 s d'avant
    g = PP.plan([gm], {"g": "ok"})
    assert g["live"] > idle["live"] and g["folders"] >= 240000 and g["max_folders"] <= 30 and base["max_folders"] == 80
    assert PP.plan([], {})["live"] > 0 and PP.plan([{"id": "d", "demo": True}], {})["max_folders"] == 80
    assert PP.is_virtual("[Gmail]/All Mail") and PP.is_virtual("[Gmail]/Important") and PP.is_virtual("[Gmail]/Tous les messages") and not PP.is_virtual("Clients/Important-ish") and not PP.is_virtual("INBOX")


def test_429_is_a_slowdown_not_a_failure():
    assert TH.classify("HTTP Error 429: Too Many Requests") == TH.BUSY
    assert TH.classify("Quota exceeded for quota metric 'Queries'") == TH.BUSY
    assert TH.classify("b'[AUTHENTICATIONFAILED] Invalid credentials (Failure)'") == TH.AUTH
    from mintmail import backend as B
    be = B.IMAPBackend({"id": "g429", "email": "x@gmail.com", "username": "x", "imap_host": "imap.gmail.com", "imap_port": 993}, "pw")
    B.IMAPBackend.BREAKER.reset()
    calls = []

    def raw(pw=None):
        calls.append(1)
        raise BackendError("OAuth : HTTP Error 429: Too Many Requests")
    be._connect_raw = raw
    for _ in range(3):
        try:
            be._connect()
            assert False
        except BackendError as e:
            assert e.cooldown and e.wait > 0 and e.retryable
    assert len(calls) == 1
    B.IMAPBackend.BREAKER.reset()
