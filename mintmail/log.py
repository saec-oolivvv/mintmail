"""Journal d'erreurs : rien n'échoue en silence."""
import sys
import time
import traceback

from .store import DATA_DIR

LOG = DATA_DIR / "mintmail.log"


def log(msg):
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if LOG.exists() and LOG.stat().st_size > 500_000:
            LOG.replace(DATA_DIR / "mintmail.log.old")
        with open(LOG, "a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    except OSError:
        pass


def log_exception(where=""):
    log("%s\n%s" % (where, traceback.format_exc()))


def tail(n=80):
    try:
        return "".join(LOG.read_text(encoding="utf-8", errors="replace").splitlines(True)[-n:]) or "(journal vide)"
    except OSError:
        return "(journal vide)"


def install_hook(on_error=None):
    def hook(etype, value, tb):
        text = "".join(traceback.format_exception(etype, value, tb))
        log("Exception non gérée :\n" + text)
        sys.__excepthook__(etype, value, tb)
        if on_error:
            try:
                on_error(value)
            except Exception:
                pass
    sys.excepthook = hook
