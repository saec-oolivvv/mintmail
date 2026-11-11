"""Interface des mises à jour : recherche automatique (une fois par jour), bandeau d'annonce visible dès le lancement, installation en un clic."""
import os
import subprocess
import time

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk

from . import __version__, updater
from .i18n import tr
from .reader import open_uri


def explain(code, detail=""):
    """Texte (traduit) d'un code d'erreur de mise à jour."""
    table = {
        "network": tr("Impossible de joindre GitHub (réseau)."),
        "ratelimit": tr("GitHub limite les requêtes : réessayez plus tard."),
        "norelease": tr("Aucune version publiée dans ce dépôt."),
        "badrepo": tr("Dépôt invalide : écrivez « propriétaire/nom »."),
        "badjson": tr("Réponse illisible de GitHub."),
        "badversion": tr("Numéro de version illisible."),
        "noasset": tr("La version publiée ne contient pas le paquet attendu."),
        "badurl": tr("Adresse de téléchargement refusée (hôte non autorisé)."),
        "toobig": tr("Fichier trop volumineux : refusé."),
        "badsize": tr("Téléchargement incomplet."),
        "checksum": tr("Somme de contrôle incorrecte : téléchargement corrompu, refusé."),
        "http": tr("Erreur du serveur de téléchargement."),
        "nokey": tr("Clé de vérification absente : installation automatique désactivée."),
        "unsigned": tr("Version non signée : refusée par sécurité."),
        "bad_signature": tr("SIGNATURE INVALIDE : paquet refusé (il ne vient pas de SAEC ou a été modifié)."),
        "bad_package": tr("Ce fichier n'est pas un paquet MintMail valide : refusé."),
        "not_newer": tr("Cette version n'est pas plus récente que celle installée : refusée."),
        "bad_file": tr("Fichier de mise à jour invalide : refusé."),
        "key_untrusted": tr("La clé de vérification installée n'est pas protégée : refusé."),
        "install_failed": tr("L'installation a échoué (le détail est dans le journal)."),
        "cancelled": tr("Authentification annulée : rien n'a été installé."),
        "nohelper": tr("Installation automatique indisponible sur cette machine (pkexec ou programme d'installation absent)."),
        "not_root": tr("Droits administrateur requis."),
        "usage": tr("Appel invalide du programme d'installation."),
        "internal": tr("Erreur interne pendant la mise à jour."),
    }
    return table.get(code, tr("Erreur de mise à jour (%s).") % code)


