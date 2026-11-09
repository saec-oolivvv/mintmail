import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, GLib, Pango

from .util import initials, color_index, format_time, date_group


def icon(name, size=Gtk.IconSize.MENU):
    return Gtk.Image.new_from_icon_name(name, size)


def icon_button(name, tip, relief=True):
    b = Gtk.Button()
    b.set_image(icon(name, Gtk.IconSize.LARGE_TOOLBAR))
    b.set_tooltip_text(tip)
    b.set_relief(Gtk.ReliefStyle.NONE)
    b.get_style_context().add_class("flat-btn")
    b.set_focus_on_click(False)
    return b


class Avatar(Gtk.Label):
    def __init__(self, name, email, size=44):
        super().__init__(label=initials(name or email))
        ctx = self.get_style_context()
        ctx.add_class("avatar")
        ctx.add_class("avatar-%d" % color_index(email or name))
        self.set_size_request(size, size)
        self.set_valign(Gtk.Align.START)


SWIPE_ACTIONS = {
    "archive": ("Archiver", "folder-symbolic", "green"),
    "trash": ("Supprimer", "user-trash-symbolic", "red"),
    "snooze": ("Reporter à demain", "alarm-symbolic", "orange"),
    "read": ("Lu / non lu", "mail-read-symbolic", "blue"),
    "star": ("Favori", "starred-symbolic", "yellow"),
    "pin": ("Épingler", "view-pin-symbolic", "purple"),
    "spam": ("Spam", "mail-mark-junk-symbolic", "grey"),
    "block": ("Bloquer l'expéditeur", "action-unavailable-symbolic", "red"),
    "none": ("Aucune action", "", "grey"),
}
DEFAULT_SWIPE = {"right": "archive", "right_long": "trash", "left": "snooze", "left_long": "read"}
SWIPE_SHORT, SWIPE_LONG = 90, 230


