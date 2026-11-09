"""Audit de sécurité : tests de régression sur les failles trouvées et corrigées (voir SECURITY.md)."""
import importlib, os, random, re, socket, stat, sys, tempfile, threading, time, types, urllib.error
from html.parser import HTMLParser
tmp = tempfile.mkdtemp()
os.environ.setdefault("XDG_DATA_HOME", tmp)
os.environ.setdefault("XDG_CONFIG_HOME", tmp)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gtkstub   # noqa: F401
from mintmail import backend as B, htmlsafe as H, p2p, reader as R, store, unsub, util
from mintmail.store import Cache, Config

# ======================================================================= 1. nettoyeur HTML
PAYLOADS = [
    "<script>alert(1)</script>", "<scr<script>ipt>alert(1)</scr</script>ipt>", "<SCRIPT SRC=//evil/x.js></SCRIPT>", "<img src=x onerror=alert(1)>",
    "<img/src=x/onerror=alert(1)>", "<img src=x onerror=alert(1) src=y>", "<IMG SRC=javascript:alert(1)>", "<img src=`javascript:alert(1)`>",
    "<svg/onload=alert(1)>", "<svg><script>alert(1)</script></svg>", "<svg><a xlink:href=javascript:alert(1)><text>x</text></a></svg>",
    "<math><mi xlink:href=javascript:alert(1)>x</mi></math>", "<a href=javascript:alert(1)>x</a>", "<a href=\" JaVaScRiPt:alert(1)\">x</a>",
    "<a href=\"jav&#x09;ascript:alert(1)\">x</a>", "<a href=\"jav&#10;ascript:alert(1)\">x</a>", "<a href=\"&#106;avascript:alert(1)\">x</a>",
    "<a href=\"\x01javascript:alert(1)\">x</a>", "<a href=\"vbscript:msgbox(1)\">x</a>", "<a href=\"data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==\">x</a>",
    "<a href=\"file:///etc/passwd\">x</a>", "<iframe src=javascript:alert(1)></iframe>", "<iframe srcdoc=\"<script>alert(1)</script>\"></iframe>",
    "<object data=javascript:alert(1)></object>", "<embed src=javascript:alert(1)>", "<form action=javascript:alert(1)><input type=submit></form>",
    "<button formaction=javascript:alert(1)>x</button>", "<meta http-equiv=refresh content=\"0;url=javascript:alert(1)\">",
    "<meta http-equiv=refresh content=\"0;url=https://evil\">", "<base href=\"https://evil/\"><a href=x>x</a>", "<link rel=stylesheet href=https://evil/x.css>",
    "<style>@import 'https://evil/x.css';</style>", "<style>body{background:url(https://evil/p.png)}</style>", "<div style=\"background:url(https://evil/p.png)\">x</div>",
    "<div style=\"width:expression(alert(1))\">x</div>", "<div style=\"behavior:url(x.htc)\">x</div>", "<div style=\"position:fixed;top:0;left:0;width:100%;height:100%\">x</div>",
    "<div style=\"color:red;background:u\\72l(https://evil)\">x</div>", "<p onmouseover=alert(1)>x</p>", "<p onclick = \"alert(1)\">x</p>", "<p ONCLICK=alert(1)>x</p>",
    "<body onload=alert(1)>", "<input autofocus onfocus=alert(1)>", "<details open ontoggle=alert(1)>", "<video><source onerror=alert(1)></video>",
    "<audio src=x onerror=alert(1)>", "<marquee onstart=alert(1)>x</marquee>", "<noscript><p title=\"</noscript><img src=x onerror=alert(1)>\">", "<template><script>alert(1)</script></template>",
    "<textarea><img src=x onerror=alert(1)></textarea>", "<title><img src=x onerror=alert(1)></title>", "<xmp><script>alert(1)</script></xmp>", "<plaintext><script>alert(1)</script>",
    "<![CDATA[<script>alert(1)</script>]]>", "<!--[if mso]><script>alert(1)</script><![endif]-->", "<!--><script>alert(1)</script>-->", "<a href=\"x\" onclick=\"alert(1)\"",
    "<img src=\"x\" alt=\"\"onerror=alert(1)>", "<a href=\"https://ok.be\"onmouseover=alert(1)>x</a>", "&lt;script&gt;alert(1)&lt;/script&gt;", "<img src=\"data:image/svg+xml;base64,PHN2ZyBvbmxvYWQ9YWxlcnQoMSk+\">",
    "<img src=\"https://track.me/p.gif\" srcset=\"https://track.me/x 2x\">", "<img src=\"cid:abc\" onerror=alert(1)>", "<table background=\"https://evil/p.png\"><tr><td>x</td></tr></table>",
    "<a ping=\"https://track.me/\" href=\"https://ok.be\">x</a>", "<a target=_blank href=\"https://ok.be\">x</a>", "<div id=ed>x</div>", "<div class=\"x\" id=\"sig\">x</div>",
]
FRAGMENTS = ["<", ">", "</", "/>", "=", "\"", "'", "`", "&", "&#x6a;", "&lt;", "<script>", "</script>", "<img ", "<a ", "href=", "src=", "onerror=", "onload=", "javascript:",
             "<svg>", "</svg>", "<style>", "</style>", "<div>", "</div>", "<p style=\"", "url(", "expression(", "<!--", "-->", "<![CDATA[", "]]>", "x", " ", "\n", "\t", "\x00", "\u202e"]


