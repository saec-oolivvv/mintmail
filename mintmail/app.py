import os
import sys
from urllib.parse import urlparse, parse_qs, unquote

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gio, GLib

from . import APP_ID, APP_NAME, __version__
from .store import Config, Cache
from .log import install_hook, LOG, log, log_exception


class MintMailApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_OPEN)
        GLib.set_application_name(APP_NAME)
        self.win = None

    def _window(self):
        if not self.win:
            try:
                from .window import MainWindow
                Gtk.Window.set_default_icon_name("mintmail")
                self.win = MainWindow(self, Config(), Cache())
            except Exception as e:
                self._startup_failure(e)
                return None
            install_hook(lambda e: GLib.idle_add(
                lambda: (self.win.toast.popup("Erreur interne : %s (menu ☰ → Journal d'erreurs)" % str(e)[:70], timeout=8), False)[1]))
        return self.win

    def _startup_failure(self, exc):
        """Démarrage impossible : message clair, journal, et possibilité de repartir de données propres (sauvegardées)."""
        log_exception("démarrage de la fenêtre")
        d = Gtk.MessageDialog(message_type=Gtk.MessageType.ERROR, text="MintMail n'a pas pu démarrer",
                              secondary_text="%s\n\nDétails : %s\nDiagnostic : /usr/bin/mintmail --diagnose\n\n"
                                             "Si le problème vient de vos données, vous pouvez les mettre de côté "
                                             "(rien n'est supprimé) et relancer." % (exc, LOG))
        d.add_buttons("Quitter", Gtk.ResponseType.CLOSE, "Mettre de côté réglages et cache, puis relancer", Gtk.ResponseType.APPLY)
        r = d.run()
        d.destroy()
        if r == Gtk.ResponseType.APPLY:
            from .entry import reset_data
            reset_data()
            os.execv(sys.executable, [sys.executable, "-m", "mintmail"])

    def do_activate(self):
        win = self._window()
        if win is None:
            self.quit()
            return
        win.present()
        if getattr(self, "open_settings", False):
            GLib.idle_add(lambda: (win.show_settings(window=self.settings_window), False)[1])

    def do_open(self, files, n_files, hint):
        win = self._window()
        if win is None:
            return
        win.present()
        for f in files:
            uri = f.get_uri()
            if uri.startswith("mailto:"):
                u = urlparse(uri)
                q = parse_qs(u.query)
                win.compose(to=unquote(u.path), cc=",".join(q.get("cc", [])),
                            subject=" ".join(q.get("subject", [])),
                            body_html=" ".join(q.get("body", [])).replace("\n", "<br>"))


def run(argv, settings=False, window=False):
    log("Interface GTK %d.%d" % (Gtk.get_major_version(), Gtk.get_minor_version()))
    app = MintMailApp()
    app.open_settings, app.settings_window = settings, window
    return app.run(argv)