class MessageRow(Gtk.ListBoxRow):
    """Ligne de message avec gestes de swipe (souris, pavé tactile, écran tactile)."""

    def __init__(self, msg, on_check=None, on_swipe=None, swipe_cfg=None, height=72, ai=None):
        super().__init__()
        self.msg = msg
        self.ai = ai or {}
        self._sig = None
        self._on_check = on_check
        self.on_swipe = on_swipe
        self.swipe_cfg = dict(DEFAULT_SWIPE)
        self.swipe_cfg.update(swipe_cfg or {})
        self.offset, self._anim, self._scroll_acc, self._scroll_src = 0.0, 0, 0.0, 0
        self._swiping, self._color = False, None
        self.get_style_context().add_class("msg-row")
        outer = Gtk.Box(spacing=10)
        outer.get_style_context().add_class("pad")

        self.rail = Gtk.Box()
        self.rail.get_style_context().add_class("rail")
        outer.pack_start(self.rail, False, False, 0)
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
        self.content = outer

        # couche d'actions (dessous) + carte glissante (dessus)
        self.actions = Gtk.Box()
        self.actions.get_style_context().add_class("swipe-bg")
        self.l_icon, self.l_lbl, self.r_icon, self.r_lbl = Gtk.Image(), Gtk.Label(), Gtk.Image(), Gtk.Label()
        self.l_box, self.r_box = Gtk.Box(spacing=8), Gtk.Box(spacing=8)
        self.l_box.pack_start(self.l_icon, False, False, 0)
        self.l_box.pack_start(self.l_lbl, False, False, 0)
        self.r_box.pack_start(self.r_lbl, False, False, 0)
        self.r_box.pack_start(self.r_icon, False, False, 0)
        self.l_box.set_margin_start(20)
        self.r_box.set_margin_end(20)
        self.actions.pack_start(self.l_box, False, False, 0)
        self.actions.pack_end(self.r_box, False, False, 0)
        self.actions.set_size_request(-1, height)
        self.actions.set_opacity(0)
        self.overlay = Gtk.Overlay()
        self.overlay.add(self.actions)
        self.card = Gtk.EventBox()
        self.card.get_style_context().add_class("msg-card")
        self.card.add(outer)
        self.card.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK |
                             Gdk.EventMask.BUTTON1_MOTION_MASK | Gdk.EventMask.TOUCH_MASK |
                             Gdk.EventMask.SMOOTH_SCROLL_MASK | Gdk.EventMask.SCROLL_MASK)
        self.overlay.add_overlay(self.card)
        self.overlay.connect("get-child-position", self._child_pos)
        self.add(self.overlay)

        self.drag = Gtk.GestureDrag.new(self.card)
        self.drag.set_button(1)
        self.drag.connect("drag-begin", self._drag_begin)
        self.drag.connect("drag-update", self._drag_update)
        self.drag.connect("drag-end", self._drag_end)
        self.card.connect("scroll-event", self._scroll)
        self.connect("map", self._sync_height)
        self.connect("destroy", lambda *_: self._cancel_anim())
        self.refresh()
        self.show_all()
        self.revealer.set_reveal_child(False)
        self.l_box.hide()
        self.r_box.hide()

    # ---- cases à cocher
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

    # ---- swipe
    def _child_pos(self, overlay, widget, alloc):
        if widget is not self.card:
            return False
        alloc.x, alloc.y = int(self.offset), 0
        alloc.width, alloc.height = overlay.get_allocated_width(), overlay.get_allocated_height()
        return True

    def _sync_height(self, *_):
        try:
            h = self.content.get_preferred_height()[1]
            if h > 0:
                self.actions.set_size_request(-1, h)
        except Exception:
            pass

    def _action_for(self, side, adx):
        act = self.swipe_cfg.get(side + "_long") if adx >= SWIPE_LONG else None
        return act or self.swipe_cfg.get(side) or "none"

    def _cancel_anim(self):
        if self._anim:
            GLib.source_remove(self._anim)
            self._anim = 0
        if self._scroll_src:
            GLib.source_remove(self._scroll_src)
            self._scroll_src = 0

    def _apply_offset(self):
        ctx = self.card.get_style_context()
        moving = abs(self.offset) >= 0.5
        (ctx.add_class if moving else ctx.remove_class)("swiping")
        self.actions.set_opacity(1.0 if moving else 0.0)
        self.overlay.queue_resize()

    def set_offset(self, dx):
        w = max(80, self.overlay.get_allocated_width() - 10)
        dx = max(-w, min(w, dx))
        side = "right" if dx > 0 else "left"
        act = self._action_for(side, abs(dx))
        if act == "none":
            dx *= 0.3
        label, ic, color = SWIPE_ACTIONS.get(act, SWIPE_ACTIONS["none"])
        ctx = self.actions.get_style_context()
        if self._color:
            ctx.remove_class("swipe-" + self._color)
        ctx.add_class("swipe-" + color)
        self._color = color
        box_l, box_r = (self.l_box, self.r_box)
        (self.l_lbl if dx > 0 else self.r_lbl).set_text(label)
        (self.l_icon if dx > 0 else self.r_icon).set_from_icon_name(ic or "image-missing", Gtk.IconSize.LARGE_TOOLBAR)
        box_l.set_visible(dx > 0)
        box_r.set_visible(dx < 0)
        self.offset = dx
        self._apply_offset()

    def _animate(self, target, done=None):
        if self._anim:
            GLib.source_remove(self._anim)
            self._anim = 0

        def step():
            d = target - self.offset
            if abs(d) < 2:
                self.offset, self._anim = float(target), 0
                self._apply_offset()
                if done:
                    done()
                return False
            self.offset += d * 0.35
            self._apply_offset()
            return True
        self._anim = GLib.timeout_add(16, step)

    def _finish(self):
        adx = abs(self.offset)
        side = "right" if self.offset > 0 else "left"
        act = self._action_for(side, adx)
        if adx >= SWIPE_SHORT and act != "none":
            w = self.overlay.get_allocated_width()

            def done():
                self.offset = 0.0
                self._apply_offset()
                if self.on_swipe:
                    self.on_swipe(self, act)
            self._animate(w if self.offset > 0 else -w, done)
        else:
            self._animate(0)

    def _drag_begin(self, g, x, y):
        self._swiping = False
        if self._anim:
            GLib.source_remove(self._anim)
            self._anim = 0

    def _drag_update(self, g, dx, dy):
        if not self._swiping:
            if abs(dx) > 12 and abs(dx) > abs(dy) * 1.4:
                self._swiping = True
                g.set_state(Gtk.EventSequenceState.CLAIMED)
            else:
                return
        self.set_offset(dx)

    def _drag_end(self, g, dx, dy):
        if self._swiping:
            self._swiping = False
            self._finish()

    def _scroll(self, w, ev):
        """Glissement à deux doigts sur pavé tactile."""
        if ev.direction != Gdk.ScrollDirection.SMOOTH:
            return False
        ok, dx, dy = ev.get_scroll_deltas()
        if not ok or (abs(dx) <= abs(dy) and not self._scroll_acc):
            return False
        sign = 1 if self.swipe_cfg.get("invert") else -1
        self._scroll_acc += sign * dx * 22
        self.set_offset(self._scroll_acc)
        if self._scroll_src:
            GLib.source_remove(self._scroll_src)
        self._scroll_src = GLib.timeout_add(170, self._scroll_end)
        return True

    def _scroll_end(self):
        self._scroll_src, self._scroll_acc = 0, 0.0
        self._finish()
        return False

    def signature(self):
        m = self.msg
        return (m.unread, m.starred, m.pinned, m.snoozed_until > 0, bool(m.attachments), m.subject, m.snippet,
                m.date, m.category, getattr(m, "thread_count", 1), self.ai.get("summary"), self.ai.get("priority"), bool(self.ai.get("spam")))

    def update_msg(self, msg, ai=None):
        """Met à jour la ligne en place (sans la reconstruire) ; retourne True si quelque chose a changé."""
        self.msg = msg
        if ai is not None:
            self.ai = ai
        if self.signature() != self._sig:
            self.refresh()
            return True
        return False

    def refresh(self):
        m = self.msg
        self._sig = self.signature()
        ctx = self.get_style_context()
        (ctx.add_class if m.unread else ctx.remove_class)("unread")
        self.sender.set_text(m.display_sender)
        self.subject.set_text(m.subject)
        summary = (self.ai.get("summary") or "").strip()
        sctx = self.snippet.get_style_context()
        if summary:
            self.snippet.set_text("✨ " + summary)
            sctx.add_class("ai-line")
        else:
            self.snippet.set_text(m.snippet)
            sctx.remove_class("ai-line")
        self.time.set_text(format_time(m.date))
        rctx = self.rail.get_style_context()
        for cls in ("rail-spam", "rail-p3", "rail-unread", "rail-news", "rail-notif"):
            rctx.remove_class(cls)
        if self.ai.get("spam"):
            rctx.add_class("rail-spam")
        elif self.ai.get("priority") == 3:
            rctx.add_class("rail-p3")
        elif m.unread:
            rctx.add_class("rail-unread")
        elif m.category in ("news", "notif"):
            rctx.add_class("rail-" + m.category)
        for ch in self.icons.get_children():
            self.icons.remove(ch)
        n = getattr(m, "thread_count", 1)
        if n > 1:   # conversation : nombre de messages
            cnt = Gtk.Label(label=str(n))
            cnt.set_tooltip_text("%d messages dans cette conversation" % n)
            cnt.get_style_context().add_class("badge-thread")
            self.icons.pack_start(cnt, False, False, 0)
        if self.ai.get("spam"):
            lab = Gtk.Label(label="Suspect")
            lab.get_style_context().add_class("badge-suspect")
            self.icons.pack_start(lab, False, False, 0)
        elif self.ai.get("priority") == 3:
            lab = Gtk.Label(label="Important")
            lab.get_style_context().add_class("badge-important")
            self.icons.pack_start(lab, False, False, 0)
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
        lbl = Gtk.Label(label=key, xalign=0)
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


def row_at_event(lb, ev):
    """Ligne de liste sous un clic. Les coordonnées d'un évènement sont relatives à la FENÊTRE qui l'a reçu (ici la carte du
    message, pas la liste) : get_row_at_y(ev.y) retombait presque toujours sur la première ligne (le dernier message reçu).
    On remonte donc depuis le widget qui a réellement reçu le clic ; à défaut, on convertit les coordonnées dans le repère de la liste."""
    w = Gtk.get_event_widget(ev)
    node = w
    while node is not None and node is not lb:
        if isinstance(node, Gtk.ListBoxRow):
            return node
        node = node.get_parent()
    if w is not None:
        try:
            res = w.translate_coordinates(lb, int(ev.x), int(ev.y))
            if res:
                return lb.get_row_at_y(int(res[-1]))
        except Exception:
            pass
    return lb.get_row_at_y(int(ev.y))