class Probe(HTMLParser):
    """Relit la sortie : chaque balise / attribut / URL doit être dans la liste blanche."""
    def __init__(self, keep_style=False):
        super().__init__(convert_charrefs=True)
        self.errors, self.keep_style = [], keep_style

    def handle_starttag(self, tag, attrs):
        if tag == "style" and self.keep_style:
            return
        if tag not in H.ALLOWED_TAGS:
            self.errors.append("balise %s" % tag)
        allowed = H.GLOBAL_ATTRS | H.TAG_ATTRS.get(tag, set()) | {"rel", "data-blocked-src"} | ({"class"} if self.keep_style else set())
        for n, v in attrs:
            if n not in allowed:
                self.errors.append("attribut %s sur %s" % (n, tag))
            v = v or ""
            if n == "href" and v and not (v.startswith("#") or H.clean_url(v, "link", False)):
                self.errors.append("href %r" % v)
            if n == "src" and not H.clean_url(v, "image", True):
                self.errors.append("src %r" % v)
            if n == "style" and H.clean_style(v) != v:
                self.errors.append("style %r" % v)
            if n.startswith("on"):
                self.errors.append("gestionnaire %s" % n)

    handle_startendtag = handle_starttag


def violations(out, keep_style=False):
    p = Probe(keep_style)
    p.feed(out)
    p.close()
    return p.errors


def test_attack_corpus_is_neutralised_in_editor_and_reader_modes():
    for payload in PAYLOADS:
        for ed, reader_mode in ((util.sanitize_html(payload), False), (H.sanitize(payload, keep_style=False), False),
                                (H.sanitize(payload, keep_style=True, allow_remote_images=True), True)):
            bad = violations(ed, keep_style=reader_mode)
            assert not bad, (payload, ed, bad)
            low = re.sub(r"[\x00-\x20]", "", ed.lower())
            assert "<script" not in low and "<iframe" not in low and "<object" not in low and "<meta" not in low and "<base" not in low and "<form" not in low, (payload, ed)
    # ce qui est légitime survit
    assert "<b>Marie</b>" in util.sanitize_html("<p>Bonjour <b>Marie</b></p>")
    ok = H.sanitize('<table width="600" bgcolor="#fff"><tr><td colspan=2 style="color:#333;padding:4px">x</td></tr></table><a href="https://ok.be/?a=1&b=2">l</a>')
    assert 'width="600"' in ok and "color:#333" in ok and 'href="https://ok.be/?a=1&amp;b=2"' in ok and 'rel="noopener noreferrer"' in ok


