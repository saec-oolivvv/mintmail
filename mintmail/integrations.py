"""Intégrations de MintMail, comme celles de Spark : envoyer un message vers Teams ou Slack (webhook entrant), l'enregistrer en note Markdown
(dossier, Obsidian, Bear), en faire une tâche Todoist ou une page Notion. Rien n'est envoyé sans geste de votre part ; les clés et adresses
de webhook sont gardées dans le trousseau, jamais dans le fichier de réglages. Module SANS Qt, testable partout."""
import ipaddress
import json
import os
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List, Tuple

from .i18n import tr

SERVICES = ("teams", "slack", "notes", "obsidian", "bear", "todoist", "notion")
SECRET_KEYS = {"teams": "integ:teams", "slack": "integ:slack", "todoist": "integ:todoist", "notion": "integ:notion"}
BODY_MAX = 3000


def labels() -> Dict[str, str]:
    return {"teams": "Microsoft Teams", "slack": "Slack", "notes": tr("Note Markdown (dossier)"), "obsidian": "Obsidian",
            "bear": "Bear", "todoist": "Todoist", "notion": "Notion"}


def settings(config) -> Dict:
    d = config.get("integrations") or {}
    return d if isinstance(d, dict) else {}


def available(config, secret_of=lambda k: "") -> List[str]:
    """Services utilisables maintenant (réglés et, si besoin, avec leur clé enregistrée)."""
    s, out = settings(config), []
    if s.get("teams") and secret_of("integ:teams"):
        out.append("teams")
    if s.get("slack") and secret_of("integ:slack"):
        out.append("slack")
    if s.get("notes_dir"):
        out.append("notes")
    if s.get("obsidian_vault"):
        out.append("obsidian")
    if s.get("bear"):
        out.append("bear")
    if s.get("todoist") and secret_of("integ:todoist"):
        out.append("todoist")
    if s.get("notion_db") and secret_of("integ:notion"):
        out.append("notion")
    return out


# ------------------------------------------------------------------ contenu
def clean_body(msg, limit=BODY_MAX) -> str:
    text = (msg.text or re.sub(r"<[^>]+>", " ", msg.html or "") or msg.snippet or "")
    text = re.sub(r"[ \t]+", " ", text.replace("\r", ""))
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:limit] + ("…" if len(text) > limit else "")


def summary_lines(msg) -> List[str]:
    when = time.strftime("%d/%m/%Y %H:%M", time.localtime(msg.date)) if getattr(msg, "date", 0) else ""
    return ["%s <%s>" % (msg.sender_name, msg.sender_email) if msg.sender_name else msg.sender_email, when]


def markdown_of(msg) -> str:
    """Note Markdown d'un message : titre, en-têtes, corps."""
    who, when = summary_lines(msg)
    q = lambda s: json.dumps(s or "", ensure_ascii=False)
    return ("---\nsujet: %s\nde: %s\ndate: %s\nsource: mintmail\n---\n\n# %s\n\n**%s** — %s\n\n%s\n"
            % (q(msg.subject), q(who), q(when), msg.subject or "(Sans objet)", who, when, clean_body(msg, 20000)))


# ------------------------------------------------------------------ sécurité des adresses
def public_https(url: str) -> bool:
    """Adresse HTTPS vers un hôte public (jamais le réseau local ni l'ordinateur lui-même)."""
    try:
        u = urllib.parse.urlsplit(url)
    except ValueError:
        return False
    if u.scheme != "https" or not u.hostname or u.username or u.password:
        return False
    host = u.hostname.lower()
    if host == "localhost" or host.endswith((".local", ".internal", ".lan")):
        return False
    try:
        addrs = {ipaddress.ip_address(host)}
    except ValueError:
        try:
            addrs = {ipaddress.ip_address(i[4][0]) for i in socket.getaddrinfo(host, u.port or 443, proto=socket.IPPROTO_TCP)}
        except OSError:
            return True                       # pas de résolution possible ici (hors ligne) : l'envoi échouera de lui-même
    return not any(a.is_private or a.is_loopback or a.is_link_local or a.is_reserved or a.is_multicast for a in addrs)


