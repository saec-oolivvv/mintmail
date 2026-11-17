"""Importer ses boîtes mail et réglages depuis un autre logiciel (Thunderbird, Evolution, ou simplement ses adresses pour Outlook / Spark / Apple Mail / Gmail…),
SANS Qt. Les mots de passe ne sont JAMAIS lus chez les autres logiciels (chiffrés par eux) : après l'import, on saisit le mot de passe de chaque compte
(ou on clique « Se connecter » pour Gmail / Outlook). Fichiers lus en lecture seule ; rien n'est modifié chez l'autre logiciel."""
import configparser
import csv
import io
import os
import re
from typing import Dict, List
from .i18n import tr

EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

# domaine -> (serveur IMAP, port, serveur SMTP, port, connexion OAuth ou "") — fournisseurs courants ; le reste est deviné et marqué « à vérifier »
PROVIDERS = {
    "gmail.com": ("imap.gmail.com", 993, "smtp.gmail.com", 587, "google"), "googlemail.com": ("imap.gmail.com", 993, "smtp.gmail.com", 587, "google"),
    "outlook.com": ("outlook.office365.com", 993, "smtp.office365.com", 587, "microsoft"), "hotmail.com": ("outlook.office365.com", 993, "smtp.office365.com", 587, "microsoft"),
    "live.com": ("outlook.office365.com", 993, "smtp.office365.com", 587, "microsoft"), "outlook.be": ("outlook.office365.com", 993, "smtp.office365.com", 587, "microsoft"),
    "hotmail.fr": ("outlook.office365.com", 993, "smtp.office365.com", 587, "microsoft"), "live.be": ("outlook.office365.com", 993, "smtp.office365.com", 587, "microsoft"),
    "icloud.com": ("imap.mail.me.com", 993, "smtp.mail.me.com", 587, ""), "me.com": ("imap.mail.me.com", 993, "smtp.mail.me.com", 587, ""),
    "mac.com": ("imap.mail.me.com", 993, "smtp.mail.me.com", 587, ""),
    "yahoo.com": ("imap.mail.yahoo.com", 993, "smtp.mail.yahoo.com", 587, ""), "yahoo.fr": ("imap.mail.yahoo.com", 993, "smtp.mail.yahoo.com", 587, ""),
    "skynet.be": ("mail.proximus.be", 993, "relay.proximus.be", 587, ""), "proximus.be": ("mail.proximus.be", 993, "relay.proximus.be", 587, ""),
    "infomaniak.ch": ("mail.infomaniak.com", 993, "mail.infomaniak.com", 587, ""), "ik.me": ("mail.infomaniak.com", 993, "mail.infomaniak.com", 587, ""),
}
SECURITY_STARTTLS = ("starttls", "2")


def account_dict(email, name="", imap_host="", imap_port=993, smtp_host="", smtp_port=587, username="", imap_ssl=True, oauth="", source="", note="",
                 signature_html="", aliases=None) -> Dict:
    return {"source": source, "email": email.strip(), "name": name.strip(), "username": (username or email).strip(), "imap_host": imap_host, "imap_port": int(imap_port or 993),
            "smtp_host": smtp_host, "smtp_port": int(smtp_port or 587), "imap_ssl": bool(imap_ssl), "oauth": oauth, "note": note,
            "signature_html": signature_html, "aliases": aliases or []}


def from_address(email, name="", source="") -> Dict:
    """Réglages d'après l'adresse seule (fournisseurs connus ; sinon imap.<domaine> / smtp.<domaine>, à vérifier)."""
    dom = email.split("@")[-1].lower()
    p = PROVIDERS.get(dom)
    if p:
        return account_dict(email, name, p[0], p[1], p[2], p[3], email, True, p[4], source)
    return account_dict(email, name, "imap." + dom, 993, "smtp." + dom, 587, email, True, "", source, "check")


def from_addresses(text, source="") -> List[Dict]:
    """Une boîte par adresse trouvée dans le texte collé (une par ligne, séparées par virgules, ou « Nom <adresse> »)."""
    seen, out = set(), []
    for m in EMAIL.finditer(text or ""):
        e = m.group(0).strip(".")
        if e.lower() not in seen:
            seen.add(e.lower())
            out.append(from_address(e, "", source))
    return out


