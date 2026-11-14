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
