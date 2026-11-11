"""Isolation des tests : jamais le trousseau, le dossier personnel ni les réglages réels de l'utilisateur
(défaut corrigé en 1.12.1 : sur une machine avec trousseau, la batterie écrasait la vraie clé d'API « ai:nvidia » par « nvapi-test »)."""
import os, sys, tempfile, types
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gtkstub   # noqa: F401
from mintmail import store


def _with_fake_keyring(fn):
    calls = []
    fake = types.ModuleType("keyring")
    for op in ("get_password", "set_password", "delete_password"):
        setattr(fake, op, lambda *a, _op=op, **k: calls.append((_op, a)) or "VRAIE-CLE")
    old = sys.modules.get("keyring")
    sys.modules["keyring"] = fake
    try:
        return fn(calls, fake)
    finally:
        if old is None:
            sys.modules.pop("keyring", None)
        else:
            sys.modules["keyring"] = old


def test_keyring_is_never_called_while_testing():
    def body(calls, fake):
        assert os.environ["MINTMAIL_NO_KEYRING"] == "1"
        c = store.Config(os.path.join(tempfile.mkdtemp(), "c.json"))
        c.set_password("ai:nvidia", "nvapi-test")
        c.set_password("acc1", "secret")
        assert c.password("ai:nvidia") == "nvapi-test" and c.password("acc1") == "secret"      # repli : fichier temporaire de test
        c.set_password("acc1", "")
        assert store._keyring("get_password", "mintmail", "ai:nvidia") is None
        assert calls == [], calls                                                              # le trousseau (même présent) n'a jamais été appelé
    _with_fake_keyring(body)


def test_the_guard_is_off_in_normal_use_so_the_real_keyring_still_works():
    def body(calls, fake):
        seen = {}
        fake.set_password = lambda *a: seen.__setitem__("set", a)
        fake.get_password = lambda *a: "valeur"
        env = os.environ.pop("MINTMAIL_NO_KEYRING")
        try:
            assert store._keyring("get_password", "mintmail", "x") == "valeur"
            assert store._keyring("set_password", "mintmail", "x", "v") is True and seen["set"] == ("mintmail", "x", "v")
        finally:
            os.environ["MINTMAIL_NO_KEYRING"] = env
    _with_fake_keyring(body)


def test_tests_run_inside_temporary_directories_not_the_users_real_ones():
    tmpdir = os.path.realpath(tempfile.gettempdir())
    for path in (store.DATA_DIR, store.CONFIG_DIR):
        assert os.path.realpath(str(path)).startswith(tmpdir), path
    assert os.path.realpath(os.environ["HOME"]).startswith(tmpdir), os.environ["HOME"]
