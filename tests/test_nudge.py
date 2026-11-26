import time

from mintmail import nudge as NU
from mintmail.models import Message


def mk(i, folder, sender, date, subj="Devis", thread="t1"):
    return Message(id=i, account="a", folder=folder, sender_email=sender, subject=subj, date=date, thread_id=thread, to="x@y.fr", message_id="<%s@m>" % i)


def test_waiting_days_and_reply_detection():
    now = time.time()
    sent = mk("1", "sent", "moi@saec.me", now - 4 * 86400)
    assert NU.waiting_days(sent, [sent], ["moi@saec.me"], now) == 4
    reply = mk("2", "inbox", "x@y.fr", now - 86400)
    assert NU.waiting_days(sent, [sent, reply], ["moi@saec.me"], now) is None
    mine_later = mk("3", "sent", "moi@saec.me", now - 86400)
    assert NU.waiting_days(sent, [sent, mine_later], ["moi@saec.me"], now) == 4          # ma propre relance n'est pas une réponse
    old = mk("4", "inbox", "x@y.fr", now - 9 * 86400)
    assert NU.waiting_days(sent, [sent, old], ["moi@saec.me"], now) == 4                 # message plus ancien : pas une réponse
    other = mk("5", "inbox", "x@y.fr", now - 86400, thread="zz", subj="Re: devis")
    assert NU.waiting_days(sent, [sent, other], ["moi@saec.me"], now) is None           # même objet : réponse
    assert NU.waiting_days(reply, [reply], [], now) is None                              # pas un message envoyé


def test_nudge_args():
    sent = mk("1", "sent", "moi@saec.me", time.time() - 86400, subj="Re: Devis cuisine")
    a = NU.args(sent, "<blockquote>q</blockquote>", 1)
    assert a["to"] == "x@y.fr" and a["subject"] == "Re: Devis cuisine" and a["in_reply_to"] == "<1@m>" and "<blockquote>q" in a["quote_html"]
    assert "<p>" in a["body_html"]
    assert NU.waiting_text(0) and NU.waiting_text(3)
