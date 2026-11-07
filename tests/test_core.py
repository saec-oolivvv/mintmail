import os, sys, tempfile, time
tmp = tempfile.mkdtemp()
os.environ["XDG_DATA_HOME"] = tmp
os.environ["XDG_CONFIG_HOME"] = tmp
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mintmail.store import Cache, Config
from mintmail.backend import DemoBackend, parse_message
from mintmail import util

def test_all():
    acc = {"id": "demo", "email": "demo@x.local", "name": "Démo", "demo": True}
    c = Cache()
    msgs, _, _, _ = DemoBackend(acc).sync("inbox", {})
    assert len(msgs) >= 10
    c.upsert_many(msgs)
    assert len(c.query("inbox")) == len(msgs)
    assert c.counts()["inbox"] > 0
    assert c.query("starred") and c.query(search="from:marie")
    m = msgs[0]
    c.update(m.id, folder="trash")
    assert c.get(m.id).folder == "trash" and m.id not in [x.id for x in c.query("inbox")]
    c.update(m.id, folder="inbox", snoozed_until=time.time() + 3600)
    assert m.id in [x.id for x in c.query("snoozed")]
    c.update(m.id, snoozed_until=time.time() - 1)
    assert c.wake_snoozed()
    cfg = Config(); cfg["theme"] = "dark"; cfg.save(); assert Config()["theme"] == "dark"

def test_parse():
    raw = (b"From: =?utf-8?q?Andr=C3=A9?= <a@b.be>\r\nTo: me@x.be\r\nSubject: Test\r\n"
           b"Date: Wed, 04 Nov 2026 10:00:00 +0100\r\nList-Unsubscribe: <https://u>\r\n"
           b"MIME-Version: 1.0\r\nContent-Type: text/html; charset=utf-8\r\n\r\n<p>Bonjour <b>monde</b></p>")
    m = parse_message(raw, "acc", "inbox", "INBOX", 7, set())
    assert m.sender_name == "André" and m.category == "news" and "Bonjour monde" in m.text and m.unread

def test_util():
    assert "src" not in util.block_remote_content('<img src="https://t.co/p.gif">').replace("data-blocked-src", "")
    assert util.has_remote_content('<img src="//x.y/z.png">')
    assert util.normalize_subject("Re: RE: Fwd: Salut") == "Salut"
    assert util.initials("Marie Dupont") == "MD"

def test_wrap_html():
    from mintmail.reader import wrap_html
    class M:
        html, text = "<p>Salut</p>", "Salut"
    out = wrap_html(M(), False, False)
    assert out.startswith("<html>") and "Salut" in out   # CSS %% ne doit pas casser le format
    class M2:
        html, text = None, "brut"
    assert "brut" in wrap_html(M2(), False, True)
