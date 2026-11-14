"""Traduction de l'interface : le catalogue couvre exactement le code, les traductions sont sûres (marqueurs, balises), la langue se choisit
correctement, le français (langue source) reste strictement inchangé, et l'anglais fonctionne de bout en bout."""
import ast, glob, json, os, re, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
os.environ.setdefault("XDG_DATA_HOME", tempfile.mkdtemp())
os.environ.setdefault("XDG_CONFIG_HOME", tempfile.mkdtemp())
import testenv
from mintmail import i18n

PKG = os.path.join(ROOT, "mintmail")
LOCALE = os.path.join(PKG, "locale")


def code_msgids():
    ids = set()
    for f in glob.glob(os.path.join(PKG, "*.py")) + glob.glob(os.path.join(PKG, "qt", "*.py")):
        if os.path.basename(f) == "i18n.py":
            continue
        for n in ast.walk(ast.parse(open(f, encoding="utf-8").read())):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "tr" and n.args \
                    and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str):
                ids.add(n.args[0].value)
    return ids


def catalogs():
    """Catalogues d'interface (xx.json) — ni les aides (help_xx.json) ni les fichiers d'état (xx.status.json)."""
    return {os.path.basename(p)[:-5]: json.load(open(p, encoding="utf-8")) for p in glob.glob(os.path.join(LOCALE, "*.json")) if re.fullmatch(r"[a-z]{2,3}\.json", os.path.basename(p))}


def run(code, lang="en"):
    env = dict(os.environ, MINTMAIL_LANG=lang, PYTHONPATH=ROOT, PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, cwd=ROOT, timeout=120)
    assert r.returncode == 0, r.stderr[-800:]
    return r.stdout


def test_english_catalog_covers_the_code_exactly():
    cat, ids = catalogs()["en"], code_msgids()
    assert not (ids - set(cat)), "chaînes sans traduction : %s" % sorted(ids - set(cat))[:8]
    assert not (set(cat) - ids), "traductions périmées (plus dans le code) : %s" % sorted(set(cat) - ids)[:8]
    assert len(ids) > 900


def test_every_catalog_entry_keeps_placeholders_tags_and_spacing():
    for lang, cat in catalogs().items():
        bad = [(k[:60], i18n.check_entry(k, v)) for k, v in cat.items() if i18n.check_entry(k, v)]
        assert not bad, (lang, bad[:5])
    assert i18n.check_entry("%d message%s", "%d message") == ["marqueurs de format différents"]
    assert i18n.check_entry("<b>%s</b>", "%s") == ["balises différentes"]
    assert i18n.check_entry("a ", "a") and i18n.check_entry("a", " ") and i18n.check_entry("a", "")
    assert i18n.check_entry("%d message%s · %d non lu%s", "%d message%s · %d unread%.0s") == []       # %.0s : consomme l'argument sans l'afficher
    assert i18n.check_entry("à %(who)s", "to %(who)s") == [] and i18n.check_entry("à %(who)s", "to %(whom)s")


def test_english_catalog_has_no_french_leftovers():
    acc = re.compile(r"[àâçéèêëîïôûùüÿœÀÂÇÉÈÊËÎÏÔÛÙÜŸŒ]")
    stop = re.compile(r"\b(le|la|les|des|pour|vous|votre|vos|avec|une|dans|sur|est|pas|et|ou|du|ce|cette|sans|aucun|aucune|nouveau)\b", re.I)
    bad = []
    for fr, en in catalogs()["en"].items():
        plain = re.sub(r"<[^>]+>|%\([^)]*\)[sd]|%[sd]", " ", en)
        if acc.search(plain) or stop.search(plain):
            bad.append((fr[:50], en[:80]))
    assert not bad, bad[:6]


