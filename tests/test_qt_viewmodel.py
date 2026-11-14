"""Interface Qt, partie sans Qt : lignes de liste, HTML du lecteur (assaini, CSP), ouverture d'un message (marqué lu ici et sur le serveur,
action rejouée), synchronisation (nouveaux messages, drapeaux, suppressions) — le tout sur le moteur seul, donc sur les trois systèmes."""
import os, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mintmail.models import Message
from mintmail.store import Cache
from mintmail.qt import viewmodel as V

A = {"id": "a1", "email": "a@x.be", "name": "A"}


class FakeBackend:
    demo = False

    def __init__(self):
        self.calls, self.result, self.fail, self.tree = [], ([], {}, None, 0), None, []

    def sync(self, logical, known, limit=60, on_batch=None, unseen=False):
        if self.fail:
            raise RuntimeError(self.fail)
        return self.result if logical == "inbox" else ([], {}, None, 0)

    def set_flags_many(self, items, seen=None, flagged=None, **kw):
        self.calls.append(("flags", [i.uid for i in items], seen) if not kw and flagged is None else ("flags", [i.uid for i in items], seen, flagged, kw))

    def move_many(self, items, dest, notjunk=False):
        self.calls.append(("move", [i.uid for i in items], dest, notjunk))

    def delete_many(self, items):
        self.calls.append(("delete", [i.uid for i in items]))

    def list_folders(self):
        return self.tree


def _eng():
    cache = Cache(os.path.join(tempfile.mkdtemp(), "c.db"))
    eng = V.Engine({"accounts": [A]}, cache)
    be = FakeBackend()
    eng._backends["a1"] = be
    return eng, cache, be


def _m(i, **kw):
    d = dict(id="m%d" % i, account="a1", folder="inbox", real_folder="INBOX", uid=i, sender_name="S%d" % i, sender_email="s%d@x.be" % i,
             subject="Sujet %d" % i, date=time.time() - i, snippet="extrait", text="corps", html="<p>corps</p>", unread=True)
    d.update(kw)
    return Message(**d)


def test_rows_and_views_cover_the_gtk_folders():
    keys = [k for k, _ in V.VIEWS]
    assert keys[:2] == ["inbox", "unread"] and {"starred", "pinned", "snoozed", "drafts", "sent", "archive", "spam", "trash"} <= set(keys)
    r = V.row_info(_m(1, pinned=True))
    assert r["sender"] == "S1" and r["unread"] and r["pinned"] and not r["attachments"] and r["time"]


def test_reader_html_is_sanitised_and_locked_down():
    h = V.render_html(_m(1, html='<p onclick="x()">salut</p><script>alert(1)</script><img src="http://t.example/p.png">'))
    assert "<script" not in h and "onclick" not in h and "Content-Security-Policy" in h
    assert "http:" not in h.split("img-src", 1)[1].split(";")[0]               # images distantes bloquées par la CSP par défaut
    assert "default-src 'none'" in h and "img-src data: cid:;" in h
    allowed = V.render_html(_m(1, html='<img src="http://t.example/p.png">'), load_images=True)
    assert "http:" in allowed.split("img-src", 1)[1].split(";")[0]
    plain = V.render_html(_m(2, html="", text="a <b> & c\nligne"), dark=True)
    assert "&lt;b&gt;" in plain and "#1f2229" in plain and "<script" not in plain


def test_opening_marks_read_locally_and_queues_the_server_action():
    eng, cache, be = _eng()
    cache.upsert_many([_m(5)])
    m = eng.open_message("m5")
    assert m.text == "corps" and not m.unread and not cache.get("m5").unread
    assert cache.ops_count() == 1
    done, errors, offline = eng.flush()
    assert len(done) == 1 and not errors and not offline and be.calls == [("flags", [5], True)] and cache.ops_count() == 0
    eng.open_message("m5")                                                    # déjà lu : rien de plus à envoyer
    assert cache.ops_count() == 0
    eng.set_unread("m5", True)
    assert cache.get("m5").unread and cache.ops_count() == 1


def test_sync_adds_new_messages_applies_flags_and_removals():
    eng, cache, be = _eng()
    cache.upsert_many([_m(1), _m(2, unread=False), _m(3)])
    be.result = ([_m(4)], {1: (False, True), 2: (True, False)}, {1, 2, 4}, 1)
    fresh, errors = eng.sync()
    assert not errors and fresh == 1
    assert cache.get("m4") is not None
    assert not cache.get("m1").unread and cache.get("m1").starred and cache.get("m2").unread
    assert cache.get("m3") is None                                            # disparu du serveur
    counts = V.counts(cache)
    assert counts["inbox"] == 2 and counts["unread"] == 2


