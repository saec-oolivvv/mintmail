"""Mises à jour via GitHub : recherche, téléchargement, signature, programme administrateur, interface. Faux serveur GitHub local, VRAIES signatures openssl."""
import json, os, shutil, stat, subprocess, sys, tempfile, threading, types, xml.dom.minidom
from http.server import BaseHTTPRequestHandler, HTTPServer
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
tmp = tempfile.mkdtemp()
os.environ.setdefault("XDG_DATA_HOME", tmp)
os.environ.setdefault("XDG_CONFIG_HOME", tmp)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
import gtkstub   # noqa: F401
from mintmail import apply_update as A, updater as U, updates_ui as UI

# ------------------------------------------------------------------ clés de test (jetables) et signature
KEYDIR = tempfile.mkdtemp()


def make_key(name):
    priv, pub = os.path.join(KEYDIR, name + ".key"), os.path.join(KEYDIR, name + ".pem")
    subprocess.run(["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048", "-out", priv], check=True, capture_output=True)
    subprocess.run(["openssl", "pkey", "-in", priv, "-pubout", "-out", pub], check=True, capture_output=True)
    return priv, pub


GOOD_PRIV, GOOD_PUB = make_key("good")
EVIL_PRIV, EVIL_PUB = make_key("evil")


def sign(path, priv=GOOD_PRIV):
    sig = path + (".sig" if priv == GOOD_PRIV else ".evil.sig")                # une signature de tiers ne doit jamais écraser la bonne
    subprocess.run(["openssl", "dgst", "-sha256", "-sign", priv, "-out", sig, path], check=True, capture_output=True)
    return sig


def fake_deb(path, package="mintmail", arch="all", version="1:1.99.0", pad=200):
    open(path, "wb").write(("PKG=%s;ARCH=%s;VER=%s;" % (package, arch, version)).encode() + b"x" * pad)
    return path


# ------------------------------------------------------------------ faux GitHub
class Gh(BaseHTTPRequestHandler):
    release = {}
    assets = {}
    status = 200
    etag = 'W/"v1"'
    redirect_to = None
    hits = 0
    seen_headers = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        Gh.hits += 1
        Gh.seen_headers.append(dict(self.headers))
        if Gh.redirect_to:
            self.send_response(302); self.send_header("Location", Gh.redirect_to); self.end_headers(); return
        if self.path.startswith("/dl/"):
            data = Gh.assets.get(self.path[4:])
            if data is None:
                self.send_response(404); self.end_headers(); return
            self.send_response(200); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data); return
        if Gh.status != 200:
            self.send_response(Gh.status); self.end_headers(); return
        if self.headers.get("If-None-Match") == Gh.etag:
            self.send_response(304); self.end_headers(); return
        body = json.dumps(Gh.release).encode() if not isinstance(Gh.release, bytes) else Gh.release
        self.send_response(200); self.send_header("ETag", Gh.etag); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)


def start_server():
    srv = HTTPServer(("127.0.0.1", 0), Gh)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, "http://127.0.0.1:%d" % srv.server_port


def release(base, version="1.99.0", with_sig=True, with_sums=True, **over):
    name = "mintmail_%s_all.deb" % version
    assets = [{"name": name, "size": 0, "browser_download_url": base + "/dl/" + name}]
    if with_sig:
        assets.append({"name": name + ".sig", "size": 10, "browser_download_url": base + "/dl/" + name + ".sig"})
    if with_sums:
        assets.append({"name": "SHA256SUMS", "size": 10, "browser_download_url": base + "/dl/SHA256SUMS"})
    r = {"tag_name": "v" + version, "draft": False, "prerelease": False, "body": "Nouveautés", "html_url": "https://github.com/o/r/releases/tag/v" + version, "assets": assets}
    r.update(over)
    return r


# ======================================================================= 1. versions, dépôt, hôtes
def test_version_logic_repo_syntax_and_schedule():
    P, N = U.parse_version, U.is_newer
    assert P("v1.11.0") == (1, 11, 0) and P("1:1.10.2") == (1, 10, 2) and P("1.2") == (1, 2) and P("") is None and P("latest") is None and P("1.x") is None and P(None) is None
    assert N("1.11.0", "1.10.2") and N("1.10.0", "1.9.2") and N("2.0", "1.99.9") and N("1.11.0.1", "1.11.0")
    assert not N("1.10.2", "1.10.2") and not N("1.9.2", "1.10.0") and not N("1.11", "1.11.0") and not N("garbage", "1.0.0") and not N("1.0.0", "garbage")
    assert U.valid_repo("saec-oolivvv/mintmail") and U.valid_repo("a.b_c/d-e.f")
    for bad in ("", "nom-seul", "a/b/c", "a/../b", "../a/b", "a b/c", "a/b;rm", "a/b\n", "https://github.com/a/b", "-a/b" * 1 + "/", "a/" + "x" * 200):
        assert not U.valid_repo(bad), bad
    assert U.due(1000, 0) and not U.due(1000, 900) and U.due(1000 + 86400, 1000) and U.due(1000, 1000 + 7200)       # jamais vérifié / récent / 24 h écoulées / horloge reculée


def test_only_github_hosts_over_https_are_allowed():
    ok = ["https://api.github.com/repos/o/r/releases/latest", "https://github.com/o/r/releases/download/v1/x.deb", "https://objects.githubusercontent.com/abc?x=1",
          "https://release-assets.githubusercontent.com/x"]
    bad = ["http://github.com/x", "https://github.com.evil.com/x", "https://evilgithub.com/x", "https://githubusercontent.com.evil.org/x", "https://user:pw@github.com/x",
           "https://evil.example/x", "ftp://github.com/x", "file:///etc/passwd", "https://127.0.0.1/x", "", "https:///x", "javascript:alert(1)"]
    assert all(U.host_allowed(u) for u in ok) and not any(U.host_allowed(u) for u in bad)
    assert U.host_allowed("http://127.0.0.1:8080/x", True) and U.host_allowed("http://localhost/x", True) and not U.host_allowed("http://127.0.0.1:8080/x")
    assert not U.host_allowed("http://evil.example/x", True) and not U.host_allowed("http://127.0.0.1.evil.com/x", True)


# ======================================================================= 2. recherche
def test_check_reports_uptodate_available_and_every_failure_without_trusting_github():
    srv, base = start_server()
    try:
        def run(**kw):
            return U.check("o/r", current=kw.pop("current", "1.10.2"), api=base, allow_loopback=True, **kw)
        Gh.status, Gh.redirect_to, Gh.release = 200, None, release(base, "1.99.0")
        r = run()
        assert r.state == "available" and r.update.version == "1.99.0" and r.update.deb_url.endswith("mintmail_1.99.0_all.deb") and r.update.sig_url and r.update.sums_url
        assert r.update.page.startswith("https://github.com/") and r.update.notes == "Nouveautés"
        assert Gh.seen_headers[-1]["User-Agent"] == "MintMail/1.10.2" and "Authorization" not in Gh.seen_headers[-1] and "Cookie" not in Gh.seen_headers[-1]    # requête anonyme
        assert run(current="1.99.0").state == "uptodate" and run(current="2.0.0").state == "uptodate"
        for flag in ("draft", "prerelease"):
            Gh.release = release(base, "1.99.0", **{flag: True})
            assert run().state == "uptodate", flag                                                   # brouillons et préversions : jamais proposés
        Gh.release = release(base, "1.99.0")
        r1 = run()
        assert r1.state == "available"
        Gh.release = release(base, "1.10.2")
        r2 = run()
        assert r2.state == "uptodate" and r2.etag == 'W/"v1"'
        assert run(etag='W/"v1"').state == "uptodate"                                                # 304 : inchangé
        for status, code in ((404, "norelease"), (403, "ratelimit"), (429, "ratelimit"), (500, "http")):
            Gh.status = status
            assert (run().state, run().code) == ("error", code), status
        Gh.status = 200
        Gh.release = b"pas du json"
        assert run().code == "badjson"
        Gh.release = b"[1, 2]"
        assert run().code == "badjson"
        Gh.release = release(base, "1.99.0", tag_name="latest")
        assert run().code == "badversion"
        Gh.release = release(base, "1.99.0", assets=[])
        assert run().code == "noasset"
        Gh.release = release(base, "1.99.0", assets=[{"name": "mintmail_9.9.9_all.deb", "size": 1, "browser_download_url": base + "/dl/x"}])
        assert run().code == "noasset"                                                               # le paquet doit porter LA version annoncée
        bad = release(base, "1.99.0")
        bad["assets"][0]["browser_download_url"] = "https://evil.example/mintmail_1.99.0_all.deb"
        Gh.release = bad
        assert run().code == "badurl"
        bad = release(base, "1.99.0")
        bad["assets"][1]["browser_download_url"] = "https://github.com.evil.org/x.sig"
        Gh.release = bad
        assert run().code == "badurl"
        Gh.release = release(base, "1.99.0")
        Gh.release["assets"][0]["size"] = U.MAX_DEB + 1
        assert run().code == "toobig"
        assert U.check("pas un dépôt", api=base, allow_loopback=True).code == "badrepo"
        assert U.check("o/r", current="n'importe quoi", api=base, allow_loopback=True).code == "badversion"
        Gh.release = release(base, "1.99.0")
        Gh.redirect_to = "https://evil.example/steal"                                                # redirection vers un hôte étranger : refusée
        assert run().state == "error"
        Gh.redirect_to = None
        assert U.check("o/r", api="https://127.0.0.1:1", allow_loopback=False).state == "error"      # http(s) local interdit hors test
        assert U.check("o/r", api="http://127.0.0.1:1", allow_loopback=True).code == "network"       # rien n'écoute : erreur propre
    finally:
        Gh.status, Gh.redirect_to = 200, None
        srv.shutdown()


