"""Épingles : enregistrées SUR LA BOÎTE (mot-clé IMAP) pour être vues par les autres postes ; serveurs qui refusent les mots-clés ; migration des anciennes épingles."""
import imaplib, os, sys, time, types
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import testenv  # noqa: F401
from test_backend import RAW, msgs
from mintmail import backend as B, offline
from mintmail.backend import IMAPBackend, PinUnsupported, PIN_KEYWORD, parse_message


class Server:
    """Boîte IMAP partagée par plusieurs « postes » ; keywords_ok=False imite Gmail : les mots-clés personnalisés sont ignorés en silence."""
    def __init__(self, keywords_ok=True, n=5, gmail=False):
        self.keywords_ok = keywords_ok
        self.gmail = gmail                                    # Gmail : étiquettes X-GM-LABELS (et mots-clés personnalisés ignorés)
        self.flags = {u: set() for u in range(1, n + 1)}
        self.labels = {u: {"\\Inbox"} for u in range(1, n + 1)}
        self.log = []


def _labels_text(srv, u):
    return " ".join('"%s"' % l.replace("\\", "\\\\") if (l.startswith("\\") or " " in l) else l for l in sorted(srv.labels[u]))


class Conn:
    def __init__(self, srv):
        self.srv = srv
        self.capabilities = ("MOVE", "X-GM-EXT-1") if srv.gmail else ("MOVE",)

    def noop(self): return "OK", []
    def logout(self): pass
    def expunge(self): pass
    def select(self, name, readonly=False): return "OK", [b"1"]
    def list(self):
        extra = [b'(\\HasNoChildren) "/" "MintMail-Epingles"', b'(\\HasNoChildren) "/" "Clients"'] if self.srv.gmail else []
        return "OK", [b'(\\HasNoChildren) "/" "INBOX"'] + extra

    def uid(self, cmd, *a):
        s = self.srv
        s.log.append((cmd,) + a)
        if cmd == "SEARCH":
            kind = a[1] if len(a) > 1 else "ALL"
            if kind == "KEYWORD":
                hit = [u for u in sorted(s.flags) if a[2] in s.flags[u]]
            elif kind == "X-GM-RAW":
                if not s.gmail:
                    raise imaplib.IMAP4.error("BAD X-GM-RAW")
                hit = [u for u in sorted(s.flags) if a[2].strip('"').split(":", 1)[1] in {l.lower() for l in s.labels[u]}]
            else:
                hit = sorted(s.flags)
            return "OK", [" ".join(str(u) for u in hit).encode()]
        if cmd == "STORE":
            ids, op, fl = a
            if "X-GM-LABELS" in op:
                if not s.gmail:
                    raise imaplib.IMAP4.error("BAD X-GM-LABELS")           # un serveur non-Gmail ne connaît pas l'extension : on ne doit JAMAIS la demander
                for u in ids.split(","):
                    for lab in fl.strip("()").split():
                        (s.labels[int(u)].add if op == "+X-GM-LABELS" else s.labels[int(u)].discard)(lab)
                return "OK", []
            for u in ids.split(","):
                for f in fl.strip("()").split():
                    if f.startswith("$") and (not s.keywords_ok or s.gmail):
                        continue                                    # Gmail / serveur incapable : ignoré, sans erreur
                    (s.flags[int(u)].add if op == "+FLAGS" else s.flags[int(u)].discard)(f)
            return "OK", []
        if cmd == "FETCH":
            want_labels = "X-GM-LABELS" in a[1]
            if want_labels and not s.gmail:
                raise imaplib.IMAP4.error("BAD X-GM-LABELS")
            out = []
            for u in a[0].split(","):
                lab = " X-GM-LABELS (%s)" % _labels_text(s, int(u)) if want_labels else ""
                if "BODY.PEEK" in a[1]:
                    raw = RAW % (int(u), int(u))
                    out += [(("%s (%sUID %s FLAGS (%s) BODY[] {%d}" % (u, lab.strip() + " " if lab else "", u, " ".join(sorted(s.flags[int(u)])), len(raw))).encode(), raw), b")"]
                else:
                    out.append(("%s (UID %s FLAGS (%s)%s)" % (u, u, " ".join(sorted(s.flags[int(u)])), lab)).encode())
            return "OK", out
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


def test_queued_actions_stay_compatible_and_the_palette_and_docs_mention_the_pin_command():
    calls = []
    be = types.SimpleNamespace(demo=False, set_flags_many=lambda items, **kw: calls.append(kw))
    fake = types.SimpleNamespace(backend=lambda aid: be)
    offline.OfflineMixin._op_exec(fake, {"account": "a", "kind": "flags", "payload": {"seen": True, "items": [{"id": "x", "uid": 1, "real": "INBOX"}]}})
    offline.OfflineMixin._op_exec(fake, {"account": "a", "kind": "flags", "payload": {"pinned": True, "probe": True, "items": [{"id": "x", "uid": 1, "real": "INBOX"}]}})
    assert calls == [{"seen": True, "flagged": None}, {"seen": None, "flagged": None, "pinned": True, "probe": True}]      # anciennes actions : appel inchangé
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    aide, help_en = (open(os.path.join(root, "docs", n), encoding="utf-8").read() for n in ("AIDE.md", "HELP.md"))
    assert "enregistrée sur la boîte" in aide and "Envoyer mes épingles vers la boîte" in aide                    # aide française
    assert "stored on the mailbox" in help_en and "Send my pins to the mailbox" in help_en                         # aide anglaise


