"""Tâches, page « Aujourd'hui », créneaux libres, brouillons de réponse préparés."""
import datetime, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gtkstub
from test_modules import Server
from test_features2 import real_msg, win_with, FakeBackend
from test_gcal import google, with_google
from mintmail import extras, gcal, listing, oauth, slots, syncdata, tasks
from mintmail.ai_engine import AIEngine
from mintmail.store import Cache, Config


def test_tasks_crud_dedup_due_and_message_tasks():
    w, be = win_with(n=301)
    m = real_msg(1, "Devis")
    w.cache.upsert_many([m])
    t = w.task_add("Envoyer le devis avant vendredi", m)
    assert t and t["due"] == tasks.parse_due("avant vendredi").isoformat() and t["msg"] == "r1" and not t["done"]
    assert w.task_add("Envoyer le devis avant vendredi", m) is None                        # même tâche, même message : pas de doublon
    assert w.task_add("Envoyer le devis avant vendredi") is not None                        # sans message : tâche distincte
    assert w.task_add("   ") is None and w.task_add("x" * 500)["text"] == "x" * 300
    assert w.task_add("Sans date")["due"] == "" and w.task_add("Appeler", due=datetime.date(2026, 12, 1))["due"] == "2026-12-01"
    w.task_set_done(t["id"])
    assert [x for x in w.tasks_all() if x["id"] == t["id"]][0]["done"] is True
    w.task_remove(t["id"])
    assert all(x["id"] != t["id"] for x in w.tasks_all())
    w.cache.ai_set("r1", "analysis", {"tasks": ["Relire le contrat demain", "Préparer la facture", "Relire le contrat demain"]})
    added = w.tasks_from_message(m)
    assert [a["text"] for a in added] == ["Relire le contrat demain", "Préparer la facture"]            # la répétition est ignorée
    assert w.tasks_from_message(m) == []                                                    # 2e clic : rien de nouveau
    assert any("déjà dans votre liste" in x[0] for x in w.toasts)


def test_tasks_sync_between_machines_with_strict_validation():
    w, be = win_with(n=302)
    t = w.task_add("Envoyer le devis demain", real_msg(1, "Devis"))
    wire = syncdata.to_wire(syncdata.local_items(w.config))
    assert syncdata.valid_item("task:" + t["id"], wire["task:" + t["id"]])
    other = Config(os.path.join(gtkstub.tmp, "tasks-other.json"))
    res = syncdata.apply_items(other, syncdata.merge_items({}, wire), None)
    assert other["tasks"][0]["text"] == "Envoyer le devis demain" and "tâche(s)" in syncdata.describe(res)
    w.task_set_done(t["id"])                                                                 # cochée sur la machine A…
    time.sleep(0.01)
    wire2 = syncdata.to_wire(syncdata.local_items(w.config))
    local_other = syncdata.local_items(other)
    wins = syncdata.merge_items(local_other, wire2)
    syncdata.apply_items(other, wins, None)
    assert other["tasks"][0]["done"] is True                                                 # …et sur la machine B
    w.task_remove(t["id"])
    wire3 = syncdata.to_wire(syncdata.local_items(w.config))
    syncdata.apply_items(other, syncdata.merge_items(syncdata.local_items(other), wire3), None)
    assert other["tasks"] == []                                                              # suppression propagée
    bad = dict(wire["task:" + t["id"]])
    for mutation in ({"text": ""}, {"text": "x" * 301}, {"due": "demain"}, {"done": "oui"}, {"id": "autre"}, {"account": "x" * 41}):
        assert not syncdata.valid_item("task:" + t["id"], dict(bad, v=dict(bad["v"], **mutation))), mutation
    assert not syncdata.valid_item("task:../x", {"v": {"id": "../x", "text": "t"}, "ts": 1.0, "del": False})
    assert syncdata.SYNC_SETTINGS["ai_prepare_drafts"](True) and not syncdata.SYNC_SETTINGS["ai_prepare_drafts"]("oui")


