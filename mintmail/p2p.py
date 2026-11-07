"""Synchronisation des préférences entre deux machines MintMail du même réseau local.

Ce qui est synchronisé (ajouts uniquement, jamais de suppression) : règles, modèles de réponse, expéditeurs
bloqués / en spam, recherches enregistrées, signatures des comptes déjà présents des deux côtés.

Ce qui n'est JAMAIS échangé : mots de passe, clés API, comptes de messagerie, courrier.

Sécurité : la fonction est désactivée par défaut. Elle exige un code de jumelage (8 caractères minimum),
identique sur les deux machines. L'authentification est mutuelle par défi/réponse HMAC-SHA256 (le code ne
circule jamais), avec nonces anti-rejeu. Les données échangées (préférences) ne sont pas chiffrées :
n'utilisez cette fonction que sur un réseau de confiance.
"""
import copy
import hashlib
import hmac
import ipaddress
import json
import re
import secrets
import socket
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

PROTOCOL = 2
MAX_LINE = 1_000_000
MIN_SECRET = 8
RULE_FIELDS = {"from", "subject", "to"}
RULE_ACTIONS = {"archive", "trash", "spam", "read", "star", "pin"}
LIST_KEYS = (("rules", "added_rules"), ("blocked", "added_blocked"),
             ("spam_senders", "added_spam_senders"), ("saved_searches", "added_saved_searches"))
COUNT_KEYS = ("added_rules", "added_templates", "added_blocked", "added_spam_senders",
              "added_saved_searches", "added_signatures")


def _key(x) -> str:
    return json.dumps(x, sort_keys=True, ensure_ascii=False)


def _short(s, n=300) -> bool:
    return isinstance(s, str) and 0 < len(s) <= n


def _valid(name: str, item) -> bool:
    """Valide un élément reçu d'un pair : on ne fait jamais confiance au réseau."""
    if name == "rules":
        return (isinstance(item, dict) and item.get("field") in RULE_FIELDS
                and item.get("action") in RULE_ACTIONS and _short(item.get("text"), 200))
    if name in ("blocked", "spam_senders"):
        return _short(item, 200) and re.match(r"^@?[^\s@]+(@[^\s@]+)?$", item) is not None
    if name == "saved_searches":
        return isinstance(item, dict) and _short(item.get("name"), 100) and _short(item.get("query"), 300)
    if name == "templates":
        return isinstance(item, dict) and _short(item.get("name"), 100) and _short(item.get("html"), 20000)
    return False


def merge_states(local: dict, remote: dict) -> Tuple[dict, dict]:
    """Union additive de l'état distant dans une copie de l'état local. Fonction pure.

    Retourne (état_fusionné, compteurs)."""
    out = copy.deepcopy(local)
    counts = {k: 0 for k in COUNT_KEYS}
    for name, ckey in LIST_KEYS:
        seen = {_key(x) for x in out.get(name, [])}
        for item in remote.get(name, []) if isinstance(remote.get(name), list) else []:
            if _valid(name, item) and _key(item) not in seen:
                out.setdefault(name, []).append(item)
                seen.add(_key(item))
                counts[ckey] += 1
    names = {t.get("name") for t in out.get("templates", [])}
    for t in remote.get("templates", []) if isinstance(remote.get("templates"), list) else []:
        if _valid("templates", t) and t["name"] not in names:
            out.setdefault("templates", []).append({"name": t["name"], "html": t["html"]})
            names.add(t["name"])
            counts["added_templates"] += 1
    sigs = dict(out.get("signatures", {}))
    rsigs = remote.get("signatures", {})
    for aid, sig in (rsigs.items() if isinstance(rsigs, dict) else []):
        if isinstance(aid, str) and isinstance(sig, str) and 0 < len(sig) <= 20000 and not sigs.get(aid):
            sigs[aid] = sig
            counts["added_signatures"] += 1
    out["signatures"] = sigs
    return out, counts


