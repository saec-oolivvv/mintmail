"""Auto-complétion des destinataires : recherche par nom / adresse / société sans accents, plusieurs destinataires, mémorisation à l'envoi."""
import json
import os
import sys
import tempfile
import time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import testenv
from mintmail import contacts as CT
from mintmail.models import Message
from mintmail.store import Cache


def test_token_bounds_and_choice():
    assert CT.current_token("a@x.be, ass") == "ass" and CT.current_token("ass") == "ass" and CT.current_token("") == ""
    assert CT.current_token("a@x.be; b", 9) == "b"
    assert CT.current_token('"Dupont, Jean" <j@x.be>, mar') == "mar"
    assert CT.current_token('"Dupont, Jean" <j@x.be>', 8) == '"Dupont, Jean" <j@x.be>'      # la virgule entre guillemets ne coupe pas
    new, cur = CT.apply_choice("a@x.be, ass", 11, "Assurances Dupont <info@ass.be>")
    assert new == "a@x.be, Assurances Dupont <info@ass.be>, " and cur == len(new)
    new, _ = CT.apply_choice("ass, c@x.be", 3, "Ass <i@a.be>")                                 # au milieu : l'autre destinataire est gardé
    assert new == "Ass <i@a.be>, c@x.be"


def test_format_entry_and_matches():
    assert CT.format_entry("", "a@x.be") == "a@x.be" and CT.format_entry("Jean", "j@x.be") == "Jean <j@x.be>"
    assert CT.format_entry("Dupont, Jean", "j@x.be") == '"Dupont, Jean" <j@x.be>'
    assert [a for _n, a in CT.parse_addresses(CT.format_entry("Dupont, Jean", "j@x.be"))] == ["j@x.be"]
    assert CT.matches("societe gen", "Société Générale", "sg@x.be") and not CT.matches("axa", "Ethias", "e@x.be") and not CT.matches("", "x")
    assert CT.matches("assur dupont", "Dupont", "d@x.be", "Assurances Dupont SA")


def _cache():
    c = Cache(os.path.join(tempfile.mkdtemp(), "c.db"))
    msgs = [Message(id="m1", account="a", folder="inbox", uid=1, sender_name="Hélène Martin", sender_email="helene@axa-assur.be", subject="Votre police", date=time.time(),
                    to="moi@x.be", message_id="<1@x>"),
            Message(id="m2", account="a", folder="sent", uid=2, sender_email="moi@x.be", subject="Sinistre", date=time.time() - 50, to="Ethias Sinistres <sinistres@ethias.be>",
                    message_id="<2@x>")]
    c.upsert_many(msgs)
    return c


def test_search_in_messages_without_any_contact_book():
    c = _cache()
    assert [e for _n, e, _o in c.contact_search("helene")] == ["helene@axa-assur.be"]          # accent ignoré
    assert [e for _n, e, _o in c.contact_search("ethias")] == ["sinistres@ethias.be"]          # destinataire d'un message envoyé
    assert [e for _n, e, _o in c.contact_search("assur")] == ["helene@axa-assur.be"]
    assert c.contact_search("zzzz") == [] and c.contact_search("") == []


def test_search_book_by_company_and_order():
    c = _cache()
    c.contact_upsert("agent@assureur.be", "Paul Agent", org="Assureur Belge SA", source="manual")
    r = c.contact_search("assureur")
    assert r and r[0][1] == "agent@assureur.be" and r[0][2] == "Assureur Belge SA"
    r = c.contact_search("belge paul")
    assert [e for _n, e, _o in r] == ["agent@assureur.be"]


def test_remember_after_send():
    c = _cache()
    assert c.contacts_remember(["Garage Dupont <garage@dupont.be>, autre@x.be", "", "cc@x.be"]) == 3
    assert c.contact_search("garage")[0][1] == "garage@dupont.be"
    c.contacts_remember(["garage@dupont.be"])
    assert [x for x in c.contacts_list() if x["email"] == "garage@dupont.be"][0]["n"] == 2
    assert c.contacts_rebuild() >= 1 and c.contact_search("garage")[0][0] == "Garage Dupont"
