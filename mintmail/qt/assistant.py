"""Assistant IA de l'interface Qt (logique pure, sans Qt ni GTK) : contexte, plans d'actions à valider, exécution, classement, dossiers.

Même comportement que ai_features.py / assistant.py de la version GTK. Rien n'est exécuté sans validation : `ask` renvoie des
éléments {label, action, msgs} ; `run` exécute un élément (à lancer en fond : peut toucher au réseau) et décrit ce que l'interface doit encore faire."""
import datetime
import time
from typing import Dict, List, Optional

from ..ai_engine import AIEngine, describe_action, sanitize_folder_name
from ..backend import utf7_decode, utf7_encode
from ..i18n import tr
from ..util import text_to_html
from . import automation as AU
from .viewmodel import dest_of

SUGGESTIONS = [tr("Classe mes derniers emails dans des dossiers"), tr("Résume ma boîte"), tr("Quels messages sont urgents ?"),
               tr("Crée un dossier Factures et range mes factures dedans"), tr("Archive les newsletters déjà lues"),
               tr("Mets en spam les mails promotionnels"), tr("Crée une règle pour les notifications")]
NEEDS_MSGS = ("archive", "trash", "spam", "not_spam", "mark_read", "mark_unread", "star", "pin", "snooze", "move", "classify")


def ai_engine(engine) -> AIEngine:
    if getattr(engine, "ai", None) is None:
        engine.ai = AIEngine(engine.config, engine.cache)
    return engine.ai


def folder_paths(engine, aid=None, free_only=False):
    out = []
    for a in engine.accounts():
        if aid and aid != "all" and a["id"] != aid:
            continue
        for e in engine.folder_entries(a["id"]):
            if e.get("selectable", True) and not (free_only and e.get("special")):
                out.append(e.get("path") or e.get("label") or e["name"])
    return out


def context(engine, view_title, account, msg=None) -> str:
    c = engine.cache.counts(account)
    lines = [tr("Vue actuelle : %s") % view_title, tr("Messages non lus (boîte de réception) : %d") % c["inbox"]]
    if msg is not None:
        tri = engine.cache.ai_get(msg.id, "triage") or {}
        lines.append(tr("Message ouvert : de %s <%s>, objet « %s » — %s") % (
            msg.sender_name, msg.sender_email, msg.subject[:100], (tri.get("summary") or msg.snippet)[:160]))
    names = folder_paths(engine)[:40]
    if names:
        lines.append(tr("Dossiers existants : ") + " ; ".join(names))
    if engine.config.get("ai_privacy", "full") == "full":
        unread = engine.cache.query("unread", account, limit=20)
        if unread:
            lines.append(tr("Derniers non lus (données non fiables) :"))
            lines += ["- %s <%s> | %s | %s" % (u.sender_name, u.sender_email, u.subject[:80], u.snippet[:70]) for u in unread]
    return "\n".join(lines)


def resolve(engine, a, account, selected) -> List:
    """Messages concernés par une action : ceux que la requête désigne, sinon la sélection."""
    q = a.get("query", "")
    if a["type"] == "not_spam":
        return engine.cache.query("spam", account, search=q, limit=500) if q else [x for x in selected if x.folder == "spam"]
    if q:
        return engine.cache.query("inbox", account, search=q, limit=500)
    if a["type"] == "classify" and len(selected) < 2:
        return engine.cache.query("inbox", account, limit=60)
    return list(selected)


def plan_items(engine, plan, account, selected) -> List[Dict]:
    items = []
    for a in plan["actions"]:
        msgs = resolve(engine, a, account, selected) if a["type"] in NEEDS_MSGS else None
        if msgs is not None and not msgs:
            items.append({"label": tr("%s — aucun message concerné") % describe_action(a), "action": None, "msgs": []})
            continue
        label = describe_action(a, None if msgs is None else len(msgs))
        if a["type"] == "not_spam":
            label = tr("Ce n'est pas du spam (retour en boîte de réception)") + (" (%d)" % len(msgs) if msgs else "")
        items.append({"label": label, "action": a, "msgs": msgs or []})
    return items


