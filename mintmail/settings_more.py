"""Connexion OAuth (Google / Microsoft), contacts, identités d'envoi et agenda CalDAV."""
import threading

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib, Gtk

import datetime

from . import caldav, contacts as vcf, gcal, oauth
from .backend import new_account_id


def _grid():
    g = Gtk.Grid(column_spacing=10, row_spacing=8)
    g.set_border_width(16)
    return g


def _row(grid, i, label, widget):
    grid.attach(Gtk.Label(label=label, xalign=1), 0, i, 1, 1)
    widget.set_hexpand(True)
    grid.attach(widget, 1, i, 1, 1)


def _note(text):
    l = Gtk.Label(label=text, xalign=0)
    l.set_line_wrap(True)
    l.set_selectable(True)
    l.get_style_context().add_class("dim")
    return l


# ------------------------------------------------------------------------------ OAuth
class OAuthMixin:
    """Méthodes ajoutées à la page des comptes."""
    _oauth = None
    _oauth_token = None

    def _oauth_ui(self):
        prov = oauth.PROVIDERS.get(self._oauth or "")
        self.oauth_btn.set_visible(bool(prov))
        self.oauth_lbl.set_visible(bool(prov))
        self.f_pass.set_sensitive(not prov)
        if prov:
            connected = bool(self._oauth_token) or bool(self.current.get("auth") == "oauth2" and self.current.get("has_password", True)
                                                        and self.cfg.password(self.current.get("id", "")))
            self.oauth_btn.set_label("🔑 Reconnecter avec %s" % prov["label"] if connected else "🔑 Se connecter avec %s" % prov["label"])
            self.oauth_lbl.set_text(("Connecté ✔ — aucun mot de passe n'est stocké : MintMail garde un jeton révocable depuis votre compte.\n"
                                     if connected else "") + "Une page de connexion s'ouvre dans votre navigateur (identifiant client OAuth à saisir une seule fois).")
            self.f_pass.set_placeholder_text("Connexion OAuth : pas de mot de passe")

    def _oauth_client_dialog(self, provider):
        prov = oauth.PROVIDERS[provider]
        cur = oauth.client_for(self.cfg, provider)
        dlg = Gtk.Dialog(title="Configurer %s — une seule fois" % prov["label"], transient_for=self.win, modal=True)
        dlg.add_buttons("Annuler", Gtk.ResponseType.CANCEL, "Enregistrer", Gtk.ResponseType.OK)
        box = dlg.get_content_area()
        box.set_border_width(16)
        box.set_spacing(8)
        box.pack_start(_note("MintMail ne peut pas créer cet identifiant à votre place (Google exige que ce soit vous, connecté à votre compte). "
                             "Suivez les étapes ci-dessous : chaque bouton ouvre la bonne page. Ensuite, collez l'ID client et le secret. "
                             "C'est à faire UNE FOIS : le réglage se synchronise avec vos autres machines (ou voir l'aide F1 pour le déployer "
                             "sur plusieurs postes)."), False, False, 0)
        for i, (text, url) in enumerate(oauth.WIZARD.get(provider, []), 1):
            row = Gtk.Box(spacing=8)
            lab = Gtk.Label(label="%d. %s" % (i, text), xalign=0)
            lab.set_line_wrap(True)
            lab.set_max_width_chars(70)
            btn = Gtk.Button(label="Ouvrir ↗")
            btn.connect("clicked", lambda _b, u=url: Gio.AppInfo.launch_default_for_uri(u, None))
            row.pack_start(lab, True, True, 0)
            row.pack_start(btn, False, False, 0)
            box.pack_start(row, False, False, 0)
        cid, secret = Gtk.Entry(), Gtk.Entry()
        cid.set_text(cur.get("client_id", ""))
        secret.set_text(cur.get("client_secret", ""))
        cid.set_placeholder_text("ID client")
        secret.set_placeholder_text("Secret client (facultatif selon le fournisseur)")
        box.pack_start(cid, False, False, 0)
        box.pack_start(secret, False, False, 0)
        dlg.show_all()
        ok = dlg.run() == Gtk.ResponseType.OK and cid.get_text().strip()
        if ok:
            clients = dict(self.cfg.get("oauth_clients") or {})
            clients[provider] = {"client_id": cid.get_text().strip(), "client_secret": secret.get_text().strip()}
            self.cfg["oauth_clients"] = clients
            self.cfg.save()
        dlg.destroy()
        return bool(ok)

    def _oauth_login(self, *_):
        provider = self._oauth
        if not provider:
            return
        client = oauth.client_for(self.cfg, provider)
        if not client.get("client_id") and not self._oauth_client_dialog(provider):
            return
        client = oauth.client_for(self.cfg, provider)
        self._say("Connexion dans le navigateur… (3 minutes maximum)")
        self.oauth_btn.set_sensitive(False)
        hint = self.f_email.get_text().strip()

        def open_url(url):
            GLib.idle_add(lambda: (Gio.AppInfo.launch_default_for_uri(url, None), False)[1])

        def work():
            try:
                res = oauth.run_loopback_flow(provider, client["client_id"], client.get("client_secret", ""), open_url, login_hint=hint)
                err = ""
            except Exception as e:
                res, err = None, str(e)

            def done():
                self.oauth_btn.set_sensitive(True)
                if err:
                    self._say("Connexion OAuth : %s" % err, True)
                    return False
                if not res.get("refresh_token"):
                    self._say("Le fournisseur n'a pas renvoyé de jeton durable (réessayez ; Google : consentement requis).", True)
                    return False
                self._oauth_token = res["refresh_token"]
                if res.get("email") and not self.f_email.get_text().strip():
                    self.f_email.set_text(res["email"])
                if not self.f_user.get_text().strip():
                    self.f_user.set_text(self.f_email.get_text().strip())
                self._oauth_ui()
                self._say("Connecté ✔ — cliquez sur « Enregistrer ».")
                return False
            GLib.idle_add(done)
        threading.Thread(target=work, daemon=True).start()


