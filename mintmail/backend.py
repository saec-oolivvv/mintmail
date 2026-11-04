"""Accès aux serveurs : IMAP/SMTP réels + backend de démonstration."""
import base64
import email
import imaplib
import mimetypes
import os
import re
import smtplib
import ssl
import time
import uuid
from email import policy
from email.message import EmailMessage
from email.utils import make_msgid, parsedate_to_datetime, parseaddr, formatdate

from .models import Message
from .store import DATA_DIR
from .util import html_to_text, split_addresses, text_to_html

PRESETS = {
    "Gmail (mot de passe d'application)": dict(imap_host="imap.gmail.com", imap_port=993, smtp_host="smtp.gmail.com", smtp_port=587),
    "Outlook / Microsoft 365": dict(imap_host="outlook.office365.com", imap_port=993, smtp_host="smtp.office365.com", smtp_port=587),
    "iCloud": dict(imap_host="imap.mail.me.com", imap_port=993, smtp_host="smtp.mail.me.com", smtp_port=587),
    "Yahoo": dict(imap_host="imap.mail.yahoo.com", imap_port=993, smtp_host="smtp.mail.yahoo.com", smtp_port=587),
    "Infomaniak": dict(imap_host="mail.infomaniak.com", imap_port=993, smtp_host="mail.infomaniak.com", smtp_port=587),
    "OVH": dict(imap_host="ssl0.ovh.net", imap_port=993, smtp_host="ssl0.ovh.net", smtp_port=587),
    "Autre (manuel)": dict(imap_host="", imap_port=993, smtp_host="", smtp_port=587),
}

LOGICAL = ["inbox", "sent", "drafts", "archive", "trash", "spam"]
SPECIAL = {"\\sent": "sent", "\\drafts": "drafts", "\\trash": "trash",
           "\\junk": "spam", "\\archive": "archive", "\\all": "archive"}
GUESS = {
    "sent": ["sent", "sent items", "sent mail", "envoyés", "éléments envoyés", "messages envoyés"],
    "drafts": ["drafts", "brouillons"],
    "trash": ["trash", "deleted items", "corbeille", "bin", "éléments supprimés"],
    "spam": ["spam", "junk", "junk email", "courrier indésirable", "indésirables"],
    "archive": ["archive", "archives", "all mail", "tous les messages"],
}


class BackendError(Exception):
    pass


def _q(name):
    return '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def classify(addr, em):
    a = (addr or "").lower()
    if em.get("List-Unsubscribe") or em.get("List-Id") or "newsletter" in a \
            or str(em.get("Precedence", "")).lower() == "bulk":
        return "news"
    if re.search(r"(no-?reply|do-?not-?reply|notification|alert|billing|mailer-daemon|updates@|support@)", a):
        return "notif"
    return "people"


def _safe(name):
    return re.sub(r"[^\w.\- ]", "_", name or "fichier")[:120] or "fichier"


