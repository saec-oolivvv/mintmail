"""Conversations, désabonnement en un clic, invitations, recherche sur le serveur, apprentissage, carnet d'adresses."""
import os
import tempfile
import threading

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib, Gtk

import datetime
import hashlib
import re
import time
import uuid

from . import caldav, gcal, ical, oauth, slots, tasks as tk, unsub
from .ai_engine import make_ics
from .models import Message, Outgoing
from .util import normalize_subject, text_to_html
from .reader import open_uri


class ExtrasMixin:
    # ----------------------------------------------------------------- conversations
    def threads_on(self):
        return bool(self.config.get("threads", True))

    def _expand_threads(self, msgs):
        """Une action sur une conversation vaut pour tous ses messages du même dossier."""
        if not (self.threads_on() and any(getattr(m, "thread_count", 1) > 1 for m in msgs)):
            return msgs
        out, seen = [], set()
        for m in msgs:
            group = [m]
            if getattr(m, "thread_count", 1) > 1 and getattr(m, "thread_id", ""):
                group = [x for x in self.cache.thread_members(m.account, m.thread_id) if x.folder == m.folder] or [m]
            for x in group:
                if x.id not in seen:
                    seen.add(x.id)
                    out.append(x)
        return out

    def _open_thread_extras(self, msg, full):
        """À l'ouverture : marque toute la conversation lue et liste ses autres messages dans le lecteur."""
        tid = getattr(full, "thread_id", "") or getattr(msg, "thread_id", "")
        if not tid:
            self.reader.show_thread([], full.id)
            if full.invite:
                self._invite_conflicts(full)
            return
        members = self.cache.thread_members(full.account, tid)
        self.reader.show_thread(members, full.id)
        if full.invite:
            self._invite_conflicts(full)
        if self.threads_on() and getattr(msg, "thread_count", 1) > 1 and msg.folder != "drafts":
            unread = [x for x in members if x.unread and x.folder == msg.folder and x.id != msg.id]
            if unread:
                self.set_unread(unread, False, reload=False)

    def _on_open_thread_message(self, reader, mid):
        m = self.cache.get(mid)
        if m is not None:
            self.open_message(m, force=True)

    def ai_summarize_thread(self, msg):
        if not self.engine.enabled():
            self.toast.popup("IA non configurée : Paramètres → IA.", timeout=4)
            self.show_settings("ai")
            return
        self._focus_message(msg)
        members = self.cache.thread_members(msg.account, msg.thread_id)
        self.reader.ai_working("Résumé de la conversation (%d messages)…" % len(members))

        def work():
            return self.engine.summarize_thread([self.cache.get(m.id) or m for m in members])
        self.run_bg(work, lambda t, e: self.reader.ai_text("Conversation", ("Erreur IA : %s" % str(e)[:100]) if e else t)
                    if self.reader.msg is not None and self.reader.msg.id == msg.id else None)

    # --------------------------------------------------------------- désabonnement
    def _confirm(self, text, secondary=""):
        d = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION, text=text, secondary_text=secondary)
        d.add_buttons("Annuler", Gtk.ResponseType.CANCEL, "Continuer", Gtk.ResponseType.OK)
        ok = d.run() == Gtk.ResponseType.OK
        d.destroy()
        return ok

    def unsubscribe(self, msg):
        """Désabonnement en un clic (RFC 8058) si le message le permet, sinon par e-mail, sinon dans le navigateur."""
        msg = self._full(msg)
        links = unsub.parse_list_unsubscribe(msg.unsubscribe)
        who = msg.display_sender
        if msg.unsub_post and links["https"]:
            if not self._confirm("Se désabonner de %s ?" % who,
                                 "MintMail envoie la demande de désabonnement directement au service (requête sécurisée, sans ouvrir de page)."):
                return
            self.toast.popup("Désabonnement en cours…", timeout=3)
            url = links["https"][0]

            def done(res, err):
                ok, detail = res if res else (False, str(err))
                if ok:
                    self.toast.popup("Désabonné de %s ✔ (si des messages arrivent encore, mettez l'expéditeur en spam)" % who[:30],
                                     "Mettre en spam", lambda: self.spam_sender(msg), timeout=10)
                else:
                    self.toast.popup("Le service a refusé la demande (%s). Ouverture de la page de désabonnement…" % detail[:40], timeout=6)
                    open_uri(self, url)
            self.run_bg(lambda: unsub.one_click_post(url), done)
        elif links["mailto"]:
            to, subject, body = unsub.mailto_fields(links["mailto"][0])
            if not to:
                self.toast.popup("Adresse de désabonnement invalide ou multiple : refusée par sécurité.", timeout=6)
                return
            if not self._confirm("Se désabonner de %s ?" % who, "Un e-mail de désabonnement sera envoyé à %s." % to):
                return
            self.queue_send(Outgoing(account=msg.account, to=to, subject=subject, html="<p>%s</p>" % body, text=body), delay=2)
            self.toast.popup("Demande de désabonnement envoyée à %s" % to, "Mettre en spam", lambda: self.spam_sender(msg), timeout=10)
        elif links["https"]:
            open_uri(self, links["https"][0])
        else:
            self.toast.popup("Ce message ne propose pas de lien de désabonnement.", timeout=4)

    # ---------------------------------------------------------------------- identités
    def _addressed_identity(self, msg):
        """Identité (alias) à laquelle le message a été adressé, ou None."""
        to = ((msg.to or "") + " " + (msg.cc or "")).lower()
        for ident in self.config.get("identities", []):
            if ident.get("account") == msg.account and ident["email"].lower() in to:
                return ident
        return None

    def _from_choice(self, msg):
        ident = self._addressed_identity(msg)
        return ("ident:" + ident["id"]) if ident else self._default_account(msg)

    # ------------------------------------------------------------------ invitations
    def _my_address(self, msg):
        """Adresse sous laquelle l'invitation a été reçue (identité ou compte)."""
        acc = next((a for a in self.accounts() if a["id"] == msg.account), {})
        to = (msg.to + " " + msg.cc).lower()
        for ident in self.config.get("identities", []):
            if ident.get("account") == msg.account and ident["email"].lower() in to:
                return ident["email"], ident.get("name", ""), ident["email"]
        return acc.get("email", ""), acc.get("name", ""), ""

    def invite_respond(self, msg, action):
        msg = self._full(msg)
        inv = msg.invite or {}
        if not inv.get("organizer"):
            self.toast.popup("Pas d'organisateur à qui répondre.", timeout=3)
            return
        email, name, from_email = self._my_address(msg)
        verb = {"accept": "accepté", "tentative": "accepté sous réserve", "decline": "décliné"}[action]
        out = Outgoing(account=msg.account, to=inv["organizer"], subject=ical.reply_subject(inv, action),
                       html="<p>J'ai %s l'invitation « %s ».</p>" % (verb, inv.get("title", "")), text="J'ai %s l'invitation." % verb,
                       ics=ical.build_reply(inv, email, name, action), ics_method="REPLY",
                       from_email=from_email, from_name=name if from_email else "")
        self.queue_send(out, delay=2)
        if action == "accept":
            self.toast.popup("Invitation acceptée — réponse envoyée à l'organisateur", "Ajouter à l'agenda", lambda: self.invite_add(msg), timeout=8)
        else:
            self.toast.popup("Réponse envoyée à l'organisateur (%s)" % verb, timeout=4)

    # ------------------------------------------------------------------ agenda
    def _gcal_cfg(self):
        c = self.config.get("gcal") or {}
        return c if c.get("enabled") and c.get("account") else None

    def _gcal_token(self):
        c = self._gcal_cfg()
        acc = next((a for a in self.accounts() if a["id"] == c["account"] and a.get("auth") == "oauth2"), None) if c else None
        if acc is None:
            raise oauth.OAuthError("compte Gmail (OAuth) introuvable : Paramètres → Agenda")
        return oauth.manager_for(self.config).access_token(acc)

    def calendar_add_event(self, ev, uid="", raw_ics=None):
        """Ajoute un événement à l'agenda choisi : Google Agenda, sinon CalDAV, sinon fichier .ics ouvert dans l'agenda du système."""
        if self._gcal_cfg():
            self.toast.popup("Ajout à Google Agenda…", timeout=3)

            def work():
                return gcal.insert_event(self._gcal_token(), ev, uid)
            self.run_bg(work, lambda res, err: self.toast.popup(
                ("Google Agenda : %s ✔" % res[1]) if res and res[0] else "Google Agenda : %s" % (res[1] if res else err), timeout=6))
            return
        cfg = self.config.get("caldav") or {}
        ics = raw_ics or make_ics(ev)
        if cfg.get("url"):
            pw = self.config.password("caldav")
            self.toast.popup("Envoi à l'agenda CalDAV…", timeout=3)
            self.run_bg(lambda: caldav.put_event(cfg["url"], cfg.get("user", ""), pw, ics.replace("METHOD:REQUEST", "METHOD:PUBLISH"),
                                                 uid or ev.get("title", "evenement")),
                        lambda res, err: self.toast.popup("Ajouté à votre agenda ✔" if res and res[0] else
                                                          "Agenda CalDAV : %s" % (res[1] if res else err), timeout=5))
            return
        try:
            fd, path = tempfile.mkstemp(prefix="mintmail-", suffix=".ics")
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
                f.write(ics)
            Gio.AppInfo.launch_default_for_uri("file://" + path, None)
            self.toast.popup("Événement « %s » envoyé à votre agenda" % ev.get("title", "")[:40], timeout=4)
        except Exception as e:
            self.show_error("Impossible d'ouvrir l'agenda", e)

    def invite_add(self, msg):
        """Ajoute l'invitation à l'agenda (Google Agenda, CalDAV ou fichier .ics)."""
        inv = self._full(msg).invite or {}
        if not inv.get("raw"):
            return
        self.calendar_add_event({"title": inv.get("title", ""), "start": inv.get("start", ""), "end": inv.get("end", ""),
                                 "location": inv.get("location", ""), "description": inv.get("description", "")},
                                uid=inv["uid"], raw_ics=inv["raw"])

    def agenda_events(self, days=14):
        """(ok, événements | message) des prochains jours dans Google Agenda ; à appeler en arrière-plan."""
        now = datetime.datetime.now()
        return gcal.list_events(self._gcal_token(), now, now + datetime.timedelta(days=days))

    def show_agenda(self):
        if not self._gcal_cfg():
            self.toast.popup("Activez Google Agenda : Paramètres → Agenda.", timeout=4)
            self.show_settings("calendar")
            return
        self.toast.popup("Chargement de l'agenda…", timeout=2)
        self.run_bg(self.agenda_events, self._agenda_dialog)

    def _agenda_dialog(self, res, err):
        ok, data = res if res else (False, str(err))
        dlg = Gtk.Dialog(title="Agenda — 14 prochains jours", transient_for=self, modal=True)
        dlg.add_buttons("Nouvel événement…", 1, "Fermer", Gtk.ResponseType.CLOSE)
        dlg.set_default_size(520, 460)
        box = dlg.get_content_area()
        box.set_border_width(14)
        sw = Gtk.ScrolledWindow()
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        sw.add(inner)
        box.pack_start(sw, True, True, 0)
        if not ok:
            inner.pack_start(Gtk.Label(label="Google Agenda : %s" % data, xalign=0), False, False, 0)
        elif not data:
            inner.pack_start(Gtk.Label(label="Rien de prévu dans les 14 prochains jours.", xalign=0), False, False, 0)
        else:
            day = None
            for e in data:
                d = e["start"].date()
                if d != day:
                    day = d
                    h = Gtk.Label(xalign=0)
                    h.set_markup("<b>%s</b>" % GLib.markup_escape_text(e["start"].strftime("%A %d %B")))
                    inner.pack_start(h, False, False, 6)
                when = "Journée entière" if e["all_day"] else "%s–%s" % (e["start"].strftime("%H:%M"), e["end"].strftime("%H:%M"))
                l = Gtk.Label(xalign=0)
                l.set_markup("%s   %s%s" % (when, GLib.markup_escape_text(e["title"]),
                                            ("  <small>📍 %s</small>" % GLib.markup_escape_text(e["location"])) if e["location"] else ""))
                l.set_line_wrap(True)
                l.set_selectable(True)
                inner.pack_start(l, False, False, 0)
        dlg.show_all()
        r = dlg.run()
        dlg.destroy()
        if r == 1:
            self.new_event_dialog()

    def new_event_dialog(self):
        dlg = Gtk.Dialog(title="Nouvel événement", transient_for=self, modal=True)
        dlg.add_buttons("Annuler", Gtk.ResponseType.CANCEL, "Ajouter", Gtk.ResponseType.OK)
        grid = Gtk.Grid(column_spacing=8, row_spacing=6)
        grid.set_border_width(14)
        now = datetime.datetime.now() + datetime.timedelta(hours=1)
        fields = {"title": Gtk.Entry(), "date": Gtk.Entry(), "time": Gtk.Entry(), "dur": Gtk.Entry(), "place": Gtk.Entry()}
        fields["date"].set_text(now.strftime("%Y-%m-%d"))
        fields["time"].set_text(now.strftime("%H:00"))
        fields["dur"].set_text("60")
        for i, (k, lab) in enumerate((("title", "Titre"), ("date", "Date (AAAA-MM-JJ)"), ("time", "Heure (HH:MM)"),
                                      ("dur", "Durée (minutes)"), ("place", "Lieu"))):
            grid.attach(Gtk.Label(label=lab, xalign=1), 0, i, 1, 1)
            fields[k].set_hexpand(True)
            grid.attach(fields[k], 1, i, 1, 1)
        dlg.get_content_area().pack_start(grid, True, True, 0)
        dlg.show_all()
        ok = dlg.run() == Gtk.ResponseType.OK
        vals = {k: w.get_text().strip() for k, w in fields.items()}
        dlg.destroy()
        if not ok:
            return
        try:
            start = datetime.datetime.fromisoformat("%sT%s" % (vals["date"], vals["time"]))
            end = start + datetime.timedelta(minutes=max(5, int(vals["dur"] or 60)))
        except ValueError:
            self.toast.popup("Date, heure ou durée invalide.", timeout=4)
            return
        self.calendar_add_event({"title": vals["title"] or "Rendez-vous", "start": start.strftime("%Y-%m-%dT%H:%M"),
                                 "end": end.strftime("%Y-%m-%dT%H:%M"), "location": vals["place"]})

    def _invite_conflicts(self, full):
        """À l'ouverture d'une invitation : prévient si le créneau est déjà pris dans Google Agenda."""
        inv = full.invite or {}
        if not (inv.get("start") and self._gcal_cfg()):
            return
        try:
            start = gcal._local_dt(inv["start"]).replace(tzinfo=None)
            end = gcal._local_dt(inv["end"]).replace(tzinfo=None) if inv.get("end") else start + datetime.timedelta(hours=1)
        except ValueError:
            return

        def work():
            ok, events = gcal.list_events(self._gcal_token(), start - datetime.timedelta(minutes=1), end + datetime.timedelta(minutes=1))
            return gcal.conflicts(events, start, end) if ok else None

        def done(clash, err):
            if err or clash is None or self.reader.msg is None or self.reader.msg.id != full.id:
                return
            if clash:
                e = clash[0]
                self.reader.set_invite_note("⚠ Conflit avec « %s » (%s–%s)%s" % (
                    e["title"][:40], e["start"].strftime("%H:%M"), e["end"].strftime("%H:%M"),
                    " et %d autre(s)" % (len(clash) - 1) if len(clash) > 1 else ""))
            else:
                self.reader.set_invite_note("✔ Vous êtes libre sur ce créneau (Google Agenda).")
        self.run_bg(work, done)

    # -------------------------------------------------------- recherche sur le serveur
    def search_server_now(self):
        text = self._effective_search()
        real = [a for a in self.accounts() if not a.get("demo")]
        if not text or not real:
            self.toast.popup("Saisissez d'abord une recherche (compte réel requis).", timeout=3)
            return
        self.srv_btn.set_sensitive(False)
        self.toast.popup("Recherche sur le serveur…", timeout=3)
        logicals = ["inbox", "sent", "archive"]
        if self.view.startswith("f:"):
            logicals.append(self.view)

        def work():
            found = 0
            for a in real:
                known = {f: set(self.cache.uids(a["id"], f)) for f in logicals}
                msgs = self.backend(a["id"]).search_server(text, logicals, known)
                if msgs:
                    self.cache.upsert_many(msgs)
                    found += len(msgs)
            return found

        def done(n, err):
            self.srv_btn.set_sensitive(True)
            if err:
                self.toast.popup("Recherche serveur : %s" % str(err)[:90], timeout=6)
                return
            self.toast.popup("%d message(s) supplémentaire(s) trouvé(s) sur le serveur" % n if n else "Rien de plus sur le serveur.", timeout=4)
            self.reload_list(full=True)
        self.run_bg(work, done)

    # ------------------------------------------------------------------ apprentissage
    def _learn_move(self, msgs, dest, path):
        """Retient où l'utilisateur range ses messages ; au 3e rangement identique, propose une règle automatique."""
        if not (dest or "").startswith("f:") or not path:
            return
        proposed = False
        for m in msgs:
            n = self.cache.learn_record(m.account, m.sender_email.lower(), path)
            if n == 3 and not proposed and not any(r.get("action") == "move" and r.get("text", "").lower() == m.sender_email.lower()
                                                   for r in self.config["rules"]):
                proposed = True
                self.toast.popup("Vous rangez souvent %s dans « %s »." % (m.sender_email, path), "Créer la règle",
                                 lambda m=m, p=path: self.ai_rule_move(m, p), timeout=10)

    # ---------------------------------------------------------------- carnet d'adresses
    def contacts_refresh(self):
        """Recopie les fiches manuelles (synchronisées) dans la base locale puis ajoute les correspondants récents."""
        def work():
            for email, c in (self.config.get("contacts") or {}).items():
                self.cache.contact_upsert(email, c.get("name", ""), c.get("phone", ""), c.get("org", ""), c.get("notes", ""), source="manual")
            self.cache.contacts_rebuild()
        threading.Thread(target=work, daemon=True).start()

    def contact_save(self, email, name="", phone="", org="", notes=""):
        email = (email or "").strip().lower()
        if "@" not in email or len(email) > 200:
            return False
        c = {"name": name.strip()[:200], "phone": phone.strip()[:60], "org": org.strip()[:120], "notes": notes.strip()[:500]}
        contacts = dict(self.config.get("contacts") or {})
        contacts[email] = c
        self.config["contacts"] = contacts
        self.config.save()
        self.cache.contact_upsert(email, c["name"], c["phone"], c["org"], c["notes"], source="manual")
        return True

    def contact_remove(self, email):
        contacts = dict(self.config.get("contacts") or {})
        contacts.pop(email.lower(), None)
        self.config["contacts"] = contacts
        self.config.save()
        self.cache.contact_delete(email)

    def contact_add(self, msg):
        if self.contact_save(msg.sender_email, msg.sender_name):
            self.toast.popup("%s ajouté aux contacts" % (msg.sender_name or msg.sender_email), timeout=3)

    # ---------------------------------------------------------------- boîte d'envoi
    def show_outbox(self):
        """Messages programmés ou en attente de réseau : envoyer maintenant ou annuler."""
        import time as _t
        items = self.cache.outbox_list()
        dlg = Gtk.Dialog(title="Boîte d'envoi", transient_for=self, modal=True)
        dlg.add_button("Fermer", Gtk.ResponseType.CLOSE)
        dlg.set_default_size(560, 360)
        box = dlg.get_content_area()
        box.set_border_width(14)
        box.set_spacing(8)
        if not items:
            box.pack_start(Gtk.Label(label="Aucun message en attente."), True, True, 0)
        for oid, at, out, tries in items:
            row = Gtk.Box(spacing=8)
            when = "dès que possible" if at <= _t.time() else _t.strftime("%d/%m %H:%M", _t.localtime(at))
            lab = Gtk.Label(xalign=0)
            lab.set_markup("<b>%s</b>\nÀ : %s · prévu %s%s" % (
                GLib.markup_escape_text(out.subject[:60]), GLib.markup_escape_text(out.to[:60]), when,
                (" · %d tentative(s)" % tries) if tries else ""))
            lab.set_ellipsize(3)
            now_b, del_b = Gtk.Button(label="Envoyer maintenant"), Gtk.Button(label="Annuler l'envoi")

            def send_now(_b, oid=oid):
                self.cache.outbox_reschedule(oid, _t.time() - 1)
                self.process_outbox()
                dlg.destroy()

            def cancel(_b, oid=oid, row=row):
                self.cache.outbox_remove(oid)
                row.destroy()
                self.update_offline_status()
            now_b.connect("clicked", send_now)
            del_b.connect("clicked", cancel)
            row.pack_start(lab, True, True, 0)
            row.pack_start(now_b, False, False, 0)
            row.pack_start(del_b, False, False, 0)
            box.pack_start(row, False, False, 0)
        box.pack_end(Gtk.Label(label="Les messages programmés partent aussi fenêtre fermée (minuterie utilisateur « mintmail-outbox »).",
                               xalign=0), False, False, 0)
        dlg.show_all()
        dlg.run()
        dlg.destroy()

    # ------------------------------------------------------------------------ tâches
    def tasks_all(self):
        return list(self.config.get("tasks") or [])

    def task_add(self, text, msg=None, due=None):
        """Ajoute une tâche (échéance lue dans le texte si non précisée). Retourne la tâche, ou None si elle existe déjà."""
        text = re.sub(r"\s+", " ", text or "").strip()[:300]
        if not text:
            return None
        mid = msg.id if msg is not None else ""
        if any(t["text"] == text and t.get("msg", "") == mid and not t.get("done") for t in self.tasks_all()):
            return None
        d = tk.parse_due(text) if due is None else due
        task = {"id": uuid.uuid4().hex[:12], "text": text, "due": d.isoformat() if d else "", "done": False, "msg": mid,
                "account": (msg.account if msg is not None else "")[:40], "created": time.time()}
        self.config["tasks"] = self.tasks_all() + [task]
        self.config.save()
        return task

    def task_set_done(self, tid, done=True):
        self.config["tasks"] = [dict(t, done=bool(done)) if t["id"] == tid else t for t in self.tasks_all()]
        self.config.save()

    def task_remove(self, tid):
        self.config["tasks"] = [t for t in self.tasks_all() if t["id"] != tid]
        self.config.save()

    def tasks_from_message(self, msg):
        """Ajoute les tâches détectées par l'analyse IA du message (une seule fois chacune)."""
        ana = self.cache.ai_get(msg.id, "analysis") or {}
        added = [t for t in (self.task_add(x, msg) for x in ana.get("tasks", [])) if t]
        self.toast.popup("%d tâche(s) ajoutée(s)" % len(added) if added else "Ces tâches sont déjà dans votre liste.", timeout=4)
        return added

    def task_add_dialog(self, msg=None):
        dlg = Gtk.Dialog(title="Ajouter une tâche", transient_for=self, modal=True)
        dlg.add_buttons("Annuler", Gtk.ResponseType.CANCEL, "Ajouter", Gtk.ResponseType.OK)
        grid = Gtk.Grid(column_spacing=8, row_spacing=6)
        grid.set_border_width(14)
        text, due = Gtk.Entry(), Gtk.Entry()
        text.set_width_chars(46)
        if msg is not None:
            text.set_text(("Répondre à %s : %s" % (msg.display_sender, msg.subject))[:200])
        due.set_placeholder_text("facultatif : vendredi, 15/11, dans 3 jours… (sinon lue dans le texte)")
        for i, (lab, w) in enumerate((("Tâche", text), ("Échéance", due))):
            grid.attach(Gtk.Label(label=lab, xalign=1), 0, i, 1, 1)
            w.set_hexpand(True)
            grid.attach(w, 1, i, 1, 1)
        dlg.get_content_area().pack_start(grid, True, True, 0)
        dlg.show_all()
        ok = dlg.run() == Gtk.ResponseType.OK
        t, d = text.get_text(), due.get_text().strip()
        dlg.destroy()
        if not ok or not t.strip():
            return None
        parsed = tk.parse_due(d) if d else None
        if d and parsed is None:
            self.toast.popup("Échéance non comprise : la tâche est ajoutée sans date.", timeout=5)
        task = self.task_add(t, msg, due=parsed if d else None)
        self.toast.popup("Tâche ajoutée%s" % ((" — échéance " + task["due"]) if task and task["due"] else "") if task else
                         "Cette tâche existe déjà.", timeout=4)
        return task

    # ---------------------------------------------------------- page « Aujourd'hui »
    def today_local(self, now=None):
        """Ce qui compte aujourd'hui, côté local : messages importants non lus, relances, tâches ouvertes, brouillons préparés."""
        now = now or datetime.datetime.now()
        inbox = self.cache.query("inbox", "all", unread_only=True, limit=200)
        meta = self.cache.ai_meta([m.id for m in inbox])
        important = [m for m in inbox if meta.get(m.id, {}).get("priority") == 3 and not meta[m.id].get("spam")][:8]
        follow = sorted(self.config.get("followups", []), key=lambda f: f["at"])
        open_tasks = sorted([t for t in self.tasks_all() if not t.get("done")], key=tk.sort_key)
        drafts = [m for m in self.cache.query("drafts", "all", limit=100) if m.id.startswith("draft-ai-")][:5]
        return {"important": important, "followups": follow, "tasks": open_tasks, "drafts": drafts, "now": now}

    def agenda_today(self):
        start = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        return gcal.list_events(self._gcal_token(), start, start + datetime.timedelta(days=1))

    def show_today(self):
        if self._gcal_cfg():
            self.run_bg(self.agenda_today, lambda res, err: self._today_dialog(res if res else (False, str(err))))
        else:
            self._today_dialog(None)

    def _today_dialog(self, agenda):
        dlg = Gtk.Dialog(title="Aujourd'hui — %s" % datetime.date.today().strftime("%d/%m/%Y"), transient_for=self, modal=True)
        dlg.add_button("Fermer", Gtk.ResponseType.CLOSE)
        dlg.set_default_size(620, 640)
        outer = dlg.get_content_area()
        outer.set_border_width(14)
        sw = Gtk.ScrolledWindow()
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        sw.add(inner)
        outer.pack_start(sw, True, True, 0)
        chosen = []

        def head(text):
            h = Gtk.Label(xalign=0)
            h.set_markup("<b>%s</b>" % GLib.markup_escape_text(text))
            inner.pack_start(h, False, False, 8)

        def line(text, dim=False):
            l = Gtk.Label(label=text, xalign=0)
            l.set_line_wrap(True)
            l.set_selectable(True)
            if dim:
                l.get_style_context().add_class("dim")
            inner.pack_start(l, False, False, 0)

        def msg_button(m, prefix=""):
            b = Gtk.Button(label="%s%s — %s" % (prefix, m.display_sender, m.subject)[:110], relief=Gtk.ReliefStyle.NONE)
            b.get_child().set_xalign(0)
            b.connect("clicked", lambda *_: (chosen.append(m), dlg.response(Gtk.ResponseType.CLOSE)))
            inner.pack_start(b, False, False, 0)

        def fill():
            for ch in inner.get_children():
                inner.remove(ch)
            data = self.today_local()
            head("📅 Agenda du jour")
            if agenda is None:
                line("Activez Google Agenda (Paramètres → Agenda) pour voir vos rendez-vous ici.", dim=True)
            elif not agenda[0]:
                line("Google Agenda : %s" % agenda[1], dim=True)
            elif not agenda[1]:
                line("Aucun rendez-vous aujourd'hui.", dim=True)
            else:
                for e in agenda[1]:
                    when = "Journée entière" if e["all_day"] else "%s–%s" % (e["start"].strftime("%H:%M"), e["end"].strftime("%H:%M"))
                    line("%s   %s%s" % (when, e["title"], ("   📍 " + e["location"]) if e["location"] else ""))
            head("⚡ À traiter en priorité (non lus, jugés importants)")
            if data["important"]:
                for m in data["important"]:
                    msg_button(m)
            else:
                line("Rien d'urgent détecté." + ("" if self.engine.enabled() else " (L'IA n'est pas activée : le tri se limite à des indices simples.)"), dim=True)
            head("☑ Tâches")
            if data["tasks"]:
                for t in data["tasks"]:
                    row = Gtk.Box(spacing=8)
                    cb = Gtk.CheckButton(label=t["text"][:90])
                    cb.connect("toggled", lambda w, tid=t["id"]: (self.task_set_done(tid, w.get_active()), fill()))
                    row.pack_start(cb, True, True, 0)
                    lab = tk.due_label(t)
                    if lab:
                        l = Gtk.Label(xalign=1)
                        l.set_markup("<span foreground='%s'>%s</span>" % ("#dc2626" if tk.is_overdue(t) else "#888888", GLib.markup_escape_text(lab)))
                        row.pack_end(l, False, False, 0)
                    if t.get("msg"):
                        ob = Gtk.Button(label="✉", relief=Gtk.ReliefStyle.NONE)
                        ob.set_tooltip_text("Ouvrir le message d'origine")
                        ob.connect("clicked", lambda _b, mid=t["msg"]: self.cache.get(mid) and (chosen.append(self.cache.get(mid)), dlg.response(Gtk.ResponseType.CLOSE)))
                        row.pack_end(ob, False, False, 0)
                    inner.pack_start(row, False, False, 0)
            else:
                line("Aucune tâche ouverte.", dim=True)
            addrow = Gtk.Box(spacing=6)
            entry = Gtk.Entry()
            entry.set_placeholder_text("Nouvelle tâche (ex. « envoyer le devis avant vendredi »)")

            def add(*_):
                if entry.get_text().strip():
                    self.task_add(entry.get_text())
                    fill()
            entry.connect("activate", add)
            b = Gtk.Button(label="Ajouter")
            b.connect("clicked", add)
            addrow.pack_start(entry, True, True, 0)
            addrow.pack_start(b, False, False, 0)
            inner.pack_start(addrow, False, False, 4)
            head("⏳ En attente de réponse")
            now_ts = time.time()
            if data["followups"]:
                for f in data["followups"][:8]:
                    n = (f["at"] - now_ts) / 86400
                    line("« %s » — %s  (%s)" % (f["subject"][:60], f["to"][:40], "relance échue" if n <= 0 else "relance dans %d j" % int(n + 0.5)))
            else:
                line("Aucune relance programmée.", dim=True)
            if data["drafts"]:
                head("✨ Brouillons de réponse préparés (à relire avant envoi)")
                for m in data["drafts"]:
                    msg_button(m, "Re : ")
            inner.show_all()
        fill()
        dlg.show_all()
        dlg.run()
        dlg.destroy()
        if chosen:
            m = chosen[0]
            if m.folder == "drafts":
                self.open_draft(m)
            else:
                self.open_message(self.cache.get(m.id) or m, force=True)

    # ----------------------------------------------------------- créneaux d'après l'agenda
    def propose_slots(self, msg, minutes=60):
        """Ouvre une réponse contenant 3 créneaux libres (Google Agenda : jours ouvrables, 9h00-17h30, à partir de dans 2 h)."""
        if not self._gcal_cfg():
            self.toast.popup("Activez Google Agenda pour proposer des créneaux : Paramètres → Agenda.", timeout=5)
            self.show_settings("calendar")
            return
        self.toast.popup("Recherche de créneaux libres…", timeout=3)

        def work():
            now = datetime.datetime.now()
            ok, events = gcal.list_events(self._gcal_token(), now, now + datetime.timedelta(days=15))
            if not ok:
                raise oauth.OAuthError(events)
            return slots.free_slots(events, now, duration=minutes)

        def done(found, err):
            if err:
                self.toast.popup("Agenda : %s" % str(err)[:100], timeout=6)
            elif not found:
                self.toast.popup("Aucun créneau libre trouvé dans les 15 prochains jours.", timeout=5)
            else:
                self.reply(msg, ai_text=slots.proposal_text(found))
        self.run_bg(work, done)

    # ------------------------------------------------------ brouillons de réponse préparés
    _preparing = False

    def _maybe_prepare_drafts(self, msgs, res):
        """Brouillons de réponse (optionnel, jamais envoyés) pour les messages que l'IA juge importants ET attendant une réponse."""
        if self._preparing or not self.config.get("ai_prepare_drafts") or not self.engine.enabled():
            return
        cutoff = time.time() - 3 * 86400
        todo = []
        for m in msgs:
            v = res.get(m.id, {})
            if (m.folder == "inbox" and m.date > cutoff and v.get("reply_needed") and not v.get("local") and not v.get("spam")
                    and v.get("priority", 0) >= 2 and v.get("category") in (None, "people") and not self.cache.ai_get(m.id, "prepared")):
                todo.append(m)
        todo = todo[:3]
        if not todo:
            return
        self._preparing = True

        def work():
            out = []
            for m in todo:
                full = self.cache.get(m.id) or m
                examples = []
                for s in self.cache.query("sent", m.account, limit=6):
                    body = (self.cache.get(s.id) or s).text or ""
                    if body.strip():
                        examples.append(re.sub(r"\n{3,}", "\n\n", body.strip())[:400])
                try:
                    text = self.engine.prepare_reply(full, examples).strip()
                except Exception:
                    continue
                if text:
                    out.append((full, text))
            return out

        def done(res2, err):
            self._preparing = False
            made = 0
            for full, text in res2 or []:
                acc = next((a for a in self.accounts() if a["id"] == full.account), {})
                ident = self._addressed_identity(full)
                sig = (ident or {}).get("signature_html") or acc.get("signature_html", "")
                did = "draft-ai-" + hashlib.sha1(full.id.encode("utf-8")).hexdigest()[:12]
                self.cache.upsert(Message(
                    id=did, account=full.account, folder="drafts", uid=0, sender_name=acc.get("name", ""), sender_email=acc.get("email", ""),
                    to=(full.reply_to or full.sender_email), subject="Re: " + normalize_subject(full.subject), date=time.time(),
                    snippet=("✨ " + text)[:150], text=text, unread=False, message_id=full.message_id, references=full.references,
                    html=text_to_html(text) + ("<br><br>-- <br>" + sig if sig.strip() else "")))
                self.cache.ai_set(full.id, "prepared", {"draft": did})
                made += 1
            if made:
                self.reload_list()
                self.update_counts()
                self.toast.popup("✨ %d brouillon(s) de réponse prêt(s) dans Brouillons — à relire avant envoi" % made, timeout=8)
        self.run_bg(work, done)
