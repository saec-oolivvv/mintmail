"""Synchronisation entre machines : détection des modifications / suppressions, fusion, canal chiffré, échange automatique."""
import io
import json
import os
import socket
import sys
import tempfile
import time
import urllib.error

tmp = tempfile.mkdtemp()
os.environ["XDG_DATA_HOME"] = tmp
os.environ["XDG_CONFIG_HOME"] = tmp
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mintmail import ai_service, syncdata
from mintmail.ai_service import AIService, AIServiceError
from mintmail.models import Message
from mintmail.p2p import SecureChannel, SyncEngine, derive_key
from mintmail.store import Config

CODE = "code-de-jumelage-solide"
ACC = {"id": "acc1234", "name": "Pro", "email": "moi@exemple.be", "username": "moi", "imap_host": "imap.exemple.be",
       "imap_port": 993, "imap_ssl": True, "smtp_host": "smtp.exemple.be", "smtp_port": 587,
       "signature_html": "<b>Moi</b>", "has_password": True}


def cfg(name, **kw):
    c = Config(os.path.join(tmp, name + ".json"))
    c.data.update(kw)
    return c


def full_config(name):
    c = cfg(name, accounts=[dict(ACC)], rules=[{"field": "from", "text": "promo", "action": "archive"}],
            templates=[{"name": "Merci", "html": "<p>Merci !</p>"}], blocked=["spam@x.be"], theme="light",
            ai_enabled=True, ai_model="mon-modele", ai_has_key=True,
            saved_searches=[{"name": "Marie", "query": "from:marie"}])
    c.set_password("acc1234", "s3cret-pass")
    c.set_password("ai:nvidia", "nvapi-secret-key")
    return c


def test_changes_and_deletions_are_detected():
    c = full_config("det")
    t0 = time.time()
    items = syncdata.local_items(c, now=t0)
    assert items["acct:acc1234"]["ts"] == t0 and items["acct:acc1234"]["secret"] == "s3cret-pass"
    assert items["set:style"]["ts"] == 0.0 and items["set:theme"]["ts"] == t0     # défaut jamais modifié : date 0
    assert syncdata.local_items(c, now=t0 + 5)["acct:acc1234"]["ts"] == t0         # rien n'a changé : date conservée
    c["theme"] = "dark"
    c["accounts"][0]["signature_html"] = "<i>Nouvelle</i>"
    items = syncdata.local_items(c, now=t0 + 10)
    assert items["set:theme"]["ts"] == t0 + 10 and items["acct:acc1234"]["ts"] == t0 + 10
    c["accounts"] = []
    c["blocked"] = []
    items = syncdata.local_items(c, now=t0 + 20)
    assert items["acct:acc1234"]["del"] and items["acct:acc1234"]["ts"] == t0 + 20 and items["blocked:spam@x.be"]["del"]
    assert Config(c.path)["sync_meta"]["acct:acc1234"]["del"] is True                 # persisté


def test_merge_last_write_wins_and_validation():
    local = {"set:theme": {"v": "dark", "ts": 100.0, "del": False}, "set:style": {"v": "aurora", "ts": 0.0, "del": False},
             "acct:acc1234": {"v": dict(ACC), "secret": "x", "ts": 100.0, "del": False}}
    remote = {"set:theme": {"v": "light", "ts": 50.0, "del": False},               # plus ancien : ignoré
              "set:style": {"v": "papier", "ts": 5.0, "del": False},              # plus récent que le défaut : gagne
              "acct:acc1234": {"v": None, "ts": 200.0, "del": True},               # suppression plus récente : gagne
              "set:density": {"v": "hostile", "ts": 999.0, "del": False},          # valeur invalide
              "set:window": {"v": 1, "ts": 999.0, "del": False},                   # réglage non synchronisable
              "acct:zzzz9999": {"v": dict(ACC, imap_host="a b;rm"), "ts": 9.0, "del": False},   # compte invalide
              "acct:other123": {"v": dict(ACC, id="mismatch1"), "ts": 9.0, "del": False},       # id incohérent
              "evil:x": {"v": 1, "ts": 9.0, "del": False}, "rule:abc": {"v": {"field": "from", "text": "x", "action": "rm"}, "ts": 9.0, "del": False}}
    wins = syncdata.merge_items(local, remote)
    assert set(wins) == {"set:style", "acct:acc1234"}, set(wins)


def test_full_roundtrip_between_two_machines_incl_secrets_and_deletion():
    a, b = full_config("A"), cfg("B")
    wins = syncdata.merge_items(syncdata.local_items(b), syncdata.to_wire(syncdata.local_items(a)))
    res = syncdata.apply_items(b, wins)
    assert res["accounts"] and res["settings"] and res["lists"] and res["ai"] and res["new_accounts"] == ["Pro"]
    acc = b["accounts"][0]
    assert acc["email"] == "moi@exemple.be" and acc["signature_html"] == "<b>Moi</b>" and "password" not in acc
    assert b.password("acc1234") == "s3cret-pass" and b.password("ai:nvidia") == "nvapi-secret-key"
    assert b["theme"] == "light" and b["ai_model"] == "mon-modele" and b["ai_has_key"] is True
    assert b["templates"][-1] == {"name": "Merci", "html": "<p>Merci !</p>"} and "spam@x.be" in b["blocked"]
    assert b["rules"] == a["rules"] and {"name": "Marie", "query": "from:marie"} in b["saved_searches"]
    assert not syncdata.merge_items(syncdata.local_items(b), syncdata.to_wire(syncdata.local_items(a)))   # stable : rien à refaire
    # B supprime le compte et modifie la signature ailleurs ; A doit suivre
    b["accounts"] = []
    time.sleep(0.01)
    wins = syncdata.merge_items(syncdata.local_items(a), syncdata.to_wire(syncdata.local_items(b)))
    assert "acct:acc1234" in wins and wins["acct:acc1234"]["del"]
    syncdata.apply_items(a, wins)
    assert a["accounts"] == [] and a.password("acc1234") == ""


