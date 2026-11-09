"""Conversations, désabonnement en un clic, invitations, recherche sur le serveur, apprentissage, carnet d'adresses."""
import os
import tempfile
import threading

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib, Gtk

import datetime

from . import caldav, gcal, ical, oauth, unsub
from .ai_engine import make_ics
from .models import Outgoing
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
