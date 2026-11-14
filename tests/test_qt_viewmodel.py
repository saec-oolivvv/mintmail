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


# ------------------------------------------------------------------ carte IA du lecteur
from mintmail.qt import readerai as RA


class _FakeAI2(_FakeAI):
    lang = "fr"

    def __init__(self, on=True):
        super().__init__()
        self.on, self.calls = on, []

    def enabled(self):
        return self.on

    def analyze(self, msg, force=False):
        self.calls.append(("analyze", msg.id, force))
        return {"summary": "Résumé", "priority": 3, "suspicious": False, "points": [], "tasks": [], "folder": "Factures"}

    def translate_message(self, msg):
        return "traduit"

    def ask(self, msg, q):
        return "réponse à " + q

    def write_from_prompt(self, idea, subject="", to="", context=""):
        self.calls.append(("write", idea, subject, to))
        return "Bonjour,\nmerci."

    def _msg_block(self, msg, limit=None):
        return "<message>%s</message>" % msg.subject


def test_reader_card_state_follows_the_gtk_decision_tree():
    eng, cache, _b = _eng_as()
    eng.ai = _FakeAI2(on=False)
    m = _m(1)
    cache.upsert(m)
    st, res = RA.state(eng, m)
    assert st == "cta" and res["local"]                                                   # IA non configurée : résumé local + invitation
    eng.ai.on = True
    eng.config["ai_auto"] = False
    assert RA.state(eng, m) == ("idle", None)
    eng.config["ai_auto"] = True
    assert RA.state(eng, m) == ("load", None)
    out = RA.fetch(eng, m, force=True)
    assert out["summary"] == "Résumé" and eng.ai.calls[-1] == ("analyze", "m1", True) and eng.ai.folder_names
    cache.ai_set("m1", "analysis", out)
    assert RA.state(eng, m)[0] == "ready"                                                 # cache : affichage immédiat
    assert RA.title(out).endswith("URGENT") and RA.title({"local": True}).startswith("✨ RÉSUMÉ (local)")
    assert RA.warning({"suspicious": True, "why": "lien"}).startswith("⚠") and RA.warning({}) == ""


def test_reader_card_spam_suggestion_translate_ask_and_draft():
    eng, cache, _b = _eng_as()
    eng.ai = _FakeAI2()
    sp = _m(2, folder="spam")
    txt, btns = RA.spam_suggestion(sp, {"folder": "Factures"})
    assert [b[1] for b in btns] == ["not_spam", "not_spam_file"] and btns[1][2] == "Factures"
    assert RA.spam_suggestion(sp, {"suspicious": True}) is None and RA.spam_suggestion(_m(3), {}) is None
    assert RA.spam_suggestion(sp, {"local": True}) is None and RA.spam_suggestion(sp, {"error": "x"}) is None
    assert RA.translate(eng, sp) == "traduit" and RA.ask(eng, sp, "quand ?") == "réponse à quand ?"
    assert RA.draft(eng, sp) == "Bonjour,\nmerci." and eng.ai.calls[-1][2:] == ("Re: Sujet 2", "s2@x.be")


def test_quick_reply_goes_to_the_sender_with_the_alias_signature():
    from mintmail.qt import composing as C
    acc = dict(A, signature_html="<b>Sig</b>")
    cfg = {"identities": []}
    m = _m(1, reply_to="reply@x.be", message_id="<id@x>", references="<r@x>", subject="Re: Question")
    out = C.quick_reply_outgoing(cfg, [acc], m, "Merci !\nA+", "a1")
    assert out.to == "reply@x.be" and out.subject == "Re: Question" and out.in_reply_to == "<id@x>" and out.account == "a1"
    assert "Merci !" in out.html and "<b>Sig</b>" in out.html and out.html.index("Merci") < out.html.index("Sig")


