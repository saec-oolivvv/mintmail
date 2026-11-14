"""Interface Qt, partie sans Qt : lignes de liste, HTML du lecteur (assaini, CSP), ouverture d'un message (marqué lu ici et sur le serveur,
action rejouée), synchronisation (nouveaux messages, drapeaux, suppressions) — le tout sur le moteur seul, donc sur les trois systèmes."""
import os, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mintmail.models import Message
from mintmail.store import Cache
from mintmail.qt import viewmodel as V

A = {"id": "a1", "email": "a@x.be", "name": "A"}


class FakeBackend:
    demo = False

    def __init__(self):
        self.calls, self.result, self.fail, self.tree = [], ([], {}, None, 0), None, []

    def sync(self, logical, known, limit=60, on_batch=None, unseen=False):
        if self.fail:
            raise RuntimeError(self.fail)
        return self.result if logical == "inbox" else ([], {}, None, 0)

    def set_flags_many(self, items, seen=None, flagged=None, **kw):
        self.calls.append(("flags", [i.uid for i in items], seen) if not kw and flagged is None else ("flags", [i.uid for i in items], seen, flagged, kw))

    def move_many(self, items, dest, notjunk=False):
        self.calls.append(("move", [i.uid for i in items], dest, notjunk))

    def delete_many(self, items):
        self.calls.append(("delete", [i.uid for i in items]))

    def list_folders(self):
        return self.tree


def _eng():
    cache = Cache(os.path.join(tempfile.mkdtemp(), "c.db"))
    eng = V.Engine({"accounts": [A]}, cache)
    be = FakeBackend()
    eng._backends["a1"] = be
    return eng, cache, be


def _m(i, **kw):
    d = dict(id="m%d" % i, account="a1", folder="inbox", real_folder="INBOX", uid=i, sender_name="S%d" % i, sender_email="s%d@x.be" % i,
             subject="Sujet %d" % i, date=time.time() - i, snippet="extrait", text="corps", html="<p>corps</p>", unread=True)
    d.update(kw)
    return Message(**d)


def test_rows_and_views_cover_the_gtk_folders():
    keys = [k for k, _ in V.VIEWS]
    assert keys[:2] == ["inbox", "unread"] and {"starred", "pinned", "snoozed", "drafts", "sent", "archive", "spam", "trash"} <= set(keys)
    r = V.row_info(_m(1, pinned=True))
    assert r["sender"] == "S1" and r["unread"] and r["pinned"] and not r["attachments"] and r["time"]


def test_reader_html_is_sanitised_and_locked_down():
    h = V.render_html(_m(1, html='<p onclick="x()">salut</p><script>alert(1)</script><img src="http://t.example/p.png">'))
    assert "<script" not in h and "onclick" not in h and "Content-Security-Policy" in h
    assert "http:" not in h.split("img-src", 1)[1].split(";")[0]               # images distantes bloquées par la CSP par défaut
    assert "default-src 'none'" in h and "img-src data: cid:;" in h
    allowed = V.render_html(_m(1, html='<img src="http://t.example/p.png">'), load_images=True)
    assert "http:" in allowed.split("img-src", 1)[1].split(";")[0]
    plain = V.render_html(_m(2, html="", text="a <b> & c\nligne"), dark=True)
    assert "&lt;b&gt;" in plain and "#1f2229" in plain and "<script" not in plain


def test_opening_marks_read_locally_and_queues_the_server_action():
    eng, cache, be = _eng()
    cache.upsert_many([_m(5)])
    m = eng.open_message("m5")
    assert m.text == "corps" and not m.unread and not cache.get("m5").unread
    assert cache.ops_count() == 1
    done, errors, offline = eng.flush()
    assert len(done) == 1 and not errors and not offline and be.calls == [("flags", [5], True)] and cache.ops_count() == 0
    eng.open_message("m5")                                                    # déjà lu : rien de plus à envoyer
    assert cache.ops_count() == 0
    eng.set_unread("m5", True)
    assert cache.get("m5").unread and cache.ops_count() == 1


def test_sync_adds_new_messages_applies_flags_and_removals():
    eng, cache, be = _eng()
    cache.upsert_many([_m(1), _m(2, unread=False), _m(3)])
    be.result = ([_m(4)], {1: (False, True), 2: (True, False)}, {1, 2, 4}, 1)
    fresh, errors = eng.sync()
    assert not errors and fresh == 1
    assert cache.get("m4") is not None
    assert not cache.get("m1").unread and cache.get("m1").starred and cache.get("m2").unread
    assert cache.get("m3") is None                                            # disparu du serveur
    counts = V.counts(cache)
    assert counts["inbox"] == 2 and counts["unread"] == 2


