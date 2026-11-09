"""Données synchronisées entre machines : comptes (avec mot de passe), signatures, IA (clé comprise), modèles de
réponse rapide, règles, blocages, recherches, réglages d'apparence… avec dernière modification gagnante et suppressions.

Principe : chaque élément a une clé stable (« acct:<id> », « set:theme », « rule:<empreinte »…) et une date de dernière
modification. Les modifications locales sont détectées par comparaison d'empreintes avec le dernier état connu
(aucune instrumentation du reste de l'application). Une suppression locale devient une « pierre tombale » datée.

Les valeurs reçues d'un pair sont toujours validées (types, longueurs, listes blanches) avant d'être appliquées.
Les mots de passe ne transitent que dans le canal chiffré et authentifié de p2p.py.
"""
import hashlib
import json
import re
import time
from typing import Any, Dict, Optional, Tuple

from .store import DEFAULTS

ACCOUNT_FIELDS = ("id", "name", "email", "username", "imap_host", "imap_port", "imap_ssl", "smtp_host", "smtp_port",
                  "signature_html", "has_password")
SWIPE_ACTIONS = {"archive", "trash", "snooze", "read", "star", "pin", "spam", "block", "none"}
RULE_FIELDS = {"from", "subject", "to"}
RULE_ACTIONS = {"archive", "trash", "spam", "read", "star", "pin"}
HOST_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _b(v): return isinstance(v, bool)
def _enum(*vals): return lambda v: v in vals
def _int(lo, hi): return lambda v: isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi
def _str(n): return lambda v: isinstance(v, str) and len(v) <= n


def _swipe(v):
    return (isinstance(v, dict) and set(v) <= {"right", "right_long", "left", "left_long"}
            and all(x in SWIPE_ACTIONS for x in v.values()))


# réglages synchronisés (ni tailles de fenêtre, ni disposition, ni zoom : propres à chaque écran)
SYNC_SETTINGS = {
    "theme": _enum("system", "light", "dark"), "style": _enum("aurora", "papier", "terminal"),
    "accent": lambda v: isinstance(v, str) and re.match(r"^#[0-9a-fA-F]{6}$", v) is not None,
    "density": _enum("compact", "comfortable", "spacious"), "load_images": _b, "notifications": _b,
    "refresh_minutes": _int(1, 60), "undo_seconds": _int(3, 30), "swipe": _swipe, "swipe_invert": _b,
    "ai_enabled": _b, "ai_auto": _b, "ai_triage": _b, "ai_digest": _b, "ai_privacy": _enum("full", "minimal"),
    "ai_lang": _enum("fr", "en", "nl", "de", "es"), "ai_tone": _enum("neutral", "formal", "friendly"),
    "nvidia_api_base": lambda v: isinstance(v, str) and len(v) <= 200 and (v == "" or v.startswith("https://")),
    "ai_model": _str(100), "ai_has_key": _b,
}


