import html
import re
import threading

import gi
from .i18n import tr
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, GObject, Gio, GLib, Pango

WebKit2 = None
for _v in ("4.1", "4.0"):
    try:
        gi.require_version("WebKit2", _v)
        from gi.repository import WebKit2
        break
    except (ValueError, ImportError):
        WebKit2 = None
HAS_WEBKIT = WebKit2 is not None

from .util import (attachment_kind, attachment_risk, save_attachments, format_full, human_size, has_remote_content, block_remote_content,
                   text_to_html, split_addresses)
from .widgets import Avatar, icon, icon_button

QUICK_REPLIES = [tr("Merci !"), tr("OK, bien reçu 👍"), tr("Je regarde ça et je reviens vers vous."), tr("Parfait, à bientôt.")]


def open_uri(widget, uri):
    """Ouvre un lien : http, https et mailto SEULEMENT (voir htmlsafe.safe_to_open). Retourne False si refusé."""
    from .htmlsafe import safe_to_open
    from .log import log
    clean = safe_to_open(uri)
    if clean is None:
        log("Lien refusé (schéma non autorisé) : %s" % (uri or "")[:120])
        return False
    try:
        Gtk.show_uri_on_window(widget.get_toplevel() if widget else None, clean, Gdk.CURRENT_TIME)
    except Exception:
        try:
            Gio.AppInfo.launch_default_for_uri(clean, None)
        except Exception:
            return False
    return True


def harden_settings(s, javascript):
    """Réglages WebKit minimaux : pas de plugins, stockage, médias, fenêtres, audit de liens (ping), WebGL, inspecteur…"""
    s.set_enable_javascript(javascript)
    for name in ("set_enable_hyperlink_auditing", "set_enable_plugins", "set_enable_java", "set_enable_webgl", "set_enable_media_stream",
                 "set_enable_mediasource", "set_enable_webaudio", "set_enable_html5_local_storage", "set_enable_html5_database",
                 "set_enable_offline_web_application_cache", "set_enable_page_cache", "set_javascript_can_open_windows_automatically",
                 "set_allow_modal_dialogs", "set_enable_dns_prefetching", "set_allow_file_access_from_file_urls",
                 "set_allow_universal_access_from_file_urls", "set_enable_site_specific_quirks", "set_enable_developer_extras",
                 "set_enable_write_console_messages_to_stdout"):
        fn = getattr(s, name, None)
        if fn:
            try:
                fn(False)
            except Exception:
                pass


def new_webview(javascript):
    """Vue WebKit durcie, avec un contexte éphémère (aucun cookie ni cache conservé)."""
    s = WebKit2.Settings()
    harden_settings(s, javascript)
    try:
        return WebKit2.WebView(web_context=WebKit2.WebContext.new_ephemeral(), settings=s)
    except Exception:
        return WebKit2.WebView.new_with_settings(s)


def navigation_policy(owner, decision, dtype):
    """Seul notre propre chargement (about:blank) est autorisé ; un clic ouvre le lien dans le navigateur (si autorisé) ; tout
    le reste (redirection, formulaire, cadre, nouvelle fenêtre) est refusé."""
    if dtype == WebKit2.PolicyDecisionType.NAVIGATION_ACTION:
        nav = decision.get_navigation_action()
        uri = nav.get_request().get_uri() or ""
        if uri == "about:blank" or uri.startswith("about:blank#"):
            return False
        if nav.get_navigation_type() == WebKit2.NavigationType.LINK_CLICKED:
            open_uri(owner, uri)
        decision.ignore()
        return True
    if dtype == WebKit2.PolicyDecisionType.NEW_WINDOW_ACTION:
        decision.ignore()
        return True
    return False


PLAIN_FONT = {"aurora": "system-ui,sans-serif", "papier": "Georgia,'DejaVu Serif',serif", "terminal": "'DejaVu Sans Mono',monospace"}


def wrap_html(msg, load_images, dark, style="aurora"):
    body = msg.html
    if body:
        from .htmlsafe import reader_csp, sanitize
        body = sanitize(body, keep_style=True, allow_remote_images=load_images)    # liste blanche + CSP : voir htmlsafe.py
        return ('<html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="' + reader_csp(load_images) + '">'
                '<meta name="viewport" content="width=device-width">'
                '<style>html{background:#fff;color:#111}body{margin:0;padding:18px 22px;'
                'font-family:system-ui,Arial,sans-serif;font-size:14px;word-wrap:break-word}'
                'img{max-width:100%%;height:auto}table{max-width:100%%;}pre{white-space:pre-wrap}'
                'blockquote{border-left:3px solid #ccc;margin-left:0;padding-left:12px;color:#555}'
                '</style></head><body>%s</body></html>' % body)
    bg, fg = ("#1f2229", "#e8eaed") if dark else ("#ffffff", "#1f2328")
    return ('<html><head><meta charset="utf-8"><style>html{background:%s;color:%s}body{margin:0;'
            'padding:18px 22px;font-family:%s;font-size:14px;line-height:1.6}'
            'a{color:#3b82f6}</style></head><body>%s</body></html>'
            % (bg, fg, PLAIN_FONT.get(style, PLAIN_FONT["aurora"]), text_to_html(msg.text or "")))


