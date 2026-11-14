"""Aide refondue : mise en forme (touches, gras, commandes, liens sûrs, surlignage), données FR/EN parallèles, les pages rendues (Qt) sont testées dans test_qt_viewmodel."""
import json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import testenv  # noqa: F401
from mintmail import help_content as H, help_format as F, i18n

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CTX = {"version": "9.9.9", "config": "~/c", "data": "~/d", "log": "~/l"}


def with_lang(lang, fn):
    old = i18n.current()
    i18n.set_language(lang)
    try:
        return fn()
    finally:
        i18n.set_language(old)


def test_blocks_recognise_bullets_steps_tips_warnings_and_commands():
    got = F.blocks("Intro.\n• Puce un\n  • Puce deux\n1. Première étape\n2) Seconde\nAstuce : une astuce\nTip: english tip\nAttention : danger\nWarning: careful\nmintmail --reset\nsudo apt install python3-gi\n\nTexte normal avec mintmail --version au milieu")
    assert got == [("p", "Intro."), ("bullet", "Puce un"), ("bullet", "Puce deux"),
                   ("step", "1|Première étape"), ("step", "2|Seconde"), ("tip", "une astuce"), ("tip", "english tip"), ("warn", "danger"), ("warn", "careful"),
                   ("code", "mintmail --reset"), ("code", "sudo apt install python3-gi"), ("p", "Texte normal avec mintmail --version au milieu")]
    assert F.blocks("") == [] and F.blocks(None) == []
    assert F.blocks("x" * 400)[0][0] == "p" and F.blocks("mintmail " + "x" * 300)[0][0] == "p"                 # une très longue ligne n'est pas prise pour une commande


def test_markup_turns_keys_screen_names_commands_and_links_into_safe_pango_markup():
    m = F.markup("Appuyez sur Ctrl+K, (S), (touche T) ou F1 ; ouvrez « Paramètres → IA » ; lancez mintmail --check-update ; voir https://saec.me/x.")
    assert m.count("font_family='monospace'") == 4 and ">  Ctrl+K </span>".replace("  ", " ") in m and "> S </span>" in m and "> T </span>" in m and "> F1 </span>" in m
    assert "<b>« Paramètres → IA »</b>" in m and "<tt><b>mintmail --check-update</b></tt>" in m
    assert '<a href="https://saec.me/x">https://saec.me/x</a>.' in m                                         # le point final reste hors du lien
    hostile = F.markup("<script>alert(1)</script> & <b>gras</b> javascript:alert(1) http://a.be/x?y=1&z=2")
    assert "<script>" not in hostile and "&lt;script&gt;" in hostile and "&amp;" in hostile and "<b>gras</b>" not in hostile
    assert 'href="http://a.be/x?y=1&amp;z=2"' in hostile and 'href="javascript' not in hostile                  # seuls http(s) deviennent des liens, tout est échappé
    assert F.markup("Ctrl+, et Ctrl+Maj+,").count("monospace") == 2 and "> Échap </span>" in F.markup("Échap annule")
    assert F.markup("") == "" and F.markup("rien de spécial") == "rien de spécial"
    assert F.markup("la touche T ouvre") .count("monospace") == 1 and F.markup("Tab et Entrée").count("monospace") == 2


def test_highlight_is_accent_and_case_insensitive_escapes_everything_and_merges_overlaps():
    h = F.highlight("Résumé des mails : OAuth & <spam>", "RESUME oauth")
    assert h.count("<span bgcolor") == 2 and ">Résumé</span>" in h and ">OAuth</span>" in h and "&amp;" in h and "&lt;spam&gt;" in h
    assert F.highlight("abc abcd", "abc abcd").count("<span bgcolor") == 2
    assert F.highlight("aaaa", "aa a").count("<span bgcolor") == 1                                              # chevauchements fusionnés
    assert F.highlight("Texte <b>", "") == "Texte &lt;b&gt;" and F.highlight("Texte", "zzz") == "Texte"
    assert F.highlight("e\u0301t\u00e9", "ete") == "e\u0301t\u00e9".replace("&", "&amp;")                       # texte décomposé : repli sûr sans balise


def test_excerpt_centres_on_the_first_match_and_cuts_on_word_boundaries():
    long_text = "mot " * 120 + "OAuth fin " + "mot " * 120
    ex = F.excerpt(long_text, "oauth", 90)
    assert "OAuth" in ex and ex.startswith("… ") and ex.endswith(" …") and len(ex) < 130 and not ex.startswith("… ot")
    assert F.excerpt("court texte", "x", 90) == "court texte"
    assert F.excerpt("a " * 200, "zzz", 60).endswith(" …") and not F.excerpt("a " * 200, "zzz", 60).startswith("…")
    assert F.plain("Intro\n• un\n1. deux\nAstuce : trois") == "Intro · un · deux · trois"