def hash_value(v) -> str:
    return hashlib.sha256(json.dumps(v, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def kind_of(key: str) -> str:
    return key.split(":", 1)[0]


# ------------------------------------------------------------------ validation
def clean_account(v) -> Optional[dict]:
    if not isinstance(v, dict):
        return None
    out = {}
    try:
        out["id"] = v["id"]
        if not (isinstance(out["id"], str) and re.match(r"^[A-Za-z0-9_-]{4,40}$", out["id"])):
            return None
        out["email"] = v["email"]
        if not (isinstance(out["email"], str) and len(out["email"]) <= 200 and EMAIL_RE.match(out["email"])):
            return None
        for h in ("imap_host", "smtp_host"):
            if not (isinstance(v[h], str) and HOST_RE.match(v[h])):
                return None
            out[h] = v[h]
        for p in ("imap_port", "smtp_port"):
            if not _int(1, 65535)(v[p]):
                return None
            out[p] = v[p]
    except KeyError:
        return None
    for k, ok in (("name", _str(100)), ("username", _str(200)), ("signature_html", _str(20000))):
        out[k] = v.get(k, "") if ok(v.get(k, "")) else ""
    out["imap_ssl"] = v.get("imap_ssl", True) if _b(v.get("imap_ssl", True)) else True
    out["has_password"] = v.get("has_password", True) if _b(v.get("has_password", True)) else True
    pw = v.get("password")
    out["password"] = pw if isinstance(pw, str) and len(pw) <= 500 else None
    return out


def valid_item(key: str, item: Any) -> bool:
    """Un élément reçu d'un pair est-il acceptable ? (tombstone : toujours, sinon valeur contrôlée)"""
    if not (isinstance(item, dict) and isinstance(key, str) and len(key) <= 300):
        return False
    if not isinstance(item.get("ts"), (int, float)) or not _b(item.get("del", False)):
        return False
    if item.get("del"):
        return kind_of(key) in ("acct", "set", "secret", "rule", "blocked", "spam", "search", "tpl")
    v, kind, rest = item.get("v"), kind_of(key), key.split(":", 1)[-1]
    if kind == "acct":
        a = clean_account(v)
        return a is not None and a["id"] == rest
    if kind == "set":
        return rest in SYNC_SETTINGS and SYNC_SETTINGS[rest](v)
    if kind == "secret":
        return rest == "ai" and isinstance(v, str) and 0 < len(v) <= 500
    if kind == "rule":
        return (isinstance(v, dict) and v.get("field") in RULE_FIELDS and v.get("action") in RULE_ACTIONS
                and _str(200)(v.get("text")) and bool(v.get("text")))
    if kind in ("blocked", "spam"):
        return isinstance(v, str) and 0 < len(v) <= 200 and re.match(r"^@?[^\s@]+(@[^\s@]+)?$", v) is not None and v == rest
    if kind == "search":
        return isinstance(v, str) and 0 < len(v) <= 300 and 0 < len(rest) <= 100
    if kind == "tpl":
        return isinstance(v, str) and 0 < len(v) <= 20000 and 0 < len(rest) <= 100
    return False


# ------------------------------------------------------------------- collecte
def collect(config) -> Dict[str, Tuple[Any, Optional[str]]]:
    """État local : {clé: (valeur non secrète, mot de passe/secret ou None)}."""
    out: Dict[str, Tuple[Any, Optional[str]]] = {}
    for a in config.get("accounts", []):
        if a.get("demo") or not a.get("id"):
            continue
        v = {k: a.get(k) for k in ACCOUNT_FIELDS if k in a}
        v.setdefault("has_password", True)
        out["acct:" + a["id"]] = (v, config.password(a["id"]) or None)
    for k in SYNC_SETTINGS:
        out["set:" + k] = (config.get(k, DEFAULTS.get(k)), None)
    if config.get("ai_has_key"):
        key = config.password("ai:nvidia")
        out["secret:ai"] = (True, key or None)
    for r in config.get("rules", []):
        out["rule:" + hash_value(r)] = (r, None)
    for v in config.get("blocked", []):
        out["blocked:" + v] = (v, None)
    for v in config.get("spam_senders", []):
        out["spam:" + v] = (v, None)
    for s in config.get("saved_searches", []):
        out["search:" + s["name"]] = (s["query"], None)
    for t in config.get("templates", []):
        out["tpl:" + t["name"]] = (t["html"], None)
    return out


def local_items(config, now: Optional[float] = None) -> Dict[str, dict]:
    """Éléments locaux datés. Détecte les modifications / suppressions locales depuis le dernier état connu."""
    now = time.time() if now is None else now
    with config.sync_lock:
        meta = config.data.setdefault("sync_meta", {})
        current = collect(config)
        changed, items = False, {}
        for key, (v, secret) in current.items():
            h, m = hash_value(v), meta.get(key)
            ph = hash_value(secret) if secret else (m or {}).get("ph")
            if m is None or m.get("del") or m.get("h") != h or (secret and m.get("ph") != ph):
                first_default = (m is None and key.startswith("set:") and v == DEFAULTS.get(key[4:]))
                meta[key] = {"h": h, "ph": ph, "ts": 0.0 if first_default else now, "del": False}
                changed = changed or not first_default
            items[key] = {"v": v, "secret": secret, "ts": meta[key]["ts"], "del": False}
        for key, m in list(meta.items()):
            if key in current:
                continue
            if not m.get("del"):   # supprimé localement : pierre tombale datée
                meta[key] = {"h": None, "ph": None, "ts": now, "del": True}
                changed = True
            items[key] = {"v": None, "secret": None, "ts": meta[key]["ts"], "del": True}
        if changed:
            config.save()
    return items


def to_wire(items: Dict[str, dict]) -> Dict[str, dict]:
    """Format d'échange : le secret rejoint la valeur (le canal est chiffré)."""
    wire = {}
    for key, it in items.items():
        v = it["v"]
        if kind_of(key) == "acct" and not it["del"]:
            v = dict(v, password=it.get("secret"))
        elif kind_of(key) == "secret" and not it["del"]:
            v = it.get("secret")
        wire[key] = {"v": v, "ts": it["ts"], "del": it["del"]}
    return wire


def fingerprint(items: Dict[str, dict]) -> str:
    return hashlib.sha256(json.dumps(sorted((k, i["ts"], i["del"]) for k, i in items.items())).encode()).hexdigest()


def merge_items(local: Dict[str, dict], remote_wire: Any, node_local: str = "", node_remote: str = "") -> Dict[str, dict]:
    """Fonction pure : retourne les éléments distants qui l'emportent (plus récents que les locaux), validés."""
    wins: Dict[str, dict] = {}
    if not isinstance(remote_wire, dict):
        return wins
    for key, it in remote_wire.items():
        if not valid_item(key, it):
            continue
        mine = local.get(key)
        if mine is None:
            if it.get("del"):
                continue   # suppression d'un élément que nous n'avons pas : rien à faire
            wins[key] = it
        elif it["ts"] > mine["ts"]:
            wins[key] = it
    return wins


# -------------------------------------------------------------------- application
def apply_items(config, wins: Dict[str, dict], cache=None) -> dict:
    """Applique les éléments gagnants à la configuration locale. Retourne un résumé pour l'interface."""
    res = {"accounts": False, "settings": False, "lists": False, "ai": False, "new_accounts": [], "count": 0,
           "kinds": {}}
    with config.sync_lock:
        meta = config.data.setdefault("sync_meta", {})
        for key, it in wins.items():
            kind, rest, deleted, v = kind_of(key), key.split(":", 1)[-1], it.get("del"), it.get("v")
            ph = None
            if kind == "acct":
                acc = [a for a in config["accounts"] if a.get("id") == rest]
                if deleted:
                    if acc:
                        config["accounts"] = [a for a in config["accounts"] if a.get("id") != rest]
                        config.delete_password(rest)
                        config.data.get("folders", {}).pop(rest, None)
                        if cache is not None:
                            cache.delete_account(rest)
                        res["accounts"] = True
                else:
                    a = clean_account(v)
                    pw = a.pop("password")
                    old = acc[0] if acc else None
                    merged = dict(old or {}, **a)
                    if old:
                        config["accounts"] = [merged if x.get("id") == rest else x for x in config["accounts"]]
                    else:
                        config["accounts"] = [x for x in config["accounts"] if not x.get("demo")] + [merged]
                        res["new_accounts"].append(merged.get("name") or merged["email"])
                    if pw:
                        config.set_password(rest, pw)
                        ph = hash_value(pw)
                    res["accounts"] = True
                v_for_hash = {k: a.get(k) for k in ACCOUNT_FIELDS if k in a} if not deleted else None
            elif kind == "set":
                if not deleted:
                    config[rest] = v
                    res["settings"] = True
                    res["ai"] = res["ai"] or rest.startswith(("ai_", "nvidia"))
                v_for_hash = v
            elif kind == "secret":
                if deleted:
                    config.delete_password("ai:nvidia")
                    config["ai_has_key"] = False
                else:
                    config.set_password("ai:nvidia", v)
                    config["ai_has_key"] = True
                    ph = hash_value(v)
                res["ai"] = True
                v_for_hash = True if not deleted else None
            else:
                v_for_hash = v
                _apply_list_item(config, kind, rest, v, deleted)
                res["lists"] = True
            res["count"] += 1
            res["kinds"][kind] = res["kinds"].get(kind, 0) + 1
            meta[key] = {"h": hash_value(v_for_hash) if not deleted else None, "ph": ph or (meta.get(key) or {}).get("ph"),
                         "ts": it["ts"], "del": bool(deleted)}
        if wins:
            config.save()
    return res


def _apply_list_item(config, kind, rest, v, deleted):
    if kind == "rule":
        rules = [r for r in config["rules"] if hash_value(r) != rest]
        config["rules"] = rules if deleted else rules + [v]
    elif kind in ("blocked", "spam"):
        name = "blocked" if kind == "blocked" else "spam_senders"
        lst = [x for x in config[name] if x != rest]
        config[name] = lst if deleted else lst + [rest]
    elif kind == "search":
        lst = [s for s in config["saved_searches"] if s["name"] != rest]
        config["saved_searches"] = lst if deleted else lst + [{"name": rest, "query": v}]
    elif kind == "tpl":
        lst = [t for t in config["templates"] if t["name"] != rest]
        config["templates"] = lst if deleted else lst + [{"name": rest, "html": v}]


def describe(res: dict) -> str:
    names = {"acct": "compte(s)", "set": "réglage(s)", "secret": "clé IA", "rule": "règle(s)", "blocked": "blocage(s)",
             "spam": "expéditeur(s) en spam", "search": "recherche(s)", "tpl": "modèle(s)"}
    return ", ".join("%d %s" % (n, names.get(k, k)) for k, n in res.get("kinds", {}).items()) or "à jour"