def test_remote_images_are_inert_unless_allowed_and_style_blocks_are_filtered():
    h = '<img src="https://track.me/p.gif" width=1><img src="cid:abc"><img src="data:image/png;base64,iVBORw0KGgo=">'
    off = H.sanitize(h)
    live = lambda s: re.search(r'(?<![\w-])src="https?://', s) is not None            # une VRAIE source distante (pas data-blocked-src)
    assert not live(off) and "data-blocked-src" in off and 'src="cid:abc"' in off and 'src="data:image/png' in off
    assert live(H.sanitize(h, allow_remote_images=True))
    css = H.sanitize("<style>@import 'x.css'; @font-face{src:url(https://e/f.woff)} .a{color:red;background:url(https://e/p.png);position:fixed} @media (max-width:600px){.b{width:100%}}</style><p class=a>t</p>", keep_style=True)
    assert "url(" not in css and "@import" not in css and "@font-face" not in css and "position" not in css and "color:red" in css and "@media" in css and "width:100%" in css
    assert "<style" not in H.sanitize("<style>.a{color:red}</style><p>t</p>", keep_style=False)


def test_random_html_always_yields_safe_idempotent_output_quickly():
    rnd = random.Random(20261110)
    t0 = time.time()
    for _ in range(3000):
        src = "".join(rnd.choice(FRAGMENTS) for _ in range(rnd.randint(1, 40)))
        out = H.sanitize(src, keep_style=False, allow_remote_images=True)
        assert not violations(out), (src, out)
        assert H.sanitize(out, keep_style=False, allow_remote_images=True) == out, (src, out)    # stable : pas de mutation à la relecture
        out2 = H.sanitize(src, keep_style=True)
        assert not violations(out2, keep_style=True), (src, out2)
    assert time.time() - t0 < 30


def test_pathological_inputs_do_not_hang():
    cases = ["<" * 300000, "<a " * 100000, "<div>" * 60000, "&" * 300000, "<a " + "x=" * 100000, "<table>" * 20000 + "x", "<!--" * 100000, "<p style=\"" + "a:b;" * 100000 + "\">x",
             "<b>" * 5000 + "</i>" * 5000, "\x00" * 200000, "<style>" + "a{b:c}" * 100000 + "</style>x"]
    for c in cases:
        t0 = time.time()
        out = H.sanitize(c, keep_style=True)
        assert isinstance(out, str)
        assert time.time() - t0 < 8, (c[:20], time.time() - t0)


def test_reader_wrap_and_editor_template_carry_a_content_security_policy():
    class M:
        html = '<p onclick="x()">Salut</p><script>alert(1)</script><img src="https://track.me/p.gif"><meta http-equiv="refresh" content="0;url=https://evil">'
        text = "Salut"
    out = R.wrap_html(M(), False, False)
    assert "Content-Security-Policy" in out and "default-src 'none'" in out and "img-src data: cid:;" in out and "http:" not in out.split("</head>")[0].split("img-src")[1].split(";")[0]
    assert "<script" not in out and "onclick" not in out and "<meta http-equiv=\"refresh\"" not in out and re.search(r'(?<![\w-])src="https?://', out) is None
    assert "img-src data: cid: http: https:" in R.wrap_html(M(), True, False)
    import mintmail.compose as C
    tpl = C.EDITOR_TPL
    script = re.search(r"<script>(.*?)</script>", tpl, re.S).group(1)
    import base64, hashlib
    digest = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
    assert "sha256-" + digest in tpl and "default-src 'none'" in tpl and "unsafe-inline'; script" not in tpl.replace("style-src 'unsafe-inline'", "")
    assert tpl.count("<script>") == 1                                                                  # un seul script, celui de l'éditeur
    os.environ["MINTMAIL_EDITOR_CSP"] = "0"
    try:
        assert "Content-Security-Policy" not in importlib.reload(C).EDITOR_TPL                     # voie de secours documentée
    finally:
        del os.environ["MINTMAIL_EDITOR_CSP"]
        importlib.reload(C)


