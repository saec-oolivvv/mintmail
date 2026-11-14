"""Carte IA du lecteur Qt (logique pure) : résumé, points, tâches, alerte d'hameçonnage, suggestion « pas du spam », traduction, question, réponse.
Même comportement que ai_features.py / reader.py de la version GTK."""
from typing import Dict, Optional, Tuple

from ..ai_engine import local_analysis
from ..i18n import tr
from ..util import normalize_subject
from . import assistant as AS

QUICK_REPLIES = [tr("Merci !"), tr("OK, bien reçu 👍"), tr("Je regarde ça et je reviens vers vous."), tr("Parfait, à bientôt.")]


def state(engine, msg) -> Tuple[str, Optional[Dict]]:
    """Que montrer à l'ouverture d'un message : ("ready", analyse) en cache, ("cta", analyse locale) si l'IA n'est pas configurée,
    ("idle", None) si l'analyse automatique est coupée, sinon ("load", None) : il faut lancer fetch() (en fond)."""
    hit = engine.cache.ai_get(msg.id, "analysis")
    if hit:
        return "ready", hit
    ai = AS.ai_engine(engine)
    if not ai.enabled():
        return "cta", local_analysis(msg, ai.lang)
    if not engine.config.get("ai_auto", True):
        return "idle", None
    return "load", None


def fetch(engine, msg, force=False) -> Dict:
    ai = AS.ai_engine(engine)
    ai.folder_names = AS.folder_paths(engine, free_only=True)
    return ai.analyze(msg, force=force)


def title(res) -> str:
    prio = {3: " · URGENT", 1: tr(" · peu important")}.get(res.get("priority"), "")
    return tr("✨ RÉSUMÉ%s%s") % (" (local)" if res.get("local") else "", prio)


def warning(res) -> str:
    if not res.get("suspicious"):
        return ""
    return tr("⚠ Message suspect (hameçonnage possible)%s. Ne cliquez sur aucun lien.") % (" : " + res["why"] if res.get("why") else "")


def spam_suggestion(msg, res):
    """Dans le Spam, l'IA juge le message légitime : (texte, [(libellé, action, charge)]) ou None."""
    if msg is None or msg.folder != "spam" or res.get("suspicious") or res.get("local") or res.get("error"):
        return None
    btns = [(tr("✔ Ce n'est pas du spam"), "not_spam", "")]
    if res.get("folder"):
        btns.append((tr("✔ Pas du spam, ranger dans « %s »") % res["folder"], "not_spam_file", res["folder"]))
    return tr("✨ Ce message semble légitime : il n'a probablement pas sa place dans le Spam."), btns


def translate(engine, msg) -> str:
    return AS.ai_engine(engine).translate_message(msg)


def ask(engine, msg, question) -> str:
    return AS.ai_engine(engine).ask(msg, question)


def draft(engine, msg, idea=None, limit=1500) -> str:
    """Texte de réponse rédigé par l'IA (réseau) ; à relire dans le composeur avant envoi."""
    ai = AS.ai_engine(engine)
    return ai.write_from_prompt(idea or tr("Réponds de façon appropriée à ce message."), "Re: " + normalize_subject(msg.subject),
                                msg.sender_email, context=ai._msg_block(msg, limit))
