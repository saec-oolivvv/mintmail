"""Connexion sécurisée OAuth 2.0 (Google, Microsoft) : flux « application de bureau » avec PKCE et retour local.

MintMail ne peut pas embarquer d'identifiant client commun : chaque utilisateur enregistre SA propre application
(console Google Cloud / portail Azure, gratuit) et colle l'identifiant dans Paramètres → Comptes. Le jeton d'actualisation
est stocké comme un mot de passe (trousseau) ; les jetons d'accès restent en mémoire.
"""
import base64
import hashlib
import http.server
import ipaddress
import json
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Dict, Optional

PROVIDERS: Dict[str, Dict] = {
    "google": {
        "label": "Google (Gmail)", "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token", "scopes": "https://mail.google.com/ openid email",
        "extra": {"access_type": "offline", "prompt": "consent"},
        "imap": ("imap.gmail.com", 993), "smtp": ("smtp.gmail.com", 587),
        "help": "console.cloud.google.com → API et services → Identifiants → ID client OAuth (type « Application de bureau »)",
    },
    "microsoft": {
        "label": "Microsoft (Outlook / 365)", "auth_url": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        "token_url": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        "scopes": "https://outlook.office.com/IMAP.AccessAsUser.All https://outlook.office.com/SMTP.Send offline_access openid email profile",
        "extra": {"prompt": "select_account"},
        "imap": ("outlook.office365.com", 993), "smtp": ("smtp.office365.com", 587),
        "help": "portal.azure.com → Inscriptions d'applications → Nouvelle (client public, URI de redirection « http://localhost »)",
    },
}


class OAuthError(Exception):
    pass


SYSTEM_CLIENTS = "/etc/mintmail/oauth-clients.json"

# Assistant de configuration : étapes à faire UNE FOIS chez le fournisseur (libellé, adresse exacte à ouvrir)
WIZARD: Dict[str, list] = {
    "google": [
        ("Créer un projet nommé « MintMail »", "https://console.cloud.google.com/projectcreate"),
        ("Activer « Google Calendar API » (pour l'agenda ; facultatif pour le courrier seul)",
         "https://console.cloud.google.com/apis/library/calendar-json.googleapis.com"),
        ("Écran de consentement : type « Externe », nom « MintMail », votre e-mail ; ajoutez les portées https://mail.google.com/ et "
         ".../auth/calendar.events ; ajoutez-vous comme utilisateur test ; puis « Publier l'application » (sinon le jeton expire après 7 jours)",
         "https://console.cloud.google.com/apis/credentials/consent"),
        ("Créer l'identifiant : type « Application de bureau », nom « MintMail », puis copier l'ID client et le secret",
         "https://console.cloud.google.com/apis/credentials/oauthclient"),
    ],
    "microsoft": [
        ("Nouvelle inscription : nom « MintMail », comptes de tous annuaires + comptes Microsoft personnels, URI de redirection de type "
         "« Client public » : http://localhost",
         "https://entra.microsoft.com/#view/Microsoft_AAD_RegisteredApps/CreateApplicationBlade/isMSAApp~/false"),
        ("Autorisations d'API → Exchange Online : IMAP.AccessAsUser.All et SMTP.Send (+ offline_access), puis copier l'ID d'application (client)",
         "https://entra.microsoft.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade"),
    ],
}