# ======================================================================= 3. téléchargement et signature
def test_download_verifies_checksum_size_and_signature_and_keeps_files_private():
    srv, base = start_server()
    work = tempfile.mkdtemp()
    try:
        src = fake_deb(os.path.join(work, "src.deb"))
        data, sig = open(src, "rb").read(), open(sign(src), "rb").read()
        import hashlib
        name = "mintmail_1.99.0_all.deb"
        sums = ("%s  %s\n%s  autre.txt\n" % (hashlib.sha256(data).hexdigest(), name, "0" * 64)).encode()
        Gh.assets = {name: data, name + ".sig": sig, "SHA256SUMS": sums}
        Gh.release = release(base, "1.99.0")
        Gh.release["assets"][0]["size"] = len(data)
        up = U.check("o/r", current="1.0.0", api=base, allow_loopback=True).update
        dest = os.path.join(work, "dl")
        deb, sg = U.fetch(up, dest, allow_loopback=True)
        assert open(deb, "rb").read() == data and open(sg, "rb").read() == sig
        assert stat.S_IMODE(os.stat(dest).st_mode) == 0o700 and stat.S_IMODE(os.stat(deb).st_mode) == 0o600 and stat.S_IMODE(os.stat(sg).st_mode) == 0o600
        assert not [f for f in os.listdir(dest) if f.endswith(".part")]
        assert U.check_signature(deb, sg, GOOD_PUB) == ""
        assert U.check_signature(deb, sg, EVIL_PUB) == "bad_signature"                               # autre clé : refusée
        assert U.check_signature(deb, sg, os.path.join(work, "absente.pem")) == "nokey"
        assert U.check_signature(deb, None, GOOD_PUB) == "unsigned" and U.check_signature(deb, os.path.join(work, "nulle.sig"), GOOD_PUB) == "unsigned"
        tampered = os.path.join(work, "tampered.deb")
        open(tampered, "wb").write(data[:-1] + b"Y")                                                  # un seul octet modifié
        assert U.check_signature(tampered, sg, GOOD_PUB) == "bad_signature"
        forged = sign(tampered, EVIL_PRIV)
        assert U.check_signature(tampered, forged, GOOD_PUB) == "bad_signature"                       # signature d'un tiers sur un paquet piégé : refusée
        open(os.path.join(work, "garbage.sig"), "wb").write(b"n'importe quoi")
        assert U.check_signature(deb, os.path.join(work, "garbage.sig"), GOOD_PUB) == "bad_signature"
        # somme de contrôle fausse -> refus et fichier supprimé
        Gh.assets[name] = data[:-1] + b"Z"
        try:
            U.fetch(up, os.path.join(work, "dl2"), allow_loopback=True)
            raise AssertionError("somme de contrôle fausse acceptée")
        except U.UpdateError as e:
            assert e.code in ("checksum", "badsize")
        assert not os.path.exists(os.path.join(work, "dl2", name))
        Gh.assets[name] = data
        # taille annoncée fausse / dépassement du plafond
        wrong = U.Update(up.version, up.deb_url, len(data) + 5, up.sig_url, "", "", "")
        try:
            U.fetch(wrong, os.path.join(work, "dl3"), allow_loopback=True)
            raise AssertionError("taille incohérente acceptée")
        except U.UpdateError as e:
            assert e.code == "badsize"
        assert not [f for f in os.listdir(os.path.join(work, "dl3")) if f.endswith((".part", ".deb"))]
        old = U.MAX_DEB
        U.MAX_DEB = 50
        try:
            U.fetch(up, os.path.join(work, "dl4"), allow_loopback=True)
            raise AssertionError("plafond ignoré")
        except U.UpdateError as e:
            assert e.code == "toobig"
        finally:
            U.MAX_DEB = old
        assert not [f for f in os.listdir(os.path.join(work, "dl4")) if f.endswith((".part", ".deb"))]
        # hôte étranger dans l'adresse du paquet : jamais contacté
        evil = U.Update(up.version, "https://evil.example/x.deb", 0, "", "", "", "")
        hits = Gh.hits
        try:
            U.fetch(evil, os.path.join(work, "dl5"))
            raise AssertionError
        except U.UpdateError as e:
            assert e.code == "badurl" and Gh.hits == hits
        U.cleanup(base=os.path.join(work, "dl"))
        assert os.listdir(os.path.join(work, "dl")) == []
    finally:
        Gh.assets = {}
        srv.shutdown()


# ======================================================================= 4. appel de pkexec
def test_install_calls_pkexec_without_shell_with_a_minimal_environment_and_maps_results():
    calls = []

    def runner(code, out, err=""):
        def run(cmd, **kw):
            calls.append((cmd, kw))
            return subprocess.CompletedProcess(cmd, code, out, err)
        return run
    which = lambda n: "/usr/bin/pkexec" if n == "pkexec" else None
    os.environ["TEST_SECRET_TOKEN"] = "ne-doit-pas-fuiter"
    helper = os.path.join(tmp, "helper")
    open(helper, "w").write("x")
    ok = U.install("/d/a.deb", "/d/a.sig", runner(0, "OK:1.99.0\n"), which, helper)
    assert ok == (True, "", "1.99.0")
    cmd, kw = calls[-1]
    assert cmd == ["/usr/bin/pkexec", helper, "/d/a.deb", "/d/a.sig"] and not kw.get("shell") and "TEST_SECRET_TOKEN" not in kw["env"] and kw["timeout"] > 0
    assert U.install("/d/a.deb", "/d/a.sig", runner(3, "ERR:bad_signature:\n"), which, helper) == (False, "bad_signature", "")
    assert U.install("/d/a.deb", "/d/a.sig", runner(3, "ERR:install_failed:E: un | deux\n"), which, helper) == (False, "install_failed", "E: un | deux")
    assert U.install("/d/a.deb", "/d/a.sig", runner(126, ""), which, helper)[1] == "cancelled"
    assert U.install("/d/a.deb", "/d/a.sig", runner(127, ""), which, helper)[1] == "cancelled"
    assert U.install("/d/a.deb", "/d/a.sig", runner(0, "bruit sans OK"), which, helper)[:2] == (False, "internal")
    assert U.install("/d/a.deb", "/d/a.sig", runner(0, "OK:1\n"), lambda n: None, helper)[:2] == (False, "nohelper")
    assert U.install("/d/a.deb", "/d/a.sig", runner(0, "OK:1\n"), which, os.path.join(tmp, "absent"))[:2] == (False, "nohelper")

    def boom(cmd, **kw):
        raise OSError("x")
    assert U.install("/d/a.deb", "/d/a.sig", boom, which, helper)[:2] == (False, "internal")
    open(os.path.join(tmp, "pk.pem"), "w").write("x")
    assert U.can_install(os.path.join(tmp, "absent.pem"), helper, which) == (False, "nokey")
    assert U.can_install(os.path.join(tmp, "pk.pem"), os.path.join(tmp, "absent"), which) == (False, "nohelper")
    assert U.can_install(os.path.join(tmp, "pk.pem"), helper, lambda n: None) == (False, "nohelper")
    assert U.can_install(os.path.join(tmp, "pk.pem"), helper, which) == (True, "")