def test_local_pending_action_wins_over_the_server_state_and_errors_are_reported():
    eng, cache, be = _eng()
    cache.upsert_many([_m(1)])
    eng.open_message("m1")                                                    # lu ici, action pas encore partie
    be.result = ([], {1: (True, False)}, {1}, 1)                              # le serveur dit encore « non lu »
    eng.sync()
    assert not cache.get("m1").unread
    be.fail = "réseau coupé"
    fresh, errors = eng.sync()
    assert fresh == 0 and errors and "réseau coupé" in errors[0]


def test_demo_account_is_used_without_configuration():
    assert V.accounts_of({"accounts": []})[0]["demo"] is True
    assert V.accounts_of({"accounts": [A]}) == [A]


def test_move_updates_the_cache_first_then_the_server_and_resyncs_the_destination():
    eng, cache, be = _eng()
    cache.upsert_many([_m(1), _m(2)])
    msgs = [cache.get_light("m1"), cache.get_light("m2")]
    ids = eng.move(msgs, "archive")
    assert cache.get("m1").folder == "archive" and cache.ops_count() == 2 - 1          # une action pour le compte
    be.result = ([_m(11, folder="archive", real_folder="Archive")], {}, {11}, 1)
    errors, offline = eng.finish_move(msgs, "archive", ids)
    assert not errors and not offline and be.calls[0] == ("move", [1, 2], "archive", False) and cache.ops_count() == 0
    assert cache.get("m1") is None                                                    # copie locale remplacée par celle du serveur
    eng2, cache2, be2 = _eng()
    cache2.upsert_many([_m(3, folder="spam", real_folder="Spam")])
    m3 = [cache2.get_light("m3")]
    eng2.finish_move(m3, "inbox", eng2.move(m3, "inbox"))
    assert be2.calls[0] == ("move", [3], "inbox", True)                              # « Ce n'est pas du spam » apprend au serveur


def test_move_offline_keeps_the_action_and_delete_forever_removes_locally():
    eng, cache, be = _eng()
    cache.upsert_many([_m(1), _m(2)])
    def boom(items, dest, notjunk=False):
        raise ConnectionResetError("réseau")
    be.move_many = boom
    m1 = [cache.get_light("m1")]
    ids = eng.move(m1, "trash")
    errors, offline = eng.finish_move(m1, "trash", ids)
    assert offline and cache.ops_count() == 1 and cache.get("m1").folder == "trash"  # conservé, rejoué au retour du réseau
    m2 = [cache.get_light("m2")]
    ids = eng.delete_forever(m2)
    assert cache.get("m2") is None
    eng.run_ops(ids)
    assert ("delete", [2]) in be.calls


def test_flags_star_unread_pin_are_local_first_and_sent_to_the_server():
    eng, cache, be = _eng()
    cache.upsert_many([_m(1, unread=False)])
    m = [cache.get_light("m1")]
    for field, value in (("starred", True), ("unread", True), ("pinned", True)):
        eng.run_ops(eng.set_flag(m, field, value))
    c = cache.get("m1")
    assert c.starred and c.unread and c.pinned
    assert be.calls[0][3] is True and be.calls[1][2] is False and be.calls[2][4] == {"pinned": True}


def test_folder_tree_lists_custom_folders_and_move_targets():
    cfg = {"accounts": [A], "folders": {"a1": [
        {"name": "INBOX", "label": "Boîte", "special": "inbox", "selectable": True, "depth": 0},
        {"name": "LTD", "label": "LTD", "special": "", "selectable": True, "depth": 0},
        {"name": "LTD/Sub", "label": "Sub", "special": "", "selectable": True, "depth": 1},
        {"name": "[Gmail]", "label": "[Gmail]", "special": "", "selectable": False, "depth": 0}]}}
    eng = V.Engine(cfg, Cache(os.path.join(tempfile.mkdtemp(), "c.db")))
    nav = eng.nav_folders()
    assert [(d, l, depth) for d, l, depth, _a in nav] == [("f:LTD", "LTD", 0), ("f:LTD/Sub", "Sub", 1)]
    assert ("f:LTD", "LTD") in eng.move_targets("a1") and ("inbox", "Boîte") in eng.move_targets("a1")
    eng2, _c, be = _eng()
    be.tree = [{"name": "INBOX", "label": "I", "special": "inbox", "selectable": True, "depth": 0}, {"name": "Z", "label": "Z", "special": "", "selectable": True, "depth": 0}]
    class Cfg(dict):
        def save(self): self.saved = True
    eng2.config = Cfg({"accounts": [A]})
    assert eng2.refresh_folders() is True and eng2.config["folders"]["a1"] == be.tree and eng2.refresh_folders() is False
