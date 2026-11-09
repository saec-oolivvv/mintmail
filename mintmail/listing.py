"""Liste des messages et actions : mises à jour incrémentales (aucune reconstruction complète),
sélection simple fiable (un clic ouvre), actions groupées en une transaction."""
import datetime
import time

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, GLib

from .util import format_full
from .widgets import MessageRow

PAGE = 100
FOLDER_VERBS = {"archive": "archivé", "trash": "supprimé", "spam": "signalé comme spam", "inbox": "déplacé"}


class ListMixin:
    # ---------------------------------------------------------------- construction
    def _row_height(self):
        return {"compact": 64, "comfortable": 72, "spacious": 80}.get(self.config["density"], 72)

    def _make_row(self, m, ai):
        row = MessageRow(m, self._row_checked, self._on_swipe,
                         dict(self.config["swipe"], invert=self.config["swipe_invert"]), self._row_height(), ai)
        row.set_select_mode(self.select_mode)
        return row

    def reload_list(self, select_index=None, full=False, reset=False):
        """Synchronise la liste avec la base : ajoute / retire / met à jour les lignes concernées seulement."""
        if reset:
            self._limit = PAGE
        grouped = self.threads_on() and not self._effective_search() and self.view not in ("drafts", "outbox")
        msgs = self.cache.query(self.view, self.account, self.category if self.view == "inbox" else None,
                                self.unread_only, self.att_only, self._effective_search(), limit=self._limit, threads=grouped)
        self.srv_btn.set_visible(bool(self._effective_search()) and any(not a.get("demo") for a in self.accounts()))
        ai = self.cache.ai_meta([m.id for m in msgs])
        sel = self.listbox.get_selected_row()
        sel_id = sel.msg.id if sel is not None else None
        self._loading = True
        try:
            if full:
                for ch in self.listbox.get_children():
                    self.listbox.remove(ch)
                self.rows = {}
            keep = {m.id for m in msgs}
            for mid in [i for i in self.rows if i not in keep]:
                self.listbox.remove(self.rows.pop(mid))
            for m in msgs:
                row = self.rows.get(m.id)
                if row is None:
                    row = self.rows[m.id] = self._make_row(m, ai.get(m.id))
                    self.listbox.add(row)
                else:
                    row.update_msg(m, ai.get(m.id))
            self.listbox.invalidate_sort()
            self.listbox.invalidate_headers()
            if not self.select_mode:
                if sel_id in self.rows:
                    self.listbox.select_row(self.rows[sel_id])
                elif select_index is not None and msgs and not self.single:
                    r = self.listbox.get_row_at_index(min(select_index, len(msgs) - 1))
                    if r:
                        self.listbox.select_row(r)
        finally:
            self._loading = False
        self.list_stack.set_visible_child_name("list" if msgs else "empty")
        self.empty_lbl.set_text("Aucun résultat" if self._effective_search() else "Aucun message ici — profitez-en 🎉")
        self._sync_reader()
        self.refresh_digest_visibility()
        unread = sum(1 for r in self.rows.values() if r.msg.unread)
        n = len(self.rows)
        self.count_lbl.set_text("%d message%s · %d non lu%s" % (n, "s" if n > 1 else "", unread, "s" if unread > 1 else ""))

    def _sync_reader(self):
        """Aligne le lecteur sur la sélection après une mise à jour de la liste."""
        if self.select_mode:
            self._update_bulk()
            return
        row = self.listbox.get_selected_row()
        if row is None:
            if self.reader.msg is not None and self.reader.msg.id not in self.rows:
                self.reader.show_empty()
                if self.single:
                    self.reader_open = False
                    self._layout()
        elif self.reader.msg is None or (self.reader.msg.id != row.msg.id and not (
                self.threads_on() and getattr(row.msg, "thread_id", None) and
                getattr(self.reader.msg, "thread_id", "") == row.msg.thread_id)):
            self.open_message(row.msg)

    def _on_edge(self, sw, pos):
        """Défilement jusqu'en bas : charge les messages suivants."""
        if pos != Gtk.PositionType.BOTTOM:
            return
        if len(self.rows) >= self._limit:
            self._limit += PAGE
            self.reload_list()
        else:
            self.load_older()

    # ---------------------------------------------------------------- sélection
    def selected_msgs(self):
        if self.select_mode:
            msgs = [r.msg for r in self.listbox.get_selected_rows()]
        else:
            r = self.listbox.get_selected_row()
            msgs = [r.msg] if r is not None else []
        if not msgs and self.reader.msg:
            msgs = [self.reader.msg]
        return self._expand_threads(msgs)

    def _selected_index(self):
        r = self.listbox.get_selected_row()
        return r.get_index() if r is not None else None

    def _on_row_selected(self, lb, row):
        """Un clic sur une ligne l'ouvre, que le lecteur soit vide ou non."""
        if self._loading or self.select_mode or row is None:
            return
        self.open_message(row.msg)

    def _on_selection_changed(self, lb):
        if self.select_mode and not self._loading:
            self._update_bulk()

    def _update_bulk(self):
        rows = self.listbox.get_selected_rows()
        n = len(rows)
        sel = set(rows)
        for r in self.rows.values():
            r.set_checked(r in sel)
        self.bulk_rev.set_reveal_child(n >= 1)
        self.bulk_lbl.set_text("%d sélectionné%s" % (n, "s" if n > 1 else ""))
        if n > 1:
            self.reader.show_multi(n)
        elif n == 1:
            self.open_message(rows[0].msg)
        else:
            self.reader.show_empty()

    def open_message(self, msg, force=False):
        full = self.cache.get(msg.id) or msg
        if not force and self.reader.msg is not None and self.reader.msg.id == full.id and self.reader.is_open():
            if self.single and not self.reader_open:
                self.reader_open = True
                self._layout()
            return
        self.reader.show_message(full, self.config["load_images"])
        if self.single:
            self.reader_open = True
            self._layout()
        if msg.unread and msg.folder != "drafts":
            self.set_unread([msg], False, reload=False)
        self._open_thread_extras(msg, full)
        self.ai_open_message(full)

    def _on_activated(self, lb, row):
        if self.select_mode:
            return
        if row.msg.folder == "drafts":
            self.open_draft(self.cache.get(row.msg.id) or row.msg)
        else:
            self.open_message(row.msg, force=self.single)

    def _row_checked(self, row, active):
        (self.listbox.select_row if active else self.listbox.unselect_row)(row)

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
            if not self.select_mode:
                lb.select_row(row)
            else:
                lb.unselect_all()
                lb.select_row(row)
        m = self.cache.get(row.msg.id) or row.msg
        menu = Gtk.Menu()
        items = [("Répondre", lambda: self.reply(m)), ("Répondre à tous", lambda: self.reply(m, True)),
                 ("Transférer", lambda: self.forward(m)), ("✨ Répondre avec l'IA", lambda: self.ai_reply_with_ai(m)), None,
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
                 ("Voir tous ses messages", lambda: self.show_from(m)),
                 ("Ajouter aux contacts", lambda: self.contact_add(m))]
        if getattr(m, "unsubscribe", ""):
            items.append(("Se désabonner de cet expéditeur", lambda: self.unsubscribe(m)))
        items += [None] + self.ai_menu_items(m)    # section IA : classement, réponses, résumé, traduction, agenda…
        for it in items:
            if it is None:
                menu.append(Gtk.SeparatorMenuItem())
                continue
            if it[0] == "sous-menu":
                sub = Gtk.Menu()
                for lab, fn in it[2]:
                    si = Gtk.MenuItem(label=lab)
                    si.connect("activate", lambda _i, f=fn: f())
                    sub.append(si)
                mi = Gtk.MenuItem(label=it[1])
                mi.set_submenu(sub)
                menu.append(mi)
                continue
            mi = Gtk.MenuItem(label=it[0])
            mi.connect("activate", lambda _i, f=it[1]: f())
            menu.append(mi)
        sn = Gtk.MenuItem(label="Reporter")
        sn.set_submenu(self.build_snooze_menu())
        menu.append(sn)
        mv = Gtk.MenuItem(label="Déplacer vers un dossier")
        mv.set_submenu(self.build_move_menu(self.selected_msgs()))
        menu.append(mv)
        menu.show_all()
        menu.popup_at_pointer(ev)
        return True

    def _toggle_select_mode(self, btn):
        self.select_mode = btn.get_active()
        self._loading = True
        self.listbox.unselect_all()
        self.listbox.set_selection_mode(Gtk.SelectionMode.MULTIPLE if self.select_mode else Gtk.SelectionMode.SINGLE)
        for r in self.rows.values():
            r.set_select_mode(self.select_mode)
        self._loading = False
        if self.select_mode:
            self._update_bulk()
        else:
            self.bulk_rev.set_reveal_child(False)

    def _step(self, d):
        cur = self._selected_index()
        n = len(self.rows)
        if not n:
            return
        i = 0 if cur is None else max(0, min(n - 1, cur + d))
        r = self.listbox.get_row_at_index(i)
        if r:
            self.listbox.select_row(r)
            r.grab_focus()

    # ------------------------------------------------------------------ actions
    def remove_rows(self, ids, select_next=True):
        ids = [i for i in ids if i in self.rows]
        sel = self.listbox.get_selected_row()
        idx = sel.get_index() if sel is not None else None
        removed_sel = (sel is not None and sel.msg.id in ids) or \
                      (self.reader.msg is not None and self.reader.msg.id in ids)
        self._loading = True
        for mid in ids:
            self.listbox.remove(self.rows.pop(mid))
        self.listbox.invalidate_headers()
        self._loading = False
        self.list_stack.set_visible_child_name("list" if self.rows else "empty")
        if removed_sel:
            if select_next and not self.single and not self.select_mode and self.rows:
                r = self.listbox.get_row_at_index(min(idx if idx is not None else 0, len(self.rows) - 1))
                if r:
                    self.listbox.select_row(r)
                    self.open_message(r.msg)
                    return
            self.reader.show_empty()
            if self.single:
                self.reader_open = False
                self._layout()

    def sender_menu_items(self, kind, msg):
        """Entrées (libellé, action) des menus Spam / Bloquer / Plus d'actions ; les libellés montrent l'adresse et le domaine."""
        who = msg.sender_email
        dom = "@" + who.split("@")[-1]
        if kind == "spam":
            return [("Signaler ce message comme spam", lambda: self.move_messages([msg], "spam")),
                    ("Mettre %s en spam" % who, lambda: self.spam_sender(msg)),
                    ("Mettre tout le domaine %s en spam" % dom, lambda: self.spam_sender(msg, True))]
        if kind == "block":
            items = [("Bloquer %s" % who, lambda: self.block_sender(msg)),
                     ("Bloquer tout le domaine %s" % dom, lambda: self.block_sender(msg, True))]
            if self.is_blocked(msg):
                items.append(("Débloquer %s" % who, lambda: self.unblock(msg)))
            return items
        return [("Marquer comme %s" % ("lu" if msg.unread else "non lu"), lambda: self.set_unread([msg], not msg.unread)),
                ("Désépingler" if msg.pinned else "Épingler", lambda: self.set_flag([msg], "pinned", not msg.pinned)),
                ("Retirer des favoris" if msg.starred else "Ajouter aux favoris",
                 lambda: self.set_flag([msg], "starred", not msg.starred)),
                ("✨ Ranger / suggérer un dossier", lambda: self.ai_suggest_folder(msg)),
                ("✨ Classer ma boîte de réception", lambda: self.ai_classify(self.cache.query("inbox", self.account, limit=60))),
                ("✨ Répondre avec l'IA", lambda: self.ai_reply_with_ai(msg)),
                ("Voir tous les messages de %s" % who, lambda: self.show_from(msg)),
                ("Copier l'adresse %s" % who, lambda: self.copy_text(who)),
                ("Me rappeler si pas de réponse (3 jours)", lambda: self.add_followup(msg, 3))]

    def sender_menu(self, kind, msg):
        menu = Gtk.Menu()
        for label, fn in self.sender_menu_items(kind, msg):
            mi = Gtk.MenuItem(label=label)
            mi.connect("activate", lambda _i, f=fn: f())
            menu.append(mi)
        if kind == "more":
            sn = Gtk.MenuItem(label="Reporter")
            sn.set_submenu(self.build_snooze_menu(lambda ts: self.snooze_msgs([msg], ts)))
            menu.append(sn)
            mv = Gtk.MenuItem(label="Déplacer vers un dossier")
            mv.set_submenu(self.build_move_menu([msg]))
            menu.append(mv)
        menu.show_all()
        return menu

    def _on_swipe(self, row, action):
        sel = [r.msg for r in self.listbox.get_selected_rows()] if (self.select_mode and row.is_selected()) else []
        msgs = sel if row.msg.id in {m.id for m in sel} else [row.msg]
        self.run_action(action, self._expand_threads(msgs))

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
            self.block_sender(self.cache.get(m.id) or m)

    def _flag_remote(self, m, seen=None, flagged=None):
        self._flag_remote_many([m], seen, flagged)

    def _flag_remote_many(self, msgs, seen=None, flagged=None):
        by = {}
        for m in msgs:
            by.setdefault(m.account, []).append(m)
        for aid, lst in by.items():
            try:
                be = self.backend(aid)
            except Exception:
                continue
            if not be.demo:
                kw = {k: v for k, v in (("seen", seen), ("flagged", flagged)) if v is not None}
                op_ids = self.op_enqueue("flags", lst, **kw)
                self.run_bg(lambda ids=op_ids: self.op_run([o for o in self.cache.ops_pending() if o["id"] in ids]),
                            lambda res, err: self._set_offline(res[2]) if res else None)

    def set_unread(self, msgs, unread, reload=True):
        ids = [m.id for m in msgs]
        self.cache.update_many(ids, unread=unread)
        for m in msgs:
            m.unread = unread
            row = self.rows.get(m.id)
            if row is not None:
                row.msg.unread = unread
                row.refresh()
        self._flag_remote_many(msgs, seen=not unread)
        self.update_counts()
        if reload and self.view == "unread" and not unread:
            self.remove_rows(ids, select_next=False)

    def set_flag(self, msgs, field, value):
        ids = [m.id for m in msgs]
        self.cache.update_many(ids, **{field: value})
        for m in msgs:
            setattr(m, field, value)
            row = self.rows.get(m.id)
            if row is not None:
                setattr(row.msg, field, value)
                row.refresh()
        if field == "starred":
            self._flag_remote_many(msgs, flagged=value)
        if field == "pinned":
            self.listbox.invalidate_sort()
            self.listbox.invalidate_headers()
        if not value and ((field == "starred" and self.view == "starred") or (field == "pinned" and self.view == "pinned")):
            self.remove_rows(ids)
        if self.reader.msg is not None and self.reader.msg.id in ids:
            setattr(self.reader.msg, field, value)
            self.reader.refresh_flags()

    def move_messages(self, msgs, dest, label=None):
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
            ids = [m.id for m in msgs]
            self.cache.delete_many(ids)
            self.remove_rows(ids)
            self.update_counts()
            op_ids = self.op_enqueue("delete", msgs)
            self.run_bg(lambda: self.op_run([o for o in self.cache.ops_pending() if o["id"] in op_ids]),
                        lambda res, err: self._set_offline(res[2]) if res else None)
            return
        ids = [m.id for m in msgs]
        prev = [(m.id, m.folder, m.snoozed_until) for m in msgs]
        self.cache.update_many(ids, folder=dest, snoozed_until=0.0)
        self.remove_rows(ids)
        self.update_counts()
        self._pending += 1
        state = {"done": False}

        def undo():
            state["done"] = True
            self._pending -= 1
            groups = {}
            for mid, f, sn in prev:
                groups.setdefault((f, sn), []).append(mid)
            for (f, sn), group in groups.items():
                self.cache.update_many(group, folder=f, snoozed_until=sn)
            self.reload_list()
            self.update_counts()

        def commit():
            if state["done"]:
                return
            state["done"] = True
            self._pending -= 1
            self._bg_move(msgs, dest)
        n = len(msgs)
        verb = label or FOLDER_VERBS.get(dest, "déplacé")
        self.toast.popup("%d message%s %s%s" % (n, "s" if n > 1 else "", verb, "s" if n > 1 and not label else ""),
                         "Annuler", undo, timeout=self.config["undo_seconds"], on_expire=commit)

    def snooze_selected(self, ts):
        self.snooze_msgs(self.selected_msgs(), ts)

    def snooze_msgs(self, msgs, ts):
        if not msgs or ts <= time.time():
            return
        ids = [m.id for m in msgs]
        prev = [(m.id, m.snoozed_until) for m in msgs]
        self.cache.update_many(ids, snoozed_until=ts)
        if self.view in ("inbox", "unread"):
            self.remove_rows(ids)
        else:
            self.reload_list()
        self.update_counts()

        def undo():
            for mid, sn in prev:
                self.cache.update(mid, snoozed_until=sn)
            self.reload_list()
            self.update_counts()
        self.toast.popup("Reporté au %s" % format_full(ts), "Annuler", undo, timeout=5)

    def mark_all_read(self):
        msgs = self.cache.query(self.view, self.account, None, True, False, self._effective_search(), limit=1000)
        if msgs:
            self.set_unread(msgs, False)

    # ---------------------------------------------------- expéditeurs : spam / blocage
    @staticmethod
    def _key(msg, domain=False):
        em = msg.sender_email.lower()
        return "@" + em.split("@")[-1] if domain else em

    def _filter_sender(self, key, kind, msg=None):
        """kind : « blocked » (corbeille) ou « spam_senders » (dossier Spam). Instantané : une transaction."""
        key = key.lower()
        if key not in self.config[kind]:
            self.config[kind].append(key)
            self.config.save()
        msgs = self.cache.by_sender(key, ("inbox", "archive"))
        if msg is not None and msg.id not in {x.id for x in msgs} and msg.folder in ("inbox", "archive"):
            msgs.append(msg)
        dest = "trash" if kind == "blocked" else "spam"
        label = ("Bloqué : " if kind == "blocked" else "En spam : ") + key
        if msgs:
            self.move_messages(msgs, dest)
        else:
            self.toast.popup(label, timeout=4)
        self.status.set_text(label)

    def spam_sender(self, msg, domain=False):
        self._filter_sender(self._key(msg, domain), "spam_senders", msg)

    def block_sender(self, msg, domain=False):
        self._filter_sender(self._key(msg, domain), "blocked", msg)