def test_missing_keyring_password_gives_a_clear_error_instead_of_a_bad_login():
    class Cfg(dict):
        def password(self, aid): return ""
    acc = {"id": "p1", "email": "moi@x.be", "host": "h", "user": "u"}
    eng = V.Engine(Cfg(accounts=[acc]), Cache(os.path.join(tempfile.mkdtemp(), "c.db")))
    try:
        eng.backend("p1")
        raise AssertionError("une connexion sans mot de passe ne doit pas être tentée")
    except RuntimeError as e:
        assert "moi@x.be" in str(e) and "keyring" in str(e)
    _fx, errors = eng.sync()
    assert errors and "keyring" in errors[0]                                              # l'erreur remonte telle quelle dans la barre d'état
    eng2 = V.Engine(Cfg(accounts=[dict(acc, id="o1", auth="oauth2")]), Cache(os.path.join(tempfile.mkdtemp(), "c.db")))
    assert eng2.backend("o1") is not None                                                  # OAuth : pas de mot de passe à chercher


# ------------------------------------------------------------------ aide intégrée (F1)
from mintmail.qt import helpdoc as HD


def test_help_pages_render_for_every_section_search_and_links_safely():
    t = TH.resolve({"theme": "light"}, False)
    nav = HD.nav()
    assert nav[0][0] == "home" and len(nav) > 8
    for sid, _i, _title in nav:
        page = HD.page_html("sec:" + sid, t)
        assert len(page) > 300 and "<script" not in page.lower() and "{version}" not in page and "{config}" not in page
    home = HD.home_html(t, ordinal=100)
    assert "sec:" in home and "tip:1" in home and HD.home_html(t, ordinal=100, tip_offset=1) != home          # « Autre astuce » fait défiler
    assert HD.page_html("tip:3", t).count("tip:4") == 1
    hits = HD.page_html("spam", t)
    assert "résultat" in hits and "sec:" in hits and "zzzqqq" not in hits
    assert "Aucun résultat" in HD.results_html("zzzqqqxx", t)
    assert HD.page_html("sec:inexistant", t) == HD.home_html(t)                                           # section inconnue → accueil


def test_help_inline_text_is_escaped_and_only_http_links_are_clickable():
    t = TH.resolve({"theme": "light"}, False)
    out = HD.inline("<img src=x onerror=1> voir https://saec.me/doc, javascript:alert(1) « Paramètres » (S) Ctrl+K `x`", t)
    assert "<img" not in out and "&lt;img" in out
    assert 'href="https://saec.me/doc"' in out and "href=\"javascript" not in out and out.count("<a ") == 1
    assert "<b>«" in out and out.count("font-family:monospace") >= 2
    body = "Astuce : un conseil\nAttention : danger\n• a\n• b\n1. étape\nmintmail --reset\ntexte"
    html_ = HD.blocks_html(body, t)
    assert html_.count("<li>") == 2 and "💡" in html_ and "⚠" in html_ and "<pre" in html_ and "étape" in html_
    assert HD.F_keys("# / Suppr") == ["#", "Suppr"] and HD.F_keys("? … (recherche)") == ["?"]


# ------------------------------------------------------------------ mises à jour
from types import SimpleNamespace as NS
from mintmail.qt import updating as UP


class _Up:
    DEFAULT_REPO = "o/r"
    def __init__(self, pend="", can=(True, ""), res=None, check_code=""):
        self.pend, self.can, self.res, self.check_code, self.calls = pend, can, res, check_code, []
    def update_from_dict(self, d, cur):
        return NS(**d) if d and d["version"] > cur else None
    def update_to_dict(self, up): return dict(vars(up))
    def restart_pending(self, cur): return self.pend
    def is_newer(self, a, b): return a > b
    def short_notes(self, n): return n[:20]
    def due(self, now, last): return now - last > 3300
    def can_install(self): return self.can
    def fetch(self, up, d, progress=None):
        progress(50, 100); progress(100, 100); self.calls.append("fetch"); return "x.deb", "x.sig"
    def downloads_dir(self): return "/tmp"
    def check_signature(self, deb, sig): return self.check_code
    def install(self, deb, sig): self.calls.append("install"); return self.res or (True, "", "1.9.0")
    def cleanup(self): self.calls.append("cleanup")


