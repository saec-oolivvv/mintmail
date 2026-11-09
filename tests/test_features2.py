"""Fonctions de la 1.8 au niveau de la fenêtre (GTK simulé) : conversations, hors ligne, désabonnement, invitations, recherche
serveur, apprentissage, identités, contacts, synchronisation des nouveaux éléments."""
import os, sys, time, types
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gtkstub
from test_listing import make_window
from mintmail import backend as B, caldav, extras, syncdata, unsub
from mintmail.ai_engine import AIEngine
from mintmail.backend import BackendError, DemoBackend
from mintmail.models import Message, Outgoing
from mintmail.store import Cache, Config


def sync_run_bg(w):
    def run_bg(fn, done=None):
        try:
            res, err = fn(), None
        except Exception as e:
            res, err = None, e
        if done:
            done(res, err)
    w.run_bg = run_bg


def real_msg(i, subject, refs="", folder="inbox", account="acc", sender="a@x.be", to="moi@x.be", date=None, unread=True, **kw):
    return Message(id="r%d" % i, account=account, folder=folder, real_folder="INBOX", uid=i + 1, sender_name="Exp", sender_email=sender,
                   to=to, subject=subject, date=date or (5000 + i), message_id="<r%d@x>" % i, references=refs, unread=unread,
                   text="corps", snippet="s", **kw)


class FakeBackend:
    demo = False

    def __init__(self): self.calls, self.fail = [], None
    def move_many(self, msgs, dest):
        if self.fail: raise self.fail
        self.calls.append(("move", [m.uid for m in msgs], dest))
    def set_flags_many(self, msgs, seen=None, flagged=None):
        if self.fail: raise self.fail
        self.calls.append(("flags", [m.uid for m in msgs], seen, flagged))
    def delete_many(self, msgs):
        if self.fail: raise self.fail
        self.calls.append(("delete", [m.uid for m in msgs]))
    def send(self, out):
        if self.fail: raise self.fail
        self.calls.append(("send", out.subject))
    def search_server(self, text, logicals, known, limit=40):
        self.calls.append(("search", text, tuple(logicals), {k: sorted(v) for k, v in known.items()}))
        return [real_msg(90, "Vieille facture 2019", date=100)]


def win_with(backend=None, n=0):
    w = make_window(max(n, 1))
    w.cache.delete_many([m.id for m in w.cache.query("inbox", limit=500)])
    w.accounts = lambda: [{"id": "acc", "name": "Moi", "email": "moi@x.be"}]
    be = backend or FakeBackend()
    w.backend = lambda aid: be
    sync_run_bg(w)
    w.sync = lambda **k: w.__dict__.setdefault("synced", []).append(k)
    w.reload_list = lambda *a, **k: None
    w.update_counts = lambda: None
    w.srv_btn = gtkstub.D()
    return w, be


def test_conversations_in_list_and_actions_apply_to_the_whole_thread():
    w = make_window(1)
    w.cache.delete_many([m.id for m in w.cache.query("inbox", limit=50)])
    w.cache.upsert_many([real_msg(1, "Projet", account="demo"), real_msg(2, "Re: Projet", refs="<r1@x>", account="demo", unread=False),
                         real_msg(3, "Re: Projet", refs="<r1@x> <r2@x>", account="demo"), real_msg(4, "Autre", account="demo")])
    w.reload_list(full=True)
    assert len(w.rows) == 2                                                          # 2 conversations
    top = [r.msg for r in w.rows.values() if r.msg.subject == "Re: Projet"][0]
    assert top.thread_count == 3 and top.unread is True
    assert {m.id for m in w._expand_threads([top])} == {"r1", "r2", "r3"}
    w.run_action("archive", w._expand_threads([top]))                                 # le swipe / clic droit vaut pour le fil entier
    assert {w.cache.get(i).folder for i in ("r1", "r2", "r3")} == {"archive"} and w.cache.get("r4").folder == "inbox"
    w.config["threads"] = False
    w.reload_list(full=True)
    assert w._expand_threads([top]) == [top]                                          # regroupement désactivé : un seul message