class UpdateBanner(Gtk.Revealer):
    """Bandeau de mise à jour glissant sous la barre de titre : discret quand tout va bien, impossible à manquer quand une version est
    disponible. États : available (annonce + Installer / Plus tard), progress (barre de progression), done (Relancer), error (Réessayer)."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.state = "hidden"
        self._pulse_id = None
        self._fraction = None
        self.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        self.set_transition_duration(380)
        card = Gtk.Box(spacing=14)
        card.get_style_context().add_class("update-banner")
        self.icon = Gtk.Label(label="⬆")
        self.icon.get_style_context().add_class("update-icon")
        card.pack_start(self.icon, False, False, 0)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        self.title = Gtk.Label(xalign=0)
        self.title.get_style_context().add_class("update-title")
        self.sub = Gtk.Label(xalign=0)
        self.sub.get_style_context().add_class("update-sub")
        self.sub.set_line_wrap(True)
        self.notes = Gtk.Label(xalign=0)
        self.notes.get_style_context().add_class("update-notes")
        self.notes.set_line_wrap(True)
        self.bar = Gtk.ProgressBar()
        for w in (self.title, self.sub, self.notes, self.bar):
            text.pack_start(w, False, False, 0)
        card.pack_start(text, True, True, 0)
        row = Gtk.Box(spacing=6)
        self.btn_install = self._button(tr("Installer maintenant"), "update-install", lambda *_: win.install_update(confirm=False))
        self.btn_retry = self._button(tr("Réessayer"), "update-install", lambda *_: win.install_update(confirm=False))
        self.btn_restart = self._button(tr("Relancer maintenant"), "update-install", lambda *_: win.restart_app())
        self.btn_notes = self._button(tr("Notes de version"), "update-link", lambda *_: win.open_update_page())
        self.btn_later = self._button(tr("Plus tard"), "update-later", lambda *_: win.snooze_update())
        self.btn_later.set_tooltip_text(tr("Me le rappeler dans 24 h"))
        self.btn_close = self._button("✕", "update-later", lambda *_: win.hide_update_banner())
        self.btn_close.set_tooltip_text(tr("Fermer"))
        self._all = (self.btn_install, self.btn_retry, self.btn_restart, self.btn_notes, self.btn_later, self.btn_close)
        for b in self._all:
            row.pack_start(b, False, False, 0)
        card.pack_start(row, False, False, 0)
        self.add(card)
        card.show_all()
        for w in (self.notes, self.bar) + self._all:
            w.set_no_show_all(True)                    # leur visibilité dépend de l'état : show_all() ne doit pas les réafficher
        self._buttons()
        self.notes.set_visible(False)
        self.bar.set_visible(False)
        self.set_reveal_child(False)

    @staticmethod
    def _button(label, css, cb):
        b = Gtk.Button(label=label)
        b.set_relief(Gtk.ReliefStyle.NONE if css != "update-install" else Gtk.ReliefStyle.NORMAL)
        b.get_style_context().add_class(css)
        b.connect("clicked", cb)
        return b

    def _buttons(self, *visible):
        for b in self._all:
            b.set_visible(b in visible)

    def _stop_pulse(self):
        if self._pulse_id:
            try:
                GLib.source_remove(self._pulse_id)
            except Exception:
                pass
            self._pulse_id = None

    def _pulse(self):
        if self.state != "progress" or self._fraction is not None:
            self._pulse_id = None
            return False
        self.bar.pulse()
        return True

    def show_available(self, up, current):
        self._stop_pulse()
        self.state = "available"
        self.icon.set_text("⬆")
        self.title.set_text(tr("MintMail %s est disponible") % up.version)
        self.sub.set_text(tr("Vous utilisez la version %s. Installation sécurisée : signature vérifiée, puis mot de passe administrateur demandé.") % current)
        n = updater.short_notes(up.notes)
        self.notes.set_text(tr("Nouveautés : %s") % n if n else "")
        self.notes.set_visible(bool(n))
        self.bar.set_visible(False)
        self._buttons(self.btn_install, *([self.btn_notes] if up.page else []), self.btn_later, self.btn_close)
        self.set_reveal_child(True)

    def show_progress(self, version, text, fraction=None):
        self.state = "progress"
        self._fraction = fraction
        self.icon.set_text("⏳")
        self.title.set_text(tr("Mise à jour vers MintMail %s") % version)
        self.sub.set_text(text)
        self.notes.set_visible(False)
        self.bar.set_visible(True)
        if fraction is None:
            if self._pulse_id is None:
                self._pulse_id = GLib.timeout_add(110, self._pulse)
        else:
            self.bar.set_fraction(max(0.0, min(1.0, fraction)))
        self._buttons()
        self.set_reveal_child(True)

    def show_done(self, version):
        self._stop_pulse()
        self.state = "done"
        self.icon.set_text("✔")
        self.title.set_text(tr("MintMail %s est installé") % version)
        self.sub.set_text(tr("Relancez MintMail pour profiter de la nouvelle version."))
        self.notes.set_visible(False)
        self.bar.set_visible(False)
        self._buttons(self.btn_restart, self.btn_close)
        self.set_reveal_child(True)

    def show_error(self, text, page=""):
        self._stop_pulse()
        self.state = "error"
        self.icon.set_text("⚠")
        self.title.set_text(tr("La mise à jour a échoué"))
        self.sub.set_text(text)
        self.notes.set_visible(False)
        self.bar.set_visible(False)
        self._buttons(self.btn_retry, *([self.btn_notes] if page else []), self.btn_close)
        self.set_reveal_child(True)

    def hide(self):
        self._stop_pulse()
        self.state = "hidden"
        self.set_reveal_child(False)


class UpdateMixin:
    def _init_updates(self):
        self._update = None
        self._update_busy = False
        self._update_views = []          # fonctions à rappeler quand l'état change (page de réglages ouverte)
        self._restore_update()           # une mise à jour déjà connue s'affiche TOUT DE SUITE, sans attendre le réseau
        GLib.timeout_add_seconds(8, lambda: (self.check_updates(), False)[1])          # 8 s après le démarrage (au plus une fois par jour)
        GLib.timeout_add_seconds(3600, lambda: (self.check_updates(), True)[1])        # puis chaque heure : GitHub n'est contacté qu'une fois par jour

    def _restore_update(self):
        cfg = self.config
        stored = cfg.get("update_available")
        self._update = updater.update_from_dict(stored, __version__)
        if stored and self._update is None:                       # déjà installée depuis, ou enregistrement invalide : on l'oublie
            cfg["update_available"] = None
            cfg.save()
        self._refresh_update_ui()

    def _snoozed(self, up):
        cfg = self.config
        return cfg.get("update_snooze_version") == up.version and time.time() < float(cfg.get("update_snooze_until") or 0)

    def _refresh_update_ui(self, force=False):
        up = self._update
        chip, banner = getattr(self, "update_chip", None), getattr(self, "update_banner", None)
        if chip is not None:
            chip.set_visible(up is not None)
            if up is not None:
                chip.set_label(tr("⬆ Mise à jour %s") % up.version)
                chip.set_tooltip_text(tr("Cliquez pour voir la mise à jour de MintMail %s") % up.version)
        if banner is not None and not self._update_busy and banner.state not in ("progress", "done", "error"):
            if up is not None and (force or not self._snoozed(up)):
                banner.show_available(up, __version__)
            else:
                banner.hide()
        self._update_changed()

    def _update_changed(self):
        for f in list(self._update_views):
            try:
                f()
            except Exception:
                self._update_views.remove(f)

    def snooze_update(self):
        """« Plus tard » : le bandeau se cache 24 h pour cette version (la pastille de la barre latérale reste)."""
        up = self._update
        if up is not None:
            self.config["update_snooze_version"] = up.version
            self.config["update_snooze_until"] = time.time() + 24 * 3600
            self.config.save()
        if getattr(self, "update_banner", None) is not None:
            self.update_banner.hide()

    def hide_update_banner(self):
        if getattr(self, "update_banner", None) is not None:
            self.update_banner.hide()

    def open_update_page(self):
        up = self._update
        if up is not None and up.page:
            open_uri(self, up.page)

    def check_updates(self, manual=False):
        cfg = self.config
        if self._update_busy:
            return
        if not manual and not (cfg.get("update_check", True) and updater.due(time.time(), cfg.get("update_last_check", 0))):
            return
        self._update_busy = True
        repo = cfg.get("update_repo") or updater.DEFAULT_REPO
        etag = cfg.get("update_etag", "") if self._update is None else ""

        def done(res, err):
            self._update_busy = False
            if err or res is None:
                if manual:
                    self.toast.popup(explain("network"), timeout=6)
                self._update_changed()
                return
            if res.state != "error":
                cfg["update_last_check"] = time.time()
                cfg["update_etag"] = res.etag if res.state == "uptodate" else ""
            if res.state == "available":
                self._update = res.update
                cfg["update_available"] = updater.update_to_dict(res.update)
                cfg["update_seen"] = res.update.version
                if manual:
                    cfg["update_snooze_until"] = 0                 # demande explicite : on montre le bandeau même s'il avait été repoussé
                cfg.save()
                self._refresh_update_ui(force=manual)
                return
            if res.state == "uptodate":
                self._update = None
                cfg["update_available"] = None
                if manual:
                    self.toast.popup(tr("MintMail est à jour (version %s).") % __version__, timeout=5)
            elif manual:
                self.toast.popup(explain(res.code), timeout=7)
            cfg.save()
            self._refresh_update_ui()
        self.run_bg(lambda: updater.check(repo, etag=etag), done)

    # ------------------------------------------------------------------ installation
    def _stage(self, version, text, fraction=None):
        """Met à jour le bandeau depuis le fil de travail (l'interface ne se modifie que dans le fil principal)."""
        banner = getattr(self, "update_banner", None)
        if banner is not None:
            GLib.idle_add(lambda: (banner.show_progress(version, text, fraction), False)[1])

    def _update_failed(self, text, up=None):
        banner = getattr(self, "update_banner", None)
        if banner is not None:
            banner.show_error(text, up.page if up else "")
        else:
            self.toast.popup(text, timeout=12)

    def install_update(self, confirm=True):
        up = self._update
        if up is None or self._update_busy:
            return
        ok, why = updater.can_install()
        if not ok:
            self._update_failed(explain(why), up)
            self.toast.popup(explain(why), tr("Ouvrir la page"), lambda: open_uri(self, up.page), timeout=12)
            return
        if confirm:
            notes = (up.notes.strip()[:600] + "\n\n") if up.notes.strip() else ""
            if not self._confirm(tr("Installer MintMail %s ?") % up.version,
                                 notes + tr("Le paquet est téléchargé depuis GitHub, sa signature est vérifiée avec la clé de SAEC intégrée à MintMail, puis votre mot de passe "
                                            "administrateur est demandé pour l'installer. Fermez et relancez MintMail ensuite.")):
                return
        self._update_busy = True
        if getattr(self, "update_banner", None) is not None:
            self.update_banner.show_progress(up.version, tr("Téléchargement…"), 0.0)
        self._update_changed()
        last = {"pct": -1}

        def progress(done, total):
            pct = int(100 * done / total) if total else -1
            if pct != last["pct"]:
                last["pct"] = pct
                self._stage(up.version, tr("Téléchargement…"), (done / total) if total else None)

        def work():
            deb, sig = updater.fetch(up, updater.downloads_dir(), progress=progress)
            self._stage(up.version, tr("Vérification de la signature…"), None)
            code = updater.check_signature(deb, sig)
            if code:
                return False, code, ""
            self._stage(up.version, tr("Installation… (votre mot de passe administrateur est demandé)"), None)
            return updater.install(deb, sig)

        def done(res, err):
            self._update_busy = False
            if err is not None:
                self._update_failed(explain(getattr(err, "code", "internal")), up)
            else:
                ok2, code, detail = res
                if ok2:
                    self._update = None
                    self.config["update_available"] = None
                    self.config.save()
                    updater.cleanup()
                    if getattr(self, "update_banner", None) is not None:
                        self.update_banner.show_done(detail or up.version)
                    else:
                        self.toast.popup(tr("✔ MintMail %s est installé : fermez puis relancez MintMail.") % (detail or up.version), timeout=0)
                    if getattr(self, "update_chip", None) is not None:
                        self.update_chip.set_visible(False)
                else:
                    from .log import log
                    log("Mise à jour refusée / échouée : %s %s" % (code, detail))
                    self._update_failed(explain(code), up)
            self._update_changed()
        self.run_bg(work, done)

    def restart_app(self):
        """Relance MintMail : une commande FIXE, lancée dans une session détachée après la fermeture de cette fenêtre (pas de texte externe)."""
        if not os.path.exists("/usr/bin/mintmail"):
            self.toast.popup(tr("Impossible de relancer automatiquement : fermez puis relancez MintMail."), timeout=8)
            return
        subprocess.Popen(["/bin/sh", "-c", "sleep 2; exec /usr/bin/mintmail"], start_new_session=True, close_fds=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        app = self.get_application() if hasattr(self, "get_application") else None
        if app is not None:
            app.quit()
        else:
            self.close()


def updates_page(win):
    """Page « Mises à jour » des paramètres."""
    cfg = win.config
    grid = Gtk.Grid(column_spacing=14, row_spacing=10)
    grid.set_border_width(18)
    alive = {"v": True}

    def note(text, dim=True):
        l = Gtk.Label(xalign=0, label=text)
        l.set_line_wrap(True)
        l.set_max_width_chars(80)
        l.set_selectable(True)
        if dim:
            l.get_style_context().add_class("dim")
        return l

    head = Gtk.Label(xalign=0, label="<b>%s</b>" % tr("Mises à jour"))
    head.set_use_markup(True)
    grid.attach(head, 0, 0, 2, 1)
    grid.attach(note(tr("Version installée : %s") % __version__, dim=False), 0, 1, 2, 1)
    auto = Gtk.Switch()
    auto.set_active(bool(cfg.get("update_check", True)))
    auto.set_halign(Gtk.Align.START)
    auto.connect("notify::active", lambda s, _p: (cfg.__setitem__("update_check", s.get_active()), cfg.save()))
    grid.attach(Gtk.Label(label=tr("Rechercher automatiquement (une fois par jour)"), xalign=1), 0, 2, 1, 1)
    grid.attach(auto, 1, 2, 1, 1)
    repo = Gtk.Entry(text=cfg.get("update_repo") or updater.DEFAULT_REPO)
    repo.set_width_chars(34)
    repo.set_tooltip_text(tr("Dépôt GitHub des versions, au format propriétaire/nom"))

    def repo_changed(e):
        v = e.get_text().strip()
        if updater.valid_repo(v):
            cfg["update_repo"], cfg["update_etag"] = v, ""
            cfg.save()
    repo.connect("changed", repo_changed)
    grid.attach(Gtk.Label(label=tr("Dépôt GitHub"), xalign=1), 0, 3, 1, 1)
    grid.attach(repo, 1, 3, 1, 1)
    status = note("", dim=False)
    grid.attach(status, 0, 4, 2, 1)
    btns = Gtk.Box(spacing=10)
    check = Gtk.Button(label=tr("Vérifier maintenant"))
    check.connect("clicked", lambda *_: win.check_updates(manual=True))
    inst = Gtk.Button(label=tr("Installer la mise à jour"))
    inst.get_style_context().add_class("suggested-action")
    inst.connect("clicked", lambda *_: win.install_update())
    btns.pack_start(check, False, False, 0)
    btns.pack_start(inst, False, False, 0)
    grid.attach(btns, 0, 5, 2, 1)
    keyline = note("", dim=True)
    grid.attach(keyline, 0, 6, 2, 1)
    grid.attach(note(tr("Chaque version est signée par SAEC. MintMail refuse tout paquet dont la signature ne correspond pas à la clé de vérification installée avec le programme "
                        "(GitHub ne sert que de transport), refuse de revenir à une ancienne version, et demande votre mot de passe administrateur pour installer. "
                        "Seule une requête anonyme est envoyée à GitHub ; désactivez la recherche automatique si vous préférez ne rien envoyer.")), 0, 7, 2, 1)

    def refresh():
        if not alive["v"]:
            return
        up = win._update
        last = cfg.get("update_last_check", 0)
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(last)) if last else tr("jamais")
        if win._update_busy:
            status.set_text(tr("Opération en cours…"))
        elif up is not None:
            status.set_text(tr("⬆ La version %s est disponible (dernière vérification : %s).") % (up.version, when))
        else:
            status.set_text(tr("Aucune mise à jour connue (dernière vérification : %s).") % when)
        ok, why = updater.can_install()
        inst.set_visible(up is not None)
        inst.set_sensitive(not win._update_busy)
        keyline.set_text(tr("Installation automatique : prête (clé de vérification présente).") if ok else
                         tr("Installation automatique désactivée : %s Vous serez seulement informé des nouvelles versions.") % explain(why))
        check.set_sensitive(not win._update_busy)
    win._update_views.append(refresh)
    grid.connect("destroy", lambda *_: alive.update(v=False))
    grid.show_all()
    refresh()
    inst.set_visible(win._update is not None)
    return grid
