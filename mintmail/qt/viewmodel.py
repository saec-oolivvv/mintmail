"""Logique de l'interface Qt SANS Qt : vues, lignes de liste, HTML du lecteur, synchronisation, lecture d'un message.
S'appuie uniquement sur le moteur (store, backend, offline, htmlsafe, util) : testable partout."""
import sys
import threading
import time
from typing import Dict, List, Tuple

from ..backend import is_retryable, make_backend
from .. import mailevents as ME
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
    info = {"id": m.id, "sender": m.display_sender, "email": m.sender_email or "", "subject": m.subject or "", "snippet": (m.snippet or "").replace("\n", " "),
            "time": format_time(m.date) if m.date else "", "unread": bool(m.unread), "starred": bool(m.starred),
            "pinned": bool(m.pinned), "attachments": bool(m.attachments)}
    n = int(getattr(m, "thread_count", 1) or 1)
    info["count"] = n if n > 1 else 0                                          # messages de la conversation (0 = message seul)
    if n > 1:
        info["unread"] = bool(getattr(m, "thread_unread", m.unread))          # un fil est en gras tant qu'un de ses messages est non lu
    return info


def list_view(cache, view="inbox", account="all", search="", limit=400, threads=False, category=None):
    """Messages d'une vue (cache.query), du plus récent au plus ancien ; threads=True : un message par conversation (le plus récent)."""
    return cache.query(view=view, account=account, search=search, limit=limit, threads=threads, category=category)


def inbox_groups(cache, config, account, key, threads, limit=400, accounts=None):
    """Boîte de réception avec groupes : (messages à afficher, non lus par groupe, groupeur). `key` : None = boîte principale
    (les groupes en mode « grouper » en sortent), 'all' = tout, ou un groupe (pinned, mine, invite, reply, notif, news)."""
    from .. import groups as G
    gr = G.Grouper(config, cache, accounts)
    if key == "all" and not threads:
        raw = cache.query("inbox", account, limit=limit, threads=False)
        shown = raw
    else:
        raw = cache.query("inbox", account, limit=2000, threads=threads)
        shown = G.filter_view(gr, raw, key)[:limit]
    unread = cache.query("inbox", account, unread_only=True, limit=2000, threads=False)
    gr.digest = G.digest(gr, raw) if key is None else {}
    return shown, gr.counts(unread), gr


def grouped(config, view, search="") -> bool:
    """Conversations affichées ? Comme en GTK : réglage « threads », jamais pendant une recherche ni dans Brouillons / Boîte d'envoi."""
    return bool(config.get("threads", True)) and not (search or "").strip() and view not in ("drafts", "outbox")


def expand_threads(cache, msgs, enabled=True):
    """Une action sur une conversation vaut pour tous ses messages du même dossier (le message cliqué reste en premier)."""
    if not (enabled and any(getattr(m, "thread_count", 1) > 1 for m in msgs)):
        return list(msgs)
    out, seen = [], set()
    for m in msgs:
        group = [m]
        if getattr(m, "thread_count", 1) > 1 and getattr(m, "thread_id", ""):
            group += [x for x in cache.thread_members(m.account, m.thread_id) if x.folder == m.folder and x.id != m.id]
        for x in group:
            if x.id not in seen:
                seen.add(x.id)
                out.append(x)
    return out


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


def info_facts(msg, accounts, thread_count=0):
    """Lignes de la colonne « Informations » du lecteur : [(libellé, valeur)] — boîte, dossier, date complète, catégorie, pièces jointes, conversation."""
    from .. import groups as G
    from ..util import format_full, human_size
    acc = next((a for a in accounts if a["id"] == msg.account), None)
    rows = []
    if acc:
        rows.append((tr("Boîte"), acc.get("email") or acc.get("name") or ""))
    folder = dict(VIEWS).get(msg.folder) or msg.folder
    if folder:
        rows.append((tr("Dossier"), folder))
    if msg.date:
        rows.append((tr("Reçu le") if msg.folder != "sent" else tr("Envoyé le"), format_full(msg.date)))
    cat = {"people": tr("Personnes"), "notif": G.label("notif"), "news": G.label("news")}.get(msg.category)
    if cat:
        rows.append((tr("Catégorie"), cat))
    atts = [a for a in msg.attachments or [] if isinstance(a, dict)]
    if atts:
        rows.append((tr("Pièces jointes"), "%d · %s" % (len(atts), human_size(sum(int(a.get("size") or 0) for a in atts)))))
    if thread_count > 1:
        rows.append((tr("Conversation"), tr("%d messages") % thread_count))
    return rows


