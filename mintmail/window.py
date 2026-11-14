import datetime
import html
import threading
import time
import uuid

import gi
from .i18n import tr

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk

from . import APP_NAME, __version__
from .ai_service import AIService
from .backend import make_backend
from .compose import ComposeWindow
from .ai_features import AIMixin
from .listing import ListMixin, PAGE
from .folders import FolderMixin, SMART_VIEWS, dest_of
from .offline import OfflineMixin, is_retryable
from .updates_ui import UpdateBanner, UpdateMixin
from .extras import ExtrasMixin
from .models import Message, Outgoing
from .p2p import SyncEngine
from .syncdata import apply_items, describe as describe_sync
from .store import P2P_MIN_SECRET
from .reader import Reader
from .settings import SettingsPage
from .log import LOG, log_exception, tail
from .store import DATA_DIR
from .style import build_css
from .util import (
    format_full,
    normalize_subject,
    sanitize_html,
    split_addresses,
    text_to_html,
)
from .widgets import (
    MessageRow,
    Toast,
    icon,
    icon_button,
    row_header,
    row_sort,
)

NAV = [
    ("inbox", tr("Boîte intelligente"), "mail-inbox-symbolic"),
    ("unread", tr("Non lus"), "mail-unread-symbolic"),
    ("starred", tr("Favoris"), "starred-symbolic"),
    ("pinned", tr("Épinglés"), "view-pin-symbolic"),
    ("snoozed", tr("Reportés"), "alarm-symbolic"),
    ("drafts", tr("Brouillons"), "document-edit-symbolic"),
    ("sent", tr("Envoyés"), "mail-send-symbolic"),
    ("archive", tr("Archives"), "folder-symbolic"),
    ("spam", "Spam", "mail-mark-junk-symbolic"),
    ("trash", tr("Corbeille"), "user-trash-symbolic"),
]
TITLES = {k: v for k, v, _ in NAV}
CATEGORIES = [(None, tr("Tout")), ("people", tr("Personnes")), ("notif", tr("Notifications")), ("news", tr("Newsletters"))]
DEMO_ACCOUNT = {"id": "demo", "name": "Démo", "email": "demo@mintmail.local", "demo": True,
                "signature_html": "<i>Envoyé avec MintMail</i>"}
NARROW, RAIL_BELOW, HIDE_BELOW = 700, 1250, 900


