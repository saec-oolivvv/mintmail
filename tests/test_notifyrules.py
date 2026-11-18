"""Notifications dosées : mode, boîtes, VIP, silence horaire (qui passe minuit)."""
import datetime
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import testenv
from mintmail import notifyrules as N
from mintmail.models import Message


def m(sender="ami@x.be", account="a1", **kw):
    return Message(id="1", account=account, sender_email=sender, **kw)


def at(h, mi=0): return datetime.datetime(2026, 11, 18, h, mi)


def test_modes():
    assert N.wants({}, m())
    assert not N.wants({"notify_mode": "none"}, m())
    news = m(category="news")
    assert not N.wants({"notify_mode": "people"}, news) and N.wants({"notify_mode": "people"}, m())
    assert not N.wants({"notify_mode": "people"}, m(unsubscribe="<u>"))
    vip = {"notify_mode": "vip", "vips": ["Boss@x.be"], "contacts": {"ami@x.be": {}}}
    assert N.wants(vip, m("boss@x.be")) and N.wants(vip, m("ami@x.be")) and not N.wants(vip, m("inconnu@x.be"))
    assert N.settings({"notify_mode": "bidon"})["notify_mode"] == "all"


def test_accounts_and_blocked():
    cfg = {"notify_off_accounts": ["a2"], "blocked": ["spam@x.be"]}
    assert N.wants(cfg, m(account="a1")) and not N.wants(cfg, m(account="a2")) and not N.wants(cfg, m("SPAM@x.be"))
    assert N.split(cfg, [m(account="a1"), m(account="a2")]) == [m(account="a1")] or len(N.split(cfg, [m(account="a1"), m(account="a2")])) == 1


def test_quiet_hours_cross_midnight():
    cfg = {"quiet_enabled": True, "quiet_from": "22:00", "quiet_to": "07:00"}
    s = N.settings(cfg)
    assert N.in_quiet_hours(s, at(23)) and N.in_quiet_hours(s, at(3)) and N.in_quiet_hours(s, at(22, 0))
    assert not N.in_quiet_hours(s, at(7, 0)) and not N.in_quiet_hours(s, at(12))
    assert not N.wants(cfg, m(), at(23)) and N.wants(cfg, m(), at(12))
    day = N.settings({"quiet_enabled": True, "quiet_from": "12:00", "quiet_to": "14:00"})
    assert N.in_quiet_hours(day, at(13)) and not N.in_quiet_hours(day, at(15))
    assert not N.in_quiet_hours(N.settings({"quiet_enabled": False}), at(23)) and not N.in_quiet_hours(N.settings({"quiet_enabled": True, "quiet_from": "08:00", "quiet_to": "08:00"}), at(8))


def test_title_count():
    assert N.title_with_count("MintMail", 12) == "MintMail (12)" and N.title_with_count("MintMail", 0) == "MintMail"