# --------------------------------------------------------------------------- contacts
def contacts_page(win):
    page = Gtk.Box(spacing=12)
    page.set_border_width(14)
    left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    search = Gtk.SearchEntry()
    search.set_placeholder_text("Rechercher un contact")
    lb = Gtk.ListBox()
    sw = Gtk.ScrolledWindow()
    sw.set_size_request(280, -1)
    sw.add(lb)
    left.pack_start(search, False, False, 0)
    left.pack_start(sw, True, True, 0)
    io = Gtk.Box(spacing=6)
    imp, exp = Gtk.Button(label="Importer .vcf"), Gtk.Button(label="Exporter .vcf")
    io.pack_start(imp, False, False, 0)
    io.pack_start(exp, False, False, 0)
    left.pack_start(io, False, False, 0)
    page.pack_start(left, False, False, 0)
    grid = _grid()
    f = {k: Gtk.Entry() for k in ("email", "name", "phone", "org", "notes")}
    for i, (k, lab) in enumerate((("name", "Nom"), ("email", "Adresse e-mail"), ("phone", "Téléphone"), ("org", "Société"), ("notes", "Notes"))):
        _row(grid, i, lab, f[k])
    status = Gtk.Label(xalign=0)
    btns = Gtk.Box(spacing=6)
    new, save, rm, write = (Gtk.Button(label="Nouveau"), Gtk.Button(label="Enregistrer"), Gtk.Button(label="Supprimer"),
                            Gtk.Button(label="✉ Écrire"))
    save.get_style_context().add_class("suggested-action")
    for b in (new, save, rm, write):
        btns.pack_start(b, False, False, 0)
    grid.attach(btns, 1, 5, 1, 1)
    grid.attach(status, 1, 6, 1, 1)
    grid.attach(_note("Les fiches enregistrées ici se synchronisent entre vos machines. Les autres correspondants (marqués auto) sont "
                      "repérés dans vos messages et servent à l'auto-complétion."), 1, 7, 1, 1)
    page.pack_start(grid, True, True, 0)

    def fill(c):
        for k in f:
            f[k].set_text((c or {}).get(k, "") or "")
        f["email"].set_sensitive(not c)

    def refresh(*_):
        for ch in lb.get_children():
            lb.remove(ch)
        for c in win.cache.contacts_list(search.get_text().strip(), limit=300):
            r = Gtk.ListBoxRow()
            r.c = c
            lab = Gtk.Label(xalign=0)
            lab.set_markup("<b>%s</b>%s\n<span alpha='60%%'>%s</span>" % (
                GLib.markup_escape_text(c["name"] or c["email"]), "" if c["source"] == "manual" else "  <small>auto</small>",
                GLib.markup_escape_text(c["email"])))
            lab.set_ellipsize(3)
            r.set_border_width(6)
            r.add(lab)
            lb.add(r)
        lb.show_all()

    def picked(_lb, row):
        if row is not None:
            fill(row.c)
    lb.connect("row-selected", picked)
    search.connect("search-changed", refresh)

    def do_new(*_):
        lb.unselect_all()
        fill(None)
        f["email"].grab_focus()
    new.connect("clicked", do_new)

    def do_save(*_):
        ok = win.contact_save(f["email"].get_text(), f["name"].get_text(), f["phone"].get_text(), f["org"].get_text(), f["notes"].get_text())
        status.set_text("Enregistré ✔" if ok else "Adresse e-mail invalide.")
        refresh()
    save.connect("clicked", do_save)

    def do_rm(*_):
        e = f["email"].get_text().strip()
        if e:
            win.contact_remove(e)
            do_new()
            refresh()
    rm.connect("clicked", do_rm)
    write.connect("clicked", lambda *_: f["email"].get_text().strip() and win.compose(to=f["email"].get_text().strip()))

    def do_import(*_):
        dlg = Gtk.FileChooserDialog(title="Importer des contacts (vCard)", parent=win, action=Gtk.FileChooserAction.OPEN)
        dlg.add_buttons("Annuler", Gtk.ResponseType.CANCEL, "Importer", Gtk.ResponseType.OK)
        if dlg.run() == Gtk.ResponseType.OK:
            try:
                with open(dlg.get_filename(), encoding="utf-8", errors="replace") as fh:
                    found = vcf.parse_vcf(fh.read())
                for c in found:
                    win.contact_save(c["email"], c["name"], c["phone"], c["org"], c["notes"])
                status.set_text("%d contact(s) importé(s)." % len(found))
            except OSError as e:
                status.set_text("Lecture impossible : %s" % e)
        dlg.destroy()
        refresh()
    imp.connect("clicked", do_import)

    def do_export(*_):
        dlg = Gtk.FileChooserDialog(title="Exporter les contacts", parent=win, action=Gtk.FileChooserAction.SAVE)
        dlg.add_buttons("Annuler", Gtk.ResponseType.CANCEL, "Exporter", Gtk.ResponseType.OK)
        dlg.set_current_name("contacts-mintmail.vcf")
        if dlg.run() == Gtk.ResponseType.OK:
            try:
                with open(dlg.get_filename(), "w", encoding="utf-8", newline="") as fh:
                    fh.write(vcf.to_vcf(win.cache.contacts_list(source="manual", limit=5000)))
                status.set_text("Contacts exportés.")
            except OSError as e:
                status.set_text("Écriture impossible : %s" % e)
        dlg.destroy()
    exp.connect("clicked", do_export)
    refresh()
    return page