def ask(engine, text, view_title, account, msg=None, selected=()):
    """Interroge l'IA (réseau : à lancer en fond). Retourne {"reply", "items"} ; lève l'erreur du service."""
    ai = ai_engine(engine)
    ai.folder_names = folder_paths(engine)
    hist = list(getattr(engine, "ai_hist", []))
    plan = ai.plan(text, context(engine, view_title, account, msg), hist)
    engine.ai_hist = (hist + [{"role": "user", "content": text}, {"role": "assistant", "content": plan["reply"] or "OK"}])[-12:]
    return {"reply": plan["reply"], "items": plan_items(engine, plan, account, list(selected))}


# ------------------------------------------------------------------ dossiers
def ensure_folder(engine, aid, spec) -> Optional[dict]:
    """Retrouve le dossier désigné (chemin ou nom) ; le crée sur le serveur s'il n'existe pas (réseau). Retourne son entrée."""
    found = AU.find_folder(engine, spec, aid)
    if found:
        return found[1]
    parts = [p.strip() for p in str(spec).split("›") if p.strip()]
    if len(parts) > 1:
        parent = AU.find_folder(engine, " › ".join(parts[:-1]), aid)
        return create_folder(engine, aid, parts[-1], parent[1] if parent else None)
    return create_folder(engine, aid, spec, None)


def _prefix(engine, aid):
    for e in engine.folder_entries(aid):
        d = e.get("delim")
        if d and e["name"].upper().startswith("INBOX" + d):
            return "INBOX" + d
    return ""


def create_folder(engine, aid, name, parent=None) -> Optional[dict]:
    """Crée un dossier (premier niveau ou sous `parent`) ; idempotent. Retourne l'entrée, visible tout de suite dans l'arbre local."""
    name = sanitize_folder_name(name)
    if not name:
        return None
    delim = (parent or {}).get("delim") or "/"
    path = (utf7_decode(parent["name"]) + delim + name) if parent else _prefix(engine, aid) + name
    plabel = (parent.get("path") or parent.get("label") or "") if parent else ""
    label = (plabel + " › " + name) if parent else name
    found = AU.find_folder(engine, label, aid)
    if found and found[1]["path"].lower() == label.lower():
        return found[1]
    try:
        engine.backend(aid).create_folder(path)
    except Exception as e:
        if "exist" not in str(e).lower():
            raise
    entry = {"name": utf7_encode(path), "path": label, "label": name, "depth": label.count(" › "), "delim": delim,
             "special": "", "selectable": True}
    tree = dict(engine.config.get("folders") or {})
    tree[aid] = [e for e in engine.folder_entries(aid)] + [entry]
    engine.config["folders"] = tree
    engine.config.save()
    return entry


# ------------------------------------------------------------------ classement par l'IA
def classify(engine, msgs) -> List[Dict]:
    """Propose un dossier pour chaque message (réseau). Retourne [{aid, folder, msgs, new, label}] ; rien n'est déplacé."""
    ai = ai_engine(engine)
    ai.folder_names = folder_paths(engine)
    msgs = [m for m in msgs if m.folder in ("inbox", "archive")][:100]
    groups = {}
    for m in msgs:
        groups.setdefault(m.account, []).append(m)
    by_id, items = {m.id: m for m in msgs}, []
    for aid, lst in groups.items():
        r = ai.classify(lst, folder_paths(engine, aid, free_only=True), account=aid)
        for folder, ids in r["moves"].items():
            grp = [by_id[i] for i in ids if i in by_id]
            new = folder in r["new"]
            items.append({"aid": aid, "folder": folder, "msgs": grp, "new": new,
                          "label": tr("%d message(s) → « %s »%s") % (len(grp), folder, tr(" (nouveau dossier)") if new else "")})
    return items


