"""Événements de messagerie entre vos machines (sans Qt) : lu / non lu, favori, épingle, déplacement. Chaque machine qui agit prévient les autres
tout de suite (réseau local, canal chiffré de la synchro) au lieu d'attendre que le serveur de courrier le leur apprenne. Le serveur reste la référence :
le receveur ne change que son cache local, la machine d'origine a déjà envoyé l'action au serveur."""
import threading
import time
from typing import Dict, Iterable, List, Optional, Tuple

FLAGS = {"read": ("unread", False), "unread": ("unread", True), "star": ("starred", True), "unstar": ("starred", False),
         "pin": ("pinned", True), "unpin": ("pinned", False)}
PRIO = {"prio_high": 1, "prio_normal": 0, "prio_low": -1}          # priorité choisie par vous
KINDS = set(FLAGS) | set(PRIO) | {"move", "delete"}
MAX_EVENTS = 500            # par envoi
MAX_AGE = 3600              # un événement vieux d'une heure n'est plus appliqué (le serveur a déjà tranché)


def _clean(s, limit) -> str:
    s = s if isinstance(s, str) else ""
    return "".join(ch for ch in s if ch >= " ")[:limit]


def make(kind, msg, account_email, dest="", ts=None) -> Optional[Dict]:
    """Événement pour `msg` (None si le message n'a pas de Message-ID : impossible à retrouver ailleurs)."""
    mid = getattr(msg, "message_id", "") or ""
    if kind not in KINDS or not mid or not account_email or (kind == "move" and not dest):
        return None
    ev = {"k": kind, "mid": mid, "acct": account_email.lower(), "ts": float(ts if ts is not None else time.time())}
    if kind == "move":
        ev["to"] = dest
    return ev


def sanitize(events, now=None) -> List[Dict]:
    """Garde seulement les événements bien formés, récents, d'un type connu (le canal est chiffré et authentifié, mais on ne fait confiance à rien)."""
    now = now if now is not None else time.time()
    out = []
    for ev in (events if isinstance(events, list) else [])[:MAX_EVENTS]:
        if not isinstance(ev, dict) or ev.get("k") not in KINDS:
            continue
        mid, acct, ts = _clean(ev.get("mid"), 998), _clean(ev.get("acct"), 320).lower(), ev.get("ts")
        if not mid or "@" not in acct or not isinstance(ts, (int, float)) or isinstance(ts, bool) or now - ts > MAX_AGE or ts > now + 300:
            continue
        clean = {"k": ev["k"], "mid": mid, "acct": acct, "ts": float(ts)}
        if ev["k"] == "move":
            dest = _clean(ev.get("to"), 200)
            if not dest:
                continue
            clean["to"] = dest
        out.append(clean)
    return out


def newest_per_message(events: Iterable[Dict]) -> List[Dict]:
    """Le dernier événement de chaque famille (indicateur / déplacement) pour chaque message : c'est celui qui compte."""
    last: Dict[Tuple, Dict] = {}
    for ev in sorted(events, key=lambda e: e["ts"]):
        family = FLAGS[ev["k"]][0] if ev["k"] in FLAGS else "prio" if ev["k"] in PRIO else "move"          # « delete » et « move » : même famille (le dernier gagne)
        last[(ev["acct"], ev["mid"], family)] = ev
    return list(last.values())


def as_change(ev) -> Tuple[str, object]:
    """(« flag », (champ, valeur)) ou (« move », destination)."""
    if ev["k"] == "move":
        return "move", ev["to"]
    if ev["k"] == "delete":
        return "delete", None
    if ev["k"] in PRIO:
        return "prio", PRIO[ev["k"]]
    return "flag", FLAGS[ev["k"]]


class Queue:
    """File d'envoi : regroupe les événements rapprochés (une rafale = un seul envoi), sans bloquer l'interface."""

    def __init__(self, deliver, delay=0.15):
        self.deliver, self.delay = deliver, delay
        self._items: List[Dict] = []
        self._lock = threading.Lock()
        self._timer: Optional[threading.Timer] = None

    def push(self, events):
        events = [e for e in events if e]
        if not events:
            return
        with self._lock:
            self._items += events
            if self._timer is None:
                self._timer = threading.Timer(self.delay, self._flush)
                self._timer.daemon = True
                self._timer.start()

    def _flush(self):
        with self._lock:
            items, self._items, self._timer = self._items, [], None
        for i in range(0, len(items), MAX_EVENTS):
            try:
                self.deliver(items[i:i + MAX_EVENTS])
            except Exception:
                pass
