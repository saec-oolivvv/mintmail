"""Détection locale (sans réseau, sans IA) de la langue d'un texte, pour proposer de traduire un message reçu ou de répondre dans la langue
de l'expéditeur. Méthode : fréquence de mots courants propres à chaque langue. Prudente : sans réponse nette, retourne None.
Module SANS Qt, testable partout."""
import re
from typing import Optional, Tuple

from .i18n import tr

WORDS = {
    "fr": "le la les des une un du de et est pour que qui dans pas sur avec vous nous votre vos ce cette sont mais ou où au aux en ne je il elle "  # i18n: skip
          "merci bonjour cordialement très être avoir fait comme plus par ont ces ses leur".split(),
    "en": "the and is are for that this with you your not have has was were will would from they their what which can but all our hello thanks "  # i18n: skip
          "regards please been about when there into".split(),
    "nl": "de het een en van is dat niet te zijn voor met op aan ook als maar bij naar dit deze wij u uw hebben wordt heeft hallo bedankt groeten "  # i18n: skip
          "alstublieft kunnen graag".split(),
    "de": "der die das und ist nicht ein eine für mit auf von zu den dem des sie wir ihr ihre ich sind wird haben auch bitte danke hallo "  # i18n: skip
          "freundliche grüße oder aber wie nach bei".split(),
    "es": "el la los las un una y es de que en para con por no se su sus del al como más pero muy hola gracias saludos usted nosotros están "  # i18n: skip
          "tiene este esta".split(),
    "it": "il lo la gli le un una e è di che per con non si del della dei sono ma come più molto ciao grazie saluti questo questa nostro "  # i18n: skip
          "vostro anche".split(),
    "pt": "o a os as um uma e é de que para com não se do da dos das em por mas como mais muito olá obrigado cumprimentos você nós este esta "  # i18n: skip
          "também".split(),
}
_SETS = {k: frozenset(v) for k, v in WORDS.items()}
_TOKEN = re.compile(r"[^\W\d_]+", re.UNICODE)


def detect(text: str, min_words: int = 12) -> Optional[Tuple[str, float]]:
    """(code de langue, confiance 0..1) ou None si le texte est trop court ou ambigu."""
    tokens = [t.lower() for t in _TOKEN.findall((text or "")[:4000])]
    if len(tokens) < min_words:
        return None
    scores = {k: sum(1 for t in tokens if t in s) for k, s in _SETS.items()}
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    (best, b), (_second, s2) = ranked[0], ranked[1]
    hits = b / len(tokens)
    if b < 4 or hits < 0.12 or b < s2 * 1.4:
        return None
    return best, round(min(1.0, hits * 3) * (1 - s2 / b * 0.5), 2)


def language_of(msg, min_words: int = 12) -> Optional[str]:
    """Langue d'un message (objet + corps hors citations) ; None si incertaine."""
    text = "%s\n%s" % (getattr(msg, "subject", ""), getattr(msg, "text", "") or re.sub(r"<[^>]+>", " ", getattr(msg, "html", "") or "") or getattr(msg, "snippet", ""))
    text = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith(">"))
    r = detect(text, min_words)
    return r[0] if r else None


def name(code: str) -> str:
    names = {"fr": tr("français"), "en": tr("anglais"), "nl": tr("néerlandais"), "de": tr("allemand"), "es": tr("espagnol"),
             "it": tr("italien"), "pt": tr("portugais")}
    return names.get(code, code)
