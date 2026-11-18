"""Sieve : génération, import Thunderbird, client ManageSieve contre un faux serveur."""
import os
import socket
import sys
import threading
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import testenv
from mintmail import sieve as S

RULES = [{"field": "from", "text": "newsletter@x.be", "action": "move", "folder": "Lettres"},
         {"field": "subject", "text": 'dit "bonjour"', "action": "trash"},
         {"field": "to", "text": "equipe", "action": "read"},
         {"field": "from", "text": "p", "action": "pin"}, {"field": "from", "text": "", "action": "trash"}]


def test_generate_rules():
    s = S.generate(RULES)
    assert s.count("if header") == 3 and 'require ["fileinto", "imap4flags"]' in s
    assert 'header :contains ["from"] "newsletter@x.be"' in s and 'fileinto "Lettres";' in s
    assert 'header :contains ["subject"] "dit \\"bonjour\\""' in s and 'fileinto "Trash";\n  stop;' in s
    assert 'header :contains ["to", "cc"] "equipe"' in s and 'addflag "\\\\Seen";' in s
    assert S.generate([]).count("require") == 0


def test_generate_vacation():
    ab = {"enabled": True, "start": "2026-12-01", "end": "2026-12-08", "subject": "Absent", "body": "Je reviens.\nA+"}
    s = S.generate([], ab, addresses=["me@x.be"])
    assert '"vacation"' in s and '"date"' in s and 'currentdate :value "ge" "date" "2026-12-01"' in s and 'le" "date" "2026-12-08"' in s
    assert ':addresses ["me@x.be"]' in s and 'vacation :days 1' in s
    assert "vacation" not in S.generate([], dict(ab, enabled=False))


TB = '''version="9"
logging="no"
name="Lettres"
enabled="yes"
type="17"
action="Move to folder"
actionValue="imap://me%40x.be@imap.x.be/INBOX/Lettres%20Info"
condition="AND (from,contains,newsletter@x.be)"
name="Lu"
enabled="yes"
type="17"
action="Mark read"
condition="AND (subject,contains,facture)"
name="Complexe"
enabled="yes"
type="17"
action="Move to folder"
actionValue="imap://x/INBOX/Z"
condition="AND (subject,contains,a) OR (from,contains,b)"
name="Éteint"
enabled="no"
type="17"
action="Delete"
condition="AND (subject,contains,z)"
'''


def test_thunderbird_import_and_merge():
    rules, skipped = S.parse_thunderbird_filters(TB)
    assert rules == [{"field": "from", "text": "newsletter@x.be", "action": "move", "folder": "Lettres Info"},
                     {"field": "subject", "text": "facture", "action": "read", "folder": ""}] and skipped == 2
    merged, n = S.merge_rules([rules[0]], rules)
    assert n == 1 and len(merged) == 2


def fake_server(responses_ok=True):
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    got = []

    def run():
        c, _ = srv.accept()
        c.sendall(b'"IMPLEMENTATION" "fake"\r\nOK "ready"\r\n')
        data = b""
        while True:
            d = c.recv(65536)
            if not d:
                break
            data += d
            while True:
                if data.startswith(b"PUTSCRIPT"):
                    head, sep, rest = data.partition(b"\r\n")
                    n = int(head.split(b"{")[1].split(b"+")[0])
                    if len(rest) < n + 2:
                        break
                    got.append(("put", head.decode(), rest[:n].decode()))
                    data = rest[n + 2:]
                    c.sendall(b'OK "stored"\r\n' if responses_ok else b'NO "syntax error"\r\n')
                elif b"\r\n" in data:
                    line, data = data.split(b"\r\n", 1)
                    got.append(("cmd", line.decode()))
                    if line.startswith(b"LOGOUT"):
                        c.sendall(b'OK "bye"\r\n')
                        c.close()
                        return
                    c.sendall(b'OK "done"\r\n')
                else:
                    break
    t = threading.Thread(target=run, daemon=True)
    t.start()
    return srv.getsockname()[1], got, t


def test_managesieve_publish():
    port, got, t = fake_server()
    script = S.generate(RULES[:1])
    S.publish("127.0.0.1", "me@x.be", "secret", script, port=port, tls=False)
    t.join(2)
    kinds = [g[1].split(" ")[0] if g[0] == "cmd" else "PUT" for g in got]
    assert kinds[:3] == ["AUTHENTICATE", "PUT", "SETACTIVE"]
    assert got[1][2] == script and '"mintmail"' in got[1][1]
    assert "secret" not in "".join(str(g) for g in got)               # PLAIN est encodé en base64, jamais en clair


def test_managesieve_refusal_and_unreachable():
    port, got, t = fake_server(responses_ok=False)
    try:
        S.publish("127.0.0.1", "u", "p", "bad", port=port, tls=False)
        assert False
    except S.SieveError as e:
        assert "NO" in str(e)
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    free = s.getsockname()[1]
    s.close()
    try:
        S.publish("127.0.0.1", "u", "p", "x", port=free, tls=False)
        assert False
    except S.SieveError:
        pass


def test_supports_and_publish_accounts():
    gm = {"id": "g", "email": "a@gmail.com", "imap_host": "imap.gmail.com"}
    ox = {"id": "o", "email": "a@x.be", "imap_host": "imap.gmail.com", "auth": "oauth2"}
    ok = {"id": "k", "email": "k@mail.be", "imap_host": "127.0.0.1", "username": "k"}
    assert not S.supports(gm) and not S.supports(ox) and S.supports(ok) and not S.supports({"imap_host": "", "email": "x"})
    port, got, t = fake_server()
    ab = {"enabled": True, "start": "2026-12-01", "end": "2026-12-02", "accounts": ["k"]}
    res = S.publish_accounts([gm, ok], lambda i: "pw", [], ab, own_of=lambda a: [a["email"]], port=port, tls=False)
    assert res == [("a@gmail.com", "unsupported"), ("k@mail.be", "ok")]
    assert "vacation" in got[1][2] and "k@mail.be" in got[1][2]
    port, got, t = fake_server()
    S.publish_accounts([ok], lambda i: "pw", [], dict(ab, accounts=["autre"]), port=port, tls=False)
    assert "vacation" not in got[1][2]