# ------------------------------------------------------------------------------ identités
def identities_page(win):
    cfg = win.config
    page = Gtk.Box(spacing=12)
    page.set_border_width(14)
    left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    lb = Gtk.ListBox()
    sw = Gtk.ScrolledWindow()
    sw.set_size_request(240, -1)
    sw.add(lb)
    left.pack_start(sw, True, True, 0)
    add = Gtk.Button(label="＋ Ajouter une identité")
    left.pack_start(add, False, False, 0)
    page.pack_start(left, False, False, 0)
    grid = _grid()
    acc = Gtk.ComboBoxText()
    name, email, sig = Gtk.Entry(), Gtk.Entry(), Gtk.TextView()
    sig.set_wrap_mode(Gtk.WrapMode.WORD)
    sigw = Gtk.ScrolledWindow()
    sigw.set_size_request(-1, 140)
    sigw.add(sig)
    for i, (lab, w) in enumerate((("Compte d'envoi", acc), ("Nom affiché", name), ("Adresse (alias)", email), ("Signature (HTML)", sigw))):
        _row(grid, i, lab, w)
    status = Gtk.Label(xalign=0)
    btns = Gtk.Box(spacing=6)
    save, rm = Gtk.Button(label="Enregistrer"), Gtk.Button(label="Supprimer")
    save.get_style_context().add_class("suggested-action")
    btns.pack_start(save, False, False, 0)
    btns.pack_start(rm, False, False, 0)
    grid.attach(btns, 1, 4, 1, 1)
    grid.attach(status, 1, 5, 1, 1)
    grid.attach(_note("Une identité est une adresse supplémentaire (alias) depuis laquelle vous pouvez écrire, avec sa propre signature. "
                      "Le serveur du compte doit autoriser cet alias. Quand un message reçu était adressé à un alias, la réponse part "
                      "automatiquement de cet alias. Choix possible dans le champ « De » de la rédaction."), 1, 6, 1, 1)
    page.pack_start(grid, True, True, 0)
    cur = {"id": None}

    def fill_accounts():
        acc.remove_all()
        for a in cfg["accounts"]:
            acc.append(a["id"], "%s <%s>" % (a.get("name", ""), a["email"]))
        acc.set_active(0)

    def refresh(select=None):
        for ch in lb.get_children():
            lb.remove(ch)
        for i in cfg.get("identities", []):
            r = Gtk.ListBoxRow()
            r.i = i
            l = Gtk.Label(label="%s <%s>" % (i.get("name", ""), i["email"]), xalign=0)
            r.set_border_width(8)
            r.add(l)
            lb.add(r)
            if select == i["id"]:
                lb.select_row(r)
        lb.show_all()

    def picked(_lb, row):
        i = row.i if row else {}
        cur["id"] = i.get("id")
        fill_accounts()
        if i:
            acc.set_active_id(i.get("account"))
        name.set_text(i.get("name", ""))
        email.set_text(i.get("email", ""))
        sig.get_buffer().set_text(i.get("signature_html", ""))
    lb.connect("row-selected", picked)

    def do_add(*_):
        lb.unselect_all()
        picked(None, None)
        email.grab_focus()
    add.connect("clicked", do_add)

    def do_save(*_):
        em = email.get_text().strip()
        if "@" not in em or not acc.get_active_id():
            status.set_text("Adresse et compte d'envoi requis.")
            return
        b = sig.get_buffer()
        ident = {"id": cur["id"] or new_account_id(), "account": acc.get_active_id(), "name": name.get_text().strip()[:100],
                 "email": em[:200], "signature_html": b.get_text(b.get_start_iter(), b.get_end_iter(), True)[:20000]}
        cfg["identities"] = [i for i in cfg.get("identities", []) if i["id"] != ident["id"]] + [ident]
        cfg.save()
        status.set_text("Identité enregistrée ✔")
        refresh(ident["id"])
    save.connect("clicked", do_save)

    def do_rm(*_):
        if cur["id"]:
            cfg["identities"] = [i for i in cfg.get("identities", []) if i["id"] != cur["id"]]
            cfg.save()
            refresh()
            do_add()
    rm.connect("clicked", do_rm)
    fill_accounts()
    refresh()
    return page


