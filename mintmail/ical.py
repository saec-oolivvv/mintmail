"""iCalendar (RFC 5545) : lecture des invitations reçues, réponses (accepter / peut-être / refuser)."""
import datetime
import re
import time
from typing import Dict, Optional
from .i18n import tr


def _unfold(text: str) -> str:
    return re.sub(r"\r?\n[ \t]", "", text)


def _unesc(v: str) -> str:
    return v.replace("\\n", "\n").replace("\\N", "\n").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")


def _esc(v: str) -> str:
    return re.sub(r"([,;\\])", r"\\\1", v).replace("\n", "\\n")


def _dt(value: str) -> str:
    """20261112T140000Z / 20261112T140000 / 20261112 -> 'YYYY-MM-DDTHH:MM' (heure telle qu'écrite ; Z converti en heure locale)."""
    m = re.match(r"^(\d{4})(\d{2})(\d{2})(?:T(\d{2})(\d{2})(\d{2})?)?(Z?)$", value.strip())
    if not m:
        return ""
    y, mo, d, h, mi, _s, z = m.groups()
    try:
        dt = datetime.datetime(int(y), int(mo), int(d), int(h or 0), int(mi or 0))
    except ValueError:
        return ""
    if z:
        dt = dt.replace(tzinfo=datetime.timezone.utc).astimezone().replace(tzinfo=None)
    return dt.strftime("%Y-%m-%dT%H:%M")


def parse_invite(text: str) -> Optional[Dict]:
    """Premier VEVENT d'un fichier .ics reçu ; None si ce n'est pas un événement exploitable."""
    if not text or "BEGIN:VEVENT" not in text:
        return None
    lines = _unfold(text).splitlines()
    inv: Dict = {"method": "PUBLISH", "uid": "", "title": "", "start": "", "end": "", "location": "", "organizer": "",
                 "organizer_name": "", "sequence": 0, "dtstart_raw": "", "dtend_raw": "", "attendees": [], "description": ""}
    in_event = False
    for line in lines:
        if line.startswith("BEGIN:VEVENT"):
            in_event = True
            continue
        if line.startswith("END:VEVENT"):
            break
        name, _, value = line.partition(":")
        key = name.split(";")[0].upper()
        if not in_event:
            if key == "METHOD":
                inv["method"] = value.strip().upper()
            continue
        if key == "UID":
            inv["uid"] = value.strip()[:200]
        elif key == "SUMMARY":
            inv["title"] = _unesc(value)[:200]
        elif key == "DTSTART":
            inv["start"], inv["dtstart_raw"] = _dt(value), line
        elif key == "DTEND":
            inv["end"], inv["dtend_raw"] = _dt(value), line
        elif key == "LOCATION":
            inv["location"] = _unesc(value)[:200]
        elif key == "DESCRIPTION":
            inv["description"] = _unesc(value)[:500]
        elif key == "SEQUENCE" and value.strip().isdigit():
            inv["sequence"] = int(value.strip())
        elif key == "ORGANIZER":
            inv["organizer"] = re.sub(r"(?i)^mailto:", "", value.strip())[:200]
            cn = re.search(r'CN="?([^;:"]+)"?', name)
            inv["organizer_name"] = cn.group(1) if cn else ""
        elif key == "ATTENDEE":
            inv["attendees"].append(re.sub(r"(?i)^mailto:", "", value.strip())[:200])
    if not (inv["uid"] and inv["start"]):
        return None
    inv["attendees"] = inv["attendees"][:50]
    inv["raw"] = text[:20000]
    return inv


PARTSTAT = {"accept": "ACCEPTED", "tentative": "TENTATIVE", "decline": "DECLINED"}
SUBJECT = {"accept": tr("Accepté"), "tentative": tr("Peut-être"), "decline": tr("Refusé")}


def build_reply(inv: Dict, attendee_email: str, attendee_name: str, action: str) -> str:
    """Réponse iCalendar (METHOD:REPLY) à envoyer à l'organisateur."""
    stamp = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    cn = (";CN=" + _esc(attendee_name)) if attendee_name else ""
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//MintMail//FR", "METHOD:REPLY", "BEGIN:VEVENT",
             "UID:" + inv["uid"], "SEQUENCE:%d" % inv.get("sequence", 0), "DTSTAMP:" + stamp]
    for raw in (inv.get("dtstart_raw"), inv.get("dtend_raw")):
        if raw:
            lines.append(raw)
    lines += ["SUMMARY:" + _esc(inv.get("title") or tr("Rendez-vous")),
              "ORGANIZER:mailto:" + inv.get("organizer", ""),
              "ATTENDEE;PARTSTAT=%s%s:mailto:%s" % (PARTSTAT[action], cn, attendee_email),
              "END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(lines) + "\r\n"


def reply_subject(inv: Dict, action: str) -> str:
    return "%s : %s" % (SUBJECT[action], inv.get("title") or tr("Invitation"))
