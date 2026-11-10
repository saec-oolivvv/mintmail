import datetime
import html
import json
import os
import re
import time
import uuid

import gi
from .i18n import tr
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, Gio, Gtk, GLib

from .models import Message, Outgoing
from .htmlsafe import clean_url, editor_csp
from .reader import WebKit2, HAS_WEBKIT, navigation_policy, new_webview, open_uri
from .util import html_to_text, sanitize_html, text_to_html, split_addresses, normalize_subject, format_full, human_size
from .widgets import icon, icon_button

EDITOR_TPL = """<html><head><meta charset="utf-8">@@CSPMETA@@<style>
html{background:#fff;color:#111}body{margin:0;font-family:system-ui,Arial,sans-serif;font-size:14px}
#ed{outline:none;padding:16px 20px;min-height:80vh;line-height:1.5}
blockquote{border-left:3px solid #ccc;margin:8px 0;padding-left:12px;color:#555}
</style></head><body><div id="ed" contenteditable="true">@@CONTENT@@</div>
<script>var e=document.getElementById('ed');e.focus();var r=document.createRange();
r.setStart(e,0);r.collapse(true);var s=window.getSelection();s.removeAllRanges();s.addRange(r);</script>
</body></html>"""

# Politique de sécurité de contenu : l'éditeur n'exécute QUE son propre script (empreinte SHA-256), aucun réseau, aucun formulaire.
# Secours en cas de problème d'affichage : lancer « MINTMAIL_EDITOR_CSP=0 mintmail » et nous le signaler.
_ED_SCRIPT = re.search(r"<script>(.*?)</script>", EDITOR_TPL, re.S).group(1)
EDITOR_TPL = EDITOR_TPL.replace("@@CSPMETA@@", "" if os.environ.get("MINTMAIL_EDITOR_CSP") == "0" else
                                '<meta http-equiv="Content-Security-Policy" content="%s">' % editor_csp(_ED_SCRIPT))


