#!/usr/bin/env python3
"""Enveloppe dans tr() les chaînes d'interface françaises de mintmail/*.py (réécriture par analyse du code, jamais par expression régulière).

  tools/i18n_wrap.py --check     rapport : à envelopper, à retirer, douteux (ne modifie rien)
  tools/i18n_wrap.py --apply     enveloppe ce qui doit l'être (idempotent)
  tools/i18n_wrap.py --unwrap    retire tr() autour de ce qui ne doit pas être traduit (identifiants, CSS, protocoles…)
  tools/i18n_wrap.py --catalog   écrit tools/i18n_msgids.json : toutes les chaînes enveloppées (langue source : français)

Jamais traduits : données (noms de dossiers à reconnaître, mots-clés de détection, démo), invites de l'IA, journaux, comparaisons, clés de
dictionnaires, expressions régulières, identifiants / noms d'icônes / couleurs / URL, commandes de protocole, gabarits CSS / HTML sans texte.
Une ligne marquée « # i18n: skip » n'est jamais modifiée. Fichiers ignorés mais avec lignes choisies : tools/i18n_manual.txt.
"""
import ast
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(ROOT, "mintmail")
SKIP_FILES = {"help_content.py", "ai_service.py", "ai_engine.py", "diagnose.py", "log.py", "i18n.py", "__init__.py", "__main__.py",
              "syncdata.py", "netutil.py", "htmlsafe.py", "tasks.py", "contacts.py", "p2p.py", "store.py", "ical.py", "apply_update.py", "updater.py"}
NEVER_CONST = {("backend.py", n) for n in ("GUESS", "SPECIAL", "LOGICAL", "TOP_RANK", "_DEMO", "DEMO_FOLDERS", "DEMO_FOLDER_MSGS")} | {
    ("folders.py", "LOGICAL"), ("folders.py", "SPECIAL_ICONS"), ("style.py", "NAV_TINTS"), ("style.py", "BASE"), ("window.py", "DEMO_ACCOUNT"),
    ("widgets.py", "DEFAULT_SWIPE")}
NEVER_SCOPE = {"DemoBackend", "_dfolder", "_demo_messages"}
SKIP_VALUES = {"(Sans objet)"}                       # stocké dans le cache : reste tel quel
FR = re.compile(r"[À-ÿœŒ]|\b(le|la|les|des|un|une|vous|votre|vos|pour|dans|sur|avec|du|et|ou|pas|est|ce|cette|aucun|aucune|nouveau|nouvelle|"
                r"ajouter|enregistrer|annuler|fermer|ouvrir|supprimer|erreur|impossible|message|messages|compte|comptes|dossier|dossiers|"
                r"archiver|reporter|favori|rechercher|actualiser|tester|appliquer|choisir|voir|tout|tous|toutes|non|oui|merci|bonjour|"
                r"lecture|réponse|répondre|envoyer|envoi|brouillon|brouillons|signature|signatures|règle|règles|modèle|modèles|"
                r"tâche|tâches|disposition|apparence|réglages|paramètres|connexion|serveur|mot de passe)\b", re.I)
UI_KW = {"label", "title", "text", "secondary_text", "placeholder_text", "tooltip_text", "tip", "message"}
UI_METHODS = {"set_label", "set_text", "set_markup", "set_tooltip_text", "set_placeholder_text", "set_title", "set_comments", "popup",
              "add_titled", "add_button", "add_buttons", "append_text", "set_program_name"}
LOGIC_CALLS = {"compile", "sub", "search", "match", "split", "findall", "fullmatch", "get", "getattr", "hasattr", "setdefault", "startswith",
               "endswith", "replace", "index", "count", "strftime", "strptime", "pop", "format_map", "encode", "decode", "connect",
               "add_class", "remove_class", "set_name", "pack_start", "set_halign", "set_valign", "get_property", "set_property", "emit", "new",
               "lower", "upper", "strip", "lstrip", "rstrip", "rsplit", "partition", "rpartition"}
