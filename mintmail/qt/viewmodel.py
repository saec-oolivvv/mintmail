"""Logique de l'interface Qt SANS Qt : vues, lignes de liste, HTML du lecteur, synchronisation, lecture d'un message.
S'appuie uniquement sur le moteur (store, backend, offline, htmlsafe, util) : testable partout."""
import time
from typing import Dict, List, Tuple

from ..backend import make_backend
from ..htmlsafe import reader_csp, sanitize
from ..i18n import tr
from ..offline import OfflineMixin
from ..util import format_time, text_to_html

DEMO_ACCOUNT = {"id": "demo", "name": "Démo", "email": "demo@mintmail.local", "demo": True,
                "signature_html": "<i>Envoyé avec MintMail</i>"}

# (clé de vue du cache, libellé) — mêmes libellés que l'interface GTK, donc déjà traduits
VIEWS: List[Tuple[str, str]] = [
    ("inbox", tr("Boîte de réception")), ("unread", tr("Non lus")), ("starred", tr("Favoris")),
    ("pinned", tr("Épinglés")), ("snoozed", tr("Reportés")), ("drafts", tr("Brouillons")),
    ("sent", tr("Envoyés")), ("archive", tr("Archives")), ("spam", "Spam"), ("trash", tr("Corbeille")),
]
COUNTED = {"inbox", "unread", "drafts", "snoozed"}          # vues qui affichent un compteur (Cache.counts)


def accounts_of(config) -> List[dict]:
    return config["accounts"] or [DEMO_ACCOUNT]


def row_info(m) -> Dict:
    """Ce que la liste affiche pour un message (version allégée suffisante)."""
    return {"id": m.id, "sender": m.display_sender, "subject": m.subject or "", "snippet": (m.snippet or "").replace("\n", " "),
            "time": format_time(m.date) if m.date else "", "unread": bool(m.unread), "starred": bool(m.starred),
            "pinned": bool(m.pinned), "attachments": bool(m.attachments)}


def list_view(cache, view="inbox", account="all", search="", limit=400):
    """Messages d'une vue (cache.query), du plus récent au plus ancien."""
    return cache.query(view=view, account=account, search=search, limit=limit)


def counts(cache, account="all") -> Dict[str, int]:
    c = cache.counts(account)
    return {k: c.get(k, 0) for k in COUNTED}


def render_html(msg, load_images=False, dark=False) -> str:
    """Page affichée par le lecteur : HTML assaini (liste blanche) + CSP stricte ; texte brut converti sinon. Même règles que le lecteur GTK."""
    if msg.html:
        body = sanitize(msg.html, keep_style=True, allow_remote_images=load_images)
        return ('<html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="' + reader_csp(load_images) + '">'
                '<meta name="viewport" content="width=device-width">'
                '<style>html{background:#fff;color:#111}body{margin:0;padding:18px 22px;'
                'font-family:system-ui,Arial,sans-serif;font-size:14px;word-wrap:break-word}'
                'img{max-width:100%%;height:auto}table{max-width:100%%;}pre{white-space:pre-wrap}'
                'blockquote{border-left:3px solid #ccc;margin-left:0;padding-left:12px;color:#555}'
                '</style></head><body>%s</body></html>' % body)
    bg, fg = ("#1f2229", "#e8eaed") if dark else ("#ffffff", "#1f2328")
    return ('<html><head><meta charset="utf-8"><style>html{background:%s;color:%s}body{margin:0;padding:18px 22px;'
            'font-family:system-ui,Arial,sans-serif;font-size:14px;line-height:1.6}a{color:#3b82f6}</style></head><body>%s</body></html>'
            % (bg, fg, text_to_html(msg.text or "")))


def header_lines(msg) -> Dict[str, str]:
    return {"from": "%s <%s>" % (msg.sender_name, msg.sender_email) if msg.sender_name else msg.sender_email,
            "to": msg.to, "subject": msg.subject, "date": time.strftime("%d/%m/%Y %H:%M", time.localtime(msg.date)) if msg.date else ""}


SPECIAL = {"INBOX": "inbox", "Drafts": "drafts", "Sent": "sent", "Archive": "archive", "Spam": "spam", "Trash": "trash"}
LOGICAL = {"inbox", "sent", "drafts", "archive", "spam", "trash"}


def dest_of(entry) -> str:
    """Identifiant de destination d'un dossier : nom logique (sent, trash…) ou « f:<nom réel> » — identique à l'interface GTK."""
    return entry["special"] if entry.get("special") in LOGICAL else "f:" + entry["name"]


