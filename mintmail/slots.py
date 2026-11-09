"""Créneaux libres d'après l'agenda : propositions de rendez-vous prêtes à coller dans une réponse."""
import datetime
from typing import Dict, List, Tuple

DAYS_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MONTHS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]


def free_slots(events: List[Dict], now: datetime.datetime, days: int = 14, duration: int = 60, count: int = 3,
               work_start: Tuple[int, int] = (9, 0), work_end: Tuple[int, int] = (17, 30), step: int = 30,
               min_lead_hours: int = 2) -> List[Tuple[datetime.datetime, datetime.datetime]]:
    """Jusqu'à `count` créneaux de `duration` minutes, sur des jours ouvrables DIFFÉRENTS (le premier libre de chaque jour), pendant
    les heures de travail, au moins `min_lead_hours` heures dans le futur. Les événements « occupés » (y compris les journées
    entières) bloquent ; les événements marqués disponibles (anniversaires, jours fériés…) ne bloquent pas."""
    busy = [e for e in events if e.get("busy", True)]
    out = []
    earliest = now + datetime.timedelta(hours=min_lead_hours)
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    for _ in range(days + 1):
        if len(out) >= count:
            break
        if day.weekday() < 5:
            day_end = day + datetime.timedelta(days=1)
            blocked_all_day = any(e["all_day"] and e["start"] < day_end and e["end"] > day for e in busy)
            if not blocked_all_day:
                t = day.replace(hour=work_start[0], minute=work_start[1])
                limit = day.replace(hour=work_end[0], minute=work_end[1])
                while t + datetime.timedelta(minutes=duration) <= limit:
                    end = t + datetime.timedelta(minutes=duration)
                    if t >= earliest and not any(not e["all_day"] and e["start"] < end and e["end"] > t for e in busy):
                        out.append((t, end))
                        break
                    t += datetime.timedelta(minutes=step)
        day += datetime.timedelta(days=1)
    return out


def format_slot(slot: Tuple[datetime.datetime, datetime.datetime]) -> str:
    s, e = slot
    return "%s %d %s, de %dh%02d à %dh%02d" % (DAYS_FR[s.weekday()], s.day, MONTHS_FR[s.month - 1], s.hour, s.minute, e.hour, e.minute)


def proposal_text(slots: List[Tuple[datetime.datetime, datetime.datetime]]) -> str:
    return "Je vous propose les créneaux suivants :\n" + "\n".join("- " + format_slot(s) for s in slots) + \
           "\nDites-moi celui qui vous convient."
