"""Synchronisation automatique entre vos machines MintMail du même réseau local.

Tout ce qui configure MintMail est synchronisé (voir syncdata.py) : comptes avec mots de passe, signatures, IA (clé
comprise), modèles de réponse rapide, règles, blocages, recherches, apparence. Les suppressions se propagent aussi.
Le courrier n'est pas échangé (chaque machine le synchronise avec son serveur).

Sécurité — des identifiants circulant, le canal est authentifié ET chiffré :
- code de jumelage commun (12 caractères minimum), jamais transmis : PBKDF2-HMAC-SHA256 (600 000 itérations) ;
- authentification mutuelle par défi/réponse HMAC-SHA256 avec nonces (anti-rejeu) ;
- clés de session dérivées des nonces ; chiffrement par flux HMAC-SHA256 en mode compteur + étiquette HMAC-SHA256
  (chiffrer puis authentifier), numéro de séquence lié à chaque trame (rejet des trames altérées, rejouées ou
  réordonnées). Uniquement la bibliothèque standard : aucune dépendance.
Limites : pas de confidentialité persistante (un code compromis permet de déchiffrer un trafic enregistré) ; le code
doit rester secret et fort — utilisez « Générer ». Réseau local de confiance recommandé.
"""
import hashlib
import hmac
import ipaddress
import json
import re
import secrets
import socket
import threading
import time
from typing import Any, Dict, List, Optional

from . import netutil, syncdata
from .netutil import local_ip   # noqa: F401  (compatibilité : importé depuis ce module par les réglages)
from .store import P2P_MIN_SECRET

PROTOCOL = 3
MAX_LINE = 4096
MAX_FRAME = 8 * 1024 * 1024
MIN_SECRET = P2P_MIN_SECRET


def derive_key(secret: str) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), b"mintmail-p2p-v3", 600_000)


def reachable(host: str) -> bool:
    """Adresse d'un réseau local ou privé (y compris VPN / Tailscale en 100.64/10) : jamais une adresse publique."""
    try:
        return not ipaddress.ip_address(host).is_global
    except ValueError:
        return False


def _xor(data: bytes, ks: bytes) -> bytes:
    return (int.from_bytes(data, "big") ^ int.from_bytes(ks, "big")).to_bytes(len(data), "big") if data else b""


class SecureChannel:
    """Trames chiffrées + authentifiées au-dessus d'un fichier binaire (chiffrer puis authentifier)."""

    def __init__(self, f, key: bytes, nc: bytes, ns: bytes, initiator: bool):
        def sub(label):
            return hmac.new(key, label + b"|" + nc + b"|" + ns, hashlib.sha256).digest()
        c_enc, c_mac, s_enc, s_mac = sub(b"c2s-enc"), sub(b"c2s-mac"), sub(b"s2c-enc"), sub(b"s2c-mac")
        self.f = f
        self.send_enc, self.send_mac, self.recv_enc, self.recv_mac = (
            (c_enc, c_mac, s_enc, s_mac) if initiator else (s_enc, s_mac, c_enc, c_mac))
        self.send_seq = self.recv_seq = 0

    @staticmethod
    def _stream(key: bytes, seq: int, n: int) -> bytes:
        out, i = [], 0
        while sum(map(len, out)) < n:
            out.append(hmac.new(key, seq.to_bytes(8, "big") + i.to_bytes(4, "big"), hashlib.sha256).digest())
            i += 1
        return b"".join(out)[:n]

    def _tag(self, key: bytes, seq: int, hdr: bytes, ct: bytes) -> bytes:
        return hmac.new(key, seq.to_bytes(8, "big") + hdr + ct, hashlib.sha256).digest()

    def send(self, obj: Any) -> None:
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        if len(data) > MAX_FRAME:
            raise ValueError("trame trop grande")
        ct = _xor(data, self._stream(self.send_enc, self.send_seq, len(data)))
        hdr = len(ct).to_bytes(4, "big")
        self.f.write(hdr + ct + self._tag(self.send_mac, self.send_seq, hdr, ct))
        self.f.flush()
        self.send_seq += 1

    def _read(self, n: int) -> bytes:
        b = self.f.read(n)
        if b is None or len(b) != n:
            raise ValueError("connexion interrompue")
        return b

    def recv(self) -> Any:
        hdr = self._read(4)
        n = int.from_bytes(hdr, "big")
        if n > MAX_FRAME:
            raise ValueError("trame trop grande")
        ct, tag = self._read(n), self._read(32)
        if not hmac.compare_digest(tag, self._tag(self.recv_mac, self.recv_seq, hdr, ct)):
            raise ValueError("authentification de la trame échouée")
        pt = _xor(ct, self._stream(self.recv_enc, self.recv_seq, n))
        self.recv_seq += 1
        return json.loads(pt.decode("utf-8"))


