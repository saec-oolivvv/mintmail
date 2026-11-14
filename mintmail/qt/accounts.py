"""Comptes et réglages SANS Qt : validation d'un compte, enregistrement (mot de passe dans le trousseau), suppression, test de connexion,
application des réglages. Mêmes règles que la page « Comptes » de l'interface GTK ; testé sur le moteur seul."""
import re
from typing import Dict, Optional, Tuple

from ..backend import PRESETS, make_backend, new_account_id
from ..i18n import tr

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PRESET_LABELS = {
    "Gmail — connexion Google (OAuth, sans mot de passe)": tr("Gmail — connexion Google (OAuth, sans mot de passe)"),
    "Outlook / Microsoft 365 — connexion Microsoft (OAuth)": tr("Outlook / Microsoft 365 — connexion Microsoft (OAuth)"),
    "Gmail (mot de passe d'application)": tr("Gmail (mot de passe d'application)"),
    "Autre (manuel)": tr("Autre (manuel)"),
}
THEMES = [("system", tr("Système")), ("light", tr("Clair")), ("dark", tr("Sombre"))]
DENSITIES = [("compact", tr("Compacte")), ("comfortable", tr("Confortable")), ("spacious", tr("Aérée"))]
APPEARANCE_KEYS = ["theme", "style", "accent", "density", "load_images", "notifications", "refresh_minutes", "undo_seconds"]


def preset_choices():
    """[(clé du préréglage, libellé affiché)] dans l'ordre de l'interface GTK."""
    return [(k, PRESET_LABELS.get(k, k)) for k in PRESETS]


def apply_preset(key) -> Dict:
    p = PRESETS.get(key)
    return dict(p) if p else {}


def collect(current: Dict, form: Dict, oauth: Optional[str] = None) -> Tuple[Optional[Dict], str]:
    """Compte à enregistrer d'après le formulaire, ou (None, message d'erreur)."""
    a = dict(current or {})
    a.setdefault("id", new_account_id())
    try:
        ip, sp = int(form.get("imap_port", 993)), int(form.get("smtp_port", 587))
    except (TypeError, ValueError):
        return None, tr("Les ports doivent être des nombres.")
    a.update(name=(form.get("name") or "").strip(), email=(form.get("email") or "").strip(), username=(form.get("username") or "").strip(),
             imap_host=(form.get("imap_host") or "").strip(), imap_port=ip, smtp_host=(form.get("smtp_host") or "").strip(), smtp_port=sp,
             imap_ssl=bool(form.get("imap_ssl", True)))
    a.pop("demo", None)
    if oauth:
        a["auth"], a["oauth_provider"] = "oauth2", oauth
    else:
        a.pop("auth", None)
        a.pop("oauth_provider", None)
    if not EMAIL_RE.match(a["email"]):
        return None, tr("Adresse e-mail invalide.")
    if not a["imap_host"] or not a["smtp_host"]:
        return None, tr("Serveurs IMAP et SMTP requis (choisissez un fournisseur).")
    if not (1 <= ip <= 65535 and 1 <= sp <= 65535):
        return None, tr("Port invalide (1 à 65535).")
    return a, ""


def save_account(config, cache, account: Dict, password: str = "", oauth: Optional[str] = None) -> str:
    """Enregistre le compte (nouveau ou modifié) ; le mot de passe / jeton va dans le trousseau. Retourne un message d'erreur ou ""."""
    existing = next((x for x in config["accounts"] if x["id"] == account["id"]), None)
    if oauth and not password and not (existing and existing.get("auth") == "oauth2" and existing.get("has_password", True)):
        return tr("Connectez-vous d'abord avec le bouton « Se connecter ».")
    if not oauth and not password and not (existing and existing.get("has_password", True)):
        return tr("Mot de passe requis.")
    if any(x["email"].lower() == account["email"].lower() and x["id"] != account["id"] for x in config["accounts"]):
        return tr("Ce compte existe déjà.")
    if password:
        config.set_password(account["id"], password)
        account["has_password"] = True
    else:
        account["has_password"] = (existing or {}).get("has_password", True)
    account["signature_html"] = (existing or {}).get("signature_html", "")
    config["accounts"] = [x for x in config["accounts"] if x["id"] != account["id"]] + [account]
    config.save()
    return ""


def remove_account(config, cache, aid: str):
    """Retire le compte, son mot de passe et son cache local (les mails restent sur le serveur)."""
    config["accounts"] = [x for x in config["accounts"] if x["id"] != aid]
    config.delete_password(aid)
    config.save()
    cache.delete_account(aid)


def test_account(config, account: Dict, password: str = "") -> Optional[str]:
    """Teste IMAP + SMTP sans rien enregistrer. Retourne None si tout va bien, sinon le message d'erreur. Bloquant : à lancer en fond."""
    pw = password or config.password(account["id"])

    class _C:                                           # configuration minimale pour make_backend
        def password(self_, _id):
            return pw

        def get(self_, key, default=None):
            return config.get(key, default)

        def set_password(self_, *_a):
            pass
    return make_backend(account, _C()).test()


def reset_appearance(config):
    config.reset(APPEARANCE_KEYS + ["layout"])
    config.save()