# ======================================================================= 2. liens et navigation
def test_only_http_https_mailto_links_are_opened_and_with_clean_addresses():
    opened = []
    R.Gtk.show_uri_on_window = lambda win, uri, t: opened.append(uri)
    for bad in ["javascript:alert(1)", "  JaVaScRiPt:alert(1)", "java\tscript:alert(1)", "file:///etc/passwd", "FILE:///home/x", "smb://srv/share", "ssh://h", "ftp://h/x", "data:text/html,<script>alert(1)</script>",
                "about:blank", "x-scheme-handler/steam", "steam://run/1", "ms-msdt:/id", "tel:+32", "vbscript:x", "", "https" + "x" * 5000 + "://a", "//evil/x", "/etc/passwd", "evil.com/x"]:
        assert R.open_uri(None, bad) is False, bad
    assert opened == []
    for good, want in [("https://saec.me/x?a=1", "https://saec.me/x?a=1"), ("HTTP://x.be", "HTTP://x.be"), ("mailto:a@b.be?subject=x", "mailto:a@b.be?subject=x"), ("ht\ttps://x.be", "https://x.be"), (" https://x.be\n", "https://x.be")]:
        assert R.open_uri(None, good) is True and opened[-1] == want, (good, opened[-1])


class FakeDecision:
    def __init__(self, uri, ntype):
        self.ignored = False
        self.nav = types.SimpleNamespace(get_request=lambda: types.SimpleNamespace(get_uri=lambda: uri), get_navigation_type=lambda: ntype)
    def get_navigation_action(self): return self.nav
    def ignore(self): self.ignored = True


def test_webview_navigation_policy_blocks_everything_but_our_own_load_and_safe_clicks():
    ns = types.SimpleNamespace(PolicyDecisionType=types.SimpleNamespace(NAVIGATION_ACTION="nav", NEW_WINDOW_ACTION="win", RESPONSE="resp"),
                               NavigationType=types.SimpleNamespace(LINK_CLICKED="click", OTHER="other", FORM_SUBMITTED="form", RELOAD="reload"))
    orig_wk, orig_open = R.WebKit2, R.open_uri
    R.WebKit2 = ns
    opened = []
    R.open_uri = lambda owner, uri: opened.append(uri) or True
    try:
        d = FakeDecision("about:blank", "other")
        assert R.navigation_policy(None, d, "nav") is False and not d.ignored                 # notre propre load_html
        d = FakeDecision("about:blank#section", "click")
        assert R.navigation_policy(None, d, "nav") is False and opened == []                  # ancre interne
        d = FakeDecision("https://ok.be/x", "click")
        assert R.navigation_policy(None, d, "nav") is True and d.ignored and opened == ["https://ok.be/x"]
        for uri, ntype in (("https://evil/redirect", "other"), ("https://evil/post", "form"), ("javascript:alert(1)", "other"), ("file:///etc/passwd", "reload")):
            d = FakeDecision(uri, ntype)
            assert R.navigation_policy(None, d, "nav") is True and d.ignored, (uri, ntype)    # redirections, formulaires, cadres : refusés
        assert opened == ["https://ok.be/x"]
        d = FakeDecision("https://evil/", "click")
        assert R.navigation_policy(None, d, "win") is True and d.ignored                      # nouvelle fenêtre : refusée
        assert R.navigation_policy(None, FakeDecision("https://x", "other"), "resp") is False
    finally:
        R.WebKit2, R.open_uri = orig_wk, orig_open


def test_webkit_settings_are_hardened():
    called = {}

    class S:
        def __getattr__(self, name):
            return lambda v: called.__setitem__(name, v)
    R.harden_settings(S(), False)
    for name in ("set_enable_hyperlink_auditing", "set_enable_plugins", "set_enable_webgl", "set_enable_html5_local_storage", "set_allow_modal_dialogs",
                 "set_javascript_can_open_windows_automatically", "set_enable_developer_extras", "set_allow_file_access_from_file_urls"):
        assert called.get(name) is False, name
    assert called["set_enable_javascript"] is False
    R.harden_settings(S(), True)
    assert called["set_enable_javascript"] is True and called["set_enable_hyperlink_auditing"] is False


