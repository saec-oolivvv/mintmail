"""Arbre des dossiers de la barre latérale Qt (logique pure) : même comportement que la version GTK — dossiers repliables, sections par compte
quand il y a plusieurs boîtes, état replié mémorisé (réglage « collapsed_folders »). Les dossiers de base (Boîte de réception, Envoyés…) restent
dans les vues ; ici, les dossiers de rangement avec leur hiérarchie."""
from typing import Dict, List

from .viewmodel import LOGICAL, dest_of

SEP = " › "


def _path(e) -> str:
    return e.get("path") or e.get("label") or e["name"]


def toggle_key(aid, e) -> str:
    return "%s|%s" % (aid, _path(e))


def build(engine, collapsed=()) -> List[Dict]:
    """Lignes de la section « Dossiers » : [{kind: account|folder, key, label, depth, aid, name, selectable, toggle, collapsed, has_children}]."""
    collapsed, accounts, rows = set(collapsed or ()), engine.accounts(), []
    multi = len(accounts) > 1
    for acc in accounts:
        aid = acc["id"]
        ents = [e for e in engine.folder_entries(aid) if e.get("special") not in LOGICAL]
        if not ents:
            continue
        if multi:
            key = "acc:" + aid
            rows.append({"kind": "account", "key": key, "label": acc.get("name") or acc["email"], "depth": 0, "aid": aid, "name": "", "selectable": False,
                         "toggle": key, "collapsed": key in collapsed, "has_children": True, "email": acc["email"]})
            if key in collapsed:
                continue
        paths = [_path(e) for e in ents]
        skip = None
        for e, p in zip(ents, paths):
            if skip and p.startswith(skip + SEP):
                continue
            skip = None
            has_children = any(q.startswith(p + SEP) for q in paths)
            is_collapsed = has_children and toggle_key(aid, e) in collapsed
            if is_collapsed:
                skip = p
            depth = sum(1 for q in paths if p.startswith(q + SEP))              # ancêtres affichés
            rows.append({"kind": "folder", "key": dest_of(e), "label": e.get("label") or e["name"], "depth": depth, "aid": aid, "name": e["name"],
                         "selectable": bool(e.get("selectable", True)), "toggle": toggle_key(aid, e) if has_children else "",
                         "collapsed": is_collapsed, "has_children": has_children, "email": ""})
    return rows


def toggle(config, key) -> bool:
    """Plie ou déplie ; l'état est mémorisé. Retourne True si la ligne est maintenant repliée."""
    cur = set(config.get("collapsed_folders") or [])
    folded = key not in cur
    (cur.add if folded else cur.discard)(key)
    config["collapsed_folders"] = sorted(cur)
    config.save()
    return folded


def unread_of(engine, row) -> int:
    """Pastille d'un dossier : messages non lus annoncés par le serveur (relevés par Engine.refresh_folder_counts)."""
    if row["kind"] != "folder":
        return 0
    return int(engine.folder_unread.get((row["aid"], row["name"]), 0) or 0)


def account_unread(engine, row, rows) -> int:
    """Pastille d'un compte replié : somme des non lus de ses dossiers (les autres lignes du compte sont cachées)."""
    if row["kind"] != "account" or not row["collapsed"]:
        return 0
    return sum(int(v or 0) for (aid, _n), v in engine.folder_unread.items() if aid == row["aid"] and _n not in ("INBOX", "Drafts", "Sent", "Archive", "Spam", "Trash"))