def test_opening_a_thread_marks_it_read_and_lists_the_other_messages():
    w = make_window(1)
    w.cache.delete_many([m.id for m in w.cache.query("inbox", limit=50)])
    w.cache.upsert_many([real_msg(1, "Projet", account="demo"), real_msg(2, "Re: Projet", refs="<r1@x>", account="demo")])
    w.reload_list(full=True)
    row = list(w.rows.values())[0]
    shown = []
    w.reader.show_thread = lambda members, cur: shown.append(([m.id for m in members], cur))
    w.open_message(row.msg, force=True)
    assert shown and set(shown[0][0]) == {"r1", "r2"} and shown[0][1] == "r2"
    assert all(not w.cache.get(i).unread for i in ("r1", "r2"))


def test_offline_actions_are_kept_then_replayed_in_order():
    w, be = win_with()
    msgs = [real_msg(1, "A"), real_msg(2, "B")]
    w.cache.upsert_many(msgs)
    be.fail = BackendError("Connexion IMAP impossible : réseau", retryable=True)
    w._auto_move(msgs, "trash")                                                       # réseau coupé
    assert w.cache.ops_count() == 1 and w.offline is True and be.calls == []
    assert all(w.cache.get(m.id).folder == "trash" for m in msgs)                       # l'interface reste fluide
    be.fail = None
    w.flush_ops()                                                                     # réseau rétabli
    assert w.cache.ops_count() == 0 and be.calls == [("move", [2, 3], "trash")] and w.offline is False
    assert w.synced                                                                   # puis resynchronisation
    be.fail = BackendError("Dossier introuvable")                                      # refus définitif : abandonné, pas de boucle
    w._auto_move([real_msg(7, "C")], "archive")
    assert w.cache.ops_count() == 0


def test_flags_and_permanent_delete_are_queued_too():
    w, be = win_with()
    m = real_msg(1, "A")
    w.cache.upsert_many([m])
    be.fail = ConnectionResetError("coupé")
    w._flag_remote_many([m], seen=True)
    assert w.cache.ops_count() == 1 and w.cache.ops_pending()[0]["kind"] == "flags"
    be.fail = None
    w.flush_ops()
    assert be.calls == [("flags", [2], True, None)] and w.cache.ops_count() == 0


def test_outbox_survives_network_loss_and_is_sent_later():
    w, be = win_with()
    w._sending = set()
    w.cache.outbox_add("o1", time.time() - 1, Outgoing(account="acc", to="p@y.be", subject="Important", html="<p>x</p>"))
    be.fail = BackendError("Envoi impossible : réseau", retryable=True)
    w.process_outbox()
    assert w.cache.outbox_count() == 1 and w.cache.outbox_tries("o1") == 1             # conservé, nouvel essai programmé
    assert w.cache.outbox_due() == []                                                  # pas avant 1 minute
    w.cache.outbox_reschedule("o1", time.time() - 1)
    be.fail = None
    be.demo = True
    w.process_outbox()
    assert w.cache.outbox_count() == 0
    # refus définitif : message rendu à l'utilisateur (pas conservé)
    w.cache.outbox_add("o2", time.time() - 1, Outgoing(account="acc", to="p@y.be", subject="Refusé", html="x"))
    be.fail = BackendError("Envoi impossible : adresse refusée")
    w.process_outbox()
    assert w.cache.outbox_count() == 0 and any("Échec de l'envoi" in t[0] for t in w.__dict__["toasts"])


def test_unsubscribe_one_click_mailto_and_browser_fallback():
    w, be = win_with()
    w._confirm = lambda *a, **k: True
    w._full = lambda m: m
    posted, opened, sent = [], [], []
    orig_post, orig_open = unsub.one_click_post, extras.open_uri
    unsub.one_click_post = lambda url, **k: (posted.append(url), (True, "HTTP 200"))[1]
    extras.open_uri = lambda widget, uri: opened.append(uri)
    w.queue_send = lambda out, delay=0, scheduled=False: sent.append(out)
    try:
        one = real_msg(1, "Promo", unsubscribe="<https://x.be/u?t=1>, <mailto:u@x.be>", unsub_post=True)
        w.unsubscribe(one)
        assert posted == ["https://x.be/u?t=1"] and any("Désabonné" in t[0] for t in w.toasts)
        mail = real_msg(2, "News", unsubscribe="<mailto:stop@x.be?subject=bye&body=ciao>")
        w.unsubscribe(mail)
        assert sent[0].to == "stop@x.be" and sent[0].subject == "bye" and "ciao" in sent[0].html
        web = real_msg(3, "Autre", unsubscribe="<https://x.be/page>")
        w.unsubscribe(web)
        assert opened == ["https://x.be/page"]
        unsub.one_click_post = lambda url, **k: (False, "HTTP 410")                    # refus : bascule sur la page web
        w.unsubscribe(one)
        assert opened[-1] == "https://x.be/u?t=1"
        w._confirm = lambda *a, **k: False                                              # annulation : rien n'est envoyé
        n = len(sent)
        w.unsubscribe(mail)
        assert len(sent) == n
        w.unsubscribe(real_msg(4, "Rien"))
        assert any("ne propose pas" in t[0] for t in w.toasts)
    finally:
        unsub.one_click_post, extras.open_uri = orig_post, orig_open


