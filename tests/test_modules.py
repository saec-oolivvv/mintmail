"""Briques sans interface : OAuth (PKCE, retour local, jetons), invitations iCalendar, désabonnement, CalDAV, vCard."""
import base64, hashlib, http.server, json, os, sys, tempfile, threading, time, urllib.parse, urllib.request
tmp = tempfile.mkdtemp()
os.environ["XDG_DATA_HOME"] = tmp
os.environ["XDG_CONFIG_HOME"] = tmp
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mintmail import caldav, contacts, ical, oauth, unsub
from mintmail.store import Config


class Server:
    """Petit serveur HTTP local qui enregistre les requêtes et répond selon un routeur."""
    def __init__(self, handler_fn):
        outer = self
        self.requests = []

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def _go(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n).decode() if n else ""
                outer.requests.append((self.command, self.path, dict(self.headers), body))
                code, ctype, payload, extra = handler_fn(self.command, self.path, self.headers, body)
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                for k, v in extra.items(): self.send_header(k, v)
                self.end_headers()
                self.wfile.write(payload if isinstance(payload, bytes) else payload.encode())
            do_GET = do_POST = do_PUT = do_OPTIONS = _go
        self.srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        self.url = "http://127.0.0.1:%d" % self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self): self.srv.shutdown(); self.srv.server_close()


def test_pkce_and_auth_url_and_xoauth2():
    # vecteur de test de la RFC 7636
    v = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert oauth._b64url(hashlib.sha256(v.encode()).digest()) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    ver, ch = oauth.pkce_pair()
    assert 43 <= len(ver) <= 128 and ch == oauth._b64url(hashlib.sha256(ver.encode()).digest())
    url = oauth.build_auth_url("google", "CID", "http://127.0.0.1:1234/", "ST", ch, "moi@gmail.com")
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert q["client_id"] == ["CID"] and q["code_challenge_method"] == ["S256"] and q["access_type"] == ["offline"]
    assert "mail.google.com" in q["scope"][0] and q["login_hint"] == ["moi@gmail.com"] and q["state"] == ["ST"]
    assert oauth.xoauth2("a@b.be", "TOK") == "user=a@b.be\x01auth=Bearer TOK\x01\x01"
    idt = "x." + base64.urlsafe_b64encode(json.dumps({"email": "moi@gmail.com"}).encode()).decode().rstrip("=") + ".y"
    assert oauth.email_from_id_token(idt) == "moi@gmail.com" and oauth.email_from_id_token("n'importe quoi") == ""


def test_loopback_flow_end_to_end_state_check_and_refresh():
    calls = {"n": 0}

    def token_endpoint(method, path, headers, body):
        f = urllib.parse.parse_qs(body)
        calls["n"] += 1
        if f["grant_type"] == ["authorization_code"]:
            assert f["code"] == ["CODE123"] and f["code_verifier"] and f["client_id"] == ["CID"]
            idt = "h." + base64.urlsafe_b64encode(json.dumps({"email": "moi@gmail.com"}).encode()).decode().rstrip("=") + ".s"
            return 200, "application/json", json.dumps({"access_token": "AT1", "refresh_token": "RT1", "expires_in": 3600, "id_token": idt}), {}
        assert f["grant_type"] == ["refresh_token"] and f["refresh_token"] == ["RT1"]
        return 200, "application/json", json.dumps({"access_token": "AT2", "expires_in": 3600}), {}
    srv = Server(token_endpoint)
    orig = oauth.PROVIDERS["google"]["token_url"]
    oauth.PROVIDERS["google"]["token_url"] = srv.url + "/token"
    try:
        def browser(auth_url):          # simule l'utilisateur qui accepte dans le navigateur
            q = urllib.parse.parse_qs(urllib.parse.urlparse(auth_url).query)
            cb = q["redirect_uri"][0] + "?" + urllib.parse.urlencode({"code": "CODE123", "state": q["state"][0]})
            threading.Thread(target=lambda: urllib.request.urlopen(cb, timeout=5).read(), daemon=True).start()
        res = oauth.run_loopback_flow("google", "CID", "SECRET", browser, timeout=10)
        assert res["access_token"] == "AT1" and res["refresh_token"] == "RT1" and res["email"] == "moi@gmail.com"

        def evil_browser(auth_url):     # état falsifié : refusé par sécurité
            q = urllib.parse.parse_qs(urllib.parse.urlparse(auth_url).query)
            cb = q["redirect_uri"][0] + "?code=CODE123&state=FAUX"
            threading.Thread(target=lambda: urllib.request.urlopen(cb, timeout=5).read(), daemon=True).start()
        try:
            oauth.run_loopback_flow("google", "CID", "", evil_browser, timeout=10); raise SystemExit("état falsifié accepté")
        except oauth.OAuthError as e:
            assert "état" in str(e)
        try:
            oauth.run_loopback_flow("google", "", "", browser); raise SystemExit("sans identifiant client")
        except oauth.OAuthError:
            pass
        # jetons : actualisation à la demande, mise en cache, jeton d'actualisation lu dans le trousseau
        c = Config(os.path.join(tmp, "oa.json"))
        c.data["oauth_clients"] = {"google": {"client_id": "CID", "client_secret": "S"}}
        c.set_password("acc9", "RT1")
        tm = oauth.TokenManager(c)
        acc = {"id": "acc9", "oauth_provider": "google"}
        assert tm.access_token(acc) == "AT2" and tm.access_token(acc) == "AT2" and calls["n"] == 2     # 2e appel : cache
        tm._cache.clear(); c.set_password("acc9", "")
        try:
            tm.access_token(acc); raise SystemExit("sans jeton d'actualisation")
        except oauth.OAuthError:
            pass
    finally:
        oauth.PROVIDERS["google"]["token_url"] = orig
        srv.close()
    try:
        oauth.post_form("http://exemple.com/token", {}); raise SystemExit("HTTP public accepté")
    except oauth.OAuthError:
        pass


