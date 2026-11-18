"""Recherche avancée : after: / before: / is:read / is:pinned (cache local et critères IMAP)."""
import datetime
import os
import sys
import tempfile
import time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import testenv
from mintmail import backend as B
from mintmail.models import Message
from mintmail.store import Cache, parse_search


def test_parse_and_imap():
    terms, f = parse_search("facture after:2026-11-01 before:2026-12-01 is:read is:pinned after:pasunedate")
    assert f["after"] == datetime.date(2026, 11, 1) and f["before"] == datetime.date(2026, 12, 1) and f["read"] and f["pinned"]
    assert terms == ["facture", "after:pasunedate"]
    a = B.build_imap_search("after:2026-11-03 before:2026-12-01 is:read is:pinned")
    assert a == ["SEEN", "KEYWORD", B.PIN_KEYWORD, "SINCE", "03-Nov-2026", "BEFORE", "01-Dec-2026"]


def test_local_query():
    c = Cache(os.path.join(tempfile.mkdtemp(), "s.db"))
    d = lambda y, m, j: time.mktime(datetime.date(y, m, j).timetuple()) + 3600
    c.upsert_many([Message(id="a", account="x", folder="inbox", uid=1, date=d(2026, 10, 20), subject="facture vieille", unread=False),
                   Message(id="b", account="x", folder="inbox", uid=2, date=d(2026, 11, 10), subject="facture récente", unread=True),
                   Message(id="c", account="x", folder="inbox", uid=3, date=d(2026, 11, 12), subject="facture épinglée", unread=False, pinned=True)])
    ids = lambda q: sorted(m.id for m in c.query("inbox", "all", search=q))
    assert ids("facture after:2026-11-01") == ["b", "c"] and ids("facture before:2026-11-01") == ["a"]
    assert ids("facture is:read") == ["a", "c"] and ids("facture is:pinned") == ["c"]
    assert ids("facture after:2026-11-11 before:2026-11-13") == ["c"]