def parse_message(raw, account, logical, real_folder, uid, flags):
    em = email.message_from_bytes(raw, policy=policy.default)
    name, addr = parseaddr(str(em.get("From", "")))
    subject = str(em.get("Subject", "") or "") or "(Sans objet)"
    try:
        ts = parsedate_to_datetime(str(em.get("Date"))).timestamp()
    except Exception:
        ts = time.time()
    html_body = text_body = ""
    try:
        p = em.get_body(preferencelist=("html",))
        if p is not None and p.get_content_type() == "text/html":
            html_body = p.get_content()
        p = em.get_body(preferencelist=("plain",))
        if p is not None and p.get_content_type() == "text/plain":
            text_body = p.get_content()
    except Exception:
        pass
    if not text_body and html_body:
        text_body = html_to_text(html_body)
    mid = "%s|%s|%d" % (account, real_folder, uid)
    atts = []
    for part in em.walk():
        if part.is_multipart():
            continue
        cid = (part.get("Content-ID") or "").strip("<> ")
        fname = part.get_filename()
        try:
            data = part.get_payload(decode=True) or b""
        except Exception:
            data = b""
        if cid and part.get_content_maintype() == "image" and html_body and ("cid:" + cid) in html_body:
            if len(data) < 2_000_000:
                uri = "data:%s;base64,%s" % (part.get_content_type(), base64.b64encode(data).decode())
                html_body = html_body.replace("cid:" + cid, uri)
            continue
        if fname or part.get_content_disposition() == "attachment":
            d = DATA_DIR / "attachments" / re.sub(r"\W", "_", mid)
            d.mkdir(parents=True, exist_ok=True)
            fname = _safe(fname or "pièce jointe" + (mimetypes.guess_extension(part.get_content_type()) or ""))
            path = d / fname
            try:
                path.write_bytes(data)
                atts.append({"filename": fname, "path": str(path), "size": len(data),
                             "mime": part.get_content_type()})
            except OSError:
                pass
    return Message(
        id=mid, account=account, folder=logical, real_folder=real_folder, uid=uid,
        sender_name=name, sender_email=addr, to=str(em.get("To", "") or ""),
        cc=str(em.get("Cc", "") or ""), reply_to=str(em.get("Reply-To", "") or ""),
        subject=subject, date=ts, snippet=re.sub(r"\s+", " ", text_body)[:160].strip(),
        text=text_body, html=html_body,
        unread=("\\seen" not in flags) and logical != "drafts",
        starred="\\flagged" in flags, category=classify(addr, em), attachments=atts,
        message_id=str(em.get("Message-ID", "") or ""), references=str(em.get("References", "") or ""),
        unsubscribe=str(em.get("List-Unsubscribe", "") or ""))


UID_RE = re.compile(rb"UID (\d+)")
FLAGS_RE = re.compile(rb"FLAGS \(([^)]*)\)")


def _flagset(b):
    m = FLAGS_RE.search(b or b"")
    return set(m.group(1).decode().lower().split()) if m else set()


