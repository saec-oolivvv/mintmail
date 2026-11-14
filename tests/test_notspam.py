"""« Ce n'est pas du spam » : le message ET tous ceux du même expéditeur quittent Spam pour la boîte de réception,
le serveur est prévenu ($NotJunk, sortie du dossier), l'expéditeur sort de la liste « en spam », et l'IA suggère l'action."""
import os, sys, time, types
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import testenv
from mintmail.models import Message
from mintmail import backend as B, offline as O


def test_server_gets_notjunk_flags_then_the_message_leaves_spam():
    be = B.IMAPBackend({"id": "a", "email": "a@b.c"}, "")
    log = []

    class Imap:
        capabilities = ("MOVE",)
        def uid(self, *a): log.append(a); return ("OK", [b"done"])
    conn = types.SimpleNamespace(imap=Imap())
    be._run = lambda kind, fn: fn(conn)
    be._resolve = lambda imap, dest: "INBOX"
    be._select = lambda c, real: log.append(("SELECT", real))
    msgs = [types.SimpleNamespace(uid=11, real_folder="[Gmail]/Spam"), types.SimpleNamespace(uid=12, real_folder="[Gmail]/Spam")]
    be.move_many(msgs, "inbox", notjunk=True)
    assert log == [("SELECT", "[Gmail]/Spam"), ("STORE", "11,12", "-FLAGS", "($Junk)"), ("STORE", "11,12", "+FLAGS", "($NotJunk)"),
                   ("MOVE", "11,12", '"INBOX"')], log
    log.clear()
    be.move_many(msgs, "inbox")                                               # sans l'option : comportement inchangé
    assert log == [("SELECT", "[Gmail]/Spam"), ("MOVE", "11,12", '"INBOX"')], log


def test_server_without_free_keywords_still_moves_the_message():
    be = B.IMAPBackend({"id": "a", "email": "a@b.c"}, "")
    log = []

    class Imap:
        capabilities = ()
        def uid(self, *a):
            log.append(a[0] + (a[2] if a[0] == "STORE" else ""))
            if a[0] == "STORE" and "Junk" in a[3]:
                raise RuntimeError("NO [CANNOT] keyword refused")
        def expunge(self): log.append("EXPUNGE")
    be._run = lambda kind, fn: fn(types.SimpleNamespace(imap=Imap()))
    be._resolve = lambda imap, dest: "INBOX"
    be._select = lambda c, real: None
    be.move_many([types.SimpleNamespace(uid=5, real_folder="Junk")], "inbox", notjunk=True)
    assert log[-3:] == ["COPY", "STORE+FLAGS", "EXPUNGE"], log               # COPY + suppression : le déplacement a bien eu lieu