# ======================================================================= 1.14.1 : Gmail (étiquettes), diagnostic réel du serveur
def test_gmail_label_parser_handles_quotes_parentheses_backslashes_and_only_our_label_counts():
    from mintmail.backend import _gm_labels, _flagset, PIN_KEYWORD_LOW
    raw = b'5 (X-GM-LABELS ("\\\\Inbox" "Travail (ancien)" "Clients \\"VIP\\"" MintMail-Epingles) UID 5 FLAGS (\\Seen))'
    assert _gm_labels(raw) == ["\\Inbox", "Travail (ancien)", 'Clients "VIP"', "MintMail-Epingles"]
    assert PIN_KEYWORD_LOW in _flagset(raw) and "\\seen" in _flagset(raw)                          # l'étiquette vaut épingle ; les drapeaux normaux restent lus
    assert PIN_KEYWORD_LOW not in _flagset(b'5 (X-GM-LABELS ("MintMail-Epingles2" "x") UID 5 FLAGS ())')
    assert PIN_KEYWORD_LOW in _flagset(b'5 (X-GM-LABELS ("mintmail-EPINGLES") UID 5 FLAGS ())')       # casse indifférente
    assert _gm_labels(b"5 (UID 5 FLAGS ())") == [] and _gm_labels(None) == [] and _gm_labels(b'X-GM-LABELS (')[:1] == []
    assert PIN_KEYWORD_LOW not in _flagset(b'5 (UID 5 FLAGS (\\Seen))')


def test_on_gmail_pinning_is_a_label_visible_in_gmail_and_other_workstations_see_it():
    srv = Server(gmail=True)
    a, b = station(srv), station(srv)
    a.set_flags_many(msgs([2, 3]), pinned=True)
    assert stores(srv)[0] == ("STORE", "2,3", "+X-GM-LABELS", "(MintMail-Epingles)")                  # étiquette Gmail, pas de mot-clé
    assert "MintMail-Epingles" in srv.labels[2] and "MintMail-Epingles" in srv.labels[3] and not any(PIN_KEYWORD in f for f in srv.flags.values())
    assert a.acc["pin_server"] is True and a.acc["pin_mode"] == "gmail" and a._pin_dirty
    known = {u: "id%d" % u for u in (2, 3, 4)}
    _, flags, _, _ = b.sync("inbox", known, limit=20)
    assert flags[2][2] is True and flags[3][2] is True and flags[4][2] is None                        # B voit les épingles de A (et apprend que le serveur est fiable)
    _, flags, _, _ = b.sync("inbox", known, limit=20)
    assert flags[4][2] is False
    a.set_flags_many(msgs([2]), pinned=False)
    assert "MintMail-Epingles" not in srv.labels[2] and "\\Inbox" in srv.labels[2]                      # le retrait ne touche pas aux autres étiquettes
    _, flags, _, _ = b.sync("inbox", known, limit=20)
    assert flags[2][2] is False and flags[3][2] is True
    srv.labels[7] = {"\\Inbox", "MintMail-Epingles"}
    srv.flags[7] = set()
    res, _, _, _ = station(srv).sync("inbox", {}, limit=20)
    assert [m.pinned for m in res if m.uid == 7] == [True] and [m.pinned for m in res if m.uid == 1] == [False]     # un message nouveau arrive déjà épinglé
    cmds = [e for e in srv.log if e[0] == "FETCH"]
    assert cmds and all("X-GM-LABELS" in e[2] for e in cmds)                                           # sur Gmail les étiquettes sont toujours demandées


def test_the_technical_label_is_hidden_from_the_folder_list_and_other_servers_never_get_gmail_commands():
    srv = Server(gmail=True)
    names = [f["name"] for f in station(srv).list_folders()]
    assert "INBOX" in names and "Clients" in names and "MintMail-Epingles" not in names               # visible dans Gmail, pas dans la liste des dossiers de MintMail
    plain = Server()
    be = station(plain)
    be.set_flags_many(msgs([2]), pinned=True)                                                          # le faux serveur LÈVE une erreur si on lui parle Gmail
    be.sync("inbox", {2: "x"}, limit=20)
    be.sync("inbox", {}, limit=20)
    assert not any("X-GM" in str(e) for e in plain.log) and PIN_KEYWORD in plain.flags[2]


