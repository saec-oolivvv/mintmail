"""Backend : OAuth (XOAUTH2), identités d'envoi, réponses d'invitation, erreurs rejouables, recherche serveur, analyse des messages."""
import base64, os, smtplib, sys, tempfile
tmp = tempfile.mkdtemp()
os.environ["XDG_DATA_HOME"] = tmp
os.environ["XDG_CONFIG_HOME"] = tmp
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mintmail import backend as B, oauth
from mintmail.models import Outgoing
from mintmail.store import Config
from test_backend import FakeIMAP, backend

ACC = {"id": "a1", "name": "Moi", "email": "moi@x.be", "imap_host": "imap.x.be", "imap_port": 993, "smtp_host": "smtp.x.be", "smtp_port": 587}


def test_oauth_accounts_use_xoauth2_for_imap_and_smtp():
    cfg = Config(os.path.join(tmp, "o.json"))
    cfg.data["oauth_clients"] = {"google": {"client_id": "CID"}}
    cfg.set_password("a1", "RT")
    seen = {}
    orig = oauth.refresh_access_token
    oauth.refresh_access_token = lambda *a, **k: {"access_token": "AT-OK", "expires_in": 3600}
    try:
        be = B.make_backend(dict(ACC, auth="oauth2", oauth_provider="google"), cfg)
        assert be.token_provider and be.password == ""

        class IM:
            def authenticate(self, mech, cb): seen["imap"] = (mech, cb(None))
            def login(self, *a): seen["login"] = a
        orig_ssl = B.imaplib.IMAP4_SSL
        B.imaplib.IMAP4_SSL = lambda *a, **k: IM()
        try:
            be._connect()
        finally:
            B.imaplib.IMAP4_SSL = orig_ssl
        assert seen["imap"] == ("XOAUTH2", b"user=moi@x.be\x01auth=Bearer AT-OK\x01\x01") and "login" not in seen

        class SM:
            def __init__(self, *a, **k): pass
            def starttls(self, **k): pass
            def ehlo(self): pass
            def docmd(self, cmd, arg): seen["smtp"] = (cmd, arg); return 235, b"ok"
        orig_smtp = B.smtplib.SMTP
        B.smtplib.SMTP = SM
        try:
            be._smtp()
        finally:
            B.smtplib.SMTP = orig_smtp
        assert seen["smtp"][0] == "AUTH" and base64.b64decode(seen["smtp"][1].split()[1]) == b"user=moi@x.be\x01auth=Bearer AT-OK\x01\x01"
        # compte ordinaire : mot de passe
        be2 = B.make_backend(dict(ACC), cfg)
        assert be2.token_provider is None
    finally:
        oauth.refresh_access_token = orig


class FakeSMTP:
    sent = []
    fail = None

    def __init__(self, *a, **k): pass
    def starttls(self, **k): pass
    def login(self, *a): pass
    def quit(self): pass
    def send_message(self, em, from_addr=None, to_addrs=None):
        if FakeSMTP.fail:
            raise FakeSMTP.fail
        FakeSMTP.sent.append((em, from_addr, to_addrs))


def with_smtp(fn):
    orig = B.smtplib.SMTP
    B.smtplib.SMTP = FakeSMTP
    FakeSMTP.sent, FakeSMTP.fail = [], None
    try:
        return fn()
    finally:
        B.smtplib.SMTP = orig


