import re
import threading

import gi
from . import i18n
from .updates_ui import updates_page
from .i18n import tr
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, GLib

from .backend import PRESETS, make_backend, new_account_id
from .reader import WebKit2, HAS_WEBKIT
from .settings_extra import (gestures_page, filters_page, templates_page,
                              p2p_page, help_page)
from .widgets import icon
from .style import ACCENTS, STYLES
from .ai_service import AIService, AIServiceError, DEFAULT_API_BASE, DEFAULT_MODEL, PROVIDERS, is_local_endpoint, list_models
from .settings_more import OAuthMixin, calendar_page, contacts_page, identities_page

SHORTCUTS = [
    ("C", tr("Nouveau message")), ("R", tr("Répondre")), ("A", tr("Répondre à tous")), ("F", tr("Transférer")),
    ("E", tr("Archiver")), (tr("# / Suppr"), tr("Supprimer")), ("S", tr("Favori")), ("P", tr("Épingler")),
    ("U", tr("Marquer lu / non lu")), ("H", tr("Reporter à demain 8 h")), ("J / K", tr("Message suivant / précédent")),
    (tr("/  ou  Ctrl+F"), tr("Rechercher")), ("Ctrl+K", tr("Palette de commandes")), ("Ctrl+A", tr("Tout sélectionner")),
    ("!", tr("Signaler comme spam")), ("B", tr("Menu Bloquer (adresse / domaine)")), ("\\", tr("Basculer colonnes / liste seule")), ("X", tr("Mode sélection")),
    ("Ctrl+J", tr("Assistant IA")), ("F11", tr("Plein écran")), (tr("? … (recherche)"), tr("Poser une question à l'IA")),
    ("Ctrl+,", tr("Ouvrir les paramètres")), ("Ctrl+R", tr("Actualiser")), (tr("Échap"), tr("Annuler la sélection / la recherche")),
    ("V", tr("Déplacer vers un dossier")), ("T", tr("Aujourd'hui (agenda, priorités, tâches)")), ("Ctrl+N", tr("Nouveau message")), (tr("Ctrl+Maj+,"), tr("Paramètres dans une fenêtre séparée")), ("F1", tr("Aide")),
]
SIG_TEMPLATE = (tr('<p><b>Prénom Nom</b><br>Fonction — Société<br>'
                '📞 +32 000 00 00 00 · ✉ vous@exemple.be<br>'
                '<a href="https://exemple.be">exemple.be</a></p>'))


def _row(grid, i, label, widget):
    l = Gtk.Label(label=label, xalign=1)
    l.get_style_context().add_class("dim")
    widget.set_hexpand(True)
    grid.attach(l, 0, i, 1, 1)
    grid.attach(widget, 1, i, 1, 1)


# noms des fournisseurs affichés (les clés de PRESETS restent des identifiants stables)
PRESET_LABELS = {
    "Gmail — connexion Google (OAuth, sans mot de passe)": tr("Gmail — connexion Google (OAuth, sans mot de passe)"),
    "Outlook / Microsoft 365 — connexion Microsoft (OAuth)": tr("Outlook / Microsoft 365 — connexion Microsoft (OAuth)"),
    "Gmail (mot de passe d'application)": tr("Gmail (mot de passe d'application)"),
    "Autre (manuel)": tr("Autre (manuel)"),
}