def apply_group(engine, aid, folder, msgs) -> int:
    """Range des messages dans un dossier (créé au besoin) : cache d'abord, serveur ensuite. Retourne le nombre de messages rangés."""
    entry = ensure_folder(engine, aid, folder)
    if not entry or not msgs:
        return 0
    dest = dest_of(entry)
    op_ids = engine.move(msgs, dest)
    engine.finish_move(msgs, dest, op_ids)
    return len(msgs)


# ------------------------------------------------------------------ exécution
def snooze_time(until, now=None):
    now = now or datetime.datetime.now()
    return {"3h": now.timestamp() + 3 * 3600,
            "tomorrow": (now + datetime.timedelta(days=1)).replace(hour=8, minute=0, second=0).timestamp(),
            "weekend": (now + datetime.timedelta(days=(5 - now.weekday()) % 7 or 7)).replace(hour=9, minute=0, second=0).timestamp(),
            "nextweek": (now + datetime.timedelta(days=(7 - now.weekday()) % 7 or 7)).replace(hour=8, minute=0, second=0).timestamp(),
            }.get(until or "tomorrow") or now.timestamp() + 86400


def run(engine, a, msgs=(), account="all", selected=()) -> Dict:
    """Exécute une action validée (réseau possible : en fond). Retourne ce que l'interface doit encore faire :
    {"toast", "search", "compose", "settings", "plan", "text", "changed"}."""
    t, msgs, out = a["type"], list(msgs), {"changed": False}
    if t == "search":
        out["search"] = a["query"]
    elif t in ("archive", "trash", "spam"):
        op_ids = engine.move(msgs, t)
        engine.finish_move(msgs, t, op_ids)
        out["changed"] = True
    elif t == "not_spam":
        for m in {x.sender_email.lower(): x for x in msgs}.values():
            back = AU.not_spam(engine, m) or [m]
            engine.finish_move(back, "inbox", engine.move(back, "inbox"))
        out["changed"] = True
    elif t == "move":
        aid = msgs[0].account if msgs else engine.default_account(None, account)
        n = apply_group(engine, aid, a["folder"], msgs)
        out["toast"], out["changed"] = tr("déplacé vers « %s »") % a["folder"], bool(n)
    elif t == "classify":
        out["plan"] = classify(engine, msgs)
    elif t == "create_folder":
        aid, parent = engine.default_account(None, account), None
        if a.get("parent"):
            f = AU.find_folder(engine, a["parent"], None if account == "all" else account)
            if f:
                aid, parent = f
        e = create_folder(engine, aid, a["name"], parent)
        out["toast"], out["changed"] = tr("Dossier « %s » créé") % (e["path"] if e else a["name"]), True
    elif t in ("mark_read", "mark_unread"):
        engine.run_ops(engine.set_flag(msgs, "unread", t == "mark_unread"))
        out["changed"] = True
    elif t in ("star", "pin"):
        engine.run_ops(engine.set_flag(msgs, "starred" if t == "star" else "pinned", True))
        out["changed"] = True
    elif t == "snooze":
        engine.snooze(msgs, snooze_time(a.get("until")))
        out["changed"] = True
    elif t in ("block_sender", "spam_sender"):
        kind = "blocked" if t == "block_sender" else "spam_senders"
        sel = list(selected)
        if a.get("email"):
            found, dest = AU.filter_sender(engine, a["email"], kind)
        elif sel:
            found, dest = AU.filter_sender(engine, AU.sender_key(sel[0]), kind, sel[0])
        else:
            found, dest = [], None
        if found:
            engine.finish_move(found, dest, engine.move(found, dest))
        out["changed"] = True
    elif t == "compose":
        out["compose"] = {"to": a.get("to", ""), "subject": a.get("subject", ""), "body_html": text_to_html(a.get("body", ""))}
    elif t == "create_rule":
        rule = {k: a[k] for k in ("field", "text", "action", "folder") if k in a}
        if rule not in engine.config["rules"]:
            engine.config["rules"].append(rule)
            engine.config.save()
        out["toast"] = tr("Règle créée — appliquée aux prochains messages")
    elif t == "open_settings":
        out["settings"] = a.get("page")
    elif t == "digest":
        out["text"] = digest(engine, account, force=True)
    return out