# ------------------------------------------------------------------------------ agenda
def _caldav_grid(win):
    cfg = win.config
    grid = _grid()
    cur = cfg.get("caldav") or {}
    url, user, pw = Gtk.Entry(), Gtk.Entry(), Gtk.Entry()
    pw.set_visibility(False)
    url.set_text(cur.get("url", ""))
    user.set_text(cur.get("user", ""))
    pw.set_placeholder_text("Enregistré — laisser vide pour le conserver" if cfg.password("caldav") else "Mot de passe (ou mot de passe d'application)")
    url.set_placeholder_text("https://cloud.exemple.be/remote.php/dav/calendars/moi/personnel/")
    for i, (lab, w) in enumerate((("Adresse du calendrier", url), ("Identifiant", user), ("Mot de passe", pw))):
        _row(grid, i, lab, w)
    status = Gtk.Label(xalign=0)
    status.set_line_wrap(True)
    btns = Gtk.Box(spacing=6)
    test, save, clear = Gtk.Button(label="Tester"), Gtk.Button(label="Enregistrer"), Gtk.Button(label="Désactiver")
    save.get_style_context().add_class("suggested-action")
    for b in (test, save, clear):
        btns.pack_start(b, False, False, 0)
    grid.attach(btns, 1, 3, 1, 1)
    grid.attach(status, 1, 4, 1, 1)
    grid.attach(_note("Optionnel : les invitations acceptées et les rendez-vous détectés par l'IA sont ajoutés directement à ce calendrier "
                      "CalDAV (Nextcloud, Radicale, Fastmail, iCloud…). Sans CalDAV, MintMail ouvre le fichier .ics dans l'agenda de votre système "
                      "(Thunderbird, GNOME Agenda…). Les réponses aux invitations (accepter / refuser) sont toujours envoyées par e-mail."), 1, 5, 1, 1)

    def secret():
        return pw.get_text() or cfg.password("caldav")

    def do_test(*_):
        status.set_text("Test…")

        def work():
            ok, d = caldav.test_connection(url.get_text().strip(), user.get_text().strip(), secret())
            GLib.idle_add(lambda: (status.set_text(("✔ " if ok else "✖ ") + d), False)[1])
        threading.Thread(target=work, daemon=True).start()
    test.connect("clicked", do_test)

    def do_save(*_):
        u = url.get_text().strip()
        if u and not (u.startswith("https://") or u.startswith("http://")):
            status.set_text("L'adresse doit commencer par https://")
            return
        cfg["caldav"] = {"url": u, "user": user.get_text().strip()}
        if pw.get_text():
            cfg.set_password("caldav", pw.get_text())
            pw.set_text("")
        cfg.save()
        status.set_text("Enregistré ✔")
    save.connect("clicked", do_save)

    def do_clear(*_):
        cfg["caldav"] = {}
        cfg.delete_password("caldav")
        cfg.save()
        url.set_text("")
        user.set_text("")
        status.set_text("CalDAV désactivé.")
    clear.connect("clicked", do_clear)
    return grid