class BodyView(Gtk.Box):
    """Affiche le corps d'un message (WebKit si disponible, sinon texte brut)."""
    def __init__(self):
        super().__init__()
        self.web = None
        if HAS_WEBKIT:
            self.web = new_webview(False)          # JavaScript désactivé pour le courrier reçu
            self.web.connect("decide-policy", self._policy)
            self.pack_start(self.web, True, True, 0)
        else:
            sw = Gtk.ScrolledWindow()
            self.tv = Gtk.TextView()
            self.tv.set_editable(False)
            self.tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
            self.tv.set_left_margin(20)
            self.tv.set_right_margin(20)
            self.tv.set_top_margin(14)
            sw.add(self.tv)
            self.pack_start(sw, True, True, 0)

    def _policy(self, web, decision, dtype):
        return navigation_policy(self, decision, dtype)

    def show_message(self, msg, load_images, dark, style="aurora"):
        if self.web:
            self.web.load_html(wrap_html(msg, load_images, dark, style), "about:blank")
        else:
            self.tv.get_buffer().set_text(msg.text or "")

    def set_zoom(self, z):
        if self.web:
            self.web.set_zoom_level(z)

    def clear(self):
        if self.web:
            self.web.load_html("", "about:blank")
        else:
            self.tv.get_buffer().set_text("")


