"""Rédaction SANS Qt : citation, réponse / transfert / brouillon, signature, identités (alias), validation, message à envoyer.
Mêmes règles que l'interface GTK (compose.py, window.py, extras.py), testées sur le moteur seul."""
import datetime
import html
import re
import time
import uuid
from typing import Dict, List, Optional

from ..i18n import tr
from ..models import Message, Outgoing
from . import sigimages as SI
from ..util import format_full, normalize_subject, split_addresses, sanitize_html, text_to_html

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def identities(config) -> List[dict]:
    return config.get("identities", []) or []


def addressed_identity(config, msg) -> Optional[dict]:
    """Alias auquel le message a été adressé, ou None."""
    to = ((msg.to or "") + " " + (msg.cc or "")).lower()
    for ident in identities(config):
        if ident.get("account") == msg.account and ident["email"].lower() in to:
            return ident
    return None


def from_choices(config, accounts) -> List[tuple]:
    """[(identifiant, libellé)] : comptes puis leurs alias (même compte d'envoi, adresse et signature propres)."""
    out = []
    for a in accounts:
        out.append((a["id"], "%s <%s>" % (a.get("name") or a["email"], a["email"])))
        for i in identities(config):
            if i.get("account") == a["id"]:
                out.append(("ident:" + i["id"], "%s <%s>  · alias" % (i.get("name") or i["email"], i["email"])))
    return out


def resolve_from(config, accounts, choice):
    """(compte, alias ou None) pour un identifiant du sélecteur « De »."""
    ident = next((i for i in identities(config) if "ident:" + i["id"] == choice), None) if (choice or "").startswith("ident:") else None
    aid = ident["account"] if ident else choice
    return next((a for a in accounts if a["id"] == aid), accounts[0] if accounts else None), ident


SIG_MARK = "\u2063"        # séparateur invisible : encadre la signature (Qt perd les attributs id des <div> en réexportant le HTML, pas ce caractère)
QUOTE_MARK = "\u2064"      # idem : début de la citation


def signature_html(account, ident) -> str:
    sig = (ident or {}).get("signature_html") or (account.get("signature_html", "") if account else "")
    return '<div id="sig">%s-- <br>%s%s</div>' % (SIG_MARK, sig, SIG_MARK) if sig.strip() else ""


def restore_signature(body: str, account, ident) -> str:
    """Remet la signature D'ORIGINE à la place de sa version passée par l'éditeur Qt (qui perd le SVG, les coins arrondis, les largeurs…).
    La signature se modifie dans les Réglages, pas message par message ; sans marqueurs (signature effacée), rien n'est ajouté."""
    inner = re.search(SIG_MARK + ".*?" + SIG_MARK, signature_html(account, ident), re.S)
    found = re.search(SIG_MARK + ".*?" + SIG_MARK, body or "", re.S)
    if not inner or not found:
        return body
    return body[:found.start()] + inner.group(0) + body[found.end():]


def swap_signature(body: str, new_sig: str) -> str:
    """Change de signature quand on change d'expéditeur, sans toucher au reste du message (ni dupliquer la signature)."""
    span = re.compile(SIG_MARK + ".*?" + SIG_MARK, re.S)
    inner = span.search(new_sig or "")
    if span.search(body):
        return span.sub(lambda m: inner.group(0) if inner else "", body, count=1)
    if '<div id="sig">' in body:
        return re.sub(r'<div id="sig">.*?</div>', lambda m: new_sig, body, count=1, flags=re.S)
    return body + new_sig


def clean_for_send(html_text: str) -> str:
    """Retire les marqueurs invisibles avant l'envoi ou l'enregistrement."""
    return (html_text or "").replace(SIG_MARK, "").replace(QUOTE_MARK, "")


def initial_content(body_html, quote_html, signature, raw=False, ai_text="") -> str:
    if raw:
        return body_html
    ai = "<div><br></div><div id='ai-text'>%s</div>" % text_to_html(ai_text) if ai_text else ""
    return body_html + ai + "<div><br></div>" + signature + quote_html


def quote_html(msg) -> str:
    orig = sanitize_html(msg.html) if msg.html else text_to_html(msg.text)
    return tr('<div id="qt"><br><div>Le %s, %s a écrit :</div><blockquote>%s</blockquote></div>').replace('<div id="qt">', '<div id="qt">' + QUOTE_MARK, 1) % (
        format_full(msg.date), html.escape(msg.display_sender), orig)


