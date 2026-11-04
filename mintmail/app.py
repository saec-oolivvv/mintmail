import sys
from urllib.parse import urlparse, parse_qs, unquote

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gio, GLib

from . import APP_ID, APP_NAME, __version__
from .store import Config, Cache


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
        return self.win

    def do_activate(self):
        self._window().present()

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
    return MintMailApp().run(argv)