def test_secure_channel_encrypts_authenticates_and_orders():
    class Pipe:
        def __init__(self): self.buf = bytearray()
        def write(self, b): self.buf += b
        def flush(self): pass
        def read(self, n):
            out, self.buf = bytes(self.buf[:n]), self.buf[n:]
            return out
    key = derive_key(CODE)
    p = Pipe()
    tx = SecureChannel(p, key, b"n" * 32, b"s" * 32, initiator=True)
    rx = SecureChannel(p, key, b"n" * 32, b"s" * 32, initiator=False)
    tx.send({"mot": "s3cret-pass", "n": 1})
    wire = bytes(p.buf)
    assert b"s3cret" not in wire and b"mot" not in wire                                # chiffré
    assert rx.recv() == {"mot": "s3cret-pass", "n": 1}
    tx.send({"n": 2}); frame = bytes(p.buf)
    tampered = bytearray(frame); tampered[6] ^= 1
    p.buf = tampered
    try:
        rx.recv(); raise SystemExit("trame altérée acceptée")
    except ValueError:
        pass
    rx.recv_seq = 1
    p.buf = bytearray(frame)
    assert rx.recv() == {"n": 2}
    p.buf = bytearray(frame)                                                           # rejeu de la même trame
    try:
        rx.recv(); raise SystemExit("rejeu accepté")
    except ValueError:
        pass
    other = SecureChannel(Pipe(), derive_key("un-autre-code-complet"), b"n" * 32, b"s" * 32, initiator=False)
    other.f.buf = bytearray(frame)
    try:
        other.recv(); raise SystemExit("mauvaise clé acceptée")
    except ValueError:
        pass


def _engine(name, tcp, disc, secret, peers=(), **extra):
    c = full_config(name) if extra.pop("full", False) else cfg(name)
    c.data.update(p2p_enabled=True, p2p_secret=secret, p2p_port=tcp, p2p_disc_port=disc, p2p_static_peers=list(peers), **extra)
    return c, SyncEngine(c)


def wait_for(cond, timeout=12.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.15)
    return False


def test_two_engines_sync_automatically_and_encrypted():
    sent = []
    orig = socket.socket.send
    socket.socket.send = lambda self, data, *a: (sent.append(bytes(data)), orig(self, data, *a))[1]
    ca, a = _engine("EA", 55501, 55511, CODE, peers=["127.0.0.1:55502"], full=True)
    cb, b = _engine("EB", 55502, 55512, CODE, peers=["127.0.0.1:55501"])
    try:
        assert b.start() and a.start()
        # 1) AUCUN clic : le compte, sa signature, le mot de passe, la clé IA, les modèles arrivent seuls
        assert wait_for(lambda: cb["accounts"] and cb.password("acc1234") == "s3cret-pass"), "compte non synchronisé"
        assert cb["accounts"][0]["signature_html"] == "<b>Moi</b>" and cb.password("ai:nvidia") == "nvapi-secret-key"
        assert cb["templates"][-1]["name"] == "Merci" and cb["ai_model"] == "mon-modele" and cb["theme"] == "light"
        # 2) rien d'intelligible sur le réseau
        blob = b"".join(sent)
        for secret in (b"s3cret-pass", b"nvapi-secret", b"imap.exemple.be", b"moi@exemple.be", b"Merci"):
            assert secret not in blob, secret
        # 3) une modification ultérieure se propage seule, dans les deux sens
        ca["rules"].append({"field": "subject", "text": "facture", "action": "star"})
        assert wait_for(lambda: {"field": "subject", "text": "facture", "action": "star"} in cb["rules"]), "règle non propagée"
        cb["accounts"][0]["signature_html"] = "<i>Signature B</i>"
        assert wait_for(lambda: ca["accounts"][0]["signature_html"] == "<i>Signature B</i>"), "signature non propagée"
        # 4) une suppression se propage aussi
        cb["accounts"] = []
        assert wait_for(lambda: ca["accounts"] == []), "suppression non propagée"
    finally:
        socket.socket.send = orig
        a.stop(); b.stop()


def test_wrong_code_and_short_code_are_refused():
    ca, a = _engine("WA", 55503, 55513, "un-code-tres-different-1", peers=["127.0.0.1:55504"], full=True)
    cb, b = _engine("WB", 55504, 55514, "un-code-tres-different-2")
    try:
        assert b.start() and a.start()
        res = a.sync_now()
        assert wait_for(lambda: "code" in a.last_error), "message d'erreur attendu ; obtenu : %r (résultat %r)" % (a.last_error, res)   # une synchro de fond peut chevaucher
        assert res["failed"] == 1 and res["applied"] == 0 and cb["accounts"] == [], res
    finally:
        a.stop(); b.stop()
    path = os.path.join(tmp, "short.json")
    json.dump({"p2p_enabled": True, "p2p_secret": "court-1234", "design_v2": True}, open(path, "w"))
    c = Config(path)
    assert c["p2p_enabled"] is False and SyncEngine(c).start() is False             # < 12 caractères : jamais actif


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
