"""Épingles : enregistrées SUR LA BOÎTE (mot-clé IMAP) pour être vues par les autres postes ; serveurs qui refusent les mots-clés ; migration des anciennes épingles."""
import os, sys, time, types
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gtkstub
from test_listing import make_window
from test_backend import RAW, msgs
from mintmail import backend as B, offline
from mintmail.backend import IMAPBackend, PinUnsupported, PIN_KEYWORD, parse_message
from mintmail.models import Message
from mintmail.store import Cache, Config


class Server:
    """Boîte IMAP partagée par plusieurs « postes » ; keywords_ok=False imite Gmail : les mots-clés personnalisés sont ignorés en silence."""
    def __init__(self, keywords_ok=True, n=5):
        self.keywords_ok = keywords_ok
        self.flags = {u: set() for u in range(1, n + 1)}
        self.log = []


class Conn:
    capabilities = ("MOVE",)

    def __init__(self, srv):
        self.srv = srv

    def noop(self): return "OK", []
    def logout(self): pass
    def expunge(self): pass
    def select(self, name, readonly=False): return "OK", [b"1"]
    def list(self): return "OK", [b'(\\HasNoChildren) "/" "INBOX"']

    def uid(self, cmd, *a):
        s = self.srv
        s.log.append((cmd,) + a)
        if cmd == "SEARCH":
            return "OK", [" ".join(str(u) for u in sorted(s.flags)).encode()]
        if cmd == "STORE":
            ids, op, fl = a
            for u in ids.split(","):
                for f in fl.strip("()").split():
                    if f.startswith("$") and not s.keywords_ok:
                        continue                                    # Gmail : ignoré, sans erreur
                    (s.flags[int(u)].add if op == "+FLAGS" else s.flags[int(u)].discard)(f)
            return "OK", []
        if cmd == "FETCH" and "BODY.PEEK" in a[1]:
            out = []
            for u in a[0].split(","):
                raw = RAW % (int(u), int(u))
                out += [(("%s (UID %s FLAGS (%s) BODY[] {%d}" % (u, u, " ".join(sorted(s.flags[int(u)])), len(raw))).encode(), raw), b")"]
            return "OK", out
        if cmd == "FETCH":
            return "OK", [("%s (UID %s FLAGS (%s))" % (u, u, " ".join(sorted(s.flags[int(u)])))).encode() for u in a[0].split(",")]
        return "OK", []


def station(srv, **acc):
    be = IMAPBackend(dict({"id": "acc", "email": "me@x.be", "imap_host": "h", "imap_port": 993, "smtp_host": "h", "smtp_port": 587}, **acc), "pw")
    be._connect = lambda: Conn(srv)
    return be


def stores(srv):
    return [e for e in srv.log if e[0] == "STORE"]


def test_pinning_writes_a_keyword_on_the_mailbox_and_proves_the_server_keeps_it():
    srv = Server()
    be = station(srv)
    srv.flags[2].add("\\Seen")
    be.set_flags_many(msgs([2, 3]), pinned=True)
    assert stores(srv) == [("STORE", "2,3", "+FLAGS", "(%s)" % PIN_KEYWORD)]                    # l'épingle est sur la boîte
    assert PIN_KEYWORD in srv.flags[2] and PIN_KEYWORD in srv.flags[3] and "\\Seen" in srv.flags[2]
    assert be.acc["pin_server"] is True and be._pin_dirty is True                                # preuve par relecture, mémorisée
    n_fetch = len([e for e in srv.log if e[0] == "FETCH"])
    be.set_flags_many(msgs([4]), pinned=True)
    assert len([e for e in srv.log if e[0] == "FETCH"]) == n_fetch                               # une fois prouvé : plus de relecture
    be.set_flags_many(msgs([2]), pinned=False)
    assert PIN_KEYWORD not in srv.flags[2] and PIN_KEYWORD in srv.flags[3] and "\\Seen" in srv.flags[2]       # désépingler n'enlève que le mot-clé
    be.set_flags_many(msgs([2]), seen=True, flagged=True)
    assert stores(srv)[-2:] == [("STORE", "2", "+FLAGS", "(\\Seen)"), ("STORE", "2", "+FLAGS", "(\\Flagged)")]   # lu / favori : comportement inchangé
    assert PIN_KEYWORD not in srv.flags[2]


def test_a_second_workstation_sees_pins_and_unpins_made_on_the_first():
    srv = Server()
    a, b = station(srv), station(srv)
    a.set_flags_many(msgs([2]), pinned=True)
    known = {u: "id%d" % u for u in (2, 3, 4)}
    _, flags, _, _ = b.sync("inbox", known, limit=20)
    assert flags[2][2] is True and flags[3][2] is None and flags[4][2] is None                    # B ignore encore si le serveur est fiable : il ne touche pas à ses épingles locales
    assert b.acc["pin_server"] is True                                                           # …mais vient de l'apprendre en voyant l'épingle de A
    _, flags, _, _ = b.sync("inbox", known, limit=20)
    assert flags[2][2] is True and flags[3][2] is False                                           # désormais l'absence du mot-clé signifie « pas épinglé »
    a.set_flags_many(msgs([2]), pinned=False)
    _, flags, _, _ = b.sync("inbox", known, limit=20)
    assert flags[2][2] is False                                                                   # le désépinglage de A arrive sur B
    srv.flags[7] = {PIN_KEYWORD.upper(), "\\Seen"}                                                # un message NOUVEAU déjà épinglé (casse quelconque) arrive épinglé
    c = station(srv)
    res, _, _, _ = c.sync("inbox", {}, limit=20)
    assert [m.pinned for m in res if m.uid == 7] == [True]


