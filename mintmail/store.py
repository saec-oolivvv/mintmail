import copy
import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

from .models import Message, Outgoing
from . import sysdeps
from .util import thread_key, normalize_subject

APP = "mintmail"
P2P_MIN_SECRET = 12   # code de jumelage : 12 caractères minimum (les identifiants circulent entre machines)
CONFIG_DIR = sysdeps.config_dir()      # Linux : ~/.config/mintmail (XDG) ; macOS : ~/Library/Application Support/MintMail ; Windows : %APPDATA%\\MintMail
DATA_DIR = sysdeps.data_dir()


def private_dir(p):
    """Dossier réservé à l'utilisateur (0700) : le courrier et les identifiants ne doivent pas être lisibles par les autres comptes."""
    p = Path(p)
    p.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        if (p.stat().st_mode & 0o077):
            os.chmod(p, 0o700)
    except OSError:
        pass
    return p


def write_private(path, data):
    """Écrit un fichier créé directement en 0600 (aucun instant où il serait lisible par d'autres)."""
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data if isinstance(data, bytes) else data.encode("utf-8"))
    os.chmod(path, 0o600)


def harden_permissions():
    """Au démarrage : dossiers 0700 et fichiers 0600 pour tout ce que MintMail stocke (anciennes installations comprises)."""
    changed = 0
    for root in (CONFIG_DIR, DATA_DIR):
        if not root.exists():
            continue
        for dirpath, dirs, files in os.walk(root):
            for name, mode in [(d, 0o700) for d in dirs] + [(f, 0o600) for f in files] + [(".", 0o700)]:
                p = os.path.join(dirpath, name)
                try:
                    if os.path.islink(p):
                        continue
                    if os.stat(p).st_mode & 0o077:
                        os.chmod(p, mode)
                        changed += 1
                except OSError:
                    pass
    return changed

DEFAULTS = {
    "accounts": [], "passwords": {}, "theme": "system", "accent": "#1a73ff",
    "density": "comfortable", "load_images": False, "notifications": True,
    "refresh_minutes": 5, "undo_seconds": 6, "width": 1280, "height": 800,
    "folders": {}, "collapsed_folders": [], "style": "aurora", "design_v2": False,
    "ui_lang": "auto", "update_check": True, "update_repo": "saec-oolivvv/mintmail", "update_last_check": 0, "update_etag": "", "update_seen": "", "update_available": None, "update_snooze_until": 0, "update_snooze_version": "", "update_last_result": "", "open_today_on_start": False, "pins_pushed": [], "threads": True, "tasks": [], "ai_prepare_drafts": False, "gcal": {}, "ai_provider": "nvidia", "oauth_clients": {}, "caldav": {}, "identities": [], "contacts": {},
    "last_view": "inbox", "layout": "columns", "pos_cols": 420, "pos_bottom": 300,
    "side_width": 230, "zoom": 1.0,
    "swipe": {"right": "archive", "right_long": "trash", "left": "snooze", "left_long": "read"},
    "swipe_invert": False,
    "blocked": [], "spam_senders": [], "image_senders": [], "rules": [], "saved_searches": [], "followups": [],
    "templates": [
        {"name": "Accusé de réception", "html": "<p>Bonjour,</p><p>Merci pour votre message, je reviens vers vous rapidement.</p><p>Cordialement,</p>"},
        {"name": "Proposition de rendez-vous", "html": "<p>Bonjour,</p><p>Seriez-vous disponible cette semaine pour un court échange (20 minutes) ? Je vous propose mardi ou jeudi en fin de matinée.</p><p>Bien cordialement,</p>"},
        {"name": "Relance aimable", "html": "<p>Bonjour,</p><p>Je me permets de revenir vers vous au sujet de mon précédent message. Avez-vous eu l'occasion d'y jeter un œil ?</p><p>Merci d'avance,</p>"},
    ],
    # Synchronisation P2P (désactivée par défaut ; exige un code de jumelage commun)
    "p2p_enabled": False, "p2p_node_id": None, "p2p_secret": "", "p2p_port": 54322, "sync_meta": {},
    "p2p_disc_port": 54321, "p2p_static_peers": [],
    # Assistance IA (désactivée par défaut ; la clé est stockée dans le trousseau, pas dans ce fichier)
    "ai_enabled": False, "nvidia_api_base": "", "ai_model": "", "ai_auto": True, "ai_triage": True,
    "ai_digest": True, "ai_privacy": "full", "ai_lang": "fr", "ai_tone": "neutral",
}