TECH = re.compile(r"[a-z0-9_\-.:/#]+|#[0-9a-fA-F]{3,8}|[\w.\-]+\.(vcf|ics|json|txt|png|svg)|https?://\S*")


def technical(s):
    """Identifiant, nom d'icône, clé de réglage, couleur, URL, nom de fichier : jamais traduit."""
    t = s.strip()
    return bool(TECH.fullmatch(t)) or t.endswith("-symbolic")


def protocol_like(s):
    """Commande / constante de protocole en majuscules (IMAP, HTTP…)."""
    t = s.strip()
    return bool(re.fullmatch(r"[\(\)A-Z0-9 _\-\./:\\]+", t)) and len(t) > 1


def visible_text(s):
    """Ce qu'un utilisateur lirait : sans <style>/<script>, balises, blocs CSS, marqueurs de format et jetons @@…@@."""
    t = re.sub(r"(?is)<(style|script)\b.*?</\1\s*>", " ", s)
    t = re.sub(r"<[^>]*>", " ", t)
    t = re.sub(r"\{[^{}]*\}", " ", t)
    return re.sub(r"%\(\w+\)[sd]|%[sdr]|@@\w+@@|&\w+;", " ", t)


def load_words():
    path = os.path.join(ROOT, "tools", "i18n_words.txt")
    return {l.strip() for l in open(path, encoding="utf-8") if l.strip()} if os.path.exists(path) else set()


def load_manual():
    """Chaînes à traiter dans les fichiers normalement ignorés, PAR VALEUR (tools/i18n_manual.jsonl : {"f": fichier, "s": texte})."""
    out = {}
    path = os.path.join(ROOT, "tools", "i18n_manual.jsonl")
    if os.path.exists(path):
        for l in open(path, encoding="utf-8"):
            if l.strip():
                d = json.loads(l)
                out.setdefault(d["f"], set()).add(d["s"])
    return out


def parse(path):
    src = open(path, encoding="utf-8").read()
    tree = ast.parse(src)
    parents = {}
    for n in ast.walk(tree):
        for c in ast.iter_child_nodes(n):
            parents[c] = n
    return src, tree, parents


def enclosing(node, parents, kinds):
    while node in parents:
        node = parents[node]
        if isinstance(node, kinds):
            return node
    return None


def is_wrapped(node, parents):
    p = parents.get(node)
    return isinstance(p, ast.Call) and isinstance(p.func, ast.Name) and p.func.id == "tr"


def top_assign_name(node, parents):
    cur = node
    while cur in parents and not isinstance(parents[cur], ast.Module):
        cur = parents[cur]
    if isinstance(cur, (ast.Assign, ast.AnnAssign)):
        t = cur.targets[0] if isinstance(cur, ast.Assign) else cur.target
        return t.id if isinstance(t, ast.Name) else None
    return None


