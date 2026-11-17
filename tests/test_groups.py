"""Groupes de la boîte de réception (groups.py) : classement, réglages généraux et par boîte, filtrage, synchronisation."""
from types import SimpleNamespace as NS

from mintmail import groups as G
from mintmail import syncdata as SD

ME = {"me@x.be"}


def msg(**kw):
    d = dict(id="m1", account="a1", pinned=False, invite={}, category="people", to="me@x.be", cc="", folder="inbox", unread=True)
    d.update(kw)
    return NS(**d)


def test_each_message_belongs_to_one_group_with_priority():
    assert G.group_of(msg(pinned=True, category="news"), ME) == "pinned"
    assert G.group_of(msg(invite={"method": "REQUEST"}), ME) == "invite"
    assert G.group_of(msg(invite={"method": "CANCEL"}), ME) == "invite"
    assert G.group_of(msg(invite={"method": "REPLY"}), ME) == "reply"
    assert G.group_of(msg(category="notif"), ME) == "notif"
    assert G.group_of(msg(category="news"), ME) == "news"


def test_assigned_to_me_is_direct_to_me_alone_or_has_a_task_or_followup():
    assert G.group_of(msg(), ME) == "mine"
    assert G.group_of(msg(to="me@x.be, autre@y.be"), ME) is None          # plusieurs destinataires : boîte principale
    assert G.group_of(msg(cc="z@y.be"), ME) is None                       # quelqu'un en copie
    assert G.group_of(msg(to="liste@y.be"), ME) is None                   # pas adressé à moi
    assert G.group_of(msg(to="liste@y.be", category="news"), ME, has_followup=True) == "mine"
    assert G.group_of(msg(category="news"), ME) == "news"                  # une newsletter adressée à moi seul reste une newsletter


def test_my_addresses_include_aliases_of_the_account_only():
    ids = [{"account": "a1", "email": "alias@x.be"}, {"account": "a2", "email": "autre@z.be"}, {"email": "global@x.be"}]
    got = G.my_addresses({"id": "a1", "email": "Me@x.be"}, ids)
    assert got == {"me@x.be", "alias@x.be", "global@x.be"}


class Cfg(dict):
    def get(self, k, d=None):
        return dict.get(self, k, d)


def cfg(**kw):
    c = Cfg(accounts=[{"id": "a1", "email": "me@x.be"}, {"id": "a2", "email": "pro@x.be"}], identities=[], tasks=[], followups=[])
    c.update(kw)
    return c


def test_default_modes_group_the_automatic_mail_and_keep_the_personal_mail_inline():
    s = G.settings_for(cfg(), "a1")
    assert s["on"] is True and s["modes"]["news"] == G.GROUP and s["modes"]["notif"] == G.GROUP
    assert s["modes"]["pinned"] == G.ALL and s["modes"]["mine"] == G.ALL


def test_general_then_per_mailbox_overrides():
    c = cfg(group_modes={"news": "inline"})
    c["accounts"][1].update(group_modes={"news": "group", "notif": "inline"}, inbox_grouping=True)
    c["accounts"][0]["inbox_grouping"] = False
    assert G.settings_for(c, "a1")["on"] is False
    assert G.settings_for(c, "a1")["modes"]["news"] == G.ALL               # réglage général
    assert G.settings_for(c, "a2")["modes"]["news"] == G.GROUP             # dérogation de la boîte
    assert G.settings_for(c, "a2")["modes"]["notif"] == G.ALL
    bad = cfg(group_modes={"news": "nimportequoi", "zzz": "group"})
    assert G.settings_for(bad, "a1")["modes"]["news"] == G.GROUP           # valeur invalide ignorée


def test_main_inbox_hides_grouped_groups_per_account_and_group_chips_show_them():
    c = cfg()
    c["accounts"][0]["inbox_grouping"] = False                             # la boîte a1 montre tout
    gr = G.Grouper(c)
    news_a1, news_a2 = msg(id="1", account="a1", category="news"), msg(id="2", account="a2", category="news", to="pro@x.be")
    perso = msg(id="3", account="a2", to="pro@x.be, x@y.be")
    pinned = msg(id="4", account="a2", pinned=True, to="pro@x.be")
    allm = [news_a1, news_a2, perso, pinned]
    assert [m.id for m in G.filter_view(gr, allm, None)] == ["1", "3", "4"]      # a2/news est sorti ; épinglés restent (mode afficher tout)
    assert [m.id for m in G.filter_view(gr, allm, "news")] == ["1", "2"]
    assert [m.id for m in G.filter_view(gr, allm, "all")] == ["1", "2", "3", "4"]
    assert gr.counts(allm)["news"] == 2 and gr.counts(allm)["pinned"] == 1
    assert gr.any_grouping()


def test_tasks_and_followups_make_a_message_mine():
    c = cfg(tasks=[{"msg": "t1", "done": False}, {"msg": "t2", "done": True}], followups=[{"id": "f1"}])
    assert G.followed_ids(c) == {"t1", "f1"}


def test_grouping_settings_travel_between_machines_and_are_validated():
    assert SD.SYNC_SETTINGS["inbox_grouping"](True) and not SD.SYNC_SETTINGS["inbox_grouping"]("oui")
    assert SD.SYNC_SETTINGS["group_modes"]({"news": "group", "pinned": "inline"})
    assert not SD.SYNC_SETTINGS["group_modes"]({"news": "x"}) and not SD.SYNC_SETTINGS["group_modes"]({"autre": "group"})
    acct = {"id": "abcd1234", "email": "a@b.be", "imap_host": "imap.b.be", "smtp_host": "smtp.b.be", "imap_port": 993, "smtp_port": 587,
            "inbox_grouping": False, "group_modes": {"news": "inline"}}
    out = SD.clean_account(acct)
    assert out["inbox_grouping"] is False and out["group_modes"] == {"news": "inline"}
    acct["group_modes"] = {"news": "boum"}
    assert "group_modes" not in SD.clean_account(acct)