def test_invitation_parsing_and_reply():
    ics = ("BEGIN:VCALENDAR\r\nMETHOD:REQUEST\r\nBEGIN:VEVENT\r\nUID:abc-123@x\r\nSUMMARY:Point projet\\, CRM\r\nDTSTART:20261112T140000\r\n"
           "DTEND:20261112T150000\r\nLOCATION:Salle A\r\nORGANIZER;CN=\"Marie Dupont\":mailto:marie@x.be\r\nATTENDEE:mailto:moi@x.be\r\n"
           "SEQUENCE:2\r\nDESCRIPTION:Ordre du jour\\nPoint 1\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
    inv = ical.parse_invite(ics)
    assert inv["method"] == "REQUEST" and inv["title"] == "Point projet, CRM" and inv["start"] == "2026-11-12T14:00"
    assert inv["organizer"] == "marie@x.be" and inv["organizer_name"] == "Marie Dupont" and inv["sequence"] == 2
    reply = ical.build_reply(inv, "moi@x.be", "Moi", "accept")
    assert "METHOD:REPLY" in reply and "PARTSTAT=ACCEPTED" in reply and "UID:abc-123@x" in reply and "ORGANIZER:mailto:marie@x.be" in reply
    assert "PARTSTAT=DECLINED" in ical.build_reply(inv, "moi@x.be", "", "decline")
    assert ical.reply_subject(inv, "accept") == "Accepté : Point projet, CRM"
    assert ical.parse_invite("pas du tout un ics") is None and ical.parse_invite("BEGIN:VEVENT\r\nSUMMARY:x\r\nEND:VEVENT") is None


def test_unsubscribe_one_click_and_mailto():
    p = unsub.parse_list_unsubscribe("<mailto:u@x.be?subject=stop&body=please>, <https://x.be/u?t=1>, <http://pas-sur.be>")
    assert p["https"] == ["https://x.be/u?t=1"] and p["mailto"] == ["mailto:u@x.be?subject=stop&body=please"]
    assert unsub.mailto_fields(p["mailto"][0]) == ("u@x.be", "stop", "please")
    srv = Server(lambda m, path, h, b: (200, "text/plain", "ok", {}) if path == "/ok" else (302, "text/plain", "", {"Location": "http://evil.example/x"}) if path == "/redir" else (410, "text/plain", "", {}))
    try:
        ok, detail = unsub.one_click_post(srv.url + "/ok", allow_loopback_http=True)
        assert ok and detail == "HTTP 200"
        method, path, headers, body = srv.requests[0]
        assert method == "POST" and body == "List-Unsubscribe=One-Click" and "x-www-form-urlencoded" in headers["Content-Type"]
        assert unsub.one_click_post(srv.url + "/gone", allow_loopback_http=True) == (False, "HTTP 410")
        ok, detail = unsub.one_click_post(srv.url + "/redir", allow_loopback_http=True)
        assert not ok                                                              # redirection vers http refusée
        assert unsub.one_click_post("http://exemple.com/u")[0] is False             # HTTP public refusé
    finally:
        srv.close()


def test_caldav_put_and_test():
    store = {}

    def dav(method, path, headers, body):
        if headers.get("Authorization") != "Basic " + base64.b64encode(b"moi:mdp").decode():
            return 401, "text/plain", "", {}
        if method == "PUT":
            store[path] = body
            return 201, "text/plain", "", {}
        return 200, "text/plain", "", {"DAV": "1, calendar-access"}
    srv = Server(dav)
    try:
        ok, d = caldav.put_event(srv.url + "/cal/", "moi", "mdp", "BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n", "uid 1@x")
        assert ok and "/cal/uid_1_x.ics" in store and "text/calendar" in srv.requests[0][2]["Content-Type"]
        assert caldav.put_event(srv.url + "/cal/", "moi", "FAUX", "x", "u") == (False, "HTTP 401 identifiants refusés")
        assert caldav.test_connection(srv.url + "/cal/", "moi", "mdp") == (True, "connecté (CalDAV : 1, calendar-access)")
        assert caldav.put_event("http://exemple.com/cal", "a", "b", "x", "u")[0] is False
    finally:
        srv.close()


def test_contacts_parsing_and_vcard_roundtrip():
    assert contacts.parse_addresses('"Dupont, Marie" <Marie@X.be>, pas une adresse, bob@y.org') == [("Dupont, Marie", "marie@x.be"), ("", "bob@y.org")]
    vcf = ("BEGIN:VCARD\r\nVERSION:3.0\r\nN:Dupont;Marie;;;\r\nEMAIL;TYPE=work:marie@x.be\r\nTEL:+32 475 00 00 00\r\nORG:Alpha\\; SPRL\r\n"
           "NOTE:VIP\\nclient\r\nEND:VCARD\r\nBEGIN:VCARD\r\nFN:Sans mail\r\nEND:VCARD\r\n")
    cs = contacts.parse_vcf(vcf)
    assert len(cs) == 1 and cs[0] == {"name": "Marie Dupont", "email": "marie@x.be", "phone": "+32 475 00 00 00", "org": "Alpha; SPRL", "notes": "VIP\nclient"}
    assert contacts.parse_vcf(contacts.to_vcf(cs)) == cs


def test_preinstalled_oauth_clients_and_wizard():
    p = os.path.join(tmp, "clients.json")
    open(p, "w").write(json.dumps({"google": {"client_id": " GID ", "client_secret": "S"}, "evil": {"client_id": "x"},
                                   "microsoft": {"client_id": 5}}))
    assert oauth.default_clients(p) == {"google": {"client_id": "GID", "client_secret": "S"}}      # inconnus et mal formés ignorés
    open(p, "w").write("pas du json")
    assert oauth.default_clients(p) == {} and oauth.default_clients(os.path.join(tmp, "absent.json")) == {}
    open(p, "w").write("[1, 2]")
    assert oauth.default_clients(p) == {}
    ok = os.path.join(tmp, "ok.json")
    open(ok, "w").write(json.dumps({"google": {"client_id": "SYS", "client_secret": ""}}))
    orig = oauth.SYSTEM_CLIENTS
    oauth.SYSTEM_CLIENTS = ok
    try:
        c = Config(os.path.join(tmp, "cl.json"))
        assert oauth.client_for(c, "google")["client_id"] == "SYS"                                   # aucun réglage : celui de la machine
        c.data["oauth_clients"] = {"google": {"client_id": "MIEN", "client_secret": ""}}
        assert oauth.client_for(c, "google")["client_id"] == "MIEN"                                  # la saisie de l'utilisateur l'emporte
        assert oauth.client_for(c, "microsoft") == {}
        calls = []
        orig_refresh = oauth.refresh_access_token
        oauth.refresh_access_token = lambda prov, cid, sec, rt: (calls.append(cid), {"access_token": "AT", "expires_in": 3600})[1]
        try:
            c.data["oauth_clients"] = {}
            c.set_password("acc7", "RT")
            assert oauth.TokenManager(c).access_token({"id": "acc7", "oauth_provider": "google"}) == "AT" and calls == ["SYS"]   # jetons sans aucune saisie
        finally:
            oauth.refresh_access_token = orig_refresh
    finally:
        oauth.SYSTEM_CLIENTS = orig
    for prov, steps in oauth.WIZARD.items():
        assert prov in oauth.PROVIDERS and len(steps) >= 2 and all(u.startswith("https://") and t for t, u in steps)