class Config:
    def __init__(self, path=None):
        self.path = Path(path) if path else CONFIG_DIR / "config.json"
        self.data = copy.deepcopy(DEFAULTS)
        self._pw = {}
        self._save_lock = threading.Lock()
        self.sync_lock = threading.RLock()   # protège les métadonnées de synchro (moteur P2P / interface)
        self._pw_miss = {}
        self.p2p_notice = ""
        self.load()

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                self.data.update(json.load(f))
        except (OSError, ValueError):
            pass
        if self.data.get("p2p_enabled") and len(str(self.data.get("p2p_secret") or "")) < P2P_MIN_SECRET:
            self.data["p2p_enabled"] = False   # jamais de synchro ouverte sans code de jumelage
            self.p2p_notice = "short_code"
        if not self.data.get("design_v2"):   # refonte 1.5 : nouvelle identité visuelle par défaut, une seule fois
            self.data.update(style="aurora", theme="dark", accent="#7c8cff", design_v2=True)
        if self.data.get("accent") == "#3b82f6":   # ancien bleu par défaut
            self.data["accent"] = DEFAULTS["accent"]

    def save(self):
        with self._save_lock:   # plusieurs threads (UI, synchro P2P) peuvent enregistrer
            private_dir(self.path.parent)
            tmp = str(self.path) + ".tmp"
            write_private(tmp, json.dumps(self.data, indent=2, ensure_ascii=False))      # 0600 dès la création (mots de passe en repli)
            os.replace(tmp, self.path)

    def __getitem__(self, k):
        return self.data[k]

    def __setitem__(self, k, v):
        self.data[k] = v

    def get(self, k, d=None):
        return self.data.get(k, d)

    # -- mots de passe : trousseau système si disponible (jamais bloquant), sinon fichier 0600
    def password(self, account_id):
        if account_id in self._pw:
            return self._pw[account_id]
        if time.time() - self._pw_miss.get(account_id, 0) < 30:   # échec récent : ne pas solliciter le trousseau en boucle
            return self.data.get("passwords", {}).get(account_id, "")
        pw = _keyring("get_password", APP, account_id) or self.data.get("passwords", {}).get(account_id, "")
        if pw:
            self._pw[account_id] = pw
        elif not keyring_pending("get_password", APP, account_id):          # réponse du trousseau encore attendue : pas un échec, on la rejoindra
            self._pw_miss[account_id] = time.time()
        return pw or ""

    def preload_passwords(self):
        for a in self.data.get("accounts", []):
            self.password(a["id"])
        if self.data.get("ai_has_key"):
            self.password("ai:nvidia")

    def ai_key(self):
        """Clé API IA : trousseau, sinon ancienne clé en clair (migrée au premier enregistrement)."""
        return self.password("ai:nvidia") or self.data.get("nvidia_api_key", "")

    def delete_password(self, account_id):
        self._pw.pop(account_id, None)
        _keyring("delete_password", APP, account_id)
        self.data.get("passwords", {}).pop(account_id, None)

    def reset(self, keys):
        for k in keys:
            self.data[k] = copy.deepcopy(DEFAULTS[k])

    def set_password(self, account_id, pw):
        self._pw[account_id] = pw
        if _keyring("set_password", APP, account_id, pw):
            self.data.get("passwords", {}).pop(account_id, None)
        else:
            self.data.setdefault("passwords", {})[account_id] = pw


MAC_SERVICE = "MintMail"       # service du trousseau macOS : DISTINCT de l'ancien « mintmail » (python-keyring), dont l'autorisation est liée à un autre programme


def _q(x: str) -> str:
    return '"' + str(x).replace("\\", "\\\\").replace('"', '\\"') + '"'


def mac_keychain(op, *args, run=subprocess.run):
    """Trousseau macOS via l'outil Apple « security » (signature stable) : l'élément est créé avec « -T /usr/bin/security », donc relu SANS fenêtre
    d'autorisation. Avec python-keyring, l'autorisation était liée à l'application elle-même (signature « ad hoc » qui change à chaque construction) :
    fenêtre de mot de passe sans TouchID, qui revenait sans fin. Le mot de passe passe par l'entrée standard, jamais par la ligne de commande."""
    account = str(args[1]) if len(args) > 1 else ""
    try:
        if op == "get_password":
            r = run(["/usr/bin/security", "find-generic-password", "-a", account, "-s", MAC_SERVICE, "-w"], capture_output=True, text=True, timeout=60)
            return r.stdout.rstrip("\n") if r.returncode == 0 and r.stdout.strip() else None
        if op == "set_password":
            pw = str(args[2])
            if "\n" in pw or "\r" in pw or "\0" in pw:
                return False
            cmd = "add-generic-password -U -a %s -s %s -w %s -T /usr/bin/security\n" % (_q(account), _q(MAC_SERVICE), _q(pw))
            r = run(["/usr/bin/security", "-i"], input=cmd, capture_output=True, text=True, timeout=60)
            return r.returncode == 0 and "error" not in (r.stderr or "").lower()
        if op == "delete_password":
            run(["/usr/bin/security", "delete-generic-password", "-a", account, "-s", MAC_SERVICE], capture_output=True, text=True, timeout=60)
            return True
    except Exception:
        return None
    return None


