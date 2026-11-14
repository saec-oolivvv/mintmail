"""Petites fonctions de l'interface Qt, sans Qt : épingles envoyées vers la boîte, recherche sur le serveur, journal d'erreurs, langues.
Mêmes règles que la version GTK (window.py / extras.py)."""
from typing import List, Tuple

from .. import i18n
from ..i18n import tr
from ..log import LOG, tail

LANGUAGE_NAMES = {"fr": "Français", "en": "English", "nl": "Nederlands", "de": "Deutsch", "es": "Español"}


# ----------------------------------------------------------------------- épingles
def save_pin_states(engine) -> List[str]:
    """Enregistre ce que le serveur a PROUVÉ (garde / ne garde pas les épingles) et retourne les comptes dont les épingles locales
    doivent encore être envoyées vers la boîte (une seule fois par compte)."""
    changed, to_push = False, []
    done = list(engine.config.get("pins_pushed", []))
    for aid, be in list(engine._backends.items()):
        if getattr(be, "_pin_dirty", False):
            be._pin_dirty = False
            changed = True
        if getattr(be, "acc", {}).get("pin_server") is True and aid not in done:
            to_push.append(aid)
    if to_push:
        engine.config["pins_pushed"] = done + to_push
        changed = True
    if changed:
        engine.config.save()
    return to_push


def push_pins(engine, aid=None) -> int:
    """Envoie vers la boîte les épingles faites sur ce poste (les autres postes les verront) ; retourne le nombre de messages concernés."""
    accounts = [aid] if aid else [a["id"] for a in engine.accounts() if not a.get("demo")]
    total = 0
    for a in accounts:
        msgs = engine.cache.pinned_messages(a)
        if msgs:
            total += len(msgs)
            engine.run_ops(engine.op_enqueue("flags", msgs, pinned=True))
    return total


def pins_text(n: int) -> str:
    return tr("%d épingle(s) envoyée(s) vers la boîte : les autres postes les verront.") % n if n else tr("Aucun message épinglé à envoyer.")


# ----------------------------------------------------------------------- recherche sur le serveur
def server_search_logicals(view_key: str) -> List[str]:
    return ["inbox", "sent", "archive"] + ([view_key] if (view_key or "").startswith("f:") else [])


def search_server(engine, text: str, view_key: str) -> int:
    """Cherche aussi sur le serveur (messages jamais téléchargés) et les ajoute au cache ; retourne le nombre trouvé."""
    logicals, found = server_search_logicals(view_key), 0
    for a in engine.accounts():
        if a.get("demo"):
            continue
        known = {f: set(engine.cache.uids(a["id"], f)) for f in logicals}
        msgs = engine.backend(a["id"]).search_server(text, logicals, known)
        if msgs:
            engine.cache.upsert_many(msgs)
            found += len(msgs)
    return found


def server_search_text(n: int) -> str:
    return tr("%d message(s) supplémentaire(s) trouvé(s) sur le serveur") % n if n else tr("Rien de plus sur le serveur.")


# ----------------------------------------------------------------------- journal et langue
def log_text() -> str:
    return "%s\n\n%s" % (LOG, tail())


def languages() -> List[Tuple[str, str]]:
    """[(code, libellé)] : « auto » d'abord, puis les langues livrées."""
    return [("auto", tr("Automatique (langue du système)"))] + [(c, LANGUAGE_NAMES.get(c, c)) for c in i18n.available()]


def set_language(config, code: str) -> str:
    """Enregistre la langue (prise en compte au prochain démarrage) ; retourne le message à afficher."""
    if code != "auto" and code not in i18n.available():
        return ""
    config["ui_lang"] = code
    config.save()
    return tr("Langue enregistrée : redémarrez MintMail pour l'appliquer.")
