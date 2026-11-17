"""Détection locale des messages suspects : motifs, absence de fausses alertes courantes, cas où l'on ne pose pas la question."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mintmail import suspect as S
from mintmail.models import Message


def msg(**kw):
    d = dict(id="m", account="a", folder="inbox", uid=1, sender_name="Marie", sender_email="marie@exemple.be", subject="Bonjour", text="Bonjour, voici le dossier.", html="", date=1)
    d.update(kw)
    return Message(**d)


def test_ordinary_mail_is_not_flagged():
    assert S.reasons(msg()) == []
    assert S.reasons(msg(sender_name="Amazon", sender_email="store-news@amazon.fr")) == []
    assert S.reasons(msg(html='<p><a href="https://www.proximus.be/facture">www.proximus.be</a></p>')) == []
    assert S.reasons(msg(sender_name="Ing. Dupont", sender_email="dupont@cabinet.be")) == []


def test_impersonation_masked_links_and_scam_text_are_flagged():
    r = S.reasons(msg(sender_name="PayPal Service", sender_email="support@secure-mail.ru"))
    assert r and "paypal" in r[0].lower()
    r = S.reasons(msg(sender_name="paypal@paypal.com", sender_email="x@evil.net"))
    assert r and "autre adresse" in r[0]
    r = S.reasons(msg(html='<a href="http://evil.example.ru/login">www.paypal.com</a>'))
    assert r and "mène vers" in r[0]
    assert S.reasons(msg(html='<a href="https://bit.ly/abc">voir</a>'))
    assert S.reasons(msg(subject="Paiement refusé", text="vérifier votre compte : cliquez ici"))
    assert S.reasons(msg(), {"suspicious": True, "why": "domaine imité", "local": False}) == ["domaine imité"]
    assert S.reasons(msg(), {"suspicious": True, "local": True}) == []                    # le jugement local est déjà refait ici


def test_question_is_asked_only_in_the_inbox_for_unknown_unjudged_senders():
    bad = msg(sender_name="PayPal", sender_email="x@evil.ru")
    assert S.should_ask(bad, None, False, False)
    assert not S.should_ask(bad, None, True, False)             # déjà jugé sûr
    assert not S.should_ask(bad, None, False, True)             # expéditeur du carnet d'adresses
    assert not S.should_ask(msg(folder="spam", sender_name="PayPal", sender_email="x@evil.ru"), None, False, False)


def test_recipients_text_shows_to_cc_and_receiving_mailbox():
    from mintmail.qt import viewmodel as vm
    from types import SimpleNamespace as NS
    m = NS(account="a1", to='Olivier <o@x.be>, p@y.com', cc="")
    r = vm.recipients_text(m, [{"id": "a1", "email": "boite@z.be"}])
    assert r == {"to": "Olivier <o@x.be>, p@y.com", "cc": "", "box": "boite@z.be"}