def test_a_server_that_refuses_custom_keywords_is_detected_never_pretended_and_can_be_retried():
    srv = Server(keywords_ok=False)
    be = station(srv)
    try:
        be.set_flags_many(msgs([2]), pinned=True)
        assert False, "devait refuser"
    except PinUnsupported as e:
        assert "reste sur ce poste" in str(e) and e.retryable is False                            # message clair, jamais réessayé en boucle
    assert be.acc["pin_server"] is False
    n = len(srv.log)
    try:
        be.set_flags_many(msgs([3]), pinned=True)
        assert False
    except PinUnsupported:
        pass
    assert srv.log[n:] == []                                                                       # déjà constaté : aucun trafic inutile
    be.set_flags_many(msgs([3]), pinned=False)                                                     # désépingler ne lève jamais d'erreur
    _, flags, _, _ = be.sync("inbox", {2: "x"}, limit=20)
    assert flags[2][2] is None                                                                     # jamais d'effacement des épingles locales sur un serveur incapable
    srv.keywords_ok = True                                                                         # le serveur a évolué : la commande « Envoyer mes épingles » refait l'essai
    be.set_flags_many(msgs([2]), pinned=True, probe=True)
    assert be.acc["pin_server"] is True and PIN_KEYWORD in srv.flags[2]


def test_sync_applies_the_mailbox_pins_but_never_overwrites_a_pending_local_action_or_an_unknown_server():
    w = make_window(10)
    cache = w.cache
    cache.upsert_many([Message(id="p%d" % i, account="acc", folder="inbox", real_folder="INBOX", uid=i, pinned=(i == 3), date=1000 + i) for i in (1, 2, 3, 4)])
    kn = {i: "p%d" % i for i in (1, 2, 3, 4)}
    cache.ops_add("acc", "flags", {"pinned": True, "items": [{"id": "p4", "uid": 4, "real": "INBOX"}]})            # l'épingle de p4 n'est pas encore partie
    cache.ops_add("acc", "flags", {"seen": True, "items": [{"id": "p1", "uid": 1, "real": "INBOX"}]})               # une action SANS épingle ne protège rien
    assert w._pending_pin_ids() == {"p4"}
    w._apply_server_flags(kn, {1: (False, False, True), 2: (True, True, None), 3: (True, False, False), 4: (False, False, False)})
    got = {i: cache.get_light("p%d" % i) for i in (1, 2, 3, 4)}
    assert got[1].pinned is True and got[1].unread is False                                         # épinglé sur la boîte → épinglé ici
    assert got[2].pinned is False and got[2].starred is True                                        # serveur inconnu : état local gardé (ici non épinglé), favori mis à jour
    assert got[3].pinned is False                                                                    # désépinglé ailleurs → désépinglé ici (serveur prouvé)
    assert got[4].pinned is False and True                                                           # p4 : action locale en attente
    w._apply_server_flags(kn, {2: (True, True)})                                                     # ancien format à 2 éléments : toujours accepté
    assert cache.get_light("p2").pinned is False


def test_legacy_local_pins_are_pushed_once_to_the_mailbox_when_the_server_is_proven_and_a_toast_reports_it():
    srv = Server()
    a, b = station(srv), station(srv)
    w = make_window(11)
    cache = w.cache
    cache.upsert_many([Message(id="acc|INBOX|%d" % i, account="acc", folder="inbox", real_folder="INBOX", uid=i, pinned=(i in (3, 4)), date=1000 + i) for i in (2, 3, 4)])
    w._backends = {"acc": b}
    w.accounts = lambda: [{"id": "acc"}]
    w.backend = lambda aid: b
    w.op_enqueue = lambda kind, lst, **kw: [cache.ops_add("acc", kind, dict(kw, items=[{"id": m.id, "uid": m.uid, "real": m.real_folder} for m in lst]))]
    w.run_bg = lambda fn, done=None: done(fn(), None) if done else fn()
    w._set_offline = lambda off: None
    w.op_run = lambda ops: offline.OfflineMixin.op_run(w, ops)
    w._op_exec = lambda op: offline.OfflineMixin._op_exec(w, op)
    w.config["pins_pushed"] = []
    w._save_pin_states()
    assert srv.flags[3] == set() and w.config["pins_pushed"] == []                                  # serveur pas encore prouvé : rien n'est envoyé
    a.set_flags_many(msgs([2]), pinned=True)
    b.sync("inbox", {2: "acc|INBOX|2"}, limit=20)                                                   # B voit l'épingle de A et apprend que le serveur sait les garder
    w._save_pin_states()
    assert PIN_KEYWORD in srv.flags[3] and PIN_KEYWORD in srv.flags[4]                              # ses anciennes épingles locales partent vers la boîte
    assert w.config["pins_pushed"] == ["acc"]
    sent = len(stores(srv))
    w._save_pin_states()
    assert len(stores(srv)) == sent                                                                  # une seule fois par compte
    _, flags, _, _ = a.sync("inbox", {3: "x", 4: "y"}, limit=20)
    assert flags[3][2] is True and flags[4][2] is True                                              # l'autre poste les voit maintenant
    w.toasts = []
    w.push_local_pins()
    assert w.toasts and "épingle(s) envoyée(s)" in w.toasts[-1][0] and "2" in w.toasts[-1][0]        # commande manuelle : résumé
    cache.update_many(["acc|INBOX|3", "acc|INBOX|4"], pinned=False)
    w.toasts = []
    w.push_local_pins()
    assert w.toasts and "Aucun message épinglé" in w.toasts[-1][0]


