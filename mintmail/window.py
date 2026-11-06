import datetime
import html
import re
import threading
import time
import uuid

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, Gio, GLib

from . import __version__, APP_NAME
from .backend import make_backend
from .compose import ComposeWindow
from .models import Message, Outgoing
from .store import DATA_DIR
from .log import log_exception, tail, LOG
from .reader import Reader
from .settings import SettingsPage
from .style import build_css
from .util import (format_full, normalize_subject, sanitize_html, split_addresses, text_to_html)
from .widgets import (MessageRow, Toast, icon, icon_button, row_header, row_sort, SWIPE_ACTIONS)

NAV = [
    ("inbox", "Boîte intelligente", "mail-inbox-symbolic"),
    ("unread", "Non lus", "mail-unread-symbolic"),
    ("starred", "Favoris", "starred-symbolic"),
    ("pinned", "Épinglés", "view-pin-symbolic"),
    ("snoozed", "Reportés", "alarm-symbolic"),
    ("drafts", "Brouillons", "document-edit-symbolic"),
    ("sent", "Envoyés", "mail-send-symbolic"),
    ("archive", "Archives", "folder-symbolic"),
    ("spam", "Spam", "mail-mark-junk-symbolic"),
    ("trash", "Corbeille", "user-trash-symbolic"),
]
TITLES = {k: v for k, v, _ in NAV}
CATEGORIES = [(None, "Tout"), ("people", "Personnes"), ("notif", "Notifications"), ("news", "Newsletters")]
DEMO_ACCOUNT = {"id": "demo", "name": "Démo", "email": "demo@mintmail.local", "demo": True,
                "signature_html": "<i>Envoyé avec MintMail</i>"}
