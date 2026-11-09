import hashlib
import html
import re
import time
import datetime
from html.parser import HTMLParser

MONTHS = ["janv.", "févr.", "mars", "avr.", "mai", "juin",
          "juil.", "août", "sept.", "oct.", "nov.", "déc."]


class _Strip(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head", "title"):
            self.skip += 1
        elif tag in ("br", "p", "div", "tr", "li", "h1", "h2", "h3", "h4"):
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head", "title"):
            self.skip = max(0, self.skip - 1)
        elif tag in ("p", "div", "tr", "li", "table"):
            self.out.append("\n")

    def handle_data(self, d):
        if not self.skip:
            self.out.append(d)


def html_to_text(h):
    p = _Strip()
    try:
        p.feed(h)
        p.close()
    except Exception:
        return re.sub(r"<[^>]+>", " ", h)
    t = "".join(p.out)
    t = re.sub(r"[ \t\xa0]+", " ", t)
    t = re.sub(r"\n\s*\n\s*\n+", "\n\n", t)
    return t.strip()


def text_to_html(t):
    t = html.escape(t)
    t = re.sub(r"(https?://[^\s<]+)", r'<a href="\1">\1</a>', t)
    return t.replace("\n", "<br>")


def format_time(ts):
    d = datetime.datetime.fromtimestamp(ts)
    today = datetime.date.today()
    if d.date() == today:
        return d.strftime("%H:%M")
    if d.date() == today - datetime.timedelta(days=1):
        return "Hier"
    if d.year == today.year:
        return "%d %s" % (d.day, MONTHS[d.month - 1])
    return d.strftime("%d/%m/%Y")


def format_full(ts):
    d = datetime.datetime.fromtimestamp(ts)
    return "%d %s %d à %s" % (d.day, MONTHS[d.month - 1], d.year, d.strftime("%H:%M"))


def date_group(ts):
    d = datetime.datetime.fromtimestamp(ts).date()
    delta = (datetime.date.today() - d).days
    if delta <= 0:
        return "Aujourd'hui"
    if delta == 1:
        return "Hier"
    if delta < 7:
        return "Cette semaine"
    if delta < 31:
        return "Ce mois-ci"
    return "Plus ancien"


def color_index(key, n=8):
    return int(hashlib.md5((key or "?").lower().encode()).hexdigest(), 16) % n


def initials(name):
    name = re.sub(r"[^\w\s@.]", "", name or "?").strip()
    if "@" in name and " " not in name:
        return name[0].upper()
    parts = [p for p in name.split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][0].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def human_size(n):
    for unit in ("o", "Ko", "Mo", "Go"):
        if n < 1024 or unit == "Go":
            return ("%d %s" % (n, unit)) if unit == "o" else ("%.1f %s" % (n, unit))
        n /= 1024.0


_IMG_TAG = re.compile(r"<img\b[^>]*>", re.I)
_REMOTE_SRC = re.compile(r"""\bsrc\s*=\s*(["']?)\s*(https?:)?//""", re.I)


def has_remote_content(h):
    return bool(_REMOTE_SRC.search(h or "")) or bool(
        re.search(r"url\(\s*['\"]?(https?:)?//", h or "", re.I))


def block_remote_content(h):
    def fix(m):
        return _REMOTE_SRC.sub(
            lambda mm: "data-blocked-src=" + mm.group(1) + (mm.group(2) or "") + "//", m.group(0))
    h = _IMG_TAG.sub(fix, h or "")
    h = re.sub(r"url\(\s*(['\"]?)(https?:)?//[^)]*\)", "none", h, flags=re.I)
    h = re.sub(r"\bbackground\s*=\s*(['\"]?)https?://[^\s>\"']*\1", "", h, flags=re.I)
    return h


def split_addresses(s):
    from email.utils import getaddresses
    return [a for _, a in getaddresses([s or ""]) if a]


def normalize_subject(s):
    return re.sub(r"^\s*((re|fwd?|tr|réf)\s*:\s*)+", "", s or "", flags=re.I).strip()


def sanitize_html(h):
    """Nettoyage minimal avant d'injecter du HTML reçu dans l'éditeur (JS actif)."""
    h = re.sub(r"(?is)<(script|style|iframe|object|embed|head|title)\b.*?</\1\s*>", "", h or "")
    h = re.sub(r"(?is)<(script|iframe|object|embed|link|meta|base)\b[^>]*>", "", h)
    h = re.sub(r"(?is)\son\w+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", "", h)
    h = re.sub(r"(?is)(href|src)\s*=\s*([\"']?)\s*javascript:[^\"'>\s]*\2", "", h)
    h = re.sub(r"(?is)</?(html|body)[^>]*>", "", h)
    return block_remote_content(h)


# ------------------------------------------------------------ conversations
def thread_key(message_id: str, references: str, subject: str, nsubj_hint: str = "") -> str:
    """Clé de conversation : racine des « References » ; sinon identifiant du message ; sinon objet normalisé."""
    refs = re.findall(r"<[^>]+>", references or "")
    if refs:
        return refs[0]
    if message_id and message_id.strip():
        mid = re.findall(r"<[^>]+>", message_id)
        return mid[0] if mid else message_id.strip()
    return "s:" + normalize_subject(subject).lower()[:120]


# -------------------------------------------------------------- pièces jointes
TEXT_PREVIEW_EXT = (".txt", ".md", ".csv", ".log", ".json", ".xml", ".ini", ".conf", ".yml", ".yaml", ".ics", ".vcf")
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg")


def attachment_kind(att) -> str:
    """'image' | 'text' | 'pdf' | 'archive' | 'file' (pour l'icône et l'aperçu)."""
    name = (att.get("filename") or "").lower()
    if name.endswith(IMAGE_EXT):
        return "image"
    if name.endswith(TEXT_PREVIEW_EXT):
        return "text"
    if name.endswith(".pdf"):
        return "pdf"
    if name.endswith((".zip", ".tar", ".gz", ".7z", ".rar", ".bz2", ".xz")):
        return "archive"
    return "file"


def unique_path(directory: str, name: str) -> str:
    """Chemin libre dans `directory` (« fichier (2).pdf » si le nom existe déjà)."""
    import os
    base, ext = os.path.splitext(os.path.basename(name) or "fichier")
    path, n = os.path.join(directory, base + ext), 2
    while os.path.exists(path):
        path = os.path.join(directory, "%s (%d)%s" % (base, n, ext))
        n += 1
    return path


def save_attachments(atts, directory: str):
    """Copie les pièces jointes dans `directory` sans rien écraser ; retourne les chemins créés."""
    import os
    import shutil
    os.makedirs(directory, exist_ok=True)
    out = []
    for a in atts:
        try:
            dst = unique_path(directory, a["filename"])
            shutil.copyfile(a["path"], dst)
            out.append(dst)
        except OSError:
            continue
    return out