class IMAPBackend:
    demo = False

    def __init__(self, account, password):
        self.acc, self.password = account, password
        self._folders_cache = None

    # -- connexion
    def _connect(self):
        a = self.acc
        try:
            if a.get("imap_ssl", True):
                imap = imaplib.IMAP4_SSL(a["imap_host"], int(a["imap_port"]),
                                         ssl_context=ssl.create_default_context(), timeout=30)
            else:
                imap = imaplib.IMAP4(a["imap_host"], int(a["imap_port"]), timeout=30)
                imap.starttls(ssl.create_default_context())
            imap.login(a.get("username") or a["email"], self.password)
            return imap
        except Exception as e:
            raise BackendError("Connexion IMAP impossible : %s" % e)

    def _folders(self, imap):
        if self._folders_cache:
            return self._folders_cache
        found = {"inbox": "INBOX"}
        typ, data = imap.list()
        names = []
        for line in data or []:
            if not isinstance(line, bytes):
                continue
            m = re.match(rb'\((?P<f>[^)]*)\)\s+(?P<d>"[^"]*"|NIL)\s+(?P<n>.+)', line)
            if not m:
                continue
            name = m.group("n").decode("utf-8", "replace").strip()
            if name.startswith('"') and name.endswith('"'):
                name = name[1:-1].replace('\\"', '"').replace("\\\\", "\\")
            names.append(name)
            for fl in m.group("f").decode().lower().split():
                if fl in SPECIAL:
                    found.setdefault(SPECIAL[fl], name)
        for logical, guesses in GUESS.items():
            if logical not in found:
                for n in names:
                    if n.split("/")[-1].split(".")[-1].lower() in guesses:
                        found[logical] = n
                        break
        self._folders_cache = found
        return found

    # -- API
    def test(self):
        try:
            self._connect().logout()
            a = self.acc
            s = self._smtp()
            s.quit()
            return None
        except BackendError as e:
            return str(e)
        except Exception as e:
            return "SMTP : %s" % e

    def sync(self, logical, known, limit=80):
        """Retourne (nouveaux messages, {uid: (unread, starred)}, uids présents, uid minimum)."""
        imap = self._connect()
        try:
            real = self._folders(imap).get(logical)
            if not real:
                return [], {}, None, 0
            typ, _ = imap.select(_q(real), readonly=True)
            if typ != "OK":
                return [], {}, None, 0
            typ, data = imap.uid("SEARCH", None, "ALL")
            uids = [int(x) for x in data[0].split()] if data and data[0] else []
            window = uids[-limit:]
            flags = {}
            old = [u for u in window if u in known]
            for chunk in _chunks(old, 100):
                typ, d = imap.uid("FETCH", ",".join(map(str, chunk)), "(UID FLAGS)")
                for item in d or []:
                    if isinstance(item, bytes):
                        mu = UID_RE.search(item)
                        if mu:
                            fl = _flagset(item)
                            flags[int(mu.group(1))] = ("\\seen" not in fl, "\\flagged" in fl)
            msgs = []
            new = [u for u in window if u not in known]
            for chunk in _chunks(new, 15):
                typ, d = imap.uid("FETCH", ",".join(map(str, chunk)), "(UID FLAGS BODY.PEEK[])")
                items = list(d or [])
                for i, item in enumerate(items):
                    if not isinstance(item, tuple):
                        continue
                    meta, raw = item[0], item[1]
                    mu = UID_RE.search(meta)
                    if not mu:
                        continue
                    fl = _flagset(meta)
                    if not fl and i + 1 < len(items) and isinstance(items[i + 1], bytes):
                        fl = _flagset(items[i + 1])
                    try:
                        msgs.append(parse_message(raw, self.acc["id"], logical, real,
                                                  int(mu.group(1)), fl))
                    except Exception:
                        continue
            return msgs, flags, set(window), (window[0] if window else 0)
        finally:
            try:
                imap.logout()
            except Exception:
                pass

    def _in_folder(self, real, fn):
        imap = self._connect()
        try:
            imap.select(_q(real))
            return fn(imap)
        finally:
            try:
                imap.logout()
            except Exception:
                pass

    def set_flags(self, msg, seen=None, flagged=None):
        def op(imap):
            u = str(msg.uid)
            if seen is not None:
                imap.uid("STORE", u, "+FLAGS" if seen else "-FLAGS", "(\\Seen)")
            if flagged is not None:
                imap.uid("STORE", u, "+FLAGS" if flagged else "-FLAGS", "(\\Flagged)")
        if msg.uid > 0 and msg.real_folder:
            self._in_folder(msg.real_folder, op)

    def move(self, msg, dest):
        if msg.uid <= 0 or not msg.real_folder:
            return None
        imap = self._connect()
        try:
            folders = self._folders(imap)
            target = folders.get(dest)
            imap.select(_q(msg.real_folder))
            u = str(msg.uid)
            if target and target != msg.real_folder:
                if "MOVE" in getattr(imap, "capabilities", ()):
                    imap.uid("MOVE", u, _q(target))
                    return None
                imap.uid("COPY", u, _q(target))
            imap.uid("STORE", u, "+FLAGS", "(\\Deleted)")
            imap.expunge()
        finally:
            try:
                imap.logout()
            except Exception:
                pass
        return None

    def delete_forever(self, msg):
        if msg.uid > 0 and msg.real_folder:
            def op(imap):
                imap.uid("STORE", str(msg.uid), "+FLAGS", "(\\Deleted)")
                imap.expunge()
            self._in_folder(msg.real_folder, op)

    def _smtp(self):
        a = self.acc
        ctx = ssl.create_default_context()
        port = int(a["smtp_port"])
        if port == 465:
            s = smtplib.SMTP_SSL(a["smtp_host"], port, context=ctx, timeout=30)
        else:
            s = smtplib.SMTP(a["smtp_host"], port, timeout=30)
            s.starttls(context=ctx)
        s.login(a.get("username") or a["email"], self.password)
        return s

    def send(self, out):
        a = self.acc
        em = EmailMessage()
        em["From"] = ("%s <%s>" % (a.get("name", ""), a["email"])) if a.get("name") else a["email"]
        em["To"], em["Subject"] = out.to, out.subject
        if out.cc:
            em["Cc"] = out.cc
        em["Date"] = formatdate(localtime=True)
        em["Message-ID"] = make_msgid(domain=a["email"].split("@")[-1])
        if out.in_reply_to:
            em["In-Reply-To"] = out.in_reply_to
            em["References"] = (out.references + " " + out.in_reply_to).strip()
        em.set_content(out.text or html_to_text(out.html))
        em.add_alternative(out.html, subtype="html")
        for path in out.attachments:
            ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
            mt, st = ctype.split("/", 1)
            with open(path, "rb") as f:
                em.add_attachment(f.read(), maintype=mt, subtype=st, filename=os.path.basename(path))
        rcpt = split_addresses(out.to) + split_addresses(out.cc) + split_addresses(out.bcc)
        if not rcpt:
            raise BackendError("Aucun destinataire valide.")
        try:
            s = self._smtp()
            s.send_message(em, to_addrs=rcpt)
            s.quit()
        except Exception as e:
            raise BackendError("Envoi impossible : %s" % e)
        if "gmail" not in a.get("imap_host", ""):
            try:
                imap = self._connect()
                sent = self._folders(imap).get("sent")
                if sent:
                    imap.append(_q(sent), "\\Seen", imaplib.Time2Internaldate(time.time()), em.as_bytes())
                imap.logout()
            except Exception:
                pass


