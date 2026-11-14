"""Interface Qt, partie sans Qt : tâches, relances, désabonnement, pièces jointes, synchro P2P (réglages), IA partout (tri, pastilles,
brouillons préparés, recherche, clic droit)."""
import os, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mintmail.models import Message
from mintmail.store import Cache, Config
from mintmail.qt import aiwork as AW, organizer as O, syncing as SY


def env():
    d = tempfile.mkdtemp()
    cfg, cache = Config(os.path.join(d, "c.json")), Cache(os.path.join(d, "c.db"))
    m = Message(id="a:1", account="a", folder="inbox", uid=1, sender_name="Bob", sender_email="bob@x.be", subject="Devis", date=time.time(), text="Bonjour", html="", unread=True)
    cache.upsert(m)
    return d, cfg, cache, m


def test_tasks_and_followups():
    _d, cfg, cache, m = env()
    task, note = O.task_add_from_form(cfg, "Appeler Bob", "demain", m)
    assert task["text"] == "Appeler Bob" and task["msg"] == "a:1" and not task["done"] and "échéance" in note
    assert O.tasks_all(cfg)[0]["id"] == task["id"]
    assert "3 jours" in O.add_followup(cfg, m, 3)
    assert O.due_followups(cfg, cache) == []                         # pas encore échu


def test_unsubscribe_plans_are_safe():
    m = Message(id="x", account="a", folder="inbox", uid=1, sender_name="News", sender_email="n@x.be", subject="s", date=0)
    assert O.unsubscribe_plan(m)["kind"] == "none"
    m.unsubscribe = "<mailto:stop@x.be?subject=unsub>, <https://x.be/u?id=1>"
    assert O.unsubscribe_plan(m)["kind"] == "mailto"
    m.unsubscribe = "<https://x.be/u?id=1>"
    assert O.unsubscribe_plan(m)["kind"] == "web"
    m.unsub_post = True
    assert O.unsubscribe_plan(m)["kind"] == "oneclick"
    m.unsubscribe, m.unsub_post = "<mailto:a@x.be,b@x.be>", False
    assert O.unsubscribe_plan(m)["kind"] in ("refused", "none")      # adresses multiples : jamais envoyées


def test_attachment_open_plan_blocks_programs_and_warns_on_macros():
    assert O.open_plan({"filename": "setup.exe", "size": 10})[0] == "block"
    assert O.open_plan({"filename": "budget.xlsm", "size": 10})[0] == "warn"
    assert O.open_plan({"filename": "photo.png", "size": 10})[0] == "preview_image"
    assert O.open_plan({"filename": "notes.txt", "size": 10})[0] == "preview_text"
    assert O.open_plan({"filename": "doc.pdf", "size": 10})[0] == "open"


def test_p2p_peers_and_settings():
    _d, cfg, _c, _m = env()
    assert SY.parse_peers("1.2.3.4:5000, pc.local  1.2.3.4:5000 5.6.7.8:99999 a/b") == ["1.2.3.4:5000", "pc.local"]
    enabled, note = SY.apply_settings(cfg, "x", True)
    assert enabled is False and note                                # code trop court : la synchro reste coupée


def test_ai_everywhere_pure_parts():
    _d, cfg, cache, m = env()
    infos = [{}]
    AW.decorate(infos, [m], {"a:1": {"summary": " Devis à valider ", "priority": 3, "spam": False}})
    assert infos[0] == {"ai": "Devis à valider", "prio": 3, "spam": False}
    assert AW.is_ai_query("? factures de mars") and AW.is_ai_query("✨ x") and not AW.is_ai_query("factures")
    assert AW.ai_query_text("✨ ? factures") == "factures"
    res = {"a:1": {"reply_needed": True, "priority": 3, "category": "people"}}
    assert AW.prepare_candidates(cfg, cache, [m], res) == []         # réglage coupé par défaut : jamais de brouillon sans accord
    cfg["ai_prepare_drafts"] = True
    assert AW.prepare_candidates(cfg, cache, [m], res) == [m]
    assert AW.prepare_candidates(cfg, cache, [m], {"a:1": dict(res["a:1"], local=True)}) == []     # tri local : on attend l'IA
    assert AW.urgent([m], {"a:1": {"priority": 3}}) == [m] and AW.urgent([m], {"a:1": {"priority": 3, "local": True}}) == []
    assert AW.add_rule_move(cfg, m, "Devis") and not AW.add_rule_move(cfg, m, "Devis")
    assert AW.reply_idea("ai_reply:1") == AW.REPLY_IDEAS[1][1]


def test_ai_context_menu_without_and_with_ai():
    _d, cfg, cache, m = env()

    class Eng:
        def accounts(self):
            return []
    e = Eng()
    e.config, e.cache = cfg, cache
    assert AW.context_items(e, m)[0][0] == "ai_enable"               # IA non configurée : on propose de l'activer
    from mintmail.qt import assistant as AS
    cfg["ai_enabled"] = True
    AS.ai_engine(e).enabled = lambda: True
    keys = [it[0] for it in AW.context_items(e, m) if it and it[0] != "sub"]
    for k in ("ai_suggest", "ai_classify_sender", "ai_classify_inbox", "summarize", "translate", "ai_about"):
        assert k in keys, k
    sub = next(it for it in AW.context_items(e, m) if it and it[0] == "sub")
    assert len(sub[2]) == len(AW.REPLY_IDEAS)


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
    print("ok")
