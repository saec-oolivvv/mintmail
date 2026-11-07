import datetime
import html
import json
import os
import re
import time
import uuid

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib

from .models import Message, Outgoing
from .reader import WebKit2, HAS_WEBKIT, open_uri
from .util import html_to_text, sanitize_html, text_to_html, split_addresses, normalize_subject, format_full, human_size
from .widgets import icon, icon_button

EDITOR_TPL = """<html><head><meta charset="utf-8"><style>
html{background:#fff;color:#111}body{margin:0;font-family:system-ui,Arial,sans-serif;font-size:14px}
#ed{outline:none;padding:16px 20px;min-height:80vh;line-height:1.5}
blockquote{border-left:3px solid #ccc;margin:8px 0;padding-left:12px;color:#555}
</style></head><body><div id="ed" contenteditable="true">@@CONTENT@@</div>
<script>var e=document.getElementById('ed');e.focus();var r=document.createRange();
r.setStart(e,0);r.collapse(true);var s=window.getSelection();s.removeAllRanges();s.addRange(r);</script>
</body></html>"""


class Editor(Gtk.Box):
    """Éditeur riche (WebKit contenteditable) avec repli texte brut."""
    def __init__(self):
        super().__init__()
        self.web = self.tv = None
        if HAS_WEBKIT:
            s = WebKit2.Settings()
            s.set_enable_javascript(True)
            self.web = WebKit2.WebView.new_with_settings(s)
            self.web.connect("decide-policy", self._policy)
            self.pack_start(self.web, True, True, 0)
        else:
            sw = Gtk.ScrolledWindow()
            self.tv = Gtk.TextView()
            self.tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
            sw.add(self.tv)
            self.pack_start(sw, True, True, 0)

    def _policy(self, web, decision, dtype):
        if dtype == WebKit2.PolicyDecisionType.NAVIGATION_ACTION:
            nav = decision.get_navigation_action()
            if nav.get_navigation_type() == WebKit2.NavigationType.LINK_CLICKED:
                open_uri(self, nav.get_request().get_uri())
                decision.ignore()
                return True
        return False

    def set_html(self, content):
        if self.web:
            self.web.load_html(EDITOR_TPL.replace("@@CONTENT@@", content), "about:blank")
        else:
            from .util import html_to_text
            self.tv.get_buffer().set_text(html_to_text(content))

    def exec(self, cmd, value=None):
        if self.web:
            js = "document.getElementById('ed').focus();document.execCommand(%s,false,%s);" % (
                json.dumps(cmd), json.dumps(value))
            self.web.run_javascript(js, None, None, None)

    def get_html(self, cb):
        if self.web:
            def done(web, res, _d=None):
                try:
                    cb(web.run_javascript_finish(res).get_js_value().to_string() or "")
                except Exception:
                    cb("")
            self.web.run_javascript("document.getElementById('ed').innerHTML", None, done, None)
        else:
            b = self.tv.get_buffer()
            cb(text_to_html(b.get_text(b.get_start_iter(), b.get_end_iter(), False)))


