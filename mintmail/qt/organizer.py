"""Organisation SANS Qt : tâches, page « Aujourd'hui », agenda (Google / CalDAV / .ics), invitations, créneaux, relances, désabonnement,
pièces jointes et fil de conversation. Mêmes règles que extras.py / reader.py de la version GTK ; testé sur le moteur seul."""
import datetime
import os
import re
import tempfile
import time
import uuid
from typing import Dict, List, Optional, Tuple

from .. import caldav, gcal, ical, oauth, slots, unsub
from .. import tasks as tk
from ..ai_engine import make_ics
from ..i18n import tr
from ..models import Outgoing
from ..util import attachment_kind, attachment_risk, human_size, normalize_subject, save_attachments, split_addresses


# ------------------------------------------------------------------ tâches
def tasks_all(config) -> List[dict]:
    return list(config.get("tasks") or [])


def task_add(config, text, msg=None, due=None) -> Optional[dict]:
    """Ajoute une tâche (échéance lue dans le texte si non précisée). Retourne la tâche, ou None si elle existe déjà."""
    text = re.sub(r"\s+", " ", text or "").strip()[:300]
    if not text:
        return None
    mid = msg.id if msg is not None else ""
    if any(t["text"] == text and t.get("msg", "") == mid and not t.get("done") for t in tasks_all(config)):
        return None
    d = tk.parse_due(text) if due is None else due
    task = {"id": uuid.uuid4().hex[:12], "text": text, "due": d.isoformat() if d else "", "done": False, "msg": mid,
            "account": (msg.account if msg is not None else "")[:40], "created": time.time()}
    config["tasks"] = tasks_all(config) + [task]
    config.save()
    return task


def task_add_from_form(config, text, due_text="", msg=None) -> Tuple[Optional[dict], str]:
    """Formulaire « Ajouter une tâche » : (tâche ou None, message à afficher)."""
    if not (text or "").strip():
        return None, ""
    parsed = tk.parse_due(due_text) if (due_text or "").strip() else None
    note = tr("Échéance non comprise : la tâche est ajoutée sans date.") if (due_text or "").strip() and parsed is None else ""
    task = task_add(config, text, msg, due=parsed if (due_text or "").strip() else None)
    if not task:
        return None, tr("Cette tâche existe déjà.")
    return task, note or (tr("Tâche ajoutée%s") % ((tr(" — échéance ") + task["due"]) if task["due"] else ""))


def task_set_done(config, tid, done=True) -> None:
    config["tasks"] = [dict(t, done=bool(done)) if t["id"] == tid else t for t in tasks_all(config)]
    config.save()


def task_remove(config, tid) -> None:
    config["tasks"] = [t for t in tasks_all(config) if t["id"] != tid]
    config.save()


def tasks_from_message(config, cache, msg) -> Tuple[list, str]:
    """Ajoute les tâches détectées par l'analyse IA du message (une seule fois chacune)."""
    ana = cache.ai_get(msg.id, "analysis") or {}
    added = [t for t in (task_add(config, x, msg) for x in ana.get("tasks", [])) if t]
    return added, (tr("%d tâche(s) ajoutée(s)") % len(added)) if added else tr("Ces tâches sont déjà dans votre liste.")


def task_default_text(msg) -> str:
    return (tr("Répondre à %s : %s") % (msg.display_sender, msg.subject))[:200]


# ------------------------------------------------------------------ Aujourd'hui
def today_local(engine, now=None) -> dict:
    """Ce qui compte aujourd'hui, côté local : messages importants non lus, relances, tâches ouvertes, brouillons préparés."""
    config, cache = engine.config, engine.cache
    now = now or datetime.datetime.now()
    inbox = cache.query("inbox", "all", unread_only=True, limit=200)
    meta = cache.ai_meta([m.id for m in inbox])
    important = [m for m in inbox if meta.get(m.id, {}).get("priority") == 3 and not meta[m.id].get("spam")][:8]
    follow = sorted(config.get("followups", []), key=lambda f: f["at"])
    open_tasks = sorted([t for t in tasks_all(config) if not t.get("done")], key=tk.sort_key)
    drafts = [m for m in cache.query("drafts", "all", limit=100) if m.id.startswith("draft-ai-")][:5]
    return {"important": important, "followups": follow, "tasks": open_tasks, "drafts": drafts, "now": now}


def followup_line(f, now_ts=None) -> str:
    n = (f["at"] - (now_ts or time.time())) / 86400
    return "« %s » — %s  (%s)" % (f["subject"][:60], f["to"][:40], tr("relance échue") if n <= 0 else tr("relance dans %d j") % int(n + 0.5))