def test_language_resolution_and_fallbacks():
    saved = {k: os.environ.pop(k, None) for k in ("MINTMAIL_LANG", "LC_ALL", "LC_MESSAGES", "LANGUAGE", "LANG")}
    try:
        assert "fr" in i18n.available() and "en" in i18n.available()
        os.environ["LANG"] = "en_GB.UTF-8"
        assert i18n.resolve("auto") == "en"
        os.environ["LANG"] = "fr_BE.UTF-8"
        assert i18n.resolve("auto") == "fr" and i18n.resolve("en") == "en" and i18n.resolve("fr") == "fr"
        os.environ["LANG"] = "xx_YY.UTF-8"                                            # langue sans catalogue : l'anglais, langue de repli
        assert i18n.resolve("auto") == "en" and i18n.resolve("xx") == "en"
        os.environ["LANGUAGE"] = "fr:en"                                              # la variable LANGUAGE prime et peut contenir une liste
        assert i18n.resolve("auto") == "fr"
        os.environ["MINTMAIL_LANG"] = "fr"                                            # la variable du programme prime sur tout
        assert i18n.resolve("en") == "fr"
    finally:
        for k in ("MINTMAIL_LANG", "LC_ALL", "LC_MESSAGES", "LANGUAGE", "LANG"):
            os.environ.pop(k, None)
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v
    try:
        assert i18n.set_language("en") == "en" and i18n.tr("Annuler") == "Cancel" and i18n.tr("Texte inconnu du catalogue") == "Texte inconnu du catalogue"
        assert i18n.set_language("zz") == "fr" and i18n.tr("Annuler") == "Annuler"           # langue inconnue : français, sans erreur
    finally:
        i18n.set_language("fr")


def test_broken_or_missing_catalog_falls_back_to_french():
    old = i18n.LOCALE_DIR
    d = tempfile.mkdtemp()
    open(os.path.join(d, "en.json"), "w").write("{ pas du json")
    open(os.path.join(d, "de.json"), "w").write(json.dumps({"Annuler": "Abbrechen", "Vide": "", "Pas une chaîne": 3}))
    i18n.LOCALE_DIR = type(old)(d)
    try:
        assert i18n.set_language("en") == "fr" and i18n.tr("Annuler") == "Annuler"
        assert i18n.set_language("de") == "de" and i18n.tr("Annuler") == "Abbrechen" and i18n.tr("Vide") == "Vide" and i18n.tr("Pas une chaîne") == "Pas une chaîne"
    finally:
        i18n.LOCALE_DIR = old
        i18n.set_language("fr")


def test_english_runtime_behaviour_end_to_end():
    out = json.loads(run("""
import json, datetime, sys
sys.path.insert(0, 'tests')
import testenv
from mintmail import i18n
lang = i18n.init_from_config('auto')
from mintmail import tasks, slots, util
d = datetime.date(2026, 11, 10)
print(json.dumps({'lang': lang,
  'due': [tasks.due_label({'due': x}, d) for x in ('2026-11-09', '2026-11-10', '2026-11-11', '2026-11-12')],
  'slots': slots.proposal_text([(datetime.datetime(2026, 11, 12, 9, 0), datetime.datetime(2026, 11, 12, 10, 30))]),
  'size': util.human_size(3 * 1024 * 1024), 'sc': ['C', i18n.tr('Nouveau message')]}))
"""))
    assert out["lang"] == "en"
    assert out["due"] == ["1 d overdue", "today", "tomorrow", "in 1 d (11/11)"] or out["due"][:3] == ["1 d overdue", "today", "tomorrow"], out["due"]
    assert out["slots"].startswith("I suggest the following time slots:") and "Thursday 12 November, from 9:00 to 10:30" in out["slots"] and out["slots"].endswith("suits you."), out["slots"]
    assert out["size"].endswith("MB"), out["size"]
    assert out["sc"][1] == "New message", out["sc"]
    fr = json.loads(run("""
import json, datetime
from mintmail import i18n
i18n.init_from_config('auto')
from mintmail import tasks, slots
print(json.dumps({'due': tasks.due_label({'due': '2026-11-09'}, datetime.date(2026, 11, 10)),
  'slots': slots.proposal_text([(datetime.datetime(2026, 11, 12, 9, 0), datetime.datetime(2026, 11, 12, 10, 30))])}))
""", lang="fr"))
    assert fr["due"] == "en retard de 1 j" and fr["slots"].startswith("Je vous propose les créneaux suivants :") and "jeudi 12 novembre" in fr["slots"], fr


