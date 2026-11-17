"""Détection locale (sans IA, sans réseau) des messages qui ressemblent à de l'hameçonnage, pour proposer à l'ouverture de les mettre en spam.
Module SANS Qt. Les motifs sont volontairement prudents : mieux vaut une question inutile qu'un message piégé qui passe sans avertissement."""
import re
from typing import Dict, List, Optional

from .ai_engine import local_suspicious
from .i18n import tr

# marque -> fragments de domaine légitimes ; un nom d'expéditeur qui porte la marque avec un autre domaine est suspect
BRANDS = {
    "paypal": ("paypal.",), "apple": ("apple.", "icloud."), "microsoft": ("microsoft.", "outlook.", "office.", "live."),
    "amazon": ("amazon.",), "netflix": ("netflix.",), "google": ("google.", "gmail."), "facebook": ("facebook", "meta."),
    "dhl": ("dhl.",), "fedex": ("fedex.",), "bpost": ("bpost.",), "proximus": ("proximus.",), "itsme": ("itsme.",),
    "belfius": ("belfius.",), "bnp": ("bnpparibas", "bnpparibasfortis"), "kbc": ("kbc.",), "argenta": ("argenta.",),
    "docusign": ("docusign.",), "linkedin": ("linkedin.",), "instagram": ("instagram.", "facebookmail."),
}
ANCHOR = re.compile(r'<a\b[^>]*?href\s*=\s*["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.I | re.S)
DOMAIN_TEXT = re.compile(r"((?:https?://)?(?:[a-z0-9-]+\.)+[a-z]{2,})(?:/\S*)?", re.I)
SHORTENERS = ("bit.ly", "tinyurl.com", "t.co", "goo.gl", "ow.ly", "is.gd", "cutt.ly", "rebrand.ly")


def _host(url: str) -> str:
    m = re.match(r"(?i)^(?:https?://)?([^/:?#]+)", (url or "").strip())
    return (m.group(1).lower() if m else "")


def _base(host: str) -> str:
    parts = host.split(".")
    return ".".join(parts[-3:]) if len(parts) >= 3 and parts[-2] in ("co", "com", "org", "gov") else ".".join(parts[-2:])


def reasons(msg, analysis: Optional[Dict] = None) -> List[str]:
    """Motifs (texte court) pour lesquels ce message paraît suspect ; liste vide si rien à signaler."""
    out: List[str] = []
    if analysis and analysis.get("suspicious") and not analysis.get("local"):
        out.append((analysis.get("why") or tr("l'analyse IA le juge suspect"))[:160])
    dom = (msg.sender_email or "").lower().split("@")[-1]
    name = (msg.sender_name or "").lower()
    m = re.search(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)", name)
    if m and m.group(1) != dom and _base(m.group(1)) != _base(dom):
        out.append(tr("le nom affiché contient une autre adresse (%s) que celle de l'expéditeur") % m.group(1))
    for brand, doms in BRANDS.items():
        if re.search(r"\b%s\b" % re.escape(brand), name) and dom and not any(d in dom for d in doms):
            out.append(tr("se présente comme « %s » mais écrit depuis %s") % (brand, dom))
            break
    html = msg.html or ""
    for href, label in ANCHOR.findall(html):
        shown = DOMAIN_TEXT.search(re.sub(r"<[^>]+>", "", label))
        real = _host(href)
        if shown and real and _base(_host(shown.group(1))) != _base(real):
            out.append(tr("un lien affiche %s mais mène vers %s") % (_base(_host(shown.group(1))), real))
            break
    if any(("://" + h + "/") in html.lower() for h in SHORTENERS):
        out.append(tr("contient un lien raccourci qui masque sa destination"))
    if local_suspicious(msg):
        out.append(tr("le texte ressemble à une arnaque (urgence, compte, paiement…)"))
    return out[:3]


def should_ask(msg, analysis: Optional[Dict], trusted: bool, known_sender: bool) -> List[str]:
    """Motifs à présenter à l'ouverture d'un message de la boîte de réception ; vide si on ne pose pas la question
    (déjà jugé sûr, expéditeur du carnet d'adresses, ou autre dossier que la boîte de réception)."""
    if trusted or known_sender or msg is None or msg.folder != "inbox":
        return []
    return reasons(msg, analysis)