# ======================================================================= 5. programme administrateur
class Sys:
    """Simule dpkg / apt (le reste, dont openssl, est RÉEL) et enregistre ce qui est installé."""
    def __init__(self, installed="1:1.10.2", install_rc=0, mutate_after_verify=None):
        self.installed, self.install_rc, self.mutate, self.installs, self.out = installed, install_rc, mutate_after_verify, [], []

    def __call__(self, cmd, **kw):
        if cmd[0] in ("openssl", "sh"):
            r = subprocess.run(cmd, **kw)
            if self.mutate and cmd[0] == "openssl" and r.returncode == 0:
                self.mutate()                                   # un attaquant local remplace le fichier D'ORIGINE juste après la vérification
            return r
        if cmd[0] == "dpkg-deb":
            fields = dict(p.split("=", 1) for p in open(cmd[2], "rb").read().split(b"x")[0].decode().split(";") if "=" in p)
            return subprocess.CompletedProcess(cmd, 0, {"Package": fields["PKG"], "Architecture": fields["ARCH"], "Version": fields["VER"]}[cmd[3]] + "\n", "")
        if cmd[0] == "dpkg-query":
            return subprocess.CompletedProcess(cmd, 0 if self.installed else 1, self.installed, "")
        if cmd[0] == "dpkg":
            ver = lambda v: tuple(int(x) for x in v.split(":")[-1].split("."))
            return subprocess.CompletedProcess(cmd, 0 if ver(cmd[2]) > ver(cmd[4]) else 1, "", "")
        raise AssertionError("commande inattendue : %r" % (cmd,))

    def installer(self, deb):
        def record(*_):
            pass
        self.installs.append((deb, open(deb, "rb").read()))
        return ["sh", "-c", "exit %d" % self.install_rc] if self.install_rc == 0 else ["sh", "-c", "echo 'E: Sub-process dpkg returned an error code'; echo 'E: autre ligne' >&2; exit %d" % self.install_rc]


def helper_run(deb, sig, system=None, pubkey=GOOD_PUB, euid=0, argv=None, key_ok=lambda p: True, tmp_root=None):
    system = system or Sys()
    out = []
    code = A.main(argv if argv is not None else [deb, sig], euid=euid, pubkey=pubkey, key_ok=key_ok, run=system, installer=system.installer, tmp_root=tmp_root, out=out.append)
    return code, out[-1], system


def test_root_helper_installs_only_a_signed_newer_mintmail_package_from_a_private_copy():
    work = tempfile.mkdtemp()
    root = tempfile.mkdtemp()
    deb = fake_deb(os.path.join(work, "u.deb"), version="1:1.99.0")
    sig = sign(deb)
    code, out, sy = helper_run(deb, sig, tmp_root=root)
    assert (code, out) == (0, "OK:1:1.99.0") and len(sy.installs) == 1
    installed_path, installed_bytes = sy.installs[0]
    assert installed_bytes == open(deb, "rb").read() and os.path.dirname(installed_path).startswith(root) and os.listdir(root) == []         # copie privée, supprimée ensuite
    # refus : droits, arguments, clé
    assert helper_run(deb, sig, euid=1000)[:2] == (3, "ERR:not_root:")
    assert helper_run(deb, sig, argv=[deb])[1] == "ERR:usage:" and helper_run(deb, sig, argv=[deb, sig, "x"])[1] == "ERR:usage:" and helper_run(deb, sig, argv=[])[1] == "ERR:usage:"
    assert helper_run(deb, sig, pubkey=os.path.join(work, "absente.pem"))[1] == "ERR:nokey:"
    c, o, s2 = helper_run(deb, sig, key_ok=lambda p: False)
    assert o == "ERR:key_untrusted:" and not s2.installs
    # signature : mauvaise clé, paquet modifié, signature tierce, signature absente / vide / folle
    for evil_sig in (sign(deb, EVIL_PRIV),):
        c, o, s2 = helper_run(deb, evil_sig)
        assert o == "ERR:bad_signature:" and not s2.installs
    bad = fake_deb(os.path.join(work, "bad.deb"), version="1:1.99.0", pad=201)
    c, o, s2 = helper_run(bad, sig)                                                                  # signature d'un AUTRE fichier
    assert o == "ERR:bad_signature:" and not s2.installs
    open(os.path.join(work, "vide.sig"), "wb").close()
    assert helper_run(deb, os.path.join(work, "vide.sig"))[1] == "ERR:bad_signature:"
    assert helper_run(deb, os.path.join(work, "n-existe-pas.sig"))[1].startswith("ERR:bad_file:")
    # paquet : nom, architecture, version
    for kw, code_expected in (({"package": "autre"}, "bad_package"), ({"arch": "amd64"}, "bad_package"), ({"package": "mintmail-evil"}, "bad_package")):
        d = fake_deb(os.path.join(work, "p.deb"), version="1:1.99.0", **kw)
        c, o, s2 = helper_run(d, sign(d))
        assert o.startswith("ERR:%s:" % code_expected) and not s2.installs, kw
    for v in ("1:1.10.2", "1:1.10.1", "1:1.9.0"):                                                    # même version ou plus ancienne : pas de retour en arrière
        d = fake_deb(os.path.join(work, "old.deb"), version=v)
        c, o, s2 = helper_run(d, sign(d))
        assert o.startswith("ERR:not_newer:") and not s2.installs, v
    c, o, s2 = helper_run(deb, sig, system=Sys(installed=""))                                          # première installation : acceptée
    assert o == "OK:1:1.99.0" and len(s2.installs) == 1
    # échec d'installation : code propre, dossier privé supprimé
    c, o, s2 = helper_run(deb, sig, system=Sys(install_rc=100), tmp_root=root)
    assert c == 3 and o.startswith("ERR:install_failed:") and os.listdir(root) == []


def test_root_helper_rejects_symlinks_special_files_and_oversized_input_and_resists_file_swapping():
    work = tempfile.mkdtemp()
    root = tempfile.mkdtemp()
    deb = fake_deb(os.path.join(work, "u.deb"))
    sig = sign(deb)
    link = os.path.join(work, "lien.deb")
    os.symlink(deb, link)
    c, o, s = helper_run(link, sig)
    assert o.startswith("ERR:bad_file:") and not s.installs                                          # jamais de lien symbolique (ex. vers /etc/shadow)
    sig_link = os.path.join(work, "lien.sig")
    os.symlink(sig, sig_link)
    assert helper_run(deb, sig_link)[1].startswith("ERR:bad_file:")
    assert helper_run(work, sig)[1].startswith("ERR:bad_file:")                                      # un dossier
    assert helper_run("/dev/null", sig)[1].startswith("ERR:bad_file:")                               # un périphérique
    old = A.MAX_DEB
    A.MAX_DEB = 100
    try:
        assert helper_run(deb, sig)[1].startswith("ERR:bad_file:")                                   # plafond de taille
    finally:
        A.MAX_DEB = old
    old = A.MAX_SIG
    A.MAX_SIG = 10
    try:
        assert helper_run(deb, sig)[1].startswith("ERR:bad_file:")
    finally:
        A.MAX_SIG = old
    # substitution du fichier d'origine après la vérification : ce qui est installé est la copie vérifiée
    original = open(deb, "rb").read()
    swap = Sys(mutate_after_verify=lambda: open(deb, "wb").write(b"PKG=mintmail;ARCH=all;VER=1:9.9.9;xPAQUET PIEGE"))
    c, o, s = helper_run(deb, sig, system=swap, tmp_root=root)
    assert o == "OK:1:1.99.0" and s.installs[0][1] == original and b"PIEGE" not in s.installs[0][1]
    assert A.key_trusted(GOOD_PUB) is False or os.stat(GOOD_PUB).st_uid == 0                         # clé de test : appartient à l'utilisateur courant


