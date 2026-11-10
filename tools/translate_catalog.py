#!/usr/bin/env python3
"""Pré-traduit l'interface de MintMail dans une autre langue avec un service d'IA compatible OpenAI (Ollama, serveur interne, cloud…).

  tools/translate_catalog.py --lang de --base-url http://localhost:11434/v1 --model llama3.1
  tools/translate_catalog.py --lang nl --base-url https://api.exemple.be/v1 --model gpt-x --key-env MON_JETON --help-too
  tools/translate_catalog.py --lang de --check        (valide un catalogue existant, sans réseau)

Chaque traduction est contrôlée (marqueurs %s / %d / %(x)s, balises HTML, espaces et retours à la ligne identiques à la source) ; les entrées
refusées sont redemandées avec la liste des défauts, puis laissées de côté (l'interface retombe alors sur le français). Le fichier est
réécrit après chaque lot : on peut interrompre et reprendre. Le texte français ET sa traduction anglaise sont donnés au modèle (meilleure qualité).
RÉSULTAT : une traduction AUTOMATIQUE, à faire relire par un locuteur avant de la publier (un fichier <langue>.status.json le rappelle).
La clé d'API se passe par variable d'environnement (--key-env), jamais en argument ; elle n'est jamais affichée ni enregistrée.
"""
import argparse
import datetime
import ipaddress
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from mintmail import i18n   # noqa: E402

LANG_NAMES = {"nl": "Dutch", "de": "German", "es": "Spanish", "it": "Italian", "pt": "Portuguese", "pl": "Polish", "sv": "Swedish", "da": "Danish",
              "ca": "Catalan", "ro": "Romanian", "cs": "Czech", "tr": "Turkish", "ar": "Arabic", "ja": "Japanese", "zh": "Simplified Chinese"}
SYSTEM = ("You are a professional software localizer translating the user interface of a desktop e-mail client. Translate each entry from French "
          "into {lang}. An English reference is provided: use it to disambiguate, but translate from the French meaning. RULES: keep every "
          "printf marker (%s, %d, %02d, %.0s, %(name)s) EXACTLY, with the same count and order; keep HTML tags and attributes untouched; keep leading "
          "and trailing spaces and newlines; keep proper names, key names (Ctrl, Esc, F1), file names, commands and URLs unchanged; keep the "
          "'(s)' plural convention only if natural in the target language; use short, natural UI wording. Reply with ONLY a JSON object mapping each "
          "id to its translation, no commentary.")


def check_base_url(url):
    p = urllib.parse.urlparse(url)
    host = (p.hostname or "").lower()
    local = host == "localhost"
    try:
        ip = ipaddress.ip_address(host)
        local = local or not ip.is_global
    except ValueError:
        pass
    if p.scheme == "https" or (p.scheme == "http" and local):
        return
    raise SystemExit("Adresse refusée : https:// obligatoire (http:// seulement pour cette machine ou le réseau local).")


def chat(base_url, model, key, system, user, timeout=180):
    body = json.dumps({"model": model, "temperature": 0.2, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}).encode()
    req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", data=body, headers={"Content-Type": "application/json"})
    if key:
        req.add_header("Authorization", "Bearer " + key)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]


def parse_obj(text):
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip())
    a, b = text.find("{"), text.rfind("}")
    obj = json.loads(text[a:b + 1])
    if not isinstance(obj, dict):
        raise ValueError("pas un objet JSON")
    return {str(k): v for k, v in obj.items() if isinstance(v, str)}


def translate_items(items, args, key, system):
    """items : {clé_source: (français, anglais)} -> ({clé_source: traduction valide}, {clé_source: défauts})."""
    ids = {str(i): k for i, k in enumerate(items)}
    good, bad = {}, {}
    todo = dict(ids)
    notes = {}
    for attempt in range(args.retries + 1):
        if not todo:
            break
        payload = {i: {"fr": k, "en": items[k][1]} for i, k in todo.items()}
        user = json.dumps(payload, ensure_ascii=False)
        if notes:
            user += "\n\nPREVIOUS ANSWER WAS REJECTED FOR THESE IDS, fix exactly these problems:\n" + json.dumps({i: notes[i] for i in todo if i in notes}, ensure_ascii=False)
        try:
            got = parse_obj(chat(args.base_url, args.model, key, system, user))
        except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
            print("  ! erreur de service (%s)" % type(e).__name__, file=sys.stderr)
            got = {}
        nxt = {}
        for i, k in todo.items():
            v = got.get(i)
            problems = i18n.check_entry(k, v) if v is not None else ["pas de réponse"]
            if problems:
                nxt[i], notes[i] = k, problems
            else:
                good[k] = v
        todo = nxt
    for i, k in todo.items():
        bad[k] = notes.get(i, ["?"])
    return good, bad


