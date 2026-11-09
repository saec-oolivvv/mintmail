"""Dossiers : arborescence IMAP complète par compte, navigation, compteurs, déplacement, création / renommage / suppression."""
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, GLib

from .backend import utf7_decode
from .widgets import Avatar, icon

SMART_VIEWS = ("inbox", "unread", "starred", "pinned", "snoozed", "drafts")
LOGICAL = ("inbox", "sent", "drafts", "archive", "trash", "spam")
SPECIAL_ICONS = {"inbox": "mail-inbox-symbolic", "drafts": "document-edit-symbolic", "sent": "mail-send-symbolic",
                 "archive": "folder-symbolic", "spam": "mail-mark-junk-symbolic", "trash": "user-trash-symbolic"}
SPECIAL_LABELS = {"inbox": "Boîte de réception", "drafts": "Brouillons", "sent": "Envoyés", "archive": "Archives",
                  "spam": "Spam", "trash": "Corbeille"}
DEFAULT_TREE = [{"name": n, "path": SPECIAL_LABELS[k], "label": SPECIAL_LABELS[k], "depth": 0, "delim": "/",
                 "special": k, "selectable": True}
                for n, k in (("INBOX", "inbox"), ("Drafts", "drafts"), ("Sent", "sent"), ("Archive", "archive"),
                             ("Spam", "spam"), ("Trash", "trash"))]


def dest_of(entry):
    """Identifiant de destination d'un dossier : nom logique (sent, trash…) ou « f:<nom réel> »."""
    return entry["special"] if entry.get("special") in LOGICAL else "f:" + entry["name"]


