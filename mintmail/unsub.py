"""Désabonnement en un clic (RFC 8058) ou par e-mail, depuis l'en-tête List-Unsubscribe."""
import ipaddress
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List, Tuple
from .i18n import tr


def parse_list_unsubscribe(header: str) -> Dict[str, List[str]]:
    """{'https': [urls], 'mailto': [uris]} depuis « <https://…>, <mailto:…> »."""
    out = {"https": [], "mailto": []}
    for m in re.findall(r"<([^>]+)>", header or ""):
        m = m.strip()
        if m.lower().startswith("https://"):
            out["https"].append(m)
        elif m.lower().startswith("mailto:"):
            out["mailto"].append(m)
    return out


_ADDR = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
_CTRL = re.compile(r"[\x00-\x1f\x7f]")


def mailto_fields(uri: str) -> Tuple[str, str, str]:
    """(destinataire, objet, corps) d'un lien mailto:. Une SEULE adresse valide est acceptée (sinon destinataire vide) :
    un en-tête malveillant ne doit pas faire écrire depuis votre compte à plusieurs inconnus, ni injecter d'en-têtes."""
    u = urllib.parse.urlparse(uri)
    q = urllib.parse.parse_qs(u.query)
    to = urllib.parse.unquote(u.path).strip()
    if not _ADDR.match(to) or any(k.lower() in ("cc", "bcc", "to") for k in q):
        to = ""
    clean = lambda s, n: _CTRL.sub(" ", s)[:n]
    return (to, clean((q.get("subject") or ["unsubscribe"])[0], 200), clean((q.get("body") or ["unsubscribe"])[0], 500))


def public_host(url: str) -> bool:
    """Adresse web dont TOUTES les résolutions DNS sont publiques (pas de bouclage, réseau privé, lien local, métadonnées cloud) et
    sans identifiants dans l'URL : évite qu'un message fasse émettre une requête vers votre réseau interne (SSRF)."""
    p = urllib.parse.urlparse(url)
    if p.username or p.password or not p.hostname:
        return False
    try:
        infos = socket.getaddrinfo(p.hostname, p.port or 443, proto=socket.IPPROTO_TCP)
    except OSError:
        return False
    return bool(infos) and all(ipaddress.ip_address(i[4][0]).is_global for i in infos)


class _HttpsOnlyRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.lower().startswith("https://") or not public_host(newurl):
            raise urllib.error.URLError(tr("redirection non sécurisée refusée"))
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _loopback(url: str) -> bool:
    try:
        return ipaddress.ip_address(urllib.parse.urlparse(url).hostname or "").is_loopback
    except ValueError:
        return False


def one_click_post(url: str, timeout: float = 15.0, allow_loopback_http: bool = False) -> Tuple[bool, str]:
    """POST « List-Unsubscribe=One-Click » (RFC 8058). HTTPS obligatoire (HTTP seulement vers le bouclage, pour les tests)."""
    if not (url.lower().startswith("https://") or (allow_loopback_http and _loopback(url))):
        return False, tr("adresse non sécurisée")
    if not allow_loopback_http and not public_host(url):
        return False, tr("adresse interne ou non publique refusée")
    req = urllib.request.Request(url, data=b"List-Unsubscribe=One-Click", method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "MintMail"})
    try:
        with urllib.request.build_opener(_HttpsOnlyRedirect).open(req, timeout=timeout) as r:
            return 200 <= r.status < 300, "HTTP %d" % r.status
    except urllib.error.HTTPError as e:
        return False, "HTTP %d" % e.code
    except (urllib.error.URLError, OSError) as e:
        return False, str(getattr(e, "reason", e))[:100]
