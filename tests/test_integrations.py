"""Intégrations (Teams, Slack, notes Markdown, Obsidian, Bear, Todoist, Notion) : contenu envoyé, sécurité des adresses, résultats."""
import io
import json
import os
import tempfile
import urllib.error
from types import SimpleNamespace as NS

from mintmail import integrations as I


def msg(**kw):
    d = dict(subject="Devis n°7", sender_name="Ana", sender_email="ana@x.be", date=1700000000.0, text="Bonjour,\n\n\n\nVoici le devis.", html="", snippet="")
    d.update(kw)
    return NS(**d)


class FakeResp:
    def __init__(self, status=200, body=b"{}"):
        self.status, self._b = status, body

    def read(self, n=-1):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Patch:
    """Remplace pytest.monkeypatch quand le test est lancé par tests/run_all.py (sans pytest)."""
    def setattr(self, obj, name, value):
        setattr(obj, name, value)


def capture(monkeypatch, status=200, body=b"{}"):
    calls = []

    def fake(req, timeout=0):
        calls.append(req)
        if status >= 400:
            raise urllib.error.HTTPError(req.full_url, status, "x", {}, io.BytesIO(b"err"))
        return FakeResp(status, body if "databases" not in req.full_url else json.dumps({"properties": {"Nom": {"type": "title"}, "Tag": {"type": "select"}}}).encode())
    monkeypatch.setattr(I.urllib.request, "urlopen", fake)
    return calls


def test_available_needs_settings_and_secrets():
    cfg = {"integrations": {"teams": True, "slack": True, "notes_dir": "/x", "obsidian_vault": "V", "bear": True, "todoist": True, "notion_db": "abc"}}
    assert I.available(cfg, lambda k: "") == ["notes", "obsidian", "bear"]
    assert I.available(cfg, lambda k: "secret") == list(I.SERVICES)
    assert I.available({}, lambda k: "secret") == []


def test_webhook_addresses_must_be_public_https():
    assert not I.public_https("http://hooks.slack.com/x")
    assert not I.public_https("https://localhost/x") and not I.public_https("https://127.0.0.1/x") and not I.public_https("https://192.168.1.5/x")
    assert not I.public_https("https://10.0.0.2/x") and not I.public_https("https://user:pw@hooks.slack.com/x") and not I.public_https("https://nas.local/x")
    assert I.public_https("https://8.8.8.8/x")


def test_teams_and_slack_payloads(monkeypatch=None):
    monkeypatch = monkeypatch or _Patch()
    calls = capture(monkeypatch)
    assert I.send_webhook("slack", "https://8.8.8.8/hook", msg())[0]
    body = json.loads(calls[0].data)
    assert "Devis n°7" in body["text"] and "Voici le devis" in body["text"] and "\n\n\n" not in body["text"]
    assert I.send_webhook("teams", "https://8.8.8.8/hook", msg())[0]
    assert json.loads(calls[1].data)["@type"] == "MessageCard"
    ok, why = I.send_webhook("slack", "http://8.8.8.8/hook", msg())
    assert not ok and len(calls) == 2                                       # refusé avant tout envoi


def test_http_errors_are_explained(monkeypatch=None):
    monkeypatch = monkeypatch or _Patch()
    capture(monkeypatch, status=401)
    ok, why = I.todoist_task("tok", msg())
    assert not ok and "401" in why


def test_todoist_and_notion_requests(monkeypatch=None):
    monkeypatch = monkeypatch or _Patch()
    calls = capture(monkeypatch)
    assert I.todoist_task("tok", msg(), project="123", due="demain")[0]
    r = calls[0]
    assert r.full_url.startswith("https://api.todoist.com/") and r.get_header("Authorization") == "Bearer tok"
    p = json.loads(r.data)
    assert p["content"] == "Devis n°7" and p["project_id"] == "123" and p["due_string"] == "demain"
    calls.clear()
    assert I.notion_page("secret", "db1", msg())[0]
    assert calls[0].get_method() == "GET" and calls[1].full_url == "https://api.notion.com/v1/pages"
    page = json.loads(calls[1].data)
    assert page["parent"] == {"database_id": "db1"} and "Nom" in page["properties"]       # la colonne titre est découverte


def test_markdown_note_never_overwrites_and_uris_are_encoded():
    with tempfile.TemporaryDirectory() as d:
        a, b = I.export_markdown(msg(subject="A/B: test"), d), I.export_markdown(msg(subject="A/B: test"), d)
        assert a != b and os.path.exists(a) and os.path.exists(b) and os.path.dirname(a) == d
        t = open(a, encoding="utf-8").read()
        assert t.startswith("---\n") and "# A/B: test" in t and "Voici le devis" in t
    u = I.obsidian_uri("Mon coffre", msg())
    assert u.startswith("obsidian://new?vault=Mon%20coffre&name=") and " " not in u and "\n" not in u
    assert I.bear_uri(msg()).startswith("bear://x-callback-url/create?title=Devis")
