"""Outils de relecture des traductions par un locuteur : export CSV, import validé « tout ou rien », déclaration de relecture."""
import csv, json, os, shutil, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import review_translations as R

SRC = {"Bonjour": ("Hello", "Hallo"), "Fermer": ("Close", "Sluiten"), "Il y a %d messages": ("There are %d messages", "Er zijn %d berichten"),
       "<b>Gras</b> et « guillemets »; point-virgule": ("<b>Bold</b>", "<b>Vet</b>"), "Deux\nlignes": ("Two\nlines", "Twee\nregels")}


def make_dir():
    d = tempfile.mkdtemp()
    json.dump({k: v[0] for k, v in SRC.items()}, open(os.path.join(d, "en.json"), "w", encoding="utf-8"), ensure_ascii=False)
    json.dump({k: v[1] for k, v in SRC.items()}, open(os.path.join(d, "nl.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=0, sort_keys=True)
    json.dump({"machine_translated": True, "translator": "Claude (IA)", "reviewed_by_human": False, "complete": True, "strings": 5, "of": 5}, open(os.path.join(d, "nl.status.json"), "w"))
    json.dump({"Bonjour": "Hallo"}, open(os.path.join(d, "de.json"), "w", encoding="utf-8"))
    return d


def fill(path, corrections, delimiter=";"):
    rows = list(csv.reader(open(path, encoding="utf-8-sig", newline=""), delimiter=delimiter))
    head = rows[0]
    out = [head]
    for r in rows[1:]:
        r = list(r)
        r[head.index("correction")] = corrections.get(r[head.index("francais")], "")
        out.append(r)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        csv.writer(f, delimiter=delimiter, quoting=csv.QUOTE_ALL).writerows(out)


def test_export_lists_every_text_with_french_english_and_current_translation_and_survives_special_characters():
    d = make_dir()
    out = os.path.join(d, "r.csv")
    assert R.export("nl", out, d) == 5
    rows = list(csv.DictReader(open(out, encoding="utf-8-sig", newline=""), delimiter=";"))
    assert [r["n"] for r in rows] == ["1", "2", "3", "4", "5"] and set(rows[0]) == set(R.COLUMNS)
    by = {r["francais"]: r for r in rows}
    assert set(by) == set(SRC) and by["Fermer"]["anglais"] == "Close" and by["Fermer"]["traduction"] == "Sluiten" and by["Fermer"]["correction"] == ""
    assert by["Deux\nlignes"]["traduction"] == "Twee\nregels" and "; point-virgule" in "".join(by).replace("point-virgule", "; point-virgule") and by["<b>Gras</b> et « guillemets »; point-virgule"]["traduction"] == "<b>Vet</b>"
    assert open(out, "rb").read().startswith(b"\xef\xbb\xbf")                                         # BOM : LibreOffice / Excel reconnaissent l'UTF-8
    out2 = os.path.join(d, "r2.csv")
    R.export("nl", out2, d, delimiter=",")
    assert list(csv.DictReader(open(out2, encoding="utf-8-sig", newline=""), delimiter=","))[0]["francais"] in SRC


def test_import_applies_validated_corrections_ignores_blanks_and_is_idempotent():
    d = make_dir()
    out = os.path.join(d, "r.csv")
    R.export("nl", out, d)
    fill(out, {"Fermer": "Afsluiten", "Bonjour": "Hallo", "Il y a %d messages": "Er zijn %d berichten in totaal", "<b>Gras</b> et « guillemets »; point-virgule": "<b>Vetgedrukt</b>"})
    before_de = open(os.path.join(d, "de.json"), "rb").read()
    done, same, errors = R.import_("nl", out, d)
    assert (done, same, errors) == (3, 1, [])                                                          # « Bonjour » identique : compté mais pas modifié
    cat = json.load(open(os.path.join(d, "nl.json"), encoding="utf-8"))
    assert cat["Fermer"] == "Afsluiten" and cat["Il y a %d messages"].endswith("totaal") and cat["Deux\nlignes"] == "Twee\nregels"       # le reste est intact
    assert open(os.path.join(d, "de.json"), "rb").read() == before_de                                  # les autres langues ne sont pas touchées
    assert json.load(open(os.path.join(d, "nl.status.json")))["reviewed_by_human"] is False           # des corrections ne valent PAS relecture complète
    assert R.import_("nl", out, d)[:2] == (0, 4) and R.import_("nl", out, d)[2] == []                  # relancer ne change plus rien


def test_import_is_all_or_nothing_and_reports_each_faulty_line():
    d = make_dir()
    out = os.path.join(d, "r.csv")
    R.export("nl", out, d)
    fill(out, {"Fermer": "Afsluiten", "Il y a %d messages": "Er zijn berichten", "Bonjour": "Hallo <b>x"})                  # marqueur %d perdu ; balise ajoutée
    rows = list(csv.reader(open(out, encoding="utf-8-sig", newline=""), delimiter=";"))
    rows.append(["99", "Texte qui n'existe pas", "", "", "Quelque chose"])
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        csv.writer(f, delimiter=";", quoting=csv.QUOTE_ALL).writerows(rows)
    snap = open(os.path.join(d, "nl.json"), "rb").read()
    done, same, errors = R.import_("nl", out, d)
    assert done == 0 and len(errors) == 3 and any("source inconnu" in e for e in errors) and any("%d" in e or "marqueur" in e.lower() or "format" in e.lower() for e in errors), errors
    assert open(os.path.join(d, "nl.json"), "rb").read() == snap                                       # la bonne ligne n'est PAS appliquée seule : tout ou rien
    bad = os.path.join(d, "mauvais.csv")
    open(bad, "w", encoding="utf-8").write("a;b\n1;2\n")
    assert "En-têtes attendus" in R.import_("nl", bad, d)[2][0]


def test_declaring_a_language_reviewed_requires_a_named_reviewer_and_everything_is_recorded():
    d = make_dir()
    out = os.path.join(d, "r.csv")
    R.export("nl", out, d)
    fill(out, {"Fermer": "Afsluiten"})
    snap = open(os.path.join(d, "nl.json"), "rb").read()
    assert R.import_("nl", out, d, reviewer="", complete=True)[2] and open(os.path.join(d, "nl.json"), "rb").read() == snap      # --complete sans nom : refusé, rien d'écrit
    done, same, errors = R.import_("nl", out, d, reviewer="Jan Peeters", complete=True)
    st = json.load(open(os.path.join(d, "nl.status.json")))
    assert errors == [] and done == 1 and st["reviewed_by_human"] is True and st["reviewed_by"] == "Jan Peeters" and st["reviewed_on"] and st["last_corrections_by"] == "Jan Peeters"
    assert st["machine_translated"] is True and st["translator"] == "Claude (IA)"                      # l'origine reste honnêtement indiquée


def test_cli_rejects_unknown_or_dangerous_language_names_and_works_end_to_end():
    d = make_dir()
    out = os.path.join(d, "r.csv")
    for bad in ("fr", "en", "../etc", "nl/../de", "xx", ""):
        assert R.main(["export", bad, out, "--dir", d]) == 1, bad
    assert R.main(["export", "nl", out, "--dir", d]) == 0 and os.path.exists(out)
    fill(out, {"Fermer": "Afsluiten"})
    assert R.main(["import", "nl", out, "--dir", d, "--reviewer", "Jan"]) == 0
    assert json.load(open(os.path.join(d, "nl.json"), encoding="utf-8"))["Fermer"] == "Afsluiten"
    fill(out, {"Il y a %d messages": "kapot"})
    assert R.main(["import", "nl", out, "--dir", d]) == 1
    # sur les VRAIS catalogues : l'export couvre tout et un import à vide ne change rien
    real = os.path.join(ROOT, "mintmail", "locale")
    tmpd = tempfile.mkdtemp()
    for f in os.listdir(real):
        shutil.copy(os.path.join(real, f), tmpd)
    for lang in ("nl", "de", "es"):
        o = os.path.join(tmpd, lang + ".csv")
        n = R.export(lang, o, tmpd)
        snap = open(os.path.join(tmpd, lang + ".json"), "rb").read()
        assert n == len(json.load(open(os.path.join(real, lang + ".json"), encoding="utf-8"))) and R.import_(lang, o, tmpd)[:3] == (0, 0, [])
        assert open(os.path.join(tmpd, lang + ".json"), "rb").read() == snap