def _call(url, payload=None, headers=None, method="POST", timeout=15.0) -> Tuple[bool, int, str]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    h = {"Content-Type": "application/json; charset=utf-8", "User-Agent": "MintMail"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return 200 <= r.status < 300, r.status, r.read(200000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return False, e.code, e.read(2000).decode("utf-8", "replace")
    except (urllib.error.URLError, OSError) as e:
        return False, 0, str(getattr(e, "reason", e))[:120]


def _result(ok, status, body, name) -> Tuple[bool, str]:
    if ok:
        return True, tr("Envoyé vers %s") % name
    hint = {0: body, 401: tr("clé refusée"), 403: tr("accès refusé"), 404: tr("adresse introuvable"), 429: tr("trop de requêtes, réessayez plus tard")}.get(status, "")
    return False, "%s : %s" % (name, ("HTTP %d %s" % (status, hint)).strip() if status else hint)


# ------------------------------------------------------------------ Teams / Slack
def webhook_payload(kind, msg) -> Dict:
    who, when = summary_lines(msg)
    body = clean_body(msg, 1500)
    title = msg.subject or "(Sans objet)"
    if kind == "slack":
        return {"text": "*%s*\n_%s — %s_\n\n%s" % (title, who, when, body)}
    return {"@type": "MessageCard", "@context": "https://schema.org/extensions", "summary": title, "themeColor": "1A73FF",   # i18n: skip
            "title": title, "text": "**%s** — %s\n\n%s" % (who, when, body.replace("\n", "\n\n"))}


def send_webhook(kind, url, msg) -> Tuple[bool, str]:
    name = labels()[kind]
    if not public_https(url):
        return False, tr("%s : l'adresse doit être en HTTPS et publique") % name
    return _result(*_call(url, webhook_payload(kind, msg)), name)


# ------------------------------------------------------------------ notes Markdown
def export_markdown(msg, folder) -> str:
    """Écrit la note dans `folder` (créé au besoin) et retourne son chemin ; ne remplace jamais un fichier existant."""
    folder = os.path.expanduser(folder)
    os.makedirs(folder, exist_ok=True)
    base = re.sub(r"[^\w.\- ]", "_", msg.subject or "message").strip()[:80] or "message"
    day = time.strftime("%Y-%m-%d", time.localtime(msg.date or time.time()))
    path, n = os.path.join(folder, "%s %s.md" % (day, base)), 1
    while os.path.exists(path):
        n += 1
        path = os.path.join(folder, "%s %s (%d).md" % (day, base, n))
    with open(path, "w", encoding="utf-8") as f:
        f.write(markdown_of(msg))
    return path


def obsidian_uri(vault, msg) -> str:
    name = re.sub(r'[\\/:*?"<>|#^\[\]]', "_", msg.subject or "message")[:80]
    return "obsidian://new?vault=%s&name=%s&content=%s" % (urllib.parse.quote(vault, safe=""), urllib.parse.quote(name, safe=""),
                                                           urllib.parse.quote(markdown_of(msg), safe=""))


def bear_uri(msg) -> str:
    return "bear://x-callback-url/create?title=%s&text=%s&tags=mintmail" % (urllib.parse.quote(msg.subject or "", safe=""),
                                                                           urllib.parse.quote(clean_body(msg, 8000), safe=""))


# ------------------------------------------------------------------ Todoist / Notion
def todoist_task(token, msg, project="", due="") -> Tuple[bool, str]:
    who, when = summary_lines(msg)
    payload = {"content": (msg.subject or "(Sans objet)")[:300], "description": "%s — %s\n\n%s" % (who, when, clean_body(msg, 1500))}
    if project:
        payload["project_id"] = project
    if due:
        payload["due_string"] = due
    return _result(*_call("https://api.todoist.com/rest/v2/tasks", payload, {"Authorization": "Bearer " + token}), labels()["todoist"])


def notion_page(token, database_id, msg) -> Tuple[bool, str]:
    h = {"Authorization": "Bearer " + token, "Notion-Version": "2022-06-28"}
    name = labels()["notion"]
    ok, status, body = _call("https://api.notion.com/v1/databases/" + urllib.parse.quote(database_id, safe=""), None, h, "GET")
    if not ok:
        return _result(ok, status, body, name)
    try:
        title_prop = next(k for k, v in json.loads(body).get("properties", {}).items() if v.get("type") == "title")
    except (StopIteration, ValueError):
        return False, tr("%s : cette base n'a pas de colonne titre") % name
    who, when = summary_lines(msg)
    chunks = [clean_body(msg, 6000)[i:i + 1900] for i in range(0, max(1, len(clean_body(msg, 6000))), 1900)]
    payload = {"parent": {"database_id": database_id},
               "properties": {title_prop: {"title": [{"text": {"content": (msg.subject or "(Sans objet)")[:200]}}]}},
               "children": [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": "%s — %s" % (who, when)}}]}}] +
                           [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": c}}]}} for c in chunks if c]}
    return _result(*_call("https://api.notion.com/v1/pages", payload, h), name)
