"""Trousseau : une réponse lente (fenêtre de mot de passe sur Mac) est rejointe, jamais redemandée."""
import os, sys
import testenv  # noqa: F401


def test_a_slow_keychain_answer_is_joined_not_asked_again():
    """Mac : la fenêtre du trousseau reste ouverte plus longtemps que l'attente ; l'ancien code abandonnait puis redemandait en boucle."""
    import threading, time, types
    from mintmail import store
    os.environ.pop("MINTMAIL_NO_KEYRING", None)
    calls = []
    def slow_get(service, account):
        calls.append(account)
        time.sleep(0.6)
        return "secret"
    fake = types.ModuleType("keyring")
    fake.get_password = slow_get
    old = sys.modules.get("keyring")
    sys.modules["keyring"] = fake
    try:
        assert store._keyring("get_password", "mintmail", "acc", timeout=0.1) is None and store.keyring_pending("get_password", "mintmail", "acc")
        assert store._keyring("get_password", "mintmail", "acc", timeout=0.1) is None          # rejoint le même appel : pas de nouvelle fenêtre
        assert store._keyring("get_password", "mintmail", "acc", timeout=3) == "secret"
        assert calls == ["acc"] and not store.keyring_pending("get_password", "mintmail", "acc")
    finally:
        os.environ["MINTMAIL_NO_KEYRING"] = "1"
        if old is None:
            sys.modules.pop("keyring", None)
        else:
            sys.modules["keyring"] = old


def test_mac_keychain_goes_through_the_apple_security_tool_without_the_password_on_the_command_line():
    from mintmail import store

    class R:
        def __init__(self, rc=0, out="", err=""):
            self.returncode, self.stdout, self.stderr = rc, out, err
    seen = []
    stored = {}

    def run(cmd, **kw):
        seen.append((cmd, kw.get("input")))
        if cmd[:2] == ["/usr/bin/security", "-i"]:
            stored["hex"] = kw["input"].split("-X ")[1].split()[0]
            return R(0)
        if "find-generic-password" in cmd and "hex" in stored:
            b = bytes.fromhex(stored["hex"])
            try:
                s = b.decode("ascii")
                shown = '"%s"' % s if s.isprintable() else "0x%s" % stored["hex"].upper()
            except UnicodeDecodeError:
                shown = "0x%s  \"?\"" % stored["hex"].upper()
            return R(0, "", "keychain: x\npassword: %s\n" % shown)
        return R(44, "", "not found")
    for pw in ('p"w\\x $1 !#', "mot de passe é€", "0xabc"):
        stored.clear()
        assert store.mac_keychain("set_password", "mintmail", "acc1", pw, run=run) is True
        cmd, _stdin = [x for x in seen if x[0][:2] == ["/usr/bin/security", "-i"]][-1]
        assert not any(pw in str(a) for a in cmd) and "-T /usr/bin/security" in _stdin and "-U" in _stdin and pw not in _stdin
        assert store.mac_keychain("get_password", "mintmail", "acc1", run=run) == pw         # aller-retour exact
    assert store.mac_keychain("get_password", "mintmail", "x", run=lambda *a, **k: R(44, "", "not found")) is None
    assert store.mac_keychain("set_password", "mintmail", "x", "a\0b", run=run) is False
    assert store.mac_keychain("get_password", "mintmail", "x", run=lambda *a, **k: (_ for _ in ()).throw(OSError("absent"))) is None
    assert store._mac_parse_secret('password: "ab cd"') == "ab cd" and store._mac_parse_secret("password:") is None
    # écriture non relue à l'identique : refusée, le mot de passe reste dans le repli fichier 0600
    assert store.mac_keychain("set_password", "mintmail", "z", "secret", run=lambda *a, **k: R(0, "", "")) is False


def test_ca_bundle_is_taken_from_certifi_only_when_the_system_gives_none():
    from mintmail import netutil
    ctx = lambda n: (lambda: type("C", (), {"cert_store_stats": lambda self: {"x509_ca": n}})())
    here = os.path.abspath(__file__)
    env = {}
    assert netutil.ensure_ca_bundle(env, ctx(0), lambda: here) == here and env["SSL_CERT_FILE"] == here        # aucun certificat système : certifi
    env = {}
    assert netutil.ensure_ca_bundle(env, ctx(140), lambda: here) == "" and env == {}                          # le système suffit : rien à faire
    env = {"SSL_CERT_FILE": "/x"}
    assert netutil.ensure_ca_bundle(env, ctx(0), lambda: here) == "" and env == {"SSL_CERT_FILE": "/x"}       # choix de l'utilisateur respecté
    env = {}
    assert netutil.ensure_ca_bundle(env, ctx(0), lambda: "/n'existe/pas") == "" and env == {}
    assert netutil.ensure_ca_bundle({}, ctx(0), lambda: (_ for _ in ()).throw(ImportError("certifi")) ) == ""      # certifi absent : sans effet


def test_backend_rereads_the_password_at_every_connection_instead_of_freezing_an_empty_one():
    from mintmail import backend
    pws = iter(["", "", "secret"])                          # trousseau lent au démarrage : vide, vide, puis le vrai mot de passe
    seen = []

    class Imap:
        def __init__(self, *a, **k):
            pass

        def login(self, user, pw):
            seen.append((user, pw))
            return "OK", []
    old = backend.imaplib.IMAP4_SSL
    backend.imaplib.IMAP4_SSL = Imap
    try:
        b = backend.IMAPBackend({"id": "a", "email": "x@y.z", "imap_host": "h", "imap_port": 993}, "", password_provider=lambda: next(pws))
        for _ in range(2):
            try:
                b._connect()
                assert False, "un mot de passe vide ne doit jamais être envoyé au serveur"
            except backend.BackendError as e:
                assert e.retryable
        assert seen == []
        b._connect()
        assert seen == [("x@y.z", "secret")]
    finally:
        backend.imaplib.IMAP4_SSL = old
