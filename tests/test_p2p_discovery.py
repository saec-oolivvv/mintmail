"""Découverte entre machines : annonces, réponse directe, versions, identifiants en double, VPN, recherche active, diagnostic."""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_sync as ts
from mintmail import netutil, p2p
from mintmail.p2p import SyncEngine
from mintmail.store import Config


class FakeUDP:
    def __init__(self): self.sent = []
    def sendto(self, data, addr): self.sent.append((data, addr))
    def close(self): pass


def engine(name, tcp=55700, disc=55701, **extra):
    c = ts.cfg(name, p2p_enabled=True, p2p_secret=ts.CODE, p2p_port=tcp, p2p_disc_port=disc, **extra)
    e = SyncEngine(c)
    e._udp = FakeUDP()
    e.synced = []
    e._auto_sync = lambda: e.synced.append(1)
    e._own = {"192.168.1.10", "127.0.0.1"}
    return c, e


def ann(version, node, port, inst=None):
    return ("MINTMAIL/%s %s %s%s" % (version, node, port, (" " + inst) if inst else "")).encode()


def test_announce_handling_all_cases():
    c, e = engine("d1")
    me = e._announce_bytes()
    assert e._handle_announce(me, ("192.168.1.99", 54321)) is None                        # notre propre annonce
    other = ann(3, "AAAA1111", 54322, "deadbeef")
    key = e._handle_announce(other, ("192.168.1.20", 54321))
    assert key == "192.168.1.20:54322" and e.peers()[0]["node_id"] == "AAAA1111"
    assert e._udp.sent and e._udp.sent[-1][1] == ("192.168.1.20", e._disc_port)          # réponse directe au nouveau pair
    n = len(e._udp.sent)
    e._handle_announce(other, ("192.168.1.20", 54321))
    assert len(e._udp.sent) == n and len(e.peers()) == 1                                  # une seule réponse (pas de boucle)
    # deux machines avec le MÊME identifiant (config copiée) : l'autre est quand même vue
    key2 = e._handle_announce(ann(3, e.node_id(), 54322, "cafebabe"), ("192.168.1.21", 54321))
    assert key2 == "192.168.1.21:54322" and len(e.peers()) == 2
    # annonce d'une ancienne version du programme (sans jeton d'instance) depuis notre propre adresse : ignorée
    assert e._handle_announce(ann(3, e.node_id(), 54322), ("192.168.1.10", 54321)) is None
    assert e._handle_announce(ann(3, "BBBB2222", 54322), ("192.168.1.30", 54321)) == "192.168.1.30:54322"
    # autre version du protocole : comptée, jamais ajoutée, signalée dans le diagnostic
    assert e._handle_announce(ann(2, "OLD00001", 54322), ("192.168.1.40", 54321)) is None
    assert e.diagnostics()["foreign_versions"] == ["2"]
    # VPN / Tailscale (100.64/10) : accepté ; adresse publique : refusée
    assert e._handle_announce(ann(3, "VPN00001", 54322, "11111111"), ("100.101.102.103", 54321)) == "100.101.102.103:54322"
    assert e._handle_announce(ann(3, "WEB00001", 54322, "22222222"), ("8.8.8.8", 54321)) is None
    assert e.diagnostics()["filtered"] == ["8.8.8.8"] and e.diagnostics()["received"] >= 8
    assert e.synced                                                                        # un échange est déclenché à chaque nouveau pair


def test_active_scan_finds_only_machines_with_the_same_code():
    cb, b = ts._engine("SB", 55711, 55721, ts.CODE)
    ca = ts.full_config("SA")
    ca.data.update(p2p_enabled=True, p2p_secret=ts.CODE, p2p_port=55711, p2p_disc_port=55722)
    a = SyncEngine(ca)
    orig = netutil.scan_candidates
    netutil.scan_candidates = lambda limit=1024: ["127.0.0.1"]
    try:
        assert b.start()
        time.sleep(0.3)
        assert a.scan_now() == 1                                                          # B trouvée sans diffusion ni IP saisie
        assert a.peers()[0]["via"] == "recherche" and a.peers()[0]["port"] == "55711"
        for _ in range(60):                                                              # l'application côté B se fait dans son propre fil : on lui laisse un instant
            if cb["accounts"]:
                break
            time.sleep(0.05)
        assert cb["accounts"] and cb.password("acc1234") == "s3cret-pass"                  # et la synchro a eu lieu
        # mauvais code : la machine répond sur le port mais n'est pas retenue
        a2 = SyncEngine(ts.cfg("SA2", p2p_enabled=True, p2p_secret="un-tout-autre-code-12", p2p_port=55711))
        assert a2.scan_now() == 0 and a2.peers() == []
    finally:
        netutil.scan_candidates = orig
        b.stop()


def test_diagnostics_and_state_label_explain_the_situation():
    c, e = engine("d3")
    e._started_at = time.time() - 120
    assert "aucune machine vue" in e.state_label()
    d = e.diagnostics()
    assert d["enabled"] and d["code_ok"] and d["code_len"] == len(ts.CODE) and "255.255.255.255" in d["broadcasts"]
    c2 = ts.cfg("d4", p2p_enabled=False, p2p_secret="court")
    e2 = SyncEngine(c2)
    assert e2.diagnostics()["code_ok"] is False and e2.state_label() == "Désactivée"
    # migration : l'ancien code trop court désactive la synchro ET le signale
    path = os.path.join(ts.tmp, "legacy2.json")
    json.dump({"p2p_enabled": True, "p2p_secret": "huitcar8", "design_v2": True}, open(path, "w"))
    cc = Config(path)
    assert cc["p2p_enabled"] is False and cc.p2p_notice == "short_code"


def test_broadcast_targets_per_interface():
    t = netutil.parse_ip_addr("2: eth0    inet 192.168.5.7/24 brd 192.168.5.255 scope global eth0\n"
                              "3: wlan0    inet 10.1.2.3/16 brd 10.1.255.255 scope global wlan0")
    assert [i["brd"] for i in t] == ["192.168.5.255", "10.1.255.255"]
    orig = netutil.interfaces
    netutil.interfaces = lambda: t
    try:
        assert netutil.broadcast_targets() == ["192.168.5.255", "10.1.255.255", "255.255.255.255"]
        hosts = netutil.scan_candidates()
        assert "192.168.5.8" in hosts and "192.168.5.7" not in hosts                       # jamais soi-même
        assert all(h.startswith(("192.168.5.", "10.1.2.")) for h in hosts)                 # /16 limité au /24 voisin
    finally:
        netutil.interfaces = orig