NARROW, RAIL_BELOW, HIDE_BELOW = 700, 1250, 900


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, app, config, cache):
        super().__init__(application=app, title=APP_NAME)
        self.config, self.cache = config, cache
        self.view = config["last_view"] if config["last_view"] in TITLES else "inbox"
        self.account, self.category = "all", None
        self.unread_only = self.att_only = self.select_mode = False
        self.narrow = self.reader_open = False
        self._zone, self.sidebar_mode, self._reflow_src = None, "full", 0
        self._saved_rows, self.nav_labels = [], []
        self.search, self._search_src = "", 0
        self._loading, self._pending, self._sync_busy = False, 0, False
        self._backends, self._sending, self.rows = {}, set(), {}
        self._last_sync, self._ticks = 0.0, 0
        self.is_dark = False
        s = Gtk.Settings.get_default()
        self._system_dark = bool(s.get_property("gtk-application-prefer-dark-theme")) or \
            "dark" in (s.get_property("gtk-theme-name") or "").lower()
        self.css = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), self.css,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.set_default_size(config["width"], config["height"])
        self.set_size_request(360, 420)
        self._build()
        self.apply_settings()
        self.connect("size-allocate", self._on_size)
        self.connect("key-press-event", self._on_key)
        self.connect("delete-event", self._on_close)
        self.show_all()
        threading.Thread(target=self.config.preload_passwords, daemon=True).start()
        self.apply_layout()
        self.reader.zoom = self.config["zoom"]
        self.reader.apply_zoom()
        self.demo_banner.set_visible(not self.config["accounts"])
        self.cat_sw.set_visible(self.view == "inbox")
        self.reload_list()
        self.update_counts()
        GLib.idle_add(lambda: (self.sync(), False)[1])
        GLib.timeout_add_seconds(1, self._tick)

    # ------------------------------------------------------------------ UI
    def _build(self):
        hb = Gtk.HeaderBar()
        hb.set_show_close_button(True)
        self.set_titlebar(hb)
        self.side_toggle = Gtk.ToggleButton()
        self.side_toggle.set_image(icon("view-sidebar-start-symbolic", Gtk.IconSize.LARGE_TOOLBAR))
        self.side_toggle.set_tooltip_text("Afficher / masquer le panneau latéral")
        self.side_toggle.set_active(True)
        self.side_toggle.connect("toggled", self._side_toggled)
        hb.pack_start(self.side_toggle)
        comp = Gtk.Button()
        comp.set_image(icon("mail-message-new-symbolic", Gtk.IconSize.LARGE_TOOLBAR))
        comp.set_tooltip_text("Nouveau message (C)")
        comp.get_style_context().add_class("round-accent")
        comp.connect("clicked", lambda *_: self.compose())
        hb.pack_start(comp)
        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_placeholder_text("Rechercher…  (from:, is:unread, has:attachment)")
        self.search_entry.set_width_chars(22)
        self.search_entry.get_style_context().add_class("mm-search")
        self.search_entry.connect("search-changed", self._search_changed)
        hb.set_custom_title(self.search_entry)
        menu_btn = Gtk.MenuButton()
        menu_btn.set_image(icon("open-menu-symbolic", Gtk.IconSize.LARGE_TOOLBAR))
        menu = Gtk.Menu()
        for label, fn in (("Palette de commandes (Ctrl+K)", self.show_palette), ("Paramètres (Ctrl+,)", self.show_settings), ("Paramètres dans une fenêtre séparée", lambda: self.show_settings(window=True)),
                          ("Basculer clair / sombre", self.toggle_theme), ("Tout marquer comme lu", self.mark_all_read),
                          ("Journal d'erreurs", self.show_log), ("À propos", self.show_about)):
            it = Gtk.MenuItem(label=label)
            it.connect("activate", lambda _i, f=fn: f())
            menu.append(it)
        menu.show_all()
        menu_btn.set_popup(menu)
        hb.pack_end(menu_btn)
        gear = Gtk.Button()
        gb = Gtk.Box(spacing=6)
        gb.pack_start(icon("preferences-system-symbolic"), False, False, 0)
        gb.pack_start(Gtk.Label(label="Paramètres"), False, False, 0)
        gear.add(gb)
        gear.set_tooltip_text("Paramètres (Ctrl+,)")
        gear.get_style_context().add_class("pill")
        gear.connect("clicked", lambda *_: self.show_settings())
        hb.pack_end(gear)
        self.refresh_btn = icon_button("view-refresh-symbolic", "Actualiser (Ctrl+R)")
        self.refresh_btn.connect("clicked", lambda *_: self.sync(True))
        hb.pack_end(self.refresh_btn)
        self.sel_btn = Gtk.ToggleButton()
        self.sel_btn.set_image(icon("object-select-symbolic", Gtk.IconSize.LARGE_TOOLBAR))
        self.sel_btn.set_tooltip_text("Mode sélection multiple")
        self.sel_btn.connect("toggled", self._toggle_select_mode)
        hb.pack_end(self.sel_btn)
        lay = Gtk.MenuButton()
        lay.set_image(icon("view-dual-symbolic", Gtk.IconSize.LARGE_TOOLBAR))
        lay.set_tooltip_text("Disposition")
        lm = Gtk.Menu()
        for label, fn in (("Colonnes : liste | lecture", lambda: self.set_layout("columns")),
                          ("Lecture en bas", lambda: self.set_layout("bottom")),
                          ("Liste seule (lecture plein écran)", lambda: self.set_layout("list")),
                          ("Barre latérale réduite / étendue", self.toggle_rail)):
            it = Gtk.MenuItem(label=label)
            it.connect("activate", lambda _i, f=fn: f())
            lm.append(it)
        lm.show_all()
        lay.set_popup(lm)
        hb.pack_end(lay)

        # barre latérale
        self.sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.sidebar.get_style_context().add_class("mm-sidebar")
        self.sidebar.set_size_request(190, -1)
        self.compose_btn = Gtk.Button()
        cbox = Gtk.Box(spacing=8)
        cbox.set_halign(Gtk.Align.CENTER)
        cbox.pack_start(icon("mail-message-new-symbolic", Gtk.IconSize.LARGE_TOOLBAR), False, False, 0)
        self.compose_lbl = Gtk.Label(label="Nouveau message")
        cbox.pack_start(self.compose_lbl, False, False, 0)
        self.compose_btn.add(cbox)
        self.compose_btn.get_style_context().add_class("compose-btn")
        self.compose_btn.connect("clicked", lambda *_: self.compose())
        self.sidebar.pack_start(self.compose_btn, False, False, 0)
        self.acc_combo = Gtk.ComboBoxText()
        self.acc_combo.set_margin_start(10)
        self.acc_combo.set_margin_end(10)
        self.acc_combo.set_margin_top(10)
        self.acc_combo.connect("changed", self._account_changed)
        self.sidebar.pack_start(self.acc_combo, False, False, 0)
        self.nav = Gtk.ListBox()
        self.nav.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.nav.set_activate_on_single_click(True)
        self.badges = {}
        self.nav_labels = []
        for vid, label, ic in NAV:
            r = Gtk.ListBoxRow()
            r.view = vid
            r.get_style_context().add_class("nav-row")
            b = Gtk.Box(spacing=10)
            b.pack_start(icon(ic), False, False, 0)
            lab = Gtk.Label(label=label, xalign=0)
            self.nav_labels.append(lab)
            b.pack_start(lab, True, True, 0)
            badge = Gtk.Label()
            badge.get_style_context().add_class("badge")
            badge.set_no_show_all(True)
            b.pack_end(badge, False, False, 0)
            self.badges[vid] = badge
            r.add(b)
            self.nav.add(r)
            if vid == self.view:
                self._nav_initial = r
        self.nav.connect("row-selected", self._nav_selected)
        nsw = Gtk.ScrolledWindow()
        nsw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        nsw.add(self.nav)
        self.sidebar.pack_start(nsw, True, True, 0)
        self.sidebar.pack_end(self._sidebar_footer(), False, False, 0)

        # liste
        self.list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.list_box.get_style_context().add_class("mm-list")
        self.list_box.set_size_request(260, -1)
        bar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        bar.get_style_context().add_class("mm-listbar")
        self.title_lbl = Gtk.Label(xalign=0)
        self.title_lbl.set_markup("<b>Boîte intelligente</b>")
        self.title_lbl.get_style_context().add_class("list-title")
        bar.pack_start(self.title_lbl, False, False, 0)
        self.cat_box = Gtk.Box(spacing=6)
        first = None
        for key, label in CATEGORIES:
            rb = Gtk.RadioButton.new_with_label_from_widget(first, label)
            rb.set_mode(False)
            rb.get_style_context().add_class("cat-tab")
            first = first or rb
            rb.connect("toggled", self._category_toggled, key)
            self.cat_box.pack_start(rb, True, True, 0)
        self.cat_sw = Gtk.ScrolledWindow()
        self.cat_sw.set_policy(Gtk.PolicyType.EXTERNAL, Gtk.PolicyType.NEVER)
        self.cat_sw.add(self.cat_box)
        bar.pack_start(self.cat_sw, False, False, 0)
        flt = Gtk.Box(spacing=6)
        self.f_unread = Gtk.ToggleButton(label="Non lus")
        self.f_att = Gtk.ToggleButton(label="Pièces jointes")
        for w, a in ((self.f_unread, "unread_only"), (self.f_att, "att_only")):
            w.connect("toggled", lambda b, attr=a: (setattr(self, attr, b.get_active()), self.reload_list()))
            w.get_style_context().add_class("pill-toggle")
            flt.pack_start(w, False, False, 0)
        bar.pack_start(flt, False, False, 0)
        self.list_box.pack_start(bar, False, False, 0)
        self.demo_banner = Gtk.Box(spacing=8)
        self.demo_banner.get_style_context().add_class("banner")
        self.demo_banner.pack_start(Gtk.Label(label="Mode démonstration"), True, True, 0)
        ab = Gtk.Button(label="Ajouter mon compte")
        ab.connect("clicked", lambda *_: self.show_settings())
        self.demo_banner.pack_end(ab, False, False, 0)
        self.list_box.pack_start(self.demo_banner, False, False, 0)

        self.bulk_rev = Gtk.Revealer()
        bulk = Gtk.Box(spacing=6)
        bulk.get_style_context().add_class("bulkbar")
        self.bulk_lbl = Gtk.Label()
        bulk.pack_start(self.bulk_lbl, True, True, 0)
        for label, fn in (("Archiver", lambda: self.move_messages(self.selected_msgs(), "archive")),
                          ("Supprimer", lambda: self.move_messages(self.selected_msgs(), "trash")),
                          ("Lu", lambda: self.set_unread(self.selected_msgs(), False)),
                          ("Non lu", lambda: self.set_unread(self.selected_msgs(), True)),
                          ("★", lambda: self.set_flag(self.selected_msgs(), "starred", True)),
                          ("Tout", lambda: self.listbox.select_all()),
                          ("✕", lambda: self.listbox.unselect_all())):
            b = Gtk.Button(label=label)
            b.connect("clicked", lambda _b, f=fn: f())
            bulk.pack_start(b, False, False, 0)
        bsw = Gtk.ScrolledWindow()
        bsw.set_policy(Gtk.PolicyType.EXTERNAL, Gtk.PolicyType.NEVER)
        bsw.add(bulk)
        self.bulk_rev.add(bsw)
        self.list_box.pack_start(self.bulk_rev, False, False, 0)

        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.MULTIPLE)
        self.listbox.set_sort_func(row_sort)
        self.listbox.set_header_func(row_header)
        self.listbox.connect("selected-rows-changed", self._on_selection)
        self.listbox.connect("row-activated", self._on_activated)
        self.listbox.connect("button-press-event", self._on_list_click)
        self.listbox.connect("button-press-event", self._on_list_context)
        sw = Gtk.ScrolledWindow()
        sw.add(self.listbox)
        self.empty_lbl = Gtk.Label(label="Aucun message")
        self.empty_lbl.get_style_context().add_class("empty-state")
        self.list_stack = Gtk.Stack()
        self.list_stack.add_named(sw, "list")
        self.list_stack.add_named(self.empty_lbl, "empty")
        self.list_box.pack_start(self.list_stack, True, True, 0)

        self.reader = Reader(self.build_snooze_menu)
        self.reader.connect("action", self._reader_action)
        self.reader.connect("quick-reply", lambda _r, t: self.quick_reply(t))

        self.paned_in = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self.paned_in.set_wide_handle(True)
        self.paned_in.pack1(self.list_box, False, False)
        self.paned_in.pack2(self.reader, True, False)
        self.paned_in.set_position(self.config["pos_cols"])
        self.paned_out = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self.paned_out.set_wide_handle(True)
        self.paned_out.pack1(self.sidebar, False, False)
        self.paned_out.pack2(self.paned_in, True, False)
        self.paned_out.set_position(self.config["side_width"])
        body = Gtk.Box()
        body.pack_start(self.paned_out, True, True, 0)
        body.get_style_context().add_class("mm-root")
        self.root_stack = Gtk.Stack()
        self.root_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.root_stack.set_transition_duration(150)
        self.root_stack.add_named(body, "mail")
        overlay = Gtk.Overlay()
        overlay.add(self.root_stack)
        self.toast = Toast()
        overlay.add_overlay(self.toast)
        self.add(overlay)
        self._fill_accounts()
        self._rebuild_saved()
        self.nav.select_row(self._nav_initial)

    def _sidebar_footer(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_border_width(10)
        self.status = Gtk.Label(xalign=0)
        self.status.get_style_context().add_class("dim")
        self.status.set_line_wrap(True)
        box.pack_start(self.status, False, False, 0)
        b = self.settings_btn = Gtk.Button(label="Paramètres")
        b.set_image(icon("preferences-system-symbolic"))
        b.set_always_show_image(True)
        b.set_relief(Gtk.ReliefStyle.NONE)
        b.connect("clicked", lambda *_: self.show_settings())
        box.pack_start(b, False, False, 0)
        rail = icon_button("pan-start-symbolic", "Réduire / étendre la barre latérale", relief=False)
        rail.connect("clicked", lambda *_: self.toggle_rail())
        box.pack_start(rail, False, False, 0)
        return box

    # --------------------------------------------------------------- comptes
    def accounts(self):
        return self.config["accounts"] or [DEMO_ACCOUNT]

    def backend(self, aid):
        if aid not in self._backends:
            acc = next((a for a in self.accounts() if a["id"] == aid), None)
            if not acc:
                raise RuntimeError("Compte introuvable")
            self._backends[aid] = make_backend(acc, self.config)
        return self._backends[aid]

    def _fill_accounts(self):
        self.acc_combo.handler_block_by_func(self._account_changed)
        self.acc_combo.remove_all()
        self.acc_combo.append("all", "Tous les comptes")
        for a in self.accounts():
            self.acc_combo.append(a["id"], "%s" % (a.get("name") or a["email"]))
        self.acc_combo.set_active_id(self.account if self.account in [a["id"] for a in self.accounts()] else "all")
        self.account = self.acc_combo.get_active_id()
        self.acc_combo.handler_unblock_by_func(self._account_changed)

    def accounts_changed(self):
        self._backends.clear()
        if self.config["accounts"]:
            self.cache.delete_account("demo")
        else:
            try:
                (DATA_DIR / "demo_seeded").unlink()   # le mode démo pourra se re-semer
            except OSError:
                pass
        self._fill_accounts()
        self.demo_banner.set_visible(not self.config["accounts"])
        self.reload_list()
        self.update_counts()
        self.sync(True)

    def _account_changed(self, combo):
        self.account = combo.get_active_id() or "all"
        self.reload_list()
        self.update_counts()

    # -------------------------------------------------------------- réglages
    def apply_settings(self):
        theme = self.config["theme"]
        self.is_dark = theme == "dark" or (theme == "system" and self._system_dark)
        Gtk.Settings.get_default().set_property("gtk-application-prefer-dark-theme", self.is_dark)
        base, fancy = build_css(self.is_dark, self.config["accent"], self.config["density"])
        for data in (base + fancy, base):   # repli sans effets si un thème GTK refuse la version raffinée
            try:
                self.css.load_from_data(data)
                break
            except GLib.Error as e:
                print("CSS :", e)
        self.reader.dark = self.is_dark
        if self.reader.msg:
            self.reader.show_message(self.reader.msg, self.config["load_images"])
        if hasattr(self, "listbox"):
            self.reload_list()

    def toggle_theme(self):
        self.config["theme"] = "light" if self.is_dark else "dark"
        self.config.save()
        self.apply_settings()

    def show_settings(self, page=None, window=False):
        """Page des paramètres dans la fenêtre (Échap / « Retour »). Repli : fenêtre séparée, puis message d'erreur."""
        try:
            if window:
                self._settings_window(page)
                return
            cur = self.root_stack.get_child_by_name("settings")
            if cur is None:
                cur = SettingsPage(self, page)
                self.root_stack.add_named(cur, "settings")
                cur.show_all()
            elif page:
                cur.show_page(page)
            self.root_stack.set_visible_child_name("settings")
        except Exception as e:
            log_exception("show_settings")
            try:
                self._settings_window(page)
            except Exception as e2:
                log_exception("show_settings (fenêtre séparée)")
                self.show_error("Impossible d'ouvrir les paramètres", e2 or e)

    def _settings_window(self, page=None):
        w = getattr(self, "_swin", None)
        if w is not None:
            w.present()
            if page:
                w.page.show_page(page)
            return
        w = Gtk.Window(title="Paramètres de MintMail")
        w.set_transient_for(self)
        w.set_default_size(960, 660)
        w.page = SettingsPage(self, page)
        w.add(w.page)
        w.show_all()
        self._swin = w
        w.connect("destroy", lambda *_: setattr(self, "_swin", None))

    def close_settings(self):
        sw = getattr(self, "_swin", None)
        if sw is not None:
            sw.destroy()
            return
        cur = self.root_stack.get_child_by_name("settings")
        self.root_stack.set_visible_child_name("mail")
        if cur is not None:
            self.root_stack.remove(cur)
            cur.destroy()

    def show_error(self, title, exc):
        d = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.ERROR,
                              text=title, secondary_text="%s\n\nDétails dans le journal : %s" % (exc, LOG))
        d.add_buttons("Fermer", Gtk.ResponseType.CLOSE)
        d.run()
        d.destroy()

    def show_log(self):
        d = Gtk.Dialog(title="Journal d'erreurs", transient_for=self, modal=True)
        d.add_buttons("Fermer", Gtk.ResponseType.CLOSE)
        d.set_default_size(720, 420)
        tv = Gtk.TextView()
        tv.set_editable(False)
        tv.set_monospace(True)
        tv.get_buffer().set_text("%s\n\n%s" % (LOG, tail()))
        sw = Gtk.ScrolledWindow()
        sw.add(tv)
        d.get_content_area().pack_start(sw, True, True, 0)
        d.show_all()
        d.run()
        d.destroy()

    def show_about(self):
        d = Gtk.AboutDialog(transient_for=self, modal=True)
        d.set_program_name(APP_NAME)
        d.set_version(__version__)
        d.set_comments("Client mail moderne pour Linux Mint.\nBoîte intelligente, reports, envoi annulable, signatures HTML.")
        d.set_website("https://saec.me")
        d.set_logo_icon_name("mintmail")
        d.run()
        d.destroy()

    # ------------------------------------------------------------ navigation
    def _nav_selected(self, lb, row):
        if not row:
            return
        self.view = row.view
        if not self.view.startswith("saved:"):
            self.config["last_view"] = self.view
        self.search_entry.set_text("")
        self.search = ""
        self.cat_sw.set_visible(self.view == "inbox")
        self.title_lbl.set_markup("<b>%s</b>" % GLib.markup_escape_text(self._view_title()))
        self.listbox.unselect_all()
        self.reader.show_empty()
        self.reader_open = False
        self._layout()
        self.reload_list()
        if self._zone == 0:
            self.side_toggle.set_active(False)
        if self.view in ("sent", "archive", "trash", "spam"):
            self.sync(folders=(self.view,), quiet=True)

    def _category_toggled(self, btn, key):
        if btn.get_active():
            self.category = key
            self.reload_list()

    def _search_changed(self, entry):
        if self._search_src:
            GLib.source_remove(self._search_src)

        def go():
            self._search_src = 0
            self.search = entry.get_text().strip()
            self.title_lbl.set_markup("<b>Résultats</b>" if self.search else "<b>%s</b>" % GLib.markup_escape_text(self._view_title()))
            self.cat_sw.set_visible(self.view == "inbox" and not self.search)
            self.reload_list()
            return False
        self._search_src = GLib.timeout_add(250, go)

    # ----------------------------------------------------------------- liste
    def reload_list(self, select_index=None):
        keep = {r.msg.id for r in self.listbox.get_selected_rows()}
        msgs = self.cache.query(self.view, self.account, self.category if self.view == "inbox" else None,
                                self.unread_only, self.att_only, self._effective_search())
        self._loading = True
        for ch in self.listbox.get_children():
            self.listbox.remove(ch)
        self.rows = {}
        for m in msgs:
            row = MessageRow(m, self._row_checked, self._on_swipe,
                             dict(self.config["swipe"], invert=self.config["swipe_invert"]), self._row_height())
            row.set_select_mode(self.select_mode)
            self.rows[m.id] = row
            self.listbox.add(row)
        self.listbox.invalidate_headers()
        for mid in keep:
            if mid in self.rows:
                self.listbox.select_row(self.rows[mid])
        if select_index is not None and msgs and not self.single:
            r = self.listbox.get_row_at_index(min(select_index, len(msgs) - 1))
            if r:
                self.listbox.select_row(r)
        self._loading = False
        self.list_stack.set_visible_child_name("list" if msgs else "empty")
        self.empty_lbl.set_text("Aucun résultat" if self._effective_search() else "Aucun message ici — profitez-en 🎉")
        self._on_selection(self.listbox)

    def selected_msgs(self):
        msgs = [r.msg for r in self.listbox.get_selected_rows()]
        if not msgs and self.reader.msg:
            msgs = [self.reader.msg]
        return msgs

    def _selected_index(self):
        idx = [r.get_index() for r in self.listbox.get_selected_rows()]
        return min(idx) if idx else None

    def _on_selection(self, lb):
        if self._loading:
            return
        rows = lb.get_selected_rows()
        sel = set(rows)
        for r in self.rows.values():
            r.set_checked(r in sel)
        n = len(rows)
        self.bulk_rev.set_reveal_child(n > 1 or (self.select_mode and n >= 1))
        self.bulk_lbl.set_text("%d sélectionné%s" % (n, "s" if n > 1 else ""))
        if n == 0:
            self.reader.show_empty()
        elif n == 1:
            if not (self.reader.msg and self.reader.msg.id == rows[0].msg.id):
                self.open_message(rows[0].msg)
        else:
            self.reader.show_multi(n)

    def open_message(self, msg):
        self.reader.show_message(msg, self.config["load_images"])
        if self.single:
            self.reader_open = True
            self._layout()
        if msg.unread and msg.folder != "drafts":
            self.set_unread([msg], False, reload=False)

    def _on_activated(self, lb, row):
        if self.select_mode:
            return
        if self.view == "drafts" or row.msg.folder == "drafts":
            self.open_draft(row.msg)
        elif self.single:
            self.open_message(row.msg)

    def _row_checked(self, row, active):
        if active:
            self.listbox.select_row(row)
        else:
            self.listbox.unselect_row(row)

    def _on_list_click(self, lb, ev):
        if self.select_mode and ev.button == 1:
            row = lb.get_row_at_y(int(ev.y))
            if row:
                (lb.unselect_row if row.is_selected() else lb.select_row)(row)
                return True
        return False

    def _on_list_context(self, lb, ev):
        if ev.button != 3:
            return False
        row = lb.get_row_at_y(int(ev.y))
        if not row:
            return False
        if not row.is_selected():
            lb.unselect_all()
            lb.select_row(row)
        m = row.msg
        menu = Gtk.Menu()
        items = [("Répondre", lambda: self.reply(m)), ("Répondre à tous", lambda: self.reply(m, True)),
                 ("Transférer", lambda: self.forward(m)), None,
                 ("Archiver", lambda: self.move_messages(self.selected_msgs(), "archive")),
                 ("Supprimer", lambda: self.move_messages(self.selected_msgs(), "trash")),
                 ("Marquer comme %s" % ("lu" if m.unread else "non lu"),
                  lambda: self.set_unread(self.selected_msgs(), not m.unread)),
                 ("Retirer des favoris" if m.starred else "Ajouter aux favoris",
                  lambda: self.set_flag(self.selected_msgs(), "starred", not m.starred)),
                 ("Désépingler" if m.pinned else "Épingler",
                  lambda: self.set_flag(self.selected_msgs(), "pinned", not m.pinned)), None,
                 ("Signaler comme spam", lambda: self.move_messages(self.selected_msgs(), "spam")),
                 ("Mettre l'expéditeur en spam", lambda: self.spam_sender(m)),
                 ("Bloquer l'expéditeur", lambda: self.block_sender(m)),
                 ("Voir tous ses messages", lambda: self.show_from(m))]
        for it in items:
            if it is None:
                menu.append(Gtk.SeparatorMenuItem())
                continue
            mi = Gtk.MenuItem(label=it[0])
            mi.connect("activate", lambda _i, f=it[1]: f())
            menu.append(mi)
        sn = Gtk.MenuItem(label="Reporter")
        sn.set_submenu(self.build_snooze_menu())
        menu.append(sn)
        menu.show_all()
        menu.popup_at_pointer(ev)
        return True

    def _toggle_select_mode(self, btn):
        self.select_mode = btn.get_active()
        for r in self.rows.values():
            r.set_select_mode(self.select_mode)
        self._on_selection(self.listbox)

    # ----------------------------------------------------------- disposition
    @property
    def single(self):
        """Un seul volet à la fois (fenêtre étroite ou disposition « liste seule »)."""
        return self.narrow or self.config["layout"] == "list"

    def _on_size(self, w, alloc):
        zone = 0 if alloc.width < HIDE_BELOW else (1 if alloc.width < RAIL_BELOW else 2)
        narrow = alloc.width < NARROW
        if (zone != self._zone or narrow != self.narrow) and not self._reflow_src:
            self._reflow_src = GLib.idle_add(self._reflow, zone, narrow)

    def _reflow(self, zone, narrow):
        self._reflow_src = 0
        if zone != self._zone:
            self._zone = zone
            self.sidebar_mode = "full" if zone == 2 else "rail"
            self.side_toggle.handler_block_by_func(self._side_toggled)
            self.side_toggle.set_active(zone > 0)
            self.side_toggle.handler_unblock_by_func(self._side_toggled)
            self._apply_sidebar()
        if narrow != self.narrow:
            self.narrow, self.reader_open = narrow, False
            self.apply_layout()
        return False

    def _side_toggled(self, btn):
        self._apply_sidebar()

    def _apply_sidebar(self):
        visible = self.side_toggle.get_active()
        rail = self.sidebar_mode == "rail"
        self.sidebar.set_visible(visible)
        for lab in self.nav_labels:
            lab.set_visible(not rail)
        for wdg in (self.acc_combo, self.status):
            wdg.set_visible(not rail)
        self.settings_btn.set_label("" if rail else "Paramètres")
        self.compose_lbl.set_visible(not rail)
        self.sidebar.set_size_request(60 if rail else 190, -1)
        if visible:
            self.paned_out.set_position(60 if rail else max(190, self.config["side_width"]))

    def toggle_rail(self):
        self.sidebar_mode = "full" if self.sidebar_mode == "rail" else "rail"
        self.side_toggle.set_active(True)
        self._apply_sidebar()

    def _save_positions(self):
        vertical = self.config["layout"] == "bottom"
        if self.list_box.get_visible() and self.reader.get_visible():
            self.config["pos_bottom" if vertical else "pos_cols"] = self.paned_in.get_position()
        if self.sidebar.get_visible() and self.sidebar_mode == "full":
            self.config["side_width"] = self.paned_out.get_position()

    def set_layout(self, mode):
        self._save_positions()
        self.config["layout"] = mode
        self.config.save()
        self.reader_open = False
        self.apply_layout()

    def apply_layout(self):
        vertical = self.config["layout"] == "bottom"
        self.paned_in.set_orientation(Gtk.Orientation.VERTICAL if vertical else Gtk.Orientation.HORIZONTAL)
        if self.single:
            self.list_box.set_size_request(-1, -1)
        elif vertical:
            self.list_box.set_size_request(-1, 150)
        else:
            self.list_box.set_size_request(260, -1)
        self.reader.set_narrow(self.single)
        self._layout()
        self.paned_in.set_position(self.config["pos_bottom" if vertical else "pos_cols"])

    def _layout(self):
        if self.single:
            self.reader.set_visible(self.reader_open)
            self.list_box.set_visible(not self.reader_open)
        else:
            self.reader.set_visible(True)
            self.list_box.set_visible(True)

    # ------------------------------------------------------------- tâches bg
    def run_bg(self, fn, done=None):
        def work():
            try:
                res, err = fn(), None
            except Exception as e:
                res, err = None, e
            if done:
                def cb():
                    done(res, err)
                    return False
                GLib.idle_add(cb)
        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------ synchro
    def sync(self, manual=False, folders=("inbox", "sent"), quiet=False):
        if self._sync_busy or self._pending:
            if manual:
                self.toast.popup("Synchronisation déjà en cours…", timeout=2)
            return
        self._sync_busy = True
        if not quiet:
            self.status.set_text("Synchronisation…")
        accounts = list(self.accounts())
        known = {(a["id"], f): self.cache.uids(a["id"], f) for a in accounts for f in folders}

        def work():
            out = []
            for a in accounts:
                be = self.backend(a["id"])
                for f in folders:
                    try:
                        out.append((a["id"], f, be.sync(f, known[(a["id"], f)]), None))
                    except Exception as e:
                        out.append((a["id"], f, None, e))
            return out
        self.run_bg(work, lambda res, err: self._sync_done(res or [], err, known, manual))

    def _sync_done(self, results, err, known, manual):
        self._sync_busy = False
        errors, fresh = [], []
        for aid, f, data, e in results:
            if e or not data:
                if e:
                    errors.append(str(e))
                continue
            msgs, flags, present, minuid = data
            self.cache.upsert_many(msgs)
            kn = known[(aid, f)]
            for uid, (unread, starred) in flags.items():
                mid = kn.get(uid)
                m = self.cache.get(mid) if mid else None
                if m and (m.unread != unread or m.starred != starred):
                    self.cache.update(mid, unread=unread, starred=starred)
            if present is not None:
                for uid, mid in kn.items():
                    if uid >= minuid and uid not in present:
                        self.cache.delete(mid)
            if f == "inbox":
                keep = self._auto_route([m for m in msgs if m.folder == "inbox"])
                if kn:
                    fresh += [m for m in keep if m.unread]
        self._last_sync = time.time()
        if errors:
            self.status.set_text("⚠ " + errors[0][:120])
            if manual:
                self.toast.popup(errors[0][:100], timeout=6)
        else:
            self.status.set_text("Synchronisé à " + time.strftime("%H:%M"))
        self.reload_list()
        self.update_counts()
        self._notify(fresh)

    def _notify(self, msgs):
        if not msgs or not self.config["notifications"]:
            return
        n = Gio.Notification.new("%d nouveaux messages" % len(msgs) if len(msgs) > 1 else msgs[0].display_sender)
        n.set_body(msgs[0].subject if len(msgs) == 1 else "\n".join(
            "%s — %s" % (m.display_sender, m.subject) for m in msgs[:3]))
        self.get_application().send_notification("new-mail", n)

    def update_counts(self):
        c = self.cache.counts(self.account)
        for key, val in (("inbox", c["inbox"]), ("unread", c["inbox"]), ("drafts", c["drafts"]),
                         ("snoozed", c["snoozed"])):
            b = self.badges[key]
            b.set_text(str(val))
            b.set_visible(val > 0)
        self.set_title("%s%s" % ("(%d) " % c["inbox"] if c["inbox"] else "", APP_NAME))

    def _tick(self):
        self._ticks += 1
        self.process_outbox()
        if self._ticks % 30 == 0:
            woken = self.cache.wake_snoozed()
            if woken:
                self._notify(woken)
                self.reload_list()
                self.update_counts()
            self.check_followups()
            if time.time() - self._last_sync > self.config["refresh_minutes"] * 60:
                self.sync()
        return True

    # ------------------------------------------------------------ actions
    def set_unread(self, msgs, unread, reload=True):
        for m in msgs:
            m.unread = unread
            self.cache.update(m.id, unread=unread)
            if m.id in self.rows:
                self.rows[m.id].msg.unread = unread
                self.rows[m.id].refresh()
            self._flag_remote(m, seen=not unread)
        self.update_counts()
        if reload and self.view == "unread":
            self.reload_list(self._selected_index())

    def set_flag(self, msgs, field, value):
        idx = self._selected_index()
        for m in msgs:
            setattr(m, field, value)
            self.cache.update(m.id, **{field: value})
            if field == "starred":
                self._flag_remote(m, flagged=value)
        self.reload_list(idx)

    def _flag_remote(self, m, seen=None, flagged=None):
        try:
            be = self.backend(m.account)
        except Exception:
            return
        if not be.demo:
            self.run_bg(lambda: be.set_flags(m, seen=seen, flagged=flagged))

    def move_messages(self, msgs, dest):
        if not msgs:
            return
        if dest == "trash" and all(m.folder == "trash" for m in msgs):
            d = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
                                  text="Supprimer définitivement %d message(s) ?" % len(msgs))
            d.add_buttons("Annuler", Gtk.ResponseType.CANCEL, "Supprimer", Gtk.ResponseType.OK)
            ok = d.run() == Gtk.ResponseType.OK
            d.destroy()
            if not ok:
                return
            idx = self._selected_index()
            for m in msgs:
                self.cache.delete(m.id)
                be = self.backend(m.account)
                self.run_bg(lambda m=m, be=be: be.delete_forever(m))
            self.reload_list(idx)
            self.update_counts()
            return
        verb = {"archive": "archivé", "trash": "supprimé", "spam": "signalé comme spam", "inbox": "déplacé"}[dest]
        prev = [(m.id, m.folder, m.snoozed_until) for m in msgs]
        idx = self._selected_index()
        for m in msgs:
            self.cache.update(m.id, folder=dest, snoozed_until=0.0)
        self._pending += 1
        self.reload_list(idx)
        self.update_counts()
        state = {"done": False}

        def undo():
            state["done"] = True
            self._pending -= 1
            for mid, f, s in prev:
                self.cache.update(mid, folder=f, snoozed_until=s)
            self.reload_list()
            self.update_counts()

        def commit():
            if state["done"]:
                return
            state["done"] = True
            self._pending -= 1

            self._bg_move(msgs, dest)
        n = len(msgs)
        self.toast.popup("%d message%s %s%s" % (n, "s" if n > 1 else "", verb, "s" if n > 1 else ""),
                         "Annuler", undo, timeout=self.config["undo_seconds"], on_expire=commit)

    # ---------------------------------------------------------------- report
    def build_snooze_menu(self, callback=None):
        cb = callback or self.snooze_selected
        menu = Gtk.Menu()
        def at(days, hour):
            d = datetime.datetime.now() + datetime.timedelta(days=days)
            return d.replace(hour=hour, minute=0, second=0, microsecond=0).timestamp()

        def wd():
            return datetime.datetime.now().weekday()
        opts = [("Plus tard aujourd'hui (+3 h)", lambda: time.time() + 3 * 3600),
                ("Demain 8 h", lambda: at(1, 8)),
                ("Ce week-end (samedi 9 h)", lambda: at((5 - wd()) % 7 or 7, 9)),
                ("Semaine prochaine (lundi 8 h)", lambda: at((7 - wd()) % 7 or 7, 8)),
                ("Choisir une date…", None)]
        for label, fn in opts:
            it = Gtk.MenuItem(label=label)
            it.connect("activate", lambda _i, f=fn: self._snooze_pick(f, cb))
            menu.append(it)
        menu.show_all()
        return menu

    def _snooze_pick(self, fn, cb):
        if fn:
            cb(fn())
            return
        dlg = Gtk.Dialog(title="Reporter jusqu'au…", transient_for=self, modal=True)
        dlg.add_buttons("Annuler", Gtk.ResponseType.CANCEL, "Reporter", Gtk.ResponseType.OK)
        cal = Gtk.Calendar()
        hour = Gtk.SpinButton.new_with_range(0, 23, 1)
        hour.set_value(9)
        box = dlg.get_content_area()
        box.pack_start(cal, False, False, 6)
        box.pack_start(hour, False, False, 6)
        dlg.show_all()
        ok = dlg.run() == Gtk.ResponseType.OK
        y, mo, d = cal.get_date()
        h = int(hour.get_value())
        dlg.destroy()
        if ok:
            cb(datetime.datetime(y, mo + 1, d, h).timestamp())

    def snooze_selected(self, ts):
        self.snooze_msgs(self.selected_msgs(), ts)

    def snooze_msgs(self, msgs, ts):
        if not msgs or ts <= time.time():
            return
        prev = [(m.id, m.snoozed_until) for m in msgs]
        idx = self._selected_index()
        for m in msgs:
            self.cache.update(m.id, snoozed_until=ts)

        def undo():
            for mid, s in prev:
                self.cache.update(mid, snoozed_until=s)
            self.reload_list()
            self.update_counts()
        self.reload_list(idx)
        self.update_counts()
        self.toast.popup("Reporté au %s" % format_full(ts), "Annuler", undo, timeout=5)

    def mark_all_read(self):
        msgs = [m for m in self.cache.query(self.view, self.account, None, True, False, self._effective_search())]
        if msgs:
            self.set_unread(msgs, False)
            self.reload_list()

    # ------------------------------------------------------------ rédaction
    def _default_account(self, msg=None):
        if msg and any(a["id"] == msg.account for a in self.accounts()):
            return msg.account
        return self.account if self.account != "all" else self.accounts()[0]["id"]

    def compose(self, **kw):
        kw.setdefault("account_id", self._default_account())
        ComposeWindow(self, self.accounts(), **kw)

    def _quote(self, msg):
        orig = sanitize_html(msg.html) if msg.html else text_to_html(msg.text)
        return '<br><div>Le %s, %s a écrit :</div><blockquote>%s</blockquote>' % (
            format_full(msg.date), html.escape(msg.display_sender), orig)

    def reply(self, msg, all_=False):
        to = msg.to if msg.folder == "sent" else (msg.reply_to or msg.sender_email)
        cc = ""
        if all_:
            mine = {a["email"].lower() for a in self.accounts()}
            others = [a for a in split_addresses(msg.to) + split_addresses(msg.cc)
                      if a.lower() not in mine and a.lower() != msg.sender_email.lower()]
            cc = ", ".join(dict.fromkeys(others))
        self.compose(account_id=self._default_account(msg), to=to, cc=cc,
                     subject="Re: " + normalize_subject(msg.subject), quote_html=self._quote(msg),
                     in_reply_to=msg.message_id, references=msg.references)

    def forward(self, msg):
        head = ("<br>---------- Message transféré ----------<br>De : %s &lt;%s&gt;<br>Date : %s<br>Objet : %s<br>À : %s<br>"
                % (html.escape(msg.sender_name), html.escape(msg.sender_email), format_full(msg.date),
                   html.escape(msg.subject), html.escape(msg.to)))
        self.compose(account_id=self._default_account(msg), subject="Fwd: " + normalize_subject(msg.subject),
                     quote_html=head + (sanitize_html(msg.html) if msg.html else text_to_html(msg.text)),
                     attachments=[a["path"] for a in msg.attachments])

    def open_draft(self, msg):
        self.compose(account_id=msg.account, to=msg.to, cc=msg.cc, subject=msg.subject, body_html=sanitize_html(msg.html), raw=True,
                     in_reply_to=msg.message_id, references=msg.references,
                     attachments=[a["path"] for a in msg.attachments], draft_id=msg.id)

    def quick_reply(self, text):
        msg = self.reader.msg
        if not msg:
            return
        acc = next((a for a in self.accounts() if a["id"] == self._default_account(msg)), self.accounts()[0])
        sig = acc.get("signature_html", "")
        body = text_to_html(text) + ("<br><br>-- <br>" + sig if sig.strip() else "")
        out = Outgoing(account=acc["id"], to=(msg.reply_to or msg.sender_email), subject="Re: " + normalize_subject(msg.subject),
                       html=body, in_reply_to=msg.message_id, references=msg.references)
        self.queue_send(out, 0)

    # ---------------------------------------------------------------- envoi
    def queue_send(self, out, delay=0, scheduled=False):
        oid = uuid.uuid4().hex
        wait = delay if scheduled else self.config["undo_seconds"]
        self.cache.outbox_add(oid, time.time() + wait, out)

        def undo():
            self.cache.outbox_remove(oid)
            ComposeWindow(self, self.accounts(), account_id=out.account, to=out.to, cc=out.cc, subject=out.subject,
                          body_html=out.html, raw=True, in_reply_to=out.in_reply_to, references=out.references,
                          attachments=out.attachments)
        if scheduled:
            self.toast.popup("Envoi programmé pour le %s" % format_full(time.time() + delay), "Annuler", undo, timeout=6)
        else:
            self.toast.popup("Envoi du message…", "Annuler", undo, timeout=max(2, self.config["undo_seconds"] - 1))

    def process_outbox(self):
        for oid, out in self.cache.outbox_due():
            if oid in self._sending:
                continue
            self._sending.add(oid)

            def done(res, err, oid=oid, out=out):
                self._sending.discard(oid)
                self.cache.outbox_remove(oid)
                if err:
                    self.toast.popup("Échec de l'envoi : %s" % str(err)[:90], "Rouvrir", lambda: ComposeWindow(
                        self, self.accounts(), account_id=out.account, to=out.to, cc=out.cc, subject=out.subject,
                        body_html=out.html, raw=True, attachments=out.attachments), timeout=10)
                    return
                self.toast.popup("Message envoyé ✔", timeout=3)
                be = self.backend(out.account)
                acc = next((a for a in self.accounts() if a["id"] == out.account), {})
                if be.demo:
                    from .util import html_to_text
                    t = html_to_text(out.html)
                    self.cache.upsert(Message(
                        id="demo|SENT|%s" % uuid.uuid4().hex[:8], account=out.account, folder="sent", uid=0,
                        sender_name=acc.get("name", ""), sender_email=acc.get("email", ""), to=out.to,
                        subject=out.subject, date=time.time(), snippet=t[:150], text=t, html=out.html, unread=False))
                    self.reload_list()
                else:
                    self.sync(folders=("sent",), quiet=True)
            self.run_bg(lambda out=out: self.backend(out.account).send(out), done)

    # --------------------------------------------------------------- lecteur
    def _reader_action(self, reader, act):
        msgs = self.selected_msgs()
        m = reader.msg
        if act == "back":
            self.reader_open = False
            self.listbox.unselect_all()
            self._layout()
        elif act == "reply" and m:
            self.reply(m)
        elif act == "reply_all" and m:
            self.reply(m, True)
        elif act == "forward" and m:
            self.forward(m)
        elif act in ("archive", "trash", "spam"):
            self.move_messages(msgs, act)
            if self.single:
                self.reader_open = False
                self._layout()
        elif act == "star" and m:
            self.set_flag(msgs, "starred", not m.starred)
            reader.show_message(self.cache.get(m.id) or m)
        elif act == "pin" and m:
            self.set_flag(msgs, "pinned", not m.pinned)
        elif act == "unread":
            self.set_unread(msgs, True)
        elif act == "images" and m:
            reader.show_message(m, True)
        elif act == "spam_sender" and m:
            self.spam_sender(m)
        elif act in ("block", "block_domain") and m:
            self.block_sender(m, act == "block_domain")
        elif act == "from_sender" and m:
            self.show_from(m)
        elif act == "copy_addr" and m:
            self.copy_text(m.sender_email)
        elif act in ("followup_3", "followup_7") and m:
            self.add_followup(m, int(act[-1]))

    # ------------------------------------------------------------- clavier
    def _on_key(self, w, ev):
        focus = self.get_focus()
        key = Gdk.keyval_name(ev.keyval) or ""
        ctrl = bool(ev.state & Gdk.ModifierType.CONTROL_MASK)
        typing = isinstance(focus, (Gtk.Entry, Gtk.TextView, Gtk.SpinButton))
        if ctrl and key in ("comma", "less"):
            self.show_settings(window=bool(ev.state & Gdk.ModifierType.SHIFT_MASK))
            return True
        if self.root_stack.get_visible_child_name() == "settings":
            if key == "Escape":
                self.close_settings()
                return True
            return False
        if key == "Escape":
            if self.search_entry.get_text():
                self.search_entry.set_text("")
                self.listbox.grab_focus()
            else:
                self.listbox.unselect_all()
            return typing is False
        if ctrl and key in ("k", "K"):
            self.show_palette()
            return True
        if ctrl and key in ("f", "F"):
            self.search_entry.grab_focus()
            return True
        if ctrl and key in ("r", "R"):
            self.sync(True)
            return True
        if ctrl and key in ("n", "N"):
            self.compose()
            return True
        if typing:
            return False
        if ctrl and key in ("a", "A"):
            self.listbox.select_all()
            return True
        if ctrl or (ev.state & Gdk.ModifierType.MOD1_MASK):
            return False
        m = self.reader.msg
        msgs = self.selected_msgs()
        acts = {
            "c": lambda: self.compose(), "r": lambda: m and self.reply(m), "a": lambda: m and self.reply(m, True),
            "f": lambda: m and self.forward(m), "e": lambda: self.move_messages(msgs, "archive"),
            "numbersign": lambda: self.move_messages(msgs, "trash"), "Delete": lambda: self.move_messages(msgs, "trash"),
            "s": lambda: m and self.set_flag(msgs, "starred", not m.starred),
            "p": lambda: m and self.set_flag(msgs, "pinned", not m.pinned),
            "u": lambda: m and self.set_unread(msgs, not m.unread),
            "h": lambda: msgs and self.snooze_selected(
                (datetime.datetime.now() + datetime.timedelta(days=1)).replace(hour=8, minute=0, second=0).timestamp()),
            "j": lambda: self._step(1), "k": lambda: self._step(-1),
            "slash": lambda: self.search_entry.grab_focus(),
            "exclam": lambda: self.move_messages(msgs, "spam"),
            "backslash": lambda: self.set_layout("columns" if self.config["layout"] == "list" else "list"),
            "x": lambda: self.sel_btn.set_active(not self.sel_btn.get_active()),
        }
        fn = acts.get(key)
        if fn:
            fn()
            return True
        return False

    def _step(self, d):
        cur = self._selected_index()
        n = len(self.rows)
        if not n:
            return
        i = 0 if cur is None else max(0, min(n - 1, cur + d))
        r = self.listbox.get_row_at_index(i)
        if r:
            self.listbox.unselect_all()
            self.listbox.select_row(r)
            r.grab_focus()

    # ----------------------------------------------------- gestes & actions
    def _row_height(self):
        return {"compact": 64, "comfortable": 72, "spacious": 80}.get(self.config["density"], 72)

    def _on_swipe(self, row, action):
        sel = [r.msg for r in self.listbox.get_selected_rows()] if row.is_selected() else []
        msgs = sel if row.msg.id in {m.id for m in sel} else [row.msg]
        self.run_action(action, msgs)

    def run_action(self, action, msgs):
        if not msgs:
            return
        m = msgs[0]
        if action in ("archive", "trash", "spam"):
            self.move_messages(msgs, action)
        elif action == "read":
            self.set_unread(msgs, not m.unread)
        elif action in ("star", "pin"):
            fld = "starred" if action == "star" else "pinned"
            self.set_flag(msgs, fld, not getattr(m, fld))
        elif action == "snooze":
            ts = (datetime.datetime.now() + datetime.timedelta(days=1)).replace(
                hour=8, minute=0, second=0, microsecond=0).timestamp()
            self.snooze_msgs(msgs, ts)
        elif action == "block":
            self.block_sender(m)

    # ------------------------------------------------- spam / blocage / règles
    @staticmethod
    def _key(msg, domain=False):
        em = msg.sender_email.lower()
        return "@" + em.split("@")[-1] if domain else em

    def _gather(self, msg, key):
        msgs = self.cache.by_sender(key, ("inbox", "archive"))
        if msg.id not in {x.id for x in msgs} and msg.folder in ("inbox", "archive"):
            msgs.append(msg)
        return msgs

    def spam_sender(self, msg, domain=False):
        """L'expéditeur (ou son domaine) part en Spam, maintenant et pour les prochains messages."""
        key = self._key(msg, domain)
        if key not in self.config["spam_senders"]:
            self.config["spam_senders"].append(key)
            self.config.save()
        msgs = self._gather(msg, key)
        if msgs:
            self.move_messages(msgs, "spam")
        self.status.set_text("En spam : " + key)

    def block_sender(self, msg, domain=False):
        """Bloque l'expéditeur : ses messages vont à la corbeille (lus), les futurs aussi."""
        key = self._key(msg, domain)
        if key not in self.config["blocked"]:
            self.config["blocked"].append(key)
            self.config.save()
        msgs = self._gather(msg, key)
        if msgs:
            self.move_messages(msgs, "trash")
        else:
            self.toast.popup("Expéditeur bloqué : " + key, timeout=4)
        self.status.set_text("Bloqué : " + key)

    def unblock(self, msg):
        em, dom = self._key(msg), self._key(msg, True)
        for k in ("blocked", "spam_senders"):
            self.config[k] = [x for x in self.config[k] if x.lower() not in (em, dom)]
        self.config.save()
        self.toast.popup("%s débloqué" % msg.sender_email, timeout=3)

    def is_blocked(self, msg):
        keys = {self._key(msg), self._key(msg, True)}
        return any(x.lower() in keys for x in self.config["blocked"] + self.config["spam_senders"])

    def show_from(self, msg):
        self.search_entry.set_text("from:" + msg.sender_email)
        self.search_entry.grab_focus()

    def copy_text(self, text):
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(text, -1)
        self.toast.popup("Copié : " + text, timeout=2)

    @staticmethod
    def _rule_match(r, m):
        txt = (r.get("text") or "").lower()
        hay = {"from": "%s %s" % (m.sender_name, m.sender_email), "subject": m.subject,
               "to": "%s %s" % (m.to, m.cc)}.get(r.get("field"), "")
        return bool(txt) and txt in hay.lower()

    def _auto_route(self, msgs):
        """Applique blocages, spam d'expéditeur et règles aux nouveaux messages. Retourne ceux qui restent."""
        cfg = self.config
        blocked = {x.lower() for x in cfg["blocked"]}
        spam_s = {x.lower() for x in cfg["spam_senders"]}
        rules = cfg["rules"]
        if not msgs or not (blocked or spam_s or rules):
            return list(msgs)
        moves, keep = {"trash": [], "spam": [], "archive": []}, []
        for m in msgs:
            em = m.sender_email.lower()
            dom = "@" + em.split("@")[-1]
            dest = "trash" if (em in blocked or dom in blocked) else \
                   "spam" if (em in spam_s or dom in spam_s) else None
            if dest is None:
                for r in rules:
                    if not self._rule_match(r, m):
                        continue
                    act = r.get("action")
                    if act in moves and dest is None:
                        dest = act
                    elif act == "read":
                        self.set_unread([m], False, reload=False)
                    elif act == "star":
                        m.starred = True
                        self.cache.update(m.id, starred=True)
                        self._flag_remote(m, flagged=True)
                    elif act == "pin":
                        m.pinned = True
                        self.cache.update(m.id, pinned=True)
            (moves[dest] if dest else keep).append(m)
        for dest, lst in moves.items():
            if lst:
                self._auto_move(lst, dest)
        return keep

    def apply_rules_now(self):
        left = self._auto_route(self.cache.query("inbox", "all"))
        self.reload_list()
        self.update_counts()
        self.toast.popup("Règles appliquées (%d message(s) restent dans la boîte)" % len(left), timeout=4)

    def _auto_move(self, msgs, dest):
        for m in msgs:
            self.cache.update(m.id, folder=dest, unread=False if dest in ("trash", "spam") else m.unread)
        self._bg_move(msgs, dest)

    def _bg_move(self, msgs, dest):
        self._pending += 1

        def work():
            errs, by = [], {}
            for m in msgs:
                by.setdefault(m.account, []).append(m)
            for aid, lst in by.items():
                try:
                    self.backend(aid).move_many(lst, dest)
                except Exception as e:
                    errs.append(str(e))
            return errs

        def done(errs, err):
            self._pending -= 1
            if err or errs:
                self.toast.popup("Échec du déplacement : %s" % ((errs or [str(err)])[0][:80]), timeout=6)
            real = False
            for m in msgs:
                try:
                    if not self.backend(m.account).demo:
                        self.cache.delete(m.id)
                        real = True
                except Exception:
                    pass
            if real:
                self.sync(folders=("inbox", dest), quiet=True)
            self.reload_list()
            self.update_counts()
        self.run_bg(work, done)

    # ------------------------------------------------------------- rappels
    def add_followup(self, msg, days):
        self.config["followups"].append({
            "id": msg.id, "at": time.time() + days * 86400, "subject": msg.subject, "date": msg.date,
            "to": msg.to if msg.folder == "sent" else msg.sender_email})
        self.config.save()
        self.toast.popup("Rappel dans %d jours si aucune réponse" % days, timeout=4)

    def check_followups(self):
        now, keep, due = time.time(), [], []
        for f in self.config["followups"]:
            if f["at"] > now:
                keep.append(f)
                continue
            addrs = [a.lower() for a in split_addresses(f["to"])]
            subj = normalize_subject(f["subject"]).lower()
            replied = bool(addrs) and any(
                m.date > f["date"] and normalize_subject(m.subject).lower() == subj
                for m in self.cache.query("inbox", "all", search="from:" + addrs[0]))
            if not replied:
                due.append(f)
        if len(keep) != len(self.config["followups"]):
            self.config["followups"] = keep
            self.config.save()
        for f in due:
            n = Gio.Notification.new("Pas de réponse")
            n.set_body("« %s » — %s" % (f["subject"], f["to"]))
            self.get_application().send_notification("followup-" + f["id"], n)
            self.toast.popup("Pas de réponse à « %s »" % f["subject"][:50], timeout=8)

    # ---------------------------------------------------- recherches enregistrées
    def _rebuild_saved(self):
        for r in self._saved_rows:
            self.nav_labels = [l for l in self.nav_labels if l is not r.lab]
            self.nav.remove(r)
        self._saved_rows = []
        for i, sv in enumerate(self.config["saved_searches"]):
            r = Gtk.ListBoxRow()
            r.view = "saved:%d" % i
            r.get_style_context().add_class("nav-row")
            b = Gtk.Box(spacing=10)
            b.pack_start(icon("system-search-symbolic"), False, False, 0)
            r.lab = Gtk.Label(label=sv["name"], xalign=0)
            self.nav_labels.append(r.lab)
            b.pack_start(r.lab, True, True, 0)
            r.add(b)
            r.show_all()
            self.nav.add(r)
            self._saved_rows.append(r)
        if hasattr(self, "settings_btn"):
            self._apply_sidebar()

    def _saved_query(self):
        if self.view.startswith("saved:"):
            try:
                return self.config["saved_searches"][int(self.view[6:])]["query"]
            except (ValueError, IndexError):
                return ""
        return ""

    def _effective_search(self):
        return self.search or self._saved_query()

    def _view_title(self):
        if self.view.startswith("saved:"):
            try:
                return self.config["saved_searches"][int(self.view[6:])]["name"]
            except (ValueError, IndexError):
                return "Recherche"
        return TITLES.get(self.view, "")

    def save_current_search(self):
        q = (self.search_entry.get_text() or self.search).strip()
        if not q:
            self.toast.popup("Tapez d'abord une recherche, puis enregistrez-la", timeout=3)
            return
        d = Gtk.Dialog(title="Enregistrer la recherche", transient_for=self, modal=True)
        d.add_buttons("Annuler", Gtk.ResponseType.CANCEL, "Enregistrer", Gtk.ResponseType.OK)
        e = Gtk.Entry(text=q)
        e.set_activates_default(True)
        d.set_default_response(Gtk.ResponseType.OK)
        d.get_content_area().pack_start(e, True, True, 12)
        d.show_all()
        ok = d.run() == Gtk.ResponseType.OK
        name = e.get_text().strip()
        d.destroy()
        if ok and name:
            self.config["saved_searches"].append({"name": name, "query": q})
            self.config.save()
            self._rebuild_saved()

    def delete_saved(self, idx):
        try:
            del self.config["saved_searches"][idx]
        except IndexError:
            return
        self.config.save()
        if self.view.startswith("saved:"):
            self._goto("inbox")
        self._rebuild_saved()

    # -------------------------------------------------------------- palette
    def _palette_commands(self):
        sel = self.selected_msgs()
        m = self.reader.msg or (sel[0] if sel else None)
        cmds = []
        if m:
            who, dom = m.sender_email, "@" + m.sender_email.split("@")[-1]
            tomorrow = lambda: self.run_action("snooze", self.selected_msgs() or [m])
            cmds += [
                ("Répondre", lambda: self.reply(m)), ("Répondre à tous", lambda: self.reply(m, True)),
                ("Transférer", lambda: self.forward(m)),
                ("Archiver", lambda: self.move_messages(self.selected_msgs() or [m], "archive")),
                ("Supprimer", lambda: self.move_messages(self.selected_msgs() or [m], "trash")),
                ("Signaler comme spam (ce message)", lambda: self.move_messages(self.selected_msgs() or [m], "spam")),
                ("Mettre l'expéditeur en spam — " + who, lambda: self.spam_sender(m)),
                ("Mettre le domaine en spam — " + dom, lambda: self.spam_sender(m, True)),
                ("Bloquer l'expéditeur — " + who, lambda: self.block_sender(m)),
                ("Bloquer le domaine — " + dom, lambda: self.block_sender(m, True)),
                ("Voir tous les messages de " + who, lambda: self.show_from(m)),
                ("Copier l'adresse " + who, lambda: self.copy_text(who)),
                ("Reporter à demain 8 h", tomorrow),
                ("Me rappeler si pas de réponse (3 jours)", lambda: self.add_followup(m, 3)),
                ("Me rappeler si pas de réponse (7 jours)", lambda: self.add_followup(m, 7)),
                ("Créer une règle pour " + who, lambda: self.show_settings("filters")),
            ]
            if self.is_blocked(m):
                cmds.insert(6, ("Débloquer " + who, lambda: self.unblock(m)))
        cmds += [
            ("Nouveau message", self.compose), ("Actualiser", lambda: self.sync(True)),
            ("Gérer les expéditeurs bloqués et les règles", lambda: self.show_settings("filters")),
            ("Appliquer les règles à la boîte de réception", self.apply_rules_now),
            ("Enregistrer la recherche actuelle", self.save_current_search),
            ("Disposition : colonnes", lambda: self.set_layout("columns")),
            ("Disposition : lecture en bas", lambda: self.set_layout("bottom")),
            ("Disposition : liste seule", lambda: self.set_layout("list")),
            ("Barre latérale : réduire / étendre", self.toggle_rail),
            ("Paramètres", self.show_settings), ("Paramètres dans une fenêtre séparée", lambda: self.show_settings(window=True)),
            ("Journal d'erreurs", self.show_log), ("Gestes de swipe (réglages)", lambda: self.show_settings("gestures")),
            ("Basculer thème clair / sombre", self.toggle_theme),
            ("Tout marquer comme lu", self.mark_all_read), ("Tout sélectionner", lambda: self.listbox.select_all()),
            ("Rechercher", lambda: self.search_entry.grab_focus()),
        ]
        for i, sv in enumerate(self.config["saved_searches"]):
            cmds.append(("Supprimer la recherche enregistrée : " + sv["name"], lambda i=i: self.delete_saved(i)))
        for vid, label, _ in NAV:
            cmds.append(("Aller à : " + label, lambda v=vid: self._goto(v)))
        return cmds

    def show_palette(self):
        cmds = self._palette_commands()
        dlg = Gtk.Dialog(transient_for=self, modal=True)
        dlg.set_decorated(False)
        dlg.set_default_size(520, 360)
        box = dlg.get_content_area()
        box.set_border_width(8)
        e = Gtk.SearchEntry()
        e.set_placeholder_text("Tapez une commande…")
        box.pack_start(e, False, False, 4)
        lb = Gtk.ListBox()
        sw = Gtk.ScrolledWindow()
        sw.add(lb)
        box.pack_start(sw, True, True, 0)
        rows = []
        for label, fn in cmds:
            r = Gtk.ListBoxRow()
            r.fn, r.label = fn, label.lower()
            r.add(Gtk.Label(label=label, xalign=0, margin=8))
            lb.add(r)
            rows.append(r)
        lb.set_filter_func(lambda r: e.get_text().lower() in r.label)

        closed = []

        def run(fn):
            closed.append(1)
            dlg.destroy()
            GLib.idle_add(lambda: (fn(), False)[1])

        def activate(*_):
            for r in rows:
                if e.get_text().lower() in r.label:
                    run(r.fn)
                    return
        e.connect("search-changed", lambda *_: lb.invalidate_filter())
        e.connect("activate", activate)
        lb.connect("row-activated", lambda _l, r: run(r.fn))
        dlg.show_all()
        dlg.run()
        if not closed:
            dlg.destroy()

    def _goto(self, vid):
        for r in self.nav.get_children():
            if r.view == vid:
                self.nav.select_row(r)

    # --------------------------------------------------------------- fermeture
    def _on_close(self, *_):
        w, h = self.get_size()
        self.config["width"], self.config["height"] = w, h
        self.config["zoom"] = self.reader.zoom
        self._save_positions()
        try:
            self.config.save()
        except OSError:
            pass
        self.toast._finish(expired=True)   # valide les actions en attente
        return False