def task_row(t) -> Tuple[str, str, bool]:
    """(texte, échéance, en retard) d'une tâche pour l'affichage."""
    return t["text"][:90], tk.due_label(t), bool(tk.is_overdue(t))


# ------------------------------------------------------------------ relances
def add_followup(config, msg, days) -> str:
    config["followups"].append({"id": msg.id, "at": time.time() + days * 86400, "subject": msg.subject, "date": msg.date,
                                "to": msg.to if msg.folder == "sent" else msg.sender_email})
    config.save()
    return tr("Rappel dans %d jours si aucune réponse") % days


def due_followups(config, cache, now=None) -> list:
    """Relances échues sans réponse ; les relances échues (répondues ou non) sont retirées de la liste."""
    now = now or time.time()
    keep, due = [], []
    for f in config["followups"]:
        if f["at"] > now:
            keep.append(f)
            continue
        addrs = [a.lower() for a in split_addresses(f["to"])]
        subj = normalize_subject(f["subject"]).lower()
        replied = bool(addrs) and any(m.date > f["date"] and normalize_subject(m.subject).lower() == subj
                                      for m in cache.query("inbox", "all", search="from:" + addrs[0]))
        if not replied:
            due.append(f)
    if len(keep) != len(config["followups"]):
        config["followups"] = keep
        config.save()
    return due


# ------------------------------------------------------------------ agenda (Google / CalDAV / .ics)
def gcal_cfg(config):
    c = config.get("gcal") or {}
    return c if c.get("enabled") and c.get("account") else None


def gcal_token(engine) -> str:
    c = gcal_cfg(engine.config)
    acc = next((a for a in engine.accounts() if a["id"] == c["account"] and a.get("auth") == "oauth2"), None) if c else None
    if acc is None:
        raise oauth.OAuthError(tr("compte Gmail (OAuth) introuvable : Paramètres → Agenda"))
    return oauth.manager_for(engine.config).access_token(acc)


def agenda_events(engine, days=14, today_only=False):
    """(ok, événements | message) dans Google Agenda ; à appeler en arrière-plan."""
    now = datetime.datetime.now()
    if today_only:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return gcal.list_events(gcal_token(engine), start, start + datetime.timedelta(days=1))
    return gcal.list_events(gcal_token(engine), now, now + datetime.timedelta(days=days))


def when_label(e) -> str:
    return tr("Journée entière") if e["all_day"] else "%s–%s" % (e["start"].strftime("%H:%M"), e["end"].strftime("%H:%M"))


def agenda_text(res, empty=None) -> List[Tuple[str, str]]:
    """Lignes (jour, texte) de l'agenda à afficher ; res = (ok, données) ou None si Google Agenda est inactif."""
    if res is None:
        return [("", tr("Activez Google Agenda (Paramètres → Agenda) pour voir vos rendez-vous ici."))]
    ok, data = res
    if not ok:
        return [("", tr("Google Agenda : %s") % data)]
    if not data:
        return [("", empty or tr("Rien de prévu dans les 14 prochains jours."))]
    return [(e["start"].strftime("%A %d %B"), "%s   %s%s" % (when_label(e), e["title"], ("   📍 " + e["location"]) if e["location"] else "")) for e in data]


def new_event(title, date, time_, dur, place="", now=None) -> Tuple[Optional[dict], str]:
    now = now or datetime.datetime.now()
    try:
        start = datetime.datetime.fromisoformat("%sT%s" % (date.strip(), time_.strip()))
        end = start + datetime.timedelta(minutes=max(5, int(dur or 60)))
    except ValueError:
        return None, tr("Date, heure ou durée invalide.")
    return {"title": (title or "").strip() or tr("Rendez-vous"), "start": start.strftime("%Y-%m-%dT%H:%M"),
            "end": end.strftime("%Y-%m-%dT%H:%M"), "location": place.strip()}, ""


def calendar_add_event(engine, ev, uid="", raw_ics=None) -> Tuple[bool, str, str]:
    """Ajoute l'événement : Google Agenda, sinon CalDAV, sinon fichier .ics (chemin renvoyé, à ouvrir dans l'agenda du système).
    Retourne (réussi, message, chemin .ics ou ''). Réseau : à lancer en arrière-plan."""
    if gcal_cfg(engine.config):
        ok, text = gcal.insert_event(gcal_token(engine), ev, uid)
        return bool(ok), (tr("Google Agenda : %s ✔") % text) if ok else tr("Google Agenda : %s") % text, ""
    cfg = engine.config.get("caldav") or {}
    ics = raw_ics or make_ics(ev)
    if cfg.get("url"):
        ok, text = caldav.put_event(cfg["url"], cfg.get("user", ""), engine.config.password("caldav"), ics.replace("METHOD:REQUEST", "METHOD:PUBLISH"),
                                    uid or ev.get("title", "evenement"))
        return bool(ok), tr("Ajouté à votre agenda ✔") if ok else tr("Agenda CalDAV : %s") % text, ""
    fd, path = tempfile.mkstemp(prefix="mintmail-", suffix=".ics")
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
        f.write(ics)
    return True, tr("Événement « %s » envoyé à votre agenda") % ev.get("title", "")[:40], path


