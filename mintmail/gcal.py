"""Google Agenda (API REST v3) : ajout d'événements, liste des prochains rendez-vous, détection de conflits.

Authentification : jeton d'accès OAuth du compte Gmail connecté (voir oauth.py) avec l'autorisation « calendar.events »,
demandée séparément (Paramètres → Agenda → Autoriser Google Agenda).
"""
import datetime
import hashlib
import ipaddress
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List, Optional, Tuple

API = "https://www.googleapis.com/calendar/v3"
SCOPE = "https://www.googleapis.com/auth/calendar.events"
NEED_SCOPE = "autorisation de l'agenda manquante : Paramètres → Agenda → « Autoriser Google Agenda »"


def _allowed(base: str) -> bool:
    u = urllib.parse.urlparse(base)
    if u.scheme == "https":
        return True
    try:
        return u.scheme == "http" and ipaddress.ip_address(u.hostname or "").is_loopback     # tests locaux uniquement
    except ValueError:
        return False


def _call(method: str, url: str, token: str, body: Optional[dict] = None, timeout: float = 20.0) -> Tuple[int, dict]:
    if not _allowed(url):
        return 0, {"error": {"message": "HTTPS obligatoire"}}
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": "Bearer " + token, "Content-Type": "application/json", "Accept": "application/json", "User-Agent": "MintMail"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
            return r.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8", "replace"))
        except (ValueError, UnicodeDecodeError):
            return e.code, {}
    except (urllib.error.URLError, OSError, ValueError) as e:
        return 0, {"error": {"message": str(getattr(e, "reason", e))[:120]}}


def _explain(code: int, body: dict) -> str:
    msg = ((body or {}).get("error") or {}).get("message", "") if isinstance(body.get("error"), dict) else ""
    if code in (401, 403):
        if "scope" in msg.lower() or "insufficient" in msg.lower() or code == 403:
            return NEED_SCOPE if "not been used" not in msg and "disabled" not in msg.lower() else \
                "l'API Google Calendar n'est pas activée dans votre projet Google Cloud (API et services → Bibliothèque → Google Calendar API → Activer)"
        return "jeton refusé : reconnectez le compte (Paramètres → Comptes)"
    if code == 404:
        return "agenda introuvable"
    if code == 0:
        return msg or "connexion impossible"
    return "HTTP %d %s" % (code, msg[:80])


def _local_dt(text: str) -> datetime.datetime:
    """'2026-11-12T14:00' (heure locale) -> datetime avec fuseau local."""
    return datetime.datetime.fromisoformat(text).astimezone() if "T" in text else datetime.datetime.fromisoformat(text + "T00:00").astimezone()


def to_google_event(ev: Dict, uid: str = "") -> Dict:
    """Événement MintMail / invitation iCalendar {title,start,end,location,description} -> corps de requête Google."""
    start = _local_dt(ev["start"])
    end = _local_dt(ev["end"]) if ev.get("end") else start + datetime.timedelta(hours=1)
    if end <= start:
        end = start + datetime.timedelta(hours=1)
    out = {"summary": (ev.get("title") or "Rendez-vous")[:200],
           "start": {"dateTime": start.isoformat()}, "end": {"dateTime": end.isoformat()},
           "source": {"title": "MintMail", "url": "https://saec.me"}}
    if ev.get("location"):
        out["location"] = ev["location"][:300]
    if ev.get("description"):
        out["description"] = ev["description"][:1000]
    if uid:   # identifiant stable : ajouter deux fois la même invitation ne crée pas de doublon
        out["id"] = hashlib.sha1(uid.encode("utf-8")).hexdigest()
    return out


def insert_event(token: str, ev: Dict, uid: str = "", calendar: str = "primary", base: Optional[str] = None) -> Tuple[bool, str]:
    base = base or API
    code, body = _call("POST", "%s/calendars/%s/events" % (base, urllib.parse.quote(calendar)), token, to_google_event(ev, uid))
    if code in (200, 201):
        return True, "ajouté"
    if code == 409:
        return True, "déjà dans votre agenda"
    return False, _explain(code, body)


def parse_item(item: Dict) -> Optional[Dict]:
    """Élément Google -> {title, start, end (datetime locaux naïfs), all_day, location}."""
    try:
        s, e = item["start"], item["end"]
        if "dateTime" in s:
            start = datetime.datetime.fromisoformat(s["dateTime"].replace("Z", "+00:00")).astimezone().replace(tzinfo=None)
            end = datetime.datetime.fromisoformat(e["dateTime"].replace("Z", "+00:00")).astimezone().replace(tzinfo=None)
            allday = False
        else:
            start = datetime.datetime.fromisoformat(s["date"])
            end = datetime.datetime.fromisoformat(e["date"])
            allday = True
        return {"title": item.get("summary") or "(sans titre)", "start": start, "end": end, "all_day": allday,
                "location": item.get("location", ""), "status": item.get("status", "confirmed")}
    except (KeyError, ValueError, TypeError):
        return None


def list_events(token: str, start: datetime.datetime, end: datetime.datetime, calendar: str = "primary", base: Optional[str] = None,
                limit: int = 100) -> Tuple[bool, object]:
    """Événements entre deux dates (heure locale). Retourne (True, [événements triés]) ou (False, message)."""
    base = base or API
    q = urllib.parse.urlencode({"timeMin": start.astimezone().isoformat(), "timeMax": end.astimezone().isoformat(), "singleEvents": "true",
                                "orderBy": "startTime", "maxResults": str(limit)})
    code, body = _call("GET", "%s/calendars/%s/events?%s" % (base, urllib.parse.quote(calendar), q), token)
    if code != 200:
        return False, _explain(code, body)
    events = [e for e in (parse_item(i) for i in body.get("items", [])) if e and e["status"] != "cancelled"]
    return True, sorted(events, key=lambda e: e["start"])


def conflicts(events: List[Dict], start: datetime.datetime, end: datetime.datetime) -> List[Dict]:
    """Événements (hors journées entières) qui chevauchent [start, end[."""
    return [e for e in events if not e["all_day"] and e["start"] < end and e["end"] > start]
