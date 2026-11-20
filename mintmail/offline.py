"""Mode hors ligne : les actions serveur (déplacer, drapeaux, suppression) sont enregistrées puis rejouées dans l'ordre."""
import json
from types import SimpleNamespace

from . import activity as AC
from .backend import is_retryable      # noqa: F401  (réexporté pour la fenêtre)
from .i18n import tr

MAX_TRIES = 8


class OfflineMixin:
    offline = False
    _flushing = False

    # --------------------------------------------------------------- enregistrement
    def op_enqueue(self, kind, msgs, **extra):
        """Enregistre l'action (une par compte) et retourne la liste des identifiants à exécuter."""
        by = {}
        for m in msgs:
            if getattr(m, "uid", 0) > 0 and getattr(m, "real_folder", ""):
                by.setdefault(m.account, []).append(m)
        ids = []
        skipped = len(msgs) - sum(len(v) for v in by.values())
        if skipped:
            AC.LOG.add(AC.WARN, AC.count_text(skipped, tr("%d message sans identifiant serveur : action faite ici seulement, rien envoyé à la boîte"),
                                              tr("%d messages sans identifiant serveur : action faite ici seulement, rien envoyé à la boîte")))
        for aid, lst in by.items():
            items = [{"id": m.id, "uid": m.uid, "real": m.real_folder} for m in lst]
            ids.append(self.cache.ops_add(aid, kind, dict(extra, items=items)))
        return ids

    def _op_exec(self, op):
        be = self.backend(op["account"])
        if be.demo:
            return
        p = op["payload"]
        items = [SimpleNamespace(id=i["id"], uid=i["uid"], real_folder=i["real"], account=op["account"]) for i in p["items"]]
        if op["kind"] == "move":
            if p.get("notjunk"):
                be.move_many(items, p["dest"], notjunk=True)      # « Ce n'est pas du spam » (voir backend.move_many)
            else:
                be.move_many(items, p["dest"])
        elif op["kind"] == "flags":
            extra = {}
            if "pinned" in p:                                   # anciennes actions en file (sans épingle) : appel inchangé
                extra["pinned"] = p["pinned"]
                if p.get("probe"):
                    extra["probe"] = True
            be.set_flags_many(items, seen=p.get("seen"), flagged=p.get("flagged"), **extra)
        elif op["kind"] == "delete":
            be.delete_many(items)

    @staticmethod
    def _coalesce(ops):
        """Regroupe les actions CONSÉCUTIVES de même nature (même boîte, même type, mêmes paramètres) : 21 suppressions rapprochées = UNE commande au serveur.
        Retourne [(action fusionnée, [actions d'origine])] dans l'ordre."""
        groups = []
        for op in ops:
            p = {k: v for k, v in op["payload"].items() if k != "items"}
            key = (op["account"], op["kind"], json.dumps(p, sort_keys=True))
            if groups and groups[-1][0] == key:
                groups[-1][2].append(op)
            else:
                groups.append((key, p, [op]))
        out = []
        for _key, p, members in groups:
            merged = dict(members[0], payload=dict(p, items=[i for m in members for i in m["payload"]["items"]]))
            out.append((merged, members))
        return out

    def _who(self, aid):
        try:
            for a in self.accounts():
                if a["id"] == aid:
                    return a.get("email") or a.get("name") or aid
        except Exception:
            pass
        return aid

    def _op_text(self, merged):
        """Phrase décrivant une action serveur : « Suppression de 3 messages sur x@y »."""
        n = len(merged["payload"].get("items", []))
        msgs = AC.count_text(n, tr("%d message"), tr("%d messages"))
        k, p = merged["kind"], merged["payload"]
        who = self._who(merged["account"])
        if k == "delete":
            return tr("Suppression définitive de %s sur %s") % (msgs, who)
        if k == "move":
            dest = p.get("dest", "")
            return tr("%s → %s sur %s") % (msgs, ("%s" % dest).split(":", 1)[-1], who)
        if "pinned" in p:
            what = tr("épingle")
        elif p.get("flagged") is not None:
            what = tr("favori (étoile)")
        else:
            what = tr("lu / non lu")
        return tr("Drapeau « %s » de %s sur %s") % (what, msgs, who)

    def op_run(self, ops):
        """Exécute des actions dans l'ordre (en arrière-plan), regroupées quand elles se suivent. Retourne (réussies, erreurs, hors_ligne)."""
        done, errors, offline, blocked = [], [], False, set()
        for merged, members in self._coalesce(ops):
            if merged["account"] in blocked:
                continue                       # l'ordre est gardé PAR BOÎTE : une boîte hors ligne ne retient pas les autres
            what = self._op_text(merged)
            AC.LOG.start(("op", merged["account"]), what + "…", merged["account"])
            try:
                self._op_exec(merged)
                for op in members:
                    self.cache.ops_done(op["id"])
                done += members
                AC.LOG.finish(("op", merged["account"]), AC.OK, what + " ✔", merged["account"])
            except Exception as e:
                if is_retryable(e) and (getattr(e, "cooldown", False) or members[0]["tries"] < MAX_TRIES):
                    for op in members:
                        if not getattr(e, "cooldown", False):          # frein anti-blocage : aucune tentative n'a eu lieu, l'action n'est pas « ratée »
                            self.cache.ops_fail(op["id"])
                    offline = True
                    blocked.add(merged["account"])
                    AC.LOG.finish(("op", merged["account"]), AC.WARN, tr("Pas de connexion, nouvel essai automatique. Action concernée : %s (%s)") % (what, str(e)[:60]), merged["account"])
                    continue
                for op in members:
                    self.cache.ops_done(op["id"])      # refus définitif (ou trop d'échecs) : abandonné
                errors.append(str(e))
                AC.LOG.finish(("op", merged["account"]), AC.ERR, tr("%s REFUSÉ par le serveur : %s — le message sera restauré à la prochaine relève") % (what, str(e)[:100]), merged["account"])
        return done, errors, offline

    # --------------------------------------------------------------------- relecture
    def flush_ops(self):
        if self._flushing or not self.cache.ops_count():
            return
        self._flushing = True

        def work():
            return self.op_run(self.cache.ops_pending())

        def done(res, err):
            self._flushing = False
            if err:
                return
            ok, errors, offline = res
            self._set_offline(offline)
            moved = [o for o in ok if o["kind"] == "move"]
            if moved:
                self.cache.delete_many([i["id"] for o in moved for i in o["payload"]["items"]])
                self.sync(folders=("inbox", "sent", "archive", "trash", "spam"), quiet=True)
            if errors:
                self.toast.popup(tr("Une action en attente a été refusée par le serveur : %s") % errors[0][:80], timeout=6)
            elif ok and not offline:
                self.toast.popup(tr("Réseau rétabli : %d action(s) envoyée(s) au serveur") % len(ok), timeout=4)
            self.reload_list()
            self.update_counts()
        self.run_bg(work, done)

    def _set_offline(self, offline):
        self.offline = bool(offline)
        self.update_offline_status()

    def update_offline_status(self):
        n = self.cache.ops_count() + self.cache.outbox_count()
        if self.offline or (n and getattr(self, "_net_error", False)):
            self.status.set_text(tr("⚠ Hors ligne — %d action(s) en attente, rejouées automatiquement") % n)
        elif n:
            self.status.set_text(tr("%d action(s) en attente d'envoi") % n)
