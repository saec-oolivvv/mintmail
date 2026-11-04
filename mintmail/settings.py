import threading

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, GLib

from .backend import PRESETS, make_backend, new_account_id
from .reader import WebKit2, HAS_WEBKIT

SHORTCUTS = [
    ("C", "Nouveau message"), ("R", "Répondre"), ("A", "Répondre à tous"), ("F", "Transférer"),
    ("E", "Archiver"), ("# / Suppr", "Supprimer"), ("S", "Favori"), ("P", "Épingler"),
    ("U", "Marquer lu / non lu"), ("H", "Reporter à demain 8 h"), ("J / K", "Message suivant / précédent"),
    ("/  ou  Ctrl+F", "Rechercher"), ("Ctrl+K", "Palette de commandes"), ("Ctrl+A", "Tout sélectionner"),
    ("Ctrl+R", "Actualiser"), ("Échap", "Annuler la sélection / la recherche"),
]
SIG_TEMPLATE = ('<p><b>Prénom Nom</b><br>Fonction — Société<br>'
                '📞 +32 000 00 00 00 · ✉ vous@exemple.be<br>'
                '<a href="https://exemple.be">exemple.be</a></p>')


def _row(grid, i, label, widget):
    l = Gtk.Label(label=label, xalign=1)
    l.get_style_context().add_class("dim")
    widget.set_hexpand(True)
    grid.attach(l, 0, i, 1, 1)
    grid.attach(widget, 1, i, 1, 1)