def recipients_text(msg, accounts) -> Dict[str, str]:
    """Destinataires affichés dans le lecteur : « À », « Cc » et la boîte (adresse du compte) qui a reçu le message."""
    from email.utils import getaddresses
    def fmt(h):
        out = []
        for name, addr in getaddresses([h or ""]):
            if addr:
                out.append("%s <%s>" % (name, addr) if name and name.lower() != addr.lower() else addr)
        return ", ".join(out)
    box = ""
    for a in accounts or []:
        if a.get("id") == msg.account:
            box = a.get("email", "") or ""
    return {"to": fmt(msg.to), "cc": fmt(getattr(msg, "cc", "")), "box": box}


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
        self.folder_unread: Dict[tuple, int] = {}              # (compte, dossier) → non lus annoncés par le serveur
        self.event_sink = None                                  # fonction(liste d'événements) : prévient vos autres machines (réseau local) tout de suite

    def accounts(self):
        return accounts_of(self.config)

    def backend(self, aid):
        if aid not in self._backends:
            acc = next((a for a in self.accounts() if a["id"] == aid), None)
            if acc is None:
                raise RuntimeError("compte introuvable")
            if not acc.get("demo") and acc.get("auth") != "oauth2" and not self.config.password(aid):
                if sys.platform == "darwin":
                    raise RuntimeError(tr("Mot de passe du compte « %s » introuvable : saisissez-le à nouveau dans Paramètres → Comptes.") % (acc.get("email") or aid))
                raise RuntimeError(tr("Mot de passe du compte « %s » introuvable : le trousseau est inaccessible depuis cet environnement (installez « keyring » dans le venv, ou créez-le avec --system-site-packages).") % (acc.get("email") or aid))
            self._backends[aid] = make_backend(acc, self.config)
        return self._backends[aid]

    # -- réception instantanée (IMAP IDLE)
    def start_push(self, on_change):
        """Un fil par compte IMAP : le serveur prévient dès qu'un message arrive (IDLE) et `on_change()` est appelé (depuis ce fil : ne touchez pas à l'interface).
        Sans effet pour les comptes de démonstration ou sans IDLE ; le relevé périodique reste le filet de sécurité."""
        import threading
        self.stop_push()
        self._push_stop = threading.Event()
        self._push_threads = []

        self.push_state = {}

        def run(aid):
            stop = self._push_stop
            state = lambda s: self.push_state.__setitem__(aid, s)
            while not stop.is_set():
                try:
                    be = self.backend(aid)
                    if getattr(be, "demo", False) or not hasattr(be, "watch"):
                        return
                    try:
                        be.watch(lambda: on_change(aid), stop, state)
                    except TypeError:                                # moteur sans suivi d'état (démonstration, tests)
                        be.watch(lambda: on_change(aid), stop)
                except Exception as e:
                    state("erreur : %s" % str(e)[:80])
                stop.wait(30)                                        # mot de passe absent, réseau coupé… : on réessaie plus tard
        for acc in self.accounts():
            if not acc.get("demo"):
                t = threading.Thread(target=run, args=(acc["id"],), daemon=True)
                t.start()
                self._push_threads.append(t)

    def push_summary(self):
        """Texte d'état de la réception instantanée, par compte (info-bulle du bouton de relevé)."""
        names = {a["id"]: a.get("name") or a["email"] for a in self.accounts()}
        st = getattr(self, "push_state", {})
        if not st:
            return tr("Réception instantanée : inactive")
        return tr("Réception instantanée :") + "\n" + "\n".join("%s %s" % ("✔" if v == "ok" else "✖", names.get(k, k) + ("" if v == "ok" else " — " + v)) for k, v in sorted(st.items()))

    def stop_push(self):
        ev = getattr(self, "_push_stop", None)
        if ev is not None:
            ev.set()

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

    def sync(self, folders=("inbox", "sent"), limit=60, only=None):
        """Nouveaux messages, drapeaux et suppressions du serveur. Retourne (nombre de nouveaux messages non lus, erreurs).
        only : identifiants de comptes à relever (relevé rapide déclenché par le serveur) ; None : tous.
        Les comptes sont relevés EN PARALLÈLE : un serveur lent ou en panne ne retarde plus les autres, et `on_progress` (si défini) est appelé dès qu'une boîte
        a reçu du nouveau, pour que l'interface l'affiche sans attendre la fin. Chaque erreur est précédée de l'adresse de la boîte concernée."""
        from concurrent.futures import ThreadPoolExecutor
        accounts = [a for a in self.accounts() if only is None or a["id"] in only]
        pending = self.pending_ids()                  # déjà déplacés / supprimés ICI mais pas encore sur le serveur : ne pas les ramener

        def one(a):
            fresh, errors = 0, []
            who = a.get("email") or a.get("name") or a["id"]
            try:
                be = self.backend(a["id"])
            except Exception as e:
                return 0, ["%s : %s" % (who, e)]
            changed = False
            for f in folders:
                try:
                    kn = self.cache.uids(a["id"], f)
                    msgs, flags, present, minuid = be.sync(f, kn, limit=limit)
                except Exception as e:
                    errors.append("%s : %s" % (who, e))
                    continue
                msgs = [m for m in msgs if m.id not in pending]
                self.cache.upsert_many(msgs)
                self._apply_flags(kn, flags)
                changed = changed or bool(msgs)
                if present is not None:
                    gone = [mid for uid, mid in kn.items() if uid >= minuid and uid not in present]
                    if gone:
                        self.cache.delete_many(gone)
                        changed = True
                if kn:
                    fresh += sum(1 for m in msgs if m.unread and m.folder == "inbox")
            if changed and getattr(self, "on_progress", None):
                try:
                    self.on_progress()
                except Exception:
                    pass
            return fresh, errors

        if not accounts:
            return 0, []
        with ThreadPoolExecutor(max_workers=min(8, len(accounts))) as pool:
            results = list(pool.map(one, accounts))
        return sum(r[0] for r in results), [e for r in results for e in r[1]]

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

    def refresh_folder_counts(self):
        """Non lus de chaque dossier de rangement, relevés sur le serveur (réseau : en fond). Retourne True si un chiffre a changé."""
        changed = False
        for a in self.accounts():
            if a.get("demo"):
                continue
            names = [e["name"] for e in self.folder_entries(a["id"]) if e.get("selectable", True)][:60]
            try:
                status = self.backend(a["id"]).folder_status(names)
            except Exception:
                continue
            for name, (_n, unseen) in status.items():
                if self.folder_unread.get((a["id"], name)) != unseen:
                    self.folder_unread[(a["id"], name)], changed = unseen, True
        return changed

    def live_check(self):
        """Veille légère (STATUS : boîte de réception et envoyés de chaque boîte, toutes en parallèle) : retourne les boîtes dont l'état a changé depuis le dernier
        passage (message arrivé, supprimé, déplacé, lu ailleurs). Complète IDLE (perdu, bloqué par un pare-feu, serveur sans IDLE) : le changement est vu en quelques secondes."""
        from concurrent.futures import ThreadPoolExecutor
        sigs = self.__dict__.setdefault("_live_sigs", {})
        accounts = [a for a in self.accounts() if not a.get("demo")]

        def one(a):
            names = {"INBOX"} | {e["name"] for e in self.folder_entries(a["id"]) if e.get("special") == "sent" and e.get("selectable", True)}
            try:
                return a["id"], self.backend(a["id"]).folder_signature(sorted(names))
            except Exception:
                return a["id"], None
        if not accounts:
            return []
        with ThreadPoolExecutor(max_workers=min(8, len(accounts))) as pool:
            results = list(pool.map(one, accounts))
        changed = []
        for aid, sig in results:
            if sig is None:
                continue
            if aid in sigs and sigs[aid] != sig:
                changed.append(aid)
            sigs[aid] = sig
        return changed

    def run_absence(self, limit=40):
        """Réponses d'absence : pour chaque message reçu pendant l'absence sur une boîte concernée, une seule réponse par expéditeur.
        Retourne le nombre de réponses envoyées ; un échec d'envoi n'est pas noté (nouvel essai à la synchronisation suivante)."""
        from .. import absence as AB
        from . import composing as C
        a = AB.settings(self.config)
        if AB.state(a) != "active":
            return 0
        log = AB.prune(self.config.get("absence_log"), a)
        sent = 0
        accounts = self.accounts()
        for acc in AB.targets(a, accounts):
            own = AB.own_addresses(self.config, acc)
            for msg in self.cache.query("inbox", acc["id"], limit=200):
                if sent >= limit or not AB.should_reply(a, msg, own, self.config, log):
                    continue
                out = C.absence_outgoing(self.config, accounts, a, msg)
                if out is None:
                    continue
                try:
                    self.backend(acc["id"]).send(out)
                except Exception:                                   # hors ligne, refus : on réessaiera
                    continue
                log[AB.log_key(msg)] = time.time()                 # noté tout de suite : jamais deux réponses au même expéditeur
                sent += 1
        self.config["absence_log"] = log
        self.config.save()
        return sent

    def sync_changed_folders(self, budget=8):
        """Tous les dossiers de toutes les boîtes (Archive, Spam, Corbeille, vos dossiers…) : interroge l'état de chacun (STATUS, léger) ; un dossier jamais lu
        ou dont l'état a changé (tri fait sur un autre poste) est relu en entier — messages récents et TOUS les non lus ; ceux partis ailleurs disparaissent d'ici.
        `budget` dossiers relus au plus par passage, pour ne pas retarder la boîte de réception : le reste suit aux passages suivants.
        Retourne True si le cache a changé."""
        sigs, changed = self.__dict__.setdefault("_folder_sigs", {}), False
        for a in self.accounts():
            if a.get("demo"):
                continue
            ents = [e for e in self.folder_entries(a["id"]) if e.get("selectable", True)][:80]
            logical = {e["name"]: dest_of(e) for e in ents}
            try:
                be = self.backend(a["id"])
                status = be.folder_signature(list(logical))
            except Exception:
                continue
            for name, sig in status.items():
                key, lg = (a["id"], name), logical[name]
                self.folder_unread[key] = sig[1]
                if sigs.get(key) == sig:
                    continue
                if lg in ("inbox", "sent"):                                 # déjà relevés par la synchronisation principale (et IDLE pour la boîte de réception)
                    sigs[key] = sig
                    continue
                if budget <= 0:
                    continue
                budget -= 1
                try:
                    kn = self.cache.uids(a["id"], lg)
                    msgs, flags, present, _min = be.sync(lg, kn, limit=60, unseen=True)
                except Exception:
                    continue                                                 # on réessaiera au prochain passage
                sigs[key] = sig
                self.cache.upsert_many(msgs)
                self._apply_flags(kn, flags)
                gone = [mid for uid, mid in kn.items() if present is not None and uid not in present]
                if gone:
                    self.cache.delete_many(gone)
                changed = changed or bool(msgs or gone or flags)
        return changed

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
        self.emit_events("move", msgs, dest)
        extra = {"notjunk": True} if dest == "inbox" and all(m.folder == "spam" for m in msgs) else {}
        return self.op_enqueue("move", msgs, dest=dest, **extra)

    def pending_ids(self):
        """Identifiants des messages visés par une action locale pas encore exécutée sur le serveur (déplacement, suppression)."""
        try:
            return {it["id"] for op in self.cache.ops_pending(limit=2000) if op["kind"] in ("move", "delete") for it in op["payload"].get("items", [])}
        except Exception:
            return set()

    def finish_move(self, msgs, dest, op_ids):
        """Exécute le déplacement sur le serveur (les actions rapprochées partent ensemble) ; si tout va bien, remplace les copies locales par celles du serveur
        (bon UID, bon dossier). Retourne (erreurs, hors_ligne)."""
        _ok, errors, offline = self.run_ops(op_ids)
        left = {o["id"] for o in self.cache.ops_pending(limit=2000)}
        if not errors and not offline and not (left & set(op_ids)):
            real = []
            for m in msgs:
                try:
                    if not self.backend(m.account).demo:
                        real.append(m.id)
                except Exception:
                    pass
            if real:
                self.cache.delete_many(real)
                dests = self.__dict__.setdefault("_resync_dests", set())
                dests.add(dest)
                lock = self.__dict__.setdefault("_resync_lock", threading.Lock())
                if lock.acquire(blocking=False):                  # une seule relecture à la fois : les suivantes y sont intégrées
                    try:
                        while dests:
                            todo, dests_copy = ("inbox",) + tuple(sorted(dests)), set(dests)
                            dests.difference_update(dests_copy)
                            self.sync(folders=todo)
                    finally:
                        lock.release()
        return errors, offline

    def delete_forever(self, msgs):
        self.cache.delete_many([m.id for m in msgs])
        self.emit_events("delete", msgs)
        return self.op_enqueue("delete", msgs)

    def run_ops(self, op_ids):
        """Envoie au serveur TOUTES les actions en attente, regroupées, une exécution à la fois (les gestes rapprochés ne s'attendent plus les uns les autres)."""
        lock = self.__dict__.setdefault("_ops_lock", threading.Lock())
        with lock:
            return self.op_run(self.cache.ops_pending(limit=2000))

    # -- événements vers les autres machines (lu, favori, épingle, déplacement, suppression)
    def emit_events(self, kind, msgs, dest=""):
        sink = self.event_sink
        if sink is None:
            return
        try:
            emails = {a["id"]: a.get("email", "") for a in self.accounts()}
            evs = [ME.make(kind, m, emails.get(m.account, ""), dest) for m in msgs]
            evs = [e for e in evs if e]
            if evs:
                sink(evs)
        except Exception:
            pass

    def apply_mail_events(self, events, now=None) -> int:
        """Applique au cache local les événements reçus d'une autre machine. Ne renvoie RIEN au serveur ni aux autres machines (pas de boucle) :
        la machine d'origine a déjà envoyé l'action au serveur. Retourne le nombre de messages modifiés."""
        ids_of = {a.get("email", "").lower(): a["id"] for a in self.accounts()}
        done = 0
        for ev in ME.newest_per_message(ME.sanitize(events, now)):
            aid = ids_of.get(ev["acct"])
            ids = self.cache.find_ids_by_message_id(aid, ev["mid"]) if aid else []
            if not ids:
                continue
            kind, what = ME.as_change(ev)
            if kind == "flag":
                self.cache.update_many(ids, **{what[0]: what[1]})
            elif kind == "move":
                self.cache.update_many(ids, folder=what, snoozed_until=0.0)
            else:
                self.cache.delete_many(ids)
            done += len(ids)
        return done

    def set_flag(self, msgs, field, value):
        """field : starred (favori), unread (non lu) ou pinned (épingle, aussi enregistrée sur la boîte). Retourne les actions à exécuter."""
        self.cache.update_many([m.id for m in msgs], **{field: bool(value)})
        self.emit_events({("unread", False): "read", ("unread", True): "unread", ("starred", True): "star", ("starred", False): "unstar",
                          ("pinned", True): "pin", ("pinned", False): "unpin"}[(field, bool(value))], msgs)
        if field == "starred":
            return self.op_enqueue("flags", msgs, flagged=bool(value))
        if field == "unread":
            return self.op_enqueue("flags", msgs, seen=not value)
        if field == "pinned":
            return self.op_enqueue("flags", msgs, pinned=bool(value))
        raise ValueError(field)

    # -- envoi
    def default_account(self, msg=None, current="all"):
        if msg and any(a["id"] == msg.account for a in self.accounts()):
            return msg.account
        return current if current != "all" and any(a["id"] == current for a in self.accounts()) else self.accounts()[0]["id"]

    def queue_send(self, out, delay=0, scheduled=False):
        """Met le message dans la boîte d'envoi (délai d'annulation, ou date programmée). Retourne son identifiant."""
        import uuid
        oid = uuid.uuid4().hex
        wait = delay if scheduled else self.config["undo_seconds"]
        self.cache.outbox_add(oid, time.time() + wait, out)
        return oid

    def undo_send(self, oid):
        """Annule un envoi pas encore parti ; retourne le message (pour le rouvrir) ou None s'il est déjà parti."""
        out = next((o for i, _t, o, _n in self.cache.outbox_list() if i == oid), None)
        self.cache.outbox_remove(oid)
        return out

    def process_outbox(self):
        """Envoie les messages dont l'heure est venue (à appeler hors du fil de l'interface). Retourne [(état, message, erreur)] avec
        état « sent », « retry » (hors ligne : conservé, nouvel essai dans 1 min) ou « failed »."""
        events = []
        for oid, out in self.cache.outbox_due():
            if not self.cache.outbox_claim(oid):
                continue                    # pris par l'envoi différé en tâche de fond (minuterie) : pas de double envoi
            try:
                be = self.backend(out.account)
                be.send(out)
            except Exception as e:
                if is_retryable(e) and self.cache.outbox_tries(oid) < 10:
                    self.cache.outbox_reschedule(oid, time.time() + 60)
                    events.append(("retry", out, e))
                else:
                    self.cache.outbox_remove(oid)
                    events.append(("failed", out, e))
                continue
            self.cache.outbox_remove(oid)
            acc = next((a for a in self.accounts() if a["id"] == out.account), {})
            if be.demo:
                import uuid
                from ..models import Message
                from ..util import html_to_text
                t = html_to_text(out.html)
                self.cache.upsert(Message(id="demo|SENT|%s" % uuid.uuid4().hex[:8], account=out.account, folder="sent", uid=0,
                                          sender_name=acc.get("name", ""), sender_email=acc.get("email", ""), to=out.to, subject=out.subject,
                                          date=time.time(), snippet=t[:150], text=t, html=out.html, unread=False))
            else:
                self.sync(folders=("sent",))
            events.append(("sent", out, None))
        return events

    def snooze(self, msgs, ts):
        """Reporte des messages jusqu'à ts (ils quittent la boîte puis y reviennent à l'heure dite)."""
        if msgs and ts > time.time():
            self.cache.update_many([m.id for m in msgs], snoozed_until=ts)
