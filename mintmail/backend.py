"""Accès aux serveurs : IMAP/SMTP réels + backend de démonstration."""
import base64
import email
import imaplib
import mimetypes
import os
import re
import select
import smtplib
import socket
import ssl
import threading
import time
import types
import uuid
from email import policy
from email.message import EmailMessage
from email.utils import formataddr, make_msgid, parsedate_to_datetime, parseaddr, formatdate

from .models import Message
from .store import DATA_DIR, private_dir, write_private
from . import ical, oauth
from .util import html_to_text, split_addresses, text_to_html, thread_key
from .i18n import tr

PRESETS = {
    "Gmail — connexion Google (OAuth, sans mot de passe)": dict(imap_host="imap.gmail.com", imap_port=993, smtp_host="smtp.gmail.com", smtp_port=587, oauth="google"),
    "Outlook / Microsoft 365 — connexion Microsoft (OAuth)": dict(imap_host="outlook.office365.com", imap_port=993, smtp_host="smtp.office365.com", smtp_port=587, oauth="microsoft"),
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


def is_retryable(exc) -> bool:
    """Problème de réseau passager (à rejouer) plutôt que refus définitif du serveur."""
    return bool(getattr(exc, "retryable", False)) or isinstance(exc, (OSError, socket.timeout))


class BackendError(Exception):
    """Erreur serveur. retryable=True : problème de réseau passager (l'action est conservée et rejouée plus tard)."""
    def __init__(self, msg="", retryable=False):
        super().__init__(msg)
        self.retryable = retryable


def utf7_decode(s):
    """Décode un nom de dossier IMAP (UTF-7 modifié, RFC 3501) : « &AOk-t&AOk- » -> « été »."""
    out, i = [], 0
    while i < len(s):
        if s[i] != "&":
            out.append(s[i])
            i += 1
            continue
        j = s.find("-", i)
        if j == -1:
            out.append(s[i:])
            break
        chunk = s[i + 1:j]
        if not chunk:
            out.append("&")
        else:
            b64 = chunk.replace(",", "/")
            b64 += "=" * (-len(b64) % 4)
            try:
                out.append(base64.b64decode(b64).decode("utf-16-be"))
            except Exception:
                out.append(s[i:j + 1])
        i = j + 1
    return "".join(out)


def utf7_encode(s):
    out, buf = [], ""

    def flush():
        nonlocal buf
        if buf:
            b = base64.b64encode(buf.encode("utf-16-be")).decode().rstrip("=").replace("/", ",")
            out.append("&" + b + "-")
            buf = ""
    for ch in s:
        if 0x20 <= ord(ch) <= 0x7E:
            flush()
            out.append("&-" if ch == "&" else ch)
        else:
            buf += ch
    flush()
    return "".join(out)


LIST_RE = re.compile(rb'\((?P<f>[^)]*)\)\s+(?P<d>"(?:[^"\\]|\\.)*"|NIL)\s+(?P<n>.+)')
TOP_RANK = {"inbox": 0, "drafts": 1, "sent": 2, "archive": 3, "spam": 4, "trash": 5}


def _ok(res, what):
    """Une commande IMAP refusée (NO / BAD) ne lève pas d'exception avec imaplib : on la transforme en erreur, pour ne JAMAIS enchaîner une suppression après un échec."""
    if isinstance(res, tuple) and res and res[0] != "OK":
        detail = res[1][0].decode("utf-8", "replace") if len(res) > 1 and res[1] and isinstance(res[1][0], bytes) else ""
        raise BackendError("%s %s" % (what, detail[:100]))
    return res


def _expunge(imap, ids):
    """Efface seulement les messages visés (UID EXPUNGE) quand le serveur le permet ; sinon l'effacement classique."""
    if "UIDPLUS" in getattr(imap, "capabilities", ()):
        r = imap.uid("EXPUNGE", ids)
        if not (isinstance(r, tuple) and r and r[0] != "OK"):
            return
    imap.expunge()


def _q(name):
    if re.search(r"[\x00-\x1f\x7f]", name or ""):                 # CR / LF / NUL : injection de commande IMAP
        raise BackendError(tr("Nom de dossier invalide (caractères de contrôle)"))
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
            private_dir(DATA_DIR / "attachments")
            private_dir(d)
            fname = _safe(fname or tr("pièce jointe") + (mimetypes.guess_extension(part.get_content_type()) or ""))
            path = d / fname
            try:
                write_private(path, data)                                    # 0600 : lisible par vous seul
                atts.append({"filename": fname, "path": str(path), "size": len(data),
                             "mime": part.get_content_type()})
            except OSError:
                pass
    message_id = str(em.get("Message-ID", "") or "")
    references = str(em.get("References", "") or "") or str(em.get("In-Reply-To", "") or "")
    invite = {}
    for part in em.walk():
        if part.get_content_type() == "text/calendar":
            try:
                invite = ical.parse_invite(part.get_content() if hasattr(part, "get_content") else "") or {}
            except Exception:
                invite = {}
            if invite:
                break
    return Message(
        id=mid, account=account, folder=logical, real_folder=real_folder, uid=uid,
        sender_name=name, sender_email=addr, to=str(em.get("To", "") or ""),
        cc=str(em.get("Cc", "") or ""), reply_to=str(em.get("Reply-To", "") or ""),
        subject=subject, date=ts, snippet=re.sub(r"\s+", " ", text_body)[:160].strip(),
        text=text_body, html=html_body,
        unread=("\\seen" not in flags) and logical != "drafts",
        starred="\\flagged" in flags, pinned=PIN_KEYWORD_LOW in flags, category=classify(addr, em), attachments=atts,
        message_id=message_id, references=references, unsubscribe=str(em.get("List-Unsubscribe", "") or ""),
        unsub_post="one-click" in str(em.get("List-Unsubscribe-Post", "") or "").lower(),
        thread_id=thread_key(message_id, references, subject), invite=invite)


def build_imap_search(text):
    """Critères IMAP SEARCH depuis la syntaxe de recherche de MintMail (mots, from:, is:unread, is:starred, has:attachment)."""
    from .store import parse_search
    terms, flt = parse_search(text)
    args, utf8 = [], [False]

    def lit(s):
        if not s.isascii():
            utf8[0] = True
            return s.encode("utf-8")
        return '"%s"' % s.replace("\\", "\\\\").replace('"', '\\"')
    if flt.get("unread"):
        args.append("UNSEEN")
    if flt.get("starred"):
        args.append("FLAGGED")
    if flt.get("from"):
        args += ["FROM", lit(flt["from"])]
    if flt.get("att"):
        args += ["HEADER", "Content-Type", '"multipart/mixed"']
    for t in terms:
        args += ["TEXT", lit(t)]
    if utf8[0]:
        args = ["CHARSET", "UTF-8"] + args
    return args or ["ALL"]


PIN_KEYWORD = "$MintMailPinned"          # mot-clé IMAP (insensible à la casse) : l'épingle est enregistrée SUR LA BOÎTE, comme le favori (\Flagged)
PIN_KEYWORD_LOW = PIN_KEYWORD.lower()
PIN_LABEL = "MintMail-Epingles"           # Gmail : l'épingle est une ÉTIQUETTE (extension X-GM-LABELS), visible dans Gmail web et mobile
PIN_LABEL_LOW = PIN_LABEL.lower()


class PinUnsupported(Exception):
    """Le serveur n'a pas conservé le mot-clé d'épingle (Gmail, Outlook.com… n'acceptent pas les mots-clés personnalisés)."""
    retryable = False

    def __init__(self):
        super().__init__(tr("Ce serveur ne mémorise pas les épingles : l'épingle reste sur ce poste seulement. Commande « mintmail --check-pins » pour le vérifier."))


UID_RE = re.compile(rb"UID (\d+)")
FLAGS_RE = re.compile(rb"FLAGS \(([^)]*)\)")


def _gm_labels(b):
    """Étiquettes Gmail d'une réponse FETCH (« X-GM-LABELS ("\\\\Inbox" "Travail (ancien)" MintMail-Epingles) »), guillemets et parenthèses compris."""
    s = (b or b"").decode("utf-8", "replace")
    i = s.find("X-GM-LABELS (")
    if i < 0:
        return []
    out, cur, quoted, esc = [], "", False, False
    for c in s[i + len("X-GM-LABELS ("):]:
        if quoted:
            if esc:
                cur, esc = cur + c, False
            elif c == "\\":
                esc = True
            elif c == '"':
                quoted = False
                out.append(cur)
                cur = ""
            else:
                cur += c
        elif c == '"':
            quoted, cur = True, ""
        elif c == ")":
            if cur:
                out.append(cur)
            break
        elif c == " ":
            if cur:
                out.append(cur)
            cur = ""
        else:
            cur += c
    return out


def _has_gm(imap):
    """Serveur Gmail (extension X-GM-EXT-1) : l'épingle y est une étiquette, pas un mot-clé IMAP."""
    return "X-GM-EXT-1" in (getattr(imap, "capabilities", None) or ())


def _flagset(b):
    m = FLAGS_RE.search(b or b"")
    s = set(m.group(1).decode().lower().split()) if m else set()
    if PIN_LABEL_LOW in [x.lower() for x in _gm_labels(b)]:
        s.add(PIN_KEYWORD_LOW)                                  # l'étiquette Gmail « MintMail-Epingles » vaut épingle pour tout le reste du code
    return s


class _Conn:
    """Connexion IMAP persistante (évite un handshake TLS + login à chaque action)."""
    def __init__(self):
        self.lock = threading.RLock()
        self.imap, self.sel, self.ts = None, None, 0.0


class IMAPBackend:
    demo = False

    def __init__(self, account, password, token_provider=None, password_provider=None):
        self.acc, self.password = account, password
        self.password_provider = password_provider   # relit le mot de passe À CHAQUE connexion (trousseau lent au démarrage : ne jamais figer un mot de passe vide)
        self.token_provider = token_provider   # OAuth : fournit un jeton d'accès valide
        self._folders_cache = None
        self._conns = {"sync": _Conn(), "act": _Conn(), "meta": _Conn()}
        self._tree_cache = None
        self._pin_dirty = False
        self._gm_seen = False

    def _pw(self):
        pw = (self.password_provider() if self.password_provider else "") or self.password
        if pw:
            self.password = pw
            return pw
        raise BackendError(tr("Mot de passe introuvable pour %s : saisissez-le à nouveau dans Paramètres → Comptes.") % (self.acc.get("email") or self.acc.get("id")), retryable=True)

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
            user = a.get("username") or a["email"]
            if self.token_provider:
                token = self.token_provider()
                imap.authenticate("XOAUTH2", lambda _c: oauth.xoauth2(user, token).encode())
            else:
                imap.login(user, self._pw())
            return imap
        except BackendError:
            raise
        except oauth.OAuthError as e:
            raise BackendError(tr("Connexion OAuth : %s") % e)
        except Exception as e:
            raise BackendError(tr("Connexion IMAP impossible : %s") % e, retryable=isinstance(e, (OSError, imaplib.IMAP4.abort)))

    def _list_raw(self, imap):
        """Liste complète des dossiers : [{name, path, label, depth, delim, special, selectable}] (arborescence triée)."""
        typ, data = imap.list()
        entries, found = [], {"inbox": "INBOX"}
        for line in data or []:
            if not isinstance(line, bytes):
                continue
            m = LIST_RE.match(line)
            if not m:
                continue
            name = m.group("n").decode("utf-8", "replace").strip()
            if name.startswith('"') and name.endswith('"'):
                name = name[1:-1].replace('\\"', '"').replace("\\\\", "\\")
            dtxt = m.group("d").decode().strip('"')
            delim = "/" if dtxt.upper() == "NIL" else dtxt
            flags = set(m.group("f").decode().lower().split())
            if (utf7_decode(name).split(delim)[-1] if delim else name).lower() == PIN_LABEL_LOW:
                continue                                               # étiquette Gmail technique des épingles : visible dans Gmail, pas dans la liste de dossiers
            special = "inbox" if name.upper() == "INBOX" else ""
            for fl in flags:
                if fl in SPECIAL and not special:
                    special = SPECIAL[fl]
            entries.append({"name": name, "flags": flags, "delim": delim, "special": special,
                            "selectable": not ({"\\noselect", "\\nonexistent"} & flags)})
        for logical, guesses in GUESS.items():     # repli par le nom quand le serveur n'annonce pas l'usage spécial
            if not any(e["special"] == logical for e in entries):
                for e in entries:
                    if not e["special"] and utf7_decode(e["name"]).split(e["delim"])[-1].lower() in guesses:
                        e["special"] = logical
                        break
        for e in entries:
            if e["special"] and e["special"] not in found:
                found[e["special"]] = e["name"]
        out = []
        for e in entries:
            path = utf7_decode(e["name"])
            parts = path.split(e["delim"]) if e["delim"] else [path]
            if len(parts) > 1 and parts[0].upper() == "INBOX":    # espace de noms « INBOX.Sent » : dossiers au premier niveau
                parts = parts[1:]
            out.append({"name": e["name"], "path": " › ".join(parts), "label": parts[-1], "depth": len(parts) - 1,
                        "delim": e["delim"], "special": e["special"], "selectable": e["selectable"],
                        "_key": [p.lower() for p in parts]})
        top = {e["_key"][0]: TOP_RANK[e["special"]] for e in out if e["depth"] == 0 and e["special"] in TOP_RANK}
        out.sort(key=lambda e: [(top.get(e["_key"][0], 9) if i == 0 else 0, k) for i, k in enumerate(e["_key"])])
        for e in out:
            e.pop("_key")
        self._folders_cache, self._tree_cache = found, out
        return out

    def _folders(self, imap):
        if not self._folders_cache:
            self._list_raw(imap)
        return self._folders_cache

    def _resolve(self, imap, key):
        """Nom réel d'un dossier : « f:<nom> » (dossier quelconque) ou nom logique (sent, trash…)."""
        return key[2:] if key.startswith("f:") else self._folders(imap).get(key)

    def list_folders(self):
        def fn(conn):
            return self._list_raw(conn.imap)
        return self._run("meta", fn)

    def folder_status(self, names):
        """{nom: (messages, non lus)} par la commande STATUS (connexion dédiée : n'attend pas les actions)."""
        def fn(conn):
            out = {}
            for n in names:
                try:
                    typ, d = conn.imap.status(_q(n), "(MESSAGES UNSEEN)")
                except imaplib.IMAP4.abort:
                    raise
                except imaplib.IMAP4.error:
                    continue
                if typ == "OK" and d and d[0]:
                    t = d[0].decode("utf-8", "replace") if isinstance(d[0], bytes) else str(d[0])
                    mm, uu = re.search(r"MESSAGES (\d+)", t), re.search(r"UNSEEN (\d+)", t)
                    out[n] = (int(mm.group(1)) if mm else 0, int(uu.group(1)) if uu else 0)
            return out
        return self._run("meta", fn)

    def _reset_selection(self):
        for c in self._conns.values():
            c.sel = None
        self._folders_cache = self._tree_cache = None

    def create_folder(self, path):
        def fn(conn):
            typ, d = conn.imap.create(_q(utf7_encode(path)))
            if typ != "OK":
                raise BackendError(tr("Création impossible : %s") % (d[0].decode("utf-8", "replace") if d and d[0] else typ))
        self._run("act", fn)
        self._reset_selection()

    def rename_folder(self, old_raw, new_path):
        def fn(conn):
            typ, d = conn.imap.rename(_q(old_raw), _q(utf7_encode(new_path)))
            if typ != "OK":
                raise BackendError(tr("Renommage impossible : %s") % (d[0].decode("utf-8", "replace") if d and d[0] else typ))
        self._reset_selection()
        self._run("act", fn)
        self._reset_selection()

    def delete_folder(self, raw):
        def fn(conn):
            try:
                conn.imap.unselect()
            except Exception:
                pass
            conn.sel = None
            typ, d = conn.imap.delete(_q(raw))
            if typ != "OK":
                raise BackendError(tr("Suppression impossible : %s") % (d[0].decode("utf-8", "replace") if d and d[0] else typ))
        self._run("act", fn)
        self._reset_selection()

    # -- API
    # ----------------------------------------------------- connexions persistantes
    def _drop(self, conn):
        try:
            if conn.imap:
                conn.imap.logout()
        except Exception:
            pass
        conn.imap, conn.sel = None, None

    def close(self):
        for c in self._conns.values():
            with c.lock:
                self._drop(c)

    def _run(self, kind, fn):
        """Exécute fn(conn) sur la connexion « sync » ou « act » (reconnexion automatique, un nouvel essai)."""
        conn = self._conns[kind]
        with conn.lock:
            for attempt in (0, 1):
                try:
                    if conn.imap is None:
                        conn.imap, conn.sel = self._connect(), None
                    elif time.time() - conn.ts > 20:
                        conn.imap.noop()
                    res = fn(conn)
                    conn.ts = time.time()
                    return res
                except (imaplib.IMAP4.abort, ssl.SSLError, OSError) as e:
                    self._drop(conn)
                    if attempt:
                        raise BackendError(tr("Connexion IMAP perdue : %s") % e)

    def _select(self, conn, real, readonly=False):
        key = (real, readonly)
        if conn.sel != key:
            typ, _ = conn.imap.select(_q(real), readonly=readonly)
            if typ != "OK":
                conn.sel = None
                raise BackendError(tr("Dossier introuvable : %s") % real)
            conn.sel = key

    # ------------------------------------------------------------------------ API
    def test(self):
        try:
            self._connect().logout()
            s = self._smtp()
            s.quit()
            return None
        except BackendError as e:
            return str(e)
        except Exception as e:
            return "SMTP : %s" % e

    def sync(self, logical, known, limit=60, on_batch=None, unseen=False):
        """Retourne (nouveaux messages, {uid: (non lu, favori)}, uids présents, uid minimum).
        Les nouveaux messages arrivent par lots, les plus récents d'abord (on_batch).
        unseen=True (dossiers de rangement) : ne télécharge que les NON LUS pas encore connus ; l'état des messages connus est relu."""
        def fn(conn):
            imap = conn.imap
            real = self._resolve(imap, logical)
            if not real:
                return [], {}, None, 0
            self._select(conn, real, readonly=True)
            typ, data = imap.uid("SEARCH", None, "ALL")
            uids = [int(x) for x in data[0].split()] if data and data[0] else []
            window = uids[-limit:]
            if unseen:
                typ, du = imap.uid("SEARCH", None, "UNSEEN")
                un = {int(x) for x in du[0].split()} if du and du[0] else set()
                window = sorted(set(window) | un)
            flags = {}
            old = [u for u in (uids[-300:] if unseen else window) if u in known]       # unseen : état relu pour tous les messages connus (lu ailleurs ?)
            proven = self.acc.get("pin_server") is True            # capacité connue AVANT cette lecture : seule elle autorise à désépingler à distance
            for chunk in _chunks(old, 100):
                typ, d = imap.uid("FETCH", ",".join(map(str, chunk)), "(UID FLAGS%s)" % (" X-GM-LABELS" if _has_gm(imap) else ""))
                for item in d or []:
                    if isinstance(item, bytes):
                        mu = UID_RE.search(item)
                        if mu:
                            fl = _flagset(item)
                            if PIN_KEYWORD_LOW in fl:
                                self._pin_state(True)
                            flags[int(mu.group(1))] = ("\\seen" not in fl, "\\flagged" in fl, True if PIN_KEYWORD_LOW in fl else (False if proven else None))
            msgs = []
            new = sorted((u for u in (un if unseen else window) if u not in known), reverse=True)
            for chunk in _chunks(new, 10):
                batch = self._fetch_batch(imap, chunk, logical, real)
                if any(m.pinned for m in batch):
                    self._pin_state(True)                         # une épingle vue sur la boîte : ce serveur sait les garder
                msgs += batch
                if on_batch and batch:
                    on_batch(batch)
            if unseen:
                return msgs, flags, set(uids), 0                   # liste COMPLÈTE : un message supprimé ou déplacé ailleurs disparaît du cache
            return msgs, flags, set(window), (window[0] if window else 0)
        return self._run("sync", fn)

    def _fetch_batch(self, imap, chunk, logical, real):
        """Télécharge et analyse un lot de messages (UID)."""
        typ, d = imap.uid("FETCH", ",".join(map(str, chunk)), "(UID FLAGS%s BODY.PEEK[])" % (" X-GM-LABELS" if _has_gm(imap) else ""))
        items, batch = list(d or []), []
        for i, item in enumerate(items):
            if not isinstance(item, tuple):
                continue
            meta, raw = item[0], item[1]
            mu = UID_RE.search(meta)
            if not mu:
                continue
            fl = _flagset(meta) | (_flagset(items[i + 1]) if i + 1 < len(items) and isinstance(items[i + 1], bytes) else set())    # drapeaux avant ou après le corps
            try:
                batch.append(parse_message(raw, self.acc["id"], logical, real, int(mu.group(1)), fl))
            except Exception:
                continue
        return batch

    def search_server(self, text, logicals, known_by_folder, limit=40):
        """Recherche sur le SERVEUR (messages jamais téléchargés) ; retourne les messages trouvés (les plus récents d'abord)."""
        crit = build_imap_search(text)

        def fn(conn):
            imap, found = conn.imap, []
            for logical in logicals:
                real = self._resolve(imap, logical)
                if not real:
                    continue
                self._select(conn, real, readonly=True)
                typ, data = imap.uid("SEARCH", *crit)
                uids = [int(x) for x in data[0].split()] if data and data[0] else []
                known = known_by_folder.get(logical, set())
                new = [u for u in reversed(uids) if u not in known][:limit]
                for chunk in _chunks(new, 10):
                    found += self._fetch_batch(imap, chunk, logical, real)
            return found
        return self._run("sync", fn)

    def _pin_state(self, ok, mode=None):
        """Mémorise (dans le compte, localement) si ce serveur garde les épingles et comment ; `_pin_dirty` demande à la fenêtre d'enregistrer."""
        if self.acc.get("pin_server") is not ok:
            self.acc["pin_server"] = ok
            self._pin_dirty = True
        if mode and self.acc.get("pin_mode") != mode:
            self.acc["pin_mode"] = mode
            self._pin_dirty = True

    def set_flags(self, msg, seen=None, flagged=None, pinned=None):
        self.set_flags_many([msg], seen, flagged, pinned)

    def set_flags_many(self, msgs, seen=None, flagged=None, pinned=None, probe=False):
        """pinned : épingle = mot-clé IMAP. Au premier essai, la relecture PROUVE que le serveur l'a gardé ; sinon PinUnsupported (rien n'est affirmé à tort).
        probe=True : refait l'essai même si le serveur avait déjà été jugé incapable (commande « Envoyer mes épingles vers la boîte »)."""
        by = {}
        for m in msgs:
            if m.uid > 0 and m.real_folder:
                by.setdefault(m.real_folder, []).append(m.uid)
        if not by:
            return
        if probe:
            self.acc.pop("pin_server", None)
        if pinned is True and self.acc.get("pin_server") is False:
            raise PinUnsupported()                                      # déjà constaté : inutile de réessayer à chaque clic
        failed = []

        def fn(conn):
            for real, uids in by.items():
                self._select(conn, real)
                ids = ",".join(str(u) for u in uids)
                if seen is not None:
                    conn.imap.uid("STORE", ids, "+FLAGS" if seen else "-FLAGS", "(\\Seen)")
                if flagged is not None:
                    conn.imap.uid("STORE", ids, "+FLAGS" if flagged else "-FLAGS", "(\\Flagged)")
                if pinned is not None:
                    gm = _has_gm(conn.imap)
                    self._gm_seen = gm
                    if gm:
                        conn.imap.uid("STORE", ids, "+X-GM-LABELS" if pinned else "-X-GM-LABELS", "(%s)" % PIN_LABEL)
                    else:
                        conn.imap.uid("STORE", ids, "+FLAGS" if pinned else "-FLAGS", "(%s)" % PIN_KEYWORD)
                    if pinned and self.acc.get("pin_server") is not True:        # première fois : le serveur l'a-t-il VRAIMENT gardé ?
                        typ, d = conn.imap.uid("FETCH", ids, "(UID FLAGS%s)" % (" X-GM-LABELS" if gm else ""))
                        kept = set()
                        for item in d or []:
                            if isinstance(item, bytes):
                                mu = UID_RE.search(item)
                                if mu and PIN_KEYWORD_LOW in _flagset(item):
                                    kept.add(int(mu.group(1)))
                        failed.extend(u for u in uids if u not in kept)
        self._run("act", fn)
        if pinned is True:
            if failed:
                self._pin_state(False)
                raise PinUnsupported()
            self._pin_state(True, "gmail" if self._gm_seen else "keyword")

    def pin_diagnostic(self, test=True):
        """Verdict RÉEL sur ce serveur (utilisé par « mintmail --check-pins »). test=True : essai réversible sur le message le plus récent de la boîte de
        réception (épingle puis retrait, retrait garanti même en cas d'erreur) ; test=False : lecture seule (aucune modification)."""
        out = {"connected": False, "mode": "", "count": None, "tested": False, "supported": None, "error": ""}
        probe = []

        def fn(conn):
            imap = conn.imap
            out["connected"] = True
            gm = _has_gm(imap)
            out["mode"] = "gmail" if gm else "keyword"
            real = self._resolve(imap, "inbox") or "INBOX"
            self._select(conn, real, readonly=not test)
            try:
                typ, d = (imap.uid("SEARCH", None, "X-GM-RAW", '"label:%s"' % PIN_LABEL_LOW) if gm else imap.uid("SEARCH", None, "KEYWORD", PIN_KEYWORD))
                out["count"] = len(d[0].split()) if typ == "OK" and d and d[0] else 0
            except imaplib.IMAP4.error:
                out["count"] = None
            typ, d = imap.uid("SEARCH", None, "ALL")
            uids = [int(x) for x in d[0].split()] if typ == "OK" and d and d[0] else []
            if uids:
                probe.append(types.SimpleNamespace(uid=uids[-1], real_folder=real))
        try:
            self._run("meta", fn)
            if test and probe:
                out["tested"] = True
                try:
                    self.set_flags_many(probe, pinned=True, probe=True)
                    out["supported"] = True
                except PinUnsupported:
                    out["supported"] = False
                finally:
                    try:
                        self.set_flags_many(probe, pinned=False)
                    except Exception as e:                            # le retrait ne doit jamais masquer le verdict
                        out["error"] = str(e)
        except Exception as e:
            out["error"] = str(e)
        return out

    def move(self, msg, dest):
        return self.move_many([msg], dest)

    def move_many(self, msgs, dest, notjunk=False):
        """Déplace plusieurs messages en une seule opération.
        notjunk=True (« Ce n'est pas du spam ») : avant de sortir du dossier Spam, le message perd $Junk et reçoit $NotJunk, que les
        filtres du serveur (Dovecot, Thunderbird, Apple Mail…) lisent comme « non-spam » ; le déplacement hors du dossier fait le reste
        (sur Gmail, le message quitte le libellé Spam)."""
        by = {}
        for m in msgs:
            if m.uid > 0 and m.real_folder:
                by.setdefault(m.real_folder, []).append(m.uid)
        if not by:
            return None

        def fn(conn):
            imap = conn.imap
            target = self._resolve(imap, dest)
            if not target and dest != "trash":
                raise BackendError(tr("Dossier « %s » introuvable sur le serveur.") % dest)
            for real, uids in by.items():
                self._select(conn, real)
                ids = ",".join(str(u) for u in uids)
                if notjunk:
                    for op, flag in (("-FLAGS", "$Junk"), ("+FLAGS", "$NotJunk")):
                        try:
                            imap.uid("STORE", ids, op, "(%s)" % flag)
                        except Exception:               # serveur sans mots-clés libres : le déplacement suffit
                            pass
                if target and target != real:
                    if "MOVE" in getattr(imap, "capabilities", ()):
                        _ok(imap.uid("MOVE", ids, _q(target)), tr("Déplacement refusé par le serveur"))
                        continue
                    _ok(imap.uid("COPY", ids, _q(target)), tr("Copie refusée par le serveur : le message n'est PAS supprimé"))
                _ok(imap.uid("STORE", ids, "+FLAGS", "(\\Deleted)"), tr("Marquage refusé par le serveur"))
                _expunge(imap, ids)
        self._run("act", fn)
        return None

    def delete_forever(self, msg):
        self.delete_many([msg])

    def delete_many(self, msgs):
        by = {}
        for m in msgs:
            if m.uid > 0 and m.real_folder:
                by.setdefault(m.real_folder, []).append(m.uid)

        def fn(conn):
            for real, uids in by.items():
                self._select(conn, real)
                ids = ",".join(str(u) for u in uids)
                _ok(conn.imap.uid("STORE", ids, "+FLAGS", "(\\Deleted)"), tr("Suppression refusée par le serveur"))
                _expunge(conn.imap, ids)
        if by:
            self._run("act", fn)

    # ------------------------------------------------------------ push (IMAP IDLE)
    def watch(self, on_change, stop):
        """Boucle IDLE sur la boîte de réception : on_change() à l'arrivée, au départ ou au changement d'un message (y compris les drapeaux posés depuis un autre poste). Bloquant (thread dédié)."""
        backoff = 5
        while not stop.is_set():
            imap = None
            try:
                imap = self._connect()
                imap.select("INBOX", readonly=True)
                backoff = 5
                while not stop.is_set():
                    if self._idle_once(imap, stop):
                        on_change()
            except Exception:
                if stop.wait(backoff):
                    break
                backoff = min(backoff * 2, 300)
            finally:
                try:
                    if imap:
                        imap.logout()
                except Exception:
                    pass

    @staticmethod
    def _idle_once(imap, stop, max_wait=540):
        sock = imap.sock
        tag = imap._new_tag()

        def read(timeout):
            if not (hasattr(sock, "pending") and sock.pending()):
                r, _, _ = select.select([sock], [], [], timeout)
                if not r:
                    return b""
            data = sock.recv(4096)
            if not data:
                raise imaplib.IMAP4.abort(tr("connexion fermée"))
            return data
        sock.sendall(tag + b" IDLE\r\n")
        buf, t0 = b"", time.time()
        while b"\n" not in buf:
            buf += read(2)
            if time.time() - t0 > 15:
                raise imaplib.IMAP4.abort(tr("IDLE sans réponse"))
        if not buf.startswith(b"+"):
            raise imaplib.IMAP4.error(tr("IDLE non pris en charge"))
        buf = buf.split(b"\n", 1)[1]
        changed, end = False, time.time() + max_wait
        while not stop.is_set() and time.time() < end and not changed:
            buf += read(5)
            if re.search(rb"\* \d+ (EXISTS|EXPUNGE|RECENT|FETCH)", buf):      # FETCH : drapeaux changés ailleurs (épingle, lu, favori)
                changed = True
        sock.sendall(b"DONE\r\n")
        t0 = time.time()
        while tag not in buf and time.time() - t0 < 15:
            buf += read(3)
        return changed

    def _smtp(self):
        a = self.acc
        ctx = ssl.create_default_context()
        port = int(a["smtp_port"])
        if port == 465:
            s = smtplib.SMTP_SSL(a["smtp_host"], port, context=ctx, timeout=30)
        else:
            s = smtplib.SMTP(a["smtp_host"], port, timeout=30)
            s.starttls(context=ctx)
        user = a.get("username") or a["email"]
        if self.token_provider:
            s.ehlo()
            code, resp = s.docmd("AUTH", "XOAUTH2 " + base64.b64encode(oauth.xoauth2(user, self.token_provider()).encode()).decode())
            if code != 235:
                raise smtplib.SMTPAuthenticationError(code, resp)
        else:
            s.login(user, self._pw())
        return s

    def send(self, out):
        a = self.acc
        em = EmailMessage()
        from_email = out.from_email or a["email"]
        from_name = out.from_name if out.from_email else a.get("name", "")
        em["From"] = formataddr((from_name, from_email)) if from_name else from_email
        em["To"], em["Subject"] = out.to, out.subject
        if out.cc:
            em["Cc"] = out.cc
        em["Date"] = formatdate(localtime=True)
        em["Message-ID"] = make_msgid(domain=from_email.split("@")[-1])
        if out.in_reply_to:
            em["In-Reply-To"] = out.in_reply_to
            em["References"] = (out.references + " " + out.in_reply_to).strip()
        em.set_content(out.text or html_to_text(out.html))
        em.add_alternative(out.html, subtype="html")
        for cid, sub, b64 in (out.inline or []):          # logos de signature : image jointe « en ligne » référencée par cid:
            em.get_body(preferencelist=("html",)).add_related(base64.b64decode(b64), "image", sub, cid="<%s>" % cid)
        if out.ics:   # réponse à une invitation : partie text/calendar (Outlook, Google, Apple la reconnaissent)
            em.add_attachment(out.ics.encode("utf-8"), maintype="text", subtype="calendar", filename="invite.ics",
                              params={"method": out.ics_method or "REPLY", "charset": "UTF-8"})
        for path in out.attachments:
            ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
            mt, st = ctype.split("/", 1)
            with open(path, "rb") as f:
                em.add_attachment(f.read(), maintype=mt, subtype=st, filename=os.path.basename(path))
        rcpt = split_addresses(out.to) + split_addresses(out.cc) + split_addresses(out.bcc)
        if not rcpt:
            raise BackendError(tr("Aucun destinataire valide."))
        try:
            s = self._smtp()
            s.send_message(em, from_addr=from_email, to_addrs=rcpt)
            s.quit()
        except (smtplib.SMTPAuthenticationError, smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused, smtplib.SMTPDataError) as e:
            raise BackendError(tr("Envoi impossible : %s") % e)                       # refus définitif : inutile de réessayer
        except oauth.OAuthError as e:
            raise BackendError(tr("Envoi impossible : %s") % e, retryable=getattr(e, "retryable", False))
        except (OSError, smtplib.SMTPException) as e:
            raise BackendError(tr("Envoi impossible : %s") % e, retryable=True)       # réseau : conservé et rejoué plus tard
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


def _dfolder(name, special="", delim="/"):
    parts = name.split(delim)
    return {"name": name, "path": " › ".join(parts), "label": parts[-1], "depth": len(parts) - 1, "delim": delim,
            "special": special, "selectable": True}


DEMO_FOLDERS = [_dfolder("INBOX", "inbox"), _dfolder("Brouillons", "drafts"), _dfolder("Envoyés", "sent"),
                _dfolder("Archives", "archive"), _dfolder("Spam", "spam"), _dfolder("Corbeille", "trash"),
                _dfolder("Clients"), _dfolder("Clients/Alpha"), _dfolder("Clients/Beta"), _dfolder("Factures"),
                _dfolder("Projets"), _dfolder("Projets/CRM"), _dfolder("Projets/CPAS"), _dfolder("À lire plus tard")]
DEMO_FOLDER_MSGS = {
    "Clients/Alpha": [("Marie Dupont", "marie.dupont@client-alpha.be", "Cahier des charges v3", "Voici la version 3 du cahier des charges, merci de valider avant vendredi.", 300, True),
                      ("Marie Dupont", "marie.dupont@client-alpha.be", "Re: Planning de livraison", "Le planning nous convient, on garde la démo du 12.", 2900, False)],
    "Clients/Beta": [("Paul Henry", "paul@beta-sprl.be", "Demande de devis module stock", "Pouvez-vous nous chiffrer un module de gestion de stock ?", 700, True)],
    "Factures": [("Compta SAEC", "compta@saec.me", "Facture 2026-114 émise", "La facture 2026-114 a été envoyée au client.", 1500, False),
                 ("Stripe", "receipts@stripe.com", "Paiement reçu — 1 250,00 €", "Paiement reçu de Client Alpha SPRL.", 4000, False)],
    "Projets/CRM": [("Julien Moreau", "julien.moreau@saec.me", "Revue de code CRM", "J'ai relu la PR #42 : deux remarques sur les requêtes N+1.", 200, True),
                    ("GitHub", "notifications@github.com", "[saec/crm] Issue #51 ouverte", "Un nouveau ticket a été ouvert : lenteur du tableau de bord.", 900, False)],
    "Projets/CPAS": [("Camille Renard", "camille.renard@commune-exemple.be", "Démonstration CPAS : créneaux", "Nous sommes disponibles mardi ou jeudi après-midi.", 1200, True)],
    "À lire plus tard": [("Le Monde — Newsletter", "newsletter@lemonde.fr", "Dossier : l'IA dans l'entreprise", "Un long dossier à lire ce week-end.", 5000, False)],
}


class DemoBackend:
    demo = True

    def __init__(self, account, password=""):
        self.acc, self._sent = account, False
        self.folders = [dict(f) for f in DEMO_FOLDERS]
        self._seeded = set()

    def list_folders(self):
        return [dict(f) for f in self.folders]

    def folder_status(self, names):
        out = {}
        for n in names:
            items = DEMO_FOLDER_MSGS.get(n)
            if items is not None:
                out[n] = (len(items), sum(1 for it in items if it[5]))
        return out

    def create_folder(self, path):
        if any(f["name"] == path for f in self.folders):
            raise BackendError("Ce dossier existe déjà.")
        self.folders.append(_dfolder(path))
        self.folders.sort(key=lambda f: ([TOP_RANK.get(f["special"], 9)] + [f["path"].lower()]))

    def rename_folder(self, old_raw, new_path):
        for f in self.folders:
            if f["name"] == old_raw or f["name"].startswith(old_raw + "/"):
                nf = _dfolder(new_path + f["name"][len(old_raw):], f["special"])
                f.update(nf)

    def delete_folder(self, raw):
        self.folders = [f for f in self.folders if not (f["name"] == raw or f["name"].startswith(raw + "/"))]

    def test(self):
        return None

    def sync(self, logical, known, limit=60, on_batch=None, unseen=False):
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
        if logical.startswith("f:") and not known and logical not in self._seeded:
            self._seeded.add(logical)
            real, now = logical[2:], time.time()
            for i, (n, e, s, b, mins, un) in enumerate(DEMO_FOLDER_MSGS.get(real, [])):
                msgs.append(Message(
                    id="%s|%s|%d" % (self.acc["id"], real, i + 1), account=self.acc["id"], folder=logical,
                    real_folder=real, uid=i + 1, sender_name=n, sender_email=e, to=self.acc["email"], subject=s,
                    date=now - mins * 60, snippet=b[:150], text=b, html=_card(s, b), unread=un, category="people"))
        return msgs, {}, None, 0

    def set_flags(self, msg, seen=None, flagged=None, pinned=None):
        pass

    def move(self, msg, dest):
        return None

    def move_many(self, msgs, dest, notjunk=False):
        return None

    def search_server(self, text, logicals, known_by_folder, limit=40):
        return []

    def set_flags_many(self, msgs, seen=None, flagged=None, pinned=None, probe=False):
        pass

    def delete_forever(self, msg):
        pass

    def delete_many(self, msgs):
        pass

    def watch(self, on_change, stop):
        stop.wait()

    def close(self):
        pass

    def send(self, out):
        time.sleep(0.4)


def make_backend(account, config):
    if account.get("demo"):
        return DemoBackend(account)
    if account.get("auth") == "oauth2":
        tm = oauth.manager_for(config)
        return IMAPBackend(account, "", token_provider=lambda: tm.access_token(account))
    return IMAPBackend(account, config.password(account["id"]), password_provider=lambda: config.password(account["id"]))


def new_account_id():
    return uuid.uuid4().hex[:10]
