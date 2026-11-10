"""Envoi d'événements vers un agenda CalDAV (Nextcloud, Radicale, Fastmail, iCloud…) : PUT d'un fichier .ics."""
import base64
import ipaddress
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Tuple
from .i18n import tr


def _allowed(url: str) -> bool:
    u = urllib.parse.urlparse(url)
    if u.scheme == "https":
        return True
    try:
        ip = ipaddress.ip_address(u.hostname or "")
        return u.scheme == "http" and (ip.is_loopback or ip.is_private)
    except ValueError:
        return False


def _auth(user: str, password: str) -> str:
    return "Basic " + base64.b64encode(("%s:%s" % (user, password)).encode("utf-8")).decode()


def put_event(url: str, user: str, password: str, ics: str, uid: str, timeout: float = 15.0) -> Tuple[bool, str]:
    """Crée / met à jour l'événement dans la collection CalDAV `url`. Retourne (ok, détail)."""
    if not _allowed(url):
        return False, tr("HTTPS obligatoire (HTTP seulement sur le réseau local)")
    name = re.sub(r"[^A-Za-z0-9._-]", "_", uid)[:80] or "event"
    target = url.rstrip("/") + "/" + name + ".ics"
    req = urllib.request.Request(target, data=ics.encode("utf-8"), method="PUT", headers={
        "Content-Type": "text/calendar; charset=utf-8", "Authorization": _auth(user, password), "User-Agent": "MintMail"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status in (200, 201, 204), "HTTP %d" % r.status
    except urllib.error.HTTPError as e:
        hint = {401: tr("identifiants refusés"), 403: tr("accès refusé"), 404: tr("calendrier introuvable (vérifiez l'adresse)")}.get(e.code, "")
        return False, "HTTP %d %s" % (e.code, hint)
    except (urllib.error.URLError, OSError) as e:
        return False, str(getattr(e, "reason", e))[:100]


def test_connection(url: str, user: str, password: str, timeout: float = 10.0) -> Tuple[bool, str]:
    """Vérifie l'adresse et les identifiants (requête OPTIONS)."""
    if not _allowed(url):
        return False, tr("HTTPS obligatoire (HTTP seulement sur le réseau local)")
    req = urllib.request.Request(url, method="OPTIONS", headers={"Authorization": _auth(user, password), "User-Agent": "MintMail"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            dav = r.headers.get("DAV", "")
            return True, tr("connecté") + (" (CalDAV : %s)" % dav if dav else "")
    except urllib.error.HTTPError as e:
        return False, "HTTP %d" % e.code
    except (urllib.error.URLError, OSError) as e:
        return False, str(getattr(e, "reason", e))[:100]
