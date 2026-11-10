"""L'aide intégrée doit rester complète et alignée sur le code : raccourcis, options, pages de paramètres, fonctions."""
import os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gtkstub   # noqa: F401
from mintmail import help_content as H
from mintmail import settings as S

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CTX = {"version": "9.9.9", "config": "/c", "data": "/d", "log": "/d/mintmail.log"}


def src(name):
    return open(os.path.join(ROOT, "mintmail", name), encoding="utf-8").read()


def test_structure_and_placeholders():
    secs = H.sections(CTX)
    assert len(secs) >= 12 and len({s["id"] for s in secs}) == len(secs) and len({s["title"] for s in secs}) == len(secs)
    text = H.full_text(CTX)
    assert len(text) > 20000 and sum(len(s["items"]) for s in secs) >= 55
    assert all(t.strip() and b.strip() for s in secs for t, b in s["items"])
    assert not re.search(r"\{(version|config|data|log)\}|@SHORTCUTS@|@CLI@", text)          # espaces réservés tous remplacés
    assert "9.9.9" in text and "/d/mintmail.log" in text and "/c/config.json" in text
    assert "au survol" not in text and "pas chiffrées" not in text                              # fonctions retirées : jamais citées


def test_shortcuts_match_the_app_and_the_settings_page():
    assert dict(H.SHORTCUTS_HELP) == dict(S.SHORTCUTS)                                          # même liste qu'à l'écran « Raccourcis »
    win = src("window.py")
    acts = re.search(r"acts = \{(.*?)\n        \}", win, re.S).group(1)
    names = set(re.findall(r'"([A-Za-z]+)": lambda', acts))
    show = {"numbersign": "#", "Delete": "Suppr", "slash": "/", "exclam": "!", "backslash": "\\"}
    keys = " ".join(k.upper() for k, _ in H.SHORTCUTS_HELP)
    for n in names:
        shown = show.get(n, n.upper())
        assert shown.upper() in keys, "touche non documentée : %s" % n
    for mod in ("F1", "F11", "CTRL+K", "CTRL+J", "CTRL+F", "CTRL+R", "CTRL+N", "CTRL+,"):
        assert mod in keys, mod


def test_every_command_line_option_is_documented():
    entry = src("entry.py")
    opts = set(re.findall(r'"(--[a-z-]+)" in argv', entry))
    opts |= {"--help", "--version", "--yes"}
    cli = H.cli_text(CTX)
    assert len(opts) >= 8
    for o in opts:
        assert o in cli, "option non documentée : %s" % o
    assert "mailto:" in cli


def test_every_settings_page_is_described():
    pages = re.findall(r'add_titled\([^\n]*?"(\w+)", (?:tr\()?"([^"]+)"\)', src("settings.py"))
    assert len(pages) >= 12
    text = H.full_text(CTX).lower()
    for ident, title in pages:
        clean = re.sub(r"^[^\w]+", "", title).lower()
        assert clean in text, "page de paramètres non décrite : %s" % title


def test_all_features_of_the_current_release_are_findable():
    needed = ["conversation", "oauth", "chercher aussi sur le serveur", "ollama", "habitudes de rangement", "miniature", "hors ligne",
              "vcard", "invitation", "caldav", "alias", "send-due", "rfc 8058", "glisser", "boite d'envoi", "f1", "classer", "creer un dossier",
              "clic droit", "assistant", "hameconnage", "pairs fixes", "diagnostic", "mot de passe d'application", "reporter", "signature",
              "modele", "regle", "bloquer", "domaine", "palette", "swipe", "idle", "trousseau", "tout enregistrer", "--reset", "--diagnose",
              "icone", "mintmail-outbox", "identite", "contacts", "langue", "confidentialite", "journal",
              "aujourd'hui", "taches", "echeance", "proposer des creneaux", "brouillons de reponse", "[a completer", "signaler une faille", "contact@saec.me", "liste blanche", "0600", "security.md", "google agenda", "calendar.events", "google calendar api", "nouvel evenement", "libre sur ce creneau", "expirer", "7 jours"]
    for term in needed:
        assert H.search(term, CTX), "introuvable dans l'aide : %s" % term


def test_search_is_accent_and_case_insensitive_and_multiword():
    assert H.search("DÉSABONNER", CTX) and H.search("desabonner", CTX)
    assert H.search("   ", CTX) == []
    hits = H.search("ollama detecter", CTX)
    assert hits and all("ollama" in (t + b).lower() for _s, t, b in hits)
    assert H.search("zzzzintrouvablezzzz", CTX) == []