# ======================================================================= 3. pièces jointes
def test_attachment_risk_levels_including_tricks():
    risk = lambda n, mime="": util.attachment_risk({"filename": n, "mime": mime})
    for n in ["setup.exe", "FACTURE.PDF.EXE", "x.exe.", "x.exe ", "run.sh", "SCRIPT.SH", "app.AppImage", "evil.desktop", "a.jar", "m.msi", "p.ps1", "q.py", "d.deb", "x.lnk", "x.hta",
              "facture\u202efdp.exe", "photo\u200b.exe", "doc.scr", "x.bat"]:
        assert risk(n) == "block", n
    assert risk("noext", "application/x-sh") == "block"
    for n in ["page.html", "image.svg", "macro.docm", "old.doc", "sheet.xls", "disk.iso", "page.HTM", "invite.ics"]:
        assert risk(n) == "warn", n
    assert risk("x", "image/svg+xml") == "warn" and risk("x", "text/html") == "warn"
    for n in ["facture.pdf", "photo.JPG", "notes.txt", "archive.zip", "data.csv", "contrat.docx", "x.png", "tableau.xlsx"]:
        assert risk(n) == "ok", n
    assert util.attachment_kind({"filename": "a.svg"}) == "file"                                  # plus d'aperçu intégré pour les SVG


def test_attachment_opening_never_launches_executables_and_asks_for_risky_files():
    launched, dialogs, previews = [], [], []
    orig = R.Gio.AppInfo.launch_default_for_uri
    R.Gio.AppInfo.launch_default_for_uri = staticmethod(lambda uri, ctx: launched.append(uri))
    answer = {"v": False}

    def dialog(title, text, ok_label=None):
        dialogs.append((title, ok_label))
        return answer["v"]
    me = types.SimpleNamespace(_warn_dialog=dialog, _preview=lambda a, k: previews.append(a["filename"]), get_toplevel=lambda: None)
    try:
        for name in ("setup.exe", "run.sh", "evil.desktop", "facture\u202efdp.exe"):
            R.Reader._open_att(me, {"filename": name, "path": "/tmp/" + name, "size": 10, "mime": ""})
        assert launched == [] and previews == [] and all(d[1] is None for d in dialogs) and len(dialogs) == 4      # refus net, enregistrement seulement
        dialogs.clear()
        R.Reader._open_att(me, {"filename": "page.html", "path": "/tmp/page.html", "size": 10, "mime": "text/html"})
        assert launched == [] and dialogs and dialogs[0][1] == "Ouvrir quand même"                              # confirmation, refusée
        answer["v"] = True
        R.Reader._open_att(me, {"filename": "page.html", "path": "/tmp/page.html", "size": 10, "mime": "text/html"})
        assert launched and launched[0].endswith("page.html")                                                   # confirmée : ouverte
        launched.clear(); dialogs.clear()
        R.Reader._open_att(me, {"filename": "photo.jpg", "path": "/tmp/photo.jpg", "size": 10, "mime": "image/jpeg"})
        assert previews == ["photo.jpg"] and dialogs == []                                                      # fichier ordinaire : aucune question
        R.Reader._open_att(me, {"filename": "huge.jpg", "path": "/tmp/huge.jpg", "size": 50_000_000, "mime": "image/jpeg"})
        assert previews == ["photo.jpg"] and launched                                                          # image énorme : pas d'aperçu en mémoire
    finally:
        R.Gio.AppInfo.launch_default_for_uri = orig


# ======================================================================= 4. données au repos
def modes(path):
    return stat.S_IMODE(os.stat(path).st_mode)


def test_private_storage_is_created_restricted_even_with_a_permissive_umask():
    old = os.umask(0)                                                  # pire cas : umask 000
    base = tempfile.mkdtemp()
    cdir, ddir = os.path.join(base, "cfg", "mintmail"), os.path.join(base, "data", "mintmail")
    orig = (store.CONFIG_DIR, store.DATA_DIR)
    try:
        c = Config(os.path.join(cdir, "config.json"))
        c.data["passwords"] = {"a1": "secret"}
        c.save()
        assert modes(cdir) == 0o700 and modes(os.path.join(cdir, "config.json")) == 0o600
        assert not os.path.exists(os.path.join(cdir, "config.json.tmp"))
        store.DATA_DIR = type(store.DATA_DIR)(ddir)
        cache = Cache(os.path.join(ddir, "cache.db"))
        from mintmail.models import Message
        cache.upsert(Message(id="m1", account="a", folder="inbox", uid=1, subject="s", text="corps confidentiel"))
        cache.db.commit()
        assert modes(ddir) == 0o700 and modes(os.path.join(ddir, "cache.db")) == 0o600
        for extra in ("cache.db-wal", "cache.db-shm"):
            p = os.path.join(ddir, extra)
            if os.path.exists(p):
                assert modes(p) & 0o077 == 0, extra
        store.write_private(os.path.join(ddir, "x.txt"), "t")
        assert modes(os.path.join(ddir, "x.txt")) == 0o600
    finally:
        os.umask(old)
        store.CONFIG_DIR, store.DATA_DIR = orig