# ------------------------------------------------------------------ démo
def _card(title, body, cta=None):
    btn = ('<p><a href="https://saec.me" style="background:#3b82f6;color:#fff;padding:10px 18px;'
           'border-radius:8px;text-decoration:none">%s</a></p>' % cta) if cta else ""
    return ('<div style="font-family:Arial,sans-serif;max-width:560px;margin:auto;color:#222">'
            '<h2 style="color:#1e3a8a">%s</h2><p style="line-height:1.55">%s</p>%s</div>' % (title, body, btn))


_DEMO = [
    # (nom, email, sujet, corps, minutes, unread, cat, star, att)
    ("Marie Dupont", "marie.dupont@client-alpha.be", "Réunion projet CRM jeudi 14h", "Bonjour,<br>Pouvons-nous valider jeudi à 14h la démo du module facturation ? J'ai joint le cahier des charges mis à jour.<br><br>Merci d'avance,<br>Marie", 18, True, "people", True, True),
    ("Thomas Leroy", "thomas.leroy@gmail.com", "Re: Devis site vitrine", "Salut, j'ai bien reçu ton devis, ça me convient. On peut démarrer la semaine prochaine ?", 55, True, "people", False, False),
    ("GitHub", "notifications@github.com", "[saec/crm] Pull request #42 fusionnée", "La pull request <b>#42 Optimisation des requêtes</b> a été fusionnée dans main.", 95, True, "notif", False, False),
    ("Proximus", "noreply@proximus.be", "Votre facture d'octobre est disponible", "Votre facture est prête. Montant : 54,90 €. Prélèvement le 12 novembre.", 160, False, "notif", False, False),
    ("Sophie Lambert", "sophie@lambert-conseil.eu", "Idées pour le salon Tech 2027", "Coucou ! J'ai eu quelques idées pour le stand, on s'appelle ? Je suis dispo demain matin.", 240, True, "people", False, False),
    ("Stripe", "receipts@stripe.com", "Paiement reçu — 1 250,00 €", "Un paiement de 1 250,00 € a été reçu de Client Alpha SPRL.", 330, False, "notif", True, False),
    ("Le Monde — Newsletter", "newsletter@lemonde.fr", "Votre matinale du mercredi", "Les informations essentielles de ce mercredi 4 novembre.", 400, True, "news", False, False),
    ("Julien Moreau", "julien.moreau@saec.me", "Sécurité : audit serveur terminé", "L'audit est terminé : 2 points mineurs à corriger (en-têtes HTTP, rotation des clés SSH). Rapport en pièce jointe.", 1500, False, "people", False, True),
    ("OVHcloud", "no-reply@ovh.com", "Renouvellement de votre nom de domaine", "Votre domaine arrive à expiration dans 30 jours.", 1800, False, "notif", False, False),
    ("Product Hunt", "hello@producthunt.com", "Les produits du jour", "Découvrez les lancements les plus populaires d'aujourd'hui.", 2000, False, "news", False, False),
    ("Camille Renard", "camille.renard@commune-exemple.be", "Demande d'information — logiciel CPAS", "Bonjour, nous sommes intéressés par une démonstration de votre solution de gestion pour le CPAS. Quelles sont vos disponibilités ?", 2900, True, "people", True, False),
    ("Slack", "feedback@slack.com", "Résumé de l'activité de votre espace", "Vous avez 12 nouveaux messages dans #général.", 4300, False, "notif", False, False),
    ("Papa", "papa.famille@hotmail.com", "Dimanche midi", "On compte sur toi dimanche, ta mère fait le lapin aux pruneaux !", 4800, False, "people", False, False),
    ("Hard Dance Events", "contact@harddance.example", "Line-up confirmé — Showcase", "Le line-up est confirmé, voici le planning définitif de la soirée.", 7200, False, "people", False, False),
    ("Notion", "team@makenotion.com", "Nouveautés de novembre", "Découvrez les dernières fonctionnalités de Notion.", 10000, False, "news", False, False),
]


