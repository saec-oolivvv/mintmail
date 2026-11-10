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


def make_win(**cfg):
    class W(UI.UpdateMixin):
        pass
    w = W()
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


def test_automatic_check_runs_daily_announces_each_version_once_and_can_be_disabled():
    calls = []
    sv = with_patches(check=lambda repo, etag="": (calls.append((repo, etag)), avail())[1])
    try:
        w = make_win(update_check=False)
        w.check_updates()
        assert calls == [] and w.toasts == []                                                        # désactivé : aucun accès réseau
        w = make_win(update_last_check=__import__("time").time() - 60)
        w.check_updates()
        assert calls == []                                                                           # vérifié il y a une minute : rien
        w = make_win()
        w.check_updates()
        assert calls == [("o/r", "")] and w._update.version == "1.99.0" and len(w.toasts) == 1 and "1.99.0" in w.toasts[0][0]
        assert w.config["update_seen"] == "1.99.0" and w.config["update_last_check"] > 0 and w.toasts[0][1]
        w.toasts[0][2]()
        assert w.settings == ["updates"]                                                             # le bouton « Voir » ouvre la page
        w.config["update_last_check"] = 0
        w.check_updates()
        assert len(w.toasts) == 1                                                                    # même version : pas de nouvelle annonce
        w.check_updates(manual=True)
        assert len(w.toasts) == 2                                                                    # à la demande : toujours une réponse
        w._update_busy = True
        n = len(calls)
        w.check_updates(manual=True)
        assert len(calls) == n                                                                       # pas deux recherches en même temps
        # à jour / erreurs
        U.check = lambda repo, etag="": U.Result("uptodate", etag='W/"x"')
        w = make_win(update_last_check=0)
        w._update = avail().update
        w.check_updates()
        assert w._update is None and w.config["update_etag"] == 'W/"x"' and w.toasts == []
        w.check_updates(manual=True)
        assert "à jour" in w.toasts[-1][0] or "up to date" in w.toasts[-1][0]
        U.check = lambda repo, etag="": U.Result("error", code="ratelimit")
        w = make_win()
        w.check_updates()
        assert w.toasts == [] and w.config["update_last_check"] == 0                                 # erreur silencieuse en automatique, et on réessaiera
        w.check_updates(manual=True)
        assert w.toasts and w.config["update_last_check"] == 0
    finally:
        restore(sv)


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