def test_command_line_is_translated():
    en = subprocess.run([sys.executable, "-m", "mintmail", "--help"], capture_output=True, text=True, cwd=ROOT, timeout=60,
                        env=dict(os.environ, MINTMAIL_LANG="en", PYTHONPATH=ROOT)).stdout
    fr = subprocess.run([sys.executable, "-m", "mintmail", "--help"], capture_output=True, text=True, cwd=ROOT, timeout=60,
                        env=dict(os.environ, MINTMAIL_LANG="fr", PYTHONPATH=ROOT)).stdout
    assert "options:" in en and "Starts the application." in en and "Shows this list of options." in en and "Lance l'application." not in en
    assert "options :" in fr and "Lance l'application." in fr


def test_pseudo_locale_every_string_changed_nothing_breaks():
    """Toutes les chaînes traduites deviennent « «…» » : l'interface simulée doit démarrer, se construire et s'exécuter sans erreur
    (détecte une logique qui dépendrait du texte français affiché)."""
    code = ("import sys, runpy, mintmail.i18n as i; i.tr = lambda s: '«%s»' % s; sys.path.insert(0, 'tests'); "
            "runpy.run_path('tests/i18n_smoke.py', run_name='__main__')")
    assert "SMOKE OK" in run(code, lang="fr")


def test_english_smoke_runs_with_the_real_catalog():
    assert "SMOKE OK" in run("import sys, runpy; sys.path.insert(0, 'tests'); runpy.run_path('tests/i18n_smoke.py', run_name='__main__')", lang="en")


def test_help_translation_is_complete_and_parallel():
    from mintmail import help_content as H
    d = json.load(open(os.path.join(LOCALE, "help_en.json"), encoding="utf-8"))
    assert [s["id"] for s in d["sections"]] == [s["id"] for s in H.SECTIONS]
    assert len(d["shortcuts"]) == len(H.SHORTCUTS_HELP) and len(d["cli"]) == len(H.CLI_OPTIONS)
    ph = lambda s: sorted(re.findall(r"\{\w+\}|@\w+@", s))
    for fr, en in zip(H.SECTIONS, d["sections"]):
        assert len(fr["items"]) == len(en["items"]), fr["id"]
        for (ft, fb), (et, eb) in zip(fr["items"], en["items"]):
            assert ph(ft + fb) == ph(et + eb), (fr["id"], ft)
            assert eb.count("• ") >= fb.count("• ") - 1, (fr["id"], ft, "puces manquantes")
    for (_, fd), (_, ed) in zip(H.CLI_OPTIONS, d["cli"]):
        assert ph(fd) == ph(ed)
    en_cat = catalogs()["en"]
    settings_src = open(os.path.join(PKG, "qt", "settings_window.py"), encoding="utf-8").read()
    titles = [t for t in re.findall(r'tabs\.addTab\([^\n]*?, (?:tr\()?"([^"]+)"\)', settings_src) if re.match(r"\w", t)]
    pages = next(i for s in d["sections"] if s["id"] == "look" for i in s["items"] if i[0] == "Settings pages")[1]
    for t in titles:
        assert en_cat[t] in pages, "page de paramètres absente de l'aide anglaise : %s" % en_cat[t]
    acc = re.compile(r"[àâçéèêëîïôûùüÿœ]")
    for s in d["sections"]:
        for t, b in s["items"]:
            if t == "Tasks and due dates":
                continue                                                              # cite volontairement des expressions françaises comprises par l'analyse
            assert not acc.search(t + b), (s["id"], t, acc.search(t + b).group())