class FolderMixin:
    # ------------------------------------------------------------------ état
    def _init_folders(self):
        self.folder_tree = {k: list(v) for k, v in (self.config.get("folders") or {}).items()}
        self.folder_unread, self._folder_badges = {}, {}
        self._dyn_rows, self._nav_guard, self._counts_busy = [], False, False
        self._collapsed = set(self.config.get("collapsed_folders") or [])
        self._fetch_limit = {}

    def tree_of(self, aid):
        return self.folder_tree.get(aid) or DEFAULT_TREE

    def folder_entry(self, aid, name):
        return next((e for e in self.tree_of(aid) if e["name"] == name), None)

    def find_folder(self, text, aid=None):
        """Retrouve un dossier par nom (insensible à la casse) : exact, fin de chemin, puis contient."""
        t = (text or "").strip().lower()
        if not t:
            return None
        accounts = [aid] if aid and aid != "all" else [a["id"] for a in self.accounts()]
        cands = [(a, e) for a in accounts for e in self.tree_of(a) if e["selectable"]]
        for test in (lambda e: e["label"].lower() == t or e["path"].lower() == t,
                     lambda e: e["path"].lower().endswith(t), lambda e: t in e["path"].lower()):
            for a, e in cands:
                if test(e):
                    return a, e
        return None

    # --------------------------------------------------------- barre latérale
    def _build_sidebar(self):
        """Marque, pastilles de comptes, boutons, arbre (smart + dossiers de chaque compte + recherches)."""
        self.sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.sidebar.get_style_context().add_class("mm-sidebar")
        self.sidebar.set_size_request(190, -1)
        brand = Gtk.Box(spacing=0)
        brand.get_style_context().add_class("wordmark")
        self.brand_labels = []
        for text, cls in (("◆ ", "wm-dot"), ("mint", "wm-a"), ("mail", "wm-b")):
            l = Gtk.Label(label=text)
            l.get_style_context().add_class(cls)
            brand.pack_start(l, False, False, 0)
            if cls != "wm-dot":
                self.brand_labels.append(l)
        self.sidebar.pack_start(brand, False, False, 0)
        self.orbs_box = Gtk.Box(spacing=8)
        self.orbs_box.set_margin_start(14)
        osw = Gtk.ScrolledWindow()
        osw.set_policy(Gtk.PolicyType.EXTERNAL, Gtk.PolicyType.NEVER)
        osw.add(self.orbs_box)
        self.sidebar.pack_start(osw, False, False, 4)
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
        self.ai_nav_btn = Gtk.Button()
        abox = Gtk.Box(spacing=8)
        abox.pack_start(Gtk.Label(label="✨"), False, False, 0)
        self.ai_nav_lbl = Gtk.Label(label="Assistant IA")
        abox.pack_start(self.ai_nav_lbl, False, False, 0)
        self.ai_nav_btn.add(abox)
        self.ai_nav_btn.get_style_context().add_class("ai-nav-btn")
        self.ai_nav_btn.connect("clicked", lambda *_: self.toggle_assistant())
        self.sidebar.pack_start(self.ai_nav_btn, False, False, 0)

        self.nav = Gtk.ListBox()
        self.nav.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.nav.set_activate_on_single_click(True)
        self.badges, self.nav_labels = {}, []
        self.nav.add(self._caption_row("Boîtes intelligentes"))
        for vid in SMART_VIEWS:
            label, ic = next((l, i) for k, l, i in self.NAV_ROWS if k == vid)
            r = Gtk.ListBoxRow()
            r.view, r.account = vid, None
            r.get_style_context().add_class("nav-row")
            r.get_style_context().add_class("nav-" + vid)
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
        self.nav.connect("row-activated", self._nav_activated)
        self.nav.connect("button-press-event", self._nav_context)
        nsw = Gtk.ScrolledWindow()
        nsw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        nsw.add(self.nav)
        self.sidebar.pack_start(nsw, True, True, 0)
        self.sidebar.pack_end(self._sidebar_footer(), False, False, 0)

    def _caption_row(self, text, toggle_key=None, account=None):
        r = Gtk.ListBoxRow()
        r.view, r.account, r.toggle_key = None, None, toggle_key
        r.set_selectable(False)
        r.set_activatable(bool(toggle_key))
        r.get_style_context().add_class("nav-caption-row")
        b = Gtk.Box(spacing=8)
        if account:
            b.pack_start(Avatar(account.get("name"), account["email"], 20), False, False, 0)
        l = Gtk.Label(label=text.upper() if not account else text, xalign=0)
        l.get_style_context().add_class("nav-caption")
        self.nav_labels.append(l)
        r.lab = l
        b.pack_start(l, True, True, 0)
        if toggle_key:
            chev = icon("pan-end-symbolic" if toggle_key in self._collapsed else "pan-down-symbolic")
            b.pack_end(chev, False, False, 0)
        r.add(b)
        r.show_all()
        return r

    def _folder_row(self, aid, e, has_children, collapsed, show_account):
        view = dest_of(e)
        r = Gtk.ListBoxRow()
        r.view, r.account, r.fname, r.entry, r.toggle_key = view, aid, e["name"], e, None
        r.set_selectable(bool(e["selectable"]))
        r.get_style_context().add_class("nav-row")
        r.get_style_context().add_class("folder-row")
        if e["special"]:
            r.get_style_context().add_class("nav-" + e["special"])
        b = Gtk.Box(spacing=6)
        b.set_margin_start(e["depth"] * 14)
        if has_children:
            ex = Gtk.Button()
            ex.set_image(icon("pan-end-symbolic" if collapsed else "pan-down-symbolic"))
            ex.set_relief(Gtk.ReliefStyle.NONE)
            ex.get_style_context().add_class("flat-btn")
            ex.connect("clicked", lambda _b, k="%s|%s" % (aid, e["path"]): self._toggle_collapse(k))
            b.pack_start(ex, False, False, 0)
        else:
            sp = Gtk.Box()
            sp.set_size_request(28, 1)
            b.pack_start(sp, False, False, 0)
        ic = SPECIAL_ICONS.get(e["special"], "folder-symbolic" if e["selectable"] else "folder-open-symbolic")
        b.pack_start(icon(ic), False, False, 0)
        lab = Gtk.Label(label=SPECIAL_LABELS.get(e["special"], e["label"]) if e["special"] in SPECIAL_LABELS and
                        e["label"].lower() in ("inbox", "drafts", "sent", "archive", "trash", "spam", "junk")
                        else e["label"], xalign=0)
        lab.set_ellipsize(3)
        self.nav_labels.append(lab)
        b.pack_start(lab, True, True, 0)
        badge = Gtk.Label()
        badge.get_style_context().add_class("badge")
        badge.set_no_show_all(True)
        b.pack_end(badge, False, False, 0)
        self._folder_badges[(aid, e["name"])] = (badge, e)
        r.add(b)
        r.show_all()
        self._set_badge(aid, e, badge)
        return r

    def _set_badge(self, aid, e, badge):
        if e["special"] == "inbox":
            n = self.cache.counts(aid)["inbox"]
        elif e["special"] == "drafts":
            n = self.cache.counts(aid)["drafts"]
        else:
            n = self.folder_unread.get((aid, e["name"]), 0)
        badge.set_text(str(n))
        badge.set_visible(n > 0)

    def _update_folder_badges(self):
        for (aid, name), (badge, e) in self._folder_badges.items():
            self._set_badge(aid, e, badge)

    def _rebuild_nav_dynamic(self):
        """Reconstruit la partie dynamique : dossiers de chaque compte (repliables) puis recherches enregistrées."""
        for r in self._dyn_rows:
            self.nav_labels = [l for l in self.nav_labels if l is not getattr(r, "lab", None)]
            self.nav.remove(r)
        self._dyn_rows, self._folder_badges = [], {}
        multi = len(self.accounts()) > 1
        added = [self._caption_row("Dossiers")]
        for acc in self.accounts():
            aid = acc["id"]
            hide_all = False
            if multi:
                key = "acc:" + aid
                added.append(self._caption_row(acc.get("name") or acc["email"], toggle_key=key, account=acc))
                hide_all = key in self._collapsed
            if hide_all:
                continue
            entries = self.tree_of(aid)
            paths = [e["path"] for e in entries]
            skip_prefix = None
            for e in entries:
                parts = e["path"].split(" › ")
                if skip_prefix and e["path"].startswith(skip_prefix + " › "):
                    continue
                skip_prefix = None
                has_children = any(p.startswith(e["path"] + " › ") for p in paths)
                collapsed = ("%s|%s" % (aid, e["path"])) in self._collapsed
                if has_children and collapsed:
                    skip_prefix = e["path"]
                added.append(self._folder_row(aid, e, has_children, collapsed, multi))
        if self.config["saved_searches"]:
            added.append(self._caption_row("Recherches"))
            for i, sv in enumerate(self.config["saved_searches"]):
                r = Gtk.ListBoxRow()
                r.view, r.account, r.toggle_key = "saved:%d" % i, None, None
                r.get_style_context().add_class("nav-row")
                b = Gtk.Box(spacing=10)
                b.pack_start(icon("system-search-symbolic"), False, False, 0)
                r.lab = Gtk.Label(label=sv["name"], xalign=0)
                self.nav_labels.append(r.lab)
                b.pack_start(r.lab, True, True, 0)
                r.add(b)
                r.show_all()
                added.append(r)
        self._nav_guard = True
        for r in added:
            self.nav.add(r)
        self._dyn_rows = added
        self._reselect_nav()
        self._nav_guard = False
        if hasattr(self, "settings_btn"):
            self._apply_sidebar()

    # compatibilité : l'ancien nom reconstruisait les recherches enregistrées
    _rebuild_saved = _rebuild_nav_dynamic

    def _reselect_nav(self):
        for r in list(self.nav.get_children()):
            if getattr(r, "view", None) == self.view and (getattr(r, "account", None) in (None, self.account)):
                self.nav.select_row(r)
                return

    def _toggle_collapse(self, key):
        (self._collapsed.discard if key in self._collapsed else self._collapsed.add)(key)
        self.config["collapsed_folders"] = sorted(self._collapsed)
        self.config.save()
        self._rebuild_nav_dynamic()

    def _nav_activated(self, lb, row):
        key = getattr(row, "toggle_key", None)
        if key:
            self._toggle_collapse(key)

    # ------------------------------------------------------------ navigation
    def _nav_selected(self, lb, row):
        if self._nav_guard or row is None or getattr(row, "view", None) is None:
            return
        self.view = row.view
        acc = getattr(row, "account", None)
        if acc:
            self.account = acc
            self._sync_orbs()
        if self.view in self.TITLES:
            self.config["last_view"] = self.view
        self.search_entry.set_text("")
        self.search = ""
        self.cat_sw.set_visible(self.view == "inbox")
        self.title_lbl.set_markup("<b>%s</b>" % GLib.markup_escape_text(self._view_title()))
        self.listbox.unselect_all()
        self.reader.show_empty()
        self.reader_open = False
        self._layout()
        self._digest_key = None
        self.reload_list(reset=True, full=True)
        if self._zone == 0:
            self.side_toggle.set_active(False)
        if self.view not in SMART_VIEWS and not self.view.startswith("saved:") and self.view != "snoozed":
            self.sync(folders=(self.view,), quiet=True,
                      accounts=None if self.account == "all" else [self.account])

    def _goto(self, vid):
        rows = [r for r in self.nav.get_children() if getattr(r, "view", None) == vid]
        pick = next((r for r in rows if r.account in (None, self.account)), rows[0] if rows else None)
        if pick is not None:
            self.nav.select_row(pick)

    def goto_folder(self, aid, entry):
        self.account = aid
        self._sync_orbs()
        self.view = dest_of(entry)
        self._rebuild_nav_dynamic()
        for r in self.nav.get_children():
            if getattr(r, "fname", None) == entry["name"] and r.account == aid:
                self.nav.select_row(r)
                return

    def _view_title(self):
        v = self.view
        if v.startswith("saved:"):
            try:
                return self.config["saved_searches"][int(v[6:])]["name"]
            except (ValueError, IndexError):
                return "Recherche"
        acc = next((a for a in self.accounts() if a["id"] == self.account), None)
        suffix = (" — " + (acc.get("name") or acc["email"])) if acc and len(self.accounts()) > 1 else ""
        if v.startswith("f:"):
            e = self.folder_entry(self.account, v[2:]) if self.account != "all" else None
            return (e["path"] if e else utf7_decode(v[2:])) + suffix
        return self.TITLES.get(v, "") + (suffix if v in LOGICAL else "")

    def load_older(self):
        """Bas de liste atteint dans un dossier : charge une page de messages plus anciens depuis le serveur."""
        if self.view in SMART_VIEWS or self.view.startswith("saved:") or self._effective_search():
            return
        scope = [self.account] if self.account != "all" else [a["id"] for a in self.accounts()]
        for aid in scope:
            self._fetch_limit[(aid, self.view)] = self._fetch_limit.get((aid, self.view), 60) + 60
        self.sync(folders=(self.view,), quiet=True, accounts=None if self.account == "all" else [self.account])

    # ---------------------------------------------------------------- comptes
    def _fill_accounts(self):
        for ch in self.orbs_box.get_children():
            self.orbs_box.remove(ch)
        self._orbs = {}
        if self.account != "all" and self.account not in [a["id"] for a in self.accounts()]:
            self.account = "all"
        items = [("all", "Tous les comptes", None)] + [(a["id"], a.get("name") or a["email"], a) for a in self.accounts()]
        for aid, name, acc in items:
            btn = Gtk.Button()
            btn.set_relief(Gtk.ReliefStyle.NONE)
            btn.set_tooltip_text(name)
            btn.get_style_context().add_class("orb")
            if acc:
                btn.add(Avatar(acc.get("name"), acc["email"], 30))
            else:
                l = Gtk.Label(label="✦")
                l.set_size_request(30, 30)
                btn.add(l)
            btn.connect("clicked", lambda _b, a=aid: self._orb_clicked(a))
            btn.show_all()
            self.orbs_box.pack_start(btn, False, False, 0)
            self._orbs[aid] = btn
        self._sync_orbs()

    def _sync_orbs(self):
        for aid, btn in getattr(self, "_orbs", {}).items():
            ctx = btn.get_style_context()
            (ctx.add_class if aid == self.account else ctx.remove_class)("orb-active")

    def _orb_clicked(self, aid):
        self.account = aid
        self._sync_orbs()
        self._digest_key = None
        self.title_lbl.set_markup("<b>%s</b>" % GLib.markup_escape_text(self._view_title()))
        self.reload_list(reset=True, full=True)
        self.update_counts()

    # --------------------------------------------------------- liste & compteurs
    def refresh_folders(self):
        """Relit l'arborescence des dossiers de chaque compte (arrière-plan) puis met à jour l'arbre et les compteurs."""
        accts = list(self.accounts())

        def work():
            out = {}
            for a in accts:
                try:
                    out[a["id"]] = self.backend(a["id"]).list_folders()
                except Exception:
                    continue
            return out

        def done(res, err):
            changed = False
            for aid, ents in (res or {}).items():
                if ents and ents != self.folder_tree.get(aid):
                    self.folder_tree[aid] = ents
                    changed = True
            if changed:
                self.config["folders"] = self.folder_tree
                self.config.save()
                self._rebuild_nav_dynamic()
            self.refresh_folder_counts()
        self.run_bg(work, done)

    def refresh_folder_counts(self):
        if self._counts_busy:
            return
        self._counts_busy = True
        todo = [(a["id"], [e["name"] for e in self.tree_of(a["id"]) if e["selectable"]][:60]) for a in self.accounts()]

        def work():
            res = {}
            for aid, names in todo:
                try:
                    res[aid] = self.backend(aid).folder_status(names)
                except Exception:
                    continue
            return res

        def done(res, err):
            self._counts_busy = False
            for aid, st in (res or {}).items():
                for name, (_n, unseen) in st.items():
                    self.folder_unread[(aid, name)] = unseen
            self._update_folder_badges()
        self.run_bg(work, done)

    # ------------------------------------------------ déplacer vers un dossier
    def build_move_menu(self, msgs=None):
        msgs = msgs or self.selected_msgs()
        menu = Gtk.Menu()
        if not msgs:
            return menu
        aid = msgs[0].account
        current = {m.folder for m in msgs}
        head = Gtk.MenuItem(label="Déplacer vers…")
        head.set_sensitive(False)
        menu.append(head)
        for e in self.tree_of(aid):
            if not e["selectable"] or dest_of(e) in current:
                continue
            label = "%s%s" % ("     " * e["depth"], SPECIAL_LABELS.get(e["special"], e["label"]))
            it = Gtk.MenuItem(label=label)
            it.connect("activate", lambda _i, d=dest_of(e), n=e["path"]: self._move_to(msgs, d, n))
            menu.append(it)
        menu.show_all()
        return menu

    def _move_to(self, msgs, dest, name):
        self.move_messages(msgs, dest, label="déplacé vers « %s »" % name)

    def choose_folder_dialog(self, msgs):
        """Sélecteur de dossier avec filtre (palette de commandes)."""
        if not msgs:
            return
        aid = msgs[0].account
        dlg = Gtk.Dialog(title="Déplacer vers…", transient_for=self, modal=True)
        dlg.add_buttons("Annuler", Gtk.ResponseType.CANCEL)
        dlg.set_default_size(380, 420)
        e = Gtk.SearchEntry()
        lb = Gtk.ListBox()
        sw = Gtk.ScrolledWindow()
        sw.add(lb)
        box = dlg.get_content_area()
        box.pack_start(e, False, False, 6)
        box.pack_start(sw, True, True, 0)
        rows = []
        for ent in self.tree_of(aid):
            if not ent["selectable"]:
                continue
            r = Gtk.ListBoxRow()
            r.entry = ent
            r.add(Gtk.Label(label="%s%s" % ("     " * ent["depth"], ent["path"].split(" › ")[-1] if ent["depth"] else
                                            SPECIAL_LABELS.get(ent["special"], ent["label"])), xalign=0, margin=8))
            lb.add(r)
            rows.append(r)
        lb.set_filter_func(lambda r: e.get_text().lower() in r.entry["path"].lower())
        e.connect("search-changed", lambda *_: lb.invalidate_filter())
        picked = []

        def pick(_lb, r):
            picked.append(r.entry)
            dlg.response(Gtk.ResponseType.OK)
        lb.connect("row-activated", pick)
        dlg.show_all()
        ok = dlg.run() == Gtk.ResponseType.OK
        dlg.destroy()
        if ok and picked:
            self._move_to(msgs, dest_of(picked[0]), picked[0]["path"])

    # ------------------------------------------------ gestion des dossiers (menu clic droit)
    def _nav_context(self, lb, ev):
        if ev.button != 3:
            return False
        row = lb.get_row_at_y(int(ev.y))
        if row is None:
            return False
        aid = getattr(row, "account", None)
        entry = getattr(row, "entry", None)
        key = getattr(row, "toggle_key", None)
        if key and key.startswith("acc:"):
            aid = key[4:]
        if not aid or (entry is None and not key):
            return False
        menu = Gtk.Menu()
        items = []
        if entry is not None and entry["selectable"]:
            items.append(("Actualiser ce dossier", lambda: self.sync(folders=(dest_of(entry),), accounts=[aid], manual=True)))
        items.append(("Nouveau dossier…" if entry is None else "Nouveau sous-dossier…",
                      lambda: self.folder_create(aid, entry)))
        if entry is not None and not entry["special"]:
            items.append(("Renommer…", lambda: self.folder_rename(aid, entry)))
            items.append(("Supprimer…", lambda: self.folder_delete(aid, entry)))
        items.append(("Actualiser la liste des dossiers", self.refresh_folders))
        for label, fn in items:
            mi = Gtk.MenuItem(label=label)
            mi.connect("activate", lambda _i, f=fn: f())
            menu.append(mi)
        menu.show_all()
        menu.popup_at_pointer(ev)
        return True

    def _ask_text(self, title, label, default=""):
        d = Gtk.Dialog(title=title, transient_for=self, modal=True)
        d.add_buttons("Annuler", Gtk.ResponseType.CANCEL, "OK", Gtk.ResponseType.OK)
        d.set_default_response(Gtk.ResponseType.OK)
        e = Gtk.Entry(text=default)
        e.set_activates_default(True)
        box = d.get_content_area()
        box.set_border_width(12)
        box.set_spacing(8)
        box.pack_start(Gtk.Label(label=label, xalign=0), False, False, 0)
        box.pack_start(e, False, False, 0)
        d.show_all()
        ok = d.run() == Gtk.ResponseType.OK
        text = e.get_text().strip()
        d.destroy()
        return text if ok and text else None

    def _folder_op(self, aid, fn, ok_text):
        def done(_res, err):
            if err:
                self.toast.popup("Dossier : %s" % str(err)[:100], timeout=6)
            else:
                self.toast.popup(ok_text, timeout=3)
            self.refresh_folders()
        self.run_bg(lambda: fn(self.backend(aid)), done)

    def folder_create(self, aid, parent):
        name = self._ask_text("Nouveau dossier", "Nom du dossier" + (" (dans « %s »)" % parent["label"] if parent else ""))
        if not name:
            return
        delim = parent["delim"] if parent else "/"
        if delim in name:
            self.toast.popup("Le nom ne peut pas contenir « %s »" % delim, timeout=4)
            return
        path = (utf7_decode(parent["name"]) + delim + name) if parent else name
        self._folder_op(aid, lambda be: be.create_folder(path), "Dossier « %s » créé" % name)

    def folder_rename(self, aid, entry):
        name = self._ask_text("Renommer le dossier", "Nouveau nom", entry["label"])
        if not name or name == entry["label"]:
            return
        decoded, delim = utf7_decode(entry["name"]), entry["delim"]
        new_path = (decoded[:decoded.rfind(delim)] + delim + name) if delim and delim in decoded else name
        self._folder_op(aid, lambda be: be.rename_folder(entry["name"], new_path), "Dossier renommé en « %s »" % name)

    def folder_delete(self, aid, entry):
        d = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.WARNING,
                              text="Supprimer le dossier « %s » ?" % entry["path"],
                              secondary_text="Les messages qu'il contient seront supprimés du serveur.")
        d.add_buttons("Annuler", Gtk.ResponseType.CANCEL, "Supprimer", Gtk.ResponseType.OK)
        ok = d.run() == Gtk.ResponseType.OK
        d.destroy()
        if not ok:
            return
        self.cache.delete_folder(aid, "f:" + entry["name"])
        if self.view == "f:" + entry["name"]:
            self.view = "inbox"
        self._folder_op(aid, lambda be: be.delete_folder(entry["name"]), "Dossier supprimé")
