"""IA partout dans l'interface Qt (logique pure, sans Qt) : tri automatique des nouveaux messages, pastilles et résumé dans la liste,
bloc « En bref », brouillons de réponse préparés, recherche en langage naturel, entrées IA du clic droit.
Même comportement que ai_features.py / extras.py de la version GTK ; rien n'est jamais envoyé ni déplacé sans validation."""
import hashlib
import re
import time
from typing import Dict, List, Optional

from ..i18n import tr
from ..models import Message
from ..util import normalize_subject, text_to_html
from . import assistant as AS

REPLY_IDEAS = [(tr("Réponse adaptée"), tr("Réponds de façon appropriée à ce message.")), (tr("Accepter"), tr("Accepte poliment la proposition.")),
               (tr("Refuser poliment"), tr("Refuse poliment la demande.")), (tr("Demander plus d'informations"), tr("Demande des précisions.")),
               (tr("Proposer un autre créneau"), tr("Propose un autre créneau.")), (tr("Ton formel"), tr("Réponds sur un ton formel.")),
               (tr("Ton amical"), tr("Réponds sur un ton amical.")), (tr("Très courte"), tr("Réponds en une ou deux phrases."))]


def enabled(engine) -> bool:
    return AS.ai_engine(engine).enabled()


# ------------------------------------------------------------------ liste : pastilles et résumé
def decorate(infos, msgs, meta: Dict[str, dict]) -> None:
    """Ajoute à chaque ligne : résumé IA, priorité (3 = important) et suspicion de spam (issus du tri, en cache)."""
    for info, m in zip(infos, msgs):
        v = meta.get(m.id) or {}
        info["ai"] = (v.get("summary") or "").strip()
        info["prio"] = v.get("priority") if v.get("priority") in (1, 2, 3) else 0
        info["spam"] = bool(v.get("spam"))


# ------------------------------------------------------------------ tri automatique
def triage(engine, msgs: List[Message]) -> Dict[str, dict]:
    """Priorité / spam / catégorie des messages pas encore triés (local tout de suite, affiné par l'IA si elle est active). Réseau : en fond."""
    ai = AS.ai_engine(engine)
    ai.folder_names = AS.folder_paths(engine, free_only=True)
    res = ai.triage(msgs, use_ai=bool(engine.config.get("ai_triage", True)))
    by = {}
    for mid, v in res.items():
        if v.get("category"):
            by.setdefault(v["category"], []).append(mid)
    for cat, ids in by.items():
        engine.cache.update_many(ids, category=cat)
    return res


def to_triage(engine, account="all", limit=40) -> List[Message]:
    """Derniers messages de la boîte de réception (le tri ignore ceux qui l'ont déjà été)."""
    return engine.cache.query("inbox", account, limit=limit)


def urgent(msgs, res) -> List[Message]:
    return [m for m in msgs if res.get(m.id, {}).get("priority") == 3 and not res[m.id].get("local") and not res[m.id].get("spam")]


# ------------------------------------------------------------------ brouillons de réponse préparés
def prepare_candidates(config, cache, msgs, res, now=None) -> List[Message]:
    """Messages importants, récents, qui attendent une réponse (3 au plus) — seulement si « Préparer des brouillons » est activé."""
    if not config.get("ai_prepare_drafts"):
        return []
    cutoff = (now or time.time()) - 3 * 86400
    out = []
    for m in msgs:
        v = res.get(m.id, {})
        if (m.folder == "inbox" and m.date > cutoff and v.get("reply_needed") and not v.get("local") and not v.get("spam")
                and v.get("priority", 0) >= 2 and v.get("category") in (None, "people") and not cache.ai_get(m.id, "prepared")):
            out.append(m)
    return out[:3]


def prepare_drafts(engine, cands: List[Message], identity_of=lambda m: None) -> int:
    """Écrit un brouillon de réponse par message (jamais envoyé) dans Brouillons, dans le style des derniers messages envoyés. Réseau : en fond."""
    ai, cache, made = AS.ai_engine(engine), engine.cache, 0
    accounts = {a["id"]: a for a in engine.accounts()}
    for m in cands:
        full = cache.get(m.id) or m
        examples = []
        for s in cache.query("sent", m.account, limit=6):
            body = (cache.get(s.id) or s).text or ""
            if body.strip():
                examples.append(re.sub(r"\n{3,}", "\n\n", body.strip())[:400])
        try:
            text = ai.prepare_reply(full, examples).strip()
        except Exception:
            continue
        if not text:
            continue
        acc = accounts.get(full.account, {})
        ident = identity_of(full)
        sig = (ident or {}).get("signature_html") or acc.get("signature_html", "")
        did = "draft-ai-" + hashlib.sha1(full.id.encode("utf-8")).hexdigest()[:12]
        cache.upsert(Message(
            id=did, account=full.account, folder="drafts", uid=0, sender_name=acc.get("name", ""), sender_email=acc.get("email", ""),
            to=(full.reply_to or full.sender_email), subject="Re: " + normalize_subject(full.subject), date=time.time(),
            snippet=("✨ " + text)[:150], text=text, unread=False, message_id=full.message_id, references=full.references,
            html=text_to_html(text) + ("<br><br>-- <br>" + sig if sig.strip() else "")))
        cache.ai_set(full.id, "prepared", {"draft": did})
        made += 1
    return made