def test_send_identity_invitation_reply_and_retryable_errors():
    be = B.IMAPBackend(dict(ACC, imap_host="imap.gmail.com"), "pw")     # gmail : pas de copie dans « Envoyés » (le serveur s'en charge)

    def go():
        be.send(Outgoing(account="a1", to="p@y.be", subject="Accepté : Réunion", html="<p>ok</p>", from_email="contact@x.be",
                         from_name="Société X", ics="BEGIN:VCALENDAR\r\nMETHOD:REPLY\r\nEND:VCALENDAR\r\n", ics_method="REPLY"))
        em, from_addr, rcpt = FakeSMTP.sent[0]
        assert from_addr == "contact@x.be" and rcpt == ["p@y.be"] and "contact@x.be" in em["From"] and "Société X" in em["From"]
        parts = [p for p in em.walk() if p.get_content_type() == "text/calendar"]
        assert parts and parts[0].get_param("method") == "REPLY" and "METHOD:REPLY" in parts[0].get_content()
        assert em["Message-ID"].endswith("@x.be>")
        be.send(Outgoing(account="a1", to="p@y.be", subject="S", html="<p>x</p>"))        # sans identité : compte
        assert FakeSMTP.sent[1][1] == "moi@x.be"
        for exc, retry in ((ConnectionResetError("coupé"), True), (smtplib.SMTPServerDisconnected("fin"), True),
                           (smtplib.SMTPRecipientsRefused({"p@y.be": (550, b"no")}), False), (smtplib.SMTPDataError(554, b"spam"), False)):
            FakeSMTP.fail = exc
            try:
                be.send(Outgoing(account="a1", to="p@y.be", subject="S", html="x")); raise SystemExit("aurait dû échouer")
            except B.BackendError as e:
                assert e.retryable is retry, (exc, e.retryable)
    with_smtp(go)


def test_server_search_translates_syntax_and_fetches_only_unknown():
    log = []

    class IM(FakeIMAP):
        def uid(self, cmd, *a):
            if cmd == "SEARCH":
                self.log.append(("SEARCH",) + a)
                return "OK", [b"3 7 9 12"]
            return super().uid(cmd, *a)
    be = backend(log)
    be._connect = lambda: IM(log)
    found = be.search_server("from:marie facture", ["inbox", "archive"], {"inbox": {7, 9}}, limit=40)
    searches = [e for e in log if e[0] == "SEARCH"]
    assert searches[0] == ("SEARCH", "FROM", '"marie"', "TEXT", '"facture"')
    got = sorted(m.uid for m in found if m.folder == "inbox")
    assert got == [3, 12]                                                       # 7 et 9 déjà connus : non retéléchargés
    assert {m.folder for m in found} == {"inbox", "archive"}
    assert B.build_imap_search("é")[:2] == ["CHARSET", "UTF-8"] and B.build_imap_search("") == ["ALL"]


def test_parse_message_thread_unsubscribe_and_invitation():
    ics = ("BEGIN:VCALENDAR\r\nMETHOD:REQUEST\r\nBEGIN:VEVENT\r\nUID:u1\r\nSUMMARY:Point\r\nDTSTART:20261112T140000\r\n"
           "ORGANIZER:mailto:o@x.be\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
    raw = ("From: Orga <o@x.be>\r\nTo: moi@x.be\r\nSubject: Re: Point\r\nDate: Wed, 04 Nov 2026 10:00:00 +0100\r\nMessage-ID: <r2@x>\r\n"
           "In-Reply-To: <r1@x>\r\nList-Unsubscribe: <https://x.be/u>, <mailto:u@x.be>\r\nList-Unsubscribe-Post: List-Unsubscribe=One-Click\r\n"
           "MIME-Version: 1.0\r\nContent-Type: multipart/alternative; boundary=BB\r\n\r\n--BB\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nBonjour\r\n"
           "--BB\r\nContent-Type: text/calendar; method=REQUEST; charset=utf-8\r\n\r\n" + ics + "--BB--\r\n").encode()
    m = B.parse_message(raw, "acc", "inbox", "INBOX", 5, set())
    assert m.references == "<r1@x>" and m.thread_id == "<r1@x>"                  # In-Reply-To sert de repli aux References
    assert m.unsub_post is True and "https://x.be/u" in m.unsubscribe
    assert m.invite["title"] == "Point" and m.invite["method"] == "REQUEST" and m.invite["organizer"] == "o@x.be"