class SettingsWindow(Gtk.Window):
    def __init__(self, win):
        super().__init__(title="Paramètres de MintMail")
        self.win, self.cfg = win, win.config
        self.set_transient_for(win)
        self.set_default_size(820, 560)
        self.current = None
        stack = Gtk.Stack()
        stack.add_titled(self._accounts_page(), "accounts", "Comptes")
        stack.add_titled(self._signature_page(), "sig", "Signatures")
        stack.add_titled(self._appearance_page(), "look", "Apparence")
        stack.add_titled(self._shortcuts_page(), "keys", "Raccourcis")
        side = Gtk.StackSidebar()
        side.set_stack(stack)
        box = Gtk.Box()
        box.pack_start(side, False, False, 0)
        box.pack_start(stack, True, True, 0)
        self.add(box)
        self._reload_accounts()
        self.show_all()

    # ------------------------------------------------------------ comptes
    def _accounts_page(self):
        page = Gtk.Box(spacing=12)
        page.set_border_width(14)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.acc_list = Gtk.ListBox()
        self.acc_list.connect("row-selected", self._acc_selected)
        sw = Gtk.ScrolledWindow()
        sw.set_size_request(200, -1)
        sw.add(self.acc_list)
        left.pack_start(sw, True, True, 0)
        add = Gtk.Button(label="＋ Ajouter un compte")
        add.connect("clicked", self._add_account)
        left.pack_start(add, False, False, 0)
        page.pack_start(left, False, False, 0)

        grid = Gtk.Grid(column_spacing=8, row_spacing=6)
        self.f_preset = Gtk.ComboBoxText()
        for k in PRESETS:
            self.f_preset.append_text(k)
        self.f_preset.connect("changed", self._preset)
        self.f_name, self.f_email = Gtk.Entry(), Gtk.Entry()
        self.f_user, self.f_pass = Gtk.Entry(), Gtk.Entry()
        self.f_pass.set_visibility(False)
        self.f_ihost, self.f_iport = Gtk.Entry(), Gtk.Entry()
        self.f_shost, self.f_sport = Gtk.Entry(), Gtk.Entry()
        self.f_ssl = Gtk.CheckButton(label="IMAP en SSL/TLS direct (port 993)")
        self.f_ssl.set_active(True)
        for i, (lab, w) in enumerate((("Fournisseur", self.f_preset), ("Nom affiché", self.f_name),
                                      ("Adresse e-mail", self.f_email), ("Identifiant", self.f_user),
                                      ("Mot de passe", self.f_pass), ("Serveur IMAP", self.f_ihost),
                                      ("Port IMAP", self.f_iport), ("Serveur SMTP", self.f_shost),
                                      ("Port SMTP", self.f_sport))):
            _row(grid, i, lab, w)
        grid.attach(self.f_ssl, 1, 9, 1, 1)
        btns = Gtk.Box(spacing=6)
        test = Gtk.Button(label="Tester la connexion")
        test.connect("clicked", self._test)
        save = Gtk.Button(label="Enregistrer")
        save.get_style_context().add_class("suggested-action")
        save.connect("clicked", self._save_account)
        rm = Gtk.Button(label="Supprimer ce compte")
        rm.connect("clicked", self._remove_account)
        for b in (test, save, rm):
            btns.pack_start(b, False, False, 0)
        grid.attach(btns, 1, 10, 1, 1)
        self.status = Gtk.Label(xalign=0)
        self.status.set_line_wrap(True)
        grid.attach(self.status, 1, 11, 1, 1)
        note = Gtk.Label(xalign=0, label="Gmail / Yahoo / iCloud : créez un « mot de passe d'application » dans les "
                                         "paramètres de sécurité du compte.")
        note.set_line_wrap(True)
        note.get_style_context().add_class("dim")
        grid.attach(note, 1, 12, 1, 1)
        page.pack_start(grid, True, True, 0)
        return page

    def _reload_accounts(self, select=None):
        for ch in self.acc_list.get_children():
            self.acc_list.remove(ch)
        for a in self.cfg["accounts"]:
            r = Gtk.ListBoxRow()
            r.acc = a
            l = Gtk.Label(label=a.get("name") or a["email"], xalign=0)
            l.set_border_width(8)
            r.add(l)
            self.acc_list.add(r)
            if select and a["id"] == select:
                self.acc_list.select_row(r)
        self.acc_list.show_all()
        self._fill_sig_combo()
        if not select and self.acc_list.get_children():
            self.acc_list.select_row(self.acc_list.get_row_at_index(0))
        elif not self.cfg["accounts"]:
            self._acc_selected(None, None)

    def _acc_selected(self, _lb, row):
        a = getattr(row, "acc", None) if row else None
        self.current = dict(a) if a else {"id": new_account_id()}
        a = self.current
        self.f_name.set_text(a.get("name", ""))
        self.f_email.set_text(a.get("email", ""))
        self.f_user.set_text(a.get("username", ""))
        self.f_pass.set_text(self.cfg.password(a["id"]) if a.get("email") else "")
        self.f_ihost.set_text(a.get("imap_host", ""))
        self.f_iport.set_text(str(a.get("imap_port", 993)))
        self.f_shost.set_text(a.get("smtp_host", ""))
        self.f_sport.set_text(str(a.get("smtp_port", 587)))
        self.f_ssl.set_active(a.get("imap_ssl", True))
        self.status.set_text("")

    def _add_account(self, *_):
        self.acc_list.unselect_all()
        self._acc_selected(None, None)
        self.f_preset.set_active(0)
        self.f_email.grab_focus()

    def _preset(self, combo):
        p = PRESETS.get(combo.get_active_text() or "")
        if p:
            self.f_ihost.set_text(p["imap_host"])
            self.f_iport.set_text(str(p["imap_port"]))
            self.f_shost.set_text(p["smtp_host"])
            self.f_sport.set_text(str(p["smtp_port"]))

    def _collect(self):
        a = dict(self.current)
        try:
            ip, sp = int(self.f_iport.get_text()), int(self.f_sport.get_text())
        except ValueError:
            self.status.set_text("Les ports doivent être des nombres.")
            return None
        a.update(name=self.f_name.get_text().strip(), email=self.f_email.get_text().strip(),
                 username=self.f_user.get_text().strip(), imap_host=self.f_ihost.get_text().strip(),
                 imap_port=ip, smtp_host=self.f_shost.get_text().strip(), smtp_port=sp,
                 imap_ssl=self.f_ssl.get_active())
        a.pop("demo", None)
        if "@" not in a["email"] or not a["imap_host"] or not a["smtp_host"]:
            self.status.set_text("Adresse e-mail et serveurs requis.")
            return None
        return a

    def _test(self, *_):
        a = self._collect()
        if not a:
            return
        self.status.set_text("Test en cours…")
        pw = self.f_pass.get_text()
        class _C:  # config minimale pour make_backend
            def password(self_, _id): return pw
        be = make_backend(a, _C())

        def work():
            err = be.test()
            GLib.idle_add(lambda: self.status.set_text("✅ Connexion réussie (IMAP + SMTP)." if not err else "❌ " + err))
        threading.Thread(target=work, daemon=True).start()

    def _save_account(self, *_):
        a = self._collect()
        if not a:
            return
        self.cfg.set_password(a["id"], self.f_pass.get_text())
        accs = [x for x in self.cfg["accounts"] if x["id"] != a["id"]]
        old = next((x for x in self.cfg["accounts"] if x["id"] == a["id"]), {})
        a["signature_html"] = old.get("signature_html", "")
        accs.append(a)
        self.cfg["accounts"] = accs
        self.cfg.save()
        self.win.accounts_changed()
        self._reload_accounts(select=a["id"])
        self.status.set_text("Compte enregistré. Synchronisation en cours…")

    def _remove_account(self, *_):
        aid = self.current.get("id")
        if aid and any(x["id"] == aid for x in self.cfg["accounts"]):
            self.cfg["accounts"] = [x for x in self.cfg["accounts"] if x["id"] != aid]
            self.cfg.save()
            self.win.cache.delete_account(aid)
            self.win.accounts_changed()
            self._reload_accounts()

    # --------------------------------------------------------- signatures
    def _signature_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        page.set_border_width(14)
        top = Gtk.Box(spacing=8)
        top.pack_start(Gtk.Label(label="Compte :"), False, False, 0)
        self.sig_combo = Gtk.ComboBoxText()
        self.sig_combo.connect("changed", self._sig_account)
        top.pack_start(self.sig_combo, False, False, 0)
        tpl = Gtk.Button(label="Insérer un modèle")
        tpl.connect("clicked", lambda *_: self.sig_buf.set_text(SIG_TEMPLATE))
        top.pack_start(tpl, False, False, 0)
        save = Gtk.Button(label="Enregistrer la signature")
        save.get_style_context().add_class("suggested-action")
        save.connect("clicked", self._sig_save)
        top.pack_end(save, False, False, 0)
        page.pack_start(top, False, False, 0)
        page.pack_start(Gtk.Label(label="Signature HTML (balises <b>, <a>, <img>… autorisées) :", xalign=0), False, False, 0)
        self.sig_view = Gtk.TextView()
        self.sig_view.set_monospace(True)
        self.sig_buf = self.sig_view.get_buffer()
        self.sig_buf.connect("changed", self._sig_preview)
        sw = Gtk.ScrolledWindow()
        sw.set_size_request(-1, 150)
        sw.add(self.sig_view)
        page.pack_start(sw, False, True, 0)
        page.pack_start(Gtk.Label(label="Aperçu :", xalign=0), False, False, 0)
        if HAS_WEBKIT:
            s = WebKit2.Settings()
            s.set_enable_javascript(False)
            self.sig_web = WebKit2.WebView.new_with_settings(s)
            frame = Gtk.Frame()
            frame.add(self.sig_web)
            page.pack_start(frame, True, True, 0)
        else:
            self.sig_web = None
        return page

    def _fill_sig_combo(self):
        self.sig_combo.remove_all()
        for a in self.cfg["accounts"]:
            self.sig_combo.append(a["id"], a.get("name") or a["email"])
        if self.cfg["accounts"]:
            self.sig_combo.set_active(0)
        else:
            self.sig_buf.set_text("")

    def _sig_account(self, *_):
        a = next((x for x in self.cfg["accounts"] if x["id"] == self.sig_combo.get_active_id()), None)
        self.sig_buf.set_text(a.get("signature_html", "") if a else "")

    def _sig_preview(self, *_):
        if self.sig_web:
            h = self.sig_buf.get_text(self.sig_buf.get_start_iter(), self.sig_buf.get_end_iter(), False)
            self.sig_web.load_html("<body style='font-family:sans-serif;font-size:14px'>%s</body>" % h, "about:blank")

    def _sig_save(self, *_):
        a = next((x for x in self.cfg["accounts"] if x["id"] == self.sig_combo.get_active_id()), None)
        if a:
            a["signature_html"] = self.sig_buf.get_text(self.sig_buf.get_start_iter(), self.sig_buf.get_end_iter(), False)
            self.cfg.save()
            self.win.toast.popup("Signature enregistrée", timeout=3)

    # --------------------------------------------------------- apparence
    def _appearance_page(self):
        grid = Gtk.Grid(column_spacing=12, row_spacing=10)
        grid.set_border_width(18)
        theme = Gtk.ComboBoxText()
        for k, v in (("system", "Système"), ("light", "Clair"), ("dark", "Sombre")):
            theme.append(k, v)
        theme.set_active_id(self.cfg["theme"])
        theme.connect("changed", lambda c: self._set("theme", c.get_active_id()))
        dens = Gtk.ComboBoxText()
        for k, v in (("compact", "Compacte"), ("comfortable", "Confortable"), ("spacious", "Aérée")):
            dens.append(k, v)
        dens.set_active_id(self.cfg["density"])
        dens.connect("changed", lambda c: self._set("density", c.get_active_id()))
        color = Gtk.ColorButton()
        rgba = Gdk.RGBA()
        rgba.parse(self.cfg["accent"])
        color.set_rgba(rgba)
        color.connect("color-set", lambda b: self._set("accent", self._hex(b.get_rgba())))
        imgs = Gtk.Switch()
        imgs.set_active(self.cfg["load_images"])
        imgs.connect("notify::active", lambda s, _p: self._set("load_images", s.get_active()))
        notif = Gtk.Switch()
        notif.set_active(self.cfg["notifications"])
        notif.connect("notify::active", lambda s, _p: self._set("notifications", s.get_active()))
        refresh = Gtk.SpinButton.new_with_range(1, 60, 1)
        refresh.set_value(self.cfg["refresh_minutes"])
        refresh.connect("value-changed", lambda s: self._set("refresh_minutes", int(s.get_value())))
        undo = Gtk.SpinButton.new_with_range(3, 30, 1)
        undo.set_value(self.cfg["undo_seconds"])
        undo.connect("value-changed", lambda s: self._set("undo_seconds", int(s.get_value())))
        for i, (lab, w) in enumerate((("Thème", theme), ("Densité de la liste", dens), ("Couleur d'accent", color),
                                      ("Charger les images distantes", imgs), ("Notifications de bureau", notif),
                                      ("Actualiser toutes les (min)", refresh), ("Délai d'annulation d'envoi (s)", undo))):
            l = Gtk.Label(label=lab, xalign=1)
            w.set_halign(Gtk.Align.START)
            grid.attach(l, 0, i, 1, 1)
            grid.attach(w, 1, i, 1, 1)
        return grid

    @staticmethod
    def _hex(c):
        return "#%02x%02x%02x" % (int(c.red * 255), int(c.green * 255), int(c.blue * 255))

    def _set(self, key, val):
        self.cfg[key] = val
        self.cfg.save()
        self.win.apply_settings()

    def _shortcuts_page(self):
        grid = Gtk.Grid(column_spacing=24, row_spacing=6)
        grid.set_border_width(18)
        for i, (k, d) in enumerate(SHORTCUTS):
            kl = Gtk.Label(xalign=1)
            kl.set_markup("<tt><b>%s</b></tt>" % GLib.markup_escape_text(k))
            grid.attach(kl, 0, i, 1, 1)
            grid.attach(Gtk.Label(label=d, xalign=0), 1, i, 1, 1)
        sw = Gtk.ScrolledWindow()
        sw.add(grid)
        return sw