def classify(node, parents, mod, words):
    """('wrap', raison) ou (None, raison) — jugé comme si la chaîne n'était PAS enveloppée."""
    s = node.value
    if len(s.strip()) < 2 or s in SKIP_VALUES or not re.search(r"[A-Za-zÀ-ÿ]{2}", s):
        return None, "court / sans lettres"
    if (technical(s) or protocol_like(s)) and s.strip() not in words:
        return None, "technique / protocole"
    p = parents.get(node)
    if is_wrapped(node, parents):
        p = parents.get(p)
    if isinstance(p, ast.Expr):
        return None, "docstring"
    if isinstance(p, ast.JoinedStr):
        return None, "fstring"
    if isinstance(p, ast.Compare) or (isinstance(p, (ast.Tuple, ast.List, ast.Set)) and isinstance(parents.get(p), ast.Compare)):
        return None, "comparaison"
    if isinstance(p, ast.Dict) and node in p.keys:
        return None, "clé de dictionnaire"
    if isinstance(p, ast.Subscript):
        return None, "indice"
    if isinstance(p, ast.keyword) and p.arg in ("id", "name", "key", "kind", "mode", "encoding", "domain", "prefix", "suffix", "filename"):
        return None, "mot-clé technique"
    outer = p
    while isinstance(outer, ast.BinOp):                    # log("… %s" % x) : le texte est sous une opération, pas directement sous l'appel
        outer = parents.get(outer)
    if isinstance(outer, ast.Call) and isinstance(outer.func, (ast.Name, ast.Attribute)) and \
            (outer.func.id if isinstance(outer.func, ast.Name) else outer.func.attr) in ("log", "log_exception", "debug", "info", "warning", "exception"):
        return None, "journal"
    call = p if isinstance(p, ast.Call) else (parents.get(p) if isinstance(p, ast.keyword) else None)
    name = ""
    if isinstance(call, ast.Call):
        fn = call.func
        name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else ""
        if name in ("log", "log_exception", "debug", "info", "warning", "exception"):          # print = sortie de la ligne de commande : à traduire
            return None, "journal"
        if name in LOGIC_CALLS and not isinstance(p, ast.keyword) and name not in UI_METHODS:
            return None, "appel logique"
    scope = enclosing(node, parents, (ast.ClassDef, ast.FunctionDef))
    while scope is not None:
        if getattr(scope, "name", "") in NEVER_SCOPE:
            return None, "démo"
        scope = enclosing(scope, parents, (ast.ClassDef, ast.FunctionDef))
    nm = top_assign_name(node, parents)
    if nm and (mod, nm) in NEVER_CONST:
        return None, "donnée"
    if FR.search(visible_text(s)):
        return "wrap", "français"
    if s.strip() in words:
        return "wrap", "vocabulaire"
    if isinstance(p, ast.keyword) and p.arg in UI_KW:
        return "wrap", "mot-clé d'affichage"
    if name in UI_METHODS or name == "icon_button":
        return "wrap", "méthode d'affichage"
    return None, "autre"


def scan(words):
    """[(fichier, nœud, décision, raison, enveloppé)] pour toutes les chaînes des fichiers concernés."""
    manual, out = load_manual(), []
    for fn in sorted(os.listdir(PKG)):
        if not fn.endswith(".py") or (fn in SKIP_FILES and fn not in manual):
            continue
        src, tree, parents = parse(os.path.join(PKG, fn))
        lines = src.split("\n")
        for n in ast.walk(tree):
            if isinstance(n, ast.Constant) and isinstance(n.value, str):
                dec, why = classify(n, parents, fn, words)
                if "# i18n: skip" in lines[n.lineno - 1]:
                    dec, why = None, "marqué skip"
                if fn in SKIP_FILES:
                    dec, why = ("wrap", "manuel") if n.value in manual.get(fn, ()) and not (why in ("docstring", "comparaison", "journal")) else (None, "fichier ignoré")
                out.append((fn, n, dec, why, is_wrapped(n, parents)))
    return out


