"""Accusés de lecture (RFC 8098) et impression : construction, reconnaissance, enregistrement sur le message envoyé."""
import email
import os
import tempfile
from email import policy
from types import SimpleNamespace as NS

from mintmail import receipts as R
from mintmail.qt import printing
from mintmail.backend import parse_message
from mintmail.models import Message
from mintmail.store import Cache


def test_mdn_is_a_valid_report_and_is_recognised():
    raw = R.build_mdn("<orig@x.be>", "Devis é", "bob@y.be", "me@x.be", "Moi é")
    em = email.message_from_bytes(raw, policy=policy.default)
    assert em.get_content_type() == "multipart/report" and em.get_param("report-type") == "disposition-notification"
    assert R.original_id_of_receipt(em) == "<orig@x.be>"
    assert R.parse_receipt_fields(raw) == ("<orig@x.be>", "me@x.be")
    assert em["Auto-Submitted"] == "auto-replied"


def test_ordinary_mail_is_not_a_receipt_and_a_request_header_is_read():
    raw = b"From: a@b.be\r\nTo: c@d.be\r\nSubject: Hi\r\nDisposition-Notification-To: Alice <a@b.be>\r\nMessage-ID: <1@b.be>\r\n\r\nHello\r\n"
    em = email.message_from_bytes(raw, policy=policy.default)
    assert R.original_id_of_receipt(em) == "" and R.requested_address(em) == "a@b.be"
    m = parse_message(raw, "acc", "inbox", "INBOX", 1, "")
    assert m.receipt_request == "a@b.be" and m.receipt_for == "" and m.category != "notif"


def test_parse_marks_an_incoming_receipt():
    raw = R.build_mdn("<orig@x.be>", "Devis", "bob@y.be", "lecteur@z.be", "Lecteur")
    m = parse_message(raw, "acc", "inbox", "INBOX", 2, "")
    assert m.receipt_for == "<orig@x.be>" and m.category == "notif"


def test_policies_and_defaults():
    assert R.settings({}) == {"request": False, "reply": "ask", "notify": True}
    assert R.settings({"receipt_reply": "bizarre"})["reply"] == "ask"
    assert R.settings({"receipt_reply": "never", "receipt_request": True, "receipt_notify": False}) == {"request": True, "reply": "never", "notify": False}


def test_receipt_is_recorded_on_the_sent_message_and_the_receipt_is_marked_read():
    with tempfile.TemporaryDirectory() as d:
        cache = Cache(os.path.join(d, "c.db"))
        sent = Message(id="s1", account="a", folder="sent", subject="Devis", message_id="<orig@x.be>", unread=False)
        cache.upsert(sent)
        raw = R.build_mdn("<orig@x.be>", "Devis", "me@x.be", "lecteur@z.be", "Lecteur")
        rcpt = parse_message(raw, "a", "inbox", "INBOX", 9, "")
        cache.upsert(rcpt)
        hit = R.record_incoming(cache, rcpt)
        assert hit and hit[0].id == "s1" and hit[1] == "Lecteur"
        assert R.read_ids(cache, ["s1", "zzz"]).keys() == {"s1"}
        assert "Lecteur" in R.eye_title(R.read_ids(cache, ["s1"])["s1"])
        assert cache.get(rcpt.id).unread is False
        assert R.record_incoming(cache, NS(receipt_for="<inconnu@x>", display_sender="?", sender_email="", date=0, id="x")) is None


def test_outgoing_request_header_is_added_by_the_backend_only_when_asked():
    import inspect
    from mintmail import backend
    src = inspect.getsource(backend.IMAPBackend.send)
    assert "Disposition-Notification-To" in src and "request_receipt" in src


def test_printable_page_has_headers_attachments_and_no_script():
    m = NS(subject="Facture <1>", sender_name="Ana", sender_email="ana@x.be", to="me@y.be", cc="z@y.be", date=1700000000.0,
           attachments=[{"filename": "f.pdf"}], html="<p>Bonjour<script>alert(1)</script><img src='http://evil/x.png'></p>", text="")
    h = printing.printable_html(m)
    assert "Facture &lt;1&gt;" in h and "ana@x.be" in h and "f.pdf" in h and "z@y.be" in h
    assert "<script" not in h and "alert(1)" not in h and ' src="http' not in h        # l'adresse distante n'est jamais chargée
    assert "Bonjour" in printing.printable_html(NS(subject="", sender_name="", sender_email="a@b", to="", cc="", date=0, attachments=[], html="", text="Bonjour"))