_inflight = {}                 # (op, service, compte) -> (fil, boîte) : un appel au trousseau encore en attente (fenêtre de mot de passe ouverte)
_inflight_lock = threading.Lock()


def _keyring_timeout():
    """Sur Mac, le trousseau ouvre une fenêtre de mot de passe : 4 s ne suffisent pas pour la remplir (l'ancienne attente abandonnait puis redemandait en boucle)."""
    if sys.platform == "darwin" and threading.current_thread() is not threading.main_thread():
        return 180                                        # fil de fond seulement : le fil de l'interface ne gèle jamais plus de 4 s
    return 4


def keyring_pending(op, *args) -> bool:
    """Vrai si un appel identique au trousseau attend encore la réponse de l'utilisateur."""
    with _inflight_lock:
        e = _inflight.get((op,) + tuple(args[:2]))
    return bool(e and e[0].is_alive())


def _keyring(op, *args, timeout=None):
    """Appelle le trousseau dans un thread : un trousseau verrouillé ne gèle plus l'interface.
    Un appel identique encore en attente est REJOINT, jamais relancé (sinon chaque relance rouvre la fenêtre du trousseau)."""
    if os.environ.get("MINTMAIL_NO_KEYRING") == "1":      # tests : ne jamais toucher au trousseau réel de l'utilisateur
        return None
    timeout = _keyring_timeout() if timeout is None else timeout
    key = (op,) + tuple(args[:2])
    with _inflight_lock:
        entry = _inflight.get(key)
        if entry is None:
            box = {}

            def run(box=box):
                try:
                    if sys.platform == "darwin" and os.environ.get("MINTMAIL_MAC_KEYRING_LIB") != "1":
                        box["v"] = mac_keychain(op, *args)
                        box["done"] = True
                        return
                    import keyring
                    if op == "set_password":
                        keyring.set_password(*args)
                        box["v"] = True
                    else:
                        box["v"] = getattr(keyring, op)(*args)
                except Exception:
                    pass
                box["done"] = True
            t = threading.Thread(target=run, daemon=True)
            entry = _inflight[key] = (t, box)
            t.start()
    t, box = entry
    t.join(timeout)
    if t.is_alive():
        return None                                       # l'utilisateur n'a pas encore répondu : l'appel reste en cours et sera rejoint
    with _inflight_lock:
        if _inflight.get(key) is entry:
            del _inflight[key]
    return box.get("v")


def parse_search(q):
    terms, flt = [], {}
    for tok in (q or "").split():
        low = tok.lower()
        if low.startswith("from:") and len(tok) > 5:
            flt["from"] = low[5:]
        elif low == "is:unread":
            flt["unread"] = True
        elif low == "is:starred":
            flt["starred"] = True
        elif low == "has:attachment":
            flt["att"] = True
        else:
            terms.append(low)
    return terms, flt


# Vue « Non lus » : tout sauf ces dossiers (un message rangé par une règle ou à la main ne doit pas passer inaperçu)
UNREAD_EXCLUDED = "('trash','spam','sent','drafts')"

