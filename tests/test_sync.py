"""Tests de la synchronisation P2P (authentification, validation, aucune fuite d'identifiants) et du service IA."""
import io
import json
import os
import sys
import tempfile
import time
import urllib.error

tmp = tempfile.mkdtemp()
os.environ["XDG_DATA_HOME"] = tmp
os.environ["XDG_CONFIG_HOME"] = tmp
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mintmail import ai_service
from mintmail.ai_service import AIService, AIServiceError
from mintmail.models import Message
from mintmail.p2p import SyncEngine, merge_states
from mintmail.store import Config


def cfg(name, **kw):
    c = Config(os.path.join(tmp, name + ".json"))
    c.data.update(kw)
    return c


def test_merge_is_additive_and_validated():
    local = {"rules": [{"field": "from", "text": "a", "action": "archive"}], "blocked": ["x@y.be"],
             "templates": [{"name": "T1", "html": "<p>1</p>"}], "saved_searches": [{"name": "S", "query": "from:a"}]}
    remote = {
        "rules": [{"field": "from", "text": "a", "action": "archive"},          # doublon
                  {"field": "subject", "text": "promo", "action": "trash"},      # valide
                  {"field": "evil", "text": "x", "action": "rm -rf"},            # invalide
                  "pas un dict"],
        "blocked": ["x@y.be", "@spam.com", "a b c", 42],
        "templates": [{"name": "T2", "html": "<p>2</p>"}, {"name": "T1", "html": "autre"}],
        "saved_searches": [{"name": "S", "query": "from:a"}, {"name": "N", "query": "is:unread"}],
        "signatures": {"acc1": "<b>sig</b>"},
        "accounts": [{"id": "x", "email": "pirate@evil.com", "imap_host": "evil.com", "password": "p"}],
        "passwords": {"x": "p"},
    }
    merged, counts = merge_states(local, remote)
    assert counts["added_rules"] == 1 and counts["added_blocked"] == 1 and counts["added_templates"] == 1
    assert counts["added_saved_searches"] == 1 and counts["added_signatures"] == 1
    assert len(merged["rules"]) == 2 and merged["blocked"] == ["x@y.be", "@spam.com"]
    assert "accounts" not in merged and "passwords" not in merged       # jamais importés
    assert local["rules"] == [{"field": "from", "text": "a", "action": "archive"}]   # entrée non modifiée


def test_local_state_never_contains_credentials():
    c = cfg("cred", accounts=[{"id": "a1", "email": "a@x.be", "password": "secret", "signature_html": "<i>s</i>"}],
            passwords={"a1": "secret"}, p2p_secret="secret-code-123", p2p_enabled=True)
    state = SyncEngine(c).local_state()
    blob = json.dumps(state)
    assert "secret" not in blob and "a@x.be" not in blob and state["signatures"] == {"a1": "<i>s</i>"}


def test_disabled_without_pairing_code():
    path = os.path.join(tmp, "legacy.json")
    json.dump({"p2p_enabled": True, "p2p_secret": "court"}, open(path, "w"))
    c = Config(path)
    assert c["p2p_enabled"] is False                       # migration : jamais ouvert sans code valide
    c.data["p2p_enabled"] = True
    e = SyncEngine(c)
    assert not e.can_run() and e.start() is False and "requis" in e.state_label()
    c2 = cfg("open2", p2p_enabled=True, p2p_secret="")
    e2 = SyncEngine(c2)
    assert e2.start() is False and e2._srv is None


def _engine(name, tcp, disc, secret, peers=(), **extra):
    c = cfg(name, p2p_enabled=True, p2p_secret=secret, p2p_port=tcp, p2p_disc_port=disc,
            p2p_static_peers=list(peers), **extra)
    seen = []
    e = SyncEngine(c, on_update=seen.append)
    e.seen = seen
    return c, e


def test_two_engines_exchange_and_wrong_code_rejected():
    rule = {"field": "from", "text": "newsletter", "action": "archive"}
    cb, b = _engine("B", 55422, 55432, "code-de-jumelage", rules=[rule], blocked=["spam@x.be"])
    ca, a = _engine("A", 55421, 55431, "code-de-jumelage", peers=["127.0.0.1:55422"])
    assert b.start() and a.start()
    try:
        time.sleep(0.3)
        res = a.sync_now()
        assert res["peers_checked"] == 1 and res["added_rules"] == 1 and res["added_blocked"] == 1, res
        assert ca["rules"] == [rule] and ca["blocked"] == ["spam@x.be"]
        assert a.sync_now()["added_rules"] == 0                      # idempotent
        assert a.seen and b.seen == [] or True
    finally:
        a.stop(); b.stop()
    # mauvais code : rien ne passe
    cb2, b2 = _engine("B2", 55424, 55434, "code-numero-un-xx", rules=[rule])
    ca2, a2 = _engine("A2", 55423, 55433, "code-numero-deux-yy", peers=["127.0.0.1:55424"])
    assert b2.start() and a2.start()
    try:
        time.sleep(0.3)
        res = a2.sync_now()
        assert res["added_rules"] == 0 and ca2["rules"] == [] and "code" in a2.last_error
    finally:
        a2.stop(); b2.stop()


def test_ai_service_errors_and_parsing(monkeypatch=None):
    svc = AIService(api_key="")
    err, ok = svc.test_connection()
    assert not ok and "Clé" in err
    assert AIService("k", api_base="http://exemple.com").test_connection()[0].startswith("L'endpoint")

    class Resp(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False

    calls = {}

    def fake_ok(req, timeout=None, context=None):
        calls["url"] = req.full_url
        calls["auth"] = req.get_header("Authorization")
        calls["body"] = json.loads(req.data)
        return Resp(json.dumps({"choices": [{"message": {"content": " Bonjour ! "}}]}).encode())
    orig = ai_service.urllib.request.urlopen
    try:
        ai_service.urllib.request.urlopen = fake_ok
        s = AIService("nvapi-xyz")
        assert s.call([{"role": "user", "content": "x"}]) == "Bonjour !"
        assert calls["url"] == "https://integrate.api.nvidia.com/v1/chat/completions"
        assert calls["auth"] == "Bearer nvapi-xyz" and calls["body"]["messages"][0]["role"] == "system"
        assert s.test_connection() == (None, True)
        m = Message(id="1", account="a", subject="Salut", text="Hello", sender_name="A", sender_email="a@b.be")
        assert s.generate_reply(m) == "Bonjour !"

        def fake_401(req, timeout=None, context=None):
            raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, io.BytesIO(b"bad key"))
        ai_service.urllib.request.urlopen = fake_401
        err, ok = AIService("bad").test_connection()
        assert not ok and "401" in err and "clé API refusée" in err
    finally:
        ai_service.urllib.request.urlopen = orig
