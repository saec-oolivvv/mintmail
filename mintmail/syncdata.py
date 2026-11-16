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

from .ai_service import is_local_endpoint
from .store import DEFAULTS
from .i18n import tr

ACCOUNT_FIELDS = ("id", "name", "email", "username", "imap_host", "imap_port", "imap_ssl", "smtp_host", "smtp_port",
                  "signature_html", "has_password", "auth", "oauth_provider")
SWIPE_ACTIONS = {"archive", "trash", "snooze", "read", "star", "pin", "spam", "block", "none"}
RULE_FIELDS = {"from", "subject", "to"}
RULE_ACTIONS = {"archive", "trash", "spam", "read", "star", "pin", "move"}
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
    "refresh_minutes": _int(1, 120), "undo_seconds": _int(0, 30), "swipe": _swipe, "swipe_invert": _b,
    "ai_enabled": _b, "ai_auto": _b, "ai_triage": _b, "ai_digest": _b, "ai_privacy": _enum("full", "minimal"),
    "ai_lang": _enum("fr", "en", "nl", "de", "es"), "ai_tone": _enum("neutral", "formal", "friendly"),
    "nvidia_api_base": lambda v: isinstance(v, str) and len(v) <= 200 and (v == "" or v.startswith("https://") or (
        v.startswith("http://") and is_local_endpoint(v))),
    "ai_model": _str(100), "ai_has_key": _b, "ai_prepare_drafts": _b, "ai_provider": _enum("nvidia", "ollama", "custom"), "threads": _b,
    "oauth_clients": lambda v: isinstance(v, dict) and set(v) <= {"google", "microsoft"} and all(
        isinstance(c, dict) and set(c) <= {"client_id", "client_secret"} and all(isinstance(x, str) and len(x) <= 300 for x in c.values())
        for c in v.values()),
    "gcal": lambda v: isinstance(v, dict) and set(v) <= {"account", "enabled"} and isinstance(v.get("enabled", False), bool)
        and (v.get("account") is None or (isinstance(v["account"], str) and re.match(r"^[A-Za-z0-9_-]{4,40}$", v["account"]) is not None)),
    "caldav": lambda v: isinstance(v, dict) and set(v) <= {"url", "user"} and all(isinstance(x, str) and len(x) <= 300 for x in v.values())
        and (not v.get("url") or v["url"].startswith("https://") or (v["url"].startswith("http://") and is_local_endpoint(v["url"]))),
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
    if v.get("auth") == "oauth2" and v.get("oauth_provider") in ("google", "microsoft"):
        out["auth"], out["oauth_provider"] = "oauth2", v["oauth_provider"]
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
        return kind_of(key) in ("acct", "set", "secret", "rule", "blocked", "spam", "imgs", "search", "tpl", "ident", "contact", "task", "followup")
    v, kind, rest = item.get("v"), kind_of(key), key.split(":", 1)[-1]
    if kind == "acct":
        a = clean_account(v)
        return a is not None and a["id"] == rest
    if kind == "set":
        return rest in SYNC_SETTINGS and SYNC_SETTINGS[rest](v)
    if kind == "secret":
        return rest in ("ai", "caldav") and isinstance(v, str) and 0 < len(v) <= 500
    if kind == "ident":
        return (isinstance(v, dict) and re.match(r"^[A-Za-z0-9_-]{4,40}$", rest) is not None and v.get("id") == rest
                and isinstance(v.get("account"), str) and re.match(r"^[A-Za-z0-9_-]{4,40}$", v["account"]) is not None
                and isinstance(v.get("email"), str) and len(v["email"]) <= 200 and EMAIL_RE.match(v["email"]) is not None
                and _str(100)(v.get("name", "")) and _str(20000)(v.get("signature_html", "")))
    if kind == "task":
        return (isinstance(v, dict) and re.match(r"^[A-Za-z0-9_-]{4,40}$", rest) is not None and v.get("id") == rest
                and isinstance(v.get("text"), str) and 0 < len(v["text"]) <= 300
                and (v.get("due", "") == "" or (isinstance(v.get("due"), str) and re.match(r"^\d{4}-\d{2}-\d{2}$", v["due"]) is not None))
                and _b(v.get("done", False)) and _str(200)(v.get("msg", "")) and _str(40)(v.get("account", ""))
                and isinstance(v.get("created", 0), (int, float)) and not isinstance(v.get("created", 0), bool))
    if kind == "followup":
        num = lambda x: isinstance(x, (int, float)) and not isinstance(x, bool)
        return (isinstance(v, dict) and 0 < len(rest) <= 250 and v.get("id") == rest and set(v) <= {"id", "at", "subject", "date", "to"}
                and num(v.get("at")) and num(v.get("date", 0)) and _str(500)(v.get("subject", "")) and _str(500)(v.get("to", "")))
    if kind == "contact":
        return (isinstance(v, dict) and EMAIL_RE.match(rest) is not None and len(rest) <= 200 and set(v) <= {"name", "phone", "org", "notes", "auto"}
                and _b(v.get("auto", False)) and all(isinstance(x, str) and len(x) <= 500 for k, x in v.items() if k != "auto"))
    if kind == "rule":
        return (isinstance(v, dict) and v.get("field") in RULE_FIELDS and v.get("action") in RULE_ACTIONS
                and _str(200)(v.get("text")) and bool(v.get("text"))
                and (v.get("action") != "move" or (isinstance(v.get("folder"), str) and 0 < len(v["folder"]) <= 120)))
    if kind in ("blocked", "spam", "imgs"):
        return isinstance(v, str) and 0 < len(v) <= 200 and re.match(r"^@?[^\s@]+(@[^\s@]+)?$", v) is not None and v == rest
    if kind == "search":
        return isinstance(v, str) and 0 < len(v) <= 300 and 0 < len(rest) <= 100
    if kind == "tpl":
        return isinstance(v, str) and 0 < len(v) <= 20000 and 0 < len(rest) <= 100
    return False


