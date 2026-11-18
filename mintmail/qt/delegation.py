"""Attribuer et partager un message (sans Qt) : « Attribuer à… » transfère le message à quelqu'un, crée la tâche suivie chez vous (échéance) et une relance
si la personne ne répond pas ; « Partager… » transfère pour information. Rien n'est envoyé sans que vous validiez la fenêtre de rédaction."""
import datetime
import time
from typing import Dict, Optional, Tuple

from .. import tasks as tk
from ..i18n import tr
from ..util import normalize_subject
from . import composing as C
from . import organizer as O


def clean_recipients(text) -> str:
    """Adresses valides séparées par des virgules ('' si une seule est invalide)."""
    parts = [a.strip() for a in (text or "").replace(";", ",").split(",") if a.strip()]
    return ", ".join(parts) if parts and C.valid_recipients(", ".join(parts)) else ""


def intro_text(note="", due: Optional[datetime.date] = None, assign=True) -> str:
    lines = [tr("Peux-tu t'en occuper ?") if assign else tr("Pour information :")]
    if note.strip():
        lines.append(note.strip())
    if due:
        lines.append(tr("Échéance : %s") % due.strftime("%d/%m/%Y"))
    return "\n\n".join(lines)


def assign(config, msg, assignee, note="", due_text="", follow_days=3, now=None) -> Tuple[Optional[dict], str]:
    """Enregistre l'attribution : tâche « Attribué à X : objet » (avec échéance) + relance si pas de réponse. Retourne (tâche, message)."""
    who = clean_recipients(assignee)
    if not who:
        return None, tr("Adresse e-mail invalide.")
    now = now if now is not None else time.time()
    due = tk.parse_due(due_text) if (due_text or "").strip() else None
    text = (tr("Attribué à %s : %s") % (who, msg.subject or tr("(Sans objet)")))[:200]
    task = O.task_add(config, text, msg, due=due)
    if task is None:
        return None, tr("Ce message est déjà attribué à cette personne.")
    task["assignee"], task["note"] = who, note.strip()[:500]
    if follow_days and follow_days > 0:
        config["followups"] = list(config.get("followups") or []) + [
            {"id": "%s:assign:%s" % (msg.id, who), "at": now + follow_days * 86400, "subject": msg.subject, "date": now, "to": who}]
    config.save()
    return task, tr("Attribué à %s%s") % (who, (tr(" — échéance ") + task["due"]) if task["due"] else "")


def compose_args(config, accounts, msg, who, note="", due=None, default_account="", assign_=True) -> Dict:
    """Fenêtre de rédaction prête : transfert du message au destinataire avec un mot d'introduction (à relire avant d'envoyer)."""
    kw = C.forward_args(msg, default_account)
    kw["to"] = who
    kw["ai_suggested_text"] = intro_text(note, due, assign_)
    return kw


def assigned_open(config):
    return [t for t in O.tasks_all(config) if t.get("assignee") and not t.get("done")]


def subject_key(msg) -> str:
    return normalize_subject(msg.subject or "").lower()
