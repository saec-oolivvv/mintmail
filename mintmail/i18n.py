"""Traduction de l'interface. La langue SOURCE du code est le français : tr("texte français") renvoie la traduction si un catalogue
existe pour la langue choisie, sinon le texte français (aucune régression possible en français).

Catalogues : mintmail/locale/<langue>.json = {"texte français": "traduction"}. Les marqueurs de format (%s, %d, %(nom)s) et les balises
(<b>…</b>) doivent être identiques à la source : vérifié par les tests (tests/test_i18n.py) et par tools/i18n_check.py.
La langue est fixée au démarrage (réglage « Langue de l'interface », ou variable MINTMAIL_LANG, ou langue du système) : changer de langue
demande de relancer MintMail.
"""
import json
import locale
import os
import re
from pathlib import Path
from typing import Dict, List, Optional

LOCALE_DIR = Path(__file__).resolve().parent / "locale"
NAMES = {"fr": "Français", "en": "English", "nl": "Nederlands", "de": "Deutsch", "es": "Español"}   # affichés dans leur langue

_lang = "fr"
_catalog: Dict[str, str] = {}


def available() -> List[str]:
    """Langues utilisables : le français (source) + celles qui ont un catalogue."""
    found = {p.stem for p in LOCALE_DIR.glob("*.json")} if LOCALE_DIR.is_dir() else set()
    return ["fr"] + sorted(l for l in found if l != "fr")


def system_language() -> str:
    for var in ("LC_ALL", "LC_MESSAGES", "LANGUAGE", "LANG"):
        v = (os.environ.get(var) or "").split(":")[0]
        if v and v not in ("C", "POSIX"):
            return v.replace("-", "_").split("_")[0].split(".")[0].lower()
    try:
        return (locale.getdefaultlocale()[0] or "fr").split("_")[0].lower()
    except Exception:
        return "fr"


def resolve(setting: Optional[str] = "auto") -> str:
    """Langue effective : variable MINTMAIL_LANG > réglage > langue du système. Langue sans catalogue : l'anglais s'il existe
    (langue universelle de repli), sinon le français."""
    av = available()
    want = (os.environ.get("MINTMAIL_LANG") or setting or "auto").lower()
    if want == "auto":
        want = system_language()
    if want in av:
        return want
    return "en" if "en" in av and want != "fr" else "fr"


def set_language(code: str) -> str:
    """Charge le catalogue ; retourne la langue réellement active."""
    global _lang, _catalog
    code = code if code in available() else "fr"
    cat: Dict[str, str] = {}
    if code != "fr":
        try:
            with open(LOCALE_DIR / (code + ".json"), encoding="utf-8") as f:
                data = json.load(f)
            cat = {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str) and v}
        except (OSError, ValueError):
            code = "fr"
    _lang, _catalog = code, cat
    return _lang


def current() -> str:
    return _lang


def tr(text: str) -> str:
    """Texte traduit (ou le texte d'origine, en français, s'il n'y a pas de traduction)."""
    return _catalog.get(text, text)


def init_from_config(config_value: str = "auto") -> str:
    return set_language(resolve(config_value))


_CONV = re.compile(r"%(?:\([^)]*\))?[#0\- +]*(?:\d+|\*)?(?:\.\d+)?[sdrfxX]")
_TAG = re.compile(r"</?(\w+)")


def check_entry(source: str, translation: str) -> list:
    """Problèmes d'une traduction (liste vide = correcte) : vide, marqueurs de format (%s %d %(x)s : même suite de types), balises HTML
    (mêmes noms, même ordre), espaces ou retour à la ligne en début / fin. Utilisé par les tests et par tools/translate_catalog.py."""
    out = []
    if not translation or not translation.strip():
        return ["traduction vide"]
    if [m[-1] for m in _CONV.findall(source)] != [m[-1] for m in _CONV.findall(translation)] or \
            re.findall(r"%\(\w+\)", source) != re.findall(r"%\(\w+\)", translation):
        out.append("marqueurs de format différents")
    if _TAG.findall(source) != _TAG.findall(translation):
        out.append("balises différentes")
    if source.startswith((" ", "\n")) != translation.startswith((" ", "\n")) or source.endswith((" ", "\n")) != translation.endswith((" ", "\n")):
        out.append("espaces ou retours à la ligne de début / fin différents")
    return out
