"""Signature, chiffrement et vérification des messages au format PGP/MIME (RFC 3156), par GnuPG (gpg) : MintMail ne manipule jamais vos clés,
c'est gpg (et son agent, qui demande la phrase secrète) qui s'en charge. Module SANS Qt, testable partout. Tout est facultatif : sans gpg, rien ne change."""
import email
import os
import re
import shutil
import subprocess
import tempfile
from email import policy
from email.message import EmailMessage
from typing import Dict, List, Optional, Tuple

from .i18n import tr

GPG_TIMEOUT = 90                         # secondes (phrase secrète demandée par pinentry)
SMTP7 = policy.SMTP.clone(cte_type="7bit")       # PGP/MIME : contenu en 7 bits (quoted-printable / base64), jamais en 8 bits


class PGPError(Exception):
    pass


def gpg_path() -> Optional[str]:
    return shutil.which("gpg2") or shutil.which("gpg")


def available() -> bool:
    return gpg_path() is not None


def _run(args: List[str], data: bytes = b"", homedir: Optional[str] = None, timeout: int = GPG_TIMEOUT) -> Tuple[int, bytes, str]:
    exe = gpg_path()
    if not exe:
        raise PGPError(tr("GnuPG (gpg) n'est pas installé."))
    cmd = [exe, "--batch", "--no-tty", "--status-fd", "2"] + (["--homedir", homedir] if homedir else []) + args
    try:
        r = subprocess.run(cmd, input=data, capture_output=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as e:
        raise PGPError(tr("GnuPG a échoué : %s") % e)
    return r.returncode, r.stdout, r.stderr.decode("utf-8", "replace")


def _crlf(b: bytes) -> bytes:
    return re.sub(rb"\r?\n", b"\r\n", b)


def _addr(s: str) -> str:
    m = re.search(r"<([^>]+)>", s or "")
    return (m.group(1) if m else (s or "")).strip().lower()


def has_secret_key(addr: str, homedir=None) -> bool:
    rc, out, _ = _run(["--list-secret-keys", "--with-colons", addr], homedir=homedir, timeout=30)
    return rc == 0 and b"\nsec:" in (b"\n" + out)


def public_key_missing(recipients: List[str], homedir=None) -> List[str]:
    """Destinataires pour lesquels gpg n'a pas de clé publique utilisable."""
    missing = []
    for r in recipients:
        rc, out, _ = _run(["--list-keys", "--with-colons", r], homedir=homedir, timeout=30)
        if rc != 0 or b"\npub:" not in (b"\n" + out):
            missing.append(r)
    return missing


# ------------------------------------------------------------------ construction
def _split(em: EmailMessage) -> Tuple[List[bytes], List[bytes], bytes]:
    """(en-têtes d'adressage, en-têtes du contenu, corps) du message sérialisé en 7 bits (en-têtes non ASCII encodés)."""
    raw = em.as_bytes(policy=SMTP7)
    head, _, body = raw.partition(b"\r\n\r\n")
    groups: List[bytes] = []
    for line in head.split(b"\r\n"):
        if line[:1] in (b" ", b"\t") and groups:
            groups[-1] += b"\r\n" + line
        else:
            groups.append(line)
    content = [g for g in groups if re.match(rb"(?i)(content-|mime-version)", g)]
    return [g for g in groups if g not in content], content, body


def _assemble(em: EmailMessage, ctype: str, body: bytes) -> bytes:
    """En-têtes d'adressage d'origine + Content-Type de l'enveloppe PGP/MIME + corps."""
    addr, _content, _body = _split(em)
    return b"\r\n".join(addr + [b"MIME-Version: 1.0", ctype.encode("ascii"), b"", b""]) + body


def protect(em: EmailMessage, sign: bool, encrypt: bool, from_addr: str, recipients: List[str], homedir=None) -> bytes:
    """Message complet (octets) signé et/ou chiffré en PGP/MIME. `em` : message ordinaire (en-têtes + contenu)."""
    if not (sign or encrypt):
        return em.as_bytes(policy=SMTP7)
    inner_bytes = _crlf(_content_bytes(em))
    boundary = "=-pgp-" + os.urandom(12).hex()
    if encrypt and not sign:
        data = _encrypt(inner_bytes, from_addr, recipients, False, homedir)
    elif encrypt:
        data = _encrypt(inner_bytes, from_addr, recipients, True, homedir)
    else:
        sig = _detach_sign(inner_bytes, from_addr, homedir)
        body = (b"--" + boundary.encode() + b"\r\n" + inner_bytes + b"\r\n--" + boundary.encode() + b"\r\n"
                b'Content-Type: application/pgp-signature; name="signature.asc"\r\n'
                b"Content-Description: OpenPGP digital signature\r\n"
                b'Content-Disposition: attachment; filename="signature.asc"\r\n\r\n' + _crlf(sig) + b"\r\n--" + boundary.encode() + b"--\r\n")
        return _assemble(em, 'Content-Type: multipart/signed; protocol="application/pgp-signature"; micalg=pgp-sha256; boundary="%s"' % boundary, body)  # i18n: skip
    body = (b"--" + boundary.encode() + b"\r\nContent-Type: application/pgp-encrypted\r\nContent-Description: PGP/MIME version identification\r\n\r\nVersion: 1\r\n\r\n"
            b"--" + boundary.encode() + b'\r\nContent-Type: application/octet-stream; name="encrypted.asc"\r\n'
            b"Content-Description: OpenPGP encrypted message\r\n"
            b'Content-Disposition: inline; filename="encrypted.asc"\r\n\r\n' + _crlf(data) + b"\r\n--" + boundary.encode() + b"--\r\n")
    return _assemble(em, 'Content-Type: multipart/encrypted; protocol="application/pgp-encrypted"; boundary="%s"' % boundary, body)


def _content_bytes(em: EmailMessage) -> bytes:
    """Le contenu du message (ses en-têtes MIME + son corps), sans les en-têtes d'adressage."""
    _addr_h, content, body = _split(em)
    return b"\r\n".join(content) + b"\r\n\r\n" + body


def _detach_sign(data: bytes, from_addr: str, homedir=None) -> bytes:
    rc, out, err = _run(["--armor", "--detach-sign", "--local-user", from_addr, "--digest-algo", "SHA256"], data, homedir)
    if rc != 0 or b"BEGIN PGP SIGNATURE" not in out:
        raise PGPError(tr("Signature impossible : %s") % _brief(err))
    return out


def _encrypt(data: bytes, from_addr: str, recipients: List[str], sign: bool, homedir=None) -> bytes:
    rcpt = sorted({_addr(r) for r in recipients if r})
    me = _addr(from_addr)
    args = ["--armor", "--encrypt", "--trust-model", "always"]
    if me and me not in rcpt and has_secret_key(me, homedir):
        rcpt.append(me)                                              # lisible aussi dans vos « Envoyés »
    if not rcpt:
        raise PGPError(tr("Aucun destinataire pour le chiffrement."))
    for r in rcpt:
        args += ["--recipient", r]
    if sign:
        args += ["--sign", "--local-user", from_addr, "--digest-algo", "SHA256"]
    rc, out, err = _run(args, data, homedir)
    if rc != 0 or b"BEGIN PGP MESSAGE" not in out:
        raise PGPError(tr("Chiffrement impossible : %s") % _brief(err))
    return out


def _brief(err: str) -> str:
    lines = [l for l in err.splitlines() if not l.startswith("[GNUPG:]") and l.strip()]
    return (lines[-1] if lines else "?")[:200]


# ------------------------------------------------------------------ lecture
def _status(err: str) -> Dict[str, str]:
    st = {"sig": "none", "signer": "", "decrypted": ""}
    for line in err.splitlines():
        if not line.startswith("[GNUPG:] "):
            continue
        parts = line[9:].split(" ", 2)
        key = parts[0]
        if key == "GOODSIG":
            st["sig"], st["signer"] = "good", (parts[2] if len(parts) > 2 else "")
        elif key == "BADSIG":
            st["sig"], st["signer"] = "bad", (parts[2] if len(parts) > 2 else "")
        elif key in ("ERRSIG", "NO_PUBKEY") and st["sig"] == "none":
            st["sig"] = "unknown"
        elif key == "DECRYPTION_OKAY":
            st["decrypted"] = "ok"
        elif key in ("DECRYPTION_FAILED", "NO_SECKEY") and not st["decrypted"]:
            st["decrypted"] = "failed"
    return st


def kind_of(em) -> str:
    """'signed', 'encrypted' ou '' selon la structure du message (aucun appel à gpg)."""
    ct = em.get_content_type() if hasattr(em, "get_content_type") else ""
    proto = (em.get_param("protocol") or "").lower() if ct.startswith("multipart/") else ""
    if ct == "multipart/signed" and proto == "application/pgp-signature":
        return "signed"
    if ct == "multipart/encrypted" and proto == "application/pgp-encrypted":
        return "encrypted"
    return ""


def _signed_parts(raw: bytes, boundary: str) -> Tuple[bytes, bytes]:
    """(contenu signé exact, signature) d'un multipart/signed, découpés dans les octets d'origine."""
    b = b"--" + boundary.encode()
    segs = _crlf(raw).split(b"\r\n" + b)
    if len(segs) < 3:
        # le premier délimiteur peut être en tout début de corps
        head, _, body = _crlf(raw).partition(b"\r\n\r\n")
        segs = (b"\r\n" + body).split(b"\r\n" + b)
    first, second = segs[1], segs[2]
    signed = first[2:] if first.startswith(b"\r\n") else first                          # retire la fin de ligne du délimiteur
    sig_part = second[2:] if second.startswith(b"\r\n") else second
    sig_msg = email.message_from_bytes(sig_part, policy=policy.default)
    return signed, (sig_msg.get_payload(decode=True) or b"")


def verify(raw: bytes, homedir=None) -> Dict[str, str]:
    """Vérifie un multipart/signed : {'sig': 'good'|'bad'|'unknown'|'none', 'signer': …}."""
    em = email.message_from_bytes(raw, policy=policy.default)
    if kind_of(em) != "signed" or not available():
        return {"sig": "none", "signer": "", "decrypted": ""}
    try:
        signed, sig = _signed_parts(raw, em.get_boundary())
    except Exception:
        return {"sig": "bad", "signer": "", "decrypted": ""}
    with tempfile.TemporaryDirectory(prefix="mintmail-pgp-") as d:
        sp, dp = os.path.join(d, "s.asc"), os.path.join(d, "d")
        open(sp, "wb").write(sig)
        open(dp, "wb").write(signed)
        _rc, _out, err = _run(["--verify", sp, dp], homedir=homedir, timeout=60)
    return _status(err)


def decrypt(raw: bytes, homedir=None, interactive=True) -> Tuple[Optional[bytes], Dict[str, str]]:
    """Déchiffre un multipart/encrypted : (message interne en octets ou None, état). `interactive` : autorise la demande de phrase secrète."""
    em = email.message_from_bytes(raw, policy=policy.default)
    if kind_of(em) != "encrypted" or not available():
        return None, {"sig": "none", "signer": "", "decrypted": ""}
    parts = [p for p in em.iter_parts()]
    if len(parts) < 2:
        return None, {"sig": "none", "signer": "", "decrypted": "failed"}
    data = parts[1].get_payload(decode=True) or b""
    args = ["--decrypt"] + ([] if interactive else ["--pinentry-mode", "error"])
    rc, out, err = _run(args, data, homedir)
    st = _status(err)
    if rc != 0 and st["decrypted"] != "ok":
        st["decrypted"] = "failed"
        return None, st
    return out, st


def label(st: Dict[str, str], kind: str) -> str:
    """Texte court pour la liste / le lecteur."""
    if kind == "encrypted":
        base = tr("🔒 Chiffré") if st.get("decrypted") == "ok" else tr("🔒 Chiffré (illisible ici)")
        if st.get("decrypted") == "ok" and st.get("sig") == "good":
            return base + " · " + tr("signature valide")
        if st.get("sig") == "bad":
            return base + " · " + tr("signature invalide")
        return base
    return {"good": tr("✔ Signature valide"), "bad": tr("✖ Signature invalide"), "unknown": tr("Signé (clé inconnue)")}.get(st.get("sig", ""), "")
