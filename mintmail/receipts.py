"""Accusés de lecture (RFC 8098, « MDN ») : demander un accusé à l'envoi, reconnaître un accusé reçu (l'œil 👁 s'affiche sur le message
envoyé), répondre — ou non — à une demande reçue. Module SANS Qt.
Limite honnête : un accusé n'existe que si le logiciel du destinataire accepte de l'envoyer (Outlook et Thunderbird demandent à
l'utilisateur, Apple Mail aussi ; Gmail ne les envoie pas). Aucune image espion n'est utilisée : MintMail ne piste personne."""
import email
import email.utils
from email import policy
from email.message import EmailMessage
from typing import Optional, Tuple

from .i18n import tr

POLICIES = ("ask", "never", "always")          # réponse aux demandes reçues


def settings(config) -> dict:
    p = config.get("receipt_reply", "ask")
    return {"request": bool(config.get("receipt_request", False)), "reply": p if p in POLICIES else "ask",
            "notify": bool(config.get("receipt_notify", True))}


def requested_address(em) -> str:
    """Adresse demandée par Disposition-Notification-To (vide si pas de demande)."""
    raw = str(em.get("Disposition-Notification-To", "") or "")
    return email.utils.parseaddr(raw)[1].lower()


def original_id_of_receipt(em) -> str:
    """Message-ID du message d'origine si `em` est un accusé de lecture « displayed » ; sinon chaîne vide."""
    if em.get_content_type() != "multipart/report" or "disposition-notification" not in (em.get_param("report-type") or "").lower():
        return ""
    for part in em.walk():
        if part.get_content_type() == "message/disposition-notification":
            fields = {}
            for sub in part.get_payload():                          # le contenu est une suite d'en-têtes (un « message » par partie)
                for k, v in sub.items():
                    fields[k.lower()] = str(v)
            disp = fields.get("disposition", "").lower()
            if "displayed" in disp or not disp:
                return fields.get("original-message-id", "").strip()
    return ""


def build_mdn(original_msg_id: str, original_subject: str, to_addr: str, from_addr: str, from_name: str = "", domain: str = "") -> bytes:
    """Accusé de lecture à envoyer en réponse à une demande (RFC 3798 : multipart/report, partie message/disposition-notification)."""
    import os
    from email.header import Header
    boundary = "=-mdn-" + os.urandom(10).hex()
    subject = tr("Accusé de lecture : %s") % original_subject
    human = tr("Votre message « %s » a été affiché par son destinataire.") % original_subject
    fields = ("Reporting-UA: MintMail; MintMail\r\nFinal-Recipient: rfc822; %s\r\nOriginal-Message-ID: %s\r\n"  # i18n: skip
              "Disposition: manual-action/MDN-sent-manually; displayed\r\n" % (from_addr, original_msg_id))
    head = ("From: %s\r\nTo: %s\r\nSubject: %s\r\nDate: %s\r\nMessage-ID: %s\r\nAuto-Submitted: auto-replied\r\nMIME-Version: 1.0\r\n"  # i18n: skip
            'Content-Type: multipart/report; report-type=disposition-notification; boundary="%s"\r\n\r\n'
            % (email.utils.formataddr((str(Header(from_name, "utf-8")) if from_name else "", from_addr)), to_addr,
               Header(subject, "utf-8").encode(), email.utils.formatdate(localtime=True),
               email.utils.make_msgid(domain=domain or from_addr.split("@")[-1]), boundary))
    import base64
    body = ("--%s\r\nContent-Type: text/plain; charset=utf-8\r\nContent-Transfer-Encoding: base64\r\n\r\n%s\r\n"  # i18n: skip
            "--%s\r\nContent-Type: message/disposition-notification\r\n\r\n%s\r\n--%s--\r\n"
            % (boundary, base64.encodebytes(human.encode("utf-8")).decode().replace("\n", "\r\n").rstrip(), boundary, fields, boundary))
    return (head + body).encode("ascii")


def parse_receipt_fields(raw: bytes) -> Tuple[str, str]:
    """(message-id d'origine, expéditeur de l'accusé) pour un message brut ; ('', '') si ce n'est pas un accusé."""
    em = email.message_from_bytes(raw, policy=policy.default)
    return original_id_of_receipt(em), email.utils.parseaddr(str(em.get("From", "")))[1].lower()


def eye_title(info: Optional[dict]) -> str:
    """Infobulle de l'œil : qui a lu, et quand."""
    if not info:
        return ""
    import time
    when = time.strftime("%d/%m/%Y %H:%M", time.localtime(info.get("at", 0))) if info.get("at") else ""
    return tr("Lu par %s le %s") % (info.get("by") or "?", when)


def record_incoming(cache, msg):
    """Un accusé de lecture vient d'arriver : le retient sur le message envoyé correspondant et le marque lu.
    Retourne (message envoyé, lecteur) ou None."""
    if not getattr(msg, "receipt_for", ""):
        return None
    sent = cache.find_sent_by_message_id(msg.receipt_for)
    if sent is None:
        return None
    by = msg.display_sender
    cache.ai_set(sent.id, "receipt", {"at": msg.date or __import__("time").time(), "by": by, "email": msg.sender_email})
    cache.update_many([msg.id], unread=False)
    return sent, by


def read_ids(cache, ids) -> dict:
    """{id: {at, by}} des messages envoyés dont un accusé de lecture est arrivé (pour afficher l'œil)."""
    return cache.ai_kind("receipt", ids)
