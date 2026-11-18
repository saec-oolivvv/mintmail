"""Relevé du courrier : les boîtes sont relevées en parallèle (une boîte lente ne bloque pas les autres), l'affichage est prévenu dès qu'une boîte a du nouveau,
et chaque erreur dit quelle boîte est en cause."""
import os
import sys
import threading
import time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import testenv
from mintmail.models import Message
from mintmail.qt import viewmodel as V


class Cache:
    def __init__(self): self.got, self.lock = [], threading.Lock()
    def uids(self, aid, f): return {1: "old"}
    def upsert_many(self, msgs):
        with self.lock: self.got += [m.id for m in msgs]
    def delete_many(self, ids): pass


class Backend:
    def __init__(self, aid, delay=0.0, fail=False): self.aid, self.delay, self.fail = aid, delay, fail
    def sync(self, f, kn, limit=60):
        time.sleep(self.delay)
        if self.fail:
            raise OSError("délai dépassé")
        return [Message(id="%s-%s" % (self.aid, f), account=self.aid, folder=f, uid=2, unread=True)], {}, None, 0


class Eng:
    sync = V.Engine.sync

    def __init__(self, backends):
        self.b, self.cache, self.progress = backends, Cache(), []
        self.on_progress = lambda: self.progress.append(time.time())
    def accounts(self): return [{"id": k, "email": k + "@x.be"} for k in self.b]
    def backend(self, aid): return self.b[aid]
    def _apply_flags(self, kn, flags): pass
    def pending_ids(self): return set()


def test_a_slow_mailbox_does_not_delay_the_others_and_errors_name_the_mailbox():
    eng = Eng({"slow": Backend("slow", 0.6), "fast": Backend("fast"), "broken": Backend("broken", 0.0, True)})
    t0 = time.time()
    fresh, errors = eng.sync(folders=("inbox",))
    elapsed = time.time() - t0
    assert elapsed < 1.1                                                   # en série : 0,6 s + le reste ; ici ~0,6 s
    assert sorted(eng.cache.got) == ["fast-inbox", "slow-inbox"] and fresh == 2
    assert errors == ["broken@x.be : délai dépassé"]
    assert len(eng.progress) == 2                                          # l'interface est prévenue pour chaque boîte qui a du nouveau
    assert eng.progress[0] < t0 + 0.5                                      # … la rapide dès qu'elle a fini, sans attendre la lente


def test_only_restricts_the_mailboxes_and_nothing_to_do_is_fine():
    eng = Eng({"a": Backend("a"), "b": Backend("b")})
    assert eng.sync(folders=("inbox",), only=["b"])[0] == 1 and eng.cache.got == ["b-inbox"]
    assert Eng({}).sync() == (0, [])