def test_today_page_collects_priorities_followups_tasks_and_prepared_drafts():
    w, be = win_with(n=303)
    now = time.time()
    msgs = [real_msg(1, "Urgent client", date=now - 100), real_msg(2, "Newsletter", date=now - 200), real_msg(3, "Déjà lu", date=now - 300, unread=False),
            real_msg(4, "Suspect", date=now - 400)]
    w.cache.upsert_many(msgs)
    w.cache.ai_set("r1", "triage", {"priority": 3, "spam": False})
    w.cache.ai_set("r2", "triage", {"priority": 1, "spam": False})
    w.cache.ai_set("r3", "triage", {"priority": 3, "spam": False})
    w.cache.ai_set("r4", "triage", {"priority": 3, "spam": True})
    w.config["followups"] = [{"id": "x", "at": now + 86400 * 2, "subject": "Proposition", "date": now, "to": "p@y.be"},
                             {"id": "y", "at": now - 10, "subject": "Contrat", "date": now, "to": "q@y.be"}]
    w.task_add("Rappeler Marie demain")
    done = w.task_add("Déjà fait")
    w.task_set_done(done["id"])
    draft = real_msg(9, "Re: Urgent client", folder="drafts")
    draft.id = "draft-ai-abc123"
    other = real_msg(8, "Brouillon manuel", folder="drafts")
    w.cache.upsert_many([draft, other])
    d = w.today_local()
    assert [m.id for m in d["important"]] == ["r1"]                                          # non lu + priorité 3 + pas spam
    assert [f["id"] for f in d["followups"]] == ["y", "x"] and [t["text"] for t in d["tasks"]] == ["Rappeler Marie demain"]
    assert [m.id for m in d["drafts"]] == ["draft-ai-abc123"]                                # seuls les brouillons préparés par l'IA
    for agenda in (None, (False, "autorisation de l'agenda manquante"), (True, []),
                   (True, [{"title": "Réunion", "start": datetime.datetime(2026, 11, 9, 9, 0), "end": datetime.datetime(2026, 11, 9, 10, 0),
                            "all_day": False, "location": "Salle A", "busy": True}])):
        w._today_dialog(agenda)                                                              # construit sans erreur dans tous les cas


def test_slot_proposal_opens_a_reply_with_free_slots_only():
    w, be = win_with(n=304)
    srv = google({})
    orig_api, gcal.API = gcal.API, srv.url + "/calendar/v3"
    orig_mgr = with_google(w)
    try:
        replies, shown = [], []
        w.reply = lambda m, all_=False, ai_text="": replies.append(ai_text)
        orig_text = slots.proposal_text
        slots.proposal_text = lambda found: (shown.append(found), orig_text(found))[1]
        w.propose_slots(real_msg(1, "Rendez-vous ?"), 60)
        assert replies and replies[0].startswith("Je vous propose les créneaux suivants :") and len(shown[0]) == 3
        assert len({s.date() for s, e in shown[0]}) == 3 and all(s.weekday() < 5 and datetime.time(9) <= s.time() and e.time() <= datetime.time(17, 30) for s, e in shown[0])
        w.propose_slots(real_msg(1, "Rendez-vous ?"), 90)
        assert all((e - s) == datetime.timedelta(minutes=90) for s, e in shown[1])
        w.config["gcal"] = {}
        n = len(replies)
        w.show_settings = lambda page=None, window=False: w.__dict__.setdefault("opened", []).append(page)
        w.propose_slots(real_msg(1, "Rendez-vous ?"), 60)                                    # Google Agenda inactif : pas de faux créneaux
        assert len(replies) == n and w.opened[-1] == "calendar"
        slots.proposal_text = orig_text
    finally:
        gcal.API = orig_api
        oauth.manager_for = orig_mgr
        srv.close()


def test_context_menu_offers_tasks_and_slots_only_when_relevant():
    labels = []
    orig = listing.Gtk.MenuItem
    listing.Gtk.MenuItem = lambda label=None, **k: (labels.append(label), gtkstub.D())[1]
    try:
        from test_listing import make_window, _click_env
        w = make_window(10)
        w.reload_list(full=True)
        w.ai_menu_items = lambda m: []
        w.build_snooze_menu = lambda cb=None: gtkstub.D()
        w.build_move_menu = lambda msgs=None: gtkstub.D()
        rows, target, ev = _click_env(w, 2)
        w._on_list_context(w.listbox, ev)
        assert "✔ Ajouter aux tâches…" in labels and "📅 Proposer des créneaux (agenda)" not in labels
        labels.clear()
        w.config["gcal"] = {"account": "acc12345", "enabled": True}
        w._on_list_context(w.listbox, ev)
        assert "✔ Ajouter aux tâches…" in labels and "📅 Proposer des créneaux (agenda)" in labels
    finally:
        listing.Gtk.MenuItem = orig


def prepared_env(n):
    w, be = win_with(n=n)
    w.engine = AIEngine(w.config, w.cache)
    w.config.data.update(ai_enabled=True, ai_has_key=True, ai_prepare_drafts=True)
    w.config.set_password("ai:nvidia", "nvapi")
    seen = []
    w.engine.prepare_reply = lambda msg, ex: (seen.append((msg.id, list(ex))), "Bonjour,\n[À COMPLÉTER : date de livraison]\nCordialement")[1]
    w.accounts = lambda: [{"id": "acc", "name": "Moi", "email": "moi@x.be", "signature_html": "<b>SAEC</b>"}]
    w.reload_list = lambda *a, **k: None
    return w, seen