def reply_args(config, accounts, msg, all_=False, default_account="") -> Dict:
    """Paramètres de la fenêtre de rédaction pour répondre (à l'expéditeur ou à tous)."""
    to = msg.to if msg.folder == "sent" else (msg.reply_to or msg.sender_email)
    cc = ""
    if all_:
        mine = {a["email"].lower() for a in accounts} | {i["email"].lower() for i in identities(config)}
        others = [a for a in split_addresses(msg.to) + split_addresses(msg.cc) if a.lower() not in mine and a.lower() != msg.sender_email.lower()]
        cc = ", ".join(dict.fromkeys(others))
    ident = addressed_identity(config, msg)
    return dict(account_id=("ident:" + ident["id"]) if ident else default_account, to=to, cc=cc,
                subject="Re: " + normalize_subject(msg.subject), quote_html=quote_html(msg),
                in_reply_to=msg.message_id, references=msg.references)


def forward_args(msg, default_account="") -> Dict:
    head = (tr("<br>---------- Message transféré ----------<br>De : %s &lt;%s&gt;<br>Date : %s<br>Objet : %s<br>À : %s<br>")
            % (html.escape(msg.sender_name), html.escape(msg.sender_email), format_full(msg.date), html.escape(msg.subject), html.escape(msg.to)))
    return dict(account_id=default_account, subject="Fwd: " + normalize_subject(msg.subject),
                quote_html='<div id="qt">' + QUOTE_MARK + head + (sanitize_html(msg.html) if msg.html else text_to_html(msg.text)) + "</div>",
                attachments=[a["path"] for a in msg.attachments])


def draft_args(msg) -> Dict:
    return dict(account_id=msg.account, to=msg.to, cc=msg.cc, subject=msg.subject, body_html=sanitize_html(SI.to_display(msg.html)), raw=True,
                in_reply_to=msg.message_id, references=msg.references, attachments=[a["path"] for a in msg.attachments], draft_id=msg.id)


def valid_recipients(to, cc="", bcc="") -> bool:
    for field in (to, cc, bcc):
        if any(not EMAIL_RE.match(a) for a in split_addresses(field)):
            return False
    return bool(split_addresses(to))


def build_outgoing(account, ident, to, cc, bcc, subject, body, attachments, in_reply_to="", references="") -> Outgoing:
    html_out, inline = SI.to_mail(clean_for_send(restore_signature(body, account, ident)))    # logos SVG / images « data: » → images jointes en ligne
    return Outgoing(account=account["id"], to=to.strip(), cc=cc.strip(), bcc=bcc.strip(),
                    from_email=ident["email"] if ident else "", from_name=ident.get("name", "") if ident else "",
                    subject=subject.strip() or "(Sans objet)", html=html_out, attachments=list(attachments),
                    in_reply_to=in_reply_to, references=references, inline=inline)


def save_draft(cache, account, draft_id, to, cc, subject, body, attachments, in_reply_to="", references="") -> str:
    """Enregistre (ou met à jour) le brouillon dans le cache ; retourne son identifiant."""
    import os
    from ..util import html_to_text
    did = draft_id or "draft-%s" % uuid.uuid4().hex[:10]
    body = clean_for_send(body)
    text = html_to_text(body)
    cache.upsert(Message(
        id=did, account=account["id"], folder="drafts", uid=0, sender_name=account.get("name", ""), sender_email=account["email"],
        to=to, cc=cc, subject=subject or "(Sans objet)", date=time.time(), snippet=text[:150], text=text, html=clean_for_send(body), unread=False,
        attachments=[{"filename": os.path.basename(p), "path": p, "size": os.path.getsize(p) if os.path.exists(p) else 0, "mime": ""} for p in attachments],
        message_id=in_reply_to, references=references))
    return did


def at(days, hour) -> float:
    d = datetime.datetime.now() + datetime.timedelta(days=days)
    return d.replace(hour=hour, minute=0, second=0, microsecond=0).timestamp()


def next_monday() -> float:
    return at((7 - datetime.datetime.now().weekday()) % 7 or 7, 8)


def body_of_qt_html(doc_html: str) -> str:
    """Corps d'un document HTML produit par Qt (QTextEdit.toHtml) : contenu de <body> sans les styles internes de Qt."""
    m = re.search(r"<body[^>]*>(.*)</body>", doc_html, re.S | re.I)
    return (m.group(1) if m else doc_html).strip()


def quick_reply_outgoing(config, accounts, msg, text, default_account="") -> Outgoing:
    """« Réponse rapide » du lecteur : réponse immédiate à l'expéditeur, avec la signature du compte ou de l'alias qui a reçu le message."""
    acc = next((a for a in accounts if a["id"] == default_account), accounts[0])
    ident = addressed_identity(config, msg)
    sig = signature_html(acc, ident)
    body = text_to_html(text) + ("<br><br>" + clean_for_send(sig) if sig else "")
    body, inline = SI.to_mail(body)
    return Outgoing(account=acc["id"], to=(msg.reply_to or msg.sender_email), subject="Re: " + normalize_subject(msg.subject), html=body,
                    from_email=ident["email"] if ident else "", from_name=ident.get("name", "") if ident else "",
                    in_reply_to=msg.message_id, references=msg.references, inline=inline)
