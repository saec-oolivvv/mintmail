import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib, Pango

from .util import initials, color_index, format_time, date_group


def icon(name, size=Gtk.IconSize.MENU):
    return Gtk.Image.new_from_icon_name(name, size)


def icon_button(name, tip, relief=True):
    b = Gtk.Button()
    b.set_image(icon(name, Gtk.IconSize.LARGE_TOOLBAR))
    b.set_tooltip_text(tip)
    b.set_relief(Gtk.ReliefStyle.NORMAL if relief else Gtk.ReliefStyle.NONE)
    b.set_focus_on_click(False)
    return b


class Avatar(Gtk.Label):
    def __init__(self, name, email, size=40):
        super().__init__(label=initials(name or email))
        ctx = self.get_style_context()
        ctx.add_class("avatar")
        ctx.add_class("avatar-%d" % color_index(email or name))
        self.set_size_request(size, size)
        self.set_valign(Gtk.Align.START)


class MessageRow(Gtk.ListBoxRow):
    def __init__(self, msg, on_check=None):
        super().__init__()
        self.msg = msg
        self._on_check = on_check
        self.get_style_context().add_class("msg-row")
        outer = Gtk.Box(spacing=10)
        outer.get_style_context().add_class("pad")

        self.revealer = Gtk.Revealer()
        self.revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_RIGHT)
        self.check = Gtk.CheckButton()
        self.check.set_valign(Gtk.Align.CENTER)
        self.check.connect("toggled", self._toggled)
        self.revealer.add(self.check)
        outer.pack_start(self.revealer, False, False, 0)

        outer.pack_start(Avatar(msg.sender_name, msg.sender_email), False, False, 0)

        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        top = Gtk.Box(spacing=6)
        self.sender = Gtk.Label(xalign=0)
        self.sender.set_ellipsize(Pango.EllipsizeMode.END)
        self.sender.get_style_context().add_class("sender")
        top.pack_start(self.sender, True, True, 0)
        self.icons = Gtk.Box(spacing=4)
        top.pack_start(self.icons, False, False, 0)
        self.time = Gtk.Label(xalign=1)
        self.time.get_style_context().add_class("dim")
        top.pack_end(self.time, False, False, 0)
        col.pack_start(top, False, False, 0)

        self.subject = Gtk.Label(xalign=0)
        self.subject.set_ellipsize(Pango.EllipsizeMode.END)
        self.subject.get_style_context().add_class("subject")
        col.pack_start(self.subject, False, False, 0)
        self.snippet = Gtk.Label(xalign=0)
        self.snippet.set_ellipsize(Pango.EllipsizeMode.END)
        self.snippet.get_style_context().add_class("dim")
        col.pack_start(self.snippet, False, False, 0)
        outer.pack_start(col, True, True, 0)

        self.add(outer)
        self.refresh()
        self.show_all()
        self.revealer.set_reveal_child(False)

    def _toggled(self, btn):
        if self._on_check:
            self._on_check(self, btn.get_active())

    def set_select_mode(self, on):
        self.revealer.set_reveal_child(on)

    def set_checked(self, on):
        if self.check.get_active() != on:
            self.check.handler_block_by_func(self._toggled)
            self.check.set_active(on)
            self.check.handler_unblock_by_func(self._toggled)

    def refresh(self):
        m = self.msg
        ctx = self.get_style_context()
        (ctx.add_class if m.unread else ctx.remove_class)("unread")
        self.sender.set_text(m.display_sender)
        self.subject.set_text(m.subject)
        self.snippet.set_text(m.snippet)
        self.time.set_text(format_time(m.date))
        for ch in self.icons.get_children():
            self.icons.remove(ch)
        if m.unread:
            dot = Gtk.Box()
            dot.set_size_request(9, 9)
            dot.set_valign(Gtk.Align.CENTER)
            dot.get_style_context().add_class("unread-dot")
            self.icons.pack_start(dot, False, False, 0)
        for flag, name in ((m.pinned, "view-pin-symbolic"), (m.starred, "starred-symbolic"),
                           (bool(m.attachments), "mail-attachment-symbolic"),
                           (m.snoozed_until > 0, "alarm-symbolic")):
            if flag:
                self.icons.pack_start(icon(name), False, False, 0)
        self.icons.show_all()


def group_key(msg):
    return "Épinglés" if msg.pinned else date_group(msg.date)


def row_header(row, before):
    key = group_key(row.msg)
    if before is None or group_key(before.msg) != key:
        lbl = Gtk.Label(label=key.upper(), xalign=0)
        lbl.get_style_context().add_class("group-header")
        lbl.show()
        row.set_header(lbl)
    else:
        row.set_header(None)


def row_sort(a, b):
    ma, mb = a.msg, b.msg
    if ma.pinned != mb.pinned:
        return -1 if ma.pinned else 1
    return -1 if ma.date > mb.date else (1 if ma.date < mb.date else 0)


class Toast(Gtk.Revealer):
    """Notification éphémère avec action (Annuler)."""
    def __init__(self):
        super().__init__()
        self.set_halign(Gtk.Align.CENTER)
        self.set_valign(Gtk.Align.END)
        self.set_transition_type(Gtk.RevealerTransitionType.SLIDE_UP)
        box = Gtk.Box(spacing=14)
        box.get_style_context().add_class("toast")
        self.label = Gtk.Label()
        self.button = Gtk.Button()
        box.pack_start(self.label, False, False, 0)
        box.pack_start(self.button, False, False, 0)
        self.add(box)
        self.button.connect("clicked", self._click)
        self._timer, self._cb, self._on_expire = 0, None, None
        box.show_all()

    def popup(self, text, action=None, callback=None, timeout=5, on_expire=None):
        self._finish(expired=True)   # une action en attente est validée si un nouveau toast arrive
        self.label.set_text(text)
        self._cb, self._on_expire = callback, on_expire
        self.button.set_visible(bool(action))
        if action:
            self.button.set_label(action)
        self.set_reveal_child(True)
        self._timer = GLib.timeout_add_seconds(timeout, self._expire)

    def _finish(self, expired):
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0
        cb = self._on_expire if expired else None
        self._cb = self._on_expire = None
        self.set_reveal_child(False)
        if cb:
            cb()

    def _expire(self):
        self._timer = 0
        self._finish(expired=True)
        return False

    def _click(self, _b):
        cb = self._cb
        self._on_expire = None
        self._finish(expired=False)
        if cb:
            cb()
