"""Qui mérite une alerte ou un son : réglages de notification par boîte, VIP, silence horaire — SANS Qt.
Modes : « all » (tous les messages), « vip » (contacts et VIP seulement), « people » (personnes : ni newsletters ni notifications automatiques), « none »."""
import datetime

MODES = ("all", "people", "vip", "none")
DEFAULTS = {"notify_mode": "all", "notify_off_accounts": [], "vips": [], "quiet_enabled": False, "quiet_from": "22:00", "quiet_to": "07:00"}


def settings(cfg) -> dict:
    s = {k: (cfg.get(k) if hasattr(cfg, "get") and cfg.get(k) is not None else v) for k, v in DEFAULTS.items()}
    if s["notify_mode"] not in MODES:
        s["notify_mode"] = "all"
    for k in ("notify_off_accounts", "vips"):
        s[k] = [x for x in s[k] if isinstance(x, str)] if isinstance(s[k], list) else []
    s["quiet_enabled"] = bool(s["quiet_enabled"])
    return s


def _minutes(hhmm, default):
    try:
        h, m = str(hhmm).split(":")
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return default


def in_quiet_hours(s, now=None) -> bool:
    """Vrai pendant le silence horaire (peut passer minuit : 22:00 → 07:00)."""
    if not s["quiet_enabled"]:
        return False
    now = now or datetime.datetime.now()
    cur = now.hour * 60 + now.minute
    a, b = _minutes(s["quiet_from"], 22 * 60), _minutes(s["quiet_to"], 7 * 60)
    if a == b:
        return False
    return a <= cur < b if a < b else (cur >= a or cur < b)


def is_vip(cfg, msg) -> bool:
    e = (msg.sender_email or "").lower()
    return e in {x.lower() for x in (cfg.get("vips") or [])} or e in {str(k).lower() for k in (cfg.get("contacts") or {})}


def wants(cfg, msg, now=None) -> bool:
    """Ce message a-t-il droit à une alerte (et un son) ? Les messages déjà lus ou bloqués jamais."""
    s = settings(cfg)
    if s["notify_mode"] == "none" or in_quiet_hours(s, now) or msg.account in s["notify_off_accounts"]:
        return False
    if (msg.sender_email or "").lower() in {x.lower() for x in (cfg.get("blocked") or [])}:
        return False
    if s["notify_mode"] == "vip":
        return is_vip(cfg, msg)
    if s["notify_mode"] == "people":
        return msg.category not in ("news", "notif") and not msg.unsubscribe and not getattr(msg, "auto", False)
    return True


def split(cfg, msgs, now=None):
    """Messages qui doivent alerter parmi les nouveaux."""
    return [m for m in msgs if wants(cfg, m, now)]


def title_with_count(base, unread) -> str:
    return "%s (%d)" % (base, unread) if unread > 0 else base


def badge_label(unread) -> str:
    """Texte de la pastille sur l'icône (comme sur un téléphone) : vide à 0, « 99+ » au-delà de 99."""
    n = int(unread or 0)
    return "" if n <= 0 else str(n) if n <= 99 else "99+"


def update(cfg, **changes) -> dict:
    """Enregistre les réglages de notification (clés inconnues ignorées)."""
    for k, v in changes.items():
        if k in DEFAULTS:
            cfg[k] = v
    if hasattr(cfg, "save"):
        cfg.save()
    return settings(cfg)
