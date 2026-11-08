"""Backend IMAP : connexions persistantes, lots progressifs (récents d'abord), actions groupées, reconnexion."""
import imaplib, os, sys, tempfile, time
tmp = tempfile.mkdtemp()
os.environ["XDG_DATA_HOME"] = tmp
os.environ["XDG_CONFIG_HOME"] = tmp
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mintmail.backend import IMAPBackend
from mintmail.models import Message

RAW = b"From: a@b.be\r\nTo: me@x.be\r\nSubject: Sujet %d\r\nDate: Wed, 04 Nov 2026 10:00:00 +0100\r\n\r\ncorps %d"


class FakeIMAP:
    capabilities = ("MOVE",)

    def __init__(self, log, dead_noop=False):
        self.log, self.dead_noop, self.selected = log, dead_noop, None

    def noop(self):
        if self.dead_noop:
            raise imaplib.IMAP4.abort("socket error: EOF")
        return "OK", []

    def logout(self): self.log.append("logout")
    def expunge(self): self.log.append("expunge")

    def select(self, name, readonly=False):
        self.log.append(("select", name, readonly))
        return "OK", [b"1"]

    def list(self):
        return "OK", [b'(\\HasNoChildren) "/" "INBOX"', b'(\\Archive) "/" "Archive"',
                      b'(\\Junk) "/" "Spam"', b'(\\Trash) "/" "Trash"']

    def uid(self, cmd, *a):
        self.log.append((cmd,) + a)
        if cmd == "SEARCH":
            return "OK", [b"1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25"]
        if cmd == "FETCH" and "BODY.PEEK" in a[1]:
            out = []
            for u in a[0].split(","):
                raw = RAW % (int(u), int(u))
                out += [(("%s (UID %s FLAGS () BODY[] {%d}" % (u, u, len(raw))).encode(), raw), b")"]
            return "OK", out
        if cmd == "FETCH":
            return "OK", [("%s (UID %s FLAGS (\\Seen))" % (u, u)).encode() for u in a[0].split(",")]
        return "OK", []


def backend(log, **kw):
    be = IMAPBackend({"id": "acc", "email": "me@x.be", "imap_host": "h", "imap_port": 993, "smtp_host": "h", "smtp_port": 587}, "pw")
    made = []

    def connect():
        made.append(FakeIMAP(log, **kw if not made else {}))
        return made[-1]
    be._connect = connect
    be.made = made
    return be


def msgs(uids):
    return [Message(id="acc|INBOX|%d" % u, account="acc", uid=u, real_folder="INBOX") for u in uids]


def test_sync_batches_newest_first_and_reuses_connection():
    log, batches = [], []
    be = backend(log)
    res, flags, present, mn = be.sync("inbox", {6: "x", 7: "y"}, limit=20, on_batch=batches.append)
    got = [m.uid for m in res]
    assert got == sorted(got, reverse=True) and len(got) == 18 and 25 in got and 1 not in got
    assert [len(b) for b in batches] == [10, 8] and batches[0][0].uid == 25    # récents d'abord, lots de 10
    assert set(flags) == {6, 7} and present == set(range(6, 26)) and mn == 6      # indicateurs des messages déjà connus
    be.sync("inbox", {}, limit=3)
    assert len(be.made) == 1                                                   # une seule connexion pour 2 synchros
    assert [e for e in log if isinstance(e, tuple) and e[0] == "select"].count(("select", '"INBOX"', True)) == 1  # pas de re-SELECT


def test_move_many_is_one_command():
    log = []
    be = backend(log)
    be.move_many(msgs([4, 5, 6, 7]), "archive")
    moves = [e for e in log if isinstance(e, tuple) and e[0] == "MOVE"]
    assert moves == [("MOVE", "4,5,6,7", '"Archive"')]
    be.set_flags_many(msgs([4, 5]), seen=True)
    stores = [e for e in log if isinstance(e, tuple) and e[0] == "STORE"]
    assert stores == [("STORE", "4,5", "+FLAGS", "(\\Seen)")] and len(be.made) == 1


def test_dead_connection_is_replaced():
    log = []
    be = backend(log, dead_noop=True)
    be.move_many(msgs([1]), "trash")                 # 1re connexion (« morte » au premier NOOP)
    be._conns["act"].ts = time.time() - 60           # inactive : NOOP avant réutilisation
    be.move_many(msgs([2]), "trash")                 # NOOP échoue → reconnexion automatique, l'action aboutit
    assert len(be.made) == 2
    assert [e for e in log if isinstance(e, tuple) and e[0] == "MOVE"][-1] == ("MOVE", "2", '"Trash"')
    be.close()
