import sys
from urllib.parse import urlparse, parse_qs, unquote

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gio, GLib

from . import APP_ID, APP_NAME, __version__
from .store import Config, Cache, CONFIG_DIR, DATA_DIR
from .log import install_hook, LOG, log


class MintMailApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_OPEN)
        GLib.set_application_name(APP_NAME)
        self.win = None

    def _window(self):
        if not self.win:
            from .window import MainWindow
            Gtk.Window.set_default_icon_name("mintmail")
            self.win = MainWindow(self, Config(), Cache())
            install_hook(lambda e: GLib.idle_add(
                lambda: (self.win.toast.popup("Erreur interne : %s (menu ☰ → Journal d'erreurs)" % str(e)[:70], timeout=8), False)[1]))
        return self.win

    def do_activate(self):
        win = self._window()
        win.present()
        if "--settings" in sys.argv:
            GLib.idle_add(lambda: (win.show_settings(window="--window" in sys.argv), False)[1])

    def do_open(self, files, n_files, hint):
        win = self._window()
        win.present()
        for f in files:
            uri = f.get_uri()
            if uri.startswith("mailto:"):
                u = urlparse(uri)
                q = parse_qs(u.query)
                win.compose(to=unquote(u.path), cc=",".join(q.get("cc", [])),
                            subject=" ".join(q.get("subject", [])),
                            body_html=" ".join(q.get("body", [])).replace("\n", "<br>"))


def main(argv=None):
    argv = argv if argv is not None else sys.argv
    if "--version" in argv:
        print("%s %s" % (APP_NAME, __version__))
        return 0
    if "--diagnose" in argv:
        return diagnose()
    log("Démarrage MintMail %s" % __version__)
    return MintMailApp().run([a for a in argv if a not in ("--settings", "--window")])


def diagnose():
    print("MintMail %s" % __version__)
    print("Config :", CONFIG_DIR / "config.json")
    print("Données :", DATA_DIR)
    print("Journal :", LOG)
    try:
        print("GTK : %d.%d.%d" % (Gtk.get_major_version(), Gtk.get_minor_version(), Gtk.get_micro_version()))
    except Exception as e:
        print("GTK : erreur", e)
    try:
        from .reader import HAS_WEBKIT
        print("WebKit :", "oui" if HAS_WEBKIT else "non (lecture en texte brut)")
    except Exception as e:
        print("WebKit : erreur", e)
    try:
        import keyring
        print("Trousseau :", keyring.get_keyring())
    except Exception as e:
        print("Trousseau : indisponible (%s) — mots de passe stockés dans le fichier de config" % type(e).__name__)
    return 0