def local_ip() -> str:
    """Adresse IP locale (sans émettre aucun paquet)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def _private(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_private or ip.is_loopback or ip.is_link_local
    except ValueError:
        return False


class SyncEngine:
    """Moteur de synchronisation : découverte UDP, échange TCP authentifié, fusion additive."""

    def __init__(self, config, cache=None, on_update=None):
        self.config, self.cache, self.on_update = config, cache, on_update
        self._node_id = config.get("p2p_node_id")
        if not self._node_id:
            self._node_id = secrets.token_hex(4).upper()
            config["p2p_node_id"] = self._node_id
            config.save()
        secret = str(config.get("p2p_secret") or "")
        self._key: Optional[bytes] = (
            hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), b"mintmail-p2p-v2", 100_000)
            if len(secret) >= MIN_SECRET else None)
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
        self._last_hash: Optional[str] = None
        self._sync_lock = threading.Lock()
        self._slots = threading.BoundedSemaphore(4)
        self.last_error = ""

    # ------------------------------------------------------------ état public
    def is_enabled(self) -> bool:
        return self._enabled

    def can_run(self) -> bool:
        return self._enabled and self._key is not None

    def node_id(self) -> str:
        return self._node_id

    def peers(self) -> List[Dict[str, str]]:
        with self._lock:
            return [{"node_id": n, "host": p["host"], "port": str(p["port"]), "last_seen": str(p["last_seen"])}
                    for n, p in self._peers.items()]

    def state_label(self) -> str:
        if not self._enabled:
            return "Désactivée"
        if self._key is None:
            return "Code de jumelage requis (%d caractères minimum)" % MIN_SECRET
        if self.last_error:
            return "Active — %s" % self.last_error
        with self._lock:
            n = len(self._peers)
        return "Active — appareil %s — %d pair(s)" % (self._node_id[:6], n)

    def local_state(self) -> dict:
        c = self.config
        return {
            "rules": list(c.get("rules", [])), "templates": list(c.get("templates", [])),
            "blocked": list(c.get("blocked", [])), "spam_senders": list(c.get("spam_senders", [])),
            "saved_searches": list(c.get("saved_searches", [])),
            "signatures": {a["id"]: a["signature_html"] for a in c.get("accounts", [])
                           if a.get("id") and a.get("signature_html")},
        }

    # --------------------------------------------------------------- cycle de vie
    def start(self) -> bool:
        if self._running or not self.can_run():
            return False
        self._stop.clear()
        self._running = True
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
        for host_spec in self._static:
            host, _, port = host_spec.partition(":")
            if host:
                with self._lock:
                    self._peers["static:" + host] = {"host": host, "port": int(port) if port.isdigit() else self._tcp_port,
                                                     "last_seen": time.time()}
        for target in (self._discovery_loop, self._server_loop, self._periodic_loop):
            threading.Thread(target=target, daemon=True, name="mintmail-p2p").start()
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
    def _discovery_loop(self):
        last_announce = 0.0
        msg = ("MINTMAIL/%d %s %d" % (PROTOCOL, self._node_id, self._tcp_port)).encode()
        while not self._stop.is_set():
            u = self._udp
            if u is None:
                self._stop.wait(2)
                continue
            now = time.time()
            if now - last_announce > 10:
                last_announce = now
                try:
                    u.sendto(msg, ("255.255.255.255", self._disc_port))
                except OSError:
                    pass
            self._check_local_changes()
            try:
                data, addr = u.recvfrom(256)
            except socket.timeout:
                continue
            except OSError:
                break
            parts = data.decode("utf-8", "replace").split()
            if (len(parts) != 3 or parts[0] != "MINTMAIL/%d" % PROTOCOL or parts[1] == self._node_id
                    or not parts[2].isdigit() or not _private(addr[0])):
                continue
            with self._lock:
                first = parts[1] not in self._peers
                self._peers[parts[1]] = {"host": addr[0], "port": int(parts[2]), "last_seen": now}
            if first:
                threading.Thread(target=self._auto_sync, daemon=True).start()

    def _periodic_loop(self):
        while not self._stop.wait(60):
            self._auto_sync()

    def _check_local_changes(self):
        try:
            h = hashlib.sha256(_key(self.local_state()).encode()).hexdigest()
        except Exception:
            return
        if self._last_hash is not None and h != self._last_hash:
            threading.Thread(target=self._auto_sync, daemon=True).start()
        self._last_hash = h

    # ------------------------------------------------------------------ protocole
    def _mac(self, tag: bytes, a: str, b: str, node: str) -> str:
        return hmac.new(self._key, b"|".join([tag, a.encode(), b.encode(), node.encode()]),
                        hashlib.sha256).hexdigest()

    @staticmethod
    def _read(f) -> dict:
        line = f.readline(MAX_LINE + 1)
        if not line or len(line) > MAX_LINE:
            raise ValueError("message vide ou trop long")
        obj = json.loads(line.decode("utf-8"))
        if not isinstance(obj, dict):
            raise ValueError("message invalide")
        return obj

    @staticmethod
    def _write(f, obj: dict):
        f.write(json.dumps(obj, ensure_ascii=False).encode("utf-8") + b"\n")
        f.flush()

    def _server_loop(self):
        while not self._stop.is_set():
            s = self._srv
            if s is None:
                self._stop.wait(2)
                continue
            try:
                conn, addr = s.accept()
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
            conn.settimeout(6.0)
            f = conn.makefile("rwb")
            hello = self._read(f)
            nc, node_c = str(hello.get("nc", "")), str(hello.get("node", ""))
            if hello.get("t") != "hello" or hello.get("v") != PROTOCOL or not re.fullmatch(r"[0-9a-f]{32}", nc):
                return
            ns = secrets.token_hex(16)
            self._write(f, {"t": "challenge", "node": self._node_id, "ns": ns,
                            "ps": self._mac(b"S", nc, ns, self._node_id)})
            msg = self._read(f)
            if msg.get("t") != "state" or not hmac.compare_digest(
                    str(msg.get("pc", "")), self._mac(b"C", ns, nc, node_c)):
                return   # code de jumelage différent : rejet silencieux
            mine = self.local_state()
            self._write(f, {"t": "state", "state": mine})
            self._apply(mine, msg.get("state") if isinstance(msg.get("state"), dict) else {})
        except (OSError, ValueError):
            pass
        finally:
            self._slots.release()
            try:
                conn.close()
            except OSError:
                pass

    def _exchange(self, peer: Dict[str, Any]) -> dict:
        counts = {k: 0 for k in COUNT_KEYS}
        sock = None
        try:
            sock = socket.create_connection((peer["host"], int(peer["port"])), timeout=4.0)
            sock.settimeout(6.0)
            f = sock.makefile("rwb")
            nc = secrets.token_hex(16)
            self._write(f, {"t": "hello", "v": PROTOCOL, "node": self._node_id, "nc": nc})
            ch = self._read(f)
            ns, node_s = str(ch.get("ns", "")), str(ch.get("node", ""))
            if ch.get("t") != "challenge" or not hmac.compare_digest(
                    str(ch.get("ps", "")), self._mac(b"S", nc, ns, node_s)):
                self.last_error = "code de jumelage différent sur « %s »" % node_s[:6]
                return counts
            mine = self.local_state()
            self._write(f, {"t": "state", "pc": self._mac(b"C", ns, nc, self._node_id), "state": mine})
            reply = self._read(f)
            if reply.get("t") == "state" and isinstance(reply.get("state"), dict):
                self.last_error = ""
                return self._apply(mine, reply["state"])
        except (OSError, ValueError):
            pass
        finally:
            if sock:
                sock.close()
        return counts

    def _apply(self, mine: dict, remote: dict) -> dict:
        merged, counts = merge_states(mine, remote)
        if not any(counts.values()):
            return counts
        with self._lock:
            c = self.config
            for name, _ in LIST_KEYS:
                if len(merged.get(name, [])) != len(c.get(name, [])):
                    c[name] = merged[name]
            if len(merged.get("templates", [])) != len(c.get("templates", [])):
                c["templates"] = merged["templates"]
            for acc in c.get("accounts", []):
                sig = merged.get("signatures", {}).get(acc.get("id"))
                if sig and not acc.get("signature_html"):
                    acc["signature_html"] = sig
            c.save()
        if self.on_update:
            try:
                self.on_update(dict(counts))
            except Exception:
                pass
        return counts

    def sync_now(self) -> dict:
        """Échange avec tous les pairs connus ; retourne les compteurs d'ajouts."""
        total = {k: 0 for k in COUNT_KEYS}
        if not self.can_run():
            total["peers_checked"] = 0
            return total
        with self._lock:
            peers = list(self._peers.values())
        for p in peers:
            for k, v in self._exchange(p).items():
                total[k] += v
        total["peers_checked"] = len(peers)
        return total

    def _auto_sync(self):
        if not self._sync_lock.acquire(blocking=False):
            return
        try:
            self.sync_now()
        finally:
            self._sync_lock.release()
