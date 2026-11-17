"""Import des boîtes et réglages depuis Thunderbird, Evolution, une liste d'adresses (Outlook / Spark / Apple Mail…) et des contacts CSV."""
import os
import sys
import tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import testenv
from mintmail import importer as IM

PREFS = '''user_pref("mail.account.account1.identities", "id1,id2");
user_pref("mail.account.account1.server", "server1");
user_pref("mail.account.account2.server", "server2");
user_pref("mail.identity.id1.fullName", "Olivier P");
user_pref("mail.identity.id1.useremail", "olivier@saec.me");
user_pref("mail.identity.id1.htmlSigText", "<b>SAEC</b>");
user_pref("mail.identity.id1.smtpServer", "smtp1");
user_pref("mail.identity.id2.fullName", "Contact");
user_pref("mail.identity.id2.useremail", "contact@saec.me");
user_pref("mail.server.server1.type", "imap");
user_pref("mail.server.server1.hostname", "mail.saec.me");
user_pref("mail.server.server1.userName", "olivier@saec.me");
user_pref("mail.server.server1.port", 993);
user_pref("mail.server.server1.socketType", 3);
user_pref("mail.server.server2.type", "pop3");
user_pref("mail.server.server2.hostname", "pop.x.be");
user_pref("mail.smtpserver.smtp1.hostname", "smtp.saec.me");
user_pref("mail.smtpserver.smtp1.port", 465);
'''
EVO = {"abc.source": "[Data Source]\nDisplayName=Pro\nParent=\n\n[Mail Account]\nBackendName=imapx\n\n[Authentication]\nHost=imap.pro.be\nPort=993\nUser=moi@pro.be\n",
       "id.source": "[Data Source]\nDisplayName=Pro\nParent=abc\n\n[Mail Identity]\nName=Moi\nAddress=moi@pro.be\n"}


class Cfg(dict):
    saved = 0
    def save(self): self.saved += 1


def test_thunderbird_accounts_identities_and_aliases():
    out = IM.parse_thunderbird(PREFS)
    assert len(out) == 1                                                       # le compte POP est ignoré
    a = out[0]
    assert (a["email"], a["name"], a["imap_host"], a["imap_port"], a["smtp_host"], a["smtp_port"], a["username"]) == \
        ("olivier@saec.me", "Olivier P", "mail.saec.me", 993, "smtp.saec.me", 465, "olivier@saec.me")
    assert a["signature_html"] == "<b>SAEC</b>" and [x["email"] for x in a["aliases"]] == ["contact@saec.me"] and a["source"] == "Thunderbird"


def test_evolution_accounts():
    out = IM.parse_evolution(EVO)
    assert len(out) == 1 and out[0]["email"] == "moi@pro.be" and out[0]["name"] == "Moi" and out[0]["imap_host"] == "imap.pro.be"


def test_addresses_get_the_provider_settings_or_a_guess():
    out = IM.from_addresses("Olivier <olivier@gmail.com>, moi@hotmail.com\nperso@monsite.be ; olivier@gmail.com")
    assert [a["email"] for a in out] == ["olivier@gmail.com", "moi@hotmail.com", "perso@monsite.be"]
    assert out[0]["oauth"] == "google" and out[1]["oauth"] == "microsoft" and out[1]["imap_host"] == "outlook.office365.com"
    assert out[2]["imap_host"] == "imap.monsite.be" and out[2]["note"] == "check" and not out[2]["oauth"]


def test_detect_reads_profiles_from_the_home_folder():
    with tempfile.TemporaryDirectory() as home:
        tb = os.path.join(home, ".thunderbird")
        os.makedirs(os.path.join(tb, "abcd.default"))
        open(os.path.join(tb, "profiles.ini"), "w").write("[Profile0]\nName=default\nPath=abcd.default\n")
        open(os.path.join(tb, "abcd.default", "prefs.js"), "w").write(PREFS)
        found = IM.detect(home)
        assert [f["source"] for f in found] == ["Thunderbird"] and found[0]["accounts"][0]["email"] == "olivier@saec.me"
    with tempfile.TemporaryDirectory() as empty:
        assert IM.detect(empty) == []


def test_apply_adds_accounts_without_password_and_skips_existing():
    cfg = Cfg(accounts=[{"id": "x", "email": "deja@saec.me"}], identities=[])
    n = iter("abcdefgh")
    found = IM.parse_thunderbird(PREFS) + IM.from_addresses("deja@saec.me, moi@gmail.com")
    r = IM.apply(cfg, found, lambda: next(n))
    assert r["added"] == 2 and r["skipped"] == 1 and cfg.saved == 1
    a = cfg["accounts"][1]
    assert a["has_password"] is False and a["signature_html"] == "<b>SAEC</b>" and a["imported_from"] == "Thunderbird"
    assert cfg["accounts"][2]["auth"] == "oauth2" and cfg["accounts"][2]["oauth_provider"] == "google"
    assert cfg["identities"] == [{"id": "b", "account": "a", "email": "contact@saec.me", "name": "Contact", "signature_html": ""}]
    assert IM.apply(cfg, found, lambda: "z")["added"] == 0                      # deuxième import : rien de plus


def test_contacts_csv_from_outlook_google_and_spark():
    outlook = "First Name,Last Name,E-mail Address\nAnne,Dupont,anne@x.be\nBob,,\n"
    google = "Name,E-mail 1 - Value\nCarl Z,carl@y.com\nCarl Z,carl@y.com\n"
    fr = "﻿Nom;Adresse e-mail\nDora;dora@z.fr\n"
    assert IM.parse_contacts_csv(outlook) == [{"name": "Anne", "email": "anne@x.be"}]
    assert IM.parse_contacts_csv(google) == [{"name": "Carl Z", "email": "carl@y.com"}]
    assert IM.parse_contacts_csv(fr) == [{"name": "Dora", "email": "dora@z.fr"}]
    assert IM.parse_contacts_csv("rien,du,tout\n1,2,3") == []