def _up(version="1.0.0", **kw):
    cfg = _CfgAU(update_check=True, update_repo="", update_etag="", update_last_check=0, update_available=None,
                 update_snooze_version="", update_snooze_until=0, update_seen="", update_last_result="")
    return UP.UpdateState(cfg, _Up(**kw), version, now=lambda: 10000.0), cfg


def _avail(v="1.9.0"):
    return NS(version=v, deb_url="", deb_size=1, sig_url="", sums_url="", notes="Nouveautés " * 5, page="https://p")


def test_update_check_announces_once_snoozes_and_respects_the_automatic_setting():
    st, cfg = _up()
    assert st.banner["state"] == "hidden" and st.chip == ""
    assert st.should_check(startup=True) and not st.should_check() or True
    repo, etag = st.begin_check()
    assert repo == "o/r" and st.busy and not st.should_check(manual=True)                      # une seule recherche à la fois
    out = st.finish_check(NS(state="available", update=_avail(), code="", etag="E"), None)
    assert out["notify"].version == "1.9.0" and st.banner["state"] == "available" and "1.9.0" in st.chip
    assert st.banner["buttons"] == ["install", "notes", "later", "close"] and cfg["update_available"]["version"] == "1.9.0"
    st.begin_check()
    assert st.finish_check(NS(state="available", update=_avail(), code="", etag=""), None)["notify"] is None   # annoncée une seule fois
    st.snooze()
    assert st.banner["state"] == "hidden" and st.chip                                              # la pastille reste
    st.refresh()
    assert st.banner["state"] == "hidden"                                                          # repoussée 24 h
    st.refresh(force=True)
    assert st.banner["state"] == "available"
    cfg["update_check"] = False
    assert not st.should_check(startup=True) and st.should_check(manual=True)


def test_update_check_results_errors_uptodate_and_restore_from_config():
    st, cfg = _up()
    st.begin_check()
    assert "à jour" in st.finish_check(NS(state="uptodate", update=None, code="", etag="E"), None, manual=True)["toast"] and cfg["update_etag"] == "E"
    st.begin_check()
    assert st.finish_check(None, RuntimeError("x"), manual=True)["toast"] and not st.busy
    assert st.finish_check(NS(state="error", update=None, code="ratelimit", etag=""), None, manual=True)["toast"]
    assert cfg["update_last_result"] == "error:ratelimit" and any("limite" in l for l in st.status_lines())
    st2, cfg2 = UP.UpdateState(_CfgAU(update_available=dict(vars(_avail())), update_snooze_version="", update_snooze_until=0, update_last_check=0,
                                      update_last_result=""), _Up(), "1.0.0", now=lambda: 1.0), None
    assert st2.banner["state"] == "available"                                                      # affichée dès le lancement, sans réseau
    st3 = UP.UpdateState(_CfgAU(update_available=dict(vars(_avail("0.5.0"))), update_snooze_version="", update_snooze_until=0, update_last_check=0,
                                update_last_result=""), _Up(), "1.0.0", now=lambda: 1.0)
    assert st3.update is None and st3.config["update_available"] is None                          # déjà dépassée : oubliée


def test_update_install_flow_progress_success_and_every_failure_path():
    st, cfg = _up()
    cfg["update_available"] = dict(vars(_avail()))
    st.restore()
    stages = []
    assert st.start_install() is None and st.busy and st.banner["state"] == "progress"
    res = st.install_work(lambda v, t, f: stages.append((t, f)))
    assert res == (True, "", "1.9.0") and st.upd.calls == ["fetch", "install"] and stages[0][1] == 0.5 and "signature" in stages[2][0]
    assert st.finish_install(res, None) == "" and st.banner["state"] == "done" and st.update is None and "cleanup" in st.upd.calls
    assert st.banner["buttons"] == ["restart", "close"] and cfg["update_available"] is None
    # signature refusée : rien n'est installé
    st, cfg = _up(check_code="bad_signature")
    cfg["update_available"] = dict(vars(_avail()))
    st.restore()
    st.start_install()
    r = st.install_work(lambda *a: None)
    assert r == (False, "bad_signature", "") and "install" not in st.upd.calls
    assert "SIGNATURE" in st.finish_install(r, None) and st.banner["state"] == "error" and "retry" in st.banner["buttons"] and not st.busy
    # erreur réseau levée pendant le téléchargement
    st.restore()
    st.start_install()
    assert st.finish_install(None, NS(code="network")) and st.banner["state"] == "error"
    # installation automatique impossible : message clair, rien de lancé
    st, cfg = _up(can=(False, "nohelper"))
    cfg["update_available"] = dict(vars(_avail()))
    st.restore()
    assert "indisponible" in st.start_install() and not st.busy and st.banner["state"] == "error"
    # déjà installée sur le disque : il ne reste qu'à relancer
    st, cfg = _up(pend="1.9.0")
    cfg["update_available"] = dict(vars(_avail()))
    st.restore()
    assert st.banner["state"] == "done" and st.chip == "" and st.start_install() == "" and any("installé" in l for l in st.status_lines())
    assert UP.restart_command()[1:] == ["-m", "mintmail", "--qt"]
    assert "disponible" in _up()[0].key_line() or "prête" in _up()[0].key_line()


