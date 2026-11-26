"""Relance d'un message envoyé resté sans réponse (module pur, sans Qt)."""
import html
import time
from typing import Iterable, Optional

from .i18n import tr
from .util import normalize_subject, split_addresses


def waiting_days(msg, members: Iterable, mine: Iterable[str] = (), now: Optional[float] = None) -> Optional[int]:
    """Jours écoulés depuis l'envoi si personne n'a répondu dans la conversation ; None si le message n'est pas un envoyé ou si une réponse existe.
    Une réponse = un message plus récent de la même conversation (ou du même objet) écrit par quelqu'un d'autre que moi."""
    if getattr(msg, "folder", "") != "sent" or not getattr(msg, "date", 0):
        return None
    me = {a.lower() for a in mine if a} | {(getattr(msg, "sender_email", "") or "").lower()}
    subj = normalize_subject(msg.subject or "").lower()
    for m in members:
        if m.id == msg.id or m.date <= msg.date or getattr(m, "folder", "") in ("trash", "spam", "drafts"):
            continue
        if (m.sender_email or "").lower() in me:
            continue
        if getattr(m, "thread_id", "") == getattr(msg, "thread_id", "x") or normalize_subject(m.subject or "").lower() == subj:
            return None
    return max(0, int(((now or time.time()) - msg.date) // 86400))


def waiting_text(days: int) -> str:
    if days <= 0:
        return tr("envoyé aujourd'hui, pas encore de réponse")
    return tr("aucune réponse depuis %d jour(s)") % days


def intro_html(days: int) -> str:
    """Court texte de relance, courtois, à adapter."""
    return "<p>%s</p><p>%s</p><p>%s</p>" % (
        html.escape(tr("Bonjour,")),
        html.escape(tr("Je me permets de revenir vers vous au sujet de mon message ci-dessous, resté sans réponse à ce jour. Avez-vous eu l'occasion d'y jeter un œil ?")),
        html.escape(tr("Merci d'avance pour votre retour.")))


def args(msg, quote: str, days: int, default_account: str = "") -> dict:
    """Paramètres de la fenêtre de rédaction : mêmes destinataires, même fil, objet « Re : … »."""
    return dict(account_id=msg.account or default_account, to=msg.to, cc=getattr(msg, "cc", "") or "",
                subject="Re: " + normalize_subject(msg.subject or ""), body_html=intro_html(days), quote_html=quote,
                in_reply_to=msg.message_id, references=msg.references)
