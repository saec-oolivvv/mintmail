#!/usr/bin/env python3
"""Relecture d'une traduction par une personne dont c'est la langue — sans toucher au code ni à git.

  export  : écrit un tableau (CSV, s'ouvre dans LibreOffice / Excel) : texte français, anglais (aide), traduction actuelle, colonne « correction » vide.
  import  : relit le tableau ; chaque cellule « correction » non vide REMPLACE la traduction, après contrôle (marqueurs %s / %d / balises identiques).
            Tout ou rien : s'il y a une seule erreur, rien n'est écrit et les lignes fautives sont listées.
  --complete (avec --reviewer) : déclare la langue « relue par une personne » dans son fichier d'état (à ne faire que si TOUT a été relu).

Usage : tools/review_translations.py export  nl  relecture-nl.csv
        tools/review_translations.py import  nl  relecture-nl.csv --reviewer "Prénom Nom" [--complete]
Options : --dir DOSSIER (catalogues, par défaut mintmail/locale) · --delimiter ';' (défaut, Excel/LibreOffice en français) ou ','
"""
import argparse
import csv
import datetime
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from mintmail import i18n  # noqa: E402

COLUMNS = ["n", "francais", "anglais", "traduction", "correction"]


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _dump(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=0, sort_keys=True)


def _lang_ok(lang):
    return bool(re.fullmatch(r"[a-z]{2,3}", lang)) and lang not in ("fr", "en")


def export(lang, out, locale_dir, delimiter=";"):
    cat = _load(os.path.join(locale_dir, lang + ".json"))
    en = _load(os.path.join(locale_dir, "en.json")) if os.path.exists(os.path.join(locale_dir, "en.json")) else {}
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=delimiter, quoting=csv.QUOTE_ALL)
        w.writerow(COLUMNS)
        for n, src in enumerate(sorted(cat), 1):
            w.writerow([n, src, en.get(src, ""), cat[src], ""])
    return len(cat)


def import_(lang, path, locale_dir, reviewer="", complete=False, delimiter=";"):
    """Retourne (appliquées, inchangées, erreurs). Si erreurs non vide : rien n'a été écrit."""
    cat_path = os.path.join(locale_dir, lang + ".json")
    cat = _load(cat_path)
    errors, changes, same = [], {}, 0
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        if not reader.fieldnames or "francais" not in reader.fieldnames or "correction" not in reader.fieldnames:
            return 0, 0, ["En-têtes attendus : %s (séparateur « %s »)." % (", ".join(COLUMNS), delimiter)]
        for line, row in enumerate(reader, 2):
            fix = (row.get("correction") or "").strip()
            if not fix:
                continue
            src = row.get("francais") or ""
            if src not in cat:
                errors.append("ligne %d : texte source inconnu : %r" % (line, src[:60]))
                continue
            problems = i18n.check_entry(src, fix)
            if problems:
                errors.append("ligne %d : %s — %r" % (line, "; ".join(problems), fix[:60]))
                continue
            if fix == cat[src]:
                same += 1
            else:
                changes[src] = fix
    if complete and not reviewer.strip():
        errors.append("--complete exige --reviewer « Prénom Nom » : c'est la personne qui engage sa relecture.")
    if errors:
        return 0, same, errors
    cat.update(changes)
    _dump(cat_path, cat)
    st_path = os.path.join(locale_dir, lang + ".status.json")
    st = _load(st_path) if os.path.exists(st_path) else {}
    today = datetime.date.today().isoformat()
    if reviewer.strip() and changes:
        st["last_corrections_by"], st["last_corrections_on"] = reviewer.strip(), today
    if complete:
        st["reviewed_by_human"], st["reviewed_by"], st["reviewed_on"] = True, reviewer.strip(), today
    if st:
        with open(st_path, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=1)
    return len(changes), same, []


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=("export", "import"))
    ap.add_argument("lang")
    ap.add_argument("csv")
    ap.add_argument("--dir", default=os.path.join(ROOT, "mintmail", "locale"))
    ap.add_argument("--reviewer", default="")
    ap.add_argument("--complete", action="store_true")
    ap.add_argument("--delimiter", default=";")
    a = ap.parse_args(argv)
    if not _lang_ok(a.lang) or not os.path.exists(os.path.join(a.dir, a.lang + ".json")):
        print("Langue inconnue ou non relisible ici : %r (nl, de, es…)." % a.lang)
        return 1
    if a.action == "export":
        n = export(a.lang, a.csv, a.dir, a.delimiter)
        print("%d textes exportés dans %s — remplissez la colonne « correction » (laissez vide ce qui est bon), puis : import." % (n, a.csv))
        return 0
    done, same, errors = import_(a.lang, a.csv, a.dir, a.reviewer, a.complete, a.delimiter)
    if errors:
        print("RIEN n'a été modifié. À corriger :")
        for e in errors:
            print("  -", e)
        return 1
    print("%d correction(s) appliquée(s), %d identique(s) à l'existant." % (done, same))
    if a.complete:
        print("%s est maintenant déclarée relue par %s." % (a.lang, a.reviewer.strip()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