def default_clients(path: Optional[str] = None) -> Dict[str, Dict[str, str]]:
    """Identifiants préinstallés pour tous les utilisateurs de la machine (/etc/mintmail/oauth-clients.json) : permet de
    déployer MintMail sans que chacun ne configure Google ou Microsoft. Fichier invalide : ignoré."""
    try:
        with open(path or SYSTEM_CLIENTS, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    out = {}
    if isinstance(data, dict):
        for prov, c in data.items():
            if (prov in PROVIDERS and isinstance(c, dict) and isinstance(c.get("client_id"), str) and c["client_id"].strip()
                    and isinstance(c.get("client_secret", ""), str)):
                out[prov] = {"client_id": c["client_id"].strip()[:300], "client_secret": c.get("client_secret", "").strip()[:300]}
    return out


def client_for(config, provider: str) -> Dict[str, str]:
    """Identifiant client à utiliser : celui saisi par l'utilisateur (synchronisé entre ses machines), sinon celui de la machine."""
    c = (config.get("oauth_clients") or {}).get(provider) or {}
    return c if c.get("client_id") else default_clients().get(provider, {})


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def pkce_pair():
    verifier = _b64url(secrets.token_bytes(48))
    return verifier, _b64url(hashlib.sha256(verifier.encode()).digest())


def build_auth_url(provider: str, client_id: str, redirect_uri: str, state: str, challenge: str, login_hint: str = "",
                   extra_scopes=()) -> str:
    p = PROVIDERS[provider]
    q = {"client_id": client_id, "redirect_uri": redirect_uri, "response_type": "code",
         "scope": " ".join([p["scopes"]] + list(extra_scopes)),
         "state": state, "code_challenge": challenge, "code_challenge_method": "S256"}
    q.update(p["extra"])
    if extra_scopes:
        q["include_granted_scopes"] = "true"       # on AJOUTE une autorisation (agenda) sans retirer celles déjà accordées
    if login_hint:
        q["login_hint"] = login_hint
    return p["auth_url"] + "?" + urllib.parse.urlencode(q)


def _loopback(url: str) -> bool:
    try:
        return ipaddress.ip_address(urllib.parse.urlparse(url).hostname or "").is_loopback
    except ValueError:
        return False


def post_form(url: str, data: Dict[str, str], timeout: float = 20.0) -> Dict:
    if not (url.startswith("https://") or _loopback(url)):
        raise OAuthError("le serveur d'authentification doit utiliser HTTPS")
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(), method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8"))
            raise OAuthError("%s : %s" % (body.get("error", "erreur %d" % e.code), body.get("error_description", ""))[:240])
        except (ValueError, UnicodeDecodeError):
            raise OAuthError("erreur HTTP %d" % e.code)
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise OAuthError("connexion impossible : %s" % getattr(e, "reason", e))


def exchange_code(provider: str, client_id: str, client_secret: str, code: str, redirect_uri: str, verifier: str) -> Dict:
    data = {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri, "client_id": client_id,
            "code_verifier": verifier}
    if client_secret:
        data["client_secret"] = client_secret
    res = post_form(PROVIDERS[provider]["token_url"], data)
    if "access_token" not in res:
        raise OAuthError("réponse sans jeton d'accès")
    return res


def refresh_access_token(provider: str, client_id: str, client_secret: str, refresh_token: str) -> Dict:
    data = {"grant_type": "refresh_token", "refresh_token": refresh_token, "client_id": client_id}
    if client_secret:
        data["client_secret"] = client_secret
    res = post_form(PROVIDERS[provider]["token_url"], data)
    if "access_token" not in res:
        raise OAuthError("actualisation refusée")
    return res


def xoauth2(user: str, token: str) -> str:
    """Chaîne d'authentification XOAUTH2 (IMAP / SMTP)."""
    return "user=%s\x01auth=Bearer %s\x01\x01" % (user, token)


def email_from_id_token(id_token: str) -> str:
    """Adresse du compte lue dans l'id_token (reçu directement du serveur de jetons, en HTTPS)."""
    try:
        payload = id_token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        return str(claims.get("email") or claims.get("preferred_username") or "")
    except (IndexError, ValueError):
        return ""


_PAGE = ("<html><head><meta charset='utf-8'><title>MintMail</title></head><body style='font-family:sans-serif;text-align:center;"
         "padding-top:15vh'><h2>%s</h2><p>Vous pouvez fermer cet onglet et revenir à MintMail.</p></body></html>")


def run_loopback_flow(provider: str, client_id: str, client_secret: str, open_url: Callable[[str], None],
                      login_hint: str = "", timeout: float = 180.0, extra_scopes=()) -> Dict:
    """Ouvre le navigateur, attend le retour sur http://127.0.0.1:<port>/ (état vérifié), échange le code. Retourne les jetons
    (+ « email » si disponible). Bloquant : à lancer dans un thread."""
    if not client_id:
        raise OAuthError("identifiant client OAuth manquant (Paramètres → Comptes)")
    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(24)
    got: Dict[str, str] = {}
    done = threading.Event()

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if "code" in q or "error" in q:
                got.update({k: v[0] for k, v in q.items()})
                ok = "code" in q and q.get("state", [""])[0] == state
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write((_PAGE % ("Connexion réussie ✔" if ok else "Connexion refusée")).encode("utf-8"))
                done.set()
            else:
                self.send_response(404)
                self.end_headers()

    srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    redirect = "http://127.0.0.1:%d/" % srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        open_url(build_auth_url(provider, client_id, redirect, state, challenge, login_hint, extra_scopes))
        if not done.wait(timeout):
            raise OAuthError("délai dépassé : connexion non terminée dans le navigateur")
    finally:
        srv.shutdown()
        srv.server_close()
    if got.get("error"):
        raise OAuthError("refusé : %s" % got.get("error_description", got["error"]))
    if got.get("state") != state:
        raise OAuthError("réponse invalide (état différent) : connexion annulée par sécurité")
    res = exchange_code(provider, client_id, client_secret, got["code"], redirect, verifier)
    res["email"] = email_from_id_token(res.get("id_token", ""))
    return res


class TokenManager:
    """Jetons d'accès en mémoire, actualisés à la demande avec le jeton d'actualisation du trousseau."""
    def __init__(self, config):
        self.config = config
        self._cache: Dict[str, tuple] = {}
        self._lock = threading.Lock()

    def access_token(self, account: Dict) -> str:
        aid = account["id"]
        with self._lock:
            tok, exp = self._cache.get(aid, ("", 0.0))
            if tok and exp > time.time() + 60:
                return tok
            provider = account.get("oauth_provider")
            client = client_for(self.config, provider)
            rt = self.config.password(aid)
            if provider not in PROVIDERS or not client.get("client_id") or not rt:
                raise OAuthError("connexion OAuth incomplète : reconnectez le compte (Paramètres → Comptes)")
            res = refresh_access_token(provider, client["client_id"], client.get("client_secret", ""), rt)
            if res.get("refresh_token") and res["refresh_token"] != rt:
                self.config.set_password(aid, res["refresh_token"])
            tok = res["access_token"]
            self._cache[aid] = (tok, time.time() + float(res.get("expires_in", 3600)))
            return tok


_MANAGERS: Dict[int, TokenManager] = {}


def manager_for(config) -> TokenManager:
    return _MANAGERS.setdefault(id(config), TokenManager(config))