def test_gmail_that_somehow_drops_the_label_is_detected_like_any_other_unsupported_server():
    srv = Server(gmail=True)
    be = station(srv)
    orig = Conn.uid

    def silent(self, cmd, *a):
        if cmd == "STORE" and "X-GM-LABELS" in a[1]:
            return "OK", []                                                                            # accepté mais non conservé
        return orig(self, cmd, *a)
    Conn.uid = silent
    try:
        try:
            be.set_flags_many(msgs([2]), pinned=True)
            assert False
        except PinUnsupported:
            pass
    finally:
        Conn.uid = orig
    assert be.acc["pin_server"] is False


def test_pin_diagnostic_gives_a_real_verdict_for_keyword_gmail_and_unsupported_servers_and_always_cleans_up():
    for kwargs, mode, supported in (({}, "keyword", True), ({"gmail": True}, "gmail", True), ({"keywords_ok": False}, "keyword", False)):
        srv = Server(**kwargs)
        d = station(srv).pin_diagnostic()
        assert d["connected"] and d["mode"] == mode and d["tested"] and d["supported"] is supported and d["error"] == "", (kwargs, d)
        assert d["count"] == 0
        assert PIN_KEYWORD not in srv.flags[5] and "MintMail-Epingles" not in srv.labels[5]            # essai réversible : plus rien sur le message
        assert stores(srv)[-1][2] in ("-FLAGS", "-X-GM-LABELS")                                         # le retrait est toujours émis
    srv = Server()
    srv.flags[3].add(PIN_KEYWORD)
    d = station(srv).pin_diagnostic(test=False)
    assert d["count"] == 1 and d["tested"] is False and d["supported"] is None and stores(srv) == []   # lecture seule : AUCUNE modification
    empty = Server(n=0)
    d = station(empty).pin_diagnostic()
    assert d["connected"] and d["tested"] is False and stores(empty) == []
    bad = station(Server())
    bad._connect = lambda: (_ for _ in ()).throw(OSError("réseau coupé"))
    d = bad.pin_diagnostic()
    assert d["connected"] is False and "réseau coupé" in d["error"]
    srv = Server()
    be = station(srv, id="acc")
    original = be.acc
    be.pin_diagnostic()
    assert be.acc.get("pin_server") is True                                                            # le diagnostic apprend l'état dans la COPIE du compte qu'on lui donne
    assert original is be.acc


def test_check_pins_command_reports_each_account_and_exit_codes():
    from mintmail import entry
    servers = {"g": Server(gmail=True), "k": Server(), "x": Server(keywords_ok=False)}
    made = []

    def factory(acc, cfg):
        be = station(servers[acc["id"]], id=acc["id"])
        be.closed = False
        be.close = lambda: made.append(acc["id"])
        return be
    cfg = {"accounts": [{"id": "g", "email": "moi@gmail.com"}, {"id": "k", "email": "moi@saec.me"}, {"id": "x", "email": "moi@outlook.com"}, {"id": "demo", "demo": True, "email": "demo@x"}]}
    lines = []
    code = entry.check_pins_cli(out=lines.append, cfg=cfg, factory=factory)
    text = "\n".join(lines)
    assert code == 1 and made == ["g", "k", "x"] and "demo@x" not in text                              # un compte ne garde pas les épingles → code 1 ; démo ignoré
    assert "== moi@gmail.com" in text and "étiquette « MintMail-Epingles »" in text and "IMAP standard" in text
    assert text.count("RÉUSSI") == 2 and text.count("ÉCHEC") == 1 and "Connexion : OK" in text
    assert [l for l in lines if "Messages épinglés" in l] == ["Messages épinglés sur le serveur (boîte de réception) : 0"] * 3
    ok_only = {"accounts": [cfg["accounts"][0], cfg["accounts"][1]]}
    assert entry.check_pins_cli(out=lambda s: None, cfg=ok_only, factory=factory) == 0
    ro = []
    entry.check_pins_cli(test=False, out=ro.append, cfg=ok_only, factory=factory)
    assert any("Lecture seule" in l for l in ro) and not any("RÉUSSI" in l for l in ro)
    none = []
    assert entry.check_pins_cli(out=none.append, cfg={"accounts": [{"id": "demo", "demo": True}]}, factory=factory) == 1 and "Aucun compte" in none[0]
    down = lambda acc, cfg: (lambda b: (setattr(b, "_connect", lambda: (_ for _ in ()).throw(OSError("coupé"))), b)[1])(station(Server(), id=acc["id"]))
    out2 = []
    assert entry.check_pins_cli(out=out2.append, cfg=ok_only, factory=down) == 1 and any("Connexion impossible" in l and "coupé" in l for l in out2)
    seen = []
    old = entry.check_pins_cli
    entry.check_pins_cli = lambda **k: (seen.append(k), 0)[1]
    try:
        assert entry.main(["mintmail", "--check-pins", "--no-test"]) == 0 and seen == [{"test": False}]
        entry.main(["mintmail", "--check-pins"])
        assert seen[-1] == {"test": True}
    finally:
        entry.check_pins_cli = old