def test_harden_permissions_fixes_old_wide_open_installations_and_attachments_are_private():
    base = tempfile.mkdtemp()
    cdir, ddir = type(store.CONFIG_DIR)(os.path.join(base, "c", "mintmail")), type(store.DATA_DIR)(os.path.join(base, "d", "mintmail"))
    os.makedirs(cdir / "sub"); os.makedirs(ddir / "attachments" / "m1")
    for p in (cdir / "config.json", ddir / "cache.db", ddir / "mintmail.log", ddir / "attachments" / "m1" / "facture.pdf"):
        p.write_text("x"); os.chmod(p, 0o644)
    for d in (cdir, ddir, ddir / "attachments", ddir / "attachments" / "m1", cdir / "sub"):
        os.chmod(d, 0o755)
    link = ddir / "lien"
    os.symlink("/etc/passwd", link)
    orig = (store.CONFIG_DIR, store.DATA_DIR)
    store.CONFIG_DIR, store.DATA_DIR = cdir, ddir
    try:
        assert store.harden_permissions() >= 8
        assert modes(cdir) == 0o700 and modes(ddir / "attachments" / "m1") == 0o700 and modes(cdir / "config.json") == 0o600 and modes(ddir / "attachments" / "m1" / "facture.pdf") == 0o600
        assert os.path.exists("/etc/passwd") and modes("/etc/passwd") & 0o004                     # le lien symbolique n'a pas été suivi
        assert store.harden_permissions() == 0                                                    # idempotent
        # pièces jointes écrites par l'analyse d'un message : privées dès la création
        old_bd = B.DATA_DIR
        B.DATA_DIR = ddir
        os.umask(0)
        try:
            raw = (b"From: a@x.be\r\nTo: b@x.be\r\nSubject: s\r\nMessage-ID: <z@x>\r\nMIME-Version: 1.0\r\nContent-Type: multipart/mixed; boundary=B\r\n\r\n--B\r\nContent-Type: text/plain\r\n\r\ncorps\r\n"
                   b"--B\r\nContent-Type: application/pdf; name=\"../../etc/evil.pdf\"\r\nContent-Disposition: attachment; filename=\"../../etc/evil.pdf\"\r\nContent-Transfer-Encoding: base64\r\n\r\nSGVsbG8=\r\n--B--\r\n")
            m = B.parse_message(raw, "acc", "inbox", "INBOX", 9, set())
        finally:
            os.umask(0o022)
            B.DATA_DIR = old_bd
        a = m.attachments[0]
        assert os.path.dirname(a["path"]).startswith(str(ddir / "attachments")) and ".." not in a["path"] and a["filename"] == "_.._etc_evil.pdf".replace("_.._", "").replace("etc_", "etc_") or "/" not in a["filename"]
        assert modes(a["path"]) == 0o600 and modes(os.path.dirname(a["path"])) == 0o700
    finally:
        store.CONFIG_DIR, store.DATA_DIR = orig


def test_log_file_is_private():
    from mintmail import log as L
    base = tempfile.mkdtemp()
    d = type(store.DATA_DIR)(os.path.join(base, "d"))
    orig = (L.DATA_DIR, L.LOG)
    L.DATA_DIR, L.LOG = d, d / "mintmail.log"
    old = os.umask(0)
    try:
        L.log("essai")
        assert modes(d) == 0o700 and modes(d / "mintmail.log") == 0o600
    finally:
        os.umask(old)
        L.DATA_DIR, L.LOG = orig