class DemoBackend:
    demo = True

    def __init__(self, account, password=""):
        self.acc, self._sent = account, False

    def test(self):
        return None

    def sync(self, logical, known, limit=80):
        msgs = []
        marker = DATA_DIR / "demo_seeded"
        if logical == "inbox" and not known and not marker.exists():
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            marker.write_text("1")
            now = time.time()
            for i, (n, e, s, b, mins, un, cat, star, att) in enumerate(_DEMO):
                atts = []
                if att:
                    d = DATA_DIR / "attachments" / "demo"
                    d.mkdir(parents=True, exist_ok=True)
                    p = d / "document.txt"
                    p.write_text("Pièce jointe de démonstration MintMail.\n", encoding="utf-8")
                    atts = [{"filename": "document.txt", "path": str(p), "size": p.stat().st_size, "mime": "text/plain"}]
                msgs.append(Message(
                    id="%s|INBOX|%d" % (self.acc["id"], i + 1), account=self.acc["id"], folder="inbox",
                    real_folder="INBOX", uid=i + 1, sender_name=n, sender_email=e,
                    to=self.acc["email"], subject=s, date=now - mins * 60,
                    snippet=re.sub(r"<[^>]+>", " ", b)[:150], text=html_to_text(b),
                    html=_card(s, b, "Ouvrir saec.me" if cat == "news" else None),
                    unread=un, starred=star, category=cat, attachments=atts,
                    unsubscribe="<https://saec.me/unsubscribe>" if cat == "news" else ""))
        return msgs, {}, None, 0

    def set_flags(self, msg, seen=None, flagged=None):
        pass

    def move(self, msg, dest):
        return None

    def delete_forever(self, msg):
        pass

    def send(self, out):
        time.sleep(0.4)


def make_backend(account, config):
    if account.get("demo"):
        return DemoBackend(account)
    return IMAPBackend(account, config.password(account["id"]))


def new_account_id():
    return uuid.uuid4().hex[:10]
