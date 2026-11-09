"""Classement IA, création de dossiers, menu clic droit IA, règles « ranger dans un dossier » (logique de la fenêtre, GTK simulé)."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gtkstub
from test_listing import make_window
from mintmail.ai_engine import AIEngine
from mintmail.ai_service import AIService
from mintmail.backend import DemoBackend
from mintmail.folders import dest_of

ORIG = AIService.call


class FakeAssistant:
    def __init__(self): self.log, self.plan = [], None
    def add_ai(self, t): self.log.append(("ai", t))
    def add_user(self, t): self.log.append(("user", t))
    def set_busy(self, b): pass
    def add_plan(self, items, run_all): self.plan = (items, run_all)
    entry = gtkstub.D()
    def focus_entry(self): pass


def setup(n=40, responder=None):
    w = make_window(n)
    w.config.data.update(ai_enabled=True, ai_has_key=True)
    w.config.set_password("ai:nvidia", "nvapi-test")
    w.engine = AIEngine(w.config, w.cache)
    be = DemoBackend({"id": "demo", "email": "d@x", "name": "Démo"})
    w.accounts = lambda: [{"id": "demo", "name": "Démo", "email": "d@x", "demo": True}]
    w.backend = lambda aid: be
    w.folder_tree = {"demo": be.list_folders()}
    w.folder_unread, w._folder_badges = {}, {}
    w._rebuild_nav_dynamic = lambda: None
    w.refresh_folder_counts = lambda: None
    w._default_account = lambda msg=None: "demo"
    w.assistant, w.toggle_assistant = FakeAssistant(), lambda show=None: None
    w.show_settings = lambda page=None, window=False: w.__dict__.setdefault("opened", []).append(page)

    def run_bg(fn, done=None):
        try:
            res, err = fn(), None
        except Exception as e:
            res, err = None, e
        if done:
            done(res, err)
    w.run_bg = run_bg
    if responder:
        AIService.call = lambda self, messages, max_tokens=400, temperature=0.6: responder(messages)
    return w, be


def teardown():
    AIService.call = ORIG


def test_classify_creates_missing_folders_only_after_validation_and_moves():
    sent = []

    def responder(messages):
        sent.append(messages)
        return json.dumps([{"i": 0, "folder": "Factures"}, {"i": 1, "folder": "factures"}, {"i": 2, "folder": "Contrats/Légaux"},
                           {"i": 3, "folder": "Clients › Alpha"}, {"i": 4, "folder": ""}])
    w, be = setup(responder=responder)
    try:
        msgs = w.cache.query("inbox", limit=5)
        before = [f["name"] for f in be.list_folders()]
        w.ai_classify(msgs)
        items, run_all = w.assistant.plan
        assert [f["name"] for f in be.list_folders()] == before            # PROPOSITION seulement : rien créé, rien déplacé
        assert all(m.folder == "inbox" for m in w.cache.query("inbox", limit=5))
        labels = [d for d, _ in items]
        assert any("Factures" in l and "nouveau" not in l and l.startswith("2 message") for l in labels), labels   # « Factures » existe déjà (casse ignorée)
        assert any("Contrats Légaux" in l for l in labels) and any("Clients › Alpha" in l and "nouveau" not in l for l in labels)
        run_all()                                                           # l'utilisateur valide tout
        names = [f["name"] for f in be.list_folders()]
        assert "Contrats Légaux" in names                                    # créé maintenant, après validation
        moved = w.cache.query("f:Factures", limit=10)
        assert len(moved) == 2 and w.cache.query("f:Clients/Alpha", limit=10)
        assert any("INBOX" == e["name"] for e in w.tree_of("demo"))
    finally:
        teardown()


def test_exec_actions_create_folder_and_move_to_new_folder():
    w, be = setup(responder=lambda m: "[]")
    try:
        w.exec_action({"type": "create_folder", "name": "Projets perso", "parent": ""})
        assert "Projets perso" in [f["name"] for f in be.list_folders()]
        msgs = w.cache.query("inbox", limit=3)
        w.exec_action({"type": "move", "query": "", "folder": "Archives 2026"}, msgs)       # dossier inexistant : créé puis rempli
        assert "Archives 2026" in [f["name"] for f in be.list_folders()]
        assert len(w.cache.query("f:Archives 2026", limit=10)) == 3
        w.exec_action({"type": "create_folder", "name": "Sous", "parent": "Clients"})        # sous-dossier d'un dossier existant
        assert "Clients/Sous" in [f["name"] for f in be.list_folders()]
    finally:
        teardown()


def test_context_menu_ai_items():
    w, be = setup(responder=lambda m: "[]")
    try:
        m = w.cache.query("inbox", limit=1)[0]
        labels = lambda items: [i[0] if i[0] != "sous-menu" else i[1] for i in items if i]
        items = w.ai_menu_items(m)
        lab = labels(items)
        assert "✨ Suggérer un dossier…" in lab and any(l.startswith("✨ Classer tous les messages de ") for l in lab)
        assert "✨ Répondre avec l'IA" in lab and "✨ Résumer / analyser ce message" in lab and "✨ Traduire ce message" in lab
        sub = next(i for i in items if i and i[0] == "sous-menu")
        assert [x[0] for x in sub[2]][:3] == ["Réponse adaptée", "Accepter", "Refuser poliment"]
        # avec une suggestion mise en cache : « Ranger dans » + règle automatique
        w.cache.ai_set(m.id, "analysis", {"folder": "Contrats 2026", "event": {"title": "Réunion équipe", "start": "2026-11-12T14:00", "end": "", "location": ""}})
        lab = labels(w.ai_menu_items(m))
        assert "✨ Ranger dans « Contrats 2026 » (suggéré)" in lab and any(l.startswith("✨ Toujours ranger") for l in lab)
        assert any(l.startswith("✨ Ajouter à l'agenda") for l in lab)
        next(i for i in w.ai_menu_items(m) if i and i[0].startswith("✨ Ranger dans"))[1]()   # clic : crée le dossier et y range
        assert "Contrats 2026" in [f["name"] for f in be.list_folders()] and w.cache.get_light(m.id).folder == "f:Contrats 2026"
        # IA désactivée : une seule entrée, qui mène aux réglages
        w.config["ai_enabled"] = False
        items = w.ai_menu_items(m)
        assert len(items) == 1 and "Activer l'IA" in items[0][0]
        items[0][1]()
        assert w.opened[-1] == "ai"
    finally:
        teardown()


def test_rule_move_files_new_messages_in_folder_and_syncs():
    w, be = setup(responder=lambda m: "[]")
    try:
        m = w.cache.query("inbox", limit=1)[0]
        w.ai_file_message(m, "Factures")                                 # crée le dossier
        m2 = w.cache.query("inbox", limit=2)[0]
        w.ai_rule_move(m2, "Factures")
        assert {"field": "from", "text": m2.sender_email.lower(), "action": "move", "folder": "Factures"} in w.config["rules"]
        same = [x for x in w.cache.query("inbox", limit=50) if x.sender_email == m2.sender_email]
        left = w._auto_route(same)
        assert not left and all(w.cache.get_light(x.id).folder == "f:Factures" for x in same)     # la règle range les messages
        from mintmail import syncdata
        r = w.config["rules"][-1]
        assert syncdata.valid_item("rule:" + syncdata.hash_value(r), {"v": r, "ts": 1.0, "del": False})
        assert not syncdata.valid_item("rule:x", {"v": dict(r, folder=""), "ts": 1.0, "del": False})   # « ranger » sans dossier : refusé
    finally:
        teardown()