def test_invitation_reply_uses_the_alias_it_was_sent_to_and_caldav():
    w, be = win_with()
    w._full = lambda m: m
    sent = []
    w.queue_send = lambda out, delay=0, scheduled=False: sent.append(out)
    w.config["identities"] = [{"id": "ident1", "account": "acc", "name": "Société X", "email": "contact@x.be", "signature_html": "<b>X</b>"}]
    inv = {"method": "REQUEST", "uid": "u1@x", "title": "Point projet", "start": "2026-11-12T14:00", "organizer": "marie@y.be",
           "dtstart_raw": "DTSTART:20261112T140000", "dtend_raw": "", "sequence": 0, "raw": "BEGIN:VCALENDAR\r\nMETHOD:REQUEST\r\nEND:VCALENDAR\r\n"}
    m = real_msg(1, "Invitation", to="Société <contact@x.be>", invite=inv)
    w.invite_respond(m, "accept")
    out = sent[0]
    assert out.to == "marie@y.be" and out.subject == "Accepté : Point projet" and out.from_email == "contact@x.be"
    assert "METHOD:REPLY" in out.ics and "PARTSTAT=ACCEPTED" in out.ics and out.ics_method == "REPLY"
    w.invite_respond(real_msg(2, "Invitation", to="moi@x.be", invite=inv), "decline")
    assert sent[1].from_email == "" and "PARTSTAT=DECLINED" in sent[1].ics                 # reçue sur le compte : pas d'alias
    puts = []
    orig = caldav.put_event
    caldav.put_event = lambda url, user, pw, ics, uid: (puts.append((url, user, uid, "METHOD:PUBLISH" in ics)), (True, "HTTP 201"))[1]
    try:
        w.config["caldav"] = {"url": "https://cal.x.be/dav/perso/", "user": "moi"}
        w.invite_add(m)
        assert puts == [("https://cal.x.be/dav/perso/", "moi", "u1@x", True)]
        assert any("Ajouté à votre agenda" in t[0] for t in w.toasts)
    finally:
        caldav.put_event = orig


def test_server_search_adds_unknown_messages_and_reports():
    w, be = win_with()
    w._effective_search = lambda: "facture"
    w.view = "inbox"
    w.cache.upsert_many([real_msg(1, "Connu")])
    w.search_server_now()
    call = [c for c in be.calls if c[0] == "search"][0]
    assert call[1] == "facture" and call[2] == ("inbox", "sent", "archive") and call[3]["inbox"] == [2]    # UID déjà connus transmis
    assert w.cache.get("r90") is not None and any("1 message(s) supplémentaire" in t[0] for t in w.toasts)
    w.view = "f:Clients"
    w.search_server_now()
    assert [c for c in be.calls if c[0] == "search"][1][2][-1] == "f:Clients"            # le dossier courant est aussi cherché


def test_learning_suggests_then_proposes_a_rule_on_third_move():
    w, be = win_with()
    w.engine = AIEngine(w.config, w.cache)
    w.config.data.update(ai_enabled=True, ai_has_key=True)
    w.config.set_password("ai:nvidia", "nvapi")
    w.ai_rule_move = lambda msg, folder: w.__dict__.setdefault("rules_made", []).append((msg.sender_email, folder))
    ms = [real_msg(i, "Facture %d" % i, sender="compta@x.be") for i in range(1, 5)]
    w.cache.upsert_many(ms)
    w._learn_move(ms[:1], "f:Factures", "Factures")
    assert w.cache.learn_best("acc", "compta@x.be") is None                              # une fois : pas encore une habitude
    w._learn_move(ms[1:2], "f:Factures", "Factures")
    assert w.cache.learn_best("acc", "compta@x.be") == "Factures"
    labels = [i[0] for i in w.ai_menu_items(ms[2]) if i and i[0] != "sous-menu"]
    assert "✨ Ranger dans « Factures » (selon vos habitudes) " .strip() in labels
    w.toasts = []
    w._learn_move(ms[2:3], "f:Factures", "Factures")                                       # 3e fois : propose une règle
    t = [x for x in w.toasts if "rangez souvent" in x[0]]
    assert t and t[0][1] == "Créer la règle"
    t[0][2]()
    assert w.rules_made == [("compta@x.be", "Factures")]
    w._learn_move(ms[3:4], "archive", "Archives")                                           # dossiers spéciaux : jamais appris
    assert w.cache.learn_best("acc", "compta@x.be") == "Factures"