def test_local_pending_action_wins_over_the_server_state_and_errors_are_reported():
    eng, cache, be = _eng()
    cache.upsert_many([_m(1)])
    eng.open_message("m1")                                                    # lu ici, action pas encore partie
    be.result = ([], {1: (True, False)}, {1}, 1)                              # le serveur dit encore « non lu »
    eng.sync()
    assert not cache.get("m1").unread
    be.fail = "réseau coupé"
    fresh, errors = eng.sync()
    assert fresh == 0 and errors and "réseau coupé" in errors[0]


def test_demo_account_is_used_without_configuration():
    assert V.accounts_of({"accounts": []})[0]["demo"] is True
    assert V.accounts_of({"accounts": [A]}) == [A]


def test_move_updates_the_cache_first_then_the_server_and_resyncs_the_destination():
    eng, cache, be = _eng()
    cache.upsert_many([_m(1), _m(2)])
    msgs = [cache.get_light("m1"), cache.get_light("m2")]
    ids = eng.move(msgs, "archive")
    assert cache.get("m1").folder == "archive" and cache.ops_count() == 2 - 1          # une action pour le compte
    be.result = ([_m(11, folder="archive", real_folder="Archive")], {}, {11}, 1)
    errors, offline = eng.finish_move(msgs, "archive", ids)
    assert not errors and not offline and be.calls[0] == ("move", [1, 2], "archive", False) and cache.ops_count() == 0
    assert cache.get("m1") is None                                                    # copie locale remplacée par celle du serveur
    eng2, cache2, be2 = _eng()
    cache2.upsert_many([_m(3, folder="spam", real_folder="Spam")])
    m3 = [cache2.get_light("m3")]
    eng2.finish_move(m3, "inbox", eng2.move(m3, "inbox"))
    assert be2.calls[0] == ("move", [3], "inbox", True)                              # « Ce n'est pas du spam » apprend au serveur


def test_move_offline_keeps_the_action_and_delete_forever_removes_locally():
    eng, cache, be = _eng()
    cache.upsert_many([_m(1), _m(2)])
    def boom(items, dest, notjunk=False):
        raise ConnectionResetError("réseau")
    be.move_many = boom
    m1 = [cache.get_light("m1")]
    ids = eng.move(m1, "trash")
    errors, offline = eng.finish_move(m1, "trash", ids)
    assert offline and cache.ops_count() == 1 and cache.get("m1").folder == "trash"  # conservé, rejoué au retour du réseau
    m2 = [cache.get_light("m2")]
    ids = eng.delete_forever(m2)
    assert cache.get("m2") is None
    eng.run_ops(ids)
    assert ("delete", [2]) in be.calls


def test_flags_star_unread_pin_are_local_first_and_sent_to_the_server():
    eng, cache, be = _eng()
    cache.upsert_many([_m(1, unread=False)])
    m = [cache.get_light("m1")]
    for field, value in (("starred", True), ("unread", True), ("pinned", True)):
        eng.run_ops(eng.set_flag(m, field, value))
    c = cache.get("m1")
    assert c.starred and c.unread and c.pinned
    assert be.calls[0][3] is True and be.calls[1][2] is False and be.calls[2][4] == {"pinned": True}


def test_folder_tree_lists_custom_folders_and_move_targets():
    cfg = {"accounts": [A], "folders": {"a1": [
        {"name": "INBOX", "label": "Boîte", "special": "inbox", "selectable": True, "depth": 0},
        {"name": "LTD", "label": "LTD", "special": "", "selectable": True, "depth": 0},
        {"name": "LTD/Sub", "label": "Sub", "special": "", "selectable": True, "depth": 1},
        {"name": "[Gmail]", "label": "[Gmail]", "special": "", "selectable": False, "depth": 0}]}}
    eng = V.Engine(cfg, Cache(os.path.join(tempfile.mkdtemp(), "c.db")))
    nav = eng.nav_folders()
    assert [(d, l, depth) for d, l, depth, _a in nav] == [("f:LTD", "LTD", 0), ("f:LTD/Sub", "Sub", 1)]
    assert ("f:LTD", "LTD") in eng.move_targets("a1") and ("inbox", "Boîte") in eng.move_targets("a1")
    eng2, _c, be = _eng()
    be.tree = [{"name": "INBOX", "label": "I", "special": "inbox", "selectable": True, "depth": 0}, {"name": "Z", "label": "Z", "special": "", "selectable": True, "depth": 0}]
    class Cfg(dict):
        def save(self): self.saved = True
    eng2.config = Cfg({"accounts": [A]})
    assert eng2.refresh_folders() is True and eng2.config["folders"]["a1"] == be.tree and eng2.refresh_folders() is False