def test_tip_of_the_day_is_stable_within_a_day_and_scrolls_with_the_button():
    tips = ["a", "b", "c"]
    assert F.tip_of_the_day(tips, 10) == F.tip_of_the_day(tips, 10) == (1, "b")
    assert [F.tip_of_the_day(tips, 10, k)[1] for k in range(4)] == ["b", "c", "a", "b"] and F.tip_of_the_day([], 5) == (0, "")


def test_help_data_french_and_english_are_parallel_and_complete():
    d = json.load(open(os.path.join(ROOT, "mintmail", "locale", "help_en.json"), encoding="utf-8"))
    ids = [s["id"] for s in H.SECTIONS]
    assert set(H.SECTION_META) == set(ids) == set(d["meta"]) and all(H.SECTION_META[i][0] and H.SECTION_META[i][1].endswith(".") for i in ids)
    assert all(d["meta"][i][0] == H.SECTION_META[i][0] and d["meta"][i][1].endswith(".") for i in ids)           # mêmes icônes, accroches terminées
    assert len(d["home"]["steps"]) == len(H.HOME["steps"]) == 4 and len(d["home"]["tips"]) == len(H.HOME["tips"]) >= 12
    assert all(s[2] in ids for s in H.HOME["steps"]) and [s[2] for s in d["home"]["steps"]] == [s[2] for s in H.HOME["steps"]]
    assert set(d["callouts"]) == {"%s:%d" % k for k in H.CALLOUTS}
    for (sid, n), text in H.CALLOUTS.items():
        assert n < len(next(s for s in H.SECTIONS if s["id"] == sid)["items"]) and text.startswith("Astuce :") and d["callouts"]["%s:%d" % (sid, n)].startswith("Tip:")
    acc = re.compile(r"[àâçéèêëîïôûùüÿœ]")
    for blob in [m[1] for m in d["meta"].values()] + list(d["home"]["welcome"]) + [x for s in d["home"]["steps"] for x in s[:2]] + d["home"]["tips"] + list(d["callouts"].values()):
        assert not acc.search(blob), blob                                                                       # l'anglais ne contient pas de français
    for tip in H.HOME["tips"] + d["home"]["tips"]:
        assert 20 < len(tip) < 170, tip                                                                          # une phrase, pas un paragraphe


def test_every_shortcut_and_command_quoted_in_tips_and_steps_really_exists():
    keys = " ".join(k for k, _ in H.SHORTCUTS_HELP)
    for k in ("Ctrl+K", "Ctrl+J", "Ctrl+A", "F1"):
        assert k in keys, k
    for single in ("T", "H", "X", "P", "S", "E", "\\", "?"):
        assert re.search(r"(^|\s)%s(\s|$)" % re.escape(single), keys) or single in keys, single
    text = " ".join(H.HOME["tips"])
    assert "--check-update" in text and any("--check-update" in c for c, _ in H.CLI_OPTIONS)                   # la commande citée existe


def test_sections_carry_icon_tagline_kinds_and_the_callouts_in_both_languages():
    secs = H.sections(CTX)
    assert len(secs) == 15 and all(s["icon"] and s["tagline"] and len(s["kinds"]) == len(s["items"]) for s in secs)
    assert [s["kinds"].count("shortcuts") for s in secs if s["id"] == "context"] == [1] and [s["kinds"].count("cli") for s in secs if s["id"] == "cli"] == [1]
    start = next(s for s in secs if s["id"] == "start")
    assert start["items"][3][1].rstrip().endswith("n'importe quelle action.") and "\nAstuce : Ctrl+K" in start["items"][3][1]
    en = with_lang("en", lambda: H.sections(CTX))
    assert "\nTip: Ctrl+K opens the command palette" in en[0]["items"][3][1] and en[0]["tagline"].startswith("Add your account")
    assert with_lang("de", lambda: H.meta()["ai"]["tagline"]).startswith("Summaries, assistant")                 # langue sans aide dédiée : anglais
    assert with_lang("de", lambda: H.home()["welcome"][0]) == "Welcome to MintMail"                           # langue sans aide dédiée : anglais
    assert H.home()["welcome"][0] == "Bienvenue dans MintMail" and len(H.shortcuts()) == len(H.SHORTCUTS_HELP) and H.cli_options(CTX)[1][0] == "mintmail --help"
    assert [h["sid"] for h in H.search_full("oauth", CTX)][:1] == ["start"] and H.search("oauth", CTX)[0][1] == H.search_full("oauth", CTX)[0]["title"]