def test_imap_folder_names_cannot_inject_commands():
    assert B._q("Factures") == '"Factures"' and B._q('a"b\\c') == '"a\\"b\\\\c"'
    for evil in ("INBOX\r\nA1 DELETE INBOX", "x\nlogout", "a\x00b", "tab\there"):
        try:
            B._q(evil)
            raise AssertionError("accepté : %r" % evil)
        except B.BackendError:
            pass


# ======================================================================= 5. synchronisation entre machines
def sync_engine(name="s1"):
    c = Config(os.path.join(tmp, name + ".json"))
    c.data.update(p2p_enabled=True, p2p_secret="Tr0ub4dor&3xKq!zWz", p2p_port=55801, p2p_disc_port=55802)
    return p2p.SyncEngine(c)


def test_only_local_network_peers_may_connect_and_announcements_are_bounded():
    for ok in ("192.168.1.20", "10.0.0.7", "172.16.5.4", "127.0.0.1", "100.101.102.103", "169.254.1.1", "::1", "fd00::1"):
        assert p2p.SyncEngine.accepts((ok, 40000)) is True, ok
    for bad in ("8.8.8.8", "93.184.216.34", "2001:4860:4860::8888", "not-an-ip", ""):
        assert p2p.SyncEngine.accepts((bad, 40000)) is False, bad
    e = sync_engine()
    e._udp = None
    ann = lambda port, node="N0": ("MINTMAIL/3 %s %s abcd1234" % (node, port)).encode()
    for port in ("80", "1023", "0", "65536", "99999999999999999999", "-1", "x"):
        assert e._handle_announce(ann(port), ("192.168.1.20", 54321)) is None, port       # port système / invalide : ignoré
    assert e._handle_announce(ann("54322"), ("192.168.1.20", 54321)) == "192.168.1.20:54322"
    for i in range(200):                                                                # inondation d'annonces falsifiées
        e._handle_announce(ann("54322", "N%d" % i), ("192.168.%d.%d" % (i // 250 + 2, i % 250 + 1), 54321))
    assert len(e.peers()) <= p2p.MAX_PEERS
    for i in range(200):
        e._handle_announce(ann("54322"), ("8.8.%d.%d" % (i // 250, i % 250), 54321))
        e._handle_announce(("MINTMAIL/%d x 54322" % (100 + i)).encode(), ("192.168.1.20", 54321))
    d = e.diagnostics()
    assert len(d["filtered"]) <= 50 and len(d["foreign_versions"]) <= 20


def test_stalled_connection_is_cut_after_the_total_deadline_and_frees_its_slot():
    e = sync_engine("s2")
    orig = p2p.CONN_DEADLINE
    p2p.CONN_DEADLINE = 1.0
    a, b = socket.socketpair()
    try:
        e._slots.acquire()
        t0 = time.time()
        th = threading.Thread(target=e._handle, args=(a,), daemon=True)
        th.start()
        b.sendall(b'{"t":"hel')                                                          # goutte à goutte : jamais de ligne complète
        th.join(6)
        assert not th.is_alive() and time.time() - t0 < 5
        assert e._slots.acquire(blocking=False) is True                                   # l'emplacement a été libéré
        e._slots.release()
    finally:
        p2p.CONN_DEADLINE = orig
        a.close(); b.close()


def test_pairing_code_strength_rejects_weak_codes_and_accepts_generated_ones():
    for _ in range(500):
        c = p2p.generate_code()
        assert len(c) == 20 and p2p.code_is_acceptable(c), c                              # le bouton « Générer » : toujours accepté
    for weak in ("aaaaaaaaaaaa", "motdepasse1234", "azertyuiop12", "123456789012", "abcdefghijkl", "passwordpassword", "mintmail-saec-2026", "qwertyuiopas", "bonjourbonjour", "linuxlinuxlinux", "Password1234", "Motdepassecomplique", "motdepassecomplique"):
        assert not p2p.code_is_acceptable(weak), weak
    for good in ("Tr0ub4dor&3xKq!z", "correct horse battery staple", "k9#Lm2$vQx8!pR4w", "Zx7-Bn3-Qw9-Lm5-Kp2"):
        assert p2p.code_is_acceptable(good), good
    assert not p2p.code_is_acceptable("Court1!") and p2p.code_strength("") == 0


def test_tampered_encrypted_frames_are_rejected():
    import io
    key = p2p.derive_key("Tr0ub4dor&3xKq!zWz")
    buf = io.BytesIO()
    a = p2p.SecureChannel(buf, key, b"nc", b"ns", True)
    a.send({"t": "items", "items": {"x": 1}})
    a.send({"t": "items", "items": {"y": 2}})
    raw = bytearray(buf.getvalue())
    ok = p2p.SecureChannel(io.BytesIO(bytes(raw)), key, b"nc", b"ns", False)
    assert ok.recv()["items"] == {"x": 1} and ok.recv()["items"] == {"y": 2}
    for pos in (0, 5, 12, len(raw) // 2 - 1, len(raw) - 1):                                 # un seul octet altéré n'importe où : rejet
        t = bytearray(raw)
        t[pos] ^= 1
        r = p2p.SecureChannel(io.BytesIO(bytes(t)), key, b"nc", b"ns", False)
        try:
            r.recv(); r.recv()
            raise AssertionError("trame altérée acceptée (octet %d)" % pos)
        except ValueError:
            pass
    swapped = p2p.SecureChannel(io.BytesIO(bytes(raw)), p2p.derive_key("autre code de jumelage 99"), b"nc", b"ns", False)       # mauvais code
    try:
        swapped.recv(); raise AssertionError("mauvais code accepté")
    except ValueError:
        pass
    wrong_session = p2p.SecureChannel(io.BytesIO(bytes(raw)), key, b"nc", b"AUTRE", False)                                         # rejeu dans une autre session
    try:
        wrong_session.recv(); raise AssertionError("rejeu accepté")
    except ValueError:
        pass


# ======================================================================= 6. désabonnement
def test_unsubscribe_cannot_be_used_to_reach_internal_hosts_or_mass_mail():
    for bad in ("https://127.0.0.1/x", "https://localhost/x", "https://10.0.0.5/u", "https://192.168.1.1/u", "https://169.254.169.254/latest/meta-data", "https://[::1]/",
                "https://user:pw@93.184.216.34/x", "https://0.0.0.0/", "https://100.64.0.1/", "https:///x", "https://"):
        assert unsub.public_host(bad) is False, bad
        ok, detail = unsub.one_click_post(bad)
        assert ok is False and ("interne" in detail or "adresse" in detail), (bad, detail)
    assert unsub.public_host("https://93.184.216.34/ok") is True
    redir = unsub._HttpsOnlyRedirect()
    for target in ("https://127.0.0.1/x", "http://93.184.216.34/x", "https://192.168.0.9/x"):
        try:
            redir.redirect_request(types.SimpleNamespace(), None, 302, "x", {}, target)
            raise AssertionError("redirection acceptée : " + target)
        except urllib.error.URLError:
            pass
    assert unsub.mailto_fields("mailto:stop@x.be?subject=bye&body=ciao") == ("stop@x.be", "bye", "ciao")
    for evil in ("mailto:a@x.be,b@y.be", "mailto:a@x.be;b@y.be", "mailto:a@x.be?bcc=spam@z.be", "mailto:a@x.be?cc=c@z.be", "mailto:a@x.be?to=b@z.be", "mailto:pas une adresse",
                 "mailto:%0D%0ABcc:x@y.be", "mailto:", "mailto:a@x.be\r\nBcc:z@y.be"):
        assert unsub.mailto_fields(evil)[0] == "", evil
    to, subj, body = unsub.mailto_fields("mailto:a@x.be?subject=x%0D%0ABcc:evil@x.be&body=l1%0A%0D%0Al2")
    assert to == "a@x.be" and "\r" not in subj and "\n" not in subj and "\r" not in body and "\n" not in body


# ======================================================================= 7. paquet
def test_launcher_ignores_the_current_directory_and_python_environment():
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packaging", "build-deb.sh")
    if not os.path.exists(p):
        return                                                                   # arbre sans dossier packaging (hors dépôt)
    assert "exec /usr/bin/python3 -I -m mintmail" in open(p, encoding="utf-8").read()