class Reader(Gtk.Stack):
    __gsignals__ = {
        "action": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "quick-reply": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "ai-action": (GObject.SignalFlags.RUN_FIRST, None, (str, str)),   # (action, charge utile)
        "open-message": (GObject.SignalFlags.RUN_FIRST, None, (str,)),    # identifiant d'un message de la conversation
    }

    def __init__(self, snooze_menu_factory):
        super().__init__()
        self.msg, self.dark, self.load_images = None, False, False
        self.secondary, self.zoom, self._wide = [], 1.0, True
        self.ai_enabled, self._ai_hidden, self.style = False, False, "aurora"
        self._snooze_factory = snooze_menu_factory
        self.get_style_context().add_class("mm-reader")

        # -- vide
        empty = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        empty.set_valign(Gtk.Align.CENTER)
        img = icon("mail-read-symbolic", Gtk.IconSize.DIALOG)
        img.set_pixel_size(72)
        img.get_style_context().add_class("empty-state")
        self.empty_label = Gtk.Label(label=tr("Sélectionnez un message pour le lire"))
        self.empty_label.get_style_context().add_class("empty-state")
        empty.pack_start(img, False, False, 0)
        empty.pack_start(self.empty_label, False, False, 0)
        self.add_named(empty, "empty")

        # -- sélection multiple
        multi = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        multi.set_valign(Gtk.Align.CENTER)
        self.multi_label = Gtk.Label()
        self.multi_label.get_style_context().add_class("subject-big")
        multi.pack_start(self.multi_label, False, False, 0)
        hint = Gtk.Label(label=tr("Utilisez la barre d'actions pour archiver, supprimer ou marquer ces messages."))
        hint.get_style_context().add_class("dim")
        multi.pack_start(hint, False, False, 0)
        self.add_named(multi, "multi")

        # -- message
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        tb = Gtk.Box(spacing=4)
        tb.get_style_context().add_class("mm-toolbar")
        self.back_btn = icon_button("go-previous-symbolic", tr("Retour à la liste"), relief=False)
        self.back_btn.connect("clicked", lambda *_: self.emit("action", "back"))
        self.back_btn.set_no_show_all(True)
        tb.pack_start(self.back_btn, False, False, 0)
        for name, tip, act in (("mail-reply-sender-symbolic", tr("Répondre (R)"), "reply"),
                               ("mail-reply-all-symbolic", tr("Répondre à tous (A)"), "reply_all"),
                               ("mail-forward-symbolic", tr("Transférer (F)"), "forward")):
            b = icon_button(name, tip, relief=False)
            b.connect("clicked", lambda _b, a=act: self.emit("action", a))
            if act != "reply":
                self.secondary.append(b)
            tb.pack_start(b, False, False, 0)
        # Bouton IA NVIDIA
        self.ai_reply_btn = Gtk.Button(label=tr("✨ Répondre"))
        self.ai_reply_btn.set_tooltip_text(tr("Rédiger une réponse avec l'IA"))
        self.ai_reply_btn.get_style_context().add_class("ai-btn")
        self.ai_reply_btn.connect("clicked", lambda *_: self.emit("ai-action", "reply_ai", ""))
        self.ai_reply_btn.set_no_show_all(True)
        tb.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 6)
        tb.pack_start(self.ai_reply_btn, False, False, 0)
        tb.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 6)
        for name, tip, act in (("folder-symbolic", tr("Archiver (E)"), "archive"),
                               ("user-trash-symbolic", tr("Supprimer (#)"), "trash")):
            b = icon_button(name, tip, relief=False)
            b.connect("clicked", lambda _b, a=act: self.emit("action", a))
            tb.pack_start(b, False, False, 0)
        self.spam_btn = Gtk.Button(label=tr("Spam ▾"))
        self.spam_btn.set_tooltip_text(tr("Spam : ce message, l'expéditeur ou tout le domaine"))
        self.spam_btn.get_style_context().add_class("pill")
        self.spam_btn.connect("clicked", lambda *_: self.emit("action", "menu_spam"))
        self.block_btn = Gtk.Button(label=tr("Bloquer ▾"))
        self.block_btn.set_tooltip_text(tr("Bloquer l'adresse ou tout le domaine"))
        self.block_btn.get_style_context().add_class("pill")
        self.block_btn.connect("clicked", lambda *_: self.emit("action", "menu_block"))
        self.notspam_btn = Gtk.Button(label=tr("✔ Pas du spam"))
        self.notspam_btn.set_tooltip_text(tr("Ce n'est pas du spam : remet ce message et ceux du même expéditeur en boîte de réception"))
        self.notspam_btn.get_style_context().add_class("pill")
        self.notspam_btn.get_style_context().add_class("suggested-action")
        self.notspam_btn.connect("clicked", lambda *_: self.emit("action", "not_spam"))
        self.notspam_btn.set_no_show_all(True)                  # visible seulement pour un message du dossier Spam
        tb.pack_start(self.notspam_btn, False, False, 2)
        tb.pack_start(self.spam_btn, False, False, 2)
        tb.pack_start(self.block_btn, False, False, 2)
        self.move_btn = icon_button("folder-open-symbolic", tr("Déplacer vers un dossier (V)"), relief=False)
        self.move_btn.connect("clicked", lambda *_: self.emit("action", "move_menu"))
        tb.pack_start(self.move_btn, False, False, 0)
        self.snooze_btn = Gtk.MenuButton()
        self.snooze_btn.set_image(icon("alarm-symbolic", Gtk.IconSize.LARGE_TOOLBAR))
        self.snooze_btn.set_tooltip_text(tr("Reporter"))
        self.snooze_btn.set_relief(Gtk.ReliefStyle.NONE)
        self.snooze_btn.set_popup(self._snooze_factory(None))
        tb.pack_start(self.snooze_btn, False, False, 0)
        self.star_btn = icon_button("non-starred-symbolic", tr("Favori (S)"), relief=False)
        self.star_btn.connect("clicked", lambda *_: self.emit("action", "star"))
        self.pin_btn = icon_button("view-pin-symbolic", tr("Épingler (P)"), relief=False)
        self.pin_btn.connect("clicked", lambda *_: self.emit("action", "pin"))
        tb.pack_start(self.star_btn, False, False, 0)
        tb.pack_start(self.pin_btn, False, False, 0)
        self.secondary += [self.star_btn, self.pin_btn]
        more = Gtk.MenuButton()
        more.set_image(icon("view-more-symbolic", Gtk.IconSize.LARGE_TOOLBAR))
        more.set_relief(Gtk.ReliefStyle.NONE)
        menu = Gtk.Menu()
        for entry in ((tr("Répondre à tous"), "reply_all"), (tr("Transférer"), "forward"), (tr("Favori"), "star"),
                      (tr("Épingler"), "pin"), None,
                      (tr("Marquer comme non lu (U)"), "unread"), (tr("Afficher les images distantes"), "images"), None,
                      (tr("✔ Ce n'est pas du spam"), "not_spam"), (tr("✔ Ce n'est pas du spam (tout son domaine)"), "not_spam_domain"),
                      (tr("Signaler comme spam (!)"), "spam"), (tr("Mettre l'expéditeur en spam"), "spam_sender"),
                      (tr("Mettre son domaine en spam"), "spam_domain"),
                      (tr("Bloquer l'expéditeur"), "block"), (tr("Bloquer son domaine"), "block_domain"),
                      (tr("Débloquer l'expéditeur"), "unblock"), None,
                      (tr("Voir tous ses messages"), "from_sender"), (tr("Copier son adresse"), "copy_addr"),
                      (tr("Me rappeler si pas de réponse — 3 jours"), "followup_3"),
                      (tr("Me rappeler si pas de réponse — 7 jours"), "followup_7"), None,
                      (tr("Texte plus grand"), "zoom_in"), (tr("Texte plus petit"), "zoom_out"),
                      (tr("Taille normale"), "zoom_reset")):
            if entry is None:
                menu.append(Gtk.SeparatorMenuItem())
                continue
            label, act = entry
            it = Gtk.MenuItem(label=label)
            it.connect("activate", lambda _i, a=act: self._menu_action(a))
            menu.append(it)
        menu.show_all()
        more.set_popup(menu)
        tb.pack_end(more, False, False, 0)
        tsw = Gtk.ScrolledWindow()
        tsw.set_policy(Gtk.PolicyType.EXTERNAL, Gtk.PolicyType.NEVER)
        tsw.add(tb)
        page.pack_start(tsw, False, False, 0)

        head = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        head.get_style_context().add_class("mm-reader-head")
        head.set_border_width(16)
        self.subject = Gtk.Label(xalign=0)
        self.subject.set_line_wrap(True)
        self.subject.set_selectable(True)
        self.subject.get_style_context().add_class("subject-big")
        head.pack_start(self.subject, False, False, 0)
        who = Gtk.Box(spacing=12)
        self.avatar_box = Gtk.Box()
        who.pack_start(self.avatar_box, False, False, 0)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.from_lbl = Gtk.Label(xalign=0)
        self.from_lbl.set_selectable(True)
        self.from_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        self.to_lbl = Gtk.Label(xalign=0)
        self.to_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        self.to_lbl.get_style_context().add_class("dim")
        col.pack_start(self.from_lbl, False, False, 0)
        col.pack_start(self.to_lbl, False, False, 0)
        who.pack_start(col, True, True, 0)
        self.date_lbl = Gtk.Label(xalign=1)
        self.date_lbl.get_style_context().add_class("dim")
        who.pack_end(self.date_lbl, False, False, 0)
        head.pack_start(who, False, False, 0)
        self.att_flow = Gtk.FlowBox()
        self.att_flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self.att_flow.set_max_children_per_line(4)
        head.pack_start(self.att_flow, False, False, 0)
        page.pack_start(head, False, False, 0)
        self.thread_exp = Gtk.Expander(label=tr("Conversation"))
        self.thread_exp.set_margin_start(16)
        self.thread_exp.set_margin_end(16)
        self.thread_list = Gtk.ListBox()
        self.thread_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.thread_list.connect("row-activated", lambda lb, row: self.emit("open-message", row.mid))
        self.thread_exp.add(self.thread_list)
        self.thread_exp.set_no_show_all(True)
        page.pack_start(self.thread_exp, False, False, 0)
        self.invite_box = Gtk.Box(spacing=8)
        self.invite_box.get_style_context().add_class("invite-box")
        self.invite_box.set_margin_start(16)
        self.invite_box.set_margin_end(16)
        self.invite_lbl = Gtk.Label(xalign=0)
        self.invite_lbl.set_line_wrap(True)
        self.invite_box.pack_start(self.invite_lbl, True, True, 0)
        self.invite_btns = []
        for label, act in ((tr("Accepter"), "invite_accept"), (tr("Peut-être"), "invite_tentative"), (tr("Refuser"), "invite_decline"),
                           (tr("Ajouter à l'agenda"), "invite_add")):
            b = Gtk.Button(label=label)
            b.get_style_context().add_class("pill")
            b.connect("clicked", lambda _b, a=act: self.emit("action", a))
            self.invite_btns.append((act, b))
            self.invite_box.pack_end(b, False, False, 0)
        self.invite_box.set_no_show_all(True)
        page.pack_start(self.invite_box, False, False, 0)
        page.pack_start(self._build_ai_card(), False, False, 0)

        self.banner = Gtk.Box(spacing=10)
        self.banner.get_style_context().add_class("banner")
        self.banner_lbl = Gtk.Label(label=tr("Images distantes bloquées (vie privée)."))
        self.banner_lbl.set_line_wrap(True)
        self.banner.pack_start(self.banner_lbl, True, True, 0)
        b_img = Gtk.Button(label=tr("Afficher"))
        b_img.connect("clicked", lambda *_: self.emit("action", "images"))
        self.banner.pack_end(b_img, False, False, 0)
        self.unsub_btn = Gtk.Button(label=tr("Désabonner"))
        self.unsub_btn.connect("clicked", self._unsub)
        self.banner.pack_end(self.unsub_btn, False, False, 0)
        self.banner.set_no_show_all(True)
        page.pack_start(self.banner, False, False, 0)

        self.body = BodyView()
        page.pack_start(self.body, True, True, 0)

        qr = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        qr.set_border_width(10)
        qr.get_style_context().add_class("quick-reply")
        chips = Gtk.Box(spacing=6)
        for t in QUICK_REPLIES:
            b = Gtk.Button(label=t)
            b.get_style_context().add_class("pill")
            b.connect("clicked", lambda _b, tx=t: self.emit("quick-reply", tx))
            chips.pack_start(b, False, False, 0)
        csw = Gtk.ScrolledWindow()
        csw.set_policy(Gtk.PolicyType.EXTERNAL, Gtk.PolicyType.NEVER)
        csw.add(chips)
        row = Gtk.Box(spacing=6)
        self.quick = Gtk.Entry()
        self.quick.set_placeholder_text(tr("Réponse rapide…"))
        self.quick.connect("activate", self._send_quick)
        send = icon_button("mail-send-symbolic", tr("Envoyer la réponse"))
        send.connect("clicked", self._send_quick)
        self.quick_ai = Gtk.Button(label="✨")
        self.quick_ai.set_tooltip_text(tr("Développer ce texte en réponse complète avec l'IA"))
        self.quick_ai.get_style_context().add_class("pill")
        self.quick_ai.set_no_show_all(True)
        self.quick_ai.connect("clicked", lambda *_: self.quick.get_text().strip() and
                              self.emit("ai-action", "quick_expand", self.quick.get_text().strip()))
        row.pack_start(self.quick, True, True, 0)
        row.pack_start(self.quick_ai, False, False, 0)
        row.pack_start(send, False, False, 0)
        qr.pack_start(row, False, False, 0)
        page.pack_start(qr, False, False, 0)
        self.add_named(page, "message")
        self.connect("size-allocate", self._on_alloc)
        self.show_all()
        self.ai_reply_btn.set_visible(self.ai_enabled)
        self.ai_card.hide()
        self.back_btn.hide()
        self.banner.hide()
        self.thread_exp.hide()
        self.invite_box.hide()
        self.set_visible_child_name("empty")

    # -- adaptation à la largeur disponible
    def _on_alloc(self, w, alloc):
        wide = alloc.width >= 560
        if wide != self._wide:
            self._wide = wide
            for b in self.secondary:
                b.set_visible(wide)

    # -- carte « Résumé » : lecture seule, sans barre d'options (les actions IA sont dans le clic droit et la palette)
    def _build_ai_card(self):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        card.get_style_context().add_class("ai-card")
        head = Gtk.Box(spacing=8)
        self.ai_title = Gtk.Label(xalign=0, label=tr("✨ RÉSUMÉ"))
        self.ai_title.get_style_context().add_class("ai-title")
        self.ai_spinner = Gtk.Spinner()
        head.pack_start(self.ai_title, False, False, 0)
        head.pack_start(self.ai_spinner, False, False, 0)
        card.pack_start(head, False, False, 0)
        self.ai_summary = Gtk.Label(xalign=0)
        self.ai_summary.set_line_wrap(True)
        self.ai_summary.set_selectable(True)
        self.ai_summary.get_style_context().add_class("ai-text")
        card.pack_start(self.ai_summary, False, False, 0)
        self.ai_points = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        card.pack_start(self.ai_points, False, False, 0)
        self.ai_warn = Gtk.Label(xalign=0)
        self.ai_warn.set_line_wrap(True)
        self.ai_warn.get_style_context().add_class("ai-warn")
        card.pack_start(self.ai_warn, False, False, 0)
        self.ai_answer = Gtk.Label(xalign=0)
        self.ai_answer.set_line_wrap(True)
        self.ai_answer.set_selectable(True)
        self.ai_answer.get_style_context().add_class("ai-text")
        card.pack_start(self.ai_answer, False, False, 0)
        self.ai_sug = Gtk.Box(spacing=6)                       # suggestions d'action (Spam : « ce n'est pas du spam », rangement)
        self.ai_sug_lbl = Gtk.Label(xalign=0)
        self.ai_sug_lbl.set_line_wrap(True)
        self.ai_sug_lbl.get_style_context().add_class("ai-text")
        self.ai_sug_btns = Gtk.FlowBox()
        self.ai_sug_btns.set_selection_mode(Gtk.SelectionMode.NONE)
        self.ai_sug_btns.set_max_children_per_line(3)
        sug_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        sug_col.pack_start(self.ai_sug_lbl, False, False, 0)
        sug_col.pack_start(self.ai_sug_btns, False, False, 0)
        self.ai_sug.pack_start(sug_col, True, True, 0)
        card.pack_start(self.ai_sug, False, False, 0)
        card.show_all()
        self.ai_sug.hide()                 # tous les enfants sont visibles ; seul le conteneur est affiché / masqué
        self.ai_warn.hide()
        self.ai_answer.hide()
        card.hide()
        self.ai_card = card
        return card

    def _ai_reset(self):
        for ch in self.ai_points.get_children():
            self.ai_points.remove(ch)
        self.ai_warn.set_text("")
        self.ai_warn.hide()
        self.ai_answer.set_text("")
        self.ai_answer.hide()
        self.ai_title.set_text(tr("✨ RÉSUMÉ"))
        for ch in self.ai_sug_btns.get_children():
            self.ai_sug_btns.remove(ch)
        self.ai_sug.hide()

    def ai_spam_suggestion(self, res):
        """Dans le dossier Spam, l'IA juge le message légitime : propose « Ce n'est pas du spam » (et un dossier de rangement)."""
        m = self.msg
        if m is None or m.folder != "spam" or res.get("suspicious") or res.get("local") or res.get("error"):
            return
        self.ai_sug_lbl.set_text(tr("✨ Ce message semble légitime : il n'a probablement pas sa place dans le Spam."))
        btns = [(tr("✔ Ce n'est pas du spam"), "not_spam", "")]
        folder = res.get("folder") or ""
        if folder:
            btns.append((tr("✔ Pas du spam, ranger dans « %s »") % folder, "not_spam_file", folder))
        for label, act, payload in btns:
            b = Gtk.Button(label=label)
            b.get_style_context().add_class("pill")
            b.connect("clicked", lambda _b, a=act, p=payload: self.emit("ai-action", a, p))
            self.ai_sug_btns.add(b)
        self.ai_sug_btns.show_all()
        self.ai_sug.show_all()

    def _ai_show_card(self):
        self.ai_warn.set_visible(bool(self.ai_warn.get_text()))
        self.ai_answer.set_visible(bool(self.ai_answer.get_text()))
        self.ai_card.show()

    def ai_loading(self):
        self._ai_reset()
        self.ai_summary.set_text(tr("Lecture du message…"))
        self.ai_spinner.start()
        self._ai_show_card()

    def ai_idle(self):
        """Analyse automatique désactivée : pas de carte (le menu clic droit propose « Résumer / analyser »)."""
        self._ai_reset()
        self.ai_spinner.stop()
        self.ai_card.hide()

    def ai_working(self, text):
        self.ai_spinner.start()
        self.ai_answer.set_text(text)
        self._ai_show_card()

    def ai_text(self, title, text):
        self.ai_spinner.stop()
        self.ai_answer.set_markup("<b>%s</b>\n%s" % (GLib.markup_escape_text(title), GLib.markup_escape_text(text)))
        self._ai_show_card()

    def ai_show(self, res, cta=False, error=""):
        """Résumé (IA ou local) : phrase de synthèse, points clés, tâches, alerte d'hameçonnage. Rien d'autre."""
        self._ai_reset()
        self.ai_spinner.stop()
        prio = {3: " · URGENT", 1: tr(" · peu important")}.get(res.get("priority"), "")
        self.ai_title.set_text(tr("✨ RÉSUMÉ%s%s") % (" (local)" if res.get("local") else "", prio))
        self.ai_summary.set_text(res.get("summary") or "")
        for mark, items in (("•  ", res.get("points", [])), ("☐  ", res.get("tasks", []))):
            for t in items:
                l = Gtk.Label(xalign=0, label=mark + t)
                l.set_line_wrap(True)
                l.show()
                self.ai_points.pack_start(l, False, False, 0)
        if res.get("suspicious"):
            self.ai_warn.set_text(tr("⚠ Message suspect (hameçonnage possible)%s. Ne cliquez sur aucun lien.") % (
                " : " + res["why"] if res.get("why") else ""))
        if error:
            self.ai_answer.set_text(tr("IA indisponible : %s") % error)
        self.ai_spam_suggestion(res)
        self._ai_show_card()

    def is_open(self):
        return self.get_visible_child_name() == "message"

    def refresh_flags(self):
        if self.msg is not None:
            self.star_btn.set_image(icon("starred-symbolic" if self.msg.starred else "non-starred-symbolic",
                                         Gtk.IconSize.LARGE_TOOLBAR))

    def _menu_action(self, act):
        if act.startswith("zoom"):
            self.zoom = 1.0 if act == "zoom_reset" else max(0.5, min(2.5, self.zoom + (0.1 if act == "zoom_in" else -0.1)))
            self.body.set_zoom(self.zoom)
        else:
            self.emit("action", act)

    def apply_zoom(self):
        self.body.set_zoom(self.zoom)

    # -- API
    def set_narrow(self, narrow):
        self.back_btn.set_visible(narrow)

    def show_empty(self, text=tr("Sélectionnez un message pour le lire")):
        self.msg = None
        self.empty_label.set_text(text)
        self.set_visible_child_name("empty")
        self.body.clear()

    def show_multi(self, n):
        self.msg = None
        self.multi_label.set_text(tr("%d messages sélectionnés") % n)
        self.set_visible_child_name("multi")

    def show_message(self, msg, load_images=None):
        self.msg = msg
        self.notspam_btn.set_visible(msg.folder == "spam")
        if load_images is not None:
            self.load_images = load_images
        self.subject.set_text(msg.subject)
        for ch in self.avatar_box.get_children():
            self.avatar_box.remove(ch)
        self.avatar_box.pack_start(Avatar(msg.sender_name, msg.sender_email, 44), False, False, 0)
        self.avatar_box.show_all()
        self.from_lbl.set_markup("<b>%s</b>  <span alpha='60%%'>&lt;%s&gt;</span>" % (
            html.escape(msg.sender_name or msg.sender_email), html.escape(msg.sender_email)))
        self.to_lbl.set_text("À : " + (msg.to or "—") + ("   Cc : " + msg.cc if msg.cc else ""))
        self.date_lbl.set_text(format_full(msg.date))
        self.star_btn.set_image(icon("starred-symbolic" if msg.starred else "non-starred-symbolic",
                                     Gtk.IconSize.LARGE_TOOLBAR))
        for ch in self.att_flow.get_children():
            self.att_flow.remove(ch)
        for a in msg.attachments:
            self.att_flow.add(self._att_chip(a))
        if len(msg.attachments) > 1:
            allb = Gtk.Button(label=tr("⬇ Tout enregistrer (%s)") % human_size(sum(a["size"] for a in msg.attachments)))
            allb.get_style_context().add_class("pill")
            allb.connect("clicked", self._save_all_att, list(msg.attachments))
            self.att_flow.add(allb)
        self.att_flow.show_all()
        self._show_invite(msg)
        remote = bool(msg.html) and has_remote_content(msg.html) and not self.load_images
        self.banner_lbl.set_visible(remote)
        for ch in self.banner.get_children():
            if isinstance(ch, Gtk.Button) and ch is not self.unsub_btn:
                ch.set_visible(remote)
        self.unsub_btn.set_visible(bool(msg.unsubscribe))
        self.banner.set_visible(remote or bool(msg.unsubscribe))
        self.ai_reply_btn.set_visible(self.ai_enabled)
        self.quick_ai.set_visible(self.ai_enabled)
        self.body.show_message(msg, self.load_images, self.dark, self.style)
        self.quick.set_text("")
        self.set_visible_child_name("message")

    def _send_quick(self, *_):
        t = self.quick.get_text().strip()
        if t and self.msg:
            self.emit("quick-reply", t)
            self.quick.set_text("")

    def _unsub(self, *_):
        if self.msg:
            self.emit("action", "unsubscribe")

    def _unsub_legacy(self, *_):
        if not self.msg:
            return
        m = re.search(r"<(https?://[^>]+)>", self.msg.unsubscribe or "")
        if not m:
            m = re.search(r"<(mailto:[^>]+)>", self.msg.unsubscribe or "")
        uri = m.group(1) if m else None
        if uri:
            open_uri(self, uri)

    # ------------------------------------------------------------ conversation
    def show_thread(self, members, current_id):
        """Liste des autres messages de la conversation (cliquables) ; masquée s'il n'y en a pas."""
        for ch in self.thread_list.get_children():
            self.thread_list.remove(ch)
        others = [m for m in members if m.id != current_id]
        self.thread_exp.set_visible(bool(others))
        if not others:
            return
        self.thread_exp.set_label(tr("Conversation · %d autre%s message%s") % (len(others), "s" if len(others) > 1 else "", "s" if len(others) > 1 else ""))
        for m in reversed(others):
            row = Gtk.ListBoxRow()
            row.mid = m.id
            box = Gtk.Box(spacing=10)
            box.get_style_context().add_class("thread-row")
            who = Gtk.Label(label=m.display_sender, xalign=0)
            who.set_width_chars(18)
            who.set_max_width_chars(18)
            who.set_ellipsize(Pango.EllipsizeMode.END)
            snip = Gtk.Label(label=m.snippet or m.subject, xalign=0)
            snip.set_ellipsize(Pango.EllipsizeMode.END)
            snip.get_style_context().add_class("dim")
            when = Gtk.Label(label=format_full(m.date), xalign=1)
            when.get_style_context().add_class("dim")
            box.pack_start(who, False, False, 0)
            box.pack_start(snip, True, True, 0)
            box.pack_end(when, False, False, 0)
            row.add(box)
            self.thread_list.add(row)
        self.thread_list.show_all()
        self.thread_exp.show()

    # ---------------------------------------------------------------- invitation
    def _show_invite(self, msg):
        inv = getattr(msg, "invite", None) or {}
        if not inv:
            self.invite_box.hide()
            return
        method = inv.get("method", "PUBLISH")
        when = (inv.get("start") or "").replace("T", " à ")
        text = "📅 <b>%s</b>\n%s%s" % (html.escape(inv.get("title") or tr("Événement")), html.escape(when),
                                       (" · " + html.escape(inv["location"])) if inv.get("location") else "")
        if method == "CANCEL":
            text += tr("\n<i>Cet événement a été annulé par l'organisateur.</i>")
        elif method == "REPLY":
            text += tr("\n<i>Réponse à une invitation.</i>")
        self._invite_base = text
        self.invite_lbl.set_markup(text)
        can_reply = method == "REQUEST" and bool(inv.get("organizer"))
        for act, b in self.invite_btns:
            b.set_visible(can_reply if act != "invite_add" else method in ("REQUEST", "PUBLISH"))
        self.invite_box.show()

    def set_invite_note(self, note):
        """Ligne ajoutée sous l'invitation (conflit d'agenda, créneau libre)."""
        base = getattr(self, "_invite_base", "")
        self.invite_lbl.set_markup(base + (("\n" + html.escape(note)) if note else ""))

    # ----------------------------------------------------------- pièces jointes
    def _att_chip(self, a):
        """Pastille de pièce jointe : miniature (images), nom, taille ; clic = aperçu / ouverture, clic droit = menu,
        glisser-déposer vers le gestionnaire de fichiers."""
        b = Gtk.Button()
        box = Gtk.Box(spacing=8)
        kind = attachment_kind(a)
        thumb = None
        if kind == "image":
            try:
                from gi.repository import GdkPixbuf
                thumb = Gtk.Image.new_from_pixbuf(GdkPixbuf.Pixbuf.new_from_file_at_size(a["path"], 44, 44))
            except Exception:
                thumb = None
        if thumb is None:
            name = {"image": "image-x-generic-symbolic", "text": "text-x-generic-symbolic", "pdf": "x-office-document-symbolic",
                    "archive": "package-x-generic-symbolic"}.get(kind, "mail-attachment-symbolic")
            thumb = icon(name)
        box.pack_start(thumb, False, False, 0)
        lab = Gtk.Label(label="%s\n%s" % (a["filename"], human_size(a["size"])), xalign=0)
        lab.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        lab.set_max_width_chars(28)
        box.pack_start(lab, False, False, 0)
        b.add(box)
        b.get_style_context().add_class("chip")
        b.set_tooltip_text(tr("Cliquer pour ouvrir · clic droit : enregistrer, copier le chemin · glisser vers un dossier"))
        b.connect("clicked", lambda *_: self._open_att(a))
        b.connect("button-press-event", lambda w, ev: self._att_menu(w, ev, a) if ev.button == 3 else False)
        b.drag_source_set(Gdk.ModifierType.BUTTON1_MASK, [Gtk.TargetEntry.new("text/uri-list", 0, 0)], Gdk.DragAction.COPY)
        b.connect("drag-data-get", lambda w, ctx, data, info, t: data.set_uris([Gio.File.new_for_path(a["path"]).get_uri()]))
        return b

    def _att_menu(self, w, ev, a):
        menu = Gtk.Menu()
        for label, fn in ((tr("Ouvrir"), lambda: self._open_att(a, preview=False)), (tr("Aperçu"), lambda: self._open_att(a, preview=True)),
                          (tr("Enregistrer sous…"), lambda: self._save_att(None, a)),
                          (tr("Copier le chemin"), lambda: Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(a["path"], -1))):
            mi = Gtk.MenuItem(label=label)
            mi.connect("activate", lambda _i, f=fn: f())
            menu.append(mi)
        menu.show_all()
        menu.popup_at_pointer(ev)
        return True

    def _open_att(self, a, preview=True):
        """Aperçu intégré (images, texte) ou ouverture avec l'application par défaut — sauf fichiers exécutables / scripts
        (enregistrement seulement) et fichiers à risque (confirmation)."""
        risk = attachment_risk(a)
        if risk == "block":
            self._warn_dialog(tr("Fichier potentiellement dangereux"), tr("« %s » est un programme ou un script : MintMail ne l'ouvre pas. "
                              "Si vous êtes certain de sa provenance, enregistrez-le (clic droit → Enregistrer sous…) et vérifiez-le avant "
                              "de l'exécuter.") % a["filename"], ok_label=None)
            return
        if risk == "warn" and not self._warn_dialog(tr("Ouvrir ce fichier ?"), tr("« %s » peut contenir des macros ou du code actif. "
                                                    "Ouvrez-le seulement si vous attendiez ce fichier.") % a["filename"], ok_label=tr("Ouvrir quand même")):
            return
        kind = attachment_kind(a)
        if preview and kind in ("image", "text") and a.get("size", 0) <= 15_000_000:
            self._preview(a, kind)
        else:
            try:
                Gio.AppInfo.launch_default_for_uri(Gio.File.new_for_path(a["path"]).get_uri(), None)
            except Exception:
                pass

    def _warn_dialog(self, title, text, ok_label=None):
        d = Gtk.MessageDialog(transient_for=self.get_toplevel(), modal=True, message_type=Gtk.MessageType.WARNING, text=title, secondary_text=text)
        d.add_button(tr("Annuler") if ok_label else tr("Fermer"), Gtk.ResponseType.CANCEL)
        if ok_label:
            d.add_button(ok_label, Gtk.ResponseType.OK)
        ok = d.run() == Gtk.ResponseType.OK
        d.destroy()
        return ok

    def _preview(self, a, kind):
        dlg = Gtk.Dialog(title=a["filename"], transient_for=self.get_toplevel(), modal=False)
        dlg.set_default_size(820, 620)
        area = dlg.get_content_area()
        sw = Gtk.ScrolledWindow()
        sw.set_hexpand(True)
        sw.set_vexpand(True)
        try:
            if kind == "image":
                from gi.repository import GdkPixbuf
                sw.add(Gtk.Image.new_from_pixbuf(GdkPixbuf.Pixbuf.new_from_file_at_size(a["path"], 1600, 1600)))
            else:
                with open(a["path"], "rb") as f:
                    txt = f.read(200_000).decode("utf-8", "replace")
                tv = Gtk.TextView()
                tv.set_editable(False)
                tv.set_monospace(True)
                tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
                tv.get_buffer().set_text(txt)
                sw.add(tv)
        except Exception:
            sw.add(Gtk.Label(label=tr("Aperçu impossible : ouvrez le fichier avec « Ouvrir ».")))
        area.pack_start(sw, True, True, 0)
        dlg.add_button(tr("Ouvrir avec…"), 1)
        dlg.add_button(tr("Fermer"), Gtk.ResponseType.CLOSE)
        dlg.connect("response", lambda d, r: (self._open_att(a, preview=False) if r == 1 else None, d.destroy() if r != 1 else None))
        dlg.show_all()

    def _save_all_att(self, _b, atts):
        dlg = Gtk.FileChooserDialog(title=tr("Enregistrer toutes les pièces jointes dans…"), parent=self.get_toplevel(),
                                    action=Gtk.FileChooserAction.SELECT_FOLDER)
        dlg.add_buttons(tr("Annuler"), Gtk.ResponseType.CANCEL, tr("Enregistrer ici"), Gtk.ResponseType.OK)
        if dlg.run() == Gtk.ResponseType.OK:
            done = save_attachments(atts, dlg.get_filename())
            self.emit("ai-action", "toast", tr("%d fichier(s) enregistré(s) dans %s") % (len(done), dlg.get_filename()))
        dlg.destroy()

    def _save_att(self, _b, att):
        dlg = Gtk.FileChooserDialog(title=tr("Enregistrer la pièce jointe"), parent=self.get_toplevel(),
                                    action=Gtk.FileChooserAction.SAVE)
        dlg.add_buttons(tr("Annuler"), Gtk.ResponseType.CANCEL, tr("Enregistrer"), Gtk.ResponseType.OK)
        dlg.set_current_name(att["filename"])
        dlg.set_do_overwrite_confirmation(True)
        if dlg.run() == Gtk.ResponseType.OK:
            try:
                with open(att["path"], "rb") as f, open(dlg.get_filename(), "wb") as g:
                    g.write(f.read())
            except OSError:
                pass
        dlg.destroy()