def test_root_helper_trusts_only_root_owned_unwritable_keys():
    d = tempfile.mkdtemp()
    k = os.path.join(d, "k.pem")
    open(k, "w").write("x")
    if os.geteuid() == 0:
        os.chmod(d, 0o755); os.chmod(k, 0o644)
        assert A.key_trusted(k) is True
        os.chmod(k, 0o666)
        assert A.key_trusted(k) is False                                                             # modifiable par tous
        os.chmod(k, 0o664)
        assert A.key_trusted(k) is False                                                             # modifiable par le groupe
        os.chmod(k, 0o644); os.chmod(d, 0o777)
        assert A.key_trusted(k) is False                                                             # dossier modifiable : la clé pourrait être remplacée
        os.chmod(d, 0o755); os.chown(k, 1000, 1000)
        assert A.key_trusted(k) is False                                                             # n'appartient pas à root
    else:
        assert A.key_trusted(k) is False


def test_root_helper_never_prints_a_raw_traceback():
    out = []
    code = A.main(["a", "b"], euid=0, pubkey=GOOD_PUB, key_ok=lambda p: True, run=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boum")), out=out.append)
    assert code in (3, 4) and out[-1].startswith("ERR:") and "Traceback" not in out[-1]


# ======================================================================= 6. règle polkit, emballage
def test_polkit_policy_requires_admin_authentication_for_exactly_the_installed_helper():
    path = os.path.join(ROOT, "data", "me.saec.mintmail.update.policy")
    doc = xml.dom.minidom.parse(path)
    actions = doc.getElementsByTagName("action")
    assert len(actions) == 1 and actions[0].getAttribute("id") == "me.saec.mintmail.update"
    assert [a.firstChild.data for a in doc.getElementsByTagName("annotate") if a.getAttribute("key") == "org.freedesktop.policykit.exec.path"] == [U.HELPER]
    for tag in ("allow_any", "allow_inactive", "allow_active"):
        assert doc.getElementsByTagName(tag)[0].firstChild.data == "auth_admin", tag                 # jamais « yes » : mot de passe à chaque installation
    assert U.HELPER == "/usr/lib/mintmail/apply-update" and A.PUBKEY == U.PUBKEY == "/usr/share/mintmail/update-pubkey.pem"


def test_packaging_installs_helper_policy_and_key_with_safe_permissions():
    p = os.path.join(ROOT, "packaging", "build-deb.sh")
    if not os.path.exists(p):
        return
    s = open(p, encoding="utf-8").read()
    for needle in ("/usr/lib/mintmail/apply-update", "polkit-1/actions", "me.saec.mintmail.update.policy", "update-pubkey.pem", "-I -c", "from mintmail.apply_update import main",
                   "Recommends:"):
        assert needle in s, needle


# ======================================================================= 7. interface
class FakeCfg(dict):
    def save(self):
        self.saved = getattr(self, "saved", 0) + 1


class FakeBanner:
    def __init__(self):
        self.state, self.log = "hidden", []

    def show_available(self, up, current):
        self.state = "available"; self.log.append(("available", up.version, current))

    def show_progress(self, version, text, fraction=None):
        self.state = "progress"; self.log.append(("progress", version, text, fraction))

    def show_done(self, version):
        self.state = "done"; self.log.append(("done", version))

    def show_error(self, text, page=""):
        self.state = "error"; self.log.append(("error", text, page))

    def hide(self):
        self.state = "hidden"; self.log.append(("hide",))


class FakeChip:
    visible, label, tooltip = False, "", ""

    def set_visible(self, v):
        self.visible = bool(v)

    def set_label(self, t):
        self.label = t

    def set_tooltip_text(self, t):
        self.tooltip = t


def make_win(banner=False, **cfg):
    class W(UI.UpdateMixin):
        def get_application(self):
            return self.app
    w = W()
    w.app = types.SimpleNamespace(quit=lambda: w.__dict__.setdefault("quit_calls", []).append(1))
    if banner:
        w.update_banner, w.update_chip = FakeBanner(), FakeChip()
    w.config = FakeCfg({"update_check": True, "update_repo": "o/r", "update_last_check": 0, "update_etag": "", "update_seen": ""})
    w.config.update(cfg)
    w.toasts, w.settings, w.confirm_answer, w.confirm_calls = [], [], True, []
    w.toast = types.SimpleNamespace(popup=lambda text, label=None, cb=None, timeout=5: w.toasts.append((text, label, cb)))
    def run_bg(fn, done):                                      # comme la vraie méthode : l'exception est transmise, pas levée
        try:
            res, err = fn(), None
        except Exception as e:
            res, err = None, e
        done(res, err)
    w.run_bg = run_bg
    w.show_settings = lambda page=None, window=False: w.settings.append(page)
    w._confirm = lambda text, secondary="": (w.confirm_calls.append((text, secondary)), w.confirm_answer)[1]
    w._update = None
    w._update_busy = False
    w._update_views = []
    return w


def with_patches(**patches):
    saved = {k: getattr(U, k) for k in patches}
    for k, v in patches.items():
        setattr(U, k, v)
    return saved


def restore(saved):
    for k, v in saved.items():
        setattr(U, k, v)


def avail(version="1.99.0"):
    return U.Result("available", U.Update(version, "https://github.com/o/r/d.deb", 10, "https://github.com/o/r/d.sig", "", "Notes de version", "https://github.com/o/r/releases/tag/v" + version))


def test_automatic_check_runs_daily_shows_the_banner_persists_the_update_and_can_be_disabled():
    calls = []
    sv = with_patches(check=lambda repo, etag="": (calls.append((repo, etag)), avail())[1])
    try:
        w = make_win(banner=True, update_check=False)
        w.check_updates()
        assert calls == [] and w.update_banner.log == []                                           # désactivé : aucun accès réseau
        w = make_win(banner=True, update_last_check=__import__("time").time() - 60)
        w.check_updates()
        assert calls == []                                                                         # vérifié il y a une minute : rien
        w = make_win(banner=True)
        w.check_updates()
        assert calls == [("o/r", "")] and w._update.version == "1.99.0"
        assert w.update_banner.log[-1][:2] == ("available", "1.99.0") and w.update_chip.visible and "1.99.0" in w.update_chip.label and "1.99.0" in w.update_chip.tooltip
        assert w.toasts == []                                                                       # le bandeau remplace la notification éphémère
        saved = w.config["update_available"]
        assert saved["version"] == "1.99.0" and saved["deb_url"].startswith("https://github.com/") and w.config["update_seen"] == "1.99.0"
        # mise à jour disparue (installée ailleurs / retirée) : bandeau et pastille s'effacent, l'enregistrement aussi
        U.check = lambda repo, etag="": U.Result("uptodate", etag='W/"x"')
        w.config["update_last_check"] = 0
        w.check_updates()
        assert w._update is None and w.config["update_available"] is None and w.update_banner.state == "hidden" and not w.update_chip.visible
        assert w.config["update_etag"] == 'W/"x"' and w.toasts == []
        w.check_updates(manual=True)
        assert "à jour" in w.toasts[-1][0] or "up to date" in w.toasts[-1][0]
        # erreurs : silencieuses en automatique (on réessaiera), expliquées à la demande
        U.check = lambda repo, etag="": U.Result("error", code="ratelimit")
        w = make_win(banner=True)
        w.check_updates()
        assert w.toasts == [] and w.config["update_last_check"] == 0 and w.update_banner.log == [("hide",)] or w.update_banner.log == []
        w.check_updates(manual=True)
        assert w.toasts and w.config["update_last_check"] == 0
        w._update_busy = True
        n = len(calls)
        U.check = lambda repo, etag="": (calls.append(1), avail())[1]
        w.check_updates(manual=True)
        assert len(calls) == n                                                                      # pas deux recherches en même temps
    finally:
        restore(sv)


def test_a_known_update_is_shown_immediately_at_launch_and_forged_or_stale_saved_state_is_discarded():
    sv = with_patches(check=lambda *a, **k: (_ for _ in ()).throw(AssertionError("aucun accès réseau pour afficher le bandeau")))
    UI.GLib.timeout_add_seconds = lambda *a, **k: 1
    try:
        good = U.update_to_dict(avail("1.99.0").update)
        w = make_win(banner=True, update_available=good)
        w._init_updates()
        assert w._update.version == "1.99.0" and w.update_banner.log == [("available", "1.99.0", UI.__version__)] and w.update_chip.visible      # dès le lancement
        w = make_win(banner=True, update_available=dict(good, version=UI.__version__))                  # déjà installée depuis : oubliée
        w._init_updates()
        assert w._update is None and w.config["update_available"] is None and w.update_banner.state == "hidden" and not w.update_chip.visible
        for bad in (dict(good, deb_url="https://evil.example/x.deb"), dict(good, sig_url="http://github.com/x"), dict(good, version="99"), dict(good, version=["1.99.0"]),
                    dict(good, deb_size=-1), dict(good, deb_size=10 ** 12), "n'importe quoi", ["liste"], 42, {}):
            w = make_win(banner=True, update_available=bad)
            w._init_updates()
            assert w._update is None and w.update_banner.state == "hidden" and not w.update_chip.visible, bad
        w = make_win(banner=True, update_available=dict(good, page="https://evil.example/p"))             # page étrangère : on garde la mise à jour, sans la page
        w._init_updates()
        assert w._update.version == "1.99.0" and w._update.page == ""
        w = make_win(banner=True, update_available=good, update_snooze_version="1.99.0", update_snooze_until=__import__("time").time() + 3600)
        w._init_updates()
        assert w.update_banner.state == "hidden" and w.update_chip.visible                               # repoussée : pas de bandeau, mais la pastille reste
    finally:
        restore(sv)


def test_later_snoozes_the_banner_for_24h_for_that_version_only_and_manual_check_overrides():
    import time
    sv = with_patches(check=lambda repo, etag="": avail("1.99.0"))
    try:
        w = make_win(banner=True)
        w._update = avail("1.99.0").update
        w._refresh_update_ui()
        assert w.update_banner.state == "available"
        w.snooze_update()
        assert w.update_banner.state == "hidden" and w.update_chip.visible
        assert w.config["update_snooze_version"] == "1.99.0" and 86300 < w.config["update_snooze_until"] - time.time() <= 86400 and w.config.saved
        w._refresh_update_ui()
        assert w.update_banner.state == "hidden"                                                        # toujours repoussé
        w._update = avail("1.99.1").update
        w._refresh_update_ui()
        assert w.update_banner.state == "available"                                                     # une version PLUS récente réapparaît aussitôt
        w._update = avail("1.99.0").update
        w.update_banner.hide()
        w.config["update_snooze_until"] = time.time() - 1                                               # délai écoulé
        w._refresh_update_ui()
        assert w.update_banner.state == "available"
        w.snooze_update()
        w.config["update_last_check"] = 0
        w.check_updates(manual=True)                                                                    # demande explicite : on montre quand même le bandeau
        assert w.update_banner.state == "available" and w.config["update_snooze_until"] == 0
        w.hide_update_banner()                                                                          # ✕ : masqué pour cette session seulement
        assert w.update_banner.state == "hidden" and w.config["update_snooze_until"] == 0
    finally:
        restore(sv)


def test_installing_from_the_banner_has_no_modal_shows_progress_then_done_and_restart():
    stages = []
    deb, sg = os.path.join(tmp, "b.deb"), os.path.join(tmp, "b.sig")

    def fetch(up, d, progress=None, **k):
        for done_, total in ((0, 100), (40, 100), (100, 100)):
            progress(done_, total)
        return deb, sg
    sv = with_patches(can_install=lambda *a, **k: (True, ""), fetch=fetch, check_signature=lambda d, s, **k: "",
                      install=lambda d, s, **k: (stages.append("install"), (True, "", "1.99.0"))[1], cleanup=lambda *a, **k: stages.append("cleanup"))
    old_idle = UI.GLib.idle_add
    UI.GLib.idle_add = lambda f, *a: f(*a)
    try:
        w = make_win(banner=True, update_available=U.update_to_dict(avail().update))
        w._update = avail().update
        w.install_update(confirm=False)
        assert w.confirm_calls == []                                                                    # le bouton du bandeau EST la confirmation (la fenêtre système demande ensuite le mot de passe)
        prog = [e for e in w.update_banner.log if e[0] == "progress"]
        assert prog[0][2:] == ("Téléchargement…", 0.0) or prog[0][3] == 0.0
        assert any(e[3] == 0.4 for e in prog) and any(e[3] == 1.0 for e in prog)                         # la barre avance avec le téléchargement
        texts = [e[2] for e in prog]
        assert any("signature" in t for t in texts) and any("administrateur" in t for t in texts)        # puis vérification, puis installation
        assert stages == ["install", "cleanup"] and w.update_banner.log[-1] == ("done", "1.99.0") and w.update_banner.state == "done"
        assert w._update is None and w.config["update_available"] is None and not w.update_chip.visible and not w._update_busy
        w._update = avail().update
        w._update_busy = True
        n = len(w.update_banner.log)
        w.install_update(confirm=False)                                                                  # double clic : ignoré
        assert len(w.update_banner.log) == n
    finally:
        UI.GLib.idle_add = old_idle
        restore(sv)


def test_banner_install_failures_show_an_error_with_retry_and_keep_the_update_available():
    deb, sg = os.path.join(tmp, "c.deb"), os.path.join(tmp, "c.sig")
    outcome = {"sig": "bad_signature", "inst": (True, "", "1.99.0")}
    sv = with_patches(can_install=lambda *a, **k: (True, ""), fetch=lambda up, d, **k: (deb, sg), check_signature=lambda d, s, **k: outcome["sig"],
                      install=lambda d, s, **k: outcome["inst"], cleanup=lambda *a, **k: None)
    old_idle = UI.GLib.idle_add
    UI.GLib.idle_add = lambda f, *a: f(*a)
    try:
        w = make_win(banner=True)
        w._update = avail().update
        w.install_update(confirm=False)
        err = w.update_banner.log[-1]
        assert err[0] == "error" and "SIGNATURE" in err[1] and err[2].startswith("https://github.com/") and w._update is not None and not w._update_busy      # jamais installé
        outcome["sig"] = ""
        outcome["inst"] = (False, "cancelled", "")
        w.update_banner.state = "error"
        w.install_update(confirm=False)                                                                  # « Réessayer »
        assert w.update_banner.log[-1][0] == "error" and ("annulée" in w.update_banner.log[-1][1] or "cancelled" in w.update_banner.log[-1][1].lower())
        outcome["inst"] = (True, "", "1.99.0")
        w.install_update(confirm=False)
        assert w.update_banner.log[-1] == ("done", "1.99.0") and w._update is None                       # la nouvelle tentative réussit
        def boom(up, d, **k):
            raise U.UpdateError("checksum")
        U.fetch = boom
        w = make_win(banner=True)
        w._update = avail().update
        w.install_update(confirm=False)
        assert w.update_banner.log[-1][0] == "error" and ("contrôle" in w.update_banner.log[-1][1] or "checksum" in w.update_banner.log[-1][1].lower())
        U.can_install = lambda *a, **k: (False, "nokey")                                                 # clé absente : message clair dans le bandeau + page de la Release
        w = make_win(banner=True)
        w._update = avail().update
        w.install_update(confirm=False)
        assert w.update_banner.log[-1][0] == "error" and "clé" in w.update_banner.log[-1][1].lower() and w.toasts
    finally:
        UI.GLib.idle_add = old_idle
        restore(sv)


def test_restart_runs_a_fixed_command_in_a_detached_session_then_quits():
    calls, real_exists = [], os.path.exists
    old_popen, old_exists = UI.subprocess.Popen, os.path.exists
    UI.subprocess.Popen = lambda *a, **k: calls.append((a, k))
    try:
        os.path.exists = lambda p: True if p == "/usr/bin/mintmail" else real_exists(p)
        w = make_win(banner=True)
        w.restart_app()
        (args, kw), = calls
        assert args[0] == ["/bin/sh", "-c", "sleep 2; exec /usr/bin/mintmail"] and kw["start_new_session"] is True and not kw.get("shell")       # commande FIXE, aucun texte externe
        assert w.quit_calls == [1]
        calls.clear()
        os.path.exists = lambda p: False if p == "/usr/bin/mintmail" else real_exists(p)                 # lancé hors paquet : on ne relance pas, on le dit
        w = make_win(banner=True)
        w.restart_app()
        assert calls == [] and w.toasts and not getattr(w, "quit_calls", None)
    finally:
        UI.subprocess.Popen, os.path.exists = old_popen, old_exists


def test_release_notes_are_summarised_for_the_banner():
    assert U.short_notes("- Bandeau visible au lancement\n- Autre chose") == "Bandeau visible au lancement"
    assert U.short_notes("• Première\n• Seconde") == "Première" and U.short_notes("* Une étoile") == "Une étoile"
    long_text = U.short_notes("- " + "mot " * 80)
    assert len(long_text) <= 120 and long_text.endswith("…")
    assert U.short_notes("Texte sans puce\nSuite") == "Texte sans puce" and U.short_notes("") == "" and U.short_notes(None) == "" and U.short_notes("# Titre\n\n") == ""


def test_the_banner_widget_builds_and_goes_through_every_state_without_leaking_its_pulse_timer():
    win = types.SimpleNamespace(install_update=lambda **k: None, restart_app=lambda: None, open_update_page=lambda: None, snooze_update=lambda: None, hide_update_banner=lambda: None)
    removed = []
    old_remove = UI.GLib.source_remove
    UI.GLib.source_remove = lambda i: removed.append(i)
    UI.GLib.timeout_add = lambda *a, **k: 77
    try:
        b = UI.UpdateBanner(win)
        assert b.state == "hidden"
        b.show_available(avail().update, "1.0.0")
        assert b.state == "available"
        b.show_available(U.Update("1.99.0", "https://github.com/o/r/d.deb", 1, "", "", "", ""), "1.0.0")        # sans notes ni page : ne casse rien
        b.show_progress("1.99.0", "Téléchargement…", None)
        assert b.state == "progress" and b._pulse_id == 77                                                       # barre « indéterminée » animée
        b.show_progress("1.99.0", "Téléchargement…", 0.5)
        assert b._fraction == 0.5
        b.show_done("1.99.0")
        assert b.state == "done" and b._pulse_id is None and removed == [77]                                     # l'animation est bien arrêtée
        b.show_error("Erreur", "https://github.com/x")
        assert b.state == "error"
        b.hide()
        assert b.state == "hidden"
        assert b._pulse() is False
    finally:
        UI.GLib.source_remove = old_remove


def test_banner_css_exists_in_every_style_and_theme_with_style_specific_looks():
    from mintmail import style
    dec = lambda x: x.decode("utf-8") if isinstance(x, bytes) else x
    for st in style.STYLES:
        for dark in (True, False):
            base, fancy = (dec(x) for x in style.build_css(dark, style=st))
            for sel in (".update-banner", ".update-icon", ".update-title", ".update-sub", "button.update-install", ".update-chip", "progressbar progress"):
                assert sel in base, (st, dark, sel)
            assert "%(" not in base + fancy and base.count("{") == base.count("}") and fancy.count("{") == fancy.count("}"), (st, dark)
            if st == "aurora":
                assert "linear-gradient" in fancy.split(".update-banner", 1)[1][:300] and "box-shadow" in fancy.split(".update-banner", 1)[1][:400]
    papier = dec(style.build_css(False, style="papier")[0])
    assert "border-radius: 0; border-top: none; border-right: none;" in papier and "border-left: 4px solid @accent; margin: 0 14px;" in papier          # papier : filet latéral net
    papier_fancy = dec(style.build_css(False, style="papier")[1])
    assert ".update-banner {" not in papier_fancy.replace(".update-banner button", "")                                                             # papier : pas de dégradé ni d'ombre sur le cadre


def test_window_wires_the_banner_and_the_chip_and_restores_the_update_at_launch():
    src = open(os.path.join(ROOT, "mintmail", "window.py"), encoding="utf-8").read()
    assert "UpdateBanner(self)" in src and "mail_page.pack_start(self.update_banner" in src and "update_chip" in src and "self._init_updates()" in src
    assert src.index("pack_start(self.update_banner") < src.index("mail_page.pack_start(body")                    # sous la barre de titre, au-dessus du courrier
    ui = open(os.path.join(ROOT, "mintmail", "updates_ui.py"), encoding="utf-8").read()
    assert "self._restore_update()" in ui and "set_no_show_all(True)" in ui and "start_new_session=True" in ui and "shell=True" not in ui


def test_install_flow_confirms_downloads_verifies_then_calls_the_privileged_installer():
    log = []
    deb, sg = os.path.join(tmp, "a.deb"), os.path.join(tmp, "a.sig")
    sv = with_patches(can_install=lambda *a, **k: (True, ""), fetch=lambda up, d, **k: (log.append("fetch"), (deb, sg))[1], check_signature=lambda d, s, **k: (log.append("sig"), "")[1],
                      install=lambda d, s, **k: (log.append(("install", d, s)), (True, "", "1.99.0"))[1], cleanup=lambda *a, **k: log.append("cleanup"))
    try:
        w = make_win()
        w._update = avail().update
        w.confirm_answer = False
        w.install_update()
        assert log == [] and w.confirm_calls and "1.99.0" in w.confirm_calls[0][0] and "Notes de version" in w.confirm_calls[0][1]      # refus : rien n'est téléchargé
        w.confirm_answer = True
        w.install_update()
        assert log == ["fetch", "sig", ("install", deb, sg), "cleanup"] and w._update is None and "1.99.0" in w.toasts[-1][0] and not w._update_busy
        # signature invalide : jamais d'appel à l'installation
        log.clear()
        U.check_signature = lambda d, s, **k: (log.append("sig"), "bad_signature")[1]
        w = make_win()
        w._update = avail().update
        w.install_update()
        assert log == ["fetch", "sig"] and "SIGNATURE" in w.toasts[-1][0] and w._update is not None
        # installation refusée / annulée
        U.check_signature = lambda d, s, **k: ""
        U.install = lambda d, s, **k: (False, "cancelled", "")
        w = make_win()
        w._update = avail().update
        w.install_update()
        assert "annulée" in w.toasts[-1][0] or "cancelled" in w.toasts[-1][0].lower()
        # téléchargement en erreur
        def boom(up, d, **k):
            raise U.UpdateError("checksum")
        U.fetch = boom
        w = make_win()
        w._update = avail().update
        w.install_update()
        assert "contrôle" in w.toasts[-1][0] or "checksum" in w.toasts[-1][0].lower()
        # installation automatique impossible : on propose la page, sans rien télécharger
        log.clear()
        U.can_install = lambda *a, **k: (False, "nokey")
        U.fetch = lambda up, d, **k: log.append("fetch")
        w = make_win()
        w._update = avail().update
        w.install_update()
        assert log == [] and w.toasts and w.toasts[-1][1] and w.confirm_calls == []
        w = make_win()
        w.install_update()                                                                           # aucune mise à jour connue : rien
        assert w.toasts == []
    finally:
        restore(sv)


def test_every_update_error_code_has_a_translated_explanation():
    codes = ["network", "ratelimit", "norelease", "badrepo", "badjson", "badversion", "noasset", "badurl", "toobig", "badsize", "checksum", "http", "nokey", "unsigned",
             "bad_signature", "bad_package", "not_newer", "bad_file", "key_untrusted", "install_failed", "cancelled", "nohelper", "not_root", "usage", "internal"]
    texts = {c: UI.explain(c) for c in codes}
    assert all(t and "(%s)" not in t for t in texts.values()) and len(set(texts.values())) == len(codes)
    assert "zzz" in UI.explain("zzz")                                                                 # code inconnu : message générique avec le code
    import re
    for src in ("updater.py", "apply_update.py"):                                                     # tout code produit est expliqué
        text = open(os.path.join(ROOT, "mintmail", src), encoding="utf-8").read()
        for c in set(re.findall(r'(?:UpdateError|Refuse|Result\("error", code=|return Result\("error", code=)\(?"(\w+)"', text)) | set(re.findall(r'code="(\w+)"', text)):
            assert c in codes, (src, c)


def test_settings_have_safe_defaults_and_the_page_builds():
    from mintmail.store import DEFAULTS
    assert DEFAULTS["update_check"] is True and U.valid_repo(DEFAULTS["update_repo"]) and DEFAULTS["update_repo"] == U.DEFAULT_REPO
    assert DEFAULTS["update_last_check"] == 0 and DEFAULTS["update_etag"] == "" and DEFAULTS["update_seen"] == ""
    sync_src = open(os.path.join(ROOT, "mintmail", "syncdata.py"), encoding="utf-8").read()
    assert "update_" not in sync_src                                                                  # réglage propre à chaque machine : jamais synchronisé (un pair ne peut pas rediriger les mises à jour)
    w = make_win()
    page = UI.updates_page(w)
    assert page is not None and w._update_views


def test_updater_never_reads_the_verification_key_or_repo_from_untrusted_places():
    src = open(os.path.join(ROOT, "mintmail", "updater.py"), encoding="utf-8").read()
    assert 'PUBKEY = "/usr/share/mintmail/update-pubkey.pem"' in open(os.path.join(ROOT, "mintmail", "apply_update.py"), encoding="utf-8").read()
    assert "environ.get" not in src and "update_pubkey" not in src and "config" not in src.lower().replace("configuration", "")   # ni réglage, ni variable d'environnement ne désigne la clé
    ui = open(os.path.join(ROOT, "mintmail", "updates_ui.py"), encoding="utf-8").read()
    assert "shell=True" not in src + ui and "os.system" not in src + ui and "eval(" not in src + ui


# ======================================================================= 1.13.1 : déjà installée, notification, diagnostic, option « Aujourd'hui »
def test_restart_is_pending_only_when_the_installed_version_is_strictly_newer_than_the_running_one():
    old = U.disk_version
    try:
        for disk, running, expected in (("1.99.0", "1.13.0", "1.99.0"), ("1.13.0", "1.13.0", ""), ("1.12.0", "1.13.0", ""), ("", "1.13.0", ""), ("n'importe quoi", "1.13.0", "")):
            U.disk_version = lambda d=disk: d
            assert U.restart_pending(running) == expected, (disk, running)
    finally:
        U.disk_version = old
    assert U.disk_version() == open(os.path.join(ROOT, "mintmail", "VERSION")).read().strip()                  # lit bien le fichier VERSION installé


def test_an_update_already_installed_on_disk_shows_restart_not_an_announcement():
    old = U.restart_pending
    try:
        U.restart_pending = lambda current=None: "1.99.0"
        w = make_win(banner=True, update_available=U.update_to_dict(avail("1.99.0").update))
        w._update = avail("1.99.0").update
        w.update_chip.visible = True
        w._refresh_update_ui()
        assert w.update_banner.log[-1] == ("done", "1.99.0") and w._update is None and not w.update_chip.visible and w.config["update_available"] is None
        U.restart_pending = lambda current=None: "1.98.0"                                                       # disque plus ancien que l'annonce : annonce normale
        w = make_win(banner=True)
        w._update = avail("1.99.0").update
        w._refresh_update_ui()
        assert w.update_banner.log[-1][:2] == ("available", "1.99.0") and w.update_chip.visible
        U.restart_pending = lambda current=None: "1.99.0"                                                       # pendant une installation : le bandeau n'est pas écrasé
        w = make_win(banner=True)
        w._update = avail("1.99.0").update
        w.update_banner.state = "progress"
        w._refresh_update_ui()
        assert w.update_banner.state == "progress"
        w = make_win(banner=True)                                                                               # au lancement (état enregistré) : « relancer » directement
        w.config["update_available"] = U.update_to_dict(avail("1.99.0").update)
        UI.GLib.timeout_add_seconds = lambda *a, **k: 1
        w._init_updates()
        assert w.update_banner.log[-1] == ("done", "1.99.0")
    finally:
        U.restart_pending = old


def test_installing_something_already_installed_never_downloads_and_a_not_newer_refusal_becomes_a_restart():
    old_rp, sv = U.restart_pending, with_patches(can_install=lambda *a, **k: (True, ""), fetch=lambda *a, **k: (_ for _ in ()).throw(AssertionError("rien à télécharger")))
    try:
        U.restart_pending = lambda current=None: "1.99.0"
        w = make_win(banner=True)
        w._update = avail("1.99.0").update
        w.install_update(confirm=False)
        assert w.update_banner.log[-1] == ("done", "1.99.0") and w._update is None                              # plus de message trompeur : on propose de relancer
        # le programme administrateur répond « pas plus récente » alors que le disque est maintenant à jour : même issue
        calls = {"n": 0}

        def rp(current=None):
            calls["n"] += 1
            return "" if calls["n"] == 1 else "1.99.0"
        U.restart_pending = rp
        deb, sg = os.path.join(tmp, "d.deb"), os.path.join(tmp, "d.sig")
        U.fetch = lambda up, d, **k: (deb, sg)
        U.check_signature = lambda d, s, **k: ""
        U.install = lambda d, s, **k: (False, "not_newer", "1.99.0 <= 1.99.0")
        old_idle = UI.GLib.idle_add
        UI.GLib.idle_add = lambda f, *a: f(*a)
        try:
            w = make_win(banner=True)
            w._update = avail("1.99.0").update
            w.install_update(confirm=False)
        finally:
            UI.GLib.idle_add = old_idle
        assert w.update_banner.log[-1] == ("done", "1.99.0") and w._update is None
        U.restart_pending = lambda current=None: ""                                                              # disque pas à jour : c'est une vraie erreur, expliquée
        calls["n"] = 0
        w = make_win(banner=True)
        w._update = avail("1.99.0").update
        UI.GLib.idle_add = lambda f, *a: f(*a)
        try:
            w.install_update(confirm=False)
        finally:
            UI.GLib.idle_add = old_idle
        assert w.update_banner.log[-1][0] == "error" and w._update is not None
    finally:
        U.restart_pending = old_rp
        restore(sv)


def test_a_desktop_notification_announces_each_new_version_once_only_when_the_window_is_not_in_front():
    sent = []

    class N:
        def __init__(self, title):
            self.title, self.body = title, ""

        @staticmethod
        def new(title):
            return N(title)

        def set_body(self, b):
            self.body = b
    old_gio = UI.Gio
    UI.Gio = types.SimpleNamespace(Notification=N)
    sv = with_patches(check=lambda repo, etag="": avail("1.99.0"))
    try:
        def win(active=False, notifications=True):
            w = make_win(banner=True, notifications=notifications)
            w.is_active = lambda: active
            w.get_application = lambda: types.SimpleNamespace(send_notification=lambda ident, n: sent.append((ident, n.title, n.body)))
            return w
        w = win()
        w.check_updates()
        assert len(sent) == 1 and sent[0][0] == "update-available" and "1.99.0" in sent[0][1] and "Notes de version" in sent[0][2] or sent[0][2]
        w.config["update_last_check"] = 0
        w.check_updates()
        assert len(sent) == 1                                                                                   # même version : pas de seconde notification
        sent.clear()
        w = win(active=True)
        w.check_updates()
        assert sent == []                                                                                       # fenêtre au premier plan : le bandeau suffit
        w = win(notifications=False)
        w.check_updates()
        assert sent == []                                                                                       # notifications désactivées : respecté
        w = win()
        w.check_updates(manual=True)
        assert sent == []                                                                                       # demande explicite : pas de notification
    finally:
        UI.Gio = old_gio
        restore(sv)


def test_the_last_result_is_remembered_logged_and_errors_are_explained_on_the_updates_page():
    import mintmail.log as L
    lines = []
    old_log = L.log
    L.log = lambda m: lines.append(m)
    try:
        for res, expected in ((avail("1.99.0"), "available:1.99.0"), (U.Result("uptodate"), "uptodate"), (U.Result("error", code="ratelimit"), "error:ratelimit")):
            sv = with_patches(check=lambda repo, etag="", r=res: r)
            try:
                w = make_win(banner=True)
                w.check_updates(manual=True)
                assert w.config["update_last_result"] == expected
            finally:
                restore(sv)
        assert len(lines) == 3 and "manuelle" in lines[0] and "error:ratelimit" in lines[2]
        w = make_win(banner=True, update_last_result="error:ratelimit")
        page = UI.updates_page(w)                                                                                # la page se construit avec un dernier résultat en erreur
        assert page is not None
    finally:
        L.log = old_log


def test_check_update_cli_reports_exactly_where_things_stand_without_installing_anything():
    from mintmail import entry
    srv, base = start_server()
    try:
        def run_cli():
            lines = []
            code = entry.check_update_cli(api=base, allow_loopback=True, out=lines.append)
            return code, "\n".join(lines)
        Gh.status, Gh.redirect_to = 200, None
        Gh.release = release(base, "99.0.0")
        code, text = run_cli()
        assert code == 10 and "99.0.0" in text and "saec-oolivvv/mintmail" in text and "Nouveautés" in text and ("oui" in text or "yes" in text.lower()), text
        Gh.release = release(base, "99.0.0", with_sig=False)
        code, text = run_cli()
        assert code == 10 and ("NON" in text or "NO " in text)                                                  # une version sans signature est signalée comme refusée
        Gh.release = release(base, "0.0.1")
        code, text = run_cli()
        assert code == 0 and ("à jour" in text or "up to date" in text)
        Gh.status = 404
        code, text = run_cli()
        assert code == 1 and "norelease" in text
        Gh.status = 403
        assert run_cli()[0] == 1 and "ratelimit" in run_cli()[1]
    finally:
        Gh.status = 200
        srv.shutdown()
    seen = []
    old = entry.check_update_cli
    entry.check_update_cli = lambda *a, **k: (seen.append(1), 10)[1]
    try:
        assert entry.main(["mintmail", "--check-update"]) == 10 and seen == [1]                                 # l'option est bien branchée sur la ligne de commande
    finally:
        entry.check_update_cli = old


def test_open_today_at_launch_is_an_off_by_default_option_wired_from_the_settings():
    from mintmail import extras
    from mintmail.store import DEFAULTS
    assert DEFAULTS["open_today_on_start"] is False
    shown, scheduled = [], []
    old = extras.GLib.timeout_add
    extras.GLib.timeout_add = lambda ms, f: (scheduled.append(ms), f())
    try:
        class W:
            config = {"open_today_on_start": True}
            show_today = lambda self: shown.append(1)
        extras.ExtrasMixin.open_today_at_start(W())
        assert shown == [1] and scheduled == [1200]
        W.config = {"open_today_on_start": False}
        extras.ExtrasMixin.open_today_at_start(W())
        assert shown == [1] and scheduled == [1200]                                                              # désactivé : rien n'est programmé
    finally:
        extras.GLib.timeout_add = old
    src = open(os.path.join(ROOT, "mintmail", "window.py"), encoding="utf-8").read()
    assert "self.open_today_at_start()" in src and src.index("self._init_updates()") < src.index("self.open_today_at_start()")
    st = open(os.path.join(ROOT, "mintmail", "settings.py"), encoding="utf-8").read()
    assert 'open_today_on_start' in st and "Ouvrir la page Aujourd'hui au lancement" in st


# ======================================================================= 1.13.3 : recherche à CHAQUE démarrage
def test_the_check_runs_at_every_launch_even_if_one_was_made_minutes_ago_and_a_release_published_meanwhile_shows_the_banner():
    import time
    seen = []
    sv = with_patches(check=lambda repo, etag="": (seen.append(etag), avail("1.99.0"))[1])
    scheduled = []
    old_timer = UI.GLib.timeout_add_seconds
    UI.GLib.timeout_add_seconds = lambda secs, fn: scheduled.append((secs, fn)) or 1
    try:
        # le scénario signalé : « Vérifier maintenant » ce matin (à jour), puis publication, puis relance
        w = make_win(banner=True, update_last_check=time.time() - 60, update_etag='W/"abc"')
        w._init_updates()
        assert [s for s, _ in scheduled] == [8, 3600]                                                         # démarrage + minuterie horaire
        scheduled[1][1]()                                                                                      # la minuterie horaire respecte la règle « due » : vérifié il y a 1 min → rien
        assert seen == [] and w.update_banner.state == "hidden"
        scheduled[0][1]()                                                                                      # le démarrage, lui, cherche TOUJOURS
        assert seen == ['W/"abc"'] and w.update_banner.log[-1][:2] == ("available", "1.99.0") and w.update_chip.visible    # requête conditionnelle (ETag) + bandeau
        assert w.config["update_available"]["version"] == "1.99.0"
        # désactivée dans les réglages : même au démarrage, aucun accès réseau
        seen.clear()
        w2 = make_win(banner=True, update_check=False)
        scheduled.clear()
        w2._init_updates()
        scheduled[0][1]()
        assert seen == [] and w2.update_banner.log == [("hide",)] or seen == []
        # sans mise à jour connue l'ETag est envoyé ; AVEC une mise à jour déjà connue on le retire pour recevoir son contenu complet
        w3 = make_win(banner=True, update_etag='W/"xyz"')
        w3._update = avail("1.99.0").update
        w3.check_updates(startup=True)
        assert seen[-1] == ""
    finally:
        UI.GLib.timeout_add_seconds = old_timer
        restore(sv)


def test_the_periodic_interval_is_six_hours_and_the_texts_say_so():
    import time
    assert U.CHECK_INTERVAL == 6 * 3600
    now = time.time()
    assert not U.due(now, now - 3600) and not U.due(now, now - 5 * 3600) and U.due(now, now - 6 * 3600 - 1) and U.due(now, 0) and U.due(now, now + 7200)
    docs = open(os.path.join(ROOT, "docs", "UPDATES.md"), encoding="utf-8").read()
    assert "chaque** démarrage" in docs and "6 heures" in docs and "une fois par jour" not in docs
    src = open(os.path.join(ROOT, "mintmail", "updates_ui.py"), encoding="utf-8").read()
    assert "Rechercher automatiquement (au démarrage, puis toutes les 6 heures)" in src and "une fois par jour\")" not in src


def test_check_update_cli_says_why_the_banner_is_or_is_not_shown():
    import time
    from mintmail import entry
    from mintmail.store import Config
    srv, base = start_server()
    cfg = Config()
    keys = ("update_available", "update_snooze_until", "update_snooze_version")
    saved = {k: cfg.get(k) for k in keys}

    def line():
        lines = []
        entry.check_update_cli(api=base, allow_loopback=True, out=lines.append)
        return [l for l in lines if "Bandeau" in l or "banner" in l.lower()][0]
    try:
        Gh.status, Gh.redirect_to, Gh.release = 200, None, release(base, "0.0.1")
        cfg["update_available"], cfg["update_snooze_until"], cfg["update_snooze_version"] = None, 0, ""
        cfg.save()
        assert "aucune mise à jour mémorisée" in line()
        cfg["update_available"] = U.update_to_dict(avail("99.0.0").update)
        cfg.save()
        assert "99.0.0" in line() and "s'affiche au lancement" in line()
        cfg["update_snooze_version"], cfg["update_snooze_until"] = "99.0.0", time.time() + 3600
        cfg.save()
        assert "repoussée jusqu'à" in line() and "99.0.0" in line()
        cfg["update_available"] = dict(U.update_to_dict(avail("99.0.0").update), deb_url="https://evil.example/x.deb")      # état falsifié : pas de bandeau, et le diagnostic le dit
        cfg.save()
        assert "aucune mise à jour mémorisée" in line()
    finally:
        for k, v in saved.items():
            cfg[k] = v
        cfg.save()
        Gh.status = 200
        srv.shutdown()
