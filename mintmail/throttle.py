"""Frein aux reconnexions : après un refus de connexion (mauvais mot de passe, « trop de tentatives », « trop de connexions »…), MintMail attend de plus en plus
longtemps avant de réessayer au lieu de marteler le serveur — c'est ce qui fait bloquer une adresse. Pur, sans réseau, sûr entre fils."""
import hashlib
import threading
import time

AUTH, BUSY = "auth", "busy"
STEPS = {AUTH: (120, 300, 900, 1800, 3600), BUSY: (30, 60, 120, 300, 600)}      # secondes d'attente après le 1er, 2e, 3e… refus de suite

_AUTH_WORDS = ("authenticationfailed", "authentication failed", "login failed", "invalid credentials", "invalid login", "auth failed", "incorrect password",
               "wrong password", "too many login", "too many failed", "too many invalid", "blocked", "temporarily disabled", "account is locked", "web login required",
               "application-specific password", "app password", "authorization failed", "nologin", "[authenticationfailed]")
_BUSY_WORDS = ("too many connections", "too many simultaneous", "maximum number of connections", "max connections", "exceeded the maximum", "connection limit",
               "throttle", "rate limit", "try again later", "temporary failure", "[unavailable]", "[inuse]",
               "429", "too many requests", "quota", "ratelimit", "rate_limit", "userratelimitexceeded", "resource_exhausted", "bandwidth limit")


def classify(message):
    """AUTH (identifiants refusés / trop d'essais), BUSY (trop de connexions, limitation) ou None (problème sans rapport : réseau…)."""
    low = str(message or "").lower()
    if any(w in low for w in _BUSY_WORDS) and not any(w in low for w in ("authenticationfailed", "invalid credentials")):
        return BUSY
    if any(w in low for w in _AUTH_WORDS):
        return AUTH
    return None


def fingerprint(secret):
    """Empreinte du mot de passe (pour savoir qu'il a changé) — jamais le mot de passe lui-même."""
    return hashlib.sha256(("mm:" + str(secret or "")).encode("utf-8")).hexdigest()[:12]


class Breaker:
    def __init__(self, clock=time.time):
        self._lock = threading.Lock()
        self._st = {}                      # clé -> {"until", "n", "kind", "fp"}
        self.clock = clock

    def failed(self, key, kind, fp=""):
        """Enregistre un refus ; retourne le nombre de secondes d'attente décidé."""
        steps = STEPS[kind]
        with self._lock:
            st = self._st.get(key)
            n = (st["n"] if st and st["fp"] == fp else 0) + 1
            wait = steps[min(n, len(steps)) - 1]
            self._st[key] = {"until": self.clock() + wait, "n": n, "kind": kind, "fp": fp}
        return wait

    def left(self, key, fp=""):
        """Secondes restantes avant le prochain essai permis (0 : on peut y aller). Un mot de passe modifié lève le frein tout de suite."""
        with self._lock:
            st = self._st.get(key)
            if not st:
                return 0
            if st["kind"] == AUTH and st["fp"] != fp:
                self._st.pop(key, None)
                return 0
            return max(0, int(st["until"] - self.clock() + 0.999))

    def ok(self, key):
        with self._lock:
            self._st.pop(key, None)

    def reset(self, key=None):
        with self._lock:
            if key is None:
                self._st.clear()
            else:
                self._st.pop(key, None)

    def info(self, key):
        with self._lock:
            return dict(self._st.get(key) or {})


def human_wait(seconds):
    s = int(seconds)
    if s < 90:
        return "%d s" % s
    return "%d min" % ((s + 59) // 60)