class Engine(OfflineMixin):
    """Moteur sans interface : comptes, serveurs, actions en file, synchronisation. Une instance par fenêtre."""

    def __init__(self, config, cache):
        self.config, self.cache = config, cache
        self._backends: Dict[str, object] = {}

    def accounts(self):
        return accounts_of(self.config)

    def backend(self, aid):
        if aid not in self._backends:
            acc = next((a for a in self.accounts() if a["id"] == aid), None)
            if acc is None:
                raise RuntimeError("compte introuvable")
            self._backends[aid] = make_backend(acc, self.config)
        return self._backends[aid]

    # -- lecture
    def open_message(self, mid):
        """Message complet ; s'il était non lu : marqué lu ici et sur le serveur (action en file, rejouée hors ligne si besoin)."""
        m = self.cache.get(mid)
        if m is not None and m.unread:
            self.cache.update(mid, unread=False)
            self.op_enqueue("flags", [m], seen=True)
            m.unread = False
        return m

    def set_unread(self, mid, unread):
        m = self.cache.get(mid)
        if m is not None:
            self.set_flag([m], "unread", unread)

    # -- réseau (à appeler hors du fil de l'interface)
    def flush(self):
        """Rejoue les actions en attente. Retourne (réussies, erreurs, hors_ligne)."""
        return self.op_run(self.cache.ops_pending()) if self.cache.ops_count() else ([], [], False)

    def sync(self, folders=("inbox", "sent"), limit=60):
        """Nouveaux messages, drapeaux et suppressions du serveur. Retourne (nombre de nouveaux messages non lus, erreurs)."""
        fresh, errors = 0, []
        for a in self.accounts():
            try:
                be = self.backend(a["id"])
            except Exception as e:
                errors.append(str(e))
                continue
            for f in folders:
                try:
                    kn = self.cache.uids(a["id"], f)
                    msgs, flags, present, minuid = be.sync(f, kn, limit=limit)
                except Exception as e:
                    errors.append(str(e))
                    continue
                self.cache.upsert_many(msgs)
                self._apply_flags(kn, flags)
                if present is not None:
                    gone = [mid for uid, mid in kn.items() if uid >= minuid and uid not in present]
                    if gone:
                        self.cache.delete_many(gone)
                if kn:
                    fresh += sum(1 for m in msgs if m.unread and m.folder == "inbox")
        return fresh, errors

    def _apply_flags(self, kn, flags):
        """Lu / favori lus sur le serveur. L'épingle n'est pas touchée ici (gérée par l'interface GTK jusqu'à l'étape suivante)."""
        pending = {i for op in self.cache.ops_pending(limit=1000) for it in op["payload"].get("items", []) for i in [it["id"]]}
        ups: Dict[tuple, list] = {}
        for uid, fl in flags.items():
            mid = kn.get(uid)
            if mid and mid not in pending:          # une action locale en attente prime sur l'état du serveur
                ups.setdefault((fl[0], fl[1]), []).append(mid)
        for (unread, starred), ids in ups.items():
            self.cache.update_many(ids, unread=unread, starred=starred)

    # -- dossiers
    def folder_entries(self, aid):
        """Dossiers du compte connus (relevés sur le serveur), sinon les six dossiers de base."""
        ents = (self.config.get("folders") or {}).get(aid)
        return ents or [{"name": n, "label": n, "depth": 0, "special": k, "selectable": True} for n, k in SPECIAL.items()]

    def nav_folders(self):
        """Dossiers de rangement (hors dossiers spéciaux, déjà dans les vues) : [(destination, libellé, profondeur, compte)]."""
        out, many = [], len(self.accounts()) > 1
        for a in self.accounts():
            for e in self.folder_entries(a["id"]):
                if e.get("selectable", True) and e.get("special") not in LOGICAL:
                    label = e.get("label") or e["name"]
                    out.append((dest_of(e), ("%s › %s" % (a.get("name") or a["email"], label)) if many else label, e.get("depth", 0), a["id"]))
        return out

    def move_targets(self, aid):
        """Destinations proposées pour déplacer un message de ce compte : [(destination, libellé)]."""
        return [(dest_of(e), e.get("label") or e["name"]) for e in self.folder_entries(aid) if e.get("selectable", True)]

    def refresh_folders(self):
        """Relit l'arborescence sur le serveur (fond). Retourne True si elle a changé."""
        tree, changed = dict(self.config.get("folders") or {}), False
        for a in self.accounts():
            if a.get("demo"):
                continue
            try:
                ents = self.backend(a["id"]).list_folders()
            except Exception:
                continue
            if ents and ents != tree.get(a["id"]):
                tree[a["id"]], changed = ents, True
        if changed:
            self.config["folders"] = tree
            self.config.save()
        return changed

    # -- actions sur des messages (cache d'abord, serveur ensuite : rien n'est perdu hors ligne)
    def move(self, msgs, dest):
        """Déplace dans le cache tout de suite ; retourne les identifiants d'actions à exécuter (finish_move, en fond)."""
        self.cache.update_many([m.id for m in msgs], folder=dest, snoozed_until=0.0)
        extra = {"notjunk": True} if dest == "inbox" and all(m.folder == "spam" for m in msgs) else {}
        return self.op_enqueue("move", msgs, dest=dest, **extra)

    def finish_move(self, msgs, dest, op_ids):
        """Exécute le déplacement sur le serveur ; si tout va bien, remplace les copies locales par celles du serveur (bon UID, bon dossier).
        Retourne (erreurs, hors_ligne)."""
        _ok, errors, offline = self.op_run([o for o in self.cache.ops_pending() if o["id"] in op_ids])
        if not errors and not offline:
            real = []
            for m in msgs:
                try:
                    if not self.backend(m.account).demo:
                        real.append(m.id)
                except Exception:
                    pass
            if real:
                self.cache.delete_many(real)
                self.sync(folders=("inbox", dest))
        return errors, offline

    def delete_forever(self, msgs):
        self.cache.delete_many([m.id for m in msgs])
        return self.op_enqueue("delete", msgs)

    def run_ops(self, op_ids):
        return self.op_run([o for o in self.cache.ops_pending() if o["id"] in op_ids])

    def set_flag(self, msgs, field, value):
        """field : starred (favori), unread (non lu) ou pinned (épingle, aussi enregistrée sur la boîte). Retourne les actions à exécuter."""
        self.cache.update_many([m.id for m in msgs], **{field: bool(value)})
        if field == "starred":
            return self.op_enqueue("flags", msgs, flagged=bool(value))
        if field == "unread":
            return self.op_enqueue("flags", msgs, seen=not value)
        if field == "pinned":
            return self.op_enqueue("flags", msgs, pinned=bool(value))
        raise ValueError(field)
