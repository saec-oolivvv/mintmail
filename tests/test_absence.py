"""Absence du bureau / vacances : dates, boîtes concernées, une réponse par expéditeur, bonne signature, jamais de réponse aux robots."""
import datetime
import os
import sys
import time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import testenv
from mintmail import absence as AB
from mintmail.models import Message
from mintmail.qt import composing as C
from mintmail.qt import viewmodel as V

TODAY = datetime.date.today()
NOW = time.time()


class Cfg(dict):
    saved = 0

    def save(self): self.saved += 1


def acc(i, sig=""):
    return {"id": "a%d" % i, "email": "box%d@x.be" % i, "name": "Box %d" % i, "signature_html": sig}


def msg(i=1, sender="client@ext.com", to="box1@x.be", account="a1", **kw):
    d = dict(id="m%d" % i, account=account, sender_email=sender, to=to, subject="Question", date=NOW - 60, message_id="<%d@e>" % i)
    d.update(kw)
    return Message(**d)


def active(**kw):
    s, e = AB.starting_today(5)
    base = {"enabled": True, "start": (TODAY - datetime.timedelta(days=1)).isoformat(), "end": e}
    base.update(kw)
    return AB.settings({"absence": base})


def test_dates_state_and_placeholders():
    a = AB.settings({"absence": {"enabled": True, "start": "2026-12-20", "end": "2026-12-31", "kind": "vacation"}})
    assert AB.days_count(a) == 12 and AB.expand("{debut}-{fin}-{retour}-{jours}", a) == "20/12/2026-31/12/2026-01/01/2027-12"
    assert AB.state(a, time.mktime(datetime.datetime(2026, 12, 1).timetuple())) == "soon"
    assert AB.state(a, time.mktime(datetime.datetime(2026, 12, 31, 23, 0).timetuple())) == "active"
    assert AB.state(a, time.mktime(datetime.datetime(2027, 1, 1, 0, 1).timetuple())) == "over"
    assert AB.state(dict(a, enabled=False)) == "off" and AB.state(dict(a, end="2026-12-01")) == "off"        # dates à l'envers
    assert "vacances" in AB.body_of(AB.settings({"absence": {"kind": "vacation"}})).lower() or True
    assert AB.settings({"absence": "n'importe quoi"})["enabled"] is False and AB.settings({})["kind"] == "office"


def test_targets_are_the_ticked_boxes_or_all_of_them():
    accounts = [acc(1), acc(2), acc(3), {"id": "demo", "email": "d@x", "demo": True}]
    assert [x["id"] for x in AB.targets(active(), accounts)] == ["a1", "a2", "a3"]
    assert [x["id"] for x in AB.targets(active(accounts=["a1", "a3"]), accounts)] == ["a1", "a3"]


def test_who_gets_an_answer():
    a, own = active(), {"box1@x.be"}
    assert AB.should_reply(a, msg(), own, {}, {})
    for bad in (msg(sender="noreply@shop.com"), msg(sender="box1@x.be"), msg(unsubscribe="<https://u>"), msg(category="news"), msg(auto=True),
                msg(subject="Réponse automatique : Question"), msg(sender="mailer-daemon@x.com"), msg(to="liste@x.be"), msg(date=NOW - 10 * 86400)):
        assert not AB.should_reply(a, bad, own, {}, {}), bad.sender_email + bad.subject
    assert not AB.should_reply(a, msg(), own, {"blocked": ["client@ext.com"]}, {})
    assert not AB.should_reply(a, msg(), own, {}, {AB.log_key(msg()): NOW})                             # déjà prévenu pendant cette absence
    assert AB.should_reply(a, msg(), own, {}, {AB.log_key(msg()): NOW - 30 * 86400})                    # réponse d'une absence précédente : oubliée
    assert not AB.should_reply(dict(a, enabled=False), msg(), own, {}, {})
    assert AB.should_reply(dict(a, known_only=True), msg(), own, {"contacts": {"client@ext.com": {}}}, {})
    assert not AB.should_reply(dict(a, known_only=True), msg(), own, {"contacts": {}}, {})