class ComposeWindow(Gtk.Window):
    def __init__(self, win, accounts, account_id=None, to="", cc="", subject="", body_html="",
                 quote_html="", in_reply_to="", references="", attachments=None, draft_id=None, raw=False,
                 ai_suggested_text=""):
        super().__init__(title="Nouveau message")
        self.win, self.accounts = win, accounts
        self.in_reply_to, self.references = in_reply_to, references
        self.draft_id, self.attachments = draft_id, list(attachments or [])
        self.body_html, self.quote_html = body_html, quote_html
        self.initial_body, self.sent, self.raw = None, False, raw
        self.ai_suggested_text = ai_suggested_text
        self.set_default_size(780, 640)
        self.set_transient_for(win)

        hb = Gtk.HeaderBar()
        hb.set_show_close_button(True)
        hb.set_title("Nouveau message")
        self.set_titlebar(hb)
        self.send_btn = Gtk.Button(label="Envoyer")
        self.send_btn.get_style_context().add_class("suggested-action")
        self.send_btn.connect("clicked", lambda *_: self.do_send(0))
        later = Gtk.MenuButton()
        later.set_image(icon("pan-down-symbolic"))
        later.set_tooltip_text("Envoyer plus tard")
        menu = Gtk.Menu()
        for label, fn in (("Dans 1 heure", lambda: time.time() + 3600),
                          ("Demain à 8 h", lambda: self._at(1, 8)),
                          ("Lundi prochain à 8 h", self._next_monday),
                          ("Choisir une date…", None)):
            it = Gtk.MenuItem(label=label)
            it.connect("activate", lambda _i, f=fn: self._schedule(f))
            menu.append(it)
        menu.show_all()
        later.set_popup(menu)
        box = Gtk.Box()
        box.get_style_context().add_class("linked")
        box.pack_start(self.send_btn, False, False, 0)
        box.pack_start(later, False, False, 0)
        hb.pack_end(box)
        att = icon_button("mail-attachment-symbolic", "Joindre un fichier")
        att.connect("clicked", self._attach)
        hb.pack_end(att)
        disc = icon_button("user-trash-symbolic", "Supprimer le brouillon")
        disc.connect("clicked", lambda *_: self._discard())
        hb.pack_start(disc)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        root.get_style_context().add_class("mm-root")
        grid = Gtk.Grid(column_spacing=8, row_spacing=4)
        grid.set_border_width(10)
        self.from_combo = Gtk.ComboBoxText()
        for a in accounts:
            self.from_combo.append(a["id"], "%s <%s>" % (a.get("name") or a["email"], a["email"]))
        self.from_combo.set_active_id(account_id if account_id in [a["id"] for a in accounts] else accounts[0]["id"])
        self.from_combo.connect("changed", self._account_changed)
        self.to = Gtk.Entry(text=to)
        self.cc = Gtk.Entry(text=cc)
        self.bcc = Gtk.Entry()
        self.subject = Gtk.Entry(text=subject)
        self._attach_completion(self.to)
        self._attach_completion(self.cc)
        self._attach_completion(self.bcc)
        self.cc_btn = Gtk.Button(label="Cc / Cci")
        self.cc_btn.set_relief(Gtk.ReliefStyle.NONE)
        self.cc_btn.connect("clicked", self._show_cc)
        rows = [("De", self.from_combo, None), ("À", self.to, self.cc_btn), ("Cc", self.cc, None),
                ("Cci", self.bcc, None), ("Objet", self.subject, None)]
        self.row_widgets = {}
        for i, (lab, w, extra) in enumerate(rows):
            l = Gtk.Label(label=lab, xalign=1)
            l.get_style_context().add_class("dim")
            w.set_hexpand(True)
            grid.attach(l, 0, i, 1, 1)
            grid.attach(w, 1, i, 1, 1)
            if extra:
                grid.attach(extra, 2, i, 1, 1)
            self.row_widgets[lab] = (l, w)
        root.pack_start(grid, False, False, 0)

        fmt = Gtk.Box(spacing=2)
        fmt.get_style_context().add_class("mm-toolbar")
        for name, tip, cmd, val in (
                ("format-text-bold-symbolic", "Gras", "bold", None),
                ("format-text-italic-symbolic", "Italique", "italic", None),
                ("format-text-underline-symbolic", "Souligné", "underline", None),
                ("format-text-strikethrough-symbolic", "Barré", "strikeThrough", None),
                ("view-list-symbolic", "Liste à puces", "insertUnorderedList", None),
                ("view-list-ordered-symbolic", "Liste numérotée", "insertOrderedList", None),
                ("format-indent-more-symbolic", "Citation", "formatBlock", "blockquote"),
                ("edit-clear-all-symbolic", "Effacer la mise en forme", "removeFormat", None)):
            b = icon_button(name, tip, relief=False)
            b.connect("clicked", lambda _b, c=cmd, v=val: self.editor.exec(c, v))
            fmt.pack_start(b, False, False, 0)
        link = icon_button("insert-link-symbolic", "Insérer un lien", relief=False)
        link.connect("clicked", self._link)
        fmt.pack_start(link, False, False, 0)
        tpl = Gtk.MenuButton(label="Modèles")
        tpl.set_relief(Gtk.ReliefStyle.NONE)
        tmenu = Gtk.Menu()
        for t in self.win.config["templates"]:
            it = Gtk.MenuItem(label=t["name"])
            it.connect("activate", lambda _i, h=t["html"]: self.editor.exec("insertHTML", sanitize_html(h)))
            tmenu.append(it)
        if not self.win.config["templates"]:
            empty = Gtk.MenuItem(label="Aucun modèle (voir Paramètres)")
            empty.set_sensitive(False)
            tmenu.append(empty)
        tmenu.show_all()
        tpl.set_popup(tmenu)
        fmt.pack_start(tpl, False, False, 8)
        # Bouton IA pour aide à la rédaction
        self.ai_btn = icon_button("computer-symbolic", "Aide IA", relief=False)
        self.ai_btn.set_no_show_all(True)
        self.ai_btn.connect("clicked", self._ai_assist)
        fmt.pack_start(self.ai_btn, False, False, 8)
        fsw = Gtk.ScrolledWindow()
        fsw.set_policy(Gtk.PolicyType.EXTERNAL, Gtk.PolicyType.NEVER)
        fsw.add(fmt)
        root.pack_start(fsw, False, False, 0)

        self.editor = Editor()
        root.pack_start(self.editor, True, True, 0)
        # Bouton IA - visible si IA activée
        ai_visible = bool(self.win._get_ai_service())
        self.ai_btn.set_visible(ai_visible)
        self.att_flow = Gtk.FlowBox()
        self.att_flow.set_selection_mode(Gtk.SelectionMode.NONE)
        root.pack_start(self.att_flow, False, False, 4)
        self.add(root)
        self.connect("delete-event", self._on_delete)
        self.show_all()
        for lab in ("Cc", "Cci"):
            if lab == "Cc" and cc:
                continue
            for w in self.row_widgets[lab]:
                w.hide()
        self._render_body()
        self._refresh_atts()
        (self.subject if to else self.to).grab_focus()

    # -- corps + signature
    def _signature(self):
        acc = self._account()
        sig = acc.get("signature_html", "") if acc else ""
        return '<div id="sig">-- <br>%s</div>' % sig if sig.strip() else ""

    def _render_body(self):
        if self.raw:
            content = self.body_html
        else:
            ai = ("<div><br></div><div id='ai-text'>%s</div>" % text_to_html(self.ai_suggested_text)
                  if self.ai_suggested_text else "")
            content = self.body_html + ai + "<div><br></div>" + self._signature() + self.quote_html
        self.initial_body = content
        self.editor.set_html(content)

    def _account(self):
        aid = self.from_combo.get_active_id()
        return next((a for a in self.accounts if a["id"] == aid), None)

    def _account_changed(self, *_):
        if self.initial_body is not None:
            def swap(cur):
                old = re.sub(r'<div id="sig">.*?</div>', "", cur, count=1, flags=re.S)
                new = self._signature()
                if '<div id="sig">' in cur:
                    cur = re.sub(r'<div id="sig">.*?</div>', lambda m: new, cur, count=1, flags=re.S)
                else:
                    cur = old + new
                self.editor.set_html(cur)
            self.editor.get_html(swap)

    # -- destinataires
    def _attach_completion(self, entry):
        store = Gtk.ListStore(str)
        for name, e in self.win.cache.contacts():
            store.append([("%s <%s>" % (name, e)) if name else e])
        comp = Gtk.EntryCompletion()
        comp.set_model(store)
        comp.set_text_column(0)
        comp.set_inline_completion(False)

        def match(c, key, it):
            tail = entry.get_text().split(",")[-1].strip().lower()
            return len(tail) >= 2 and tail in store[it][0].lower()

        def selected(c, model, it):
            parts = [p.strip() for p in entry.get_text().split(",")[:-1]]
            parts.append(model[it][0])
            entry.set_text(", ".join(parts) + ", ")
            entry.set_position(-1)
            return True
        comp.set_match_func(match)
        comp.connect("match-selected", selected)
        entry.set_completion(comp)

    def _show_cc(self, btn):
        for lab in ("Cc", "Cci"):
            for w in self.row_widgets[lab]:
                w.show()
        btn.hide()

    # -- assistance IA
    def _ai_assist(self, *_):
        """Demande à l'IA un projet de message (texte brut, inséré échappé)."""
        ai = self.win._get_ai_service()
        if not ai:
            self.win.toast.popup("IA non configurée : Paramètres → IA NVIDIA.", timeout=4)
            return
        self.ai_btn.set_sensitive(False)
        subject, to = self.subject.get_text().strip(), self.to.get_text().strip()
        quoted = html_to_text(self.quote_html) if self.quote_html else ""

        def work():
            return ai.assist_draft(subject, to, quoted)

        def done(text, err):
            self.ai_btn.set_sensitive(True)
            if err:
                self.win.toast.popup("Erreur IA : %s" % str(err)[:90], timeout=6)
            elif text:
                self.editor.exec("insertHTML", text_to_html(text) + "<br><br>")
                self.win.toast.popup("Texte IA inséré. Relisez avant d'envoyer.", timeout=4)
            else:
                self.win.toast.popup("L'IA n'a pas généré de texte.", timeout=3)
        self.win.run_bg(work, done)

    # -- pièces jointes
    def _attach(self, *_):
        dlg = Gtk.FileChooserDialog(title="Joindre des fichiers", parent=self,
                                    action=Gtk.FileChooserAction.OPEN)
        dlg.add_buttons("Annuler", Gtk.ResponseType.CANCEL, "Joindre", Gtk.ResponseType.OK)
        dlg.set_select_multiple(True)
        if dlg.run() == Gtk.ResponseType.OK:
            self.attachments += [f for f in dlg.get_filenames() if f not in self.attachments]
            self._refresh_atts()
        dlg.destroy()

    def _refresh_atts(self):
        for ch in self.att_flow.get_children():
            self.att_flow.remove(ch)
        for p in self.attachments:
            box = Gtk.Box(spacing=6)
            box.get_style_context().add_class("chip")
            try:
                size = human_size(os.path.getsize(p))
            except OSError:
                size = "?"
            box.pack_start(Gtk.Label(label="%s (%s)" % (os.path.basename(p), size)), False, False, 0)
            rm = Gtk.Button()
            rm.set_image(icon("window-close-symbolic"))
            rm.set_relief(Gtk.ReliefStyle.NONE)
            rm.connect("clicked", lambda _b, path=p: (self.attachments.remove(path), self._refresh_atts()))
            box.pack_start(rm, False, False, 0)
            self.att_flow.add(box)
        self.att_flow.show_all()

    def _link(self, *_):
        dlg = Gtk.Dialog(title="Insérer un lien", transient_for=self, modal=True)
        dlg.add_buttons("Annuler", Gtk.ResponseType.CANCEL, "Insérer", Gtk.ResponseType.OK)
        e = Gtk.Entry(text="https://")
        e.set_activates_default(True)
        dlg.get_content_area().pack_start(e, True, True, 12)
        dlg.set_default_response(Gtk.ResponseType.OK)
        dlg.show_all()
        if dlg.run() == Gtk.ResponseType.OK and e.get_text().strip():
            self.editor.exec("createLink", e.get_text().strip())
        dlg.destroy()

    # -- envoi
    @staticmethod
    def _at(days, hour):
        d = datetime.datetime.now() + datetime.timedelta(days=days)
        return d.replace(hour=hour, minute=0, second=0, microsecond=0).timestamp()

    def _next_monday(self):
        d = datetime.datetime.now()
        return self._at((7 - d.weekday()) % 7 or 7, 8)

    def _schedule(self, fn):
        if fn is None:
            dlg = Gtk.Dialog(title="Envoyer plus tard", transient_for=self, modal=True)
            dlg.add_buttons("Annuler", Gtk.ResponseType.CANCEL, "Planifier", Gtk.ResponseType.OK)
            cal = Gtk.Calendar()
            hour = Gtk.SpinButton.new_with_range(0, 23, 1)
            hour.set_value(9)
            box = dlg.get_content_area()
            box.set_spacing(8)
            box.pack_start(cal, False, False, 0)
            row = Gtk.Box(spacing=6)
            row.pack_start(Gtk.Label(label="Heure :"), False, False, 0)
            row.pack_start(hour, False, False, 0)
            box.pack_start(row, False, False, 0)
            dlg.show_all()
            ok = dlg.run() == Gtk.ResponseType.OK
            y, m, d = cal.get_date()
            h = int(hour.get_value())
            dlg.destroy()
            if not ok:
                return
            ts = datetime.datetime(y, m + 1, d, h).timestamp()
        else:
            ts = fn()
        self.do_send(max(0, ts - time.time()), scheduled=True)

    def _valid(self):
        for e in (self.to, self.cc, self.bcc):
            for a in split_addresses(e.get_text()):
                if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", a):
                    return False
        return bool(split_addresses(self.to.get_text()))

    def do_send(self, delay, scheduled=False):
        if not self._valid():
            d = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.WARNING,
                                  buttons=Gtk.ButtonsType.OK,
                                  text="Adresse de destinataire manquante ou invalide.")
            d.run()
            d.destroy()
            self.to.grab_focus()
            return
        if not self.subject.get_text().strip():
            d = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
                                  text="Envoyer ce message sans objet ?")
            d.add_buttons("Annuler", Gtk.ResponseType.CANCEL, "Envoyer", Gtk.ResponseType.OK)
            ok = d.run() == Gtk.ResponseType.OK
            d.destroy()
            if not ok:
                return

        def go(body):
            out = Outgoing(account=self.from_combo.get_active_id(), to=self.to.get_text().strip(),
                           cc=self.cc.get_text().strip(), bcc=self.bcc.get_text().strip(),
                           subject=self.subject.get_text().strip() or "(Sans objet)", html=body,
                           attachments=list(self.attachments), in_reply_to=self.in_reply_to,
                           references=self.references)
            self.sent = True
            if self.draft_id:
                self.win.cache.delete(self.draft_id)
            self.win.queue_send(out, delay, scheduled)
            self.destroy()
        self.editor.get_html(go)

    # -- fermeture / brouillon
    def _discard(self):
        self.sent = True
        if self.draft_id:
            self.win.cache.delete(self.draft_id)
            self.win.reload_list()
        self.destroy()

    def _on_delete(self, *_):
        if self.sent:
            return False

        def check(body):
            dirty = (self.to.get_text().strip() or self.subject.get_text().strip()
                     or self.attachments or body.strip() != (self.initial_body or "").strip())
            if not dirty:
                self.sent = True
                self.destroy()
                return
            d = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
                                  text="Enregistrer ce message comme brouillon ?")
            d.add_buttons("Supprimer", Gtk.ResponseType.REJECT, "Continuer l'écriture", Gtk.ResponseType.CANCEL,
                          "Enregistrer", Gtk.ResponseType.OK)
            r = d.run()
            d.destroy()
            if r == Gtk.ResponseType.OK:
                self._save_draft(body)
                self.sent = True
                self.destroy()
            elif r == Gtk.ResponseType.REJECT:
                self._discard()
        self.editor.get_html(check)
        return True

    def _save_draft(self, body):
        did = self.draft_id or "draft-%s" % uuid.uuid4().hex[:10]
        acc = self._account()
        from .util import html_to_text
        text = html_to_text(body)
        self.win.cache.upsert(Message(
            id=did, account=acc["id"], folder="drafts", uid=0, sender_name=acc.get("name", ""),
            sender_email=acc["email"], to=self.to.get_text(), cc=self.cc.get_text(),
            subject=self.subject.get_text() or "(Sans objet)", date=time.time(), snippet=text[:150],
            text=text, html=body, unread=False, attachments=[
                {"filename": os.path.basename(p), "path": p, "size": os.path.getsize(p) if os.path.exists(p) else 0,
                 "mime": ""} for p in self.attachments],
            message_id=self.in_reply_to, references=self.references))
        self.win.reload_list()
        self.win.update_counts()