# ------------------------------------------------------------------ Thunderbird
def parse_prefs(text) -> Dict:
    """prefs.js de Mozilla : user_pref("clé", valeur);"""
    out = {}
    for m in re.finditer(r'user_pref\("([^"]+)",\s*(.+?)\);\s*$', text or "", re.M):
        v = m.group(2).strip()
        if v.startswith('"') and v.endswith('"'):
            v = v[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        elif v in ("true", "false"):
            v = v == "true"
        else:
            try:
                v = int(v)
            except ValueError:
                pass
        out[m.group(1)] = v
    return out


def parse_thunderbird(prefs_text) -> List[Dict]:
    """Comptes IMAP de Thunderbird : serveur entrant, serveur sortant, identité (nom, adresse, signature) et alias supplémentaires."""
    p = parse_prefs(prefs_text)
    out = []
    for key, val in sorted(p.items()):
        m = re.match(r"mail\.account\.(account\d+)\.server$", key)
        if not m:
            continue
        acc, srv = m.group(1), val
        if p.get("mail.server.%s.type" % srv) != "imap":
            continue
        idents = [i for i in str(p.get("mail.account.%s.identities" % acc, "")).split(",") if i]
        def ident(i):
            return {"email": str(p.get("mail.identity.%s.useremail" % i, "")), "name": str(p.get("mail.identity.%s.fullName" % i, "")),
                    "sig": str(p.get("mail.identity.%s.htmlSigText" % i, "")),
                    "smtp": str(p.get("mail.identity.%s.smtpServer" % i, ""))}
        ids = [ident(i) for i in idents]
        main = next((i for i in ids if i["email"]), None)
        user = str(p.get("mail.server.%s.userName" % srv, ""))
        host = str(p.get("mail.server.%s.hostname" % srv, ""))
        if not host or not (main or "@" in user):
            continue
        email = main["email"] if main else user
        sec = p.get("mail.server.%s.socketType" % srv, 3)
        port = int(p.get("mail.server.%s.port" % srv, 993) or 993)
        smtp = main["smtp"] if main and main["smtp"] else str(p.get("mail.smtpserver.default", "") or p.get("mail.smtp.defaultserver", ""))
        sh = str(p.get("mail.smtpserver.%s.hostname" % smtp, "")) if smtp else ""
        sp = int(p.get("mail.smtpserver.%s.port" % smtp, 587) or 587) if smtp else 587
        aliases = [{"email": i["email"], "name": i["name"], "signature_html": i["sig"]} for i in ids if i["email"] and i["email"].lower() != email.lower()]
        a = account_dict(email, main["name"] if main else "", host, port, sh or "smtp." + email.split("@")[-1], sp, user or email,
                         True, "", "Thunderbird", "" if sh else "check",
                         main["sig"] if main else "", aliases)
        a["imap_ssl"] = port == 993 or sec == 3
        out.append(a)
    return out


def thunderbird_prefs_files(home=None) -> List[str]:
    """Fichiers prefs.js des profils Thunderbird trouvés (Linux, snap, flatpak, macOS, Windows)."""
    home = home or os.path.expanduser("~")
    roots = [os.path.join(home, ".thunderbird"), os.path.join(home, "snap/thunderbird/common/.thunderbird"),
             os.path.join(home, ".var/app/org.mozilla.Thunderbird/.thunderbird"), os.path.join(home, "Library/Thunderbird"),
             os.path.join(os.environ.get("APPDATA", os.path.join(home, "AppData/Roaming")), "Thunderbird")]
    out = []
    for root in roots:
        ini = os.path.join(root, "profiles.ini")
        if not os.path.isfile(ini):
            continue
        cp = configparser.RawConfigParser()
        try:
            cp.read(ini, encoding="utf-8")
        except (configparser.Error, OSError):
            continue
        for sec in cp.sections():
            path = cp.get(sec, "Path", fallback="")
            if not path or not sec.lower().startswith("profile"):
                continue
            full = path if os.path.isabs(path) else os.path.join(root, path)
            f = os.path.join(full, "prefs.js")
            if os.path.isfile(f) and f not in out:
                out.append(f)
    return out


# ------------------------------------------------------------------ Evolution
def parse_evolution(sources: Dict[str, str]) -> List[Dict]:
    """Comptes IMAP d'Evolution : {nom de fichier .source: contenu} (~/.config/evolution/sources)."""
    cps = {}
    for name, text in sources.items():
        cp = configparser.RawConfigParser(strict=False)
        cp.optionxform = str
        try:
            cp.read_string(text)
        except configparser.Error:
            continue
        cps[os.path.basename(name)[:-7] if name.endswith(".source") else os.path.basename(name)] = cp
    out = []
    for uid, cp in cps.items():
        if not cp.has_section("Mail Account"):
            continue
        if cp.get("Mail Account", "BackendName", fallback="") != "imapx" or not cp.has_section("Authentication"):
            continue
        host = cp.get("Authentication", "Host", fallback="")
        user = cp.get("Authentication", "User", fallback="")
        port = int(cp.get("Authentication", "Port", fallback="993") or 993)
        method = cp.get("Security", "Method", fallback="") if cp.has_section("Security") else ""
        ident = None
        # l'identité est une source distincte dont le parent est le compte
        for c in cps.values():
            if c.has_section("Mail Identity") and c.get("Data Source", "Parent", fallback="") == uid:
                ident = c
                break
        email = ident.get("Mail Identity", "Address", fallback="") if ident else (user if "@" in user else "")
        if not host or not email:
            continue
        name = ident.get("Mail Identity", "Name", fallback="") if ident else ""
        smtp_host, smtp_port = "", 587
        for c in cps.values():
            if c.has_section("Mail Transport") and c.get("Data Source", "Parent", fallback="") != "" and c.has_section("Authentication"):
                if c.get("Data Source", "DisplayName", fallback="") and c.get("Authentication", "User", fallback="") in (user, email):
                    smtp_host, smtp_port = c.get("Authentication", "Host", fallback=""), int(c.get("Authentication", "Port", fallback="587") or 587)
                    break
        a = account_dict(email, name, host, port, smtp_host or "smtp." + email.split("@")[-1], smtp_port, user or email, port == 993 or method == "ssl-on-alternate-port",
                         "", "Evolution", "" if smtp_host else "check")
        out.append(a)
    return out


def evolution_sources(home=None) -> Dict[str, str]:
    d = os.path.join(home or os.path.expanduser("~"), ".config", "evolution", "sources")
    out = {}
    try:
        for f in os.listdir(d):
            if f.endswith(".source"):
                with open(os.path.join(d, f), encoding="utf-8", errors="replace") as fh:
                    out[f] = fh.read()
    except OSError:
        pass
    return out


def detect(home=None) -> List[Dict]:
    """Tout ce qu'on trouve sur cet ordinateur : [{source, accounts: [...]}] ; vide si aucun logiciel connu n'est installé."""
    found = []
    tb = []
    for f in thunderbird_prefs_files(home):
        try:
            with open(f, encoding="utf-8", errors="replace") as fh:
                tb += parse_thunderbird(fh.read())
        except OSError:
            continue
    if tb:
        found.append({"source": "Thunderbird", "accounts": tb})
    ev = parse_evolution(evolution_sources(home))
    if ev:
        found.append({"source": "Evolution", "accounts": ev})
    return found


# ------------------------------------------------------------------ contacts (Outlook, Google, Spark, Apple : export CSV)
NAME_COLS = ("name", "display name", "full name", "nom", "nom complet", "first name", "prénom", "given name")  # i18n: skip
MAIL_COLS = ("e-mail address", "email address", "email", "e-mail", "e-mail 1 - value", "adresse e-mail", "adresse de messagerie", "mail", "courriel")


def parse_contacts_csv(text) -> List[Dict]:
    """Contacts d'un export CSV d'Outlook, Google Contacts, Spark ou Apple : [{name, email}] (sans adresse valide : ignoré)."""
    text = (text or "").lstrip("﻿")
    try:
        dialect = csv.Sniffer().sniff(text[:2000], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rd = csv.reader(io.StringIO(text), dialect)
    rows = list(rd)
    if not rows:
        return []
    head = [h.strip().lower() for h in rows[0]]
    mi = next((i for i, h in enumerate(head) if h in MAIL_COLS), None)
    if mi is None:
        mi = next((i for i, h in enumerate(head) if "mail" in h), None)
    if mi is None:
        return []
    ni = [i for i, h in enumerate(head) if h in NAME_COLS]
    out, seen = [], set()
    for r in rows[1:]:
        if mi >= len(r):
            continue
        m = EMAIL.search(r[mi])
        if not m or m.group(0).lower() in seen:
            continue
        seen.add(m.group(0).lower())
        out.append({"name": " ".join(r[i].strip() for i in ni if i < len(r) and r[i].strip()), "email": m.group(0)})
    return out


# ------------------------------------------------------------------ application
def apply(config, accounts: List[Dict], new_id) -> Dict:
    """Ajoute les comptes choisis (déjà présents : ignorés) avec leur signature et leurs alias ; retourne {added, skipped, ids}.
    Aucun mot de passe : chaque compte importé est à compléter (mot de passe ou « Se connecter »)."""
    have = {a["email"].lower() for a in config.get("accounts") or []}
    added, skipped, ids = 0, 0, []
    cur = list(config.get("accounts") or [])
    idents = list(config.get("identities") or [])
    for a in accounts:
        e = a["email"].lower()
        if e in have or not EMAIL.fullmatch(a["email"]) or not a["imap_host"] or not a["smtp_host"]:
            skipped += 1
            continue
        aid = new_id()
        acc = {"id": aid, "name": a["name"] or a["email"].split("@")[0], "email": a["email"], "username": a["username"], "imap_host": a["imap_host"],
               "imap_port": a["imap_port"], "smtp_host": a["smtp_host"], "smtp_port": a["smtp_port"], "imap_ssl": a["imap_ssl"],
               "signature_html": a.get("signature_html", ""), "has_password": False, "imported_from": a.get("source", "")}
        if a.get("oauth"):
            acc["auth"], acc["oauth_provider"] = "oauth2", a["oauth"]
        cur.append(acc)
        have.add(e)
        for al in a.get("aliases") or []:
            if al["email"].lower() not in have:
                idents.append({"id": new_id(), "account": aid, "email": al["email"], "name": al.get("name", ""), "signature_html": al.get("signature_html", "")})
                have.add(al["email"].lower())
        added += 1
        ids.append(aid)
    config["accounts"], config["identities"] = cur, idents
    config.save()
    return {"added": added, "skipped": skipped, "ids": ids}
