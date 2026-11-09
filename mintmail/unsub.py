"""Désabonnement en un clic (RFC 8058) ou par e-mail, depuis l'en-tête List-Unsubscribe."""
import ipaddress
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List, Tuple


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


def mailto_fields(uri: str) -> Tuple[str, str, str]:
    """(destinataire, objet, corps) d'un lien mailto:."""
    u = urllib.parse.urlparse(uri)
    q = urllib.parse.parse_qs(u.query)
    return (urllib.parse.unquote(u.path), (q.get("subject") or ["unsubscribe"])[0][:200], (q.get("body") or ["unsubscribe"])[0][:500])


class _HttpsOnlyRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.lower().startswith("https://"):
            raise urllib.error.URLError("redirection non sécurisée refusée")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _loopback(url: str) -> bool:
    try:
        return ipaddress.ip_address(urllib.parse.urlparse(url).hostname or "").is_loopback
    except ValueError:
        return False


def one_click_post(url: str, timeout: float = 15.0, allow_loopback_http: bool = False) -> Tuple[bool, str]:
    """POST « List-Unsubscribe=One-Click » (RFC 8058). HTTPS obligatoire (HTTP seulement vers le bouclage, pour les tests)."""
    if not (url.lower().startswith("https://") or (allow_loopback_http and _loopback(url))):
        return False, "adresse non sécurisée"
    req = urllib.request.Request(url, data=b"List-Unsubscribe=One-Click", method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "MintMail"})
    try:
        with urllib.request.build_opener(_HttpsOnlyRedirect).open(req, timeout=timeout) as r:
            return 200 <= r.status < 300, "HTTP %d" % r.status
    except urllib.error.HTTPError as e:
        return False, "HTTP %d" % e.code
    except (urllib.error.URLError, OSError) as e:
        return False, str(getattr(e, "reason", e))[:100]
