"""Mode hors ligne : les actions serveur (déplacer, drapeaux, suppression) sont enregistrées puis rejouées dans l'ordre."""
from types import SimpleNamespace

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

    def op_run(self, ops):
        """Exécute des actions dans l'ordre (en arrière-plan). Retourne (réussies, erreurs, hors_ligne)."""
        done, errors, offline = [], [], False
        for op in ops:
            try:
                self._op_exec(op)
                self.cache.ops_done(op["id"])
                done.append(op)
            except Exception as e:
                if is_retryable(e) and op["tries"] < MAX_TRIES:
                    self.cache.ops_fail(op["id"])
                    offline = True
                    break              # on garde l'ordre : le reste attend le retour du réseau
                self.cache.ops_done(op["id"])      # refus définitif (ou trop d'échecs) : abandonné
                errors.append(str(e))
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
