"""Carnet d'adresses : analyse des en-têtes, import / export vCard (.vcf)."""
import re
from email.utils import getaddresses
from typing import Dict, List, Tuple

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def parse_addresses(header: str) -> List[Tuple[str, str]]:
    """[(nom, adresse)] depuis un en-tête To / Cc / From (adresses invalides ignorées)."""
    return [(n.strip(), a.strip().lower()) for n, a in getaddresses([header or ""]) if EMAIL_RE.match(a.strip())]


def _unfold(text: str) -> str:
    return re.sub(r"\r?\n[ \t]", "", text)


def _unesc(v: str) -> str:
    return v.replace("\\n", "\n").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")


def _esc(v: str) -> str:
    return v.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def parse_vcf(text: str) -> List[Dict[str, str]]:
    """Contacts d'un fichier vCard (2.1 / 3.0 / 4.0) : name, email, phone, org, notes ; sans adresse e-mail : ignoré."""
    out, cur = [], None
    for line in _unfold(text or "").splitlines():
        u = line.upper()
        if u.startswith("BEGIN:VCARD"):
            cur = {"name": "", "email": "", "phone": "", "org": "", "notes": ""}
            continue
        if u.startswith("END:VCARD"):
            if cur and cur["email"]:
                out.append(cur)
            cur = None
            continue
        if cur is None or ":" not in line:
            continue
        name, _, raw = line.partition(":")
        key = name.split(";")[0].upper()
        value = _unesc(raw).strip()
        comps = [_unesc(p).strip() for p in re.split(r"(?<!\\);", raw) if p.strip()]   # composants structurés (N, ORG)
        if key == "FN" and value:
            cur["name"] = value[:200]
        elif key == "N" and not cur["name"]:
            cur["name"] = " ".join(reversed(comps[:2]))[:200] if comps else ""
        elif key == "EMAIL" and not cur["email"] and EMAIL_RE.match(value):
            cur["email"] = value.lower()[:200]
        elif key == "TEL" and not cur["phone"]:
            cur["phone"] = value[:60]
        elif key == "ORG" and not cur["org"]:
            cur["org"] = " ".join(comps)[:120]
        elif key == "NOTE" and not cur["notes"]:
            cur["notes"] = value[:500]
    return out


def to_vcf(contacts: List[Dict[str, str]]) -> str:
    out = []
    for c in contacts:
        out += ["BEGIN:VCARD", "VERSION:3.0", "FN:" + _esc(c.get("name") or c["email"]), "EMAIL:" + c["email"]]
        if c.get("phone"):
            out.append("TEL:" + _esc(c["phone"]))
        if c.get("org"):
            out.append("ORG:" + _esc(c["org"]))
        if c.get("notes"):
            out.append("NOTE:" + _esc(c["notes"]))
        out.append("END:VCARD")
    return "\r\n".join(out) + ("\r\n" if out else "")


# ------------------------------------------------------------------ saisie des destinataires (auto-complétion)
def token_bounds(text: str, pos: int = None) -> Tuple[int, int]:
    """(début, fin) de l'adresse en cours de saisie : le texte entre la virgule / le point-virgule précédent(e) et le suivant(e), espaces de tête exclus.
    Une virgule entre guillemets (« "Dupont, Jean" <j@x.be> ») ne coupe pas."""
    text = text or ""
    pos = len(text) if pos is None else max(0, min(pos, len(text)))
    start, quoted = 0, False
    for i, ch in enumerate(text[:pos]):
        if ch == '"':
            quoted = not quoted
        elif ch in ",;" and not quoted:
            start = i + 1
    end, q = len(text), quoted
    for i in range(pos, len(text)):
        ch = text[i]
        if ch == '"':
            q = not q
        elif ch in ",;" and not q:
            end = i
            break
    while start < end and text[start] == " ":
        start += 1
    return start, end


def current_token(text: str, pos: int = None) -> str:
    s, e = token_bounds(text, pos)
    return (text or "")[s:e]


def format_entry(name: str, email: str) -> str:
    """« Nom <adresse> » (nom entre guillemets s'il contient une virgule, un point-virgule ou des guillemets) ; l'adresse seule sans nom."""
    name = (name or "").strip()
    if not name or name.lower() == (email or "").lower():
        return email
    if any(c in name for c in ',;"<>@'):
        name = '"%s"' % name.replace("\\", "\\\\").replace('"', '\\"')
    return "%s <%s>" % (name, email)


def apply_choice(text: str, pos: int, entry: str, sep: str = ", ") -> Tuple[str, int]:
    """Remplace l'adresse en cours de saisie par `entry` ; retourne (nouveau texte, position du curseur). Les autres destinataires sont conservés."""
    text = text or ""
    s, e = token_bounds(text, pos)
    tail = text[e:].lstrip(" ,;") if text[e:].strip(" ,;") else ""
    new = text[:s] + entry + (sep + tail if tail else sep)
    return new, len(text[:s] + entry + sep)


def fold(s: str) -> str:
    """Minuscules sans accents, pour chercher « societe » dans « Société »."""
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", (s or "").lower()) if unicodedata.category(c) != "Mn")


def matches(query: str, *fields: str) -> bool:
    """Tous les mots de la saisie se retrouvent (sans accents ni casse) dans le nom, l'adresse, la société…"""
    words = fold(query).split()
    hay = fold(" ".join(f or "" for f in fields))
    return bool(words) and all(w in hay for w in words)
