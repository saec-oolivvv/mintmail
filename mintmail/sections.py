"""Découpage d'une liste de messages par période, comme dans Spark : Aujourd'hui, Hier, Semaine dernière, puis chaque mois de l'année
en cours, puis chaque année. Module SANS Qt, testable partout."""
import datetime
import time
from typing import List, Optional, Sequence, Tuple

from .i18n import tr


def month_names() -> List[str]:
    return [tr("Janvier"), tr("Février"), tr("Mars"), tr("Avril"), tr("Mai"), tr("Juin"), tr("Juillet"), tr("Août"), tr("Septembre"), tr("Octobre"),
            tr("Novembre"), tr("Décembre")]


def section_of(ts: float, now: Optional[float] = None) -> Tuple[str, str]:
    """(clé, libellé) de la période d'un message. Clé stable : deux messages de la même période ont la même clé."""
    today = datetime.date.fromtimestamp(now if now is not None else time.time())
    d = datetime.date.fromtimestamp(ts or 0)
    days = (today - d).days
    if days <= 0:
        return "today", tr("Aujourd'hui")
    if days == 1:
        return "yesterday", tr("Hier")
    if days <= 7:
        return "week", tr("Semaine dernière")
    if d.year == today.year:
        return "m%04d%02d" % (d.year, d.month), month_names()[d.month - 1]
    return "y%04d" % d.year, str(d.year)


def headings(dates: Sequence[float], now: Optional[float] = None) -> List[str]:
    """Pour chaque message (du plus récent au plus ancien) : le titre de période s'il ouvre une nouvelle période, sinon ''."""
    out, last = [], None
    for ts in dates:
        key, label = section_of(ts, now)
        out.append(label if key != last else "")
        last = key
    return out
