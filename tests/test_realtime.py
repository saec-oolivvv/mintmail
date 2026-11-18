"""Temps réel : actions rapprochées envoyées ensemble, messages en attente jamais ramenés par un relevé, veille légère des boîtes."""
import os
import sys
import threading
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import testenv
from mintmail.models import Message
from mintmail.offline import OfflineMixin
from mintmail.qt import viewmodel as V


class Cache:
    def __init__(self):
        self.ops, self.n, self.rows = [], 0, {}
        self.lock = threading.Lock()

    def ops_add(self, account, kind, payload):
        self.n += 1
        self.ops.append({"id": self.n, "account": account, "kind": kind, "payload": payload, "tries": 0})
        return self.n

    def ops_pending(self, limit=200): return list(self.ops)[:limit]
    def ops_done(self, i): self.ops = [o for o in self.ops if o["id"] != i]
    def ops_fail(self, i):
        for o in self.ops:
            if o["id"] == i: o["tries"] += 1


class Eng(OfflineMixin):
    run_ops = V.Engine.run_ops
    pending_ids = V.Engine.pending_ids

    def __init__(self, fail=None):
        self.cache, self.calls, self.fail = Cache(), [], fail

    def _op_exec(self, op):
        if self.fail:
            raise self.fail
        self.calls.append((op["account"], op["kind"], op["payload"].get("dest"), [i["uid"] for i in op["payload"]["items"]]))


def enqueue(e, aid, kind, uids, **extra):
    return e.cache.ops_add(aid, kind, dict(extra, items=[{"id": "%s-%d" % (aid, u), "uid": u, "real": "INBOX"} for u in uids]))


def test_21_deletions_in_a_row_go_to_the_server_as_one_command():
    e = Eng()
    ids = [enqueue(e, "a1", "move", [u], dest="trash") for u in range(1, 22)]
    done, errors, offline = e.run_ops(ids)
    assert e.calls == [("a1", "move", "trash", list(range(1, 22)))] and len(done) == 21 and not errors and not offline and not e.cache.ops
    assert e.run_ops(ids) == ([], [], False) and len(e.calls) == 1               # les autres appels trouvent tout déjà fait : rien n'est renvoyé


def test_only_neighbours_of_the_same_kind_are_merged_and_order_is_kept():
    e = Eng()
    enqueue(e, "a1", "move", [1], dest="trash")
    enqueue(e, "a1", "move", [2], dest="trash")
    enqueue(e, "a1", "move", [3], dest="archive")              # autre destination : commande à part
    enqueue(e, "a2", "move", [4], dest="archive")              # autre boîte : commande à part
    enqueue(e, "a1", "flags", [5], seen=True)
    e.run_ops([])
    assert [(c[0], c[1], c[2], c[3]) for c in e.calls] == [("a1", "move", "trash", [1, 2]), ("a1", "move", "archive", [3]), ("a2", "move", "archive", [4]), ("a1", "flags", None, [5])]


def test_offline_keeps_every_merged_action_for_later():
    e = Eng(fail=OSError("réseau coupé"))
    ids = [enqueue(e, "a1", "move", [u], dest="trash") for u in (1, 2, 3)]
    done, errors, offline = e.run_ops(ids)
    assert offline and not done and len(e.cache.ops) == 3 and all(o["tries"] == 1 for o in e.cache.ops)
    assert e.pending_ids() == {"a1-1", "a1-2", "a1-3"}


class Cache2:
    def __init__(self, known): self.known, self.up = known, []
    def uids(self, aid, f): return self.known
    def upsert_many(self, msgs): self.up += [m.id for m in msgs]
    def delete_many(self, ids): pass
    def ops_pending(self, limit=200): return [{"id": 1, "kind": "move", "payload": {"items": [{"id": "a1-9"}]}}]


class Be:
    def sync(self, f, kn, limit=60):
        return [Message(id="a1-9", account="a1", folder="inbox", uid=9), Message(id="a1-10", account="a1", folder="inbox", uid=10)], {}, None, 0


class SyncEng:
    sync = V.Engine.sync
    pending_ids = V.Engine.pending_ids
    def __init__(self): self.cache = Cache2({1: "x"})
    def accounts(self): return [{"id": "a1", "email": "a@x"}]
    def backend(self, aid): return Be()
    def _apply_flags(self, kn, flags): pass


def test_a_message_moved_here_but_not_yet_on_the_server_is_not_brought_back():
    e = SyncEng()
    e.sync(folders=("inbox",))
    assert e.cache.up == ["a1-10"]                              # a1-9 : déplacement en attente, il ne revient pas dans la boîte de réception


class LiveEng:
    live_check = V.Engine.live_check

    def __init__(self):
        self.sig = {"a1": {"INBOX": (5, 2, 10)}, "a2": {"INBOX": (1, 0, 3)}}
        self.bad = set()
    def accounts(self): return [{"id": "a1", "email": "a"}, {"id": "a2", "email": "b"}, {"id": "demo", "demo": True}]
    def folder_entries(self, aid): return [{"name": "INBOX", "special": "inbox"}, {"name": "Sent", "special": "sent", "selectable": True}]
    def backend(self, aid):
        eng = self
        class B:
            def folder_signature(self, names):
                if aid in eng.bad: raise OSError("coupé")
                return dict(eng.sig[aid], Sent=(0, 0, 1))
        return B()


def test_live_check_reports_only_mailboxes_that_changed():
    e = LiveEng()
    assert e.live_check() == []                                  # premier passage : on mémorise
    assert e.live_check() == []
    e.sig["a1"] = {"INBOX": (4, 2, 10)}                          # un message supprimé ailleurs
    assert e.live_check() == ["a1"] and e.live_check() == []
    e.bad.add("a2")
    e.sig["a2"] = {"INBOX": (9, 9, 9)}
    assert e.live_check() == []                                  # boîte injoignable : pas de fausse alerte
    e.bad.clear()
    assert e.live_check() == ["a2"]


def test_a_mailbox_that_is_offline_does_not_hold_back_the_others():
    e = Eng()
    orig = e._op_exec
    def exec_(op):
        if op["account"] == "off":
            raise OSError("réseau coupé")
        orig(op)
    e._op_exec = exec_
    enqueue(e, "off", "move", [1], dest="trash")
    enqueue(e, "ok", "move", [2], dest="trash")
    enqueue(e, "off", "move", [3], dest="archive")
    done, errors, offline = e.run_ops([])
    assert offline and e.calls == [("ok", "move", "trash", [2])] and [o["account"] for o in e.cache.ops] == ["off", "off"]
