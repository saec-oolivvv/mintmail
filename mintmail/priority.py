"""Priorité des messages (sans Qt) : 1 = haute, 0 = normale, -1 = basse.
Trois sources : l'importance posée par l'expéditeur (en-têtes X-Priority / Importance / Priority), le choix que vous faites vous-même sur un message
(prioritaire sur l'expéditeur), et la priorité estimée par l'IA (1 à 3, utilisée seulement pour le tri « Par priorité »)."""
from .i18n import tr

HIGH, NORMAL, LOW = 1, 0, -1
LEVELS = (HIGH, NORMAL, LOW)


def label(level) -> str:
    if level == HIGH:
        return tr("Haute")
    if level == LOW:
        return tr("Basse")
    return tr("Priorité normale")


def from_headers(em) -> int:
    """Importance voulue par l'expéditeur : X-Priority 1-2 = haute, 4-5 = basse ; Importance: high/low ; Priority: urgent / non-urgent."""
    xp = str(em.get("X-Priority", "") or "").strip()[:1]
    imp = str(em.get("Importance", "") or em.get("X-MSMail-Priority", "") or "").strip().lower()
    pri = str(em.get("Priority", "") or "").strip().lower()
    if xp in ("1", "2") or imp == "high" or pri == "urgent":
        return HIGH
    if xp in ("4", "5") or imp == "low" or pri == "non-urgent":
        return LOW
    return NORMAL


def headers(level) -> dict:
    """En-têtes à ajouter à un message envoyé ({} pour une priorité normale)."""
    if level == HIGH:
        return {"X-Priority": "1 (Highest)", "Importance": "High", "Priority": "urgent"}
    if level == LOW:
        return {"X-Priority": "5 (Lowest)", "Importance": "Low", "Priority": "non-urgent"}
    return {}


def clamp(level) -> int:
    try:
        return max(LOW, min(HIGH, int(level)))
    except (TypeError, ValueError):
        return NORMAL


def effective(user_level, sender_importance=0) -> int:
    """Votre choix (même « normale ») l'emporte sur celui de l'expéditeur ; sans choix de votre part : celui de l'expéditeur."""
    return clamp(user_level) if user_level is not None else clamp(sender_importance)


def sort_score(level, ai_priority=0) -> int:
    """Tri « Par priorité » : votre niveau d'abord, la priorité IA (0-3) départage."""
    return clamp(level) * 10 + (ai_priority if ai_priority in (1, 2, 3) else 0)


def mark(level) -> str:
    """Pastille de la liste : ❗ haute, ⬇ basse, rien si normale."""
    return "❗ " if level == HIGH else "⬇ " if level == LOW else ""
