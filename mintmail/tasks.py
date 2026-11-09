"""Tâches : lecture des échéances en français (« avant vendredi », « le 15/11 », « dans 3 jours »…) et tri."""
import calendar
import datetime
import re
import unicodedata
from typing import Dict, List, Optional

DAYS = {"lundi": 0, "mardi": 1, "mercredi": 2, "jeudi": 3, "vendredi": 4, "samedi": 5, "dimanche": 6}
MONTHS = {"janvier": 1, "janv": 1, "fevrier": 2, "fevr": 2, "fev": 2, "mars": 3, "avril": 4, "avr": 4, "mai": 5, "juin": 6,
          "juillet": 7, "juil": 7, "aout": 8, "septembre": 9, "sept": 9, "octobre": 10, "oct": 10, "novembre": 11, "nov": 11,
          "decembre": 12, "dec": 12}
_MONTH_RE = "|".join(sorted(MONTHS, key=len, reverse=True))


def _plain(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower().replace("’", "'"))
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def _safe(y: int, m: int, d: int) -> Optional[datetime.date]:
    try:
        return datetime.date(y, m, d)
    except ValueError:
        return None


def _pick_year(today: datetime.date, m: int, d: int) -> Optional[datetime.date]:
    """Date sans année : cette année ; l'année suivante seulement si elle est passée depuis plus de 60 jours (une échéance
    dépassée récemment reste en retard au lieu de sauter un an)."""
    this = _safe(today.year, m, d)
    if this is None:
        return None
    if this >= today or (today - this).days <= 60:
        return this
    return _safe(today.year + 1, m, d)


def parse_due(text: str, today: Optional[datetime.date] = None) -> Optional[datetime.date]:
    """Première échéance trouvée dans le texte, ou None. Jours de la semaine : prochaine occurrence (aujourd'hui exclu,
    sauf « ce vendredi »). Français uniquement."""
    today = today or datetime.date.today()
    t = _plain(text or "")
    m = re.search(r"\b(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2,4}))?\b", t)
    if m:
        d, mo = int(m.group(1)), int(m.group(2))
        if m.group(3):
            y = int(m.group(3))
            return _safe(y + 2000 if y < 100 else y, mo, d)
        return _pick_year(today, mo, d)
    m = re.search(r"\b(\d{1,2})(?:er)?\s+(%s)\b\.?(?:\s+(\d{4}))?" % _MONTH_RE, t)
    if m:
        d, mo = int(m.group(1)), MONTHS[m.group(2)]
        return _safe(int(m.group(3)), mo, d) if m.group(3) else _pick_year(today, mo, d)
    if re.search(r"apres[- ]?demain", t):
        return today + datetime.timedelta(days=2)
    if re.search(r"\bdemain\b", t):
        return today + datetime.timedelta(days=1)
    if re.search(r"aujourd'?hui|\bce soir\b|\bce jour\b|\bcet apres-midi\b", t):
        return today
    m = re.search(r"\bdans\s+(\d{1,3})\s+(jour|jours|semaine|semaines)\b", t)
    if m:
        return today + datetime.timedelta(days=int(m.group(1)) * (7 if m.group(2).startswith("semaine") else 1))
    if re.search(r"fin\s+(du\s+|de\s+|d'?)mois", t):
        return datetime.date(today.year, today.month, calendar.monthrange(today.year, today.month)[1])
    if re.search(r"fin\s+(de\s+la\s+|de\s+|d'?la\s+)?semaine", t):
        return today + datetime.timedelta(days=(4 - today.weekday()) % 7)
    if re.search(r"semaine\s+prochaine", t):
        return today + datetime.timedelta(days=7 - today.weekday())
    m = re.search(r"\b(ce\s+)?(%s)\b" % "|".join(DAYS), t)
    if m:
        delta = (DAYS[m.group(2)] - today.weekday()) % 7
        if delta == 0 and not m.group(1):
            delta = 7
        return today + datetime.timedelta(days=delta)
    m = re.search(r"\b(?:le|avant le|pour le|d'ici le)\s+(\d{1,2})\b(?!\s*(?:h|heure|:))", t)
    if m:
        d = int(m.group(1))
        cand = _safe(today.year, today.month, d)
        if cand is None or cand < today:
            ny, nm = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
            cand = _safe(ny, nm, d)
        return cand
    return None


def sort_key(task: Dict, today: Optional[datetime.date] = None):
    """En retard d'abord, puis par échéance, puis sans échéance."""
    due = task.get("due") or ""
    return (0 if due else 1, due or "9999-99-99", task.get("created", 0))


def is_overdue(task: Dict, today: Optional[datetime.date] = None) -> bool:
    today = today or datetime.date.today()
    return bool(task.get("due")) and not task.get("done") and task["due"] < today.isoformat()


def due_label(task: Dict, today: Optional[datetime.date] = None) -> str:
    today = today or datetime.date.today()
    if not task.get("due"):
        return ""
    d = datetime.date.fromisoformat(task["due"])
    n = (d - today).days
    if n < 0:
        return "en retard de %d j" % -n
    return {0: "aujourd'hui", 1: "demain"}.get(n, "dans %d j (%s)" % (n, d.strftime("%d/%m")))
