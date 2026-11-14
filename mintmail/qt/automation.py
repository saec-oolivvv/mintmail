"""Règles, expéditeurs bloqués / en spam et recherche de dossier pour l'interface Qt (logique pure, sans Qt ni GTK).

Même comportement que la version GTK (window._auto_route, listing._filter_sender / not_spam, folders.find_folder)."""
from typing import Dict, List, Optional, Tuple

from ..i18n import tr
from .viewmodel import dest_of

MOVES = ("trash", "spam", "archive")
RULE_FIELDS = [("from", tr("L'expéditeur contient")), ("subject", tr("L'objet contient")), ("to", tr("Les destinataires contiennent"))]
RULE_ACTIONS = [("archive", tr("Archiver")), ("trash", tr("Supprimer")), ("spam", tr("Mettre en spam")),
                ("read", tr("Marquer comme lu")), ("star", tr("Ajouter aux favoris")), ("pin", tr("Épingler")),
                ("move", tr("Ranger dans le dossier →"))]


def rule_match(rule, m) -> bool:
    txt = (rule.get("text") or "").lower()
    hay = {"from": "%s %s" % (m.sender_name, m.sender_email), "subject": m.subject,
           "to": "%s %s" % (m.to, m.cc)}.get(rule.get("field"), "")
    return bool(txt) and txt in hay.lower()


def sender_key(m, domain=False) -> str:
    em = m.sender_email.lower()
    return "@" + em.split("@")[-1] if domain else em


def find_folder(engine, text, aid=None) -> Optional[Tuple[str, dict]]:
    """Retrouve un dossier par nom (casse ignorée) : exact, fin de chemin, puis « contient »."""
    t = (text or "").strip().lower()
    if not t:
        return None
    accounts = [aid] if aid and aid != "all" else [a["id"] for a in engine.accounts()]
    cands = []
    for a in accounts:
        for e in engine.folder_entries(a):
            if e.get("selectable", True):
                e = dict(e, label=e.get("label") or e["name"], path=e.get("path") or e.get("label") or e["name"])
                cands.append((a, e))
    for test in (lambda e: e["label"].lower() == t or e["path"].lower() == t,
                 lambda e: e["path"].lower().endswith(t), lambda e: t in e["path"].lower()):
        for a, e in cands:
            if test(e):
                return a, e
    return None


def route(engine, msgs) -> Tuple[List, Dict[str, List]]:
    """Applique blocages, spam d'expéditeur et règles. Le cache est mis à jour tout de suite.
    Retourne (messages qui restent, {destination: [messages déplacés]}) ; le serveur est prévenu via op_ids (voir run_moves)."""
    cfg = engine.config
    blocked = {x.lower() for x in cfg["blocked"]}
    spam_s = {x.lower() for x in cfg["spam_senders"]}
    rules = cfg["rules"]
    if not msgs or not (blocked or spam_s or rules):
        return list(msgs), {}
    plan, keep = {}, []
    for m in msgs:
        em = m.sender_email.lower()
        dom = "@" + em.split("@")[-1]
        dest = "trash" if (em in blocked or dom in blocked) else "spam" if (em in spam_s or dom in spam_s) else None
        fdest = None
        if dest is None:
            for r in rules:
                if not rule_match(r, m):
                    continue
                act = r.get("action")
                if act == "move" and fdest is None and dest is None:
                    found = find_folder(engine, r.get("folder", ""), m.account)
                    if found:
                        fdest = dest_of(found[1])
                elif act in MOVES and dest is None:
                    dest = act
                elif act == "read":
                    engine.set_flag([m], "unread", False)
                elif act == "star":
                    engine.set_flag([m], "starred", True)
                elif act == "pin":
                    engine.set_flag([m], "pinned", True)
        final = dest or fdest
        if final:
            plan.setdefault(final, []).append(m)
        else:
            keep.append(m)
    return keep, plan