# ------------------------------------------------------------------- collecte
def collect(config, cache=None) -> Dict[str, Tuple[Any, Optional[str]]]:
    """État local : {clé: (valeur non secrète, mot de passe/secret ou None)}. `cache` : carnet d'adresses en base (contacts saisis ou importés
    qui ne seraient pas dans les réglages, contacts collectés automatiquement)."""
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
    if (config.get("caldav") or {}).get("url"):
        out["secret:caldav"] = (True, config.password("caldav") or None)
    for i in config.get("identities", []):
        if isinstance(i, dict) and i.get("id"):
            out["ident:" + i["id"]] = (i, None)
    for email, c in (config.get("contacts") or {}).items():
        out["contact:" + email] = (c, None)
    for email, c in _db_contacts(cache).items():
        out.setdefault("contact:" + email, (c, None))        # les réglages (fiches saisies) l'emportent sur la base
    for t in config.get("tasks", []):
        if isinstance(t, dict) and t.get("id"):
            out["task:" + t["id"]] = (t, None)
    for f in config.get("followups", []):
        if isinstance(f, dict) and f.get("id"):
            out["followup:" + str(f["id"])] = (f, None)
    for r in config.get("rules", []):
        out["rule:" + hash_value(r)] = (r, None)
    for v in config.get("blocked", []):
        out["blocked:" + v] = (v, None)
    for v in config.get("spam_senders", []):
        out["spam:" + v] = (v, None)
    for v in config.get("image_senders", []):
        out["imgs:" + v] = (v, None)
    for s in config.get("saved_searches", []):
        out["search:" + s["name"]] = (s["query"], None)
    for t in config.get("templates", []):
        out["tpl:" + t["name"]] = (t["html"], None)
    return out


AUTO_CONTACTS_MAX = 3000


def _db_contacts(cache) -> Dict[str, dict]:
    """Contacts de la base locale à synchroniser : fiches « manual » (saisies, importées, ajoutées depuis un message) et contacts collectés
    automatiquement qui ont un nom (marqués auto) ; l'ordre est stable pour que l'ensemble ne bouge pas d'un échange à l'autre."""
    out: Dict[str, dict] = {}
    if cache is None:
        return out
    try:
        rows = cache.contacts_list(limit=100000)
    except Exception:
        return out
    n_auto = 0
    for r in sorted(rows, key=lambda r: r["email"]):
        email = (r.get("email") or "").strip().lower()
        if not email or len(email) > 200 or not EMAIL_RE.match(email):
            continue
        if r.get("source") == "manual":
            out[email] = {"name": (r.get("name") or "")[:200], "phone": (r.get("phone") or "")[:60],
                          "org": (r.get("org") or "")[:120], "notes": (r.get("notes") or "")[:500]}
        elif r.get("name") and n_auto < AUTO_CONTACTS_MAX:
            n_auto += 1
            out[email] = {"name": r["name"][:200], "auto": True}
    return out