class Editor(Gtk.Box):
    """Éditeur riche (WebKit contenteditable) avec repli texte brut."""
    def __init__(self):
        super().__init__()
        self.web = self.tv = None
        if HAS_WEBKIT:
            self.web = new_webview(True)           # JavaScript nécessaire à l'édition, borné par la CSP ci-dessus
            self.web.connect("decide-policy", self._policy)
            self.pack_start(self.web, True, True, 0)
        else:
            sw = Gtk.ScrolledWindow()
            self.tv = Gtk.TextView()
            self.tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
            sw.add(self.tv)
            self.pack_start(sw, True, True, 0)

    def _policy(self, web, decision, dtype):
        return navigation_policy(self, decision, dtype)

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

    def get_user_text(self, cb):
        """cb(texte, est_sélection) : sélection, sinon texte écrit (hors signature et citation)."""
        if self.web:
            js = ("(function(){var s=window.getSelection();var t=(s&&s.rangeCount)?s.toString():'';"
                  "if(t&&t.trim()){return JSON.stringify({sel:true,text:t});}"
                  "var ed=document.getElementById('ed').cloneNode(true);"
                  "ed.querySelectorAll('#sig,#qt').forEach(function(n){n.remove();});"
                  "return JSON.stringify({sel:false,text:ed.innerText});})()")

            def done(web, res, _d=None):
                try:
                    obj = json.loads(web.run_javascript_finish(res).get_js_value().to_string() or "{}")
                    cb(obj.get("text", ""), bool(obj.get("sel")))
                except Exception:
                    cb("", False)
            self.web.run_javascript(js, None, done, None)
        else:
            b = self.tv.get_buffer()
            if b.get_has_selection():
                a, z = b.get_selection_bounds()
                cb(b.get_text(a, z, False), True)
            else:
                cb(b.get_text(b.get_start_iter(), b.get_end_iter(), False), False)

    def replace_user_text(self, html_text, selection):
        if self.web:
            if selection:
                self.exec("insertHTML", html_text)
            else:
                js = ("(function(h){var ed=document.getElementById('ed');var keep='';"
                      "['sig','qt'].forEach(function(id){var n=document.getElementById(id);if(n){keep+=n.outerHTML;}});"
                      "ed.innerHTML=h+'<div><br></div>'+keep;})(%s)" % json.dumps(html_text))
                self.web.run_javascript(js, None, None, None)
        else:
            from .util import html_to_text
            b = self.tv.get_buffer()
            if selection and b.get_has_selection():
                a, z = b.get_selection_bounds()
                b.delete(a, z)
                b.insert(a, html_to_text(html_text))
            else:
                b.set_text(html_to_text(html_text))

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
        super().__init__(title=tr("Nouveau message"))
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
        hb.set_decoration_layout(":minimize,maximize,close")
        hb.set_title(tr("Nouveau message"))
        self.set_titlebar(hb)
        self.send_btn = Gtk.Button(label=tr("Envoyer"))
        self.send_btn.get_style_context().add_class("suggested-action")
        self.send_btn.connect("clicked", lambda *_: self.do_send(0))
        later = Gtk.MenuButton()
        later.set_image(icon("pan-down-symbolic"))
        later.set_tooltip_text(tr("Envoyer plus tard"))
        menu = Gtk.Menu()
        for label, fn in ((tr("Dans 1 heure"), lambda: time.time() + 3600),
                          (tr("Demain à 8 h"), lambda: self._at(1, 8)),
                          (tr("Lundi prochain à 8 h"), self._next_monday),
                          (tr("Choisir une date…"), None)):
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
        att = icon_button("mail-attachment-symbolic", tr("Joindre un fichier"))
        att.connect("clicked", self._attach)
        hb.pack_end(att)
        disc = icon_button("user-trash-symbolic", tr("Supprimer le brouillon"))
        disc.connect("clicked", lambda *_: self._discard())
        hb.pack_start(disc)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        root.get_style_context().add_class("mm-root")
        grid = Gtk.Grid(column_spacing=8, row_spacing=4)
        grid.set_border_width(10)
        self.from_combo = Gtk.ComboBoxText()
        for a in accounts:
            self.from_combo.append(a["id"], "%s <%s>" % (a.get("name") or a["email"], a["email"]))
            for i in win.config.get("identities", []):       # alias : même compte d'envoi, adresse et signature propres
                if i.get("account") == a["id"]:
                    self.from_combo.append("ident:" + i["id"], "%s <%s>  · alias" % (i.get("name") or i["email"], i["email"]))
        ids = [a["id"] for a in accounts] + ["ident:" + i["id"] for i in win.config.get("identities", [])]
        self.from_combo.set_active_id(account_id if account_id in ids else accounts[0]["id"])
        self.from_combo.connect("changed", self._account_changed)
        self.to = Gtk.Entry(text=to)
        self.cc = Gtk.Entry(text=cc)
        self.bcc = Gtk.Entry()
        self.subject = Gtk.Entry(text=subject)
        self.subject.set_icon_from_icon_name(Gtk.EntryIconPosition.SECONDARY, "starred-symbolic")
        self.subject.set_icon_tooltip_text(Gtk.EntryIconPosition.SECONDARY, tr("✨ Suggérer un objet"))
        self.subject.connect("icon-press", self._ai_subject_icon)
        self._attach_completion(self.to)
        self._attach_completion(self.cc)
        self._attach_completion(self.bcc)
        self.cc_btn = Gtk.Button(label=tr("Cc / Cci"))
        self.cc_btn.set_relief(Gtk.ReliefStyle.NONE)
        self.cc_btn.connect("clicked", self._show_cc)
        rows = [(tr("De"), self.from_combo, None), ("À", self.to, self.cc_btn), ("Cc", self.cc, None),
                (tr("Cci"), self.bcc, None), (tr("Objet"), self.subject, None)]
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
                ("format-text-bold-symbolic", tr("Gras"), "bold", None),
                ("format-text-italic-symbolic", tr("Italique"), "italic", None),
                ("format-text-underline-symbolic", tr("Souligné"), "underline", None),
                ("format-text-strikethrough-symbolic", tr("Barré"), "strikeThrough", None),
                ("view-list-symbolic", tr("Liste à puces"), "insertUnorderedList", None),
                ("view-list-ordered-symbolic", tr("Liste numérotée"), "insertOrderedList", None),
                ("format-indent-more-symbolic", tr("Citation"), "formatBlock", "blockquote"),
                ("edit-clear-all-symbolic", tr("Effacer la mise en forme"), "removeFormat", None)):
            b = icon_button(name, tip, relief=False)
            b.connect("clicked", lambda _b, c=cmd, v=val: self.editor.exec(c, v))
            fmt.pack_start(b, False, False, 0)
        link = icon_button("insert-link-symbolic", tr("Insérer un lien"), relief=False)
        link.connect("clicked", self._link)
        fmt.pack_start(link, False, False, 0)
        tpl = Gtk.MenuButton(label=tr("Modèles"))
        tpl.set_relief(Gtk.ReliefStyle.NONE)
        tmenu = Gtk.Menu()
        for t in self.win.config["templates"]:
            it = Gtk.MenuItem(label=t["name"])
            it.connect("activate", lambda _i, h=t["html"]: self.editor.exec("insertHTML", sanitize_html(h)))
            tmenu.append(it)
        if not self.win.config["templates"]:
            empty = Gtk.MenuItem(label=tr("Aucun modèle (voir Paramètres)"))
            empty.set_sensitive(False)
            tmenu.append(empty)
        tmenu.show_all()
        tpl.set_popup(tmenu)
        fmt.pack_start(tpl, False, False, 8)
        # Bouton IA pour aide à la rédaction
        self.ai_btn = Gtk.MenuButton(label=tr("✨ IA"))
        self.ai_btn.get_style_context().add_class("ai-btn")
        self.ai_btn.set_no_show_all(True)
        aim = Gtk.Menu()
        for entry in ((tr("Rédiger à partir d'une idée…"), "write"), None,
                      (tr("Améliorer le texte"), "improve"), (tr("Corriger l'orthographe"), "fix"),
                      (tr("Raccourcir"), "shorten"), (tr("Développer"), "expand"),
                      (tr("Ton plus formel"), "formal"), (tr("Ton plus amical"), "friendly"), None,
                      (tr("Traduire en français"), "translate:fr"), (tr("Traduire en anglais"), "translate:en"),
                      (tr("Traduire en néerlandais"), "translate:nl"), (tr("Traduire en allemand"), "translate:de"),
                      (tr("Traduire en espagnol"), "translate:es"), None,
                      (tr("Suggérer un objet"), "subject")):
            if entry is None:
                aim.append(Gtk.SeparatorMenuItem())
                continue
            it = Gtk.MenuItem(label=entry[0])
            it.connect("activate", lambda _i, op=entry[1]: self._ai_op(op))
            aim.append(it)
        aim.show_all()
        self.ai_btn.set_popup(aim)
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
        self.att_total = Gtk.Label(xalign=0)
        self.att_total.set_no_show_all(True)
        root.pack_start(self.att_total, False, False, 0)
        for target in (self, self.att_flow):      # glisser des fichiers depuis le gestionnaire de fichiers
            try:
                target.drag_dest_set(Gtk.DestDefaults.ALL, [], Gdk.DragAction.COPY)
                target.drag_dest_add_uri_targets()
                target.connect("drag-data-received", self._on_drop)
            except Exception:
                pass
        self.add(root)
        self.connect("delete-event", self._on_delete)
        self.show_all()
        for lab in ("Cc", tr("Cci")):
            if lab == "Cc" and cc:
                continue
            for w in self.row_widgets[lab]:
                w.hide()
        self._render_body()
        self._refresh_atts()
        (self.subject if to else self.to).grab_focus()

    # -- corps + signature
    def _identity(self):
        aid = self.from_combo.get_active_id() or ""
        if aid.startswith("ident:"):
            return next((i for i in self.win.config.get("identities", []) if "ident:" + i["id"] == aid), None)
        return None

    def _signature(self):
        acc, ident = self._account(), self._identity()
        sig = (ident or {}).get("signature_html") or (acc.get("signature_html", "") if acc else "")
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
        aid = self.from_combo.get_active_id() or ""
        ident = self._identity() if aid.startswith("ident:") else None
        if ident:
            aid = ident["account"]
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
        for lab in ("Cc", tr("Cci")):
            for w in self.row_widgets[lab]:
                w.show()
        btn.hide()

    # -- assistance IA
    def _ai_busy(self, busy):
        self.ai_btn.set_sensitive(not busy)
        self.ai_btn.set_label("✨ …" if busy else "✨ IA")

    def _ai_op(self, op):
        """Opérations IA du composeur : rédiger, améliorer, corriger, raccourcir, traduire, objet…"""
        eng = self.win.engine
        if not eng.enabled():
            self.win.toast.popup(tr("IA non configurée : Paramètres → IA."), timeout=4)
            self.win.show_settings("ai")
            return
        subject, to = self.subject.get_text().strip(), self.to.get_text().strip()

        def finish(text, err, apply):
            self._ai_busy(False)
            if err:
                self.win.toast.popup(tr("Erreur IA : %s") % str(err)[:90], timeout=6)
            elif text:
                apply(text)
                self.win.toast.popup(tr("✨ Fait. Relisez avant d'envoyer."), timeout=3)
            else:
                self.win.toast.popup(tr("L'IA n'a rien renvoyé."), timeout=3)

        if op == "write":
            idea = self._ask_idea()
            if not idea:
                return
            self._ai_busy(True)
            quoted = html_to_text(self.quote_html) if self.quote_html else ""

            def got(text, selection):
                self.win.run_bg(lambda: eng.write_from_prompt(idea, subject, to, quoted),
                                lambda t, e: finish(t, e, lambda x: self.editor.replace_user_text(
                                    text_to_html(x), selection) if (selection or text.strip()) else
                                    self.editor.exec("insertHTML", text_to_html(x))))
            self.editor.get_user_text(got)
            return

        def got(text, selection):
            if not text.strip():
                self._ai_busy(False)
                self.win.toast.popup(tr("Écrivez d'abord un peu de texte."), timeout=3)
                return
            if op == "subject":
                self.win.run_bg(lambda: eng.subject_for(text),
                                lambda t, e: finish(t, e, lambda x: self.subject.set_text(x)))
            else:
                self.win.run_bg(lambda: eng.rewrite(text, op),
                                lambda t, e: finish(t, e, lambda x: self.editor.replace_user_text(text_to_html(x), selection)))
        self._ai_busy(True)
        self.editor.get_user_text(got)

    def _ask_idea(self):
        d = Gtk.Dialog(title=tr("✨ Rédiger avec l'IA"), transient_for=self, modal=True)
        d.add_buttons(tr("Annuler"), Gtk.ResponseType.CANCEL, tr("Rédiger"), Gtk.ResponseType.OK)
        d.set_default_size(460, 200)
        tv = Gtk.TextView()
        tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        tv.set_left_margin(8)
        tv.set_top_margin(8)
        sw = Gtk.ScrolledWindow()
        sw.add(tv)
        box = d.get_content_area()
        box.set_spacing(8)
        box.set_border_width(12)
        box.pack_start(Gtk.Label(label=tr("Que voulez-vous dire ? (quelques mots suffisent)"), xalign=0), False, False, 0)
        box.pack_start(sw, True, True, 0)
        d.show_all()
        ok = d.run() == Gtk.ResponseType.OK
        b = tv.get_buffer()
        text = b.get_text(b.get_start_iter(), b.get_end_iter(), False).strip()
        d.destroy()
        return text if ok else ""

    def _ai_subject_icon(self, entry, pos, ev):
        self._ai_op("subject")

    # -- pièces jointes
    def _attach(self, *_):
        dlg = Gtk.FileChooserDialog(title=tr("Joindre des fichiers"), parent=self,
                                    action=Gtk.FileChooserAction.OPEN)
        dlg.add_buttons(tr("Annuler"), Gtk.ResponseType.CANCEL, tr("Joindre"), Gtk.ResponseType.OK)
        dlg.set_select_multiple(True)
        if dlg.run() == Gtk.ResponseType.OK:
            self.attachments += [f for f in dlg.get_filenames() if f not in self.attachments]
            self._refresh_atts()
        dlg.destroy()

    def _on_drop(self, widget, ctx, x, y, data, info, time_):
        paths = []
        for uri in data.get_uris() or []:
            try:
                p = Gio.File.new_for_uri(uri).get_path()
            except Exception:
                p = None
            if p and os.path.isfile(p) and p not in self.attachments:
                paths.append(p)
        if paths:
            self.attachments += paths
            self._refresh_atts()
        ctx.finish(bool(paths), False, time_)

    def _refresh_atts(self):
        total = 0
        for p in self.attachments:
            try:
                total += os.path.getsize(p)
            except OSError:
                pass
        if self.attachments:
            big = total > 20 * 1024 * 1024
            self.att_total.set_markup("<span foreground='%s'>%d fichier(s) · %s%s</span>" % (
                "#dc2626" if big else "#888888", len(self.attachments), human_size(total),
                tr(" — attention : la plupart des serveurs refusent plus de 20-25 Mo") if big else ""))
            self.att_total.show()
        else:
            self.att_total.hide()
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
        dlg = Gtk.Dialog(title=tr("Insérer un lien"), transient_for=self, modal=True)
        dlg.add_buttons(tr("Annuler"), Gtk.ResponseType.CANCEL, tr("Insérer"), Gtk.ResponseType.OK)
        e = Gtk.Entry(text="https://")
        e.set_activates_default(True)
        dlg.get_content_area().pack_start(e, True, True, 12)
        dlg.set_default_response(Gtk.ResponseType.OK)
        dlg.show_all()
        url = e.get_text().strip()
        if dlg.run() == Gtk.ResponseType.OK and url:
            if clean_url(url, "link", False):
                self.editor.exec("createLink", url)
            else:
                self.win.toast.popup(tr("Lien refusé : seuls http, https, mailto et tel sont acceptés."), timeout=5)
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
            dlg = Gtk.Dialog(title=tr("Envoyer plus tard"), transient_for=self, modal=True)
            dlg.add_buttons(tr("Annuler"), Gtk.ResponseType.CANCEL, tr("Planifier"), Gtk.ResponseType.OK)
            cal = Gtk.Calendar()
            hour = Gtk.SpinButton.new_with_range(0, 23, 1)
            hour.set_value(9)
            box = dlg.get_content_area()
            box.set_spacing(8)
            box.pack_start(cal, False, False, 0)
            row = Gtk.Box(spacing=6)
            row.pack_start(Gtk.Label(label=tr("Heure :")), False, False, 0)
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
                                  text=tr("Adresse de destinataire manquante ou invalide."))
            d.run()
            d.destroy()
            self.to.grab_focus()
            return
        if not self.subject.get_text().strip():
            d = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
                                  text=tr("Envoyer ce message sans objet ?"))
            d.add_buttons(tr("Annuler"), Gtk.ResponseType.CANCEL, tr("Envoyer"), Gtk.ResponseType.OK)
            ok = d.run() == Gtk.ResponseType.OK
            d.destroy()
            if not ok:
                return

        def go(body):
            ident = self._identity()
            out = Outgoing(account=self._account()["id"], to=self.to.get_text().strip(),
                           from_email=ident["email"] if ident else "", from_name=ident.get("name", "") if ident else "",
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
                                  text=tr("Enregistrer ce message comme brouillon ?"))
            d.add_buttons(tr("Supprimer"), Gtk.ResponseType.REJECT, tr("Continuer l'écriture"), Gtk.ResponseType.CANCEL,
                          tr("Enregistrer"), Gtk.ResponseType.OK)
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
