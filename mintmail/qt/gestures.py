"""Gestes de balayage (swipe) de la liste des messages Qt : règles pures, sans Qt — mêmes réglages, seuils et actions que la version GTK."""
from typing import Dict, Optional, Tuple

from ..i18n import tr

# action → (libellé, couleur de fond, glyphe)
SWIPE_ACTIONS: Dict[str, Tuple[str, str, str]] = {
    "archive": (tr("Archiver"), "#16a34a", "🗄"),
    "trash": (tr("Supprimer"), "#dc2626", "🗑"),
    "snooze": (tr("Reporter à demain"), "#ea580c", "⏰"),
    "read": (tr("Lu / non lu"), "#2563eb", "✉"),
    "star": (tr("Favori"), "#ca8a04", "★"),
    "pin": (tr("Épingler"), "#7c3aed", "📌"),
    "spam": ("Spam", "#6b7280", "⚠"),
    "block": (tr("Bloquer l'expéditeur"), "#b91c1c", "⛔"),
    "none": (tr("Aucune action"), "#6b7280", ""),
}
LAYOUTS = [("columns", tr("Colonnes : liste | lecture")), ("bottom", tr("Lecture en bas")), ("list", tr("Liste seule (lecture plein écran)"))]
DEFAULT_SWIPE = {"right": "archive", "right_long": "trash", "left": "snooze", "left_long": "read"}
SWIPE_SHORT, SWIPE_LONG = 90, 230
WHEEL_GAIN = 1.0                                       # pixels de glissement par unité de défilement horizontal du pavé tactile


def settings(config) -> Dict[str, str]:
    """Actions configurées (valeurs inconnues ou absentes → réglage par défaut)."""
    out = dict(DEFAULT_SWIPE)
    for k, v in (config.get("swipe") or {}).items():
        if k in out and v in SWIPE_ACTIONS:
            out[k] = v
    return out


def pick(dx: float, cfg: Dict[str, str], invert: bool = False, wheel: bool = False) -> Tuple[Optional[str], int]:
    """Action déclenchée par un glissement de dx pixels : (action ou None, niveau 0 = rien, 1 = court, 2 = long).
    `invert` ne s'applique qu'au pavé tactile (le défilement naturel va dans l'autre sens)."""
    if wheel and invert:
        dx = -dx
    mag = abs(dx)
    if mag < SWIPE_SHORT:
        return None, 0
    side = "right" if dx > 0 else "left"
    level = 2 if mag >= SWIPE_LONG else 1
    act = cfg.get(side + ("_long" if level == 2 else ""), "none")
    return (None, 0) if act == "none" else (act, level)


def effect(act: str, msg, now_tomorrow: float) -> Dict:
    """Ce que l'action change pour ce message : {"move": destination} | {"flag": (champ, valeur)} | {"snooze": instant} | {"block": adresse}."""
    if act in ("archive", "trash", "spam"):
        return {"move": act}
    if act == "read":
        return {"flag": ("unread", not msg.unread)}
    if act == "star":
        return {"flag": ("starred", not msg.starred)}
    if act == "pin":
        return {"flag": ("pinned", not msg.pinned)}
    if act == "snooze":
        return {"snooze": now_tomorrow}
    if act == "block":
        return {"block": msg.sender_email.lower()}
    return {}
