"""Signatures, identités d'envoi (alias), modèles de réponse, contacts et aide IA à l'écriture — SANS Qt.
Mêmes règles que les pages « Signatures », « Identités d'envoi », « Modèles de réponse » et « Contacts » de la version GTK ; testé sur le moteur seul."""
import re
from typing import Dict, List, Optional, Tuple

from .. import contacts as vcf
from ..backend import new_account_id
from ..i18n import tr
from ..util import sanitize_html
from . import sigimages as SI

SIG_TEMPLATE = tr('<p><b>Prénom Nom</b><br>Fonction — Société<br>'
                  '📞 +32 000 00 00 00 · ✉ vous@exemple.be<br>'
                  '<a href="https://exemple.be">exemple.be</a></p>')
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# opérations IA du compositeur : (libellé, opération) ; None = séparateur
AI_OPS = [(tr("Rédiger à partir d'une idée…"), "write"), None,
          (tr("Améliorer le texte"), "improve"), (tr("Corriger l'orthographe"), "fix"), (tr("Raccourcir"), "shorten"), (tr("Développer"), "expand"),
          (tr("Ton plus formel"), "formal"), (tr("Ton plus amical"), "friendly"), None,
          (tr("Traduire en français"), "translate:fr"), (tr("Traduire en anglais"), "translate:en"), (tr("Traduire en néerlandais"), "translate:nl"),
          (tr("Traduire en allemand"), "translate:de"), (tr("Traduire en espagnol"), "translate:es"), None,
          (tr("Suggérer un objet"), "subject")]


# ------------------------------------------------------------------ signatures
def get_signature(config, account_id: str) -> str:
    a = next((x for x in config["accounts"] if x["id"] == account_id), None)
    return (a or {}).get("signature_html", "") or ""


def set_signature(config, account_id: str, html: str) -> bool:
    a = next((x for x in config["accounts"] if x["id"] == account_id), None)
    if a is None:
        return False
    a["signature_html"] = (html or "")[:20000]
    config["accounts"] = list(config["accounts"])
    config.save()
    return True


def signature_preview(html: str) -> str:
    """HTML de l'aperçu (nettoyé : jamais de script)."""
    from ..htmlsafe import sanitize
    return "<div style='font-size:14px'>%s</div>" % sanitize(SI.to_display(html or ""), keep_style=True, allow_remote_images=False)


# ------------------------------------------------------------------ identités (alias)
def identities(config) -> List[dict]:
    return list(config.get("identities", []) or [])


def identity_save(config, cur_id: Optional[str], account_id: str, name: str, email: str, signature: str) -> Tuple[Optional[dict], str]:
    email = (email or "").strip()
    if not EMAIL_RE.match(email) or not account_id:
        return None, tr("Adresse et compte d'envoi requis.")
    ident = {"id": cur_id or new_account_id(), "account": account_id, "name": (name or "").strip()[:100], "email": email[:200],
             "signature_html": (signature or "")[:20000]}
    config["identities"] = [i for i in identities(config) if i["id"] != ident["id"]] + [ident]
    config.save()
    return ident, tr("Identité enregistrée ✔")


def identity_delete(config, ident_id: str) -> bool:
    before = identities(config)
    config["identities"] = [i for i in before if i["id"] != ident_id]
    config.save()
    return len(config["identities"]) != len(before)


# ------------------------------------------------------------------ modèles de réponse
def templates(config) -> List[dict]:
    return config["templates"]


def template_add(config) -> int:
    config["templates"].append({"name": tr("Nouveau modèle"), "html": tr("<p>Bonjour,</p>")})
    config.save()
    return len(config["templates"]) - 1


def template_save(config, i: int, name: str, html: str) -> bool:
    if i is None or not 0 <= i < len(config["templates"]):
        return False
    config["templates"][i] = {"name": (name or "").strip() or tr("Sans titre"), "html": html or ""}
    config.save()
    return True


def template_delete(config, i: int) -> bool:
    if i is None or not 0 <= i < len(config["templates"]):
        return False
    del config["templates"][i]
    config.save()
    return True


def template_html(config, i: int) -> str:
    """HTML d'un modèle prêt à insérer (nettoyé)."""
    return sanitize_html(config["templates"][i]["html"]) if 0 <= i < len(config["templates"]) else ""


# ------------------------------------------------------------------ contacts
def contact_save(config, cache, email, name="", phone="", org="", notes="") -> bool:
    email = (email or "").strip().lower()
    if "@" not in email or len(email) > 200:
        return False
    c = {"name": name.strip()[:200], "phone": phone.strip()[:60], "org": org.strip()[:120], "notes": notes.strip()[:500]}
    contacts = dict(config.get("contacts") or {})
    contacts[email] = c
    config["contacts"] = contacts
    config.save()
    cache.contact_upsert(email, c["name"], c["phone"], c["org"], c["notes"], source="manual")
    return True


def contact_remove(config, cache, email) -> None:
    contacts = dict(config.get("contacts") or {})
    contacts.pop((email or "").lower(), None)
    config["contacts"] = contacts
    config.save()
    cache.contact_delete(email)


def contact_label(c: Dict) -> str:
    return (c.get("name") or c["email"]) + ("" if c.get("source") == "manual" else "  (auto)")


def import_vcf(config, cache, text: str) -> int:
    found = vcf.parse_vcf(text)
    return sum(1 for c in found if contact_save(config, cache, c["email"], c["name"], c["phone"], c["org"], c["notes"]))


def export_vcf(cache) -> str:
    return vcf.to_vcf(cache.contacts_list(source="manual", limit=5000))


def add_sender_to_contacts(config, cache, msg) -> Tuple[bool, str]:
    ok = contact_save(config, cache, msg.sender_email, msg.sender_name or "")
    return ok, (tr("%s ajouté aux contacts") % (msg.sender_name or msg.sender_email)) if ok else tr("Adresse e-mail invalide.")


# ------------------------------------------------------------------ aide IA à l'écriture
def ai_run(ai, op: str, text: str, subject: str = "", to: str = "", idea: str = "", quoted: str = "") -> Tuple[str, str]:
    """(cible, résultat) : cible « subject » (objet suggéré) ou « body » (texte du message). Réseau : à lancer en arrière-plan."""
    if op == "write":
        return "body", ai.write_from_prompt(idea, subject, to, quoted)
    if op == "subject":
        return "subject", ai.subject_for(text)
    return "body", ai.rewrite(text, op)


def ai_needs_text(op: str) -> bool:
    return op != "write"
