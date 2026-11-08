"""Panneau « Assistant » : conversation avec l'IA, propositions d'actions à confirmer."""
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib, GObject

from .widgets import icon, icon_button

SUGGESTIONS = ["Résume ma boîte", "Quels messages sont urgents ?", "Archive les newsletters déjà lues",
               "Mets en spam les mails promotionnels", "Rédige une relance polie", "Crée une règle pour les notifications"]


class AssistantPanel(Gtk.Box):
    __gsignals__ = {"ask": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
                    "close": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.get_style_context().add_class("assistant")
        self.set_size_request(340, -1)
        head = Gtk.Box(spacing=8)
        head.get_style_context().add_class("assistant-head")
        title = Gtk.Label(xalign=0)
        title.set_markup("<b>✨ Assistant</b>")
        head.pack_start(title, True, True, 0)
        clear = icon_button("edit-clear-all-symbolic", "Nouvelle conversation", relief=False)
        clear.connect("clicked", lambda *_: self.clear())
        close = icon_button("window-close-symbolic", "Fermer (Ctrl+J)", relief=False)
        close.connect("clicked", lambda *_: self.emit("close"))
        head.pack_end(close, False, False, 0)
        head.pack_end(clear, False, False, 0)
        self.pack_start(head, False, False, 0)

        self.log = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.scroll = Gtk.ScrolledWindow()
        self.scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroll.add(self.log)
        self.pack_start(self.scroll, True, True, 0)

        self.chips = Gtk.FlowBox()
        self.chips.set_selection_mode(Gtk.SelectionMode.NONE)
        self.chips.set_max_children_per_line(2)
        self.chips.set_margin_start(10)
        self.chips.set_margin_end(10)
        for t in SUGGESTIONS:
            b = Gtk.Button(label=t)
            b.get_style_context().add_class("ai-chip")
            b.connect("clicked", lambda _b, tx=t: self.emit("ask", tx))
            self.chips.add(b)
        self.pack_start(self.chips, False, False, 6)

        row = Gtk.Box(spacing=6)
        row.set_border_width(10)
        self.entry = Gtk.Entry()
        self.entry.set_placeholder_text("Demandez n'importe quoi à votre boîte mail…")
        self.entry.connect("activate", self._send)
        send = Gtk.Button()
        send.add(icon("mail-send-symbolic"))
        send.get_style_context().add_class("ai-btn")
        send.connect("clicked", self._send)
        row.pack_start(self.entry, True, True, 0)
        row.pack_start(send, False, False, 0)
        self.pack_start(row, False, False, 0)
        self._busy = None
        self.show_all()

    def _send(self, *_):
        t = self.entry.get_text().strip()
        if t:
            self.entry.set_text("")
            self.emit("ask", t)

    def _scroll_bottom(self):
        adj = self.scroll.get_vadjustment()
        adj.set_value(adj.get_upper() - adj.get_page_size())
        return False

    def _add(self, widget):
        self.chips.hide()
        self.log.pack_start(widget, False, False, 0)
        widget.show_all()
        GLib.idle_add(self._scroll_bottom)

    def _bubble(self, text, kind):
        lab = Gtk.Label(label=text, xalign=0)
        lab.set_line_wrap(True)
        lab.set_selectable(True)
        lab.set_max_width_chars(40)
        lab.get_style_context().add_class("bubble-" + kind)
        lab.set_halign(Gtk.Align.END if kind == "user" else Gtk.Align.START)
        return lab

    def add_user(self, text):
        self._add(self._bubble(text, "user"))

    def add_ai(self, text):
        lab = self._bubble(text, "ai")
        self._add(lab)
        return lab

    def set_busy(self, busy):
        if busy and self._busy is None:
            self._busy = self._bubble("…", "ai")
            self._add(self._busy)
        elif not busy and self._busy is not None:
            self.log.remove(self._busy)
            self._busy = None
        self.entry.set_sensitive(not busy)

    def add_plan(self, items, run_all):
        """items : [(description, callable)] ; chaque action est confirmée par un clic."""
        for desc, fn in items:
            row = Gtk.Box(spacing=8)
            row.get_style_context().add_class("plan-row")
            lab = Gtk.Label(label=desc, xalign=0)
            lab.set_line_wrap(True)
            lab.set_max_width_chars(28)
            btn = Gtk.Button(label="Exécuter")
            btn.get_style_context().add_class("pill")

            def go(b, f=fn, l=lab):
                b.set_sensitive(False)
                b.set_label("✓ Fait")
                f()
            btn.connect("clicked", go)
            row.pack_start(lab, True, True, 0)
            row.pack_end(btn, False, False, 0)
            self._add(row)
        if len(items) > 1:
            allb = Gtk.Button(label="Tout exécuter")
            allb.get_style_context().add_class("ai-btn")
            allb.set_halign(Gtk.Align.END)
            allb.set_margin_end(10)
            allb.connect("clicked", lambda b: (b.set_sensitive(False), run_all()))
            self._add(allb)

    def clear(self):
        for ch in self.log.get_children():
            self.log.remove(ch)
        self._busy = None
        self.entry.set_sensitive(True)
        self.chips.show()

    def focus_entry(self):
        self.entry.grab_focus()