def local_items(config, now: Optional[float] = None, cache=None) -> Dict[str, dict]:
    """Éléments locaux datés. Détecte les modifications / suppressions locales depuis le dernier état connu."""
    now = time.time() if now is None else now
    with config.sync_lock:
        meta = config.data.setdefault("sync_meta", {})
        current = collect(config, cache)
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
                slot = "ai:nvidia" if rest == "ai" else "caldav"
                if deleted:
                    config.delete_password(slot)
                    if rest == "ai":
                        config["ai_has_key"] = False
                else:
                    config.set_password(slot, v)
                    if rest == "ai":
                        config["ai_has_key"] = True
                    ph = hash_value(v)
                res["ai"] = res["ai"] or rest == "ai"
                v_for_hash = True if not deleted else None
            else:
                v_for_hash = v
                _apply_list_item(config, kind, rest, v, deleted, cache)
                res["lists"] = True
            res["count"] += 1
            res["kinds"][kind] = res["kinds"].get(kind, 0) + 1
            meta[key] = {"h": hash_value(v_for_hash) if not deleted else None, "ph": ph or (meta.get(key) or {}).get("ph"),
                         "ts": it["ts"], "del": bool(deleted)}
        if wins:
            config.save()
    return res


def _apply_list_item(config, kind, rest, v, deleted, cache=None):
    if kind == "rule":
        rules = [r for r in config["rules"] if hash_value(r) != rest]
        config["rules"] = rules if deleted else rules + [v]
    elif kind in ("blocked", "spam", "imgs"):
        name = {"blocked": "blocked", "spam": "spam_senders", "imgs": "image_senders"}[kind]
        lst = [x for x in config[name] if x != rest]
        config[name] = lst if deleted else lst + [rest]
    elif kind == "search":
        lst = [s for s in config["saved_searches"] if s["name"] != rest]
        config["saved_searches"] = lst if deleted else lst + [{"name": rest, "query": v}]
    elif kind == "tpl":
        lst = [t for t in config["templates"] if t["name"] != rest]
        config["templates"] = lst if deleted else lst + [{"name": rest, "html": v}]
    elif kind == "ident":
        lst = [i for i in config.get("identities", []) if i.get("id") != rest]
        config["identities"] = lst if deleted else lst + [v]
    elif kind == "followup":
        lst = [f for f in config.get("followups", []) if str(f.get("id")) != rest]
        config["followups"] = lst if deleted else lst + [v]
    elif kind == "task":
        lst = [t for t in config.get("tasks", []) if t.get("id") != rest]
        config["tasks"] = lst if deleted else lst + [v]
    elif kind == "contact" and not deleted and v.get("auto"):
        if cache is not None and not any(c["email"] == rest and c["source"] == "manual" for c in cache.contacts_list(rest, limit=5)):
            cache.contact_upsert(rest, v.get("name", ""), source="auto", force_name=True)        # contact collecté (nom du pair : sinon les deux machines se renverraient leur nom sans fin) : dans le carnet seulement (pas dans les réglages)
    elif kind == "contact":
        contacts = dict(config.get("contacts") or {})
        if deleted:
            contacts.pop(rest, None)
        else:
            contacts[rest] = v
        config["contacts"] = contacts
        if cache is not None:   # carnet consultable (auto-complétion) : même contenu dans la base locale
            if deleted:
                cache.contact_delete(rest)
            else:
                cache.contact_upsert(rest, v.get("name", ""), v.get("phone", ""), v.get("org", ""), v.get("notes", ""), source="manual")


def describe(res: dict) -> str:
    names = {"acct": tr("compte(s)"), "set": tr("réglage(s)"), "secret": tr("clé IA"), "rule": tr("règle(s)"), "blocked": tr("blocage(s)"),
             "spam": tr("expéditeur(s) en spam"), "imgs": tr("expéditeur(s) aux images chargées"), "search": tr("recherche(s)"), "tpl": tr("modèle(s)"), "ident": tr("identité(s)"), "contact": tr("contact(s)"), "task": tr("tâche(s)")}
    names["followup"] = tr("relance(s) programmée(s)")
    return ", ".join("%d %s" % (n, names.get(k, k)) for k, n in res.get("kinds", {}).items()) or tr("à jour")
