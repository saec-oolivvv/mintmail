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