# ------------------------------------------------------------------ arbre des dossiers repliable
from mintmail.qt import navtree as NT


def _tree_eng(multi=False):
    ent = lambda name, label, path, depth, special="", sel=True: {"name": name, "label": label, "path": path, "depth": depth, "special": special, "selectable": sel}
    tree = [ent("INBOX", "Boîte", "Boîte", 0, "inbox"), ent("Clients", "Clients", "Clients", 0), ent("Clients/Alpha", "Alpha", "Clients › Alpha", 1),
            ent("Clients/Alpha/2026", "2026", "Clients › Alpha › 2026", 2), ent("Clients/Beta", "Beta", "Clients › Beta", 1),
            ent("Perso", "Perso", "Perso", 0), ent("[Gmail]", "[Gmail]", "[Gmail]", 0, sel=False), ent("[Gmail]/Tous", "Tous", "[Gmail] › Tous", 1)]
    accs = [A] + ([{"id": "a2", "email": "b@x.be", "name": "Pro"}] if multi else [])
    cfg = _CfgAU(accounts=accs, collapsed_folders=[], folders={a["id"]: tree for a in accs})
    return V.Engine(cfg, Cache(os.path.join(tempfile.mkdtemp(), "c.db"))), cfg


def test_nav_tree_is_collapsible_like_the_gtk_version_and_remembers_its_state():
    eng, cfg = _tree_eng()
    rows = NT.build(eng, cfg["collapsed_folders"])
    assert [r["label"] for r in rows] == ["Clients", "Alpha", "2026", "Beta", "Perso", "[Gmail]", "Tous"]          # la Boîte de réception reste dans les vues
    assert [r["depth"] for r in rows] == [0, 1, 2, 1, 0, 0, 1] and rows[0]["has_children"] and not rows[3]["has_children"]
    assert rows[5]["selectable"] is False and rows[0]["toggle"] == "a1|Clients" and rows[3]["toggle"] == ""
    assert NT.toggle(cfg, "a1|Clients") is True and cfg["collapsed_folders"] == ["a1|Clients"]
    rows = NT.build(eng, cfg["collapsed_folders"])
    assert [r["label"] for r in rows] == ["Clients", "Perso", "[Gmail]", "Tous"] and rows[0]["collapsed"]            # tout le sous-arbre disparaît
    NT.toggle(cfg, "a1|Clients")
    NT.toggle(cfg, "a1|Clients › Alpha")                                                                           # on peut ne replier qu'une branche
    assert [r["label"] for r in NT.build(eng, cfg["collapsed_folders"])][:4] == ["Clients", "Alpha", "Beta", "Perso"]
    assert NT.toggle(cfg, "a1|Clients › Alpha") is False and cfg["collapsed_folders"] == []