# ------------------------------------------------------------------ rédaction (sans Qt)
from mintmail.qt import composing as C
from mintmail.models import Outgoing


def _cfg(**kw):
    d = {"accounts": [A, {"id": "a2", "email": "b@x.be", "name": "B"}], "identities": [
        {"id": "i1", "account": "a1", "email": "ventes@x.be", "name": "Ventes", "signature_html": "<b>Équipe ventes</b>"}], "undo_seconds": 6}
    d.update(kw)
    return d


def test_reply_quotes_the_original_and_picks_the_alias_it_was_sent_to():
    cfg = _cfg()
    m = _m(1, to="ventes@x.be, moi@y.be", cc="tiers@z.be", reply_to="", message_id="<m1@x>", references="<r0@x>", html="<p>Bonjour <script>x</script></p>")
    a = C.reply_args(cfg, cfg["accounts"], m, all_=True, default_account="a1")
    assert a["account_id"] == "ident:i1" and a["to"] == "s1@x.be" and a["subject"] == "Re: Sujet 1"
    assert "moi@y.be" in a["cc"] and "tiers@z.be" in a["cc"] and "ventes@x.be" not in a["cc"]          # mes propres adresses n'y sont pas
    assert "<blockquote>" in a["quote_html"] and "<script" not in a["quote_html"] and a["in_reply_to"] == "<m1@x>"
    single = C.reply_args(cfg, cfg["accounts"], m, default_account="a1")
    assert single["cc"] == ""
    f = C.forward_args(_m(2, attachments=[{"filename": "a.pdf", "path": "/tmp/a.pdf"}]), "a1")
    assert f["subject"] == "Fwd: Sujet 2" and f["attachments"] == ["/tmp/a.pdf"] and 'id="qt"' in f["quote_html"]


def test_signature_follows_the_chosen_sender_and_never_duplicates():
    cfg = _cfg()
    acc, ident = C.resolve_from(cfg, cfg["accounts"], "ident:i1")
    assert acc["id"] == "a1" and ident["email"] == "ventes@x.be"
    assert [k for k, _ in C.from_choices(cfg, cfg["accounts"])] == ["a1", "ident:i1", "a2"]
    sig = C.signature_html(acc, ident)
    body = C.initial_content("", "<div id='qt'>cité</div>", sig)
    assert body.count('id="sig"') == 1 and body.endswith("<div id='qt'>cité</div>")
    other = C.signature_html({"signature_html": "Cordialement"}, None)
    swapped = C.swap_signature(body, other)
    assert "Équipe ventes" not in swapped and "Cordialement" in swapped and swapped.count('id="sig"') == 1
    assert C.initial_content("<p>brouillon</p>", "", sig, raw=True) == "<p>brouillon</p>"
    assert C.signature_html({"signature_html": "  "}, None) == ""


def test_recipient_validation_and_outgoing_message():
    assert C.valid_recipients("a@b.be, c@d.fr") and C.valid_recipients("a@b.be", "x@y.be", "z@t.be")
    assert not C.valid_recipients("") and not C.valid_recipients("pas-une-adresse") and not C.valid_recipients("a@b.be", "oups")
    cfg = _cfg()
    acc, ident = C.resolve_from(cfg, cfg["accounts"], "ident:i1")
    out = C.build_outgoing(acc, ident, " a@b.be ", "", "", "  ", "<p>x</p>", ["/tmp/f"], "<id@x>", "<r@x>")
    assert out.account == "a1" and out.from_email == "ventes@x.be" and out.to == "a@b.be" and out.subject == "(Sans objet)" and out.in_reply_to == "<id@x>"
    assert C.body_of_qt_html("<html><head><style>p{}</style></head><body style='x'><p>salut</p></body></html>") == "<p>salut</p>"