class Cache:
    """Cache SQLite. La liste lit des « méta » légères (sans corps) ; les corps sont chargés à l'ouverture.
    Les indicateurs (dossier, lu, favori…) vivent dans des colonnes : une mise à jour = un UPDATE."""

    COLS = {"folder": "folder", "unread": "unread", "starred": "starred", "pinned": "pinned",
            "snoozed_until": "snoozed", "category": "category"}

    def __init__(self, path=None):
        private_dir(DATA_DIR)
        db_file = Path(str(path or DATA_DIR / "cache.db"))
        if not db_file.exists():
            try:
                fd = os.open(str(db_file), os.O_WRONLY | os.O_CREAT, 0o600)      # base créée en 0600 (tout votre courrier y est)
                os.close(fd)
            except OSError:
                pass
        if not db_file.exists():
            try:
                (DATA_DIR / "demo_seeded").unlink()
            except OSError:
                pass
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(path or DATA_DIR / "cache.db"), check_same_thread=False, timeout=15)   # plusieurs processus (interface, envois différés)
        with self.lock:
            for pragma in ("journal_mode=WAL", "synchronous=NORMAL", "temp_store=MEMORY"):
                try:
                    self.db.execute("PRAGMA " + pragma)
                except sqlite3.DatabaseError:
                    pass
            self.db.execute("""CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY, account TEXT, folder TEXT, uid INTEGER, date REAL,
                unread INTEGER, starred INTEGER, pinned INTEGER, snoozed REAL,
                has_att INTEGER, category TEXT, sender TEXT, search TEXT, data TEXT)""")
            for col in ("meta TEXT", "thread TEXT", "nsubj TEXT"):
                try:
                    self.db.execute("ALTER TABLE messages ADD COLUMN " + col)
                except sqlite3.OperationalError:
                    pass   # colonne déjà présente
            self.db.execute("CREATE INDEX IF NOT EXISTS i_thread ON messages(account, thread)")
            self.db.execute("""CREATE TABLE IF NOT EXISTS ops (
                id INTEGER PRIMARY KEY AUTOINCREMENT, account TEXT, kind TEXT, payload TEXT, ts REAL, tries INTEGER DEFAULT 0)""")
            self.db.execute("""CREATE TABLE IF NOT EXISTS learn (
                account TEXT, sender TEXT, folder TEXT, n INTEGER, ts REAL, PRIMARY KEY (account, sender, folder))""")
            self.db.execute("""CREATE TABLE IF NOT EXISTS contacts (
                email TEXT PRIMARY KEY, name TEXT, phone TEXT, org TEXT, notes TEXT, source TEXT, n INTEGER DEFAULT 0, ts REAL)""")
            self.db.execute("CREATE INDEX IF NOT EXISTS i_msg ON messages(account, folder, date)")
            self.db.execute("CREATE INDEX IF NOT EXISTS i_sender ON messages(sender)")
            self.db.execute("""CREATE TABLE IF NOT EXISTS outbox (
                id TEXT PRIMARY KEY, send_at REAL, data TEXT)""")
            for col in ("claim REAL", "tries INTEGER DEFAULT 0"):
                try:
                    self.db.execute("ALTER TABLE outbox ADD COLUMN " + col)
                except sqlite3.OperationalError:
                    pass
            self.db.execute("""CREATE TABLE IF NOT EXISTS ai (
                msg_id TEXT, kind TEXT, data TEXT, ts REAL, PRIMARY KEY (msg_id, kind))""")
            self.db.commit()

    # ------------------------------------------------------------ conversions
    @staticmethod
    def _meta_of(m):
        d = m.to_dict()
        d["text"], d["html"] = "", ""
        return json.dumps(d, ensure_ascii=False)

    @staticmethod
    def _build(blob, folder, unread, starred, pinned, snoozed, category, light):
        m = Message.from_dict(json.loads(blob))
        m.folder, m.unread, m.starred, m.pinned = folder, bool(unread), bool(starred), bool(pinned)
        m.snoozed_until, m.category = snoozed or 0.0, category or m.category
        if light:
            m.text, m.html, m.light = "", "", True
        return m

    # ---------------------------------------------------------------- messages
    def upsert(self, m, commit=True):
        if getattr(m, "light", False):
            raise ValueError("message allégé : utiliser update()")
        sender = ("%s %s" % (m.sender_name, m.sender_email)).lower()
        search = ("%s %s %s %s" % (m.subject, sender, m.to, m.text[:4000])).lower()
        thread = m.thread_id or thread_key(m.message_id, m.references, m.subject)
        nsubj = normalize_subject(m.subject).lower()[:120]
        with self.lock:
            if thread.startswith("s:"):   # sans en-têtes de fil : rattaché à une conversation de même objet déjà connue
                r = self.db.execute("SELECT thread FROM messages WHERE account=? AND nsubj=? AND thread IS NOT NULL LIMIT 1",
                                    (m.account, nsubj)).fetchone()
                thread = r[0] if r else thread
            m.thread_id = thread
            self.db.execute(
                "INSERT OR REPLACE INTO messages (id,account,folder,uid,date,unread,starred,pinned,snoozed,"
                "has_att,category,sender,search,data,meta,thread,nsubj) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (m.id, m.account, m.folder, m.uid, m.date, int(m.unread), int(m.starred),
                 int(m.pinned), m.snoozed_until, int(bool(m.attachments)), m.category,
                 sender, search, json.dumps(m.to_dict(), ensure_ascii=False), self._meta_of(m), thread, nsubj))
            if commit:
                self.db.commit()

    def upsert_many(self, msgs):
        for m in msgs:
            self.upsert(m, commit=False)
        with self.lock:
            self.db.commit()

    _SEL = ("SELECT %s, folder, unread, starred, pinned, snoozed, category, %s FROM messages ")

    def get(self, mid):
        """Message complet (avec corps)."""
        with self.lock:
            r = self.db.execute(self._SEL % ("data", "0") + "WHERE id=?", (mid,)).fetchone()
        return self._build(*r[:7], light=False) if r else None

    def get_light(self, mid):
        with self.lock:
            r = self.db.execute(self._SEL % ("COALESCE(meta,data)", "1") + "WHERE id=?", (mid,)).fetchone()
        return self._build(*r[:7], light=True) if r else None

    def pinned_messages(self, account=None):
        """Messages épinglés (légers) d'un compte ou de tous : sert à envoyer vers la boîte les épingles faites avant la 1.13.2."""
        sql = self._SEL % ("COALESCE(meta,data)", "1") + "WHERE pinned=1 AND uid>0" + (" AND account=?" if account else "")
        with self.lock:
            rows = self.db.execute(sql, (account,) if account else ()).fetchall()
        return [self._build(*r[:7], light=True) for r in rows]

    def update(self, mid, **fields):
        self.update_many([mid], **fields)

    def update_many(self, ids, **fields):
        """Met à jour des colonnes (folder, unread, starred, pinned, snoozed_until, category) en une transaction."""
        ids = list(ids)
        sets = [(self.COLS[k], int(v) if isinstance(v, bool) else v) for k, v in fields.items() if k in self.COLS]
        if not ids or not sets:
            return
        clause = ", ".join("%s=?" % c for c, _ in sets)
        with self.lock:
            for i in range(0, len(ids), 500):
                chunk = ids[i:i + 500]
                self.db.execute("UPDATE messages SET %s WHERE id IN (%s)" % (clause, ",".join("?" * len(chunk))),
                                [v for _, v in sets] + chunk)
            self.db.commit()

    def backfill_meta(self):
        """Complète les méta et la clé de conversation des anciennes lignes (thread de fond au démarrage)."""
        while True:
            with self.lock:
                rows = self.db.execute("SELECT id, data FROM messages WHERE meta IS NULL OR thread IS NULL LIMIT 200").fetchall()
                if not rows:
                    return
                for mid, blob in rows:
                    try:
                        d = json.loads(blob)
                        th = d.get("thread_id") or thread_key(d.get("message_id", ""), d.get("references", ""), d.get("subject", ""))
                        d["thread_id"] = th
                        full = json.dumps(d, ensure_ascii=False)
                        d["text"], d["html"] = "", ""
                        meta = json.dumps(d, ensure_ascii=False)
                        ns = normalize_subject(d.get("subject", "")).lower()[:120]
                    except ValueError:
                        meta, full, th, ns = "{}", blob, mid, ""
                    self.db.execute("UPDATE messages SET meta=?, data=?, thread=?, nsubj=? WHERE id=?", (meta, full, th, ns, mid))
                self.db.commit()

    def clear_all(self):
        with self.lock:
            self.db.execute("DELETE FROM messages")
            self.db.commit()

    def delete(self, mid):
        self.delete_many([mid])

    def delete_many(self, ids):
        ids = list(ids)
        with self.lock:
            for i in range(0, len(ids), 500):
                chunk = ids[i:i + 500]
                self.db.execute("DELETE FROM messages WHERE id IN (%s)" % ",".join("?" * len(chunk)), chunk)
            self.db.commit()

    def delete_folder(self, account, folder):
        with self.lock:
            self.db.execute("DELETE FROM messages WHERE account=? AND folder=?", (account, folder))
            self.db.commit()

    def delete_account(self, account):
        with self.lock:
            self.db.execute("DELETE FROM messages WHERE account=?", (account,))
            self.db.commit()

    def folders_with_unread(self):
        """{(compte, dossier)} où le cache connaît au moins un message non lu (à resynchroniser : il a pu être lu ailleurs)."""
        with self.lock:
            return {(a, f) for a, f in self.db.execute("SELECT DISTINCT account, folder FROM messages WHERE unread=1").fetchall()}

    def uids(self, account, folder):
        with self.lock:
            rows = self.db.execute(
                "SELECT uid, id FROM messages WHERE account=? AND folder=? AND uid>0",
                (account, folder)).fetchall()
        return {u: i for u, i in rows}

    def _light_rows(self, sql, args):
        with self.lock:
            rows = self.db.execute(self._SEL % ("COALESCE(meta,data)", "1") + sql, args).fetchall()
        return [self._build(*r[:7], light=True) for r in rows]

    def by_sender(self, key, folders=("inbox", "archive")):
        """Messages d'un expéditeur (adresse complète ou '@domaine'), versions allégées."""
        marks = ",".join("?" * len(folders))
        return self._light_rows("WHERE sender LIKE ? AND folder IN (%s)" % marks,
                                ["%" + key.lower() + "%"] + list(folders))

    def query(self, view="inbox", account="all", category=None, unread_only=False,
              attachments_only=False, search="", limit=400, threads=False):
        now = time.time()
        where, args = [], []
        if account != "all":
            where.append("account=?")
            args.append(account)
        terms, flt = parse_search(search)
        if terms or flt:
            where.append("folder NOT IN ('trash','spam')")
            for t in terms:
                where.append("search LIKE ?")
                args.append("%" + t + "%")
            if "from" in flt:
                where.append("sender LIKE ?")
                args.append("%" + flt["from"] + "%")
            if flt.get("unread"):
                where.append("unread=1")
            if flt.get("starred"):
                where.append("starred=1")
            if flt.get("att"):
                where.append("has_att=1")
        elif view == "inbox":
            where.append("folder='inbox' AND snoozed<=?")
            args.append(now)
        elif view == "unread":
            where.append("unread=1 AND folder NOT IN %s AND snoozed<=?" % UNREAD_EXCLUDED)
            args.append(now)
        elif view == "starred":
            where.append("starred=1 AND folder NOT IN ('trash','spam')")
        elif view == "pinned":
            where.append("pinned=1 AND folder NOT IN ('trash','spam')")
        elif view == "snoozed":
            where.append("snoozed>? AND folder NOT IN ('trash','spam')")
            args.append(now)
        else:
            where.append("folder=?")
            args.append(view)
        if category:
            where.append("category=?")
            args.append(category)
        if unread_only:
            where.append("unread=1")
        if attachments_only:
            where.append("has_att=1")
        if threads:
            return self.query_threads(" AND ".join(where), args, limit)
        return self._light_rows("WHERE " + " AND ".join(where) + " ORDER BY date DESC LIMIT ?", args + [limit])

    def thread_members(self, account, thread, exclude=("trash", "spam")):
        """Messages (allégés) d'une conversation, du plus ancien au plus récent."""
        marks = ",".join("?" * len(exclude))
        msgs = self._light_rows("WHERE account=? AND thread=? AND folder NOT IN (%s) ORDER BY date ASC" % marks,
                                [account, thread] + list(exclude))
        return msgs

    def query_threads(self, where, args, limit):
        """Un message par conversation (le plus récent), avec le nombre de messages et l'état « non lu » du fil."""
        sql = ("SELECT COALESCE(meta,data), folder, unread, starred, pinned, snoozed, category, tcnt, tun FROM ("
               "SELECT *, ROW_NUMBER() OVER (PARTITION BY account, COALESCE(NULLIF(thread,''), id) ORDER BY date DESC) rn,"
               " COUNT(*) OVER (PARTITION BY account, COALESCE(NULLIF(thread,''), id)) tcnt,"
               " SUM(unread) OVER (PARTITION BY account, COALESCE(NULLIF(thread,''), id)) tun FROM messages WHERE " + where +
               ") WHERE rn=1 ORDER BY date DESC LIMIT ?")
        with self.lock:
            rows = self.db.execute(sql, args + [limit]).fetchall()
        out = []
        for r in rows:
            m = self._build(*r[:7], light=True)
            m.thread_count, m.thread_unread = int(r[7] or 1), bool(r[8])
            out.append(m)
        return out

    # ------------------------------------------------ apprentissage (habitudes de rangement)
    def learn_record(self, account, sender, folder):
        sender = (sender or "").lower()
        if not sender or not folder:
            return 0
        with self.lock:
            self.db.execute("INSERT INTO learn (account, sender, folder, n, ts) VALUES (?,?,?,1,?) "
                            "ON CONFLICT(account, sender, folder) DO UPDATE SET n=n+1, ts=excluded.ts",
                            (account, sender, folder, time.time()))
            self.db.commit()
            return self.db.execute("SELECT n FROM learn WHERE account=? AND sender=? AND folder=?",
                                   (account, sender, folder)).fetchone()[0]

    def learn_best(self, account, sender, min_count=2):
        """Dossier où l'utilisateur range habituellement les messages de cet expéditeur (ou de son domaine)."""
        sender = (sender or "").lower()
        with self.lock:
            for key in (sender, "@" + sender.split("@")[-1]):
                r = self.db.execute("SELECT folder, n FROM learn WHERE account=? AND sender=? ORDER BY n DESC, ts DESC LIMIT 1",
                                    (account, key)).fetchone()
                if r and r[1] >= min_count:
                    return r[0]
        return None

    def learn_examples(self, account, limit=12):
        with self.lock:
            return self.db.execute("SELECT sender, folder FROM learn WHERE account=? AND n>=2 ORDER BY n DESC, ts DESC LIMIT ?",
                                   (account, limit)).fetchall()

    def learn_clear(self):
        with self.lock:
            self.db.execute("DELETE FROM learn")
            self.db.commit()

    # ------------------------------------------------ actions serveur en attente (mode hors ligne)
    def ops_add(self, account, kind, payload):
        with self.lock:
            cur = self.db.execute("INSERT INTO ops (account, kind, payload, ts) VALUES (?,?,?,?)",
                                  (account, kind, json.dumps(payload, ensure_ascii=False), time.time()))
            self.db.commit()
            return cur.lastrowid

    def ops_pending(self, limit=200):
        with self.lock:
            rows = self.db.execute("SELECT id, account, kind, payload, tries FROM ops ORDER BY id LIMIT ?", (limit,)).fetchall()
        return [{"id": i, "account": a, "kind": k, "payload": json.loads(p), "tries": t} for i, a, k, p, t in rows]

    def ops_done(self, op_id):
        with self.lock:
            self.db.execute("DELETE FROM ops WHERE id=?", (op_id,))
            self.db.commit()

    def ops_fail(self, op_id):
        with self.lock:
            self.db.execute("UPDATE ops SET tries=tries+1 WHERE id=?", (op_id,))
            self.db.commit()

    def ops_count(self):
        with self.lock:
            return self.db.execute("SELECT COUNT(*) FROM ops").fetchone()[0]

    # ------------------------------------------------------------------- contacts
    def contact_upsert(self, email, name="", phone="", org="", notes="", source="auto", bump=0):
        email = (email or "").strip().lower()
        if not email:
            return
        with self.lock:
            old = self.db.execute("SELECT name, phone, org, notes, source, n FROM contacts WHERE email=?", (email,)).fetchone()
            if old is None:
                self.db.execute("INSERT INTO contacts (email, name, phone, org, notes, source, n, ts) VALUES (?,?,?,?,?,?,?,?)",
                                (email, name, phone, org, notes, source, bump, time.time()))
            elif source == "manual":     # une saisie manuelle l'emporte et verrouille la fiche
                self.db.execute("UPDATE contacts SET name=?, phone=?, org=?, notes=?, source='manual', ts=? WHERE email=?",
                                (name, phone, org, notes, time.time(), email))
            else:
                self.db.execute("UPDATE contacts SET name=?, n=n+?, ts=? WHERE email=?",
                                (old[0] or name, bump, time.time(), email))
            self.db.commit()

    def contact_delete(self, email):
        with self.lock:
            self.db.execute("DELETE FROM contacts WHERE email=?", (email.lower(),))
            self.db.commit()

    def contacts_list(self, query="", source=None, limit=500):
        q, args = "SELECT email, name, phone, org, notes, source, n FROM contacts WHERE 1=1", []
        if query:
            q += " AND (email LIKE ? OR LOWER(name) LIKE ? OR LOWER(org) LIKE ?)"
            args += ["%" + query.lower() + "%"] * 3
        if source:
            q += " AND source=?"
            args.append(source)
        q += " ORDER BY (source='manual') DESC, n DESC, name LIMIT ?"
        with self.lock:
            rows = self.db.execute(q, args + [limit]).fetchall()
        return [dict(zip(("email", "name", "phone", "org", "notes", "source", "n"), r)) for r in rows]

    def contacts_rebuild(self, limit=3000):
        """Alimente le carnet avec les expéditeurs / destinataires des messages récents (arrière-plan)."""
        from .contacts import parse_addresses
        with self.lock:
            rows = self.db.execute("SELECT COALESCE(meta,data) FROM messages WHERE folder IN ('inbox','sent','archive') "
                                   "ORDER BY date DESC LIMIT ?", (limit,)).fetchall()
        counts = {}
        for (blob,) in rows:
            try:
                d = json.loads(blob)
            except ValueError:
                continue
            for hdr in ((d.get("sender_name", "") + " <" + d.get("sender_email", "") + ">"), d.get("to", ""), d.get("cc", "")):
                for name, addr in parse_addresses(hdr):
                    n, c = counts.get(addr, ("", 0))
                    counts[addr] = (n or name, c + 1)
        with self.lock:
            for addr, (name, c) in counts.items():
                old = self.db.execute("SELECT source FROM contacts WHERE email=?", (addr,)).fetchone()
                if old is None:
                    self.db.execute("INSERT INTO contacts (email, name, source, n, ts) VALUES (?,?,?,?,?)", (addr, name, "auto", c, time.time()))
                elif old[0] == "auto":
                    self.db.execute("UPDATE contacts SET n=?, name=COALESCE(NULLIF(name,''), ?) WHERE email=?", (c, name, addr))
            self.db.commit()
        return len(counts)

    def counts(self, account="all"):
        acc = "" if account == "all" else " AND account=?"
        a = [] if account == "all" else [account]
        now = time.time()
        with self.lock:
            q = lambda s, x: self.db.execute(s, x).fetchone()[0]
            return {
                "inbox": q("SELECT COUNT(*) FROM messages WHERE folder='inbox' AND unread=1 AND snoozed<=?" + acc, [now] + a),
                "unread": q("SELECT COUNT(*) FROM messages WHERE unread=1 AND folder NOT IN %s AND snoozed<=?%s" % (UNREAD_EXCLUDED, acc), [now] + a),
                "drafts": q("SELECT COUNT(*) FROM messages WHERE folder='drafts'" + acc, a),
                "snoozed": q("SELECT COUNT(*) FROM messages WHERE snoozed>?" + acc, [now] + a),
            }

    def wake_snoozed(self):
        now = time.time()
        with self.lock:
            ids = [r[0] for r in self.db.execute(
                "SELECT id FROM messages WHERE snoozed>0 AND snoozed<=?", (now,)).fetchall()]
        if ids:
            self.update_many(ids, snoozed_until=0.0, unread=True)
        return [m for m in (self.get_light(i) for i in ids) if m]

    def contacts(self, limit=300):
        """(nom, adresse) pour l'auto-complétion : carnet d'adresses d'abord, puis expéditeurs récents."""
        found = [(c["name"], c["email"]) for c in self.contacts_list(limit=limit)]
        if len(found) >= 20:
            return found
        with self.lock:
            rows = self.db.execute(
                "SELECT COALESCE(meta,data) FROM messages WHERE folder IN ('inbox','sent','archive') "
                "ORDER BY date DESC LIMIT 800").fetchall()
        seen, out = set(), []
        for (d,) in rows:
            m = json.loads(d)
            e = m.get("sender_email")
            if e and e not in seen:
                seen.add(e)
                out.append((m.get("sender_name") or "", e))
            if len(out) >= limit:
                break
        known = {e for _n, e in found}
        return found + [x for x in out if x[1] not in known]

    # ------------------------------------------------------------------ IA (cache)
    def ai_get(self, msg_id, kind):
        with self.lock:
            r = self.db.execute("SELECT data FROM ai WHERE msg_id=? AND kind=?", (msg_id, kind)).fetchone()
        try:
            return json.loads(r[0]) if r else None
        except ValueError:
            return None

    def ai_set(self, msg_id, kind, obj):
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO ai (msg_id, kind, data, ts) VALUES (?,?,?,?)",
                            (msg_id, kind, json.dumps(obj, ensure_ascii=False), time.time()))
            self.db.commit()

    def ai_meta(self, ids):
        """{id: {summary, priority, spam}} pour l'affichage de la liste."""
        ids = list(ids)
        out = {}
        with self.lock:
            for i in range(0, len(ids), 500):
                chunk = ids[i:i + 500]
                for mid, blob in self.db.execute(
                        "SELECT msg_id, data FROM ai WHERE kind='triage' AND msg_id IN (%s)" % ",".join("?" * len(chunk)),
                        chunk).fetchall():
                    try:
                        out[mid] = json.loads(blob)
                    except ValueError:
                        pass
        return out

    def ai_clear(self):
        with self.lock:
            self.db.execute("DELETE FROM ai")
            self.db.commit()

    def ai_count(self):
        with self.lock:
            return self.db.execute("SELECT COUNT(*) FROM ai").fetchone()[0]

    # -- boîte d'envoi (envoi différé / annulable)
    def outbox_add(self, oid, send_at, out):
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO outbox (id, send_at, data) VALUES (?,?,?)",
                            (oid, send_at, json.dumps(out.to_dict(), ensure_ascii=False)))
            self.db.commit()

    def outbox_due(self):
        with self.lock:
            rows = self.db.execute("SELECT id, data FROM outbox WHERE send_at<=?",
                                   (time.time(),)).fetchall()
        return [(i, Outgoing.from_dict(json.loads(d))) for i, d in rows]

    def outbox_claim(self, oid, ttl=180):
        """Réserve un envoi (atomique entre processus) : évite qu'il parte deux fois (interface + minuterie)."""
        now = time.time()
        with self.lock:
            cur = self.db.execute("UPDATE outbox SET claim=? WHERE id=? AND (claim IS NULL OR claim<?)", (now + ttl, oid, now))
            self.db.commit()
            return cur.rowcount == 1

    def outbox_reschedule(self, oid, at):
        with self.lock:
            self.db.execute("UPDATE outbox SET send_at=?, claim=NULL, tries=COALESCE(tries,0)+1 WHERE id=?", (at, oid))
            self.db.commit()

    def outbox_tries(self, oid):
        with self.lock:
            r = self.db.execute("SELECT COALESCE(tries,0) FROM outbox WHERE id=?", (oid,)).fetchone()
        return r[0] if r else 0

    def outbox_list(self):
        with self.lock:
            rows = self.db.execute("SELECT id, send_at, data, COALESCE(tries,0) FROM outbox ORDER BY send_at").fetchall()
        return [(i, t, Outgoing.from_dict(json.loads(d)), n) for i, t, d, n in rows]

    def outbox_remove(self, oid):
        with self.lock:
            self.db.execute("DELETE FROM outbox WHERE id=?", (oid,))
            self.db.commit()

    def outbox_count(self):
        with self.lock:
            return self.db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0]