def test_help_language_selection_and_search():
    out = json.loads(run("""
import json
from mintmail import i18n
i18n.init_from_config('auto')
from mintmail import help_content as H
ctx = {'version': '9.9', 'config': '~/c', 'data': '~/d', 'log': '~/l'}
print(json.dumps({'titles': [s['title'] for s in H.sections(ctx)][:2], 'oauth': len(H.search('oauth', ctx)), 'fr_word': len(H.search('désabonner', ctx)),
                  'unsub': len(H.search('unsubscribe', ctx)), 'version_filled': any('9.9' in t for s in H.sections(ctx) for t, b in s['items']),
                  'cli_filled': '~/d/diagnostic.txt' in H.full_text(ctx)}))
"""))
    assert out["titles"] == ["Getting started", "Read and organize"] and out["oauth"] >= 3 and out["unsub"] >= 2 and out["fr_word"] == 0
    assert out["version_filled"] and out["cli_filled"]
    de = json.loads(run("""
import json
from mintmail import i18n, help_content as H
i18n.init_from_config('auto')
print(json.dumps(H.sections({'version': '1', 'config': 'c', 'data': 'd', 'log': 'l'})[0]['title']))
""", lang="xx"))
    assert de == "Getting started"                                                     # langue inconnue : aide anglaise, pas française


def test_ui_language_setting_is_local_to_the_machine():
    from mintmail.store import DEFAULTS
    assert DEFAULTS["ui_lang"] == "auto"
    assert "ui_lang" not in open(os.path.join(PKG, "syncdata.py"), encoding="utf-8").read()


def test_wrapping_tool_finds_nothing_to_wrap_or_unwrap_and_no_identifier_is_translatable():
    tool = os.path.join(ROOT, "tools", "i18n_wrap.py")
    if not os.path.exists(tool):
        return
    r = subprocess.run([sys.executable, tool, "--check"], capture_output=True, text=True, cwd=ROOT, timeout=120)
    assert r.stdout.startswith("À ENVELOPPER : 0 | À RETIRER (enveloppées à tort) : 0"), r.stdout[:600]
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import importlib.util
    spec = importlib.util.spec_from_file_location("i18n_wrap", tool)
    w = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(w)
    words = w.load_words() | {v for vals in w.load_manual().values() for v in vals}      # mots d'interface choisis volontairement
    for s in code_msgids():
        assert not ((w.technical(s) or w.protocol_like(s)) and s.strip() not in words), "identifiant ou protocole traduisible : %r" % s


def test_settings_page_offers_the_language_choice():
    src = open(os.path.join(PKG, "qt", "settings_window.py"), encoding="utf-8").read() + open(os.path.join(PKG, "qt", "maintenance.py"), encoding="utf-8").read()
    assert "ui_lang" in src and "i18n.available()" in src and "redémarrez MintMail" in src and "MT.languages()" in src


# ======================================================================= langues livrées : néerlandais, allemand, espagnol
FRENCH_ONLY_CHARS = {"en": "àâçèêîôûùœ", "nl": "àâçèêîôûùœ", "de": "àâçèêîôûùœé", "es": "àâçèêîôûùœë"}
FRENCH_WORDS = re.compile(r"\b(vous|votre|vos|pour|avec|dans|cette|ces|sans|aucun|aucune|nouveau|nouvelle|boîte|dossier|message(s)? (?:non|envoy)|réglages|paramètres)\b", re.I)


def test_available_languages_are_exactly_the_shipped_catalogs():
    assert i18n.available() == ["fr", "de", "en", "es", "nl"], i18n.available()                    # pas de « help_en », pas de « de.status »
    for code in i18n.available():
        assert code in i18n.NAMES, code                                                           # chaque langue a son nom dans le sélecteur