def test_prepared_drafts_only_for_important_mails_that_expect_a_reply_and_never_sent():
    w, seen = prepared_env(401)
    now = time.time()
    w.cache.upsert_many([real_msg(50, "Ancien envoi", folder="sent", sender="moi@x.be", date=now - 9999)])
    sent = real_msg(51, "Précédent", folder="sent", sender="moi@x.be", date=now - 5000)
    sent.text = "Bonjour Marie, merci pour votre retour, je regarde cela cette semaine. Bien cordialement, Prénom Nom"
    cands = [real_msg(i, "Question %d" % i, date=now - 60, sender="marie@y.be") for i in range(1, 7)]
    cands[0].category = "people"
    old = real_msg(20, "Trop ancien", date=now - 5 * 86400, sender="marie@y.be")
    w.cache.upsert_many([sent] + cands + [old])
    ok = {"priority": 3, "reply_needed": True, "spam": False, "category": "people"}
    res = {m.id: dict(ok) for m in cands}
    res["r2"] = dict(ok, reply_needed=False)            # pas de réponse attendue
    res["r3"] = dict(ok, spam=True)                     # suspect
    res["r4"] = dict(ok, local=True)                    # tri local seulement : pas assez fiable
    res["r5"] = dict(ok, priority=1)                    # peu important
    res["r20"] = dict(ok)
    w._maybe_prepare_drafts(cands + [old], res)
    assert [s[0] for s in seen] == ["r1", "r6"]                                              # seuls r1 et r6 qualifient (r20 : trop ancien)
    assert any("merci pour votre retour" in e for e in seen[0][1])                           # style appris sur les messages envoyés
    drafts = w.cache.query("drafts", "all", limit=50)
    assert len(drafts) == 2 and all(d.id.startswith("draft-ai-") and d.folder == "drafts" for d in drafts)
    d = w.cache.get(drafts[0].id)
    assert d.to == "marie@y.be" and d.subject.startswith("Re: Question") and "[À COMPLÉTER : date de livraison]" in d.text
    assert "<b>SAEC</b>" in d.html and d.message_id.startswith("<r") and d.snippet.startswith("✨")
    assert w.cache.outbox_count() == 0                                                       # jamais envoyé ni mis en file d'envoi
    seen.clear()
    w._maybe_prepare_drafts(cands, res)
    assert [s[0] for s in seen] == []                                                        # déjà préparés : pas de doublon
    assert any("brouillon(s) de réponse prêt(s)" in t[0] for t in w.toasts)


def test_prepared_drafts_off_by_default_or_without_ai_and_limited_to_three():
    w, seen = prepared_env(402)
    now = time.time()
    cands = [real_msg(i, "Q%d" % i, date=now - 60, sender="a%d@y.be" % i) for i in range(1, 9)]
    w.cache.upsert_many(cands)
    res = {m.id: {"priority": 2, "reply_needed": True, "spam": False, "category": "people"} for m in cands}
    w.config["ai_prepare_drafts"] = False
    w._maybe_prepare_drafts(cands, res)
    assert seen == []                                                                         # interrupteur éteint : rien
    w.config["ai_prepare_drafts"] = True
    w.config["ai_enabled"] = False
    w._maybe_prepare_drafts(cands, res)
    assert seen == []                                                                         # IA désactivée : rien
    w.config["ai_enabled"] = True
    w._maybe_prepare_drafts(cands, res)
    assert len(seen) == 3                                                                     # au plus 3 par passage


def test_triage_reads_reply_needed_from_the_model_and_defaults_to_false_locally():
    def route(m, path, h, b):
        return 200, "application/json", json.dumps({"choices": [{"message": {"content": json.dumps(
            [{"i": 0, "summary": "Demande de devis", "priority": 3, "spam": False, "category": "people", "reply": True},
             {"i": 1, "summary": "Promo", "priority": 1, "spam": False, "category": "news"}])}}]}), {}
    srv = Server(route)
    try:
        c = Config(os.path.join(gtkstub.tmp, "tri.json"))
        c.data.update(ai_enabled=True, ai_provider="ollama", nvidia_api_base=srv.url + "/v1")
        eng = AIEngine(c, Cache(os.path.join(gtkstub.tmp, "tri.db")))
        ms = [real_msg(1, "Devis ?"), real_msg(2, "Promo")]
        out = eng.triage(ms)
        assert out["r1"]["reply_needed"] is True and out["r2"]["reply_needed"] is False and out["r1"]["priority"] == 3
        c.data["ai_enabled"] = False
        local = eng.triage([real_msg(3, "Autre")])
        assert local["r3"]["reply_needed"] is False and local["r3"]["local"] is True
    finally:
        srv.close()