def test_draft_roundtrip_and_schedule_times():
    eng, cache, _ = _eng()
    did = C.save_draft(cache, A, None, "a@b.be", "", "Objet", "<p>corps</p>", [], "<id@x>", "")
    d = cache.get(did)
    assert d.folder == "drafts" and d.to == "a@b.be" and d.subject == "Objet" and "corps" in d.text and not d.unread
    again = C.save_draft(cache, A, did, "a@b.be", "", "Objet 2", "<p>autre</p>", [])
    assert again == did and cache.get(did).subject == "Objet 2"
    args = C.draft_args(cache.get(did))
    assert args["draft_id"] == did and args["raw"] is True and args["account_id"] == "a1"
    now = time.time()
    assert C.at(1, 8) > now and C.next_monday() > now


def test_outbox_sends_after_the_undo_delay_keeps_offline_messages_and_reports_failures():
    eng, cache, be = _eng()
    sent = []
    be.send = lambda out: sent.append(out.subject)
    eng.config = {"accounts": [A], "undo_seconds": 0}
    oid = eng.queue_send(Outgoing(account="a1", to="x@y.be", subject="S1", html="<p>1</p>"))
    out = eng.undo_send(oid)                                                   # annulé avant le départ : rien n'est envoyé
    assert out.subject == "S1" and not eng.process_outbox() and not sent
    eng.queue_send(Outgoing(account="a1", to="x@y.be", subject="S2", html="<p>2</p>"))
    ev = eng.process_outbox()
    assert [(k, o.subject) for k, o, _e in ev] == [("sent", "S2")] and sent == ["S2"] and not cache.outbox_due()
    def down(out): raise ConnectionResetError("réseau")
    be.send = down
    eng.queue_send(Outgoing(account="a1", to="x@y.be", subject="S3", html="x"))
    assert [k for k, _o, _e in eng.process_outbox()] == ["retry"] and cache.outbox_count() == 1       # conservé pour un nouvel essai
    def refused(out): raise RuntimeError("550 refusé")
    be.send = refused
    cache.outbox_reschedule(cache.outbox_list()[0][0], time.time() - 1)
    assert [k for k, _o, _e in eng.process_outbox()] == ["failed"] and cache.outbox_count() == 0
    eng.queue_send(Outgoing(account="a1", to="x@y.be", subject="S4", html="x"), delay=3600, scheduled=True)
    assert not eng.process_outbox() and cache.outbox_count() == 1               # programmé : attend son heure


def test_demo_account_sent_messages_land_in_the_sent_folder():
    eng, cache, _ = _eng()
    eng.config = {"accounts": [], "undo_seconds": 0}
    eng._backends["demo"] = V.make_backend(V.DEMO_ACCOUNT, eng.config)
    eng._backends["demo"].send = lambda out: None
    eng.queue_send(Outgoing(account="demo", to="x@y.be", subject="Démo", html="<p>hop</p>"))
    assert [k for k, _o, _e in eng.process_outbox()] == ["sent"]
    assert any(m.subject == "Démo" for m in cache.query("sent", "all"))
    eng.snooze([_m(1)], time.time() + 3600)                                     # sans effet sur un message absent du cache, sans erreur


# ------------------------------------------------------------------ thème
from mintmail.qt import theme as TH
from mintmail.style import STYLES


def test_theme_builds_for_every_style_and_mode_with_colours_qt_can_read():
    import re
    for style in STYLES:
        for mode in ("dark", "light"):
            t = TH.resolve({"style": style, "theme": mode, "accent": "#7c8cff"})
            q = TH.build_qss(t)
            assert t["dark"] == (mode == "dark") and "rgba(" not in q and "%(" not in q
            for k in ("bg", "side", "card", "panel", "hover", "text", "dim", "line", "field", "accent", "on"):
                assert re.fullmatch(r"#[0-9a-fA-F]{6}", t[k]), (style, mode, k, t[k])      # aplats #rrggbb : Qt les lit tous
    assert TH.resolve({"theme": "system"}, system_dark=True)["dark"] and not TH.resolve({"theme": "system"}, system_dark=False)["dark"]
    assert TH.resolve({"style": "inconnu"})["style"] == "aurora"
    assert TH.solid("rgba(255,255,255,0.5)") == "#80ffffff" and TH.solid("#123456") == "#123456"
    assert TH.row_height("compact") < TH.row_height("comfortable") < TH.row_height("spacious")
    assert V.row_info(_m(1, sender_email="Z@x.be"))["email"] == "Z@x.be"


# ------------------------------------------------------------------ comptes et réglages
from mintmail.qt import accounts as AC