class SyncEngine:
    """Découverte UDP, échange chiffré TCP, fusion « dernière modification gagnante » entièrement automatique."""

    def __init__(self, config, cache=None, on_update=None, apply_cb=None):
        self.config, self.cache, self.on_update, self.apply_cb = config, cache, on_update, apply_cb
        self._node_id = config.get("p2p_node_id")
        if not self._node_id:
            self._node_id = secrets.token_hex(4).upper()
            config["p2p_node_id"] = self._node_id
            config.save()
        secret = str(config.get("p2p_secret") or "")
        self._key: Optional[bytes] = derive_key(secret) if len(secret) >= MIN_SECRET else None
        self._enabled = bool(config.get("p2p_enabled", False))
        self._tcp_port = int(config.get("p2p_port", 54322))
        self._disc_port = int(config.get("p2p_disc_port", 54321))
        self._static = list(config.get("p2p_static_peers") or [])
        self._lock = threading.RLock()
        self._peers: Dict[str, Dict[str, Any]] = {}
        self._stop = threading.Event()
        self._running = False
        self._udp: Optional[socket.socket] = None
        self._srv: Optional[socket.socket] = None
        self._last_fp: Optional[str] = None
        self._sync_lock = threading.Lock()
        self._slots = threading.BoundedSemaphore(4)
        self.last_error, self.last_sync, self.last_summary = "", 0.0, ""
        self._instance = secrets.token_hex(4)           # distingue NOS annonces des autres (même si deux machines partagent un identifiant)
        self._own = netutil.own_addresses()
        self._own_at = time.time()
        self._started_at = 0.0
        self._last_scan = 0.0
        self.stats = {"sent": 0, "received": 0, "foreign": set(), "filtered": set(), "send_errors": 0, "scanned": 0}

    # ------------------------------------------------------------ état public
    def is_enabled(self) -> bool:
        return self._enabled

    def can_run(self) -> bool:
        return self._enabled and self._key is not None

    def node_id(self) -> str:
        return self._node_id

    def peers(self) -> List[Dict[str, str]]:
        with self._lock:
            return [{"node_id": p.get("node") or k, "host": p["host"], "port": str(p["port"]),
                     "last_seen": str(p["last_seen"]), "via": p.get("via", "annonce")} for k, p in self._peers.items()]

    def state_label(self) -> str:
        if not self._enabled:
            return "Désactivée"
        if self._key is None:
            return "Code de jumelage requis (%d caractères minimum)" % MIN_SECRET
        with self._lock:
            n = len(self._peers)
        base = "Active — appareil %s — %d pair(s)" % (self._node_id[:6], n)
        if self.last_error:
            return base + " — " + self.last_error
        if self.last_sync:
            return base + " — synchronisé à " + time.strftime("%H:%M:%S", time.localtime(self.last_sync))
        if n == 0 and self._started_at and time.time() - self._started_at > 30:
            return base + " — aucune machine vue (voir Paramètres → Synchronisation)"
        return base

    def diagnostics(self) -> Dict[str, Any]:
        """Tout ce qu'il faut pour comprendre pourquoi deux machines ne se voient pas."""
        secret = str(self.config.get("p2p_secret") or "")
        return {
            "enabled": self._enabled, "code_len": len(secret), "code_ok": self._key is not None,
            "udp_bound": self._udp is not None, "tcp_bound": self._srv is not None,
            "disc_port": self._disc_port, "tcp_port": self._tcp_port, "own_ips": sorted(self._own - {"127.0.0.1"}),
            "broadcasts": netutil.broadcast_targets(), "sent": self.stats["sent"], "received": self.stats["received"],
            "send_errors": self.stats["send_errors"], "foreign_versions": sorted(self.stats["foreign"]),
            "filtered": sorted(self.stats["filtered"]), "scanned": self.stats["scanned"], "peers": self.peers(),
        }

    def local_items(self):
        return syncdata.local_items(self.config)

    # --------------------------------------------------------------- cycle de vie
    def start(self) -> bool:
        if self._running or not self.can_run():
            return False
        self._stop.clear()
        self._running = True
        self._started_at = time.time()
        try:
            u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            u.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            u.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            u.bind(("", self._disc_port))
            u.settimeout(1.0)
            self._udp = u
        except OSError as e:
            self._udp = None
            self.last_error = "découverte automatique indisponible (%s)" % e.strerror
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("", self._tcp_port))
            s.listen(4)
            s.settimeout(1.0)
            self._srv = s
        except OSError as e:
            self._srv = None
            self.last_error = "port TCP %d indisponible (%s)" % (self._tcp_port, e.strerror)
        for spec in self._static:
            host, _, port = spec.partition(":")
            if host:
                with self._lock:
                    self._peers["static:" + host] = {"host": host, "port": int(port) if port.isdigit() else self._tcp_port,
                                                     "last_seen": time.time()}
        for target in (self._discovery_loop, self._server_loop, self._periodic_loop):
            threading.Thread(target=target, daemon=True, name="mintmail-p2p").start()
        threading.Timer(1.0, self._auto_sync).start()    # premier échange dès le démarrage
        return True

    def stop(self) -> None:
        self._stop.set()
        self._running = False
        for sock in (self._udp, self._srv):
            try:
                if sock:
                    sock.close()
            except OSError:
                pass
        self._udp = self._srv = None
        with self._lock:
            self._peers.clear()

    # ---------------------------------------------------------------- découverte
    def _announce_bytes(self) -> bytes:
        return ("MINTMAIL/%d %s %d %s" % (PROTOCOL, self._node_id, self._tcp_port, self._instance)).encode()

    def _send_announces(self):
        u = self._udp
        if u is None:
            return
        for target in netutil.broadcast_targets():
            try:
                u.sendto(self._announce_bytes(), (target, self._disc_port))
                self.stats["sent"] += 1
            except OSError:
                self.stats["send_errors"] += 1

    def _handle_announce(self, data: bytes, addr) -> Optional[str]:
        """Traite une annonce reçue ; retourne la clé du pair ajouté (ou None). Répond en unicast à un pair nouveau."""
        parts = data.decode("utf-8", "replace").split()
        if not parts or not parts[0].startswith("MINTMAIL/"):
            return None
        self.stats["received"] += 1
        host = addr[0]
        if parts[0] != "MINTMAIL/%d" % PROTOCOL:
            self.stats["foreign"].add(parts[0].split("/", 1)[1] if "/" in parts[0] else "?")   # machine d'une autre version
            return None
        if len(parts) < 3 or not parts[2].isdigit():
            return None
        instance = parts[3] if len(parts) > 3 else None
        if time.time() - self._own_at > 30:
            self._own, self._own_at = netutil.own_addresses(), time.time()
        if instance == self._instance or (instance is None and host in self._own):
            return None   # notre propre annonce (ou diffusion bouclée)
        if not reachable(host):
            self.stats["filtered"].add(host)
            return None
        key = "%s:%s" % (host, parts[2])
        with self._lock:
            first = key not in self._peers
            self._peers[key] = {"host": host, "port": int(parts[2]), "last_seen": time.time(), "node": parts[1], "via": "annonce"}
        if first:
            try:
                if self._udp is not None:   # réponse directe : le pair nous voit même si nos diffusions ne lui parviennent pas
                    self._udp.sendto(self._announce_bytes(), (host, self._disc_port))
            except OSError:
                pass
            threading.Thread(target=self._auto_sync, daemon=True).start()
        return key

    def _discovery_loop(self):
        last_announce = 0.0
        while not self._stop.is_set():
            u = self._udp
            if u is None:
                self._stop.wait(2)
                self._check_local_changes()
                continue
            now = time.time()
            with self._lock:
                alone = not self._peers
            if now - last_announce > (3 if alone else 15):
                last_announce = now
                self._send_announces()
            self._check_local_changes()
            try:
                data, addr = u.recvfrom(256)
            except socket.timeout:
                continue
            except OSError:
                break
            self._handle_announce(data, addr)

    def _periodic_loop(self):
        ticks = 0
        while not self._stop.wait(10):
            ticks += 1
            with self._lock:
                alone = not self._peers
            if alone and time.time() - self._started_at > 20 and time.time() - self._last_scan > 180:
                self.scan_now()          # personne vu : sonde le réseau local (la diffusion peut être filtrée)
            if ticks % 3 == 0:
                self._auto_sync()

    def scan_now(self) -> int:
        """Recherche active : sonde le port de synchro sur les réseaux locaux et vérifie l'authentification (code commun)."""
        if not self.can_run():
            return 0
        self._last_scan = time.time()
        hosts = netutil.scan_candidates()
        found, lock = [], threading.Lock()
        queue = list(hosts)

        def worker():
            while True:
                with lock:
                    if not queue or self._stop.is_set():
                        return
                    host = queue.pop()
                try:
                    socket.create_connection((host, self._tcp_port), timeout=0.3).close()
                except OSError:
                    continue
                peer = {"host": host, "port": self._tcp_port, "last_seen": time.time(), "via": "recherche"}
                if self._exchange(peer) >= 0:      # n'est retenu que si la machine connaît notre code de jumelage
                    with self._lock:
                        self._peers["%s:%d" % (host, self._tcp_port)] = peer
                    with lock:
                        found.append(host)
        threads = [threading.Thread(target=worker, daemon=True) for _ in range(48)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(60)
        self.stats["scanned"] = len(hosts)
        return len(found)

    def _check_local_changes(self):
        """Détecte toute modification locale (compte ajouté, signature, réglage…) et synchronise aussitôt."""
        try:
            fp = syncdata.fingerprint(self.local_items())
        except Exception:
            return
        if self._last_fp is not None and fp != self._last_fp:
            threading.Thread(target=self._auto_sync, daemon=True).start()
        self._last_fp = fp

    # ------------------------------------------------------------------ protocole
    def _mac(self, tag: bytes, a: str, b: str, node: str) -> str:
        return hmac.new(self._key, b"|".join([tag, a.encode(), b.encode(), node.encode()]), hashlib.sha256).hexdigest()

    @staticmethod
    def _read_line(f) -> dict:
        line = f.readline(MAX_LINE + 1)
        if not line or len(line) > MAX_LINE:
            raise ValueError("message vide ou trop long")
        obj = json.loads(line.decode("utf-8"))
        if not isinstance(obj, dict):
            raise ValueError("message invalide")
        return obj

    @staticmethod
    def _write_line(f, obj: dict):
        f.write(json.dumps(obj).encode("utf-8") + b"\n")
        f.flush()

    def _server_loop(self):
        while not self._stop.is_set():
            s = self._srv
            if s is None:
                self._stop.wait(2)
                continue
            try:
                conn, _addr = s.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            if not self._slots.acquire(blocking=False):
                conn.close()
                continue
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn):
        try:
            conn.settimeout(10.0)
            f = conn.makefile("rwb")
            hello = self._read_line(f)
            nc, node_c = str(hello.get("nc", "")), str(hello.get("node", ""))
            if hello.get("t") != "hello" or hello.get("v") != PROTOCOL or not re.fullmatch(r"[0-9a-f]{32}", nc):
                return
            ns = secrets.token_hex(16)
            self._write_line(f, {"t": "challenge", "node": self._node_id, "ns": ns,
                                 "ps": self._mac(b"S", nc, ns, self._node_id)})
            auth = self._read_line(f)
            if auth.get("t") != "auth" or not hmac.compare_digest(str(auth.get("pc", "")), self._mac(b"C", ns, nc, node_c)):
                return   # code de jumelage différent : rejet silencieux
            chan = SecureChannel(f, self._key, nc.encode(), ns.encode(), initiator=False)
            msg = chan.recv()
            mine = self.local_items()
            chan.send({"t": "items", "items": syncdata.to_wire(mine)})
            if msg.get("t") == "items":
                self._merge(mine, msg.get("items"), node_c)
        except (OSError, ValueError):
            pass
        finally:
            self._slots.release()
            try:
                conn.close()
            except OSError:
                pass

    def _exchange(self, peer: Dict[str, Any]) -> int:
        sock = None
        try:
            sock = socket.create_connection((peer["host"], int(peer["port"])), timeout=4.0)
            sock.settimeout(10.0)
            f = sock.makefile("rwb")
            nc = secrets.token_hex(16)
            self._write_line(f, {"t": "hello", "v": PROTOCOL, "node": self._node_id, "nc": nc})
            ch = self._read_line(f)
            ns, node_s = str(ch.get("ns", "")), str(ch.get("node", ""))
            if ch.get("t") != "challenge" or not hmac.compare_digest(str(ch.get("ps", "")), self._mac(b"S", nc, ns, node_s)):
                self.last_error = "code de jumelage différent sur « %s »" % node_s[:6]
                return -1
            self._write_line(f, {"t": "auth", "pc": self._mac(b"C", ns, nc, self._node_id)})
            chan = SecureChannel(f, self._key, nc.encode(), ns.encode(), initiator=True)
            mine = self.local_items()
            chan.send({"t": "items", "items": syncdata.to_wire(mine)})
            reply = chan.recv()
            self.last_error = ""
            self.last_sync = time.time()
            if reply.get("t") == "items":
                return self._merge(mine, reply.get("items"), node_s)
            return 0
        except (OSError, ValueError):
            return -1
        finally:
            if sock:
                sock.close()

    def _merge(self, mine: dict, remote_wire: Any, node: str) -> int:
        """Fusion « dernière modification gagnante » : applique ce qui est plus récent côté pair."""
        wins = syncdata.merge_items(mine, remote_wire)
        if not wins:
            return 0
        res = self.apply_cb(wins) if self.apply_cb else syncdata.apply_items(self.config, wins, self.cache)
        res = res or {"count": len(wins), "kinds": {}}
        self.last_summary = syncdata.describe(res)
        if self.on_update:
            try:
                self.on_update(res)
            except Exception:
                pass
        return int(res.get("count", len(wins)))

    def sync_now(self) -> dict:
        """Échange avec tous les pairs connus. Retourne {applied, peers_checked, failed}."""
        out = {"applied": 0, "peers_checked": 0, "failed": 0}
        if not self.can_run():
            return out
        with self._lock:
            peers = list(self._peers.values())
        for p in peers:
            n = self._exchange(p)
            out["peers_checked"] += 1
            if n < 0:
                out["failed"] += 1
            else:
                out["applied"] += n
        return out

    def _auto_sync(self):
        if not self._sync_lock.acquire(blocking=False):
            return
        try:
            self.sync_now()
        finally:
            self._sync_lock.release()
