"""Journal d'activité en temps réel : ce que MintMail fait avec vos boîtes (relève, suppression, déplacement, drapeaux…), affiché dans le pied de page.
Pur et sans Qt ; sûr à appeler depuis n'importe quel fil. `LOG` est le journal partagé du moteur."""
import threading
import time
from collections import deque

from .i18n import tr

INFO, OK, WARN, ERR, BUSY = "info", "ok", "warn", "err", "busy"
ICONS = {INFO: "•", OK: "✔", WARN: "⚠", ERR: "✖", BUSY: "⟳"}


class Log:
    def __init__(self, maxlen=400):
        self._lock = threading.Lock()
        self._items = deque(maxlen=maxlen)
        self._busy = {}                    # clé -> (ts, texte) : opérations en cours
        self._subs = []
        self.seq = 0

    # -- écriture
    def add(self, level, text, account=""):
        item = {"ts": time.time(), "level": level, "text": str(text), "account": account}
        with self._lock:
            self._items.append(item)
            self.seq += 1
        self._notify()
        return item

    def start(self, key, text, account=""):
        """Une opération démarre (affichée « en cours » tant que finish n'est pas appelé)."""
        with self._lock:
            self._busy[key] = (time.time(), str(text), account)
            self.seq += 1
        self._notify()

    def finish(self, key, level=None, text="", account=""):
        with self._lock:
            self._busy.pop(key, None)
            if level:
                self._items.append({"ts": time.time(), "level": level, "text": str(text), "account": account})
            self.seq += 1
        self._notify()

    def clear(self):
        with self._lock:
            self._items.clear()
            self._busy.clear()
            self.seq += 1
        self._notify()

    # -- lecture
    def entries(self, n=200):
        """Les n dernières entrées, la plus récente en premier."""
        with self._lock:
            return list(self._items)[-n:][::-1]

    def busy(self):
        with self._lock:
            return [v[1] for v in sorted(self._busy.values())]

    def current(self):
        """(niveau, texte) du pied de page : l'opération en cours si elle existe, sinon la dernière entrée ; (None, '') si rien."""
        with self._lock:
            if self._busy:
                texts = [v[1] for v in sorted(self._busy.values())]
                return BUSY, texts[-1] + ("  (+%d)" % (len(texts) - 1) if len(texts) > 1 else "")
            if self._items:
                it = self._items[-1]
                return it["level"], it["text"]
        return None, ""

    def errors_since(self, ts):
        with self._lock:
            return [i for i in self._items if i["level"] == ERR and i["ts"] >= ts]

    # -- abonnés (appelés dans le fil qui écrit : à eux de rebondir vers l'interface)
    def subscribe(self, cb):
        with self._lock:
            self._subs.append(cb)

    def unsubscribe(self, cb):
        with self._lock:
            if cb in self._subs:
                self._subs.remove(cb)

    def _notify(self):
        with self._lock:
            subs = list(self._subs)
        for cb in subs:
            try:
                cb()
            except Exception:
                pass


LOG = Log()


def line(item):
    """« 14:03:22  ✔ texte » pour l'affichage et l'export."""
    return "%s  %s %s" % (time.strftime("%H:%M:%S", time.localtime(item["ts"])), ICONS.get(item["level"], "•"), item["text"])


def count_text(n, one, many):
    """« 1 message » / « 3 messages » — one et many contiennent %d."""
    return (one if n == 1 else many) % n


def sync_summary(who, new, gone, changed):
    """Résultat d'une relève d'une boîte, en une phrase."""
    parts = []
    if new:
        parts.append(count_text(new, tr("%d nouveau message"), tr("%d nouveaux messages")))
    if gone:
        parts.append(count_text(gone, tr("%d retiré du serveur"), tr("%d retirés du serveur")))
    if changed:
        parts.append(count_text(changed, tr("%d état modifié"), tr("%d états modifiés")))
    return "%s : %s" % (who, ", ".join(parts) if parts else tr("rien de nouveau"))
