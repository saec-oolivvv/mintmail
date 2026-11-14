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


def signature_html(account, ident) -> str:
    sig = (ident or {}).get("signature_html") or (account.get("signature_html", "") if account else "")
    return '<div id="sig">-- <br>%s</div>' % sig if sig.strip() else ""


def swap_signature(body: str, new_sig: str) -> str:
    """Change de signature quand on change d'expéditeur, sans toucher au reste du message."""
    if '<div id="sig">' in body:
        return re.sub(r'<div id="sig">.*?</div>', lambda m: new_sig, body, count=1, flags=re.S)
    return body + new_sig


def initial_content(body_html, quote_html, signature, raw=False, ai_text="") -> str:
    if raw:
        return body_html
    ai = "<div><br></div><div id='ai-text'>%s</div>" % text_to_html(ai_text) if ai_text else ""
    return body_html + ai + "<div><br></div>" + signature + quote_html


def quote_html(msg) -> str:
    orig = sanitize_html(msg.html) if msg.html else text_to_html(msg.text)
    return tr('<div id="qt"><br><div>Le %s, %s a écrit :</div><blockquote>%s</blockquote></div>') % (
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
                quote_html='<div id="qt">' + head + (sanitize_html(msg.html) if msg.html else text_to_html(msg.text)) + "</div>",
                attachments=[a["path"] for a in msg.attachments])


def draft_args(msg) -> Dict:
    return dict(account_id=msg.account, to=msg.to, cc=msg.cc, subject=msg.subject, body_html=sanitize_html(msg.html), raw=True,
                in_reply_to=msg.message_id, references=msg.references, attachments=[a["path"] for a in msg.attachments], draft_id=msg.id)


def valid_recipients(to, cc="", bcc="") -> bool:
    for field in (to, cc, bcc):
        if any(not EMAIL_RE.match(a) for a in split_addresses(field)):
            return False
    return bool(split_addresses(to))


def build_outgoing(account, ident, to, cc, bcc, subject, body, attachments, in_reply_to="", references="") -> Outgoing:
    return Outgoing(account=account["id"], to=to.strip(), cc=cc.strip(), bcc=bcc.strip(),
                    from_email=ident["email"] if ident else "", from_name=ident.get("name", "") if ident else "",
                    subject=subject.strip() or "(Sans objet)", html=body, attachments=list(attachments),
                    in_reply_to=in_reply_to, references=references)


def save_draft(cache, account, draft_id, to, cc, subject, body, attachments, in_reply_to="", references="") -> str:
    """Enregistre (ou met à jour) le brouillon dans le cache ; retourne son identifiant."""
    import os
    from ..util import html_to_text
    did = draft_id or "draft-%s" % uuid.uuid4().hex[:10]
    text = html_to_text(body)
    cache.upsert(Message(
        id=did, account=account["id"], folder="drafts", uid=0, sender_name=account.get("name", ""), sender_email=account["email"],
        to=to, cc=cc, subject=subject or "(Sans objet)", date=time.time(), snippet=text[:150], text=text, html=body, unread=False,
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
