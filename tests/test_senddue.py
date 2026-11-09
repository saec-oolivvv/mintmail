"""Envoi différé sans interface (--send-due) : un seul envoi, réessais réseau, abandon propre, compte supprimé."""
import os, subprocess, sys, tempfile, time
tmp = tempfile.mkdtemp()
os.environ["XDG_DATA_HOME"] = tmp
os.environ["XDG_CONFIG_HOME"] = tmp
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mintmail import backend as B, entry, store
from mintmail.models import Outgoing
from mintmail.store import Cache, Config

ACC = {"id": "acc12345", "name": "Moi", "email": "moi@x.be", "imap_host": "i.x.be", "imap_port": 993, "smtp_host": "s.x.be", "smtp_port": 587}


class FakeBE:
    sent, fail = [], None

    def send(self, out):
        if FakeBE.fail:
            raise FakeBE.fail
        FakeBE.sent.append(out.subject)


def run(cfg, cache):
    orig = (store.Cache, store.Config, B.make_backend, subprocess.run)
    notes = []
    store.Cache, store.Config, B.make_backend = (lambda *a, **k: cache), (lambda *a, **k: cfg), (lambda acc, c: FakeBE())
    subprocess.run = lambda cmd, **k: notes.append(cmd)
    try:
        return entry.send_due(), notes
    finally:
        store.Cache, store.Config, B.make_backend, subprocess.run = orig


def setup(name):
    cfg = Config(os.path.join(tmp, name + ".json"))
    cfg["accounts"] = [ACC]
    cache = Cache(os.path.join(tmp, name + ".db"))
    FakeBE.sent, FakeBE.fail = [], None
    return cfg, cache


def test_due_messages_are_sent_once_and_future_ones_wait():
    cfg, cache = setup("s1")
    cache.outbox_add("a", time.time() - 5, Outgoing(account="acc12345", to="p@y.be", subject="Dû", html="x"))
    cache.outbox_add("b", time.time() + 3600, Outgoing(account="acc12345", to="p@y.be", subject="Plus tard", html="x"))
    assert run(cfg, cache)[0] == 0
    assert FakeBE.sent == ["Dû"] and cache.outbox_count() == 1                          # « Plus tard » reste programmé
    run(cfg, cache)
    assert FakeBE.sent == ["Dû"]                                                        # jamais deux fois
    cache.outbox_add("c", time.time() - 1, Outgoing(account="acc12345", to="p@y.be", subject="Réservé", html="x"))
    assert cache.outbox_claim("c")                                                      # la fenêtre MintMail l'a déjà pris
    run(cfg, cache)
    assert "Réservé" not in FakeBE.sent and cache.outbox_count() == 2


def test_network_errors_are_retried_and_refusals_are_dropped_with_a_notification():
    cfg, cache = setup("s2")
    cache.outbox_add("a", time.time() - 5, Outgoing(account="acc12345", to="p@y.be", subject="Réseau", html="x"))
    FakeBE.fail = B.BackendError("Envoi impossible : réseau", retryable=True)
    run(cfg, cache)
    assert cache.outbox_count() == 1 and cache.outbox_tries("a") == 1 and cache.outbox_due() == []     # nouvel essai dans 2 min
    cache.outbox_reschedule("a", time.time() - 1)
    FakeBE.fail = B.BackendError("Envoi impossible : adresse refusée")
    code, notes = run(cfg, cache)
    assert cache.outbox_count() == 0 and any(n[0] == "notify-send" for n in notes)                    # l'utilisateur est prévenu
    cache.outbox_add("z", time.time() - 1, Outgoing(account="supprime", to="p@y.be", subject="Orphelin", html="x"))
    FakeBE.fail = None
    run(cfg, cache)
    assert cache.outbox_count() == 0 and FakeBE.sent == []                               # compte supprimé : rien n'est envoyé


def test_cli_option_exists_and_runs_without_gui():
    r = subprocess.run([sys.executable, "-m", "mintmail", "--send-due"], capture_output=True, text=True, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       env=dict(os.environ, HOME=tmp, XDG_DATA_HOME=tmp + "/d", XDG_CONFIG_HOME=tmp + "/c", PYTHONPATH=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), timeout=60)
    assert r.returncode == 0 and "Traceback" not in r.stderr                              # rien à envoyer : sortie silencieuse et rapide
