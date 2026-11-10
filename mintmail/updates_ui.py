"""Interface des mises à jour : recherche automatique (une fois par jour), annonce, page de réglages, installation en un clic."""
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


class UpdateMixin:
    def _init_updates(self):
        self._update = None
        self._update_busy = False
        self._update_views = []          # fonctions à rappeler quand l'état change (page de réglages ouverte)
        GLib.timeout_add_seconds(120, lambda: (self.check_updates(), False)[1])        # 2 minutes après le démarrage
        GLib.timeout_add_seconds(3600, lambda: (self.check_updates(), True)[1])        # puis chaque heure : GitHub n'est contacté qu'une fois par jour

    def _update_changed(self):
        for f in list(self._update_views):
            try:
                f()
            except Exception:
                self._update_views.remove(f)

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
                return
            if res.state != "error":
                cfg["update_last_check"] = time.time()
                cfg["update_etag"] = res.etag if res.state == "uptodate" else ""
                cfg.save()
            if res.state == "available":
                self._update = res.update
                if manual or cfg.get("update_seen") != res.update.version:
                    cfg["update_seen"] = res.update.version
                    cfg.save()
                    self.toast.popup(tr("⬆ MintMail %s est disponible.") % res.update.version, tr("Voir"), lambda: self.show_settings("updates"), timeout=20)
            elif res.state == "uptodate":
                self._update = None
                if manual:
                    self.toast.popup(tr("MintMail est à jour (version %s).") % __version__, timeout=5)
            elif manual:
                self.toast.popup(explain(res.code), timeout=7)
            self._update_changed()
        self.run_bg(lambda: updater.check(repo, etag=etag), done)

    def install_update(self):
        up = self._update
        if up is None or self._update_busy:
            return
        ok, why = updater.can_install()
        if not ok:
            self.toast.popup(explain(why), tr("Ouvrir la page"), lambda: open_uri(self, up.page), timeout=12)
            return
        notes = (up.notes.strip()[:600] + "\n\n") if up.notes.strip() else ""
        if not self._confirm(tr("Installer MintMail %s ?") % up.version,
                             notes + tr("Le paquet est téléchargé depuis GitHub, sa signature est vérifiée avec la clé de SAEC intégrée à MintMail, puis votre mot de passe "
                                        "administrateur est demandé pour l'installer. Fermez et relancez MintMail ensuite.")):
            return
        self._update_busy = True
        self.toast.popup(tr("Téléchargement de MintMail %s…") % up.version, timeout=8)
        self._update_changed()

        def work():
            deb, sig = updater.fetch(up, updater.downloads_dir())
            code = updater.check_signature(deb, sig)
            if code:
                return False, code, ""
            return updater.install(deb, sig)

        def done(res, err):
            self._update_busy = False
            if err is not None:
                code = getattr(err, "code", "internal")
                self.toast.popup(explain(code), timeout=10)
            else:
                ok2, code, detail = res
                if ok2:
                    self._update = None
                    updater.cleanup()
                    self.toast.popup(tr("✔ MintMail %s est installé : fermez puis relancez MintMail.") % detail, timeout=0)
                else:
                    from .log import log
                    log("Mise à jour refusée / échouée : %s %s" % (code, detail))
                    self.toast.popup(explain(code), timeout=12)
            self._update_changed()
        self.run_bg(work, done)


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
