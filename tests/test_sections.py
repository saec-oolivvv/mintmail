"""Périodes de la liste (sections.py) et rangées de groupes de la boîte unifiée (groups.digest)."""
import datetime
import time
from types import SimpleNamespace as NS

from mintmail import groups as G
from mintmail import sections as S

NOW = time.mktime(datetime.datetime(2026, 11, 17, 15, 0).timetuple())


def ago(days, hour=10):
    d = datetime.datetime(2026, 11, 17, hour, 0) - datetime.timedelta(days=days)
    return time.mktime(d.timetuple())


def test_periods_follow_spark_today_yesterday_last_week_months_then_years():
    assert S.section_of(ago(0), NOW)[0] == "today" and S.section_of(NOW + 3600, NOW)[0] == "today"
    assert S.section_of(ago(1), NOW)[0] == "yesterday"
    assert S.section_of(ago(2), NOW)[0] == "week" and S.section_of(ago(7), NOW)[0] == "week"
    assert S.section_of(ago(8), NOW)[0] == "m202611"                      # novembre, mais plus d'une semaine
    assert S.section_of(ago(60), NOW)[0] == "m202609"
    assert S.section_of(ago(400), NOW) == ("y2025", "2025")


def test_headings_only_open_a_new_period():
    dates = [ago(0), ago(0, 8), ago(1), ago(3), ago(5), ago(40), ago(45), ago(500)]
    h = S.headings(dates, NOW)
    assert [bool(x) for x in h] == [True, False, True, True, False, True, False, True]
    assert h[-1] == "2025" or h[-1].isdigit()


def msg(i, g, sender, unread=True, **kw):
    d = dict(id=i, account="a1", pinned=False, invite={}, category="people", to="x@y.be, z@y.be", cc="", folder="inbox", unread=unread, display_sender=sender)
    if g == "notif":
        d["category"] = "notif"
    if g == "news":
        d["category"] = "news"
    if g == "pinned":
        d["pinned"] = True
    d.update(kw)
    return NS(**d)


def test_digest_lists_only_sender_names_unread_first_without_duplicates():
    cfg = {"accounts": [{"id": "a1", "email": "me@x.be"}]}
    gr = G.Grouper(cfg, None, cfg["accounts"])
    msgs = [msg("1", "news", "Le Soir", unread=False), msg("2", "news", "Medium"), msg("3", "news", "Medium"), msg("4", "notif", "GitHub"),
            msg("5", "pinned", "Ana"), msg("6", None, "Bob")]
    d = G.digest(gr, msgs)
    assert d["news"] == {"n": 3, "unread": 2, "senders": ["Medium", "Le Soir"]}
    assert d["notif"]["senders"] == ["GitHub"] and d["pinned"]["n"] == 1
    assert "mine" not in d and None not in d                             # la boîte principale n'a pas de rangée
    assert G.ROW_ORDER[:4] == ["pinned", "notif", "news", "invite"]


def test_digest_skips_groups_shown_inline():
    cfg = {"accounts": [{"id": "a1", "email": "me@x.be"}], "group_modes": {"news": "inline"}}
    gr = G.Grouper(cfg, None, cfg["accounts"])
    assert "news" not in G.digest(gr, [msg("1", "news", "Medium")])
