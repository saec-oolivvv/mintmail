"""Réglages d'agenda SANS Qt : Google Agenda (compte Gmail OAuth, autorisation, test) et CalDAV (adresse, identifiants, test).
Mêmes règles que les pages GTK ; les appels réseau sont à lancer en arrière-plan."""
import datetime
from typing import Callable, List, Tuple

from .. import caldav, gcal, oauth
from ..i18n import tr

GOOGLE_HELP = tr("Ce que ça apporte : les invitations acceptées et les rendez-vous détectés par l'IA arrivent directement dans Google Agenda "
                 "(sans doublon) ; « Agenda » dans la palette affiche vos 14 prochains jours et permet de créer un événement ; à la réception d'une "
                 "invitation, MintMail prévient si le créneau est déjà pris.\n\n"
                 "Mise en place (une seule fois) :\n"
                 "1. Connectez d'abord votre compte Gmail avec le fournisseur « OAuth » (Paramètres → Comptes).\n"
                 "2. Console Google Cloud (le même projet que pour Gmail) → API et services → Bibliothèque → « Google Calendar API » → Activer.\n"
                 "3. Ici : « Autoriser Google Agenda » (une page Google s'ouvre ; l'autorisation « calendar.events » est AJOUTÉE à celle de Gmail).\n"
                 "Important : tant que l'écran de consentement est en mode « Test », Google fait expirer le jeton au bout de 7 jours (il faut alors "
                 "ré-autoriser). Pour un usage personnel durable, passez l'application en « En production » (écran « application non validée » à "
                 "accepter une fois ; jusqu'à 100 utilisateurs).")
CALDAV_HELP = tr("Optionnel : les invitations acceptées et les rendez-vous détectés par l'IA sont ajoutés directement à ce calendrier "
                 "CalDAV (Nextcloud, Radicale, Fastmail, iCloud…). Sans CalDAV, MintMail ouvre le fichier .ics dans l'agenda de votre système "
                 "(Thunderbird, GNOME Agenda…). Les réponses aux invitations (accepter / refuser) sont toujours envoyées par e-mail.")


def google_accounts(config) -> List[dict]:
    return [a for a in config["accounts"] if a.get("auth") == "oauth2" and a.get("oauth_provider") == "google"]


def google_state(config) -> Tuple[List[dict], str, bool]:
    """(comptes Gmail OAuth, compte choisi, activé)."""
    accs, cur = google_accounts(config), config.get("gcal") or {}
    chosen = cur.get("account") if any(a["id"] == cur.get("account") for a in accs) else (accs[0]["id"] if accs else "")
    return accs, chosen, bool(cur.get("enabled")) and bool(accs)


def google_save(config, account_id, enabled) -> None:
    config["gcal"] = {"account": account_id or "", "enabled": bool(enabled and account_id)}
    config.save()


def google_authorize(config, account, open_url: Callable[[str], None]) -> Tuple[bool, str]:
    """Autorisation OAuth dans le navigateur (3 minutes maximum) ; enregistre le nouveau jeton (Gmail + Agenda). Bloquant : arrière-plan."""
    client = oauth.client_for(config, "google")
    if not account:
        return False, tr("Ajoutez d'abord un compte Gmail avec le fournisseur « OAuth » (Paramètres → Comptes).")
    if not client.get("client_id"):
        return False, tr("Identifiant client OAuth manquant : Paramètres → Comptes → Gmail (OAuth).")
    try:
        res = oauth.run_loopback_flow("google", client["client_id"], client.get("client_secret", ""), open_url,
                                      login_hint=account["email"], extra_scopes=[gcal.SCOPE])
        err = "" if res.get("refresh_token") else tr("Google n'a pas renvoyé de jeton durable : réessayez.")
    except Exception as e:
        return False, tr("Autorisation : %s") % e
    if err:
        return False, tr("Autorisation : %s") % err
    config.set_password(account["id"], res["refresh_token"])
    oauth.manager_for(config)._cache.pop(account["id"], None)
    google_save(config, account["id"], True)
    return True, tr("Google Agenda autorisé ✔ — cliquez « Tester » pour vérifier.")


def google_test(config, account) -> Tuple[bool, str]:
    if not account:
        return False, tr("Aucun compte Gmail (OAuth).")
    try:
        now = datetime.datetime.now()
        ok, data = gcal.list_events(oauth.manager_for(config).access_token(account), now, now + datetime.timedelta(days=7))
    except Exception as e:
        return False, "✖ %s" % e
    return (True, tr("✔ Connecté : %d événement(s) dans les 7 prochains jours.") % len(data)) if ok else (False, "✖ %s" % data)


def caldav_state(config) -> Tuple[str, str, bool]:
    cur = config.get("caldav") or {}
    return cur.get("url", ""), cur.get("user", ""), bool(config.password("caldav"))


def caldav_save(config, url, user, password="") -> Tuple[bool, str]:
    url = (url or "").strip()
    if url and not (url.startswith("https://") or url.startswith("http://")):
        return False, tr("L'adresse doit commencer par https://")
    config["caldav"] = {"url": url, "user": (user or "").strip()}
    if password:
        config.set_password("caldav", password)
    config.save()
    return True, tr("Enregistré ✔")


def caldav_clear(config) -> str:
    config["caldav"] = {}
    config.delete_password("caldav")
    config.save()
    return tr("CalDAV désactivé.")


def caldav_test(config, url, user, password="") -> Tuple[bool, str]:
    ok, d = caldav.test_connection((url or "").strip(), (user or "").strip(), password or config.password("caldav"))
    return bool(ok), ("✔ " if ok else "✖ ") + d
