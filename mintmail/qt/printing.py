"""Impression d'un message : page HTML simple (en-têtes + corps assaini, aucune image distante) pour l'imprimante ou un fichier PDF.
Module SANS Qt (la mise en page par Qt se fait dans qt/window.py)."""
import html as _html
import time

from ..i18n import tr
from ..htmlsafe import sanitize
from ..util import text_to_html


def _addr(s):
    return _html.escape(s or "")


def printable_html(msg) -> str:
    """Document imprimable : objet, expéditeur, destinataires, date, pièces jointes, puis le corps (texte noir sur blanc)."""
    when = time.strftime("%d/%m/%Y %H:%M", time.localtime(msg.date)) if msg.date else ""
    rows = [(tr("De"), "%s &lt;%s&gt;" % (_addr(msg.sender_name), _addr(msg.sender_email)) if msg.sender_name else _addr(msg.sender_email)),
            (tr("À"), _addr(msg.to))]
    if getattr(msg, "cc", ""):
        rows.append((tr("Copie"), _addr(msg.cc)))
    rows.append((tr("Envoyé le"), _addr(when)))
    atts = [a.get("filename", "") for a in (msg.attachments or [])]
    if atts:
        rows.append((tr("Pièces jointes"), _addr(", ".join(atts))))
    head = "".join("<tr><td style='color:#555;padding-right:12px' valign='top'><b>%s</b></td><td>%s</td></tr>" % (k, v) for k, v in rows if v)
    body = sanitize(msg.html, keep_style=False, allow_remote_images=False) if msg.html else text_to_html(msg.text or "")
    return ("<html><body style='font-family:sans-serif;font-size:11pt;color:#000'><h2 style='margin:0 0 8px 0'>%s</h2>"
            "<table cellspacing='0' cellpadding='2'>%s</table><hr/>%s</body></html>" % (_addr(msg.subject or "(Sans objet)"), head, body))
