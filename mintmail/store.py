import copy
import json
import os
import sqlite3
import threading
import time
from pathlib import Path

from .models import Message, Outgoing

APP = "mintmail"
P2P_MIN_SECRET = 12   # code de jumelage : 12 caractères minimum (les identifiants circulent entre machines)
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / APP
DATA_DIR = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / APP

DEFAULTS = {
    "accounts": [], "passwords": {}, "theme": "system", "accent": "#1a73ff",
    "density": "comfortable", "load_images": False, "notifications": True,
    "refresh_minutes": 5, "undo_seconds": 6, "width": 1280, "height": 800,
    "folders": {}, "collapsed_folders": [], "style": "aurora", "design_v2": False,
    "last_view": "inbox", "layout": "columns", "pos_cols": 420, "pos_bottom": 300,
    "side_width": 230, "zoom": 1.0,
    "swipe": {"right": "archive", "right_long": "trash", "left": "snooze", "left_long": "read"},
    "swipe_invert": False,
    "blocked": [], "spam_senders": [], "rules": [], "saved_searches": [], "followups": [],
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
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = str(self.path) + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
            os.chmod(tmp, 0o600)
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
        else:
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


def _keyring(op, *args, timeout=4):
    """Appelle le trousseau dans un thread : un trousseau verrouillé ne gèle plus l'interface."""
    box = {}

    def run():
        try:
            import keyring
            if op == "set_password":
                keyring.set_password(*args)
                box["v"] = True
            else:
                box["v"] = getattr(keyring, op)(*args)
        except Exception:
            pass
    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(timeout)
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


class Cache:
    """Cache SQLite. La liste lit des « méta » légères (sans corps) ; les corps sont chargés à l'ouverture.
    Les indicateurs (dossier, lu, favori…) vivent dans des colonnes : une mise à jour = un UPDATE."""

    COLS = {"folder": "folder", "unread": "unread", "starred": "starred", "pinned": "pinned",
            "snoozed_until": "snoozed", "category": "category"}

    def __init__(self, path=None):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if not Path(str(path or DATA_DIR / "cache.db")).exists():
            try:
                (DATA_DIR / "demo_seeded").unlink()
            except OSError:
                pass
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(path or DATA_DIR / "cache.db"), check_same_thread=False)
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
            try:
                self.db.execute("ALTER TABLE messages ADD COLUMN meta TEXT")
            except sqlite3.OperationalError:
                pass   # colonne déjà présente
            self.db.execute("CREATE INDEX IF NOT EXISTS i_msg ON messages(account, folder, date)")
            self.db.execute("CREATE INDEX IF NOT EXISTS i_sender ON messages(sender)")
            self.db.execute("""CREATE TABLE IF NOT EXISTS outbox (
                id TEXT PRIMARY KEY, send_at REAL, data TEXT)""")
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
        with self.lock:
            self.db.execute(
                "INSERT OR REPLACE INTO messages (id,account,folder,uid,date,unread,starred,pinned,snoozed,"
                "has_att,category,sender,search,data,meta) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (m.id, m.account, m.folder, m.uid, m.date, int(m.unread), int(m.starred),
                 int(m.pinned), m.snoozed_until, int(bool(m.attachments)), m.category,
                 sender, search, json.dumps(m.to_dict(), ensure_ascii=False), self._meta_of(m)))
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
        """Complète les méta des anciennes lignes (thread de fond au démarrage)."""
        while True:
            with self.lock:
                rows = self.db.execute("SELECT id, data FROM messages WHERE meta IS NULL LIMIT 200").fetchall()
                if not rows:
                    return
                for mid, blob in rows:
                    try:
                        d = json.loads(blob)
                        d["text"], d["html"] = "", ""
                        meta = json.dumps(d, ensure_ascii=False)
                    except ValueError:
                        meta = "{}"
                    self.db.execute("UPDATE messages SET meta=? WHERE id=?", (meta, mid))
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
              attachments_only=False, search="", limit=400):
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
            where.append("unread=1 AND folder='inbox' AND snoozed<=?")
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
        return self._light_rows("WHERE " + " AND ".join(where) + " ORDER BY date DESC LIMIT ?", args + [limit])

    def counts(self, account="all"):
        acc = "" if account == "all" else " AND account=?"
        a = [] if account == "all" else [account]
        now = time.time()
        with self.lock:
            q = lambda s, x: self.db.execute(s, x).fetchone()[0]
            return {
                "inbox": q("SELECT COUNT(*) FROM messages WHERE folder='inbox' AND unread=1 AND snoozed<=?" + acc, [now] + a),
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
        return out

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
            self.db.execute("INSERT OR REPLACE INTO outbox VALUES (?,?,?)",
                            (oid, send_at, json.dumps(out.to_dict(), ensure_ascii=False)))
            self.db.commit()

    def outbox_due(self):
        with self.lock:
            rows = self.db.execute("SELECT id, data FROM outbox WHERE send_at<=?",
                                   (time.time(),)).fetchall()
        return [(i, Outgoing.from_dict(json.loads(d))) for i, d in rows]

    def outbox_remove(self, oid):
        with self.lock:
            self.db.execute("DELETE FROM outbox WHERE id=?", (oid,))
            self.db.commit()

    def outbox_count(self):
        with self.lock:
            return self.db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0]