class _Cfg(dict):
    def __init__(self, **kw):
        super().__init__(accounts=[], **kw)
        self.pw, self.saved = {}, 0

    def password(self, aid):
        return self.pw.get(aid, "")

    def set_password(self, aid, pw):
        self.pw[aid] = pw

    def delete_password(self, aid):
        self.pw.pop(aid, None)

    def save(self):
        self.saved += 1

    def reset(self, keys):
        for k in keys:
            self.pop(k, None)


FORM = dict(name="Moi", email="moi@exemple.be", username="", imap_host="imap.exemple.be", imap_port=993, smtp_host="smtp.exemple.be", smtp_port=587, imap_ssl=True)


def test_account_form_validation_matches_the_gtk_rules():
    assert AC.collect({}, dict(FORM, email="pas-un-mail"))[1] == "Adresse e-mail invalide."
    assert "IMAP et SMTP" in AC.collect({}, dict(FORM, imap_host=""))[1]
    assert AC.collect({}, dict(FORM, imap_port="abc"))[1] == "Les ports doivent être des nombres."
    assert AC.collect({}, dict(FORM, smtp_port=70000))[1] == "Port invalide (1 à 65535)."
    a, err = AC.collect({"demo": True}, FORM)
    assert not err and a["email"] == "moi@exemple.be" and "demo" not in a and a["id"] and "auth" not in a
    g, _ = AC.collect({}, FORM, oauth="google")
    assert g["auth"] == "oauth2" and g["oauth_provider"] == "google"
    assert AC.apply_preset("iCloud")["imap_host"] == "imap.mail.me.com" and AC.apply_preset("inconnu") == {}
    assert len(AC.preset_choices()) == len(AC.PRESETS)


def test_account_save_remove_and_password_handling():
    cfg, cache = _Cfg(), Cache(os.path.join(tempfile.mkdtemp(), "c.db"))
    a, _ = AC.collect({}, FORM)
    assert AC.save_account(cfg, cache, dict(a)) == "Mot de passe requis." and not cfg["accounts"]
    assert AC.save_account(cfg, cache, dict(a), "secret") == "" and cfg.pw[a["id"]] == "secret" and cfg["accounts"][0]["has_password"]
    dup, _ = AC.collect({}, FORM)                                                       # même adresse, autre compte
    assert AC.save_account(cfg, cache, dup, "x") == "Ce compte existe déjà."
    edited, _ = AC.collect(cfg["accounts"][0], dict(FORM, name="Nouveau nom"))
    assert AC.save_account(cfg, cache, edited) == "" and cfg["accounts"][0]["name"] == "Nouveau nom" and cfg.pw[a["id"]] == "secret"     # mot de passe conservé
    og, _ = AC.collect({}, dict(FORM, email="g@gmail.com"), oauth="google")
    assert "Se connecter" in AC.save_account(cfg, cache, og, "", "google")
    assert AC.save_account(cfg, cache, og, "refresh-token", "google") == "" and len(cfg["accounts"]) == 2
    cache.upsert(_m(1, account=a["id"]))
    AC.remove_account(cfg, cache, a["id"])
    assert len(cfg["accounts"]) == 1 and a["id"] not in cfg.pw and cache.get("m1") is None


def test_connection_test_uses_the_typed_password_and_reports_errors(monkeypatch=None):
    import mintmail.qt.accounts as mod
    seen = {}

    class B:
        def __init__(self, acc, cfg): seen["pw"] = cfg.password(acc["id"])
        def test(self): return None if seen["pw"] == "bon" else "authentification refusée"
    real = mod.make_backend
    mod.make_backend = lambda acc, cfg: B(acc, cfg)
    try:
        cfg = _Cfg()
        cfg.pw["x"] = "bon"
        assert AC.test_account(cfg, {"id": "x"}, "") is None and AC.test_account(cfg, {"id": "x"}, "mauvais") == "authentification refusée"
    finally:
        mod.make_backend = real


def test_reset_appearance_restores_defaults():
    from mintmail.store import DEFAULTS
    cfg = _Cfg(theme="dark")
    cfg["style"] = "terminal"
    AC.reset_appearance(cfg)
    assert "theme" not in cfg and "style" not in cfg and cfg.saved == 1
    assert set(AC.APPEARANCE_KEYS) <= set(DEFAULTS)                                      # chaque clé réinitialisable existe vraiment


# ------------------------------------------------------------------ règles, expéditeurs bloqués / spam
from mintmail.qt import automation as AU


class _CfgAU(dict):
    def save(self):
        self.saved = getattr(self, "saved", 0) + 1


