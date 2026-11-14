"""Fenêtre principale Qt — organisation : Aujourd'hui, agenda, tâches, invitations, créneaux, relances, désabonnement, pièces jointes, fil,
synchronisation P2P, barre latérale réduite, zoom, catégories, notifications et état hors ligne. Mélangé à MainWindow (voir window.py) ;
la logique est dans organizer.py / syncing.py, testée sans Qt."""
import threading
import time

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QFileDialog, QMessageBox

from .. import sysdeps
from ..i18n import tr
from ..p2p import SyncEngine
from ..syncdata import apply_items, describe as describe_sync
from . import assistant as AS
from . import organizer as O
from . import syncing as SY
from . import ui_organizer as UO

CATEGORIES = [(None, tr("Tout")), ("people", tr("Personnes")), ("notif", tr("Notifications")), ("news", tr("Newsletters"))]
ZOOM_MIN, ZOOM_MAX, ZOOM_STEP = 0.6, 2.4, 0.1


class OrganizerMixin:
    # ------------------------------------------------------------ utilitaires
    def ai_enabled(self):
        return AS.ai_engine(self.engine).enabled()

    def say(self, text, ms=0):
        self.status.setText(text)

    def focus_message(self, m):
        """Affiche un message (de la liste ou non) dans le lecteur ; sélectionne sa ligne si elle est visible."""
        if m is None:
            return
        full = self.cache.get(m.id) or m
        if full.folder == "drafts":
            return self.open_draft(full)
        r = self.model.row_of(m.id)
        if r >= 0:
            self.list.setCurrentIndex(self.model.index(r))
        else:
            self.current = m.id
            self._show(self.engine.open_message(m.id))

    # ------------------------------------------------------------ clic droit : organisation
    def add_extra_menu(self, menu, m):
        menu.addSeparator()
        menu.addAction(tr("Créer une tâche depuis ce message…"), lambda: self.add_task_dialog(self.cache.get(m.id) or m))
        menu.addAction(tr("Proposer des créneaux (agenda)…"), lambda: self.propose_slots(self.cache.get(m.id) or m))
        fu = menu.addMenu(tr("Me le rappeler si pas de réponse"))
        for days, label in ((1, tr("sous 1 jour")), (3, tr("sous 3 jours")), (7, tr("sous 7 jours"))):
            fu.addAction(label, lambda d=days: self.add_followup(self.cache.get(m.id) or m, d))
        full = self.cache.get(m.id) or m
        if getattr(full, "unsubscribe", ""):
            menu.addAction(tr("Se désabonner…"), lambda: self.unsubscribe(full))

    # ------------------------------------------------------------ extras du lecteur
    def fill_extras(self, msg):
        if msg is None:
            self.extras.clear()
            return
        threads = bool(self.config.get("threads", True))
        rows = O.thread_rows(self.cache, msg) if threads else []
        plan = O.unsubscribe_plan(msg)
        inv = O.invite_view(msg)
        self.extras.set_message(msg, rows, plan["kind"] in ("oneclick", "mailto", "web") and bool(getattr(msg, "unsubscribe", "")), inv,
                                O.attachment_chips(msg), O.attachments_total(msg))
        if inv and O.gcal_cfg(self.config):
            mid = msg.id
            self.run_bg(lambda: O.invite_conflict_note(self.engine, msg),
                        lambda note, err: self.extras.set_invite_note(note) if note and self.shown is not None and self.shown.id == mid else None)

    def _wire_extras(self):
        x = self.extras
        x.attachment.connect(self.attachment_action)
        x.save_all.connect(self.attachments_save_all)
        x.unsubscribe.connect(lambda: self.unsubscribe(self.shown))
        x.invite.connect(self.invite_action)
        x.open_message.connect(lambda mid: self.focus_message(self.cache.get(mid)))

    # ------------------------------------------------------------ pièces jointes
    def attachment_action(self, att, action):
        if action == "copy":
            QGuiApplication.clipboard().setText(att["path"])
            return
        if action == "save":
            path, _ = QFileDialog.getSaveFileName(self, tr("Enregistrer la pièce jointe"), att["filename"])
            if path:
                O.save_one(att, path)
            return
        kind, text = O.open_plan(att)
        if kind == "block":
            QMessageBox.warning(self, tr("Fichier potentiellement dangereux"), text)
            return
        if kind == "warn" and QMessageBox.question(self, tr("Ouvrir ce fichier ?"), text) != QMessageBox.Yes:
            return
        if kind.startswith("preview") and action != "open_external" and (action == "preview" or action == "open"):
            dlg = UO.AttachmentPreview(self, att, kind.split("_")[1])
            dlg.open_with.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(att["path"])))
            dlg.show()
            self._previews = getattr(self, "_previews", []) + [dlg]
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(att["path"]))

    def attachments_save_all(self):
        m = self.shown
        if m is None:
            return
        d = QFileDialog.getExistingDirectory(self, tr("Enregistrer toutes les pièces jointes dans…"))
        if d:
            self.say(tr("%d fichier(s) enregistré(s) dans %s") % (len(O.save_all(m, d)), d))

    # ------------------------------------------------------------ désabonnement
    def unsubscribe(self, msg):
        if msg is None:
            return
        msg = self.cache.get(msg.id) or msg
        plan = O.unsubscribe_plan(msg)
        kind = plan["kind"]
        if kind in ("none", "refused"):
            self.say(plan["note"])
        elif kind == "web":
            QDesktopServices.openUrl(QUrl(plan["url"]))
        elif QMessageBox.question(self, tr("Désabonnement"), plan["ask"] + "\n\n" + plan["detail"]) == QMessageBox.Yes:
            if kind == "mailto":
                self.queue_send(O.unsubscribe_mail(msg, plan), delay=2)
                self.say(tr("Demande de désabonnement envoyée à %s") % plan["to"])
            else:
                self.say(tr("Désabonnement en cours…"))

                def done(res, err):
                    ok, detail = res if res else (False, str(err))
                    if ok:
                        self.say(tr("Désabonné de %s ✔ (si des messages arrivent encore, mettez l'expéditeur en spam)") % plan["who"][:30])
                    else:
                        self.say(tr("Le service a refusé la demande (%s). Ouverture de la page de désabonnement…") % detail[:40])
                        QDesktopServices.openUrl(QUrl(plan["url"]))
                self.run_bg(lambda: O.unsubscribe_oneclick(plan), done)

    # ------------------------------------------------------------ invitations, agenda, créneaux
    def invite_action(self, action):
        m = self.shown
        if m is None:
            return
        m = self.cache.get(m.id) or m
        if action == "slots":
            return self.propose_slots(m)
        if action == "add":
            return self.invite_add(m)
        out, text = O.invite_reply(self.engine, m, action)
        if out is None:
            self.say(text)
            return
        self.queue_send(out, delay=2)
        self.say(text)
        if action == "accept" and O.invite_event(m)[0]:
            self.invite_add(m)

    def invite_add(self, m):
        ev, uid, raw = O.invite_event(m)
        if ev:
            self.calendar_add(ev, uid, raw)

    def calendar_add(self, ev, uid="", raw=None):
        self.say(tr("Ajout à l'agenda…"))

        def done(res, err):
            if err:
                self.say(tr("Agenda : %s") % str(err)[:100])
                return
            ok, text, path = res
            self.say(text)
            if path:
                QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        self.run_bg(lambda: O.calendar_add_event(self.engine, ev, uid, raw), done)

    def show_agenda(self):
        if not O.gcal_cfg(self.config):
            self.say(tr("Activez Google Agenda : Paramètres → Agenda."))
            return self.show_settings(page="calendar")
        self.say(tr("Chargement de l'agenda…"))

        def done(res, err):
            dlg = UO.AgendaDialog(self, res if res else (False, str(err)))
            dlg.new_event.connect(lambda: QTimer.singleShot(0, self.new_event_dialog))
            dlg.exec()
        self.run_bg(lambda: O.agenda_events(self.engine), done)

    def new_event_dialog(self):
        dlg = UO.EventDialog(self)
        if dlg.exec() != dlg.Accepted:
            return
        ev, err = dlg.event()
        if ev is None:
            self.say(err)
            return
        self.calendar_add(ev)

    def propose_slots(self, msg=None):
        m = msg or self._open_msg()
        if m is None:
            return
        if not O.gcal_cfg(self.config):
            self.say(tr("Activez Google Agenda pour proposer des créneaux : Paramètres → Agenda."))
            return self.show_settings(page="calendar")
        self.say(tr("Recherche de créneaux libres…"))

        def done(text, err):
            if err:
                self.say(tr("Agenda : %s") % str(err)[:100])
                return
            self.say("")
            from . import composing as C
            kw = C.reply_args(self.config, self.engine.accounts(), m, False, self.engine.default_account(m, self.account))
            kw["ai_suggested_text"] = text
            self.compose(**kw)
        self.run_bg(lambda: O.propose_slots(self.engine), done)

    # ------------------------------------------------------------ tâches, Aujourd'hui, relances
    def add_task_dialog(self, msg=None):
        dlg = UO.TaskDialog(self, msg)
        if dlg.exec() != dlg.Accepted:
            return
        task, note = O.task_add_from_form(self.config, dlg.text.text(), dlg.due.text(), msg)
        if note:
            self.say(note)

    def tasks_from_message(self, msg):
        _added, text = O.tasks_from_message(self.config, self.cache, msg)
        self.say(text)

    def show_today(self):
        if O.gcal_cfg(self.config):
            self.run_bg(lambda: O.agenda_events(self.engine, today_only=True), lambda res, err: self._today(res if res else (False, str(err))))
        else:
            self._today(None)

    def _today(self, agenda):
        dlg = UO.TodayDialog(self, agenda)
        dlg.chosen.connect(lambda m: QTimer.singleShot(0, lambda: self.focus_message(m)))
        dlg.exec()

    def open_today_at_start(self):
        if self.config.get("open_today_on_start"):
            QTimer.singleShot(1500, self.show_today)

    def add_followup(self, msg, days):
        self.say(O.add_followup(self.config, msg, days))

    def check_followups(self):
        for f in O.due_followups(self.config, self.cache):
            self.say(tr("Pas de réponse à « %s »") % f["subject"][:50])
            if self.config.get("notifications", True):
                sysdeps.notify(tr("Pas de réponse"), "« %s » — %s" % (f["subject"], f["to"]))

    # ------------------------------------------------------------ synchronisation P2P
    def init_sync(self):
        """(Re)démarre la synchronisation automatique entre machines (sans effet si désactivée ou sans code de jumelage)."""
        old = getattr(self, "sync_engine", None)
        if old is not None:
            old.stop()
        self.sync_engine = SyncEngine(self.config, cache=self.cache, apply_cb=self._p2p_apply)
        self.sync_engine.start()

    def _p2p_apply(self, wins):
        """Appelé par le moteur (fil de synchro) : applique les éléments reçus DANS le fil de l'interface, puis attend le résultat."""
        box, ev = {}, threading.Event()
        self._p2p_job = (wins, box, ev)
        self.bridge.p2p.emit()
        ev.wait(15)
        return box.get("res")

    def _p2p_run(self):
        wins, box, ev = self._p2p_job
        try:
            box["res"] = apply_items(self.config, wins, self.cache)
            self._p2p_refresh(box["res"])
        except Exception:
            from ..log import log_exception
            log_exception("p2p apply")
        finally:
            ev.set()

    def _p2p_refresh(self, res):
        if res["accounts"]:
            self.engine._backends.clear()
            self._build_sidebar(self.view_key)
        if res["settings"]:
            self.apply_theme()
        if res["lists"]:
            self._build_sidebar(self.view_key)
        self.reload()
        names = res.get("new_accounts") or []
        self.say((tr("Synchro : compte « %s » ajouté — ") % names[0] if names else tr("Synchro : ")) + describe_sync(res))

    def p2p_now(self):
        eng = getattr(self, "sync_engine", None)
        if eng is None or not eng.is_enabled():
            self.say(tr("Synchronisation entre postes inactive : Réglages → Synchronisation."))
            return self.show_settings(page="p2p")
        self.say(tr("Synchronisation avec vos autres postes…"))
        self.run_bg(lambda: eng.sync_now(), lambda res, err: self.say(SY.sync_result_text(eng, res) if not err else tr("Synchro : %s") % str(err)[:80]))

    def p2p_footer(self):
        self.p2p_lbl.setText(SY.footer_label(getattr(self, "sync_engine", None), self.config))
        self.p2p_lbl.setVisible(bool(self.p2p_lbl.text()) and not self.rail)

    # ------------------------------------------------------------ barre latérale réduite
    def set_rail(self, rail):
        self.rail = bool(rail)
        self.config["rail"] = self.rail
        self.config.save()
        self.sidebar.setFixedWidth(64 if self.rail else 250)
        self.nav_delegate.rail = self.rail
        for w in (self.brand_text, self.status, self.p2p_lbl):
            w.setVisible(not self.rail and (w is not self.p2p_lbl or bool(self.p2p_lbl.text())))
        self.new_btn.setText("✎" if self.rail else "✎   " + tr("Nouveau message"))
        self.today_btn.setText("📅" if self.rail else "📅   " + tr("Aujourd'hui"))
        for i in range(self.folders.count()):
            it = self.folders.item(i)
            it.setToolTip(it.text() if self.rail else "")
        self.folders.doItemsLayout()
        self.folders.viewport().update()

    def toggle_rail(self):
        self.set_rail(not self.rail)

    # ------------------------------------------------------------ zoom du lecteur
    def zoom_reader(self, delta):
        z = 1.0 if delta == 0 else min(ZOOM_MAX, max(ZOOM_MIN, round(float(self.config.get("zoom", 1.0)) + delta, 2)))
        self.config["zoom"] = z
        self.config.save()
        self.apply_zoom()
        self.say(tr("Zoom : %d %%") % round(z * 100))

    def apply_zoom(self):
        z = float(self.config.get("zoom", 1.0) or 1.0)
        if getattr(self.reader, "kind", "") == "webengine":
            self.reader.setZoomFactor(z)
        else:
            f = self.reader.font()
            base = getattr(self, "_reader_base_px", None) or f.pointSizeF() or 10.0
            self._reader_base_px = base
            f.setPointSizeF(base * z)
            self.reader.setFont(f)

    # ------------------------------------------------------------ catégories (Personnes / Notifications / Newsletters)
    def set_category(self, key):
        self.category = key
        for k, b in self.cat_buttons.items():
            b.blockSignals(True)
            b.setChecked(k == key)
            b.blockSignals(False)
        self.reload()

    def update_category_bar(self):
        self.cat_bar.setVisible(self.view_key == "inbox")

    # ------------------------------------------------------------ notifications et état hors ligne
    def notify_new_mail(self, fresh):
        """Notification de bureau pour les nouveaux messages (pas au tout premier chargement)."""
        if fresh <= 0 or not self.config.get("notifications", True) or self.isActiveWindow():
            return
        top = next(iter(self.cache.query("inbox", "all", unread_only=True, limit=1)), None)
        if fresh == 1 and top is not None:
            sysdeps.notify(top.display_sender, top.subject or "")
        else:
            sysdeps.notify(tr("MintMail"), tr("%d nouveaux messages") % fresh)

    def offline_text(self, offline):
        n = self.cache.ops_count() + self.cache.outbox_count()
        if offline:
            return tr("⚠ Hors ligne — %d action(s) en attente, rejouées automatiquement") % n
        return tr("%d action(s) en attente d'envoi") % n if n else ""