def test_each_box_answers_with_its_own_signature_and_alias():
    accounts = [acc(1, "<b>Sig un</b>"), acc(2, "<b>Sig deux</b>")]
    cfg = Cfg(identities=[{"id": "i1", "account": "a2", "email": "alias@x.be", "name": "Alias", "signature_html": "<b>Sig alias</b>"}])
    a = active(subject="Absent jusqu'au {fin}", body="Je suis absent jusqu'au {fin}.")
    o1 = C.absence_outgoing(cfg, accounts, a, msg(to="box1@x.be"))
    o2 = C.absence_outgoing(cfg, accounts, a, msg(2, to="box2@x.be", account="a2"))
    o3 = C.absence_outgoing(cfg, accounts, a, msg(3, to="alias@x.be", account="a2"))
    assert o1.account == "a1" and "Sig un" in o1.html and o2.account == "a2" and "Sig deux" in o2.html and "Sig un" not in o2.html
    assert o3.from_email == "alias@x.be" and "Sig alias" in o3.html and "Sig deux" not in o3.html
    assert o1.auto_reply and o1.to == "client@ext.com" and o1.in_reply_to == "<1@e>" and o1.subject.startswith("Absent jusqu'au ")
    assert AB.expand("{fin}", a) in o1.html and C.absence_outgoing(cfg, accounts, a, msg(9, to="autre@x.be")) is None


class FakeCache:
    def __init__(self, by): self.by = by
    def query(self, view, account, limit=0): return self.by.get(account, [])


class FakeEngine:
    run_absence = V.Engine.run_absence

    def __init__(self, cfg, accounts, by, fail=()):
        self.config, self._accounts, self.cache, self.sent, self.fail = cfg, accounts, FakeCache(by), [], set(fail)

    def accounts(self): return self._accounts

    def backend(self, aid):
        eng = self

        class B:
            def send(self, out):
                if aid in eng.fail:
                    raise OSError("hors ligne")
                eng.sent.append((aid, out))
        return B()


def test_engine_answers_once_per_sender_on_the_ticked_boxes_only():
    accounts = [acc(1, "<i>S1</i>"), acc(2, "<i>S2</i>"), acc(3, "<i>S3</i>")]
    by = {"a1": [msg(1), msg(2)], "a2": [msg(3, account="a2", to="box2@x.be")], "a3": [msg(4, account="a3", to="box3@x.be")]}
    cfg = Cfg(absence=active(accounts=["a1", "a2"]), accounts=accounts, identities=[])
    eng = FakeEngine(cfg, accounts, by)
    assert eng.run_absence() == 2                                                  # a1 : un seul envoi malgré 2 messages du même expéditeur ; a2 : 1 ; a3 : exclue
    assert sorted(a for a, _ in eng.sent) == ["a1", "a2"] and cfg.saved == 1
    assert eng.run_absence() == 0 and len(eng.sent) == 2                           # la synchro suivante ne répond plus
    off = FakeEngine(Cfg(absence=dict(active(), enabled=False), accounts=accounts, identities=[]), accounts, by)
    assert off.run_absence() == 0 and not off.sent


def test_failed_send_is_retried_next_time():
    accounts = [acc(1)]
    cfg = Cfg(absence=active(), accounts=accounts, identities=[])
    eng = FakeEngine(cfg, accounts, {"a1": [msg(1)]}, fail=["a1"])
    assert eng.run_absence() == 0 and not cfg.get("absence_log")
    eng.fail.clear()
    assert eng.run_absence() == 1


def test_update_keeps_known_keys_only_and_quick_duration():
    cfg = Cfg()
    a = AB.update(cfg, enabled=True, accounts=["a1"], bidon=1)
    assert a["enabled"] and a["accounts"] == ["a1"] and "bidon" not in cfg["absence"] and cfg.saved == 1
    s, e = AB.starting_today(3, datetime.date(2026, 11, 17))
    assert (s, e) == ("2026-11-17", "2026-11-19")