class SettingsPage(OAuthMixin, Gtk.Box):
    """Page des paramètres, affichée dans la fenêtre principale (retour : bouton, Échap)."""

    def __init__(self, win, page=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.win, self.cfg = win, win.config
        self.get_style_context().add_class("settings-page")
        self.current = None
        top = Gtk.Box(spacing=12)
        top.set_border_width(12)
        back = Gtk.Button()
        bb = Gtk.Box(spacing=6)
        bb.pack_start(icon("go-previous-symbolic"), False, False, 0)
        bb.pack_start(Gtk.Label(label=tr("Retour")), False, False, 0)
        back.add(bb)
        back.get_style_context().add_class("pill")
        back.connect("clicked", lambda *_: self.win.close_settings())
        ttl = Gtk.Label(label=tr("Paramètres"), xalign=0)
        ttl.get_style_context().add_class("list-title")
        top.pack_start(back, False, False, 0)
        top.pack_start(ttl, True, True, 0)
        hint = Gtk.Label(label=tr("Échap pour revenir · Ctrl+, pour rouvrir"))
        hint.get_style_context().add_class("dim")
        top.pack_end(hint, False, False, 0)
        self.pack_start(top, False, False, 0)
        self.stack = stack = Gtk.Stack()
        stack.add_titled(self._scr(self._accounts_page()), "accounts", tr("Comptes"))
        stack.add_titled(self._scr(self._signature_page()), "sig", tr("Signatures"))
        stack.add_titled(self._scr(self._appearance_page()), "look", tr("Apparence"))
        stack.add_titled(self._ai_page(), "ai", tr("✨ Intelligence artificielle"))
        stack.add_titled(p2p_page(win), "p2p", tr("Synchronisation P2P"))
        stack.add_titled(gestures_page(win), "gestures", tr("Gestes & disposition"))
        stack.add_titled(filters_page(win), "filters", tr("Filtres & blocage"))
        stack.add_titled(templates_page(win), "templates", tr("Modèles de réponse"))
        stack.add_titled(contacts_page(win), "contacts", tr("Contacts"))
        stack.add_titled(identities_page(win), "identities", tr("Identités d'envoi"))
        stack.add_titled(self._scr(calendar_page(win)), "calendar", tr("Agenda (Google / CalDAV)"))
        stack.add_titled(self._shortcuts_page(), "keys", tr("Raccourcis"))
        stack.add_titled(self._scr(updates_page(win)), "updates", tr("Mises à jour"))
        stack.add_titled(help_page(), "help", tr("Aide & Crédits"))
        side = Gtk.StackSidebar()
        side.set_stack(stack)
        box = Gtk.Box()
        box.pack_start(side, False, False, 0)
        box.pack_start(stack, True, True, 0)
        self.pack_start(box, True, True, 0)
        self._reload_accounts()
        self.show_all()
        if page:
            stack.set_visible_child_name(page)

    @staticmethod
    def _scr(widget):
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        sw.add(widget)
        return sw

    def show_page(self, name):
        self.stack.set_visible_child_name(name)

    def _say(self, text, error=False):
        self.status.set_markup("<span foreground='%s'>%s</span>" % (
            "#dc2626" if error else "#16a34a", GLib.markup_escape_text(text)))

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
        add = Gtk.Button(label=tr("＋ Ajouter un compte"))
        add.connect("clicked", self._add_account)
        left.pack_start(add, False, False, 0)
        page.pack_start(left, False, False, 0)

        grid = Gtk.Grid(column_spacing=8, row_spacing=6)
        self.f_preset = Gtk.ComboBoxText()
        for k in PRESETS:
            self.f_preset.append_text(PRESET_LABELS.get(k, k))
        self.f_preset.connect("changed", self._preset)
        self.f_name, self.f_email = Gtk.Entry(), Gtk.Entry()
        self.f_user, self.f_pass = Gtk.Entry(), Gtk.Entry()
        self.f_pass.set_visibility(False)
        self.f_ihost, self.f_iport = Gtk.Entry(), Gtk.Entry()
        self.f_shost, self.f_sport = Gtk.Entry(), Gtk.Entry()
        self.f_ssl = Gtk.CheckButton(label=tr("IMAP en SSL/TLS direct (port 993)"))
        self.f_ssl.set_active(True)
        for i, (lab, w) in enumerate(((tr("Fournisseur"), self.f_preset), (tr("Nom affiché"), self.f_name),
                                      (tr("Adresse e-mail"), self.f_email), (tr("Identifiant"), self.f_user),
                                      (tr("Mot de passe"), self.f_pass), (tr("Serveur IMAP"), self.f_ihost),
                                      (tr("Port IMAP"), self.f_iport), (tr("Serveur SMTP"), self.f_shost),
                                      (tr("Port SMTP"), self.f_sport))):
            _row(grid, i, lab, w)
        grid.attach(self.f_ssl, 1, 9, 1, 1)
        btns = Gtk.Box(spacing=6)
        test = Gtk.Button(label=tr("Tester la connexion"))
        test.connect("clicked", self._test)
        save = Gtk.Button(label=tr("Enregistrer"))
        save.get_style_context().add_class("suggested-action")
        save.connect("clicked", self._save_account)
        rm = Gtk.Button(label=tr("Supprimer ce compte"))
        rm.connect("clicked", self._remove_account)
        self.oauth_btn = Gtk.Button(label=tr("🔑 Se connecter"))
        self.oauth_btn.get_style_context().add_class("suggested-action")
        self.oauth_btn.set_no_show_all(True)
        self.oauth_btn.connect("clicked", self._oauth_login)
        for b in (self.oauth_btn, test, save, rm):
            btns.pack_start(b, False, False, 0)
        grid.attach(btns, 1, 10, 1, 1)
        self.oauth_lbl = Gtk.Label(xalign=0)
        self.oauth_lbl.set_line_wrap(True)
        self.oauth_lbl.get_style_context().add_class("dim")
        self.oauth_lbl.set_no_show_all(True)
        grid.attach(self.oauth_lbl, 1, 13, 1, 1)
        self.status = Gtk.Label(xalign=0)
        self.status.set_line_wrap(True)
        grid.attach(self.status, 1, 11, 1, 1)
        note = Gtk.Label(xalign=0, label=tr("Gmail / Yahoo / iCloud : créez un « mot de passe d'application » dans les "
                                         "paramètres de sécurité du compte."))
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
            r.set_border_width(8)
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
        self.f_preset.set_active(-1)
        self.current = dict(a) if a else {"id": new_account_id()}
        a = self.current
        self.f_name.set_text(a.get("name", ""))
        self.f_email.set_text(a.get("email", ""))
        self.f_user.set_text(a.get("username", ""))
        self.f_pass.set_text("")
        self.f_pass.set_placeholder_text(tr("Enregistré — laisser vide pour le conserver")
                                         if a.get("email") and a.get("has_password", True) else tr("Mot de passe"))
        self.f_ihost.set_text(a.get("imap_host", ""))
        self.f_iport.set_text(str(a.get("imap_port", 993)))
        self.f_shost.set_text(a.get("smtp_host", ""))
        self.f_sport.set_text(str(a.get("smtp_port", 587)))
        self.f_ssl.set_active(a.get("imap_ssl", True))
        self.status.set_text("")
        self._oauth = a.get("oauth_provider") if a.get("auth") == "oauth2" else None
        self._oauth_token = None
        self._oauth_ui()

    def _add_account(self, *_):
        self.acc_list.unselect_all()
        self._acc_selected(None, None)
        self.f_preset.set_active(0)
        self.f_email.grab_focus()

    def _preset(self, combo):
        shown = combo.get_active_text() or ""
        p = PRESETS.get({v: k for k, v in PRESET_LABELS.items()}.get(shown, shown))
        self._oauth = p.get("oauth") if p else None
        if p:
            self._oauth_token = None
            self._oauth_ui()
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
            self._say(tr("Les ports doivent être des nombres."), True)
            return None
        a.update(name=self.f_name.get_text().strip(), email=self.f_email.get_text().strip(),
                 username=self.f_user.get_text().strip(), imap_host=self.f_ihost.get_text().strip(),
                 imap_port=ip, smtp_host=self.f_shost.get_text().strip(), smtp_port=sp,
                 imap_ssl=self.f_ssl.get_active())
        a.pop("demo", None)
        if self._oauth:
            a["auth"], a["oauth_provider"] = "oauth2", self._oauth
        else:
            a.pop("auth", None)
            a.pop("oauth_provider", None)
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", a["email"]):
            self._say(tr("Adresse e-mail invalide."), True)
            return None
        if not a["imap_host"] or not a["smtp_host"]:
            self._say(tr("Serveurs IMAP et SMTP requis (choisissez un fournisseur)."), True)
            return None
        if not (1 <= ip <= 65535 and 1 <= sp <= 65535):
            self._say(tr("Port invalide (1 à 65535)."), True)
            return None
        return a

    def _test(self, *_):
        a = self._collect()
        if not a:
            return
        typed = self._oauth_token or self.f_pass.get_text()
        if not typed and not a.get("has_password", True):
            self._say(tr("Saisissez le mot de passe (ou mot de passe d'application)."), True)
            return
        self._say(tr("Test de connexion en cours…"))

        def work():
            pw = typed or self.cfg.password(a["id"])

            outer = self.cfg

            class _C:  # config minimale pour make_backend
                def password(self_, _id):
                    return pw

                def get(self_, key, default=None):
                    return outer.get(key, default)

                def set_password(self_, *_a):
                    pass
            err = make_backend(a, _C()).test()
            GLib.idle_add(lambda: self._say(tr("Connexion réussie (IMAP + SMTP).") if not err else err, bool(err)))
        threading.Thread(target=work, daemon=True).start()

    def _save_account(self, *_):
        a = self._collect()
        if not a:
            return
        pw = self._oauth_token or self.f_pass.get_text()
        existing = next((x for x in self.cfg["accounts"] if x["id"] == a["id"]), None)
        if self._oauth and not pw and not (existing and existing.get("auth") == "oauth2" and existing.get("has_password", True)):
            self._say(tr("Connectez-vous d'abord avec le bouton « Se connecter »."), True)
            return
        if not self._oauth and not pw and not (existing and existing.get("has_password", True)):
            self._say(tr("Mot de passe requis."), True)
            return
        if any(x["email"].lower() == a["email"].lower() and x["id"] != a["id"] for x in self.cfg["accounts"]):
            self._say(tr("Ce compte existe déjà."), True)
            return
        first = not self.cfg["accounts"]
        if pw:
            self.cfg.set_password(a["id"], pw)
            a["has_password"] = True
        else:
            a["has_password"] = existing.get("has_password", True)
        accs = [x for x in self.cfg["accounts"] if x["id"] != a["id"]]
        old = next((x for x in self.cfg["accounts"] if x["id"] == a["id"]), {})
        a["signature_html"] = old.get("signature_html", "")
        accs.append(a)
        self.cfg["accounts"] = accs
        self.cfg.save()
        self.win.accounts_changed()
        self._reload_accounts(select=a["id"])
        self._say(tr("Compte enregistré. Synchronisation en cours…"))
        self.win.toast.popup(tr("Compte ajouté. Réglages : icône ⚙ en haut à droite ou Ctrl+,"), timeout=7)
        if first:
            GLib.timeout_add(900, lambda: (self.win.close_settings(), False)[1])

    def _remove_account(self, *_):
        aid = self.current.get("id")
        if aid and any(x["id"] == aid for x in self.cfg["accounts"]):
            d = Gtk.MessageDialog(transient_for=self.win, modal=True, message_type=Gtk.MessageType.QUESTION,
                                  text=tr("Supprimer ce compte de MintMail ?"),
                                  secondary_text=tr("Les messages en cache seront effacés. Vos mails restent sur le serveur."))
            d.add_buttons(tr("Annuler"), Gtk.ResponseType.CANCEL, tr("Supprimer"), Gtk.ResponseType.OK)
            ok = d.run() == Gtk.ResponseType.OK
            d.destroy()
            if not ok:
                return
            self.cfg["accounts"] = [x for x in self.cfg["accounts"] if x["id"] != aid]
            self.cfg.delete_password(aid)
            self.cfg.save()
            self.win.cache.delete_account(aid)
            self.win.accounts_changed()
            self._reload_accounts()

    # --------------------------------------------------------- signatures
    def _signature_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        page.set_border_width(14)
        top = Gtk.Box(spacing=8)
        top.pack_start(Gtk.Label(label=tr("Compte :")), False, False, 0)
        self.sig_combo = Gtk.ComboBoxText()
        self.sig_combo.connect("changed", self._sig_account)
        top.pack_start(self.sig_combo, False, False, 0)
        tpl = Gtk.Button(label=tr("Insérer un modèle"))
        tpl.connect("clicked", lambda *_: self.sig_buf.set_text(SIG_TEMPLATE))
        top.pack_start(tpl, False, False, 0)
        save = Gtk.Button(label=tr("Enregistrer la signature"))
        save.get_style_context().add_class("suggested-action")
        save.connect("clicked", self._sig_save)
        top.pack_end(save, False, False, 0)
        page.pack_start(top, False, False, 0)
        page.pack_start(Gtk.Label(label=tr("Signature HTML (balises <b>, <a>, <img>… autorisées) :"), xalign=0), False, False, 0)
        self.sig_view = Gtk.TextView()
        self.sig_view.set_monospace(True)
        self.sig_buf = self.sig_view.get_buffer()
        self.sig_buf.connect("changed", self._sig_preview)
        sw = Gtk.ScrolledWindow()
        sw.set_size_request(-1, 150)
        sw.add(self.sig_view)
        page.pack_start(sw, False, True, 0)
        page.pack_start(Gtk.Label(label=tr("Aperçu :"), xalign=0), False, False, 0)
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
            self.win.toast.popup(tr("Signature enregistrée"), timeout=3)

    # --------------------------------------------------------- apparence
    def _appearance_page(self):
        grid = Gtk.Grid(column_spacing=12, row_spacing=10)
        grid.set_border_width(18)
        stylec = Gtk.ComboBoxText()
        for k, v in STYLES.items():
            stylec.append(k, v["label"])
        stylec.set_active_id(self.cfg["style"])

        def style_changed(c):
            k = c.get_active_id()
            self.cfg["accent"] = STYLES[k]["accent"]   # chaque style a sa couleur signature (modifiable ensuite)
            self._set("style", k)
        stylec.connect("changed", style_changed)
        theme = Gtk.ComboBoxText()
        for k, v in (("system", tr("Système")), ("light", tr("Clair")), ("dark", tr("Sombre"))):
            theme.append(k, v)
        theme.set_active_id(self.cfg["theme"])
        theme.connect("changed", lambda c: self._set("theme", c.get_active_id()))
        dens = Gtk.ComboBoxText()
        for k, v in (("compact", tr("Compacte")), ("comfortable", tr("Confortable")), ("spacious", tr("Aérée"))):
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
        for i, (lab, w) in enumerate(((tr("Style visuel"), stylec), (tr("Mode"), theme), (tr("Densité de la liste"), dens), (tr("Couleur d'accent"), color),
                                      (tr("Charger les images distantes"), imgs), (tr("Notifications de bureau"), notif),
                                      (tr("Actualiser toutes les (min)"), refresh), (tr("Délai d'annulation d'envoi (s)"), undo))):
            l = Gtk.Label(label=lab, xalign=1)
            w.set_halign(Gtk.Align.START)
            grid.attach(l, 0, i, 1, 1)
            grid.attach(w, 1, i, 1, 1)
        swatches = Gtk.FlowBox()
        swatches.set_selection_mode(Gtk.SelectionMode.NONE)
        swatches.set_max_children_per_line(6)
        for name, hexcol in ACCENTS:
            b = Gtk.Button(label=name)
            b.get_style_context().add_class("pill")
            b.connect("clicked", lambda _b, h=hexcol: (self._set("accent", h), color.set_rgba(self._rgba(h))))
            swatches.add(b)
        grid.attach(Gtk.Label(label=tr("Couleurs prédéfinies"), xalign=1), 0, 8, 1, 1)
        grid.attach(swatches, 1, 8, 1, 1)
        clear = Gtk.Button(label=tr("Vider le cache des messages"))
        clear.set_halign(Gtk.Align.START)
        clear.connect("clicked", self._clear_cache)
        reset = Gtk.Button(label=tr("Rétablir l'apparence et la disposition par défaut"))
        reset.set_halign(Gtk.Align.START)
        reset.connect("clicked", self._reset_look)
        grid.attach(clear, 1, 9, 1, 1)
        grid.attach(reset, 1, 10, 1, 1)
        # langue de l'interface : « Automatique » = langue du système ; changement pris en compte au prochain démarrage
        langc = Gtk.ComboBoxText()
        langc.append("auto", tr("Automatique (langue du système)"))
        for code in i18n.available():
            langc.append(code, i18n.NAMES.get(code, code))
        cur = self.cfg.get("ui_lang", "auto")
        langc.set_active_id(cur if cur in ["auto"] + i18n.available() else "auto")

        def lang_changed(c):
            self._set("ui_lang", c.get_active_id())
            self.win.toast.popup(tr("Langue enregistrée : redémarrez MintMail pour l'appliquer."), timeout=6)
        langc.connect("changed", lang_changed)
        langc.set_halign(Gtk.Align.START)
        grid.attach(Gtk.Label(label=tr("Langue de l'interface"), xalign=1), 0, 11, 1, 1)
        grid.attach(langc, 1, 11, 1, 1)
        return grid

    def _clear_cache(self, *_):
        self.win.cache.clear_all()
        self.win.reload_list()
        self.win.update_counts()
        self.win.sync(True)
        self.win.toast.popup(tr("Cache vidé, resynchronisation…"), timeout=3)

    def _reset_look(self, *_):
        d = Gtk.MessageDialog(transient_for=self.win, modal=True, message_type=Gtk.MessageType.QUESTION,
                              text=tr("Rétablir l'apparence, la disposition et les gestes par défaut ?"))
        d.add_buttons(tr("Annuler"), Gtk.ResponseType.CANCEL, tr("Rétablir"), Gtk.ResponseType.OK)
        ok = d.run() == Gtk.ResponseType.OK
        d.destroy()
        if not ok:
            return
        self.cfg.reset(["theme", "style", "accent", "density", "load_images", "notifications", "refresh_minutes",
                        "undo_seconds", "layout", "pos_cols", "pos_bottom", "side_width", "zoom",
                        "swipe", "swipe_invert"])
        self.cfg.save()
        self.win.apply_settings()
        self.win.apply_layout()
        self.win.close_settings()
        self.win.show_settings("look")

    @staticmethod
    def _rgba(hexcol):
        c = Gdk.RGBA()
        c.parse(hexcol)
        return c

    @staticmethod
    def _hex(c):
        return "#%02x%02x%02x" % (int(c.red * 255), int(c.green * 255), int(c.blue * 255))

    def _set(self, key, val):
        self.cfg[key] = val
        self.cfg.save()
        if key in ("theme", "style", "accent", "density", "load_images"):   # les autres réglages n'exigent pas de rafraîchir l'interface
            self.win.apply_settings()

    def _ai_page(self):
        """L'IA est l'ADN de MintMail : réglages des fonctions, de la confidentialité et du fournisseur NVIDIA."""
        cfg = self.cfg
        grid = Gtk.Grid(column_spacing=12, row_spacing=10)
        grid.set_border_width(18)
        ttl = Gtk.Label(label=tr("✨ Intelligence artificielle"), xalign=0)
        ttl.get_style_context().add_class("list-title")
        grid.attach(ttl, 0, 0, 2, 1)
        note = Gtk.Label(xalign=0, label=tr("Résumés, réponses suggérées, tri par priorité, détection d'hameçonnage, rédaction, "
                                         "traduction, assistant conversationnel capable d'agir sur votre boîte. Désactivée "
                                         "par défaut : une fois activée, le texte des messages traités est envoyé au fournisseur choisi "
                                         "(voir « Confidentialité »). Avec Ollama, tout reste sur votre machine. Aucune action "
                                         "n'est exécutée sans votre accord."))
        note.set_line_wrap(True)
        note.get_style_context().add_class("dim")
        grid.attach(note, 0, 1, 2, 1)
        row = [2]

        def add(label, widget):
            grid.attach(Gtk.Label(label=label, xalign=1), 0, row[0], 1, 1)
            widget.set_halign(Gtk.Align.START) if not isinstance(widget, (Gtk.Entry, Gtk.Box)) else None
            grid.attach(widget, 1, row[0], 1, 1)
            row[0] += 1

        def switch(label, key, default=False):
            sw = Gtk.Switch()
            sw.set_active(bool(cfg.get(key, default)))

            def changed(w, _p):
                cfg[key] = w.get_active()
                cfg.save()
                self.win.refresh_ai()
            sw.connect("notify::active", changed)
            add(label, sw)

        def combo(label, key, options, default):
            c = Gtk.ComboBoxText()
            for k, v in options:
                c.append(k, v)
            c.set_active_id(cfg.get(key, default))

            def changed(w):
                cfg[key] = w.get_active_id()
                cfg.save()
                self.win.refresh_ai()
            c.connect("changed", changed)
            add(label, c)
        switch(tr("IA activée"), "ai_enabled")
        switch(tr("Analyser chaque message à l'ouverture"), "ai_auto", True)
        switch(tr("Trier les nouveaux messages (priorité, spam)"), "ai_triage", True)
        switch(tr("Résumé « En bref » de la boîte"), "ai_digest", True)
        switch(tr("Préparer des brouillons de réponse (messages importants)"), "ai_prepare_drafts", False)
        combo(tr("Confidentialité"), "ai_privacy", (("full", tr("Texte complet (meilleurs résultats)")),
                                                ("minimal", tr("Minimal : 500 premiers caractères"))), "full")
        combo(tr("Langue de l'IA"), "ai_lang", (("fr", tr("Français")), ("en", "English"), ("nl", "Nederlands"),
                                            ("de", "Deutsch"), ("es", tr("Español"))), "fr")
        combo(tr("Ton des rédactions"), "ai_tone", (("neutral", tr("Neutre et poli")), ("formal", tr("Formel")),
                                                 ("friendly", tr("Amical"))), "neutral")

        prov = Gtk.ComboBoxText()
        for k, (lab, _b, _m, _needs) in PROVIDERS.items():
            prov.append(k, lab)
        prov.set_active_id(cfg.get("ai_provider", "nvidia"))
        add(tr("Fournisseur"), prov)
        self.ai_key_entry = Gtk.Entry()
        self.ai_key_entry.set_visibility(False)
        self.ai_key_entry.set_hexpand(True)
        has_key = bool(cfg.get("ai_has_key") or cfg.get("nvidia_api_key"))
        self.ai_key_entry.set_placeholder_text(tr("Clé enregistrée — saisir pour la remplacer") if has_key else tr("Clé API NVIDIA (nvapi-…)"))
        save_key = Gtk.Button(label=tr("Enregistrer la clé"))
        krow = Gtk.Box(spacing=6)
        krow.pack_start(self.ai_key_entry, True, True, 0)
        krow.pack_start(save_key, False, False, 0)
        add(tr("Clé API"), krow)
        endpoint, model = Gtk.Entry(), Gtk.Entry()
        endpoint.set_placeholder_text(DEFAULT_API_BASE)
        endpoint.set_text(cfg.get("nvidia_api_base") or "")
        model.set_placeholder_text(DEFAULT_MODEL)
        model.set_text(cfg.get("ai_model") or "")
        for e in (endpoint, model):
            e.set_hexpand(True)
        add(tr("Endpoint API"), endpoint)
        add(tr("Modèle"), model)
        detect = Gtk.Button(label=tr("🔍 Détecter les modèles installés"))
        add("", detect)

        def provider_changed(c):
            k = c.get_active_id() or "nvidia"
            _lab, base, mdl, needs_key = PROVIDERS[k]
            if cfg.get("ai_provider", "nvidia") != k:
                cfg["ai_provider"] = k
                cfg["nvidia_api_base"] = ""      # chaque fournisseur a son adresse par défaut
                cfg["ai_model"] = ""
                endpoint.set_text("")
                model.set_text("")
                cfg.save()
                self.win.refresh_ai()
            endpoint.set_placeholder_text(base or "https://…/v1 (compatible OpenAI)")
            model.set_placeholder_text(mdl or tr("nom du modèle"))
            self.ai_key_entry.set_sensitive(needs_key or k == "custom")
            detect.set_visible(k != "nvidia")
            self.ai_key_entry.set_placeholder_text(tr("Clé enregistrée — saisir pour la remplacer") if has_key else (
                tr("Clé API NVIDIA (nvapi-…)") if needs_key else tr("Facultatif (service local : aucune clé nécessaire)")))
        prov.connect("changed", provider_changed)
        detect.set_no_show_all(True)
        self.ai_status = Gtk.Label(xalign=0)
        self.ai_status.set_line_wrap(True)
        test_btn = Gtk.Button(label=tr("Tester la connexion"))
        clear_btn = Gtk.Button(label=tr("Vider le cache IA (%d éléments)") % self.win.cache.ai_count())
        learn_btn = Gtk.Button(label=tr("Oublier mes habitudes de rangement"))
        learn_btn.set_tooltip_text(tr("Efface ce que MintMail a retenu de vos rangements (expéditeur → dossier)"))
        learn_btn.connect("clicked", lambda *_: (self.win.cache.learn_clear(), say(tr("Habitudes de rangement effacées."))))
        brow = Gtk.Box(spacing=6)
        brow.pack_start(test_btn, False, False, 0)
        brow.pack_start(clear_btn, False, False, 0)
        brow.pack_start(learn_btn, False, False, 0)
        add("", brow)
        add("", self.ai_status)

        def say(text, error=False):
            self.ai_status.set_markup("<span foreground='%s'>%s</span>" % (
                "#dc2626" if error else "#16a34a", GLib.markup_escape_text(text)))

        def store_key(*_):
            text = self.ai_key_entry.get_text().strip()
            if not text:
                return
            cfg.set_password("ai:nvidia", text)
            cfg["ai_has_key"] = True
            cfg.data.pop("nvidia_api_key", None)   # migration : plus jamais en clair
            cfg.save()
            self.ai_key_entry.set_text("")
            self.ai_key_entry.set_placeholder_text(tr("Clé enregistrée — saisir pour la remplacer"))
            self.win.refresh_ai()
            say(tr("Clé enregistrée dans le trousseau."))

        def store_text(key, entry, https=False):
            def save(*_):
                v = entry.get_text().strip()
                if https and v and not (v.startswith("https://") or (v.startswith("http://") and is_local_endpoint(v))):
                    say(tr("L'endpoint doit commencer par https:// (http:// seulement sur cette machine ou le réseau local)."), True)
                    return False
                cfg[key] = v
                cfg.save()
                self.win.refresh_ai()
                return False
            entry.connect("activate", save)
            entry.connect("focus-out-event", lambda *_: save() or False)
        store_text("nvidia_api_base", endpoint, https=True)
        store_text("ai_model", model)
        save_key.connect("clicked", store_key)
        self.ai_key_entry.connect("activate", store_key)

        def test(*_):
            typed = self.ai_key_entry.get_text().strip()
            _l, pbase, pmodel, _n = PROVIDERS[cfg.get("ai_provider", "nvidia")]
            base, mdl = endpoint.get_text().strip() or pbase or None, model.get_text().strip() or pmodel or None
            say(tr("Test en cours…"))

            def work():
                key = typed or cfg.ai_key()
                err, ok = AIService(api_key=key, api_base=base, model=mdl).test_connection()
                GLib.idle_add(lambda: (say(tr("Connexion réussie.") if ok else err, not ok), False)[1])
            threading.Thread(target=work, daemon=True).start()
        test_btn.connect("clicked", test)

        def do_detect(*_):
            _l, pbase, _m, _n = PROVIDERS[cfg.get("ai_provider", "nvidia")]
            base = endpoint.get_text().strip() or pbase
            say(tr("Recherche des modèles…"))

            def work():
                try:
                    names, err = list_models(base, self.ai_key_entry.get_text().strip() or cfg.ai_key() or ""), ""
                except AIServiceError as e:
                    names, err = [], str(e)

                def show():
                    if err:
                        say(err + tr(" — Ollama est-il lancé (ollama serve) et un modèle installé (ollama pull llama3.2) ?"), True)
                        return False
                    menu = Gtk.Menu()
                    for n in names[:40]:
                        mi = Gtk.MenuItem(label=n)
                        mi.connect("activate", lambda _i, n=n: (model.set_text(n), cfg.__setitem__("ai_model", n), cfg.save(), self.win.refresh_ai()))
                        menu.append(mi)
                    menu.show_all()
                    menu.popup_at_widget(detect, Gdk.Gravity.SOUTH_WEST, Gdk.Gravity.NORTH_WEST, None)
                    say(tr("%d modèle(s) trouvé(s) : choisissez-en un.") % len(names))
                    return False
                GLib.idle_add(show)
            threading.Thread(target=work, daemon=True).start()
        detect.connect("clicked", do_detect)
        provider_changed(prov)

        def clear(*_):
            self.win.cache.ai_clear()
            clear_btn.set_label(tr("Vider le cache IA (0 élément)"))
            self.win.reload_list()
        clear_btn.connect("clicked", clear)
        return self._scr(grid)

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


SettingsWindow = SettingsPage   # compatibilité