class MainWindow(UpdateMixin, ExtrasMixin, OfflineMixin, ListMixin, AIMixin, FolderMixin, Gtk.ApplicationWindow):
    NAV_ROWS = NAV
    TITLES = TITLES

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
        self._limit, self._partial_ids = PAGE, set()
        self._init_ai()
        self._init_folders()
        self._loading, self._pending, self._sync_busy = False, 0, False
        self._backends, self._sending, self.rows = {}, set(), {}
        self._last_sync, self._ticks = 0.0, 0
        self.is_dark = False
        s = Gtk.Settings.get_default()
        self._system_dark = bool(s.get_property("gtk-application-prefer-dark-theme")) or \
            "dark" in (s.get_property("gtk-theme-name") or "").lower()
        s.set_property("gtk-decoration-layout", ":minimize,maximize,close")   # boutons de fenêtre toujours présents
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
        self._init_sync()
        threading.Thread(target=self.config.preload_passwords, daemon=True).start()
        self.apply_layout()
        self.reader.zoom = self.config["zoom"]
        self.reader.apply_zoom()
        self.demo_banner.set_visible(not self.config["accounts"])
        self.cat_sw.set_visible(self.view == "inbox")
        self.reload_list(full=True)
        self.update_counts()
        self.refresh_ai()
        threading.Thread(target=self.cache.backfill_meta, daemon=True).start()
        GLib.idle_add(lambda: (self.sync(), False)[1])
        GLib.timeout_add(800, lambda: (self.refresh_folders(), False)[1])
        GLib.timeout_add(6000, lambda: (self.contacts_refresh(), self.flush_ops(), False)[2])   # carnet d'adresses + actions en attente
        if self.config.p2p_notice == "short_code":   # l'ancien code (moins de 12 caractères) a désactivé la synchro
            GLib.timeout_add(2500, lambda: (self.toast.popup(
                tr("Synchronisation désactivée : l'ancien code de jumelage est trop court (12 caractères minimum)."),
                tr("Corriger"), lambda: self.show_settings("p2p"), timeout=15), False)[1])
        GLib.timeout_add_seconds(3, lambda: (self._start_push(), False)[1])
        GLib.timeout_add_seconds(1, self._tick)
        self._init_updates()
        self.open_today_at_start()

    # ------------------------------------------------------------------ UI
    def _build(self):
        hb = Gtk.HeaderBar()
        hb.set_show_close_button(True)
        hb.set_decoration_layout(":minimize,maximize,close")   # réduire / agrandir / fermer toujours présents
        self.set_titlebar(hb)
        self.side_toggle = Gtk.ToggleButton()
        self.side_toggle.set_image(icon("view-sidebar-start-symbolic", Gtk.IconSize.LARGE_TOOLBAR))
        self.side_toggle.set_tooltip_text(tr("Afficher / masquer le panneau latéral"))
        self.side_toggle.set_active(True)
        self.side_toggle.connect("toggled", self._side_toggled)
        hb.pack_start(self.side_toggle)
        comp = Gtk.Button()
        comp.set_image(icon("mail-message-new-symbolic", Gtk.IconSize.LARGE_TOOLBAR))
        comp.set_tooltip_text(tr("Nouveau message (C)"))
        comp.get_style_context().add_class("round-accent")
        comp.connect("clicked", lambda *_: self.compose())
        hb.pack_start(comp)
        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_placeholder_text(tr("Rechercher — ou « ? » + une question pour l'IA"))
        self.search_entry.set_width_chars(22)
        self.search_entry.get_style_context().add_class("mm-search")
        self.search_entry.connect("search-changed", self._search_changed)
        self.search_entry.connect("activate", self._search_activate)
        hb.set_custom_title(self.search_entry)
        menu_btn = Gtk.MenuButton()
        menu_btn.set_image(icon("open-menu-symbolic", Gtk.IconSize.LARGE_TOOLBAR))
        menu = Gtk.Menu()
        for label, fn in ((tr("Palette de commandes (Ctrl+K)"), self.show_palette), (tr("Paramètres (Ctrl+,)"), self.show_settings), (tr("Paramètres dans une fenêtre séparée"), lambda: self.show_settings(window=True)),
                          (tr("Aujourd'hui (T)"), self.show_today), (tr("Aide (F1)"), lambda: self.show_settings("help")),
                          (tr("Basculer clair / sombre"), self.toggle_theme), (tr("Tout marquer comme lu"), self.mark_all_read),
                          (tr("Mises à jour"), lambda: self.show_settings("updates")), (tr("Journal d'erreurs"), self.show_log), (tr("À propos"), self.show_about)):
            it = Gtk.MenuItem(label=label)
            it.connect("activate", lambda _i, f=fn: f())
            menu.append(it)
        menu.show_all()
        menu_btn.set_popup(menu)
        hb.pack_end(menu_btn)
        gear = Gtk.Button()
        gb = Gtk.Box(spacing=6)
        gb.pack_start(icon("preferences-system-symbolic"), False, False, 0)
        gb.pack_start(Gtk.Label(label=tr("Paramètres")), False, False, 0)
        gear.add(gb)
        gear.set_tooltip_text(tr("Paramètres (Ctrl+,)"))
        gear.get_style_context().add_class("pill")
        gear.connect("clicked", lambda *_: self.show_settings())
        hb.pack_end(gear)
        self.ai_btn = Gtk.ToggleButton(label=tr("✨ Assistant"))
        self.ai_btn.get_style_context().add_class("ai-btn")
        self.ai_btn.set_tooltip_text(tr("Assistant IA (Ctrl+J)"))
        self.ai_btn.connect("toggled", lambda b: self.toggle_assistant(b.get_active()))
        hb.pack_end(self.ai_btn)
        self.refresh_btn = icon_button("view-refresh-symbolic", tr("Actualiser (Ctrl+R)"))
        self.refresh_btn.connect("clicked", lambda *_: self.sync(True))
        hb.pack_end(self.refresh_btn)
        self.sel_btn = Gtk.ToggleButton()
        self.sel_btn.set_image(icon("object-select-symbolic", Gtk.IconSize.LARGE_TOOLBAR))
        self.sel_btn.set_tooltip_text(tr("Mode sélection multiple"))
        self.sel_btn.connect("toggled", self._toggle_select_mode)
        hb.pack_end(self.sel_btn)
        lay = Gtk.MenuButton()
        lay.set_image(icon("view-dual-symbolic", Gtk.IconSize.LARGE_TOOLBAR))
        lay.set_tooltip_text(tr("Disposition"))
        lm = Gtk.Menu()
        for label, fn in ((tr("Colonnes : liste | lecture"), lambda: self.set_layout("columns")),
                          (tr("Lecture en bas"), lambda: self.set_layout("bottom")),
                          (tr("Liste seule (lecture plein écran)"), lambda: self.set_layout("list")),
                          (tr("Barre latérale réduite / étendue"), self.toggle_rail)):
            it = Gtk.MenuItem(label=label)
            it.connect("activate", lambda _i, f=fn: f())
            lm.append(it)
        lm.show_all()
        lay.set_popup(lm)
        hb.pack_end(lay)

        # barre latérale
        self._build_sidebar()

        # liste
        self.list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.list_box.get_style_context().add_class("mm-list")
        self.list_box.set_size_request(260, -1)
        bar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        bar.get_style_context().add_class("mm-listbar")
        self.title_lbl = Gtk.Label(xalign=0)
        self.title_lbl.set_markup(tr("<b>Boîte intelligente</b>"))
        self.title_lbl.get_style_context().add_class("list-title")
        self.count_lbl = Gtk.Label(xalign=0)
        self.count_lbl.get_style_context().add_class("count-lbl")
        bar.pack_start(self.count_lbl, False, False, 0)
        self.srv_btn = Gtk.Button(label=tr("🔎 Chercher aussi sur le serveur"))
        self.srv_btn.get_style_context().add_class("pill")
        self.srv_btn.set_tooltip_text(tr("Cherche dans tous les messages du serveur, même ceux qui ne sont pas encore téléchargés"))
        self.srv_btn.set_no_show_all(True)
        self.srv_btn.connect("clicked", lambda *_: self.search_server_now())
        bar.pack_start(self.srv_btn, False, False, 0)
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
        self.f_unread = Gtk.ToggleButton(label=tr("Non lus"))
        self.f_att = Gtk.ToggleButton(label=tr("Pièces jointes"))
        for w, a in ((self.f_unread, "unread_only"), (self.f_att, "att_only")):
            w.connect("toggled", lambda b, attr=a: (setattr(self, attr, b.get_active()), self.reload_list(reset=True)))
            w.get_style_context().add_class("pill-toggle")
            flt.pack_start(w, False, False, 0)
        bar.pack_start(flt, False, False, 0)
        self.list_box.pack_start(bar, False, False, 0)
        self.demo_banner = Gtk.Box(spacing=8)
        self.demo_banner.get_style_context().add_class("banner")
        self.demo_banner.pack_start(Gtk.Label(label=tr("Mode démonstration")), True, True, 0)
        abtn = Gtk.Button(label=tr("✨ Activer l'IA"))
        abtn.get_style_context().add_class("ai-chip")
        abtn.connect("clicked", lambda *_: self.show_settings("ai"))
        self.demo_banner.pack_end(abtn, False, False, 0)
        ab = Gtk.Button(label=tr("Ajouter mon compte"))
        ab.connect("clicked", lambda *_: self.show_settings())
        self.demo_banner.pack_end(ab, False, False, 0)
        self.list_box.pack_start(self.demo_banner, False, False, 0)
        self.list_box.pack_start(self.build_digest_box(), False, False, 0)

        self.bulk_rev = Gtk.Revealer()
        bulk = Gtk.Box(spacing=6)
        bulk.get_style_context().add_class("bulkbar")
        self.bulk_lbl = Gtk.Label()
        bulk.pack_start(self.bulk_lbl, True, True, 0)
        for label, fn in ((tr("Archiver"), lambda: self.move_messages(self.selected_msgs(), "archive")),
                          (tr("Supprimer"), lambda: self.move_messages(self.selected_msgs(), "trash")),
                          (tr("Lu"), lambda: self.set_unread(self.selected_msgs(), False)),
                          (tr("Non lu"), lambda: self.set_unread(self.selected_msgs(), True)),
                          ("★", lambda: self.set_flag(self.selected_msgs(), "starred", True)),
                          (tr("Tout"), lambda: self.listbox.select_all() if self.select_mode else None),
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
        self.listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)   # un clic = un message ouvert
        self.listbox.set_sort_func(row_sort)
        self.listbox.set_header_func(row_header)
        self.listbox.connect("row-selected", self._on_row_selected)
        self.listbox.connect("selected-rows-changed", self._on_selection_changed)
        self.listbox.connect("row-activated", self._on_activated)
        self.listbox.connect("button-press-event", self._on_list_click)
        self.listbox.connect("button-press-event", self._on_list_context)
        sw = self.list_scroll = Gtk.ScrolledWindow()
        sw.add(self.listbox)
        sw.connect("edge-reached", self._on_edge)
        self.empty_lbl = Gtk.Label(label=tr("Aucun message"))
        self.empty_lbl.get_style_context().add_class("empty-state")
        self.list_stack = Gtk.Stack()
        self.list_stack.add_named(sw, "list")
        self.list_stack.add_named(self.empty_lbl, "empty")
        self.list_box.pack_start(self.list_stack, True, True, 0)

        self.reader = Reader(self.build_snooze_menu)
        self.reader.connect("action", self._reader_action)
        self.reader.connect("quick-reply", lambda _r, t: self.quick_reply(t))
        self.reader.connect("ai-action", self._on_ai_action)
        self.reader.connect("open-message", self._on_open_thread_message)

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
        body.pack_start(self.build_assistant(), False, False, 0)
        body.get_style_context().add_class("mm-root")
        self.root_stack = Gtk.Stack()
        self.root_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.root_stack.set_transition_duration(150)
        mail_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        line = Gtk.Box()
        line.get_style_context().add_class("aurora-line")   # filet dégradé signature (style Aurora)
        mail_page.pack_start(line, False, False, 0)
        self.update_banner = UpdateBanner(self)           # bandeau de mise à jour (glisse sous la barre de titre)
        mail_page.pack_start(self.update_banner, False, False, 0)
        mail_page.pack_start(body, True, True, 0)
        self.root_stack.add_named(mail_page, "mail")
        overlay = Gtk.Overlay()
        overlay.add(self.root_stack)
        self.toast = Toast()
        overlay.add_overlay(self.toast)
        self.add(overlay)
        self._fill_accounts()
        self._rebuild_nav_dynamic()
        self._nav_guard = True
        if self._nav_initial is not None:
            self.nav.select_row(self._nav_initial)
        self._nav_guard = False

    def _sidebar_footer(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_border_width(10)
        self.status = Gtk.Label(xalign=0)
        self.status.get_style_context().add_class("dim")
        self.status.set_line_wrap(True)
        box.pack_start(self.status, False, False, 0)
        self.p2p_lbl = Gtk.Label(xalign=0)
        self.p2p_lbl.get_style_context().add_class("dim")
        self.p2p_lbl.set_line_wrap(True)
        box.pack_start(self.p2p_lbl, False, False, 0)
        self.update_chip = Gtk.Button()                     # pastille « ⬆ Mise à jour X » : reste visible même si le bandeau est repoussé
        self.update_chip.get_style_context().add_class("update-chip")
        self.update_chip.set_halign(Gtk.Align.START)
        self.update_chip.set_relief(Gtk.ReliefStyle.NONE)
        self.update_chip.set_no_show_all(True)
        self.update_chip.connect("clicked", lambda *_: self.show_settings("updates"))
        box.pack_start(self.update_chip, False, False, 0)
        b = self.settings_btn = Gtk.Button(label=tr("Paramètres"))
        b.set_image(icon("preferences-system-symbolic"))
        b.set_always_show_image(True)
        b.set_relief(Gtk.ReliefStyle.NONE)
        b.connect("clicked", lambda *_: self.show_settings())
        box.pack_start(b, False, False, 0)
        rail = icon_button("pan-start-symbolic", tr("Réduire / étendre la barre latérale"), relief=False)
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
                raise RuntimeError(tr("Compte introuvable"))
            self._backends[aid] = make_backend(acc, self.config)
        return self._backends[aid]


    def _apply_server_flags(self, kn, flags):
        """Applique au cache les drapeaux lus sur la boîte : lu / favori / épinglé. L'épingle n'est touchée que si le serveur est PROUVÉ capable
        (None sinon) et jamais pour un message dont l'épingle locale attend encore d'être envoyée."""
        ups, pending_pins = {}, self._pending_pin_ids()
        for uid, fl in flags.items():
            mid = kn.get(uid)
            if mid:
                pinned = fl[2] if len(fl) > 2 and mid not in pending_pins else None
                ups.setdefault((fl[0], fl[1], pinned), []).append(mid)
        for (unread, starred, pinned), ids in ups.items():
            fields = {"unread": unread, "starred": starred}
            if pinned is not None:
                fields["pinned"] = pinned
            self.cache.update_many(ids, **fields)

    def _pending_pin_ids(self):
        """Messages dont une épingle / désépingle attend encore d'être envoyée (hors ligne) : la boîte ne doit pas l'écraser."""
        ids = set()
        try:
            for op in self.cache.ops_pending():
                if op["kind"] == "flags" and "pinned" in op["payload"]:
                    ids.update(i["id"] for i in op["payload"]["items"])
        except Exception:
            pass
        return ids

    def _save_pin_states(self):
        """Enregistre ce que le serveur a PROUVÉ (garde / ne garde pas les épingles) et, une fois par compte, envoie vers la boîte les épingles locales."""
        changed, to_push = False, []
        for aid, be in list(self._backends.items()):
            if getattr(be, "_pin_dirty", False):
                be._pin_dirty = False
                changed = True
            if getattr(be, "acc", {}).get("pin_server") is True and aid not in self.config.get("pins_pushed", []):
                to_push.append(aid)
        if to_push:
            self.config["pins_pushed"] = list(self.config.get("pins_pushed", [])) + to_push
            changed = True
        if changed:
            self.config.save()
        for aid in to_push:
            self.push_local_pins(aid, quiet=True)

    def push_local_pins(self, aid=None, quiet=False):
        """Envoie vers la boîte les épingles faites sur ce poste (avant la 1.13.2 elles restaient locales) : les autres postes les verront."""
        accounts = [aid] if aid else [a["id"] for a in self.accounts() if not a.get("demo")]
        total = [0]
        for a in accounts:
            msgs = self.cache.pinned_messages(a)
            if not msgs:
                continue
            total[0] += len(msgs)
            self._flag_remote_many(msgs, pinned=True, probe=not quiet, after=None if quiet else (
                lambda res, err, n: self.toast.popup(tr("%d épingle(s) envoyée(s) vers la boîte : les autres postes les verront.") % n, timeout=6)
                if res and not res[1] and not err else None))
        if not total[0] and not quiet:
            self.toast.popup(tr("Aucun message épinglé à envoyer."), timeout=4)

    def accounts_changed(self):
        self._stop_push()
        for be in list(self._backends.values()):
            try:
                be.close()
            except Exception:
                pass
        self._backends.clear()
        ids = {a["id"] for a in self.accounts()}
        self.folder_tree = {k: v for k, v in self.folder_tree.items() if k in ids}
        if self.config["accounts"]:
            self.cache.delete_account("demo")
        else:
            try:
                (DATA_DIR / "demo_seeded").unlink()   # le mode démo pourra se re-semer
            except OSError:
                pass
        self._fill_accounts()
        self._rebuild_nav_dynamic()
        self.refresh_folders()
        self.demo_banner.set_visible(not self.config["accounts"])
        self.reload_list(full=True)
        self.update_counts()
        self.sync(True)
        self._start_push()


    # -------------------------------------------------------------- réglages
    def apply_settings(self):
        theme = self.config["theme"]
        self.is_dark = theme == "dark" or (theme == "system" and self._system_dark)
        Gtk.Settings.get_default().set_property("gtk-application-prefer-dark-theme", self.is_dark)
        self.reader.style = self.config["style"]
        base, fancy = build_css(self.is_dark, self.config["accent"], self.config["density"], self.config["style"])
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
            self.reload_list(full=True)

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
                self.show_error(tr("Impossible d'ouvrir les paramètres"), e2 or e)

    def _settings_window(self, page=None):
        w = getattr(self, "_swin", None)
        if w is not None:
            w.present()
            if page:
                w.page.show_page(page)
            return
        w = Gtk.Window(title=tr("Paramètres de MintMail"))
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
                              text=title, secondary_text=tr("%s\n\nDétails dans le journal : %s") % (exc, LOG))
        d.add_buttons(tr("Fermer"), Gtk.ResponseType.CLOSE)
        d.run()
        d.destroy()

    def show_log(self):
        d = Gtk.Dialog(title=tr("Journal d'erreurs"), transient_for=self, modal=True)
        d.add_buttons(tr("Fermer"), Gtk.ResponseType.CLOSE)
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
        d.set_comments(tr("Client mail moderne pour Linux Mint.\nBoîte intelligente, reports, envoi annulable, signatures HTML."))
        d.set_website("https://saec.me")
        d.set_copyright("© 2026 SAEC")
        d.set_license_type(Gtk.License.MIT_X11)          # logiciel libre : licence MIT
        d.set_logo_icon_name("mintmail")
        d.run()
        d.destroy()

    # ------------------------------------------------------------ navigation

    def _category_toggled(self, btn, key):
        if btn.get_active():
            self.category = key
            self.reload_list(reset=True)

    def _search_changed(self, entry):
        if self._search_src:
            GLib.source_remove(self._search_src)

        def go():
            self._search_src = 0
            text = entry.get_text().strip()
            if text.startswith(("?", "✨")):
                return False   # question pour l'IA : attendre la touche Entrée
            self.search = text
            self.title_lbl.set_markup(tr("<b>Résultats</b>") if self.search else "<b>%s</b>" % GLib.markup_escape_text(self._view_title()))
            self.cat_sw.set_visible(self.view == "inbox" and not self.search)
            self.reload_list(reset=True)
            return False
        self._search_src = GLib.timeout_add(250, go)

    # ----------------------------------------------------------------- liste










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
        self.status.set_visible(not rail)
        for l in self.brand_labels:
            l.set_visible(not rail)
        self.settings_btn.set_label("" if rail else tr("Paramètres"))
        self.compose_lbl.set_visible(not rail)
        self.ai_nav_lbl.set_visible(not rail)
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

    def _notify(self, msgs):
        if not msgs or not self.config["notifications"]:
            return
        n = Gio.Notification.new(tr("%d nouveaux messages") % len(msgs) if len(msgs) > 1 else msgs[0].display_sender)
        n.set_body(msgs[0].subject if len(msgs) == 1 else "\n".join(
            "%s — %s" % (m.display_sender, m.subject) for m in msgs[:3]))
        self.get_application().send_notification("new-mail", n)

    def update_counts(self):
        c = self.cache.counts(self.account)
        for key, val in (("inbox", c["inbox"]), ("unread", c["unread"]), ("drafts", c["drafts"]),
                         ("snoozed", c["snoozed"])):
            b = self.badges[key]
            b.set_text(str(val))
            b.set_visible(val > 0)
        self._update_folder_badges()
        self.set_title("%s%s" % ("(%d) " % c["inbox"] if c["inbox"] else "", APP_NAME))

    def _tick(self):
        self._ticks += 1
        self.process_outbox()
        if self._ticks % 10 == 0:
            self.flush_ops()
        if self._ticks % 3 == 0:
            self._drain_sync_wanted()
        if self._ticks % 3 == 0 and hasattr(self, "p2p_lbl"):
            eng = self.sync_engine
            short = 0 < len(str(self.config.get("p2p_secret") or "")) < P2P_MIN_SECRET
            self.p2p_lbl.set_text("⇄ " + eng.short_label()
                                  if eng.is_enabled() else (tr("⇄ désactivée : code < %d car.") % P2P_MIN_SECRET if short else ""))
        if self._ticks % 60 == 30 and not self._sync_busy and not self._pending:
            self.refresh_folders_soon(40)                   # dossier créé / renommé sur un autre poste
            if time.time() - self._last_sync > 55:
                self.sync(False, ("inbox",), quiet=True)    # épingles, lu, favoris, rangements faits ailleurs
        if self._ticks % 30 == 0:
            woken = self.cache.wake_snoozed()
            if woken:
                self._notify(woken)
                self.reload_list()
                self.update_counts()
            self.check_followups()
            if self._ticks % 120 == 0:
                self.refresh_folder_counts()
            if time.time() - self._last_sync > self.config["refresh_minutes"] * 60:
                self.sync()
        return True

    # ------------------------------------------------------------ actions




    # ---------------------------------------------------------------- report
    def build_snooze_menu(self, callback=None):
        cb = callback or self.snooze_selected
        menu = Gtk.Menu()
        def at(days, hour):
            d = datetime.datetime.now() + datetime.timedelta(days=days)
            return d.replace(hour=hour, minute=0, second=0, microsecond=0).timestamp()

        def wd():
            return datetime.datetime.now().weekday()
        opts = [(tr("Plus tard aujourd'hui (+3 h)"), lambda: time.time() + 3 * 3600),
                (tr("Demain 8 h"), lambda: at(1, 8)),
                (tr("Ce week-end (samedi 9 h)"), lambda: at((5 - wd()) % 7 or 7, 9)),
                (tr("Semaine prochaine (lundi 8 h)"), lambda: at((7 - wd()) % 7 or 7, 8)),
                (tr("Choisir une date…"), None)]
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
        dlg = Gtk.Dialog(title=tr("Reporter jusqu'au…"), transient_for=self, modal=True)
        dlg.add_buttons(tr("Annuler"), Gtk.ResponseType.CANCEL, tr("Reporter"), Gtk.ResponseType.OK)
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




    # ------------------------------------------------------------ Synchronisation
    def _init_sync(self):
        """(Re)démarre la synchronisation automatique entre machines. Le moteur existe toujours."""
        old = getattr(self, "sync_engine", None)
        if old is not None:
            old.stop()
        self.sync_engine = SyncEngine(self.config, cache=self.cache, apply_cb=self._p2p_apply)
        self.sync_engine.start()   # sans effet si désactivé ou sans code de jumelage

    def _p2p_apply(self, wins):
        """Appelé par le moteur (thread de synchro) : applique les éléments reçus DANS le fil principal, puis attend."""
        box, ev = {}, threading.Event()

        def run():
            try:
                box["res"] = apply_items(self.config, wins, self.cache)
                self._p2p_refresh(box["res"])
            except Exception:
                log_exception("p2p apply")
            finally:
                ev.set()
            return False
        GLib.idle_add(run)
        ev.wait(15)
        return box.get("res")

    def _p2p_refresh(self, res):
        """Met l'interface à jour selon ce que la synchro vient de changer (comptes, réglages, IA, listes)."""
        if res["accounts"]:
            self.accounts_changed()
        if res["settings"]:
            self.apply_settings()
        if res["ai"]:
            self.refresh_ai()
        if res["lists"]:
            self._rebuild_nav_dynamic()
            self.reload_list()
        names = res.get("new_accounts") or []
        self.toast.popup((tr("Synchro : compte « %s » ajouté — ") % names[0] if names else tr("Synchro : ")) + describe_sync(res),
                         timeout=6)

    def sync_from_store(self):
        """Déclenche un échange P2P immédiat avec les pairs."""
        if hasattr(self, 'sync_engine') and self.sync_engine.is_enabled():
            return self.sync_engine.sync_now()
        return {}

    # ------------------------------------------------------------ rédaction
    def _default_account(self, msg=None):
        if msg and any(a["id"] == msg.account for a in self.accounts()):
            return msg.account
        return self.account if self.account != "all" else self.accounts()[0]["id"]











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
            self.toast.popup(tr("Envoi programmé pour le %s") % format_full(time.time() + delay), tr("Annuler"), undo, timeout=6)
        else:
            self.toast.popup(tr("Envoi du message…"), tr("Annuler"), undo, timeout=max(2, self.config["undo_seconds"] - 1))

    def process_outbox(self):
        for oid, out in self.cache.outbox_due():
            if oid in self._sending or not self.cache.outbox_claim(oid):
                continue          # déjà en cours ici, ou pris par l'envoi différé en tâche de fond
            self._sending.add(oid)

            def done(res, err, oid=oid, out=out):
                self._sending.discard(oid)
                if err and is_retryable(err) and self.cache.outbox_tries(oid) < 10:
                    self.cache.outbox_reschedule(oid, time.time() + 60)        # hors ligne : conservé, nouvel essai dans 1 min
                    self._net_error = True
                    self.update_offline_status()
                    self.toast.popup(tr("Hors ligne : message conservé, nouvel essai automatique."), timeout=5)
                    return
                self.cache.outbox_remove(oid)
                if err:
                    self.toast.popup(tr("Échec de l'envoi : %s") % str(err)[:90], tr("Rouvrir"), lambda: ComposeWindow(
                        self, self.accounts(), account_id=out.account, to=out.to, cc=out.cc, subject=out.subject,
                        body_html=out.html, raw=True, attachments=out.attachments), timeout=10)
                    return
                self.toast.popup(tr("Message envoyé ✔"), timeout=3)
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
            self.set_flag(msgs, "starred", not m.starred)   # met à jour la ligne et le lecteur en place
        elif act == "pin" and m:
            self.set_flag(msgs, "pinned", not m.pinned)
        elif act == "unread":
            self.set_unread(msgs, True)
        elif act == "unsubscribe" and m:
            self.unsubscribe(m)
        elif act in ("invite_accept", "invite_tentative", "invite_decline") and m:
            self.invite_respond(m, act.split("_", 1)[1] if act != "invite_accept" else "accept")
        elif act == "invite_add" and m:
            self.invite_add(m)
        elif act == "images" and m:
            reader.show_message(m, True)
        elif act == "move_menu":
            self.build_move_menu(msgs).popup_at_widget(reader.move_btn, Gdk.Gravity.SOUTH_WEST, Gdk.Gravity.NORTH_WEST, None)
        elif act in ("not_spam", "not_spam_domain") and m:
            self.not_spam(m, act == "not_spam_domain")
        elif act == "spam_sender" and m:
            self.spam_sender(m)
        elif act == "spam_domain" and m:
            self.spam_sender(m, True)
        elif act == "unblock" and m:
            self.unblock(m)
        elif act in ("menu_spam", "menu_block") and m:
            btn = reader.spam_btn if act == "menu_spam" else reader.block_btn
            self.sender_menu("spam" if act == "menu_spam" else "block", m).popup_at_widget(
                btn, Gdk.Gravity.SOUTH_WEST, Gdk.Gravity.NORTH_WEST, None)
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
        if key == "F1":
            self.show_settings("help")
            return True
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
        if key == "F11":
            self.toggle_fullscreen()
            return True
        if ctrl and key in ("j", "J"):
            self.toggle_assistant()
            return True
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
            self.sel_btn.set_active(True)   # sélection multiple uniquement à la demande
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
            "v": lambda: self.build_move_menu(msgs).popup_at_pointer(None),
            "b": lambda: m and self.sender_menu("block", m).popup_at_pointer(None),
            "exclam": lambda: self.move_messages(msgs, "spam"),
            "backslash": lambda: self.set_layout("columns" if self.config["layout"] == "list" else "list"),
            "x": lambda: self.sel_btn.set_active(not self.sel_btn.get_active()),
            "t": lambda: self.show_today(),
        }
        fn = acts.get(key)
        if fn:
            fn()
            return True
        return False


    # ----------------------------------------------------- gestes & actions



    # ------------------------------------------------- spam / blocage / règles




    def unblock(self, msg):
        em, dom = self._key(msg), self._key(msg, True)
        for k in ("blocked", "spam_senders"):
            self.config[k] = [x for x in self.config[k] if x.lower() not in (em, dom)]
        self.config.save()
        self.toast.popup(tr("%s débloqué") % msg.sender_email, timeout=3)

    def is_blocked(self, msg):
        keys = {self._key(msg), self._key(msg, True)}
        return any(x.lower() in keys for x in self.config["blocked"] + self.config["spam_senders"])

    def show_from(self, msg):
        self.search_entry.set_text("from:" + msg.sender_email)
        self.search_entry.grab_focus()

    def copy_text(self, text):
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(text, -1)
        self.toast.popup(tr("Copié : ") + text, timeout=2)

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
        moves, keep, folder_moves = {"trash": [], "spam": [], "archive": []}, [], {}
        for m in msgs:
            em = m.sender_email.lower()
            dom = "@" + em.split("@")[-1]
            dest = "trash" if (em in blocked or dom in blocked) else \
                   "spam" if (em in spam_s or dom in spam_s) else None
            fdest = None
            if dest is None:
                for r in rules:
                    if not self._rule_match(r, m):
                        continue
                    act = r.get("action")
                    if act == "move" and dest is None and fdest is None:
                        found = self.find_folder(r.get("folder", ""), m.account)     # règle « ranger dans un dossier »
                        if found:
                            fdest = dest_of(found[1])
                    elif act in moves and dest is None:
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
            if fdest and not dest:
                folder_moves.setdefault(fdest, []).append(m)
            else:
                (moves[dest] if dest else keep).append(m)
        for dest, lst in list(moves.items()) + list(folder_moves.items()):
            if lst:
                self._auto_move(lst, dest)
        return keep

    def apply_rules_now(self):
        left = self._auto_route(self.cache.query("inbox", "all"))
        self.reload_list()
        self.update_counts()
        self.toast.popup(tr("Règles appliquées (%d message(s) restent dans la boîte)") % len(left), timeout=4)



    # ------------------------------------------------------------- rappels
    def add_followup(self, msg, days):
        self.config["followups"].append({
            "id": msg.id, "at": time.time() + days * 86400, "subject": msg.subject, "date": msg.date,
            "to": msg.to if msg.folder == "sent" else msg.sender_email})
        self.config.save()
        self.toast.popup(tr("Rappel dans %d jours si aucune réponse") % days, timeout=4)

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
            self.toast.popup(tr("Pas de réponse à « %s »") % f["subject"][:50], timeout=8)

    # ---------------------------------------------------- recherches enregistrées

    def _saved_query(self):
        if self.view.startswith("saved:"):
            try:
                return self.config["saved_searches"][int(self.view[6:])]["query"]
            except (ValueError, IndexError):
                return ""
        return ""

    def _effective_search(self):
        return self.search or self._saved_query()


    def save_current_search(self):
        q = (self.search_entry.get_text() or self.search).strip()
        if not q:
            self.toast.popup(tr("Tapez d'abord une recherche, puis enregistrez-la"), timeout=3)
            return
        d = Gtk.Dialog(title=tr("Enregistrer la recherche"), transient_for=self, modal=True)
        d.add_buttons(tr("Annuler"), Gtk.ResponseType.CANCEL, tr("Enregistrer"), Gtk.ResponseType.OK)
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



    # --------------------------------------------------------------- fermeture
    # ----------------------------------------------------------- synchronisation
    def sync(self, manual=False, folders=("inbox", "sent"), quiet=False, accounts=None):
        """Synchronise les comptes en arrière-plan ; les nouveaux messages apparaissent par lots, les plus récents d'abord."""
        if self._sync_busy or self._pending:
            if manual:
                self.toast.popup(tr("Synchronisation déjà en cours…"), timeout=2)
            self.__dict__.setdefault("_sync_wanted", set()).update(folders)       # demande gardée : refaite dès que la synchro en cours est finie (un dossier de rangement n'attend plus la prochaine minuterie)
            return
        self._sync_busy = True
        if not quiet:
            self.status.set_text(tr("Synchronisation…"))
        accounts = [a for a in self.accounts() if not accounts or a["id"] in accounts]
        known = {(a["id"], f): self.cache.uids(a["id"], f) for a in accounts for f in folders}
        self._partial_ids = set()

        def on_batch(batch):
            GLib.idle_add(self._partial, batch)

        def work():
            out = []
            for a in accounts:
                be = self.backend(a["id"])
                for f in folders:
                    try:
                        out.append((a["id"], f, be.sync(f, known[(a["id"], f)], limit=self._fetch_limit.get((a["id"], f), 60), on_batch=on_batch), None))
                    except Exception as e:
                        out.append((a["id"], f, None, e))
            return out
        self.run_bg(work, lambda res, err: self._sync_done(res or [], err, known, manual))

    def _partial(self, batch):
        """Un lot de nouveaux messages vient d'arriver : on l'affiche tout de suite."""
        self.cache.upsert_many(batch)
        self._partial_ids.update(m.id for m in batch)
        self.reload_list()
        self.update_counts()
        return False

    def _sync_done(self, results, err, known, manual):
        """Intègre les résultats de synchronisation dans le cache et l'interface."""
        self._sync_busy = False
        errors, fresh, routed_inbox, net_flags = [], [], [], []
        for aid, f, data, e in results:
            if e or not data:
                if e:
                    errors.append(str(e))
                    net_flags.append(is_retryable(e))      # indépendant de la langue des messages
                continue
            msgs, flags, present, minuid = data
            self.cache.upsert_many([m for m in msgs if m.id not in self._partial_ids])
            kn = known[(aid, f)]
            self._apply_server_flags(kn, flags)
            if present is not None:
                gone = [mid for uid, mid in kn.items() if uid >= minuid and uid not in present]
                if gone:
                    self.cache.delete_many(gone)
            if f == "inbox":
                keep = self._auto_route([m for m in msgs if m.folder == "inbox"])
                routed_inbox += keep
                if kn:
                    fresh += [m for m in keep if m.unread]
        self._save_pin_states()
        self._last_sync = time.time()
        self._net_error = bool(errors) and any(net_flags)
        if not errors:
            self._set_offline(False)
        if errors:
            self.status.set_text("⚠ " + errors[0][:120])
            if manual:
                self.toast.popup(errors[0][:100], timeout=6)
        else:
            self.status.set_text(tr("Synchronisé à ") + time.strftime("%H:%M"))
            self.flush_ops()
        if errors and self._net_error:
            self.update_offline_status()
        self.reload_list()
        self.update_counts()
        self._notify(fresh)
        self.ai_triage(routed_inbox)
        self.refresh_folder_counts()
        GLib.timeout_add(300, lambda: (self._drain_sync_wanted(), False)[1])

    def _unread_jobs(self):
        """{compte: [dossiers]} à resynchroniser pour la vue « Non lus » : dossiers de rangement / archives où le serveur annonce des non lus,
        ou où le cache en garde (ils ont pu être lus ailleurs). Jamais Spam, Corbeille, Envoyés, Brouillons ni la boîte de réception (déjà synchronisée)."""
        cached, jobs = self.cache.folders_with_unread(), {}
        for a in self.accounts():
            if a.get("demo"):
                continue
            for e in self.tree_of(a["id"]):
                if not e["selectable"] or e["special"] in ("inbox", "sent", "drafts", "trash", "spam"):
                    continue
                dest = dest_of(e)
                if self.folder_unread.get((a["id"], e["name"]), 0) or (a["id"], dest) in cached:
                    jobs.setdefault(a["id"], []).append(dest)
        return jobs

    def sync_other_unread(self):
        """Va chercher les messages NON LUS rangés dans vos dossiers (règles, IA, rangement manuel, filtres du serveur) pour que la vue « Non lus »
        les montre tous : sans cela un message important rangé dans un dossier passerait inaperçu."""
        if self.__dict__.get("_other_busy"):
            return
        jobs = self._unread_jobs()
        if not jobs:
            return
        self._other_busy = True
        known = {(aid, f): self.cache.uids(aid, f) for aid, fs in jobs.items() for f in fs}

        def work():
            out = []
            for aid, fs in jobs.items():
                try:
                    be = self.backend(aid)
                except Exception:
                    continue
                for f in fs:
                    try:
                        out.append((aid, f, be.sync(f, known[(aid, f)], limit=60, unseen=True), None))
                    except Exception as e:
                        out.append((aid, f, None, e))
            return out

        def done(res, err):
            self._other_busy = False
            changed, fresh = False, []
            for aid, f, data, e in res or []:
                if e or not data:
                    continue
                msgs, flags, present, minuid = data
                kn = known[(aid, f)]
                self.cache.upsert_many(msgs)
                self._apply_server_flags(kn, flags)
                if present is not None:
                    gone = [mid for uid, mid in kn.items() if uid >= minuid and uid not in present]
                    if gone:
                        self.cache.delete_many(gone)
                        changed = True
                changed = changed or bool(msgs or flags)
                if kn:                                           # dossier déjà connu : ce qui arrive est vraiment nouveau (pas le premier remplissage)
                    fresh += [m for m in msgs if m.unread and time.time() - m.date < 86400]
            if changed:
                self.reload_list()
                self.update_counts()
            self._notify(fresh)
        self.run_bg(work, done)

    def _drain_sync_wanted(self):
        """Refait la synchronisation demandée pendant qu'une autre tournait (ex. le dossier où l'on vient de ranger des messages)."""
        wanted = self.__dict__.get("_sync_wanted")
        if wanted and not self._sync_busy and not self._pending:
            todo, self._sync_wanted = tuple(sorted(wanted)), set()
            self.sync(False, todo, quiet=True)

    # ----------------------------------------------------- push (IMAP IDLE)
    def _start_push(self):
        self._stop_push()
        self._push_stop = threading.Event()
        for a in self.accounts():
            if a.get("demo"):
                continue
            try:
                be = self.backend(a["id"])
            except Exception:
                continue
            threading.Thread(target=be.watch, args=(lambda: GLib.idle_add(self._push_ping), self._push_stop),
                             daemon=True, name="mintmail-idle").start()

    def _stop_push(self):
        ev = getattr(self, "_push_stop", None)
        if ev is not None:
            ev.set()

    def _push_ping(self):
        self.sync(False, ("inbox",), quiet=True)
        self.refresh_folders_soon(15)                       # un message rangé ailleurs a souvent un nouveau dossier derrière lui
        return False

    # -------------------------------------------------- déplacements en arrière-plan
    def _auto_move(self, msgs, dest):
        self.cache.update_many([m.id for m in msgs], folder=dest,
                               **({"unread": False} if dest in ("trash", "spam") else {}))
        self._bg_move(msgs, dest)

    def _bg_move(self, msgs, dest, notjunk=False):
        self._pending += 1
        op_ids = self.op_enqueue("move", msgs, dest=dest, **({"notjunk": True} if notjunk else {}))      # enregistré d'abord : rien n'est perdu si le réseau tombe

        def work():
            ops = [o for o in self.cache.ops_pending() if o["id"] in op_ids]
            return self.op_run(ops)

        def done(res, err):
            self._pending -= 1
            _ok, errs, offline = res if res else ([], [], False)
            self._set_offline(offline)
            if offline:
                self.toast.popup(tr("Hors ligne : le déplacement est conservé et sera envoyé dès le retour du réseau."), timeout=6)
                self.reload_list()
                self.update_counts()
                return
            if err or errs:
                self.toast.popup(tr("Échec du déplacement : %s") % ((errs or [str(err)])[0][:80]), timeout=6)
            real = []
            for m in msgs:
                try:
                    if not self.backend(m.account).demo:
                        real.append(m.id)
                except Exception:
                    pass
            if real:
                self.cache.delete_many(real)
                self.sync(folders=("inbox", dest), quiet=True)
            self.reload_list()
            self.update_counts()
            self._drain_sync_wanted()
        self.run_bg(work, done)

    # ------------------------------------------------------------ rédaction
    def _full(self, msg):
        """Message complet (avec corps) : la liste ne contient que des versions allégées."""
        if getattr(msg, "light", False):
            return self.cache.get(msg.id) or msg
        return msg

    def compose(self, **kw):
        kw.setdefault("account_id", self._default_account())
        ComposeWindow(self, self.accounts(), **kw)

    def _quote(self, msg):
        orig = sanitize_html(msg.html) if msg.html else text_to_html(msg.text)
        return tr('<div id="qt"><br><div>Le %s, %s a écrit :</div><blockquote>%s</blockquote></div>') % (
            format_full(msg.date), html.escape(msg.display_sender), orig)

    def reply(self, msg, all_=False, ai_text=""):
        msg = self._full(msg)
        to = msg.to if msg.folder == "sent" else (msg.reply_to or msg.sender_email)
        cc = ""
        if all_:
            mine = {a["email"].lower() for a in self.accounts()} | {i["email"].lower() for i in self.config.get("identities", [])}
            others = [a for a in split_addresses(msg.to) + split_addresses(msg.cc)
                      if a.lower() not in mine and a.lower() != msg.sender_email.lower()]
            cc = ", ".join(dict.fromkeys(others))
        self.compose(account_id=self._from_choice(msg), to=to, cc=cc,
                     subject="Re: " + normalize_subject(msg.subject), quote_html=self._quote(msg),
                     in_reply_to=msg.message_id, references=msg.references, ai_suggested_text=ai_text)

    def forward(self, msg):
        msg = self._full(msg)
        head = (tr("<br>---------- Message transféré ----------<br>De : %s &lt;%s&gt;<br>Date : %s<br>Objet : %s<br>À : %s<br>")
                % (html.escape(msg.sender_name), html.escape(msg.sender_email), format_full(msg.date),
                   html.escape(msg.subject), html.escape(msg.to)))
        self.compose(account_id=self._default_account(msg), subject="Fwd: " + normalize_subject(msg.subject),
                     quote_html='<div id="qt">' + head + (sanitize_html(msg.html) if msg.html else text_to_html(msg.text)) + "</div>",
                     attachments=[a["path"] for a in msg.attachments])

    def open_draft(self, msg):
        msg = self._full(msg)
        self.compose(account_id=msg.account, to=msg.to, cc=msg.cc, subject=msg.subject,
                     body_html=sanitize_html(msg.html), raw=True, in_reply_to=msg.message_id,
                     references=msg.references, attachments=[a["path"] for a in msg.attachments], draft_id=msg.id)

    def quick_reply(self, text):
        msg = self.reader.msg
        if not msg:
            return
        acc = next((a for a in self.accounts() if a["id"] == self._default_account(msg)), self.accounts()[0])
        ident = self._addressed_identity(msg)
        sig = (ident or {}).get("signature_html") or acc.get("signature_html", "")
        body = text_to_html(text) + ("<br><br>-- <br>" + sig if sig.strip() else "")
        out = Outgoing(account=acc["id"], to=(msg.reply_to or msg.sender_email),
                       subject="Re: " + normalize_subject(msg.subject), html=body,
                       from_email=ident["email"] if ident else "", from_name=ident.get("name", "") if ident else "",
                       in_reply_to=msg.message_id, references=msg.references)
        self.queue_send(out, 0)

    # -------------------------------------------------------- recherche & fenêtre
    def _search_activate(self, entry):
        """Entrée dans la barre de recherche : « ? … » ou une phrase libre déclenche la recherche IA."""
        text = entry.get_text().strip()
        words = text.split()
        if text.startswith(("?", "✨")) or (self.engine.enabled() and len(words) >= 4 and ":" not in text):
            self.ai_search(text)

    def toggle_fullscreen(self):
        fs = bool(self.get_window() and self.get_window().get_state() & Gdk.WindowState.FULLSCREEN)
        (self.unfullscreen if fs else self.fullscreen)()

    # ------------------------------------------------------------- palette
    def _palette_commands(self):
        sel = self.selected_msgs()
        m = self.reader.msg or (sel[0] if sel else None)
        cmds = []
        if m:
            who, dom = m.sender_email, "@" + m.sender_email.split("@")[-1]
            cmds += [
                (tr("Se désabonner de cet expéditeur"), lambda: self.unsubscribe(m)),
                (tr("✨ Résumer / analyser ce message"), lambda: self.ai_fetch(self._full(m), force=True)),
                (tr("✨ Répondre avec l'IA"), lambda: self.ai_reply_with_ai(m)),
                (tr("✨ Traduire ce message"), lambda: self._on_ai_action(self.reader, "translate", "")),
                (tr("Répondre"), lambda: self.reply(m)), (tr("Répondre à tous"), lambda: self.reply(m, True)),
                (tr("Transférer"), lambda: self.forward(m)),
                (tr("Archiver"), lambda: self.move_messages(self.selected_msgs() or [m], "archive")),
                (tr("Supprimer"), lambda: self.move_messages(self.selected_msgs() or [m], "trash")),
                *([(tr("✔ Ce n'est pas du spam — ") + who, lambda: self.not_spam(m))] if m.folder == "spam" else []),
                (tr("Signaler comme spam (ce message)"), lambda: self.move_messages(self.selected_msgs() or [m], "spam")),
                (tr("Mettre l'expéditeur en spam — ") + who, lambda: self.spam_sender(m)),
                (tr("Mettre le domaine en spam — ") + dom, lambda: self.spam_sender(m, True)),
                (tr("Bloquer l'expéditeur — ") + who, lambda: self.block_sender(m)),
                (tr("Bloquer le domaine — ") + dom, lambda: self.block_sender(m, True)),
                (tr("Voir tous les messages de ") + who, lambda: self.show_from(m)),
                (tr("Copier l'adresse ") + who, lambda: self.copy_text(who)),
                (tr("Reporter à demain 8 h"), lambda: self.run_action("snooze", self.selected_msgs() or [m])),
                (tr("Me rappeler si pas de réponse (3 jours)"), lambda: self.add_followup(m, 3)),
                (tr("Me rappeler si pas de réponse (7 jours)"), lambda: self.add_followup(m, 7)),
                (tr("Créer une règle pour ") + who, lambda: self.show_settings("filters")),
            ]
            if self.is_blocked(m):
                cmds.insert(9, (tr("Débloquer ") + who, lambda: self.unblock(m)))
        cmds += [
            (tr("✨ Ouvrir l'assistant IA"), lambda: self.toggle_assistant(True)),
            (tr("✨ Résumer ma boîte de réception"), lambda: self._maybe_digest(force=True)),
            (tr("Nouveau message"), self.compose), (tr("Actualiser"), lambda: self.sync(True)),
            (tr("Boîte d'envoi (messages en attente ou programmés)…"), self.show_outbox),
            (tr("Chercher aussi sur le serveur"), self.search_server_now),
            (tr("Aide et raccourcis (F1)"), lambda: self.show_settings("help")),
            (tr("Aujourd'hui : agenda, priorités, tâches, relances"), self.show_today),
            (tr("Nouvelle tâche…"), self.task_add_dialog),
            (tr("Agenda : prochains rendez-vous (Google Agenda)"), self.show_agenda),
            (tr("Nouvel événement dans l'agenda…"), self.new_event_dialog),
            (tr("Contacts…"), lambda: self.show_settings("contacts")),
            (tr("Identités d'envoi (alias)…"), lambda: self.show_settings("identities")),
            (tr("Gérer les expéditeurs bloqués et les règles"), lambda: self.show_settings("filters")),
            (tr("Appliquer les règles à la boîte de réception"), self.apply_rules_now),
            (tr("Enregistrer la recherche actuelle"), self.save_current_search),
            (tr("Disposition : colonnes"), lambda: self.set_layout("columns")),
            (tr("Disposition : lecture en bas"), lambda: self.set_layout("bottom")),
            (tr("Disposition : liste seule"), lambda: self.set_layout("list")),
            (tr("Barre latérale : réduire / étendre"), self.toggle_rail),
            (tr("Paramètres (Ctrl+,)"), self.show_settings),
            (tr("Paramètres dans une fenêtre séparée"), lambda: self.show_settings(window=True)),
            (tr("Réglages de l'IA"), lambda: self.show_settings("ai")),
            (tr("Envoyer mes épingles vers la boîte"), lambda: self.push_local_pins()),
            (tr("Rechercher les mises à jour"), lambda: self.check_updates(manual=True)), (tr("Mises à jour"), lambda: self.show_settings("updates")),
            (tr("Journal d'erreurs"), self.show_log), (tr("Gestes de swipe (réglages)"), lambda: self.show_settings("gestures")),
            (tr("Basculer thème clair / sombre"), self.toggle_theme), (tr("Plein écran (F11)"), self.toggle_fullscreen),
            (tr("Tout marquer comme lu"), self.mark_all_read),
            (tr("Tout sélectionner"), lambda: (self.sel_btn.set_active(True), self.listbox.select_all())),
            (tr("Rechercher"), lambda: self.search_entry.grab_focus()),
        ]
        for i, sv in enumerate(self.config["saved_searches"]):
            cmds.append((tr("Supprimer la recherche enregistrée : ") + sv["name"], lambda i=i: self.delete_saved(i)))
        multi = len(self.accounts()) > 1
        for acc in self.accounts():
            for e in self.tree_of(acc["id"]):
                if e["selectable"]:
                    nm = e["path"] + ((" — " + (acc.get("name") or acc["email"])) if multi else "")
                    cmds.append((tr("Aller au dossier : ") + nm, lambda a=acc["id"], e=e: self.goto_folder(a, e)))
        if m:
            cmds.insert(0, (tr("Déplacer vers un dossier…"), lambda: self.choose_folder_dialog(self.selected_msgs() or [m])))
        for vid, label, _ in NAV:
            cmds.append((tr("Aller à : ") + label, lambda v=vid: self._goto(v)))
        return cmds

    def show_palette(self):
        cmds = self._palette_commands()
        dlg = Gtk.Dialog(transient_for=self, modal=True)
        dlg.set_decorated(False)
        dlg.set_default_size(560, 400)
        box = dlg.get_content_area()
        box.set_border_width(8)
        e = Gtk.SearchEntry()
        e.set_placeholder_text(tr("Tapez une commande — ou demandez n'importe quoi à l'IA…"))
        box.pack_start(e, False, False, 4)
        lb = Gtk.ListBox()
        sw = Gtk.ScrolledWindow()
        sw.add(lb)
        box.pack_start(sw, True, True, 0)
        rows = []
        ai_row = Gtk.ListBoxRow()
        ai_lbl = Gtk.Label(label="", xalign=0, margin=8)
        ai_row.add(ai_lbl)
        ai_row.label = ""
        lb.add(ai_row)
        for label, fn in cmds:
            r = Gtk.ListBoxRow()
            r.fn, r.label = fn, label.lower()
            r.add(Gtk.Label(label=label, xalign=0, margin=8))
            lb.add(r)
            rows.append(r)
        closed = []

        def run(fn):
            closed.append(1)
            dlg.destroy()
            GLib.idle_add(lambda: (fn(), False)[1])

        def ask_ai():
            text = e.get_text().strip()
            run(lambda: self.assistant_ask(text))

        def visible(r):
            t = e.get_text().lower()
            if r is ai_row:
                return len(t.strip()) > 2
            return t in r.label

        def changed(*_):
            ai_lbl.set_text(tr("✨ Demander à l'assistant : « %s »") % e.get_text().strip())
            lb.invalidate_filter()
        lb.set_filter_func(visible)
        e.connect("search-changed", changed)

        def activate(*_):
            t = e.get_text().lower()
            for r in rows:
                if t in r.label:
                    run(r.fn)
                    return
            if len(t.strip()) > 2:
                ask_ai()
        e.connect("activate", activate)
        lb.connect("row-activated", lambda _l, r: ask_ai() if r is ai_row else run(r.fn))
        dlg.show_all()
        dlg.run()
        if not closed:
            dlg.destroy()


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
        self._stop_push()
        for be in list(self._backends.values()):
            try:
                be.close()
            except Exception:
                pass
        try:
            self.sync_engine.stop()
        except Exception:
            pass
        return False