def rewrite(fn, edits):
    """edits : [(nœud, 'wrap'|'unwrap', nœud_appel)] — travaille sur les octets UTF-8 (col_offset est en octets)."""
    path = os.path.join(PKG, fn)
    lines = [l.encode("utf-8") for l in open(path, encoding="utf-8").read().split("\n")]
    for node, kind, call in sorted(edits, key=lambda e: (e[0].lineno, e[0].col_offset), reverse=True):
        if kind == "wrap":
            l1, c1, l2, c2 = node.lineno, node.col_offset, node.end_lineno, node.end_col_offset
            lines[l2 - 1] = lines[l2 - 1][:c2] + b")" + lines[l2 - 1][c2:]
            lines[l1 - 1] = lines[l1 - 1][:c1] + b"tr(" + lines[l1 - 1][c1:]
        else:
            # retire d'abord la parenthèse fermante (fin), puis « tr( » (début) : les décalages restent valables
            le = lines[call.end_lineno - 1]
            assert le[call.end_col_offset - 1:call.end_col_offset] == b")", (fn, call.lineno)
            lines[call.end_lineno - 1] = le[:call.end_col_offset - 1] + le[call.end_col_offset:]
            ls = lines[call.lineno - 1]
            assert ls[call.col_offset:call.col_offset + 3] == b"tr(", (fn, call.lineno)
            lines[call.lineno - 1] = ls[:call.col_offset] + ls[call.col_offset + 3:]
    text = b"\n".join(lines).decode("utf-8")
    if any(k == "wrap" for _n, k, _c in edits) and not re.search(r"^from \.i18n import .*\btr\b", text, re.M):
        tree = ast.parse(text)
        last = 0
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                last = node.end_lineno
            elif isinstance(node, ast.Expr) and isinstance(getattr(node, "value", None), ast.Constant):
                continue
            elif last:
                break
        ls = text.split("\n")
        ls.insert(last, "from .i18n import tr")
        text = "\n".join(ls)
    open(path, "w", encoding="utf-8").write(text)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "--check"
    words = load_words()
    if mode == "--catalog":
        ids = {}
        for fn in sorted(os.listdir(PKG)):
            if fn.endswith(".py") and fn != "i18n.py":
                for n in ast.walk(ast.parse(open(os.path.join(PKG, fn), encoding="utf-8").read())):
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "tr" and n.args \
                            and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str):
                        ids.setdefault(n.args[0].value, set()).add(fn)
        json.dump({k: sorted(v) for k, v in sorted(ids.items())}, open(os.path.join(ROOT, "tools", "i18n_msgids.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print("%d chaînes distinctes" % len(ids))
        return
    items = scan(words)
    to_wrap = [(fn, n) for fn, n, d, w, wr in items if d == "wrap" and not wr]
    to_unwrap = [(fn, n) for fn, n, d, w, wr in items if d != "wrap" and wr]
    if mode in ("--apply", "--unwrap"):
        edits = {}
        for fn, n in (to_wrap if mode == "--apply" else []):
            edits.setdefault(fn, []).append((n, "wrap", None))
        if mode == "--unwrap":
            for fn in {f for f, _ in to_unwrap}:
                src, tree, parents = parse(os.path.join(PKG, fn))
                key = {(n.lineno, n.col_offset) for f, n in to_unwrap if f == fn}
                for n in ast.walk(tree):
                    if isinstance(n, ast.Constant) and (n.lineno, n.col_offset) in key and is_wrapped(n, parents):
                        edits.setdefault(fn, []).append((n, "unwrap", parents[n]))
        for fn, e in edits.items():
            rewrite(fn, e)
        print("%d chaînes %s dans %d fichiers" % (sum(map(len, edits.values())), "enveloppées" if mode == "--apply" else "retirées", len(edits)))
        return
    print("À ENVELOPPER : %d | À RETIRER (enveloppées à tort) : %d" % (len(to_wrap), len(to_unwrap)))
    for fn, n in to_unwrap[:60]:
        print("  retirer %s:%d  %r" % (fn, n.lineno, n.value[:70]))
    left = [(fn, n.lineno, n.value) for fn, n, d, w, wr in items if d is None and w == "autre" and not wr and re.match(
        r"^[A-ZÉÈÀ][\w'’éèêàùçôîï\-]+( [\w'’éèêàùçôîï\-:,.!?()/]+){0,6}[.:!?…]?$", n.value.strip()) and len(n.value) < 90 and not protocol_like(n.value)]
    print("DOUTEUX (non enveloppés, mot capitalisé) : %d" % len(left))
    for x in left[:120]:
        print("  %s:%d  %r" % x)


if __name__ == "__main__":
    main()