def _google_section(win):
    cfg = win.config
    grid = _grid()
    head = Gtk.Label(xalign=0)
    head.set_markup("<b>Google Agenda</b> — avec votre compte Gmail connecté en OAuth")
    grid.attach(head, 0, 0, 2, 1)
    accs = [a for a in cfg["accounts"] if a.get("auth") == "oauth2" and a.get("oauth_provider") == "google"]
    combo = Gtk.ComboBoxText()
    for a in accs:
        combo.append(a["id"], a["email"])
    cur = cfg.get("gcal") or {}
    combo.set_active_id(cur.get("account") if any(a["id"] == cur.get("account") for a in accs) else (accs[0]["id"] if accs else None))
    on = Gtk.Switch()
    on.set_active(bool(cur.get("enabled")) and bool(accs))
    on.set_halign(Gtk.Align.START)
    _row(grid, 1, "Compte Gmail", combo)
    _row(grid, 2, "Utiliser Google Agenda", on)
    status = Gtk.Label(xalign=0)
    status.set_line_wrap(True)
    status.set_selectable(True)
    btns = Gtk.Box(spacing=6)
    auth, test = Gtk.Button(label="🔑 Autoriser Google Agenda"), Gtk.Button(label="Tester (7 prochains jours)")
    auth.get_style_context().add_class("suggested-action")
    btns.pack_start(auth, False, False, 0)
    btns.pack_start(test, False, False, 0)
    grid.attach(btns, 1, 3, 1, 1)
    grid.attach(status, 1, 4, 1, 1)
    grid.attach(_note(
        "Ce que ça apporte : les invitations acceptées et les rendez-vous détectés par l'IA arrivent directement dans Google Agenda "
        "(sans doublon) ; « Agenda » dans la palette affiche vos 14 prochains jours et permet de créer un événement ; à la réception d'une "
        "invitation, MintMail prévient si le créneau est déjà pris.\n\n"
        "Mise en place (une seule fois) :\n"
        "1. Connectez d'abord votre compte Gmail avec le fournisseur « OAuth » (Paramètres → Comptes).\n"
        "2. Console Google Cloud (le même projet que pour Gmail) → API et services → Bibliothèque → « Google Calendar API » → Activer.\n"
        "3. Ici : « Autoriser Google Agenda » (une page Google s'ouvre ; l'autorisation « calendar.events » est AJOUTÉE à celle de Gmail).\n"
        "Important : tant que l'écran de consentement est en mode « Test », Google fait expirer le jeton au bout de 7 jours (il faut alors "
        "ré-autoriser). Pour un usage personnel durable, passez l'application en « En production » (écran « application non validée » à "
        "accepter une fois ; jusqu'à 100 utilisateurs)."), 1, 5, 1, 1)

    def say(text, error=False):
        status.set_markup("<span foreground='%s'>%s</span>" % ("#dc2626" if error else "#16a34a", GLib.markup_escape_text(text)))

    def save_cfg(*_):
        cfg["gcal"] = {"account": combo.get_active_id(), "enabled": bool(on.get_active() and combo.get_active_id())}
        cfg.save()
    on.connect("notify::active", save_cfg)
    combo.connect("changed", save_cfg)

    def account():
        return next((a for a in accs if a["id"] == combo.get_active_id()), None)

    def do_auth(*_):
        acc = account()
        client = oauth.client_for(cfg, "google")
        if not acc:
            say("Ajoutez d'abord un compte Gmail avec le fournisseur « OAuth » (Paramètres → Comptes).", True)
            return
        if not client.get("client_id"):
            say("Identifiant client OAuth manquant : Paramètres → Comptes → Gmail (OAuth).", True)
            return
        say("Autorisation dans le navigateur… (3 minutes maximum)")
        auth.set_sensitive(False)

        def open_url(url):
            GLib.idle_add(lambda: (Gio.AppInfo.launch_default_for_uri(url, None), False)[1])

        def work():
            try:
                res = oauth.run_loopback_flow("google", client["client_id"], client.get("client_secret", ""), open_url,
                                              login_hint=acc["email"], extra_scopes=[gcal.SCOPE])
                err = "" if res.get("refresh_token") else "Google n'a pas renvoyé de jeton durable : réessayez."
            except Exception as e:
                res, err = None, str(e)

            def done():
                auth.set_sensitive(True)
                if err:
                    say("Autorisation : %s" % err, True)
                    return False
                cfg.set_password(acc["id"], res["refresh_token"])           # nouveau jeton : Gmail + Agenda
                oauth.manager_for(cfg)._cache.pop(acc["id"], None)
                on.set_active(True)
                save_cfg()
                say("Google Agenda autorisé ✔ — cliquez « Tester » pour vérifier.")
                return False
            GLib.idle_add(done)
        threading.Thread(target=work, daemon=True).start()
    auth.connect("clicked", do_auth)

    def do_test(*_):
        acc = account()
        if not acc:
            say("Aucun compte Gmail (OAuth).", True)
            return
        say("Test…")

        def work():
            try:
                now = datetime.datetime.now()
                ok, data = gcal.list_events(oauth.manager_for(cfg).access_token(acc), now, now + datetime.timedelta(days=7))
            except Exception as e:
                ok, data = False, str(e)
            GLib.idle_add(lambda: (say(("✔ Connecté : %d événement(s) dans les 7 prochains jours." % len(data)) if ok else "✖ %s" % data, not ok), False)[1])
        threading.Thread(target=work, daemon=True).start()
    test.connect("clicked", do_test)
    return grid


def calendar_page(win):
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    box.pack_start(_google_section(win), False, False, 0)
    box.pack_start(Gtk.Separator(), False, False, 6)
    alt = Gtk.Label(xalign=0)
    alt.set_markup("   <b>Autre calendrier : CalDAV</b> (Nextcloud, Radicale, Fastmail, iCloud…) — utilisé si Google Agenda est désactivé")
    box.pack_start(alt, False, False, 4)
    box.pack_start(_caldav_grid(win), False, False, 0)
    return box
