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

    def run(cmd, **kw):
        seen.append((cmd, kw.get("input")))
        return R(0, "motdepasse\n")
    assert store.mac_keychain("set_password", "mintmail", "acc1", 'p"w\\x', run=run) is True
    cmd, stdin = seen[-1]
    assert cmd == ["/usr/bin/security", "-i"] and "p" in stdin and "-T /usr/bin/security" in stdin and "-U" in stdin
    assert 'p\\"w\\\\x' in stdin and not any("p\"w" in str(a) for a in cmd)                    # le secret n'est jamais dans la ligne de commande
    assert store.mac_keychain("get_password", "mintmail", "acc1", run=run) == "motdepasse"
    assert seen[-1][0][:2] == ["/usr/bin/security", "find-generic-password"] and "MintMail" in seen[-1][0]
    assert store.mac_keychain("get_password", "mintmail", "x", run=lambda *a, **k: R(44, "", "not found")) is None
    assert store.mac_keychain("set_password", "mintmail", "x", "a\nb", run=run) is False        # un saut de ligne casserait la commande : repli fichier 0600
    assert store.mac_keychain("get_password", "mintmail", "x", run=lambda *a, **k: (_ for _ in ()).throw(OSError("absent"))) is None


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