def propose_slots(engine, minutes=60) -> str:
    """Texte de 3 créneaux libres (Google Agenda : jours ouvrables, 9h00-17h30, à partir de dans 2 h) ; lève une erreur lisible sinon."""
    now = datetime.datetime.now()
    ok, events = gcal.list_events(gcal_token(engine), now, now + datetime.timedelta(days=15))
    if not ok:
        raise oauth.OAuthError(events)
    found = slots.free_slots(events, now, duration=minutes)
    if not found:
        raise oauth.OAuthError(tr("Aucun créneau libre trouvé dans les 15 prochains jours."))
    return slots.proposal_text(found)


# ------------------------------------------------------------------ invitations
def invite_view(msg) -> Optional[dict]:
    inv = getattr(msg, "invite", None) or {}
    if not inv:
        return None
    return {"title": inv.get("title", ""), "start": inv.get("start", ""), "end": inv.get("end", ""), "where": inv.get("location", ""),
            "organizer": inv.get("organizer", ""), "can_reply": bool(inv.get("organizer")), "can_add": bool(inv.get("raw")),
            "cancelled": bool(inv.get("cancelled"))}


def my_address(engine, msg) -> Tuple[str, str, str]:
    """(adresse, nom, adresse d'alias) sous laquelle l'invitation a été reçue (identité ou compte)."""
    acc = next((a for a in engine.accounts() if a["id"] == msg.account), {})
    to = ((msg.to or "") + " " + (msg.cc or "")).lower()
    for ident in engine.config.get("identities", []):
        if ident.get("account") == msg.account and ident["email"].lower() in to:
            return ident["email"], ident.get("name", ""), ident["email"]
    return acc.get("email", ""), acc.get("name", ""), ""


def invite_reply(engine, msg, action) -> Tuple[Optional[Outgoing], str]:
    inv = msg.invite or {}
    if not inv.get("organizer"):
        return None, tr("Pas d'organisateur à qui répondre.")
    email, name, from_email = my_address(engine, msg)
    verb = {"accept": tr("accepté"), "tentative": tr("accepté sous réserve"), "decline": tr("décliné")}[action]
    out = Outgoing(account=msg.account, to=inv["organizer"], subject=ical.reply_subject(inv, action),
                   html="<p>J'ai %s l'invitation « %s ».</p>" % (verb, inv.get("title", "")), text=tr("J'ai %s l'invitation.") % verb,
                   ics=ical.build_reply(inv, email, name, action), ics_method="REPLY", from_email=from_email, from_name=name if from_email else "")
    return out, (tr("Invitation acceptée — réponse envoyée à l'organisateur") if action == "accept"
                 else tr("Réponse envoyée à l'organisateur (%s)") % verb)


def invite_event(msg) -> Tuple[Optional[dict], str, Optional[str]]:
    """(événement, uid, .ics brut) pour « Ajouter à l'agenda » ; None si le message n'a pas d'invitation exploitable."""
    inv = msg.invite or {}
    if not inv.get("raw"):
        return None, "", None
    return ({"title": inv.get("title", ""), "start": inv.get("start", ""), "end": inv.get("end", ""), "location": inv.get("location", ""),
             "description": inv.get("description", "")}, inv["uid"], inv["raw"])


def invite_conflict_note(engine, msg) -> str:
    """Note sur le créneau d'une invitation d'après Google Agenda (« » si inconnu) ; à appeler en arrière-plan."""
    inv = msg.invite or {}
    if not (inv.get("start") and gcal_cfg(engine.config)):
        return ""
    try:
        start = gcal._local_dt(inv["start"]).replace(tzinfo=None)
        end = gcal._local_dt(inv["end"]).replace(tzinfo=None) if inv.get("end") else start + datetime.timedelta(hours=1)
    except ValueError:
        return ""
    ok, events = gcal.list_events(gcal_token(engine), start - datetime.timedelta(minutes=1), end + datetime.timedelta(minutes=1))
    if not ok:
        return ""
    clash = gcal.conflicts(events, start, end)
    if not clash:
        return tr("✔ Vous êtes libre sur ce créneau (Google Agenda).")
    e = clash[0]
    return tr("⚠ Conflit avec « %s » (%s–%s)%s") % (e["title"][:40], e["start"].strftime("%H:%M"), e["end"].strftime("%H:%M"),
                                                   tr(" et %d autre(s)") % (len(clash) - 1) if len(clash) > 1 else "")