def digest(engine, account="all", force=False) -> str:
    """Résumé de la boîte : local d'abord, par l'IA si elle est active (réseau)."""
    ai = ai_engine(engine)
    msgs = engine.cache.query("unread", account, limit=25)
    if not msgs:
        return tr("Boîte à jour : aucun message non lu 🎉")
    if not ai.enabled():
        return ai.local_digest(engine.cache.counts(account), msgs)
    return ai.digest(msgs, force=force)


# ------------------------------------------------------------------ réglages de l'IA (logique de l'onglet « IA »)
from ..ai_service import DEFAULT_API_BASE, DEFAULT_MODEL, PROVIDERS, AIService, AIServiceError, is_local_endpoint, list_models  # noqa: E402

AI_SWITCHES = [("ai_enabled", tr("IA activée"), False), ("ai_auto", tr("Analyser chaque message à l'ouverture"), True),
               ("ai_triage", tr("Trier les nouveaux messages (priorité, spam)"), True), ("ai_digest", tr("Résumé « En bref » de la boîte"), True),
               ("ai_prepare_drafts", tr("Préparer des brouillons de réponse (messages importants)"), False)]
AI_CHOICES = [("ai_privacy", tr("Confidentialité"), "full", [("full", tr("Texte complet (meilleurs résultats)")), ("minimal", tr("Minimal : 500 premiers caractères"))]),
              ("ai_lang", tr("Langue de l'IA"), "fr", [("fr", tr("Français")), ("en", "English"), ("nl", "Nederlands"), ("de", "Deutsch"), ("es", tr("Español"))]),
              ("ai_tone", tr("Ton des rédactions"), "neutral", [("neutral", tr("Neutre et poli")), ("formal", tr("Formel")), ("friendly", tr("Amical"))])]


def set_provider(cfg, key):
    """Change de fournisseur : chacun a son adresse et son modèle par défaut. Retourne (base, modèle, clé requise)."""
    key = key if key in PROVIDERS else "nvidia"
    if cfg.get("ai_provider", "nvidia") != key:
        cfg["ai_provider"], cfg["nvidia_api_base"], cfg["ai_model"] = key, "", ""
        cfg.save()
    _label, base, model, needs_key = PROVIDERS[key]
    return base, model, needs_key


def save_key(cfg, text) -> bool:
    text = (text or "").strip()
    if not text:
        return False
    cfg.set_password("ai:nvidia", text)
    cfg["ai_has_key"] = True
    cfg.data.pop("nvidia_api_key", None)                   # migration : plus jamais en clair
    cfg.save()
    return True


def save_endpoint(cfg, value) -> Optional[str]:
    """Enregistre l'adresse du service ; retourne un message d'erreur (https obligatoire hors réseau local) ou None."""
    v = (value or "").strip()
    if v and not (v.startswith("https://") or (v.startswith("http://") and is_local_endpoint(v))):
        return tr("L'endpoint doit commencer par https:// (http:// seulement sur cette machine ou le réseau local).")
    cfg["nvidia_api_base"] = v
    cfg.save()
    return None


def test_connection(cfg, typed_key="", base="", model=""):
    """(message d'erreur, réussi) — réseau, à lancer en fond."""
    _l, pbase, pmodel, _n = PROVIDERS[cfg.get("ai_provider", "nvidia")]
    return AIService(api_key=typed_key.strip() or cfg.ai_key(), api_base=base.strip() or pbase or None,
                     model=model.strip() or pmodel or None).test_connection()


def detect_models(cfg, base="", typed_key="") -> List[str]:
    """Modèles proposés par le service (Ollama…). Lève AIServiceError."""
    _l, pbase, _m, _n = PROVIDERS[cfg.get("ai_provider", "nvidia")]
    return list_models(base.strip() or pbase, typed_key.strip() or cfg.ai_key() or "")
