"""PGP/MIME par gpg : signature, chiffrement, vérification, détection de falsification, intégration à parse_message (clés jetables, jamais les vôtres)."""
import email
import os
import subprocess
import sys
import tempfile
from email import policy
from email.message import EmailMessage

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mintmail import backend, pgp


def keyring():
    h = tempfile.mkdtemp()
    os.chmod(h, 0o700)
    for who in ("Alice <alice@x.be>", "Bob <bob@x.be>"):
        r = subprocess.run(["gpg", "--batch", "--homedir", h, "--passphrase", "", "--quick-generate-key", who, "default", "default", "never"], capture_output=True)
        assert r.returncode == 0, r.stderr
    return h


def mail(subject="Héllo", body="plain ascii line two"):
    em = EmailMessage()
    em["From"], em["To"], em["Subject"], em["Date"] = "Alice <alice@x.be>", "bob@x.be", subject, "Mon, 16 Nov 2026 10:00:00 +0100"
    em.set_content(body)
    em.add_alternative("<p>%s é</p>" % body, subtype="html")
    em.add_attachment(b"\x00\x01data", maintype="application", subtype="octet-stream", filename="f.bin")
    return em


def test_sign_encrypt_verify_decrypt_and_tampering_with_throwaway_keys():
    if not pgp.available():
        return
    h = keyring()
    raw = pgp.protect(mail(), True, False, "alice@x.be", ["bob@x.be"], homedir=h)
    raw.decode("ascii")                                                         # PGP/MIME : tout en 7 bits, en-têtes compris
    m = email.message_from_bytes(raw, policy=policy.default)
    assert pgp.kind_of(m) == "signed" and m["Subject"] == "Héllo"
    assert pgp.verify(raw, h)["sig"] == "good" and pgp.verify(raw, h)["signer"].startswith("Alice")
    assert pgp.verify(raw.replace(b"f.bin", b"g.bin"), h)["sig"] == "bad"       # une pièce jointe modifiée invalide la signature
    # chiffrement (+ signature) : le texte en clair ne figure nulle part dans le message
    for sign in (False, True):
        enc = pgp.protect(mail(body="secret-12345"), sign, True, "alice@x.be", ["bob@x.be"], homedir=h)
        assert b"secret-12345" not in enc and pgp.kind_of(email.message_from_bytes(enc, policy=policy.default)) == "encrypted"
        inner, st = pgp.decrypt(enc, h, interactive=False)
        assert st["decrypted"] == "ok" and (st["sig"] == "good") == sign and b"multipart" in inner
    assert pgp.public_key_missing(["bob@x.be", "nobody@x.be"], h) == ["nobody@x.be"]
    try:
        pgp.protect(mail(), False, True, "alice@x.be", ["nobody@x.be"], homedir=h)
        assert False
    except pgp.PGPError:
        pass
    assert pgp.protect(mail(), False, False, "alice@x.be", []).startswith(b"From:")


def test_incoming_messages_are_labelled_by_parse_message_and_encrypted_ones_are_opened():
    if not pgp.available():
        return
    h = keyring()
    os.environ["GNUPGHOME"] = h
    try:
        signed = pgp.protect(mail(body="ok body"), True, False, "alice@x.be", [], homedir=h)
        m = backend.parse_message(signed, "acc", "inbox", "INBOX", 1, "")
        assert m.security.startswith("✔") and "ok body" in m.text
        bad = backend.parse_message(signed.replace(b"f.bin", b"g.bin"), "acc", "inbox", "INBOX", 2, "")
        assert "invalide" in bad.security
        enc = pgp.protect(mail(body="top secret body"), True, True, "alice@x.be", ["bob@x.be"], homedir=h)
        m = backend.parse_message(enc, "acc", "inbox", "INBOX", 3, "")
        assert m.security.startswith("🔒") and "top secret body" in m.text and m.subject == "Héllo" and m.sender_email == "alice@x.be"
        os.environ["GNUPGHOME"] = tempfile.mkdtemp()                              # sans la clé secrète : message illisible, jamais d'exception
        os.chmod(os.environ["GNUPGHOME"], 0o700)
        m = backend.parse_message(enc, "acc", "inbox", "INBOX", 4, "")
        assert "illisible" in m.security and "chiffré" in m.text.lower()
        plain = backend.parse_message(mail().as_bytes(), "acc", "inbox", "INBOX", 5, "")
        assert plain.security == ""
    finally:
        os.environ.pop("GNUPGHOME", None)