def save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=0, sort_keys=True)
    os.replace(tmp, path)


def translate_help(args, key, system, locale_dir, lang):
    src = json.load(open(os.path.join(locale_dir, "help_en.json"), encoding="utf-8"))
    ph = lambda s: sorted(re.findall(r"\{\w+\}|@\w+@", s))
    out = {"sections": [], "shortcuts": [], "cli": []}

    def one(text):
        for _ in range(args.retries + 1):
            try:
                got = parse_obj(chat(args.base_url, args.model, key, system.replace("from French", "from English").replace("The French", "The English"),
                                     json.dumps({"1": {"fr": text, "en": text}}, ensure_ascii=False)))
                v = got.get("1")
            except (urllib.error.URLError, OSError, ValueError, KeyError):
                v = None
            if v and ph(v) == ph(text) and v.count("\n") == text.count("\n") and v.count("• ") == text.count("• "):
                return v
        return None
    failed = 0
    for s in src["sections"]:
        sec = {"id": s["id"], "title": one(s["title"]) or s["title"], "items": []}
        for t, b in s["items"]:
            tt, bb = one(t), one(b)
            failed += (tt is None) + (bb is None)
            sec["items"].append([tt or t, bb or b])
        out["sections"].append(sec)
    for k, d in src["shortcuts"]:
        dd = one(d)
        failed += dd is None
        out["shortcuts"].append([k, dd or d])
    for c, d in src["cli"]:
        dd = one(d)
        failed += dd is None
        out["cli"].append([c, dd or d])
    save_json(os.path.join(locale_dir, "help_%s.json" % lang), out)
    print("Aide : %s (%d texte(s) restés en anglais)" % ("écrite", failed))
    return failed


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--lang", required=True, help="code de langue (de, nl, es…)")
    ap.add_argument("--base-url"), ap.add_argument("--model"), ap.add_argument("--key-env", default="MINTMAIL_TRANSLATE_KEY")
    ap.add_argument("--batch", type=int, default=25), ap.add_argument("--retries", type=int, default=2), ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--locale-dir", default=os.path.join(ROOT, "mintmail", "locale")), ap.add_argument("--lang-name")
    ap.add_argument("--help-too", action="store_true", help="traduit aussi l'aide intégrée (depuis l'anglais)"), ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    lang, ld = args.lang.lower(), args.locale_dir
    if lang in ("fr", "en"):
        raise SystemExit("Le français est la langue source et l'anglais est relu à la main : rien à pré-traduire.")
    ids = json.load(open(os.path.join(ROOT, "tools", "i18n_msgids.json"), encoding="utf-8"))
    en = json.load(open(os.path.join(ld, "en.json"), encoding="utf-8"))
    path = os.path.join(ld, lang + ".json")
    cat = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
    cat = {k: v for k, v in cat.items() if k in ids and not i18n.check_entry(k, v)}       # on ne garde que le valide
    missing = [k for k in ids if k not in cat]
    if args.check:
        print("%s : %d / %d chaînes valides, %d manquantes" % (lang, len(cat), len(ids), len(missing)))
        return 0 if not missing else 1
    if not args.base_url or not args.model:
        raise SystemExit("--base-url et --model sont requis (sauf avec --check).")
    check_base_url(args.base_url)
    key = os.environ.get(args.key_env, "")
    lang_name = args.lang_name or LANG_NAMES.get(lang, lang)
    system = SYSTEM.format(lang=lang_name)
    if args.limit:
        missing = missing[:args.limit]
    print("%s : %d chaîne(s) à traduire (%d déjà valides)" % (lang_name, len(missing), len(cat)))
    rejected = {}
    for i in range(0, len(missing), args.batch):
        part = {k: (k, en.get(k, k)) for k in missing[i:i + args.batch]}
        good, bad = translate_items(part, args, key, system)
        cat.update(good)
        rejected.update(bad)
        save_json(path, cat)
        print("  lot %d/%d : %d traduites, %d refusées" % (i // args.batch + 1, (len(missing) + args.batch - 1) // args.batch, len(good), len(bad)))
    failed_help = translate_help(args, key, system, ld, lang) if args.help_too else 0
    save_json(os.path.join(ld, lang + ".status.json"), {
        "machine_translated": True, "reviewed_by_human": False, "model": args.model, "date": datetime.date.today().isoformat(),
        "strings": len(cat), "of": len(ids), "rejected": len(rejected), "help_untranslated": failed_help})
    print("Terminé : %d / %d chaînes. Entrées refusées (restent en français) : %d. TRADUCTION AUTOMATIQUE : à faire relire avant publication." % (len(cat), len(ids), len(rejected)))
    return 0 if not rejected and not failed_help else 1


if __name__ == "__main__":
    sys.exit(main())