# ------------------------------------------------------------------ désabonnement
def unsubscribe_plan(msg) -> dict:
    """Comment se désabonner : « oneclick » (requête sécurisée RFC 8058), « mailto », « web » (page à ouvrir) ou « none »."""
    links = unsub.parse_list_unsubscribe(getattr(msg, "unsubscribe", "") or "")
    who = msg.display_sender
    if getattr(msg, "unsub_post", False) and links["https"]:
        return {"kind": "oneclick", "url": links["https"][0], "who": who,
                "ask": tr("Se désabonner de %s ?") % who,
                "detail": tr("MintMail envoie la demande de désabonnement directement au service (requête sécurisée, sans ouvrir de page).")}
    if links["mailto"]:
        to, subject, body = unsub.mailto_fields(links["mailto"][0])
        if not to:
            return {"kind": "refused", "who": who, "note": tr("Adresse de désabonnement invalide ou multiple : refusée par sécurité.")}
        return {"kind": "mailto", "to": to, "subject": subject, "body": body, "who": who, "ask": tr("Se désabonner de %s ?") % who,
                "detail": tr("Un e-mail de désabonnement sera envoyé à %s.") % to}
    if links["https"]:
        return {"kind": "web", "url": links["https"][0], "who": who}
    return {"kind": "none", "who": who, "note": tr("Ce message ne propose pas de lien de désabonnement.")}


def unsubscribe_mail(msg, plan) -> Outgoing:
    return Outgoing(account=msg.account, to=plan["to"], subject=plan["subject"], html="<p>%s</p>" % plan["body"], text=plan["body"])


def unsubscribe_oneclick(plan) -> Tuple[bool, str]:
    return unsub.one_click_post(plan["url"])


# ------------------------------------------------------------------ pièces jointes
def attachment_chips(msg) -> List[dict]:
    out = []
    for a in msg.attachments or []:
        out.append({"att": a, "name": a.get("filename", ""), "size": human_size(a.get("size", 0)), "kind": attachment_kind(a),
                    "risk": attachment_risk(a), "exists": os.path.exists(a.get("path", ""))})
    return out


def attachments_total(msg) -> str:
    return human_size(sum(a.get("size", 0) for a in (msg.attachments or [])))


def open_plan(att) -> Tuple[str, str]:
    """(action, texte) pour un clic sur une pièce jointe : « block » (jamais ouvert), « warn » (confirmation), « preview_image »,
    « preview_text » ou « open » (application par défaut)."""
    risk, kind = attachment_risk(att), attachment_kind(att)
    if risk == "block":
        return "block", tr("« %s » est un programme ou un script : MintMail ne l'ouvre pas. Si vous êtes certain de sa provenance, enregistrez-le "
                           "(clic droit → Enregistrer sous…) et vérifiez-le avant de l'exécuter.") % att.get("filename", "")
    if risk == "warn":
        return "warn", tr("« %s » peut contenir des macros ou du code actif. Ouvrez-le seulement si vous attendiez ce fichier.") % att.get("filename", "")
    if kind in ("image", "text") and att.get("size", 0) <= 15_000_000:
        return "preview_" + kind, ""
    return "open", ""


def read_text_preview(att, limit=200_000) -> str:
    with open(att["path"], "rb") as f:
        return f.read(limit).decode("utf-8", "replace")


def save_one(att, dest) -> bool:
    try:
        with open(att["path"], "rb") as f, open(dest, "wb") as g:
            g.write(f.read())
        return True
    except OSError:
        return False


def save_all(msg, directory) -> List[str]:
    return save_attachments(list(msg.attachments or []), directory)


# ------------------------------------------------------------------ fil de conversation
def thread_rows(cache, msg, threads=True) -> List[dict]:
    """Autres messages de la conversation (du plus ancien au plus récent) : [{id, who, date, snippet, unread, folder, current}]."""
    tid = getattr(msg, "thread_id", "") or ""
    if not tid:
        return []
    members = sorted(cache.thread_members(msg.account, tid), key=lambda m: m.date)
    if len(members) < 2:
        return []
    from ..util import format_full
    return [{"id": m.id, "who": m.display_sender, "date": format_full(m.date), "snippet": (m.snippet or "")[:90], "unread": bool(m.unread),
             "folder": m.folder, "current": m.id == msg.id} for m in members]


def thread_unread_others(cache, msg) -> list:
    """Messages non lus du même fil et du même dossier (à marquer lus quand on ouvre le fil)."""
    tid = getattr(msg, "thread_id", "") or ""
    if not tid:
        return []
    return [x for x in cache.thread_members(msg.account, tid) if x.unread and x.folder == msg.folder and x.id != msg.id]