def test_every_shipped_language_catalog_is_complete_valid_and_free_of_french():
    ids = code_msgids()
    cats = catalogs()
    assert set(cats) == {"en", "nl", "de", "es"}, set(cats)
    for lang, cat in cats.items():
        assert set(cat) == ids, (lang, sorted(ids - set(cat))[:5], sorted(set(cat) - ids)[:5])
        bad = [(k[:50], i18n.check_entry(k, v)) for k, v in cat.items() if i18n.check_entry(k, v)]
        assert not bad, (lang, bad[:4])
        leftovers = []
        for fr, tr_ in cat.items():
            plain = re.sub(r"<[^>]+>|%\([^)]*\)[sd]|%[sdr.\d]+s?|https?://\S+", " ", tr_)
            if any(ch in plain for ch in FRENCH_ONLY_CHARS[lang]) or FRENCH_WORDS.search(plain):
                leftovers.append((fr[:40], tr_[:70]))
        assert not leftovers, (lang, leftovers[:5])
        same = [k for k, v in cat.items() if k == v and len(re.sub(r"[^A-Za-zÀ-ÿ]", "", k)) > 10]
        assert len(same) <= 6, (lang, same[:10])                                                  # quasi rien ne doit rester identique au français (hors noms propres)


def test_translated_catalogs_declare_honestly_that_they_were_machine_translated_and_not_reviewed():
    for lang in ("nl", "de", "es"):
        st = json.load(open(os.path.join(LOCALE, lang + ".status.json"), encoding="utf-8"))
        assert st["machine_translated"] is True and st["complete"] is True and st["strings"] == st["of"] == len(code_msgids()), (lang, st)
        assert st["reviewed_by_human"] is False or (st["reviewed_by_human"] is True and str(st.get("reviewed_by", "")).strip() and st.get("reviewed_on")), (lang, st)   # « relue » exige un nom et une date


def test_each_new_language_works_end_to_end_with_native_dates_tasks_and_a_clean_ui_start():
    expected = {"nl": ("Ik stel de volgende tijdsloten voor:", "donderdag 12 november", "vandaag", "morgen", "1 d te laat"),
                "de": ("Ich schlage die folgenden Zeitfenster vor:", "Donnerstag 12 November", "heute", "morgen", "1 T. überfällig"),
                "es": ("Te propongo las siguientes franjas horarias:", "jueves 12 de noviembre", "hoy", "mañana", "1 d de retraso")}
    code = """
import json, datetime, sys
sys.path.insert(0, 'tests')
import testenv
from mintmail import i18n
lang = i18n.init_from_config('auto')
from mintmail import slots, tasks
d = datetime.date(2026, 11, 10)
print(json.dumps({'lang': lang, 'slots': slots.proposal_text([(datetime.datetime(2026, 11, 12, 9, 0), datetime.datetime(2026, 11, 12, 10, 30))]),
                  'due': [tasks.due_label({'due': x}, d) for x in ('2026-11-09', '2026-11-10', '2026-11-11')]}))
"""
    for lang, (intro, day, today, tomorrow, late) in expected.items():
        out = json.loads(run(code, lang=lang))
        assert out["lang"] == lang and out["slots"].startswith(intro) and day in out["slots"], out
        assert out["due"] == [late, today, tomorrow], out["due"]
        assert "SMOKE OK" in run("import sys, runpy; sys.path.insert(0, 'tests'); runpy.run_path('tests/i18n_smoke.py', run_name='__main__')", lang=lang), lang
        cli = subprocess.run([sys.executable, "-m", "mintmail", "--help"], capture_output=True, text=True, cwd=ROOT, timeout=60, env=dict(os.environ, MINTMAIL_LANG=lang, PYTHONPATH=ROOT)).stdout
        assert "Starts the application." in cli, lang                                                 # l'aide en ligne de commande retombe sur l'anglais (pas de traduction dédiée)


def test_languages_without_dedicated_help_get_the_english_help_not_the_french_one():
    for lang in ("nl", "de", "es"):
        title = json.loads(run("""
import json
from mintmail import i18n, help_content as H
i18n.init_from_config('auto')
print(json.dumps(H.sections({'version': '1', 'config': 'c', 'data': 'd', 'log': 'l'})[0]['title']))
""", lang=lang))
        assert title == "Getting started", (lang, title)


def test_the_french_german_style_slip_is_fixed_recipients_are_addressed_consistently():
    de = catalogs()["de"]
    assert de["\nDites-moi celui qui vous convient."] == "\nSagen Sie mir bitte, welcher Ihnen passt."    # message adressé à un tiers : vouvoiement cohérent avec le reste de l'interface allemande