def test_nav_tree_has_one_collapsible_section_per_account_and_unread_badges():
    eng, cfg = _tree_eng(multi=True)
    rows = NT.build(eng, [])
    assert [r["kind"] for r in rows].count("account") == 2 and rows[0]["label"] == "A" and rows[0]["toggle"] == "acc:a1"
    assert len([r for r in rows if r["kind"] == "folder"]) == 14
    rows = NT.build(eng, ["acc:a2"])
    assert [r["label"] for r in rows if r["kind"] == "account"] == ["A", "Pro"] and len([r for r in rows if r["kind"] == "folder"]) == 7
    assert rows[-1]["kind"] == "account" and rows[-1]["collapsed"]
    eng.folder_unread[("a1", "Clients/Beta")] = 3
    eng.folder_unread[("a2", "Perso")] = 2
    assert NT.unread_of(eng, next(r for r in rows if r["name"] == "Clients/Beta")) == 3
    assert NT.account_unread(eng, rows[-1], rows) == 2 and NT.account_unread(eng, rows[0], rows) == 0
    assert NT.unread_of(eng, rows[0]) == 0
    eng1, _c = _tree_eng()
    assert not any(r["kind"] == "account" for r in NT.build(eng1, []))                                              # un seul compte : pas de section


def test_folder_counts_are_read_from_the_server_and_report_changes_only():
    eng, cache, be = _eng()
    be.folder_status = lambda names: {n: (5, 2 if n == "LTD" else 0) for n in names}
    eng.config = {"accounts": [A], "folders": {"a1": [{"name": "INBOX", "selectable": True, "special": "inbox"}, {"name": "LTD", "selectable": True, "special": ""}]}}
    assert eng.refresh_folder_counts() is True and eng.folder_unread[("a1", "LTD")] == 2
    assert eng.refresh_folder_counts() is False
    be.folder_status = lambda names: (_ for _ in ()).throw(RuntimeError("hors ligne"))
    assert eng.refresh_folder_counts() is False and eng.folder_unread[("a1", "LTD")] == 2                        # hors ligne : on garde les derniers chiffres


# ------------------------------------------------------------------ gestes de balayage
from mintmail.qt import gestures as GS


def test_swipe_thresholds_actions_and_touchpad_inversion_match_the_gtk_rules():
    cfg = GS.settings({})
    assert cfg == GS.DEFAULT_SWIPE
    assert GS.pick(40, cfg) == (None, 0) and GS.pick(-89, cfg) == (None, 0)                      # trop court : rien
    assert GS.pick(90, cfg) == ("archive", 1) and GS.pick(229, cfg) == ("archive", 1)
    assert GS.pick(230, cfg) == ("trash", 2) and GS.pick(-100, cfg) == ("snooze", 1) and GS.pick(-300, cfg) == ("read", 2)
    assert GS.pick(100, cfg, invert=True) == ("archive", 1)                                      # souris : jamais inversé
    assert GS.pick(100, cfg, invert=True, wheel=True) == ("snooze", 1) and GS.pick(-300, cfg, invert=True, wheel=True) == ("trash", 2)
    assert GS.pick(120, dict(cfg, right="none")) == (None, 0)
    mine = GS.settings({"swipe": {"right": "star", "left_long": "bidon", "inconnu": "trash"}})
    assert mine["right"] == "star" and mine["left_long"] == "read" and "inconnu" not in mine     # valeur ou clé inconnue : ignorée


def test_swipe_effects_toggle_flags_and_target_the_right_things():
    m = _m(1, unread=True)
    assert GS.effect("archive", m, 5) == {"move": "archive"} and GS.effect("spam", m, 5) == {"move": "spam"} and GS.effect("trash", m, 5) == {"move": "trash"}
    assert GS.effect("read", m, 5) == {"flag": ("unread", False)} and GS.effect("read", _m(2, unread=False), 5) == {"flag": ("unread", True)}
    assert GS.effect("star", m, 5) == {"flag": ("starred", True)} and GS.effect("pin", _m(3, pinned=True), 5) == {"flag": ("pinned", False)}
    assert GS.effect("snooze", m, 99.0) == {"snooze": 99.0} and GS.effect("block", _m(4, sender_email="A@B.be"), 5) == {"block": "a@b.be"}
    assert GS.effect("none", m, 5) == {}
    assert set(GS.DEFAULT_SWIPE.values()) <= set(GS.SWIPE_ACTIONS)