def _eng_au(**extra):
    eng, cache, be = _eng()
    cfg = _CfgAU({"accounts": [A], "blocked": [], "spam_senders": [], "rules": [],
                  "folders": {"a1": [{"name": "INBOX", "label": "Boîte", "path": "Boîte", "special": "inbox", "selectable": True, "depth": 0},
                                     {"name": "Factures", "label": "Factures", "path": "Factures", "special": "", "selectable": True, "depth": 0}]}})
    cfg.update(extra)
    eng.config = cfg
    return eng, cache, be


def test_rule_match_and_find_folder_follow_the_gtk_semantics():
    m = _m(1, subject="Facture mars", sender_name="Ana", sender_email="ana@shop.be")
    assert AU.rule_match({"field": "subject", "text": "FACTURE"}, m) and not AU.rule_match({"field": "subject", "text": ""}, m)
    assert AU.rule_match({"field": "from", "text": "shop.be"}, m) and not AU.rule_match({"field": "to", "text": "shop"}, m)
    eng, _c, _b = _eng_au()
    assert AU.find_folder(eng, "factures")[1]["name"] == "Factures" and AU.find_folder(eng, "zzz") is None and AU.find_folder(eng, "") is None


def test_route_applies_block_spam_and_rules_and_apply_moves_updates_the_cache():
    eng, cache, be = _eng_au(blocked=["@bad.com"], spam_senders=["s2@x.be"],
                             rules=[{"field": "subject", "text": "facture", "action": "move", "folder": "Factures"},
                                    {"field": "subject", "text": "promo", "action": "archive"},
                                    {"field": "subject", "text": "info", "action": "read"}])
    ms = [_m(1, sender_email="u@bad.com"), _m(2), _m(3, subject="Facture"), _m(4, subject="Promo -20%"), _m(5, subject="Info"), _m(6)]
    for m in ms:
        cache.upsert(m) if hasattr(cache, "upsert") else cache.add([m])
    keep, plan = AU.route(eng, ms)
    assert [m.id for m in keep] == ["m5", "m6"] and {k: [m.id for m in v] for k, v in plan.items()} == {
        "trash": ["m1"], "spam": ["m2"], "f:Factures": ["m3"], "archive": ["m4"]}
    groups = AU.apply_moves(eng, plan)
    assert len(groups) == 4 and cache.get("m1").folder == "trash" and cache.get("m3").folder == "f:Factures"
    assert cache.get("m5").unread is False                                                   # règle « marquer lu »
    assert AU.route(eng, [])[1] == {}


def test_filter_sender_block_unblock_and_not_spam_roundtrip():
    eng, cache, _b = _eng_au()
    a, b = _m(1, sender_email="x@spam.io"), _m(2, sender_email="y@spam.io")
    for m in (a, b):
        cache.upsert(m) if hasattr(cache, "upsert") else cache.add([m])
    msgs, dest = AU.filter_sender(eng, "@spam.io", "blocked", a)
    assert dest == "trash" and {m.id for m in msgs} == {"m1", "m2"} and eng.config["blocked"] == ["@spam.io"]
    AU.filter_sender(eng, "@spam.io", "blocked")
    assert eng.config["blocked"] == ["@spam.io"]                                              # pas de doublon
    AU.unfilter_sender(eng, "blocked", "@SPAM.io")
    assert eng.config["blocked"] == []
    c = _m(3, folder="spam", sender_email="z@x.be")
    cache.upsert(c) if hasattr(cache, "upsert") else cache.add([c])
    eng.config["spam_senders"] = ["z@x.be", "@x.be"]
    back = AU.not_spam(eng, c)
    assert [m.id for m in back] == ["m3"] and eng.config["spam_senders"] == []


def test_rules_add_remove_and_apply_now():
    eng, cache, _b = _eng_au()
    assert AU.add_rule(eng, "subject", " Promo ", "trash") and not AU.add_rule(eng, "subject", "Promo", "trash") and not AU.add_rule(eng, "from", " ", "trash")
    assert AU.add_rule(eng, "subject", "Fact", "move", "Factures") and eng.config["rules"][1]["folder"] == "Factures"
    m = _m(1, subject="Promo")
    cache.upsert(m) if hasattr(cache, "upsert") else cache.add([m])
    left, groups = AU.apply_rules_now(eng)
    assert left == 0 and groups[0][1] == "trash"
    assert AU.remove_rule(eng, 0) and len(eng.config["rules"]) == 1 and not AU.remove_rule(eng, 9)