def apply_moves(engine, plan) -> List[Tuple[list, str, list]]:
    """Déplace (cache) chaque groupe ; retourne [(messages, destination, op_ids)] à terminer en fond avec engine.finish_move."""
    out = []
    for dest, lst in plan.items():
        if lst:
            if dest in ("trash", "spam"):
                engine.cache.update_many([m.id for m in lst], unread=False)
            out.append((lst, dest, engine.move(lst, dest)))
    return out


def filter_sender(engine, key, kind, msg=None):
    """kind : « blocked » (corbeille) ou « spam_senders » (Spam). Retourne (messages à déplacer, destination)."""
    key = key.lower()
    if key not in engine.config[kind]:
        engine.config[kind].append(key)
        engine.config.save()
    msgs = engine.cache.by_sender(key, ("inbox", "archive"))
    if msg is not None and msg.id not in {x.id for x in msgs} and msg.folder in ("inbox", "archive"):
        msgs.append(msg)
    return msgs, ("trash" if kind == "blocked" else "spam")


def unfilter_sender(engine, kind, key):
    engine.config[kind] = [x for x in engine.config[kind] if x.lower() != key.lower()]
    engine.config.save()


def not_spam(engine, msg, domain=False):
    """« Ce n'est pas du spam » : l'expéditeur sort de la liste spam ; retourne les messages du Spam à remettre en boîte."""
    key = sender_key(msg, domain)
    em, dom = sender_key(msg), sender_key(msg, True)
    old = list(engine.config["spam_senders"])
    engine.config["spam_senders"] = [x for x in old if x.lower() not in (em, dom)]
    if engine.config["spam_senders"] != old:
        engine.config.save()
    msgs = [x for x in engine.cache.by_sender(key, ("spam",))
            if x.account == msg.account and sender_key(x, domain) == key]
    if msg.folder != "inbox" and msg.id not in {x.id for x in msgs}:
        msgs.append(msg)
    for x in msgs:
        tri, ana = engine.cache.ai_get(x.id, "triage"), engine.cache.ai_get(x.id, "analysis")
        if tri and tri.get("spam"):
            engine.cache.ai_set(x.id, "triage", dict(tri, spam=False))
        if ana and ana.get("suspicious"):
            engine.cache.ai_set(x.id, "analysis", dict(ana, suspicious=False))
    return msgs


def add_rule(engine, field, text, action, folder=""):
    r = {"field": field, "text": text.strip(), "action": action}
    if action == "move":
        r["folder"] = folder
    if not r["text"] or r in engine.config["rules"]:
        return False
    engine.config["rules"].append(r)
    engine.config.save()
    return True


def remove_rule(engine, index):
    rules = list(engine.config["rules"])
    if 0 <= index < len(rules):
        del rules[index]
        engine.config["rules"] = rules
        engine.config.save()
        return True
    return False


def apply_rules_now(engine):
    """Rejoue règles et listes sur la boîte de réception. Retourne (nombre restant, groupes à terminer)."""
    keep, plan = route(engine, engine.cache.query("inbox", "all"))
    return len(keep), apply_moves(engine, plan)


def sync_and_route(engine, folders=("inbox", "sent")):
    """Synchronise puis applique blocages, listes et règles aux seuls NOUVEAUX messages de la boîte (comme la version GTK).
    Retourne (nouveaux non lus restants, erreurs, groupes déplacés terminés)."""
    before = {m.id for m in engine.cache.query("inbox", "all")}
    fresh, errors = engine.sync(folders=folders)
    new = [m for m in engine.cache.query("inbox", "all") if m.id not in before]
    keep, plan = route(engine, new)
    done = []
    for msgs, dest, op_ids in apply_moves(engine, plan):
        errs, _off = engine.finish_move(msgs, dest, op_ids)
        errors += list(errs)
        done.append((dest, len(msgs)))
    return fresh - sum(1 for m in new if m.unread and m not in keep), errors, done