def test_identities_choice_and_contacts_storage_and_sync():
    w, be = win_with()
    w.config["identities"] = [{"id": "ident1", "account": "acc", "name": "Pro", "email": "pro@x.be", "signature_html": ""}]
    m = real_msg(1, "Hello", to="Pro <pro@x.be>, autre@y.be")
    assert w._from_choice(m) == "ident:ident1" and w._addressed_identity(m)["email"] == "pro@x.be"
    assert w._from_choice(real_msg(2, "Hello", to="moi@x.be")) == w._default_account(real_msg(2, "x"))
    composed = []
    w.compose = lambda **kw: composed.append(kw)
    w._full = lambda msg: msg
    w._quote = lambda msg: ""
    w.reply(m)
    assert composed[0]["account_id"] == "ident:ident1"
    # contacts : fiche manuelle -> configuration (synchronisée) + base locale
    assert w.contact_save("Marie@X.be", "Marie", "+32 475", "Alpha", "VIP") and not w.contact_save("pas-une-adresse")
    assert w.config["contacts"]["marie@x.be"]["org"] == "Alpha" and w.cache.contacts_list(source="manual")[0]["phone"] == "+32 475"
    w.config["identities"].append({"id": "ident2", "account": "acc99999", "name": "Pro 2", "email": "pro2@x.be", "signature_html": "<i>sig</i>"})
    items = syncdata.collect(w.config)
    assert "ident:ident2" in items and "contact:marie@x.be" in items
    wire = syncdata.to_wire(syncdata.local_items(w.config))
    assert syncdata.valid_item("ident:ident2", wire["ident:ident2"]) and syncdata.valid_item("contact:marie@x.be", wire["contact:marie@x.be"])
    bad = dict(wire["ident:ident2"], v=dict(wire["ident:ident2"]["v"], email="pas une adresse"))
    assert not syncdata.valid_item("ident:ident2", bad)
    assert not syncdata.valid_item("contact:marie@x.be", {"v": {"name": "x", "evil": "y"}, "ts": 1.0, "del": False})
    other_cfg, other_cache = Config(os.path.join(gtkstub.tmp, "other.json")), Cache(os.path.join(gtkstub.tmp, "other.db"))
    wins = syncdata.merge_items({}, wire)
    res = syncdata.apply_items(other_cfg, wins, other_cache)
    assert other_cfg["identities"][0]["email"] == "pro2@x.be" and other_cfg["contacts"]["marie@x.be"]["name"] == "Marie"
    assert other_cache.contacts_list(source="manual")[0]["email"] == "marie@x.be" and "identité(s)" in syncdata.describe(res)
    w.contact_remove("marie@x.be")
    assert "marie@x.be" not in w.config["contacts"] and not w.cache.contacts_list(source="manual")
    # nouveaux réglages synchronisables, avec contrôle strict
    ok = syncdata.SYNC_SETTINGS
    assert ok["ai_provider"]("ollama") and not ok["ai_provider"]("autre") and ok["threads"](False)
    assert ok["nvidia_api_base"]("http://localhost:11434/v1") and not ok["nvidia_api_base"]("http://exemple.com/v1")
    assert ok["oauth_clients"]({"google": {"client_id": "x"}}) and not ok["oauth_clients"]({"evil": {}})
    assert ok["caldav"]({"url": "https://c.x.be/dav", "user": "u"}) and not ok["caldav"]({"url": "http://exemple.com/dav"})
    acct = {"id": "acc9999", "email": "a@gmail.com", "imap_host": "imap.gmail.com", "imap_port": 993, "smtp_host": "smtp.gmail.com", "smtp_port": 587,
            "auth": "oauth2", "oauth_provider": "google", "password": "REFRESH"}
    assert syncdata.clean_account(acct)["oauth_provider"] == "google" and "auth" not in syncdata.clean_account(dict(acct, oauth_provider="evil"))