def test_sync_and_route_only_filters_new_messages():
    eng, cache, be = _eng_au(blocked=["s9@x.be"])
    old = _m(1, sender_email="s9@x.be")                                                      # déjà en boîte : on n'y touche pas
    cache.upsert_many([old, _m(2)])
    be.result = ([_m(9, sender_email="s9@x.be"), _m(8)], {}, {1, 2, 8, 9}, 1)
    fresh, errors, done = AU.sync_and_route(eng)
    assert not errors and done == [("trash", 1)]
    assert cache.get("m1").folder == "inbox" and cache.get("m8").folder == "inbox"
    assert ("move", [9], "trash", False) in be.calls                                           # le serveur est prévenu du rangement
    assert fresh == 1                                                                         # m9 (bloqué) ne compte pas comme nouveau non lu


# ------------------------------------------------------------------ assistant IA
from mintmail.qt import assistant as AS


class _FakeAI:
    def __init__(self, plan=None, cls=None):
        self._plan, self._cls, self.folder_names, self.asked = plan, cls, [], []

    def plan(self, text, ctx, hist):
        self.asked.append((text, ctx, hist))
        return self._plan

    def classify(self, msgs, existing, account=None, **kw):
        return self._cls

    def enabled(self):
        return True

    def local_digest(self, counts, msgs):
        return "local %d" % len(msgs)


def _eng_as(plan=None, cls=None, **extra):
    eng, cache, be = _eng_au(**extra)
    eng.config.setdefault("ai_privacy", "full")
    eng.config.get = lambda k, d=None, _c=eng.config: dict.get(_c, k, d)
    eng.ai = _FakeAI(plan, cls)
    be.created = []
    be.create_folder = lambda path: be.created.append(path)
    return eng, cache, be


def test_assistant_context_and_plan_resolution_follow_the_gtk_rules():
    eng, cache, be = _eng_as({"reply": "ok", "actions": [{"type": "archive", "query": "from:s1"}, {"type": "trash", "query": "zzz"},
                                                            {"type": "search", "query": "x"}, {"type": "not_spam"}]})
    cache.upsert_many([_m(1), _m(2)])
    res = AS.ask(eng, "range", "Boîte de réception", "all", None, [])
    ctx = eng.ai.asked[0][1]
    assert "Boîte de réception" in ctx and "Dossiers existants" in ctx and "Factures" in ctx and "Derniers non lus" in ctx
    labels = [i["label"] for i in res["items"]]
    assert "Archiver (1 message)" in labels[0] and "aucun message concerné" in labels[1] and labels[2].startswith("Rechercher")
    assert res["items"][1]["action"] is None and res["items"][3]["action"] is None
    assert eng.ai_hist[-1]["content"] == "ok" and eng.ai.folder_names
    eng.config["ai_privacy"] = "minimal"
    assert "Derniers non lus" not in AS.context(eng, "v", "all")


def test_assistant_run_moves_flags_rules_and_ui_requests():
    eng, cache, be = _eng_as()
    ms = [_m(1), _m(2)]
    cache.upsert_many(ms)
    out = AS.run(eng, {"type": "archive"}, ms)
    assert out["changed"] and ("move", [1, 2], "archive", False) in be.calls
    out = AS.run(eng, {"type": "star"}, [_m(1)])
    assert any(c[0] == "flags" for c in be.calls)
    assert AS.run(eng, {"type": "search", "query": "is:unread"})["search"] == "is:unread"
    assert AS.run(eng, {"type": "open_settings", "page": "ai"})["settings"] == "ai"
    c = AS.run(eng, {"type": "compose", "to": "a@b.c", "subject": "S", "body": "x\ny"})["compose"]
    assert c["to"] == "a@b.c" and "<br" in c["body_html"] or "<p" in c["body_html"]
    AS.run(eng, {"type": "create_rule", "field": "subject", "text": "promo", "action": "trash"})
    AS.run(eng, {"type": "create_rule", "field": "subject", "text": "promo", "action": "trash"})
    assert eng.config["rules"] == [{"field": "subject", "text": "promo", "action": "trash"}]
    AS.run(eng, {"type": "block_sender", "email": "@spam.io"})
    assert eng.config["blocked"] == ["@spam.io"]
    AS.run(eng, {"type": "block_sender"}, selected=[_m(7, sender_email="z@z.be")])
    assert "z@z.be" in eng.config["blocked"]
    cache.upsert(_m(5))
    AS.run(eng, {"type": "snooze", "until": "3h"}, [_m(5)])
    assert cache.get("m5").snoozed_until > time.time()
    assert AS.snooze_time("nextweek") > time.time() and AS.snooze_time("weekend") > time.time()