# ------------------------------------------------------------------ « En bref »
def digest_key(engine, account, today: str) -> tuple:
    return (len(engine.cache.query("unread", account, limit=25)), today, account)


def digest_local(engine, account) -> str:
    msgs = engine.cache.query("unread", account, limit=25)
    if not msgs:
        return tr("Boîte à jour : aucun message non lu 🎉")
    return AS.ai_engine(engine).local_digest(engine.cache.counts(account), msgs)


def digest_ai(engine, account, force=False) -> str:
    return AS.digest(engine, account, force=force)


# ------------------------------------------------------------------ recherche en langage naturel
def is_ai_query(text: str) -> bool:
    return (text or "").lstrip().startswith(("?", "✨"))


def ai_query_text(text: str) -> str:
    return (text or "").lstrip("?✨ ").strip()


def nl_search(engine, text: str) -> str:
    return AS.ai_engine(engine).nl_search(ai_query_text(text))


# ------------------------------------------------------------------ clic droit
Item = Optional[tuple]


def context_items(engine, msg, account="all") -> List[Item]:
    """Entrées IA du clic droit : (clé, libellé) | (« sub », libellé, [(clé, libellé)…]) | None. Clés : voir AIMixin.run_ai."""
    if not enabled(engine):
        return [("ai_enable", tr("✨ Activer l'IA : classement, résumés, réponses…"))]
    ana = engine.cache.ai_get(msg.id, "analysis") or {}
    sug, who = ana.get("folder") or "", msg.sender_email
    items: List[Item] = []
    if msg.folder == "spam":
        suspect = bool(ana.get("suspicious"))
        items.append(("notspam", tr("✨ Ce n'est pas du spam (remettre en boîte de réception)") if not suspect
                      else tr("✔ Ce n'est pas du spam (malgré l'avis de l'IA)")))
        if ana.get("folder") and not suspect:
            items.append(("ai_notspam_file:" + ana["folder"], tr("✨ Pas du spam, ranger dans « %s »") % ana["folder"]))
    habit = "" if sug else (engine.cache.learn_best(msg.account, who) or "")
    if habit:
        sug = habit
        items.append(("ai_file:" + sug, tr("✨ Ranger dans « %s » (selon vos habitudes)") % sug))
    elif sug:
        items.append(("ai_file:" + sug, tr("✨ Ranger dans « %s » (suggéré)") % sug))
    else:
        items.append(("ai_suggest", tr("✨ Suggérer un dossier…")))
    items.append(("ai_classify_sender", tr("✨ Classer tous les messages de %s") % who))
    items.append(("ai_classify_inbox", tr("✨ Classer ma boîte de réception (60 derniers)")))
    if sug:
        items.append(("ai_rule:" + sug, tr("✨ Toujours ranger %s dans « %s »") % (who, sug)))
    if ana.get("tasks"):
        items.append(("ai_tasks", tr("✨ Ajouter les %d tâche(s) détectée(s)") % len(ana["tasks"])))
    items.append(None)
    items.append(("sub", tr("✨ Répondre avec l'IA"), [("ai_reply:%d" % i, lab) for i, (lab, _idea) in enumerate(REPLY_IDEAS)]))
    if getattr(msg, "thread_count", 1) > 1:
        items.append(("ai_thread", tr("✨ Résumer la conversation (%d messages)") % msg.thread_count))
    items.append(("summarize", tr("✨ Résumer / analyser ce message")))
    items.append(("translate", tr("✨ Traduire ce message")))
    if ana.get("event"):
        items.append(("ai_event", tr("✨ Ajouter à l'agenda : %s") % ana["event"]["title"][:30]))
    items.append(("ai_about", tr("✨ Demander à l'assistant à propos de ce message…")))
    return items


def reply_idea(key: str) -> str:
    i = int(key.split(":", 1)[1])
    return REPLY_IDEAS[i][1] if 0 <= i < len(REPLY_IDEAS) else REPLY_IDEAS[0][1]


def event_of(engine, msg) -> Optional[dict]:
    return (engine.cache.ai_get(msg.id, "analysis") or {}).get("event")


def thread_summary(engine, msg) -> str:
    members = engine.cache.thread_members(msg.account, msg.thread_id)
    return AS.ai_engine(engine).summarize_thread([engine.cache.get(m.id) or m for m in members])


def thread_size(engine, msg) -> int:
    return len(engine.cache.thread_members(msg.account, msg.thread_id))


def add_rule_move(config, msg, folder) -> bool:
    rule = {"field": "from", "text": msg.sender_email.lower(), "action": "move", "folder": folder}
    if rule in config["rules"]:
        return False
    config["rules"].append(rule)
    config.save()
    return True


def suggest_folder(engine, msg):
    """(dossier, nouveau ?) suggéré par l'IA pour ce message, ou (None, False) ; réseau : en fond."""
    ai = AS.ai_engine(engine)
    ai.folder_names = AS.folder_paths(engine, free_only=True)
    r = ai.classify([msg], AS.folder_paths(engine, msg.account, free_only=True), account=msg.account)
    if not r["moves"]:
        return None, False
    f = next(iter(r["moves"]))
    return f, f in r["new"]