def test_pinning_in_the_list_goes_to_the_mailbox_through_the_offline_queue_and_a_refusing_server_is_reported_once():
    srv = Server(keywords_ok=False)
    be = station(srv)
    w = make_window(12)
    cache = w.cache
    m = Message(id="acc|INBOX|2", account="acc", folder="inbox", real_folder="INBOX", uid=2, date=1000)
    cache.upsert_many([m])
    w.backend = lambda aid: be
    w.op_enqueue = lambda kind, lst, **kw: [cache.ops_add("acc", kind, dict(kw, items=[{"id": x.id, "uid": x.uid, "real": x.real_folder} for x in lst]))]
    w.run_bg = lambda fn, done=None: done(fn(), None) if done else fn()
    w._set_offline = lambda off: None
    w._op_exec = lambda op: offline.OfflineMixin._op_exec(w, op)
    w.op_run = lambda ops: offline.OfflineMixin.op_run(w, ops)
    w._save_pin_states = lambda: None
    w.toasts = []
    w.set_flag([m], "pinned", True)
    assert cache.get_light(m.id).pinned is True                                                      # l'épingle locale est faite quoi qu'il arrive
    assert len(w.toasts) == 1 and "reste sur ce poste" in w.toasts[0][0]                             # le serveur refuse : on le DIT
    w.set_flag([m], "pinned", False)
    w.set_flag([m], "pinned", True)
    assert len(w.toasts) == 1                                                                         # une seule alerte par session
    srv2 = Server()
    be2 = station(srv2)
    w2 = make_window(13)
    m2 = Message(id="acc|INBOX|3", account="acc", folder="inbox", real_folder="INBOX", uid=3, date=1000)
    w2.cache.upsert_many([m2])
    w2.backend = lambda aid: be2
    w2.op_enqueue = lambda kind, lst, **kw: [w2.cache.ops_add("acc", kind, dict(kw, items=[{"id": x.id, "uid": x.uid, "real": x.real_folder} for x in lst]))]
    w2.run_bg = lambda fn, done=None: done(fn(), None) if done else fn()
    w2._set_offline = lambda off: None
    w2._op_exec = lambda op: offline.OfflineMixin._op_exec(w2, op)
    w2.op_run = lambda ops: offline.OfflineMixin.op_run(w2, ops)
    w2._save_pin_states = lambda: None
    w2.toasts = []
    w2.set_flag([m2], "pinned", True)
    assert PIN_KEYWORD in srv2.flags[3] and not w2.toasts and w2.cache.ops_pending() == []         # serveur capable : épinglé sur la boîte, file vide, aucune alerte


def test_queued_actions_stay_compatible_and_the_palette_and_docs_mention_the_pin_command():
    calls = []
    be = types.SimpleNamespace(demo=False, set_flags_many=lambda items, **kw: calls.append(kw))
    fake = types.SimpleNamespace(backend=lambda aid: be)
    offline.OfflineMixin._op_exec(fake, {"account": "a", "kind": "flags", "payload": {"seen": True, "items": [{"id": "x", "uid": 1, "real": "INBOX"}]}})
    offline.OfflineMixin._op_exec(fake, {"account": "a", "kind": "flags", "payload": {"pinned": True, "probe": True, "items": [{"id": "x", "uid": 1, "real": "INBOX"}]}})
    assert calls == [{"seen": True, "flagged": None}, {"seen": None, "flagged": None, "pinned": True, "probe": True}]      # anciennes actions : appel inchangé
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(root, "mintmail", "window.py"), encoding="utf-8").read()
    assert 'tr("Envoyer mes épingles vers la boîte")' in src and "self._apply_server_flags(kn, flags)" in src
    aide, help_en = (open(os.path.join(root, "docs", n), encoding="utf-8").read() for n in ("AIDE.md", "HELP.md"))
    assert "enregistrée sur la boîte" in aide and "Envoyer mes épingles vers la boîte" in aide                    # aide française
    assert "stored on the mailbox" in help_en and "Send my pins to the mailbox" in help_en                         # aide anglaise