def test_assistant_creates_folders_once_and_moves_into_them():
    eng, cache, be = _eng_as()
    m = _m(1)
    cache.upsert(m)
    out = AS.run(eng, {"type": "move", "folder": "Clients"}, [m])
    assert be.created == ["Clients"] and out["changed"] and ("move", [1], "f:Clients", False) in be.calls
    assert any(e["label"] == "Clients" for e in eng.folder_entries("a1"))
    AS.run(eng, {"type": "create_folder", "name": "Clients"})                                  # idempotent : rien de recréé
    assert be.created == ["Clients"]
    AS.run(eng, {"type": "create_folder", "name": "Alpha", "parent": "Clients"})
    assert be.created == ["Clients", "Clients/Alpha"] and AU.find_folder(eng, "Clients › Alpha")
    assert AS.ensure_folder(eng, "a1", "Clients › Beta")["path"] == "Clients › Beta"
    assert AS.create_folder(eng, "a1", "///") is None
    be.create_folder = lambda p: (_ for _ in ()).throw(RuntimeError("ALREADYEXISTS"))
    assert AS.create_folder(eng, "a1", "Déjà")["label"] == "Déjà"                            # « existe déjà » n'est pas une erreur


def test_assistant_classify_proposes_then_applies_only_on_approval():
    eng, cache, be = _eng_as(cls={"moves": {"Factures": ["m1", "m2"], "Nouveau": ["m3"]}, "new": ["Nouveau"], "stay": 1})
    ms = [_m(1), _m(2), _m(3), _m(4, folder="trash")]
    cache.upsert_many(ms)
    out = AS.run(eng, {"type": "classify"}, ms)
    plan = out["plan"]
    assert [p["folder"] for p in plan] == ["Factures", "Nouveau"] and plan[1]["new"] and "(nouveau dossier)" in plan[1]["label"]
    assert not be.calls and not be.created                                                    # rien n'a bougé avant l'accord
    assert AS.apply_group(eng, "a1", "Nouveau", plan[1]["msgs"]) == 1 and be.created == ["Nouveau"]
    assert AS.apply_group(eng, "a1", "Factures", plan[0]["msgs"]) == 2


def test_assistant_digest_is_local_without_ai_and_says_all_clear_when_empty():
    eng, cache, _b = _eng_as()
    assert "à jour" in AS.digest(eng)
    cache.upsert_many([_m(1), _m(2)])
    eng.ai.enabled = lambda: False
    assert AS.digest(eng) == "local 2"


def test_ai_settings_logic_provider_key_and_endpoint_rules():
    class Cfg(dict):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self.data, self.pw, self.saved = {"nvidia_api_key": "vieux"}, {}, 0
        def save(self): self.saved += 1
        def set_password(self, k, v): self.pw[k] = v
    cfg = Cfg(ai_provider="nvidia", nvidia_api_base="https://x/v1", ai_model="m")
    base, model, needs = AS.set_provider(cfg, "ollama")
    assert base.startswith("http://localhost") and not needs and cfg["nvidia_api_base"] == "" and cfg["ai_model"] == ""
    assert AS.set_provider(cfg, "nimporte")[2] is True and cfg["ai_provider"] == "nvidia"       # fournisseur inconnu → NVIDIA
    assert AS.save_key(cfg, "  ") is False and AS.save_key(cfg, " nvapi-1 ") and cfg.pw["ai:nvidia"] == "nvapi-1"
    assert cfg["ai_has_key"] is True and "nvidia_api_key" not in cfg.data                      # plus jamais en clair
    assert AS.save_endpoint(cfg, "http://exemple.com/v1") and cfg["nvidia_api_base"] != "http://exemple.com/v1"
    assert AS.save_endpoint(cfg, "https://exemple.com/v1") is None and cfg["nvidia_api_base"] == "https://exemple.com/v1"
    assert AS.save_endpoint(cfg, "http://localhost:11434/v1") is None and AS.save_endpoint(cfg, "") is None and cfg["nvidia_api_base"] == ""
    assert {k for k, _l, _d in AS.AI_SWITCHES} <= set(__import__("mintmail.store", fromlist=["DEFAULTS"]).DEFAULTS)
    assert {k for k, _l, _d, _o in AS.AI_CHOICES} <= set(__import__("mintmail.store", fromlist=["DEFAULTS"]).DEFAULTS)
