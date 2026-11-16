"""Fenêtre de rédaction Qt : De / À / Cc / Cci / Objet, corps riche, signature, pièces jointes, envoi, envoi différé, brouillon.
La logique (signature, validation, message à envoyer, brouillon) est dans composing.py, testée sans Qt."""
import datetime
import os
import time

from PySide6.QtCore import QStringListModel, Qt
from PySide6.QtGui import QAction, QKeySequence, QShortcut, QTextCharFormat, QFont
from PySide6.QtWidgets import (QComboBox, QCompleter, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QMainWindow, QMenu, QMessageBox, QPushButton, QScrollArea, QSpinBox, QTextEdit, QToolButton, QVBoxLayout, QWidget,
                               QCalendarWidget, QInputDialog)

from ..i18n import tr
from ..util import human_size
from .. import pgp
from . import composing as C
from . import sigimages as SI
from . import ui_fetch as F
from . import ui_icons as UI
from . import personal as P
from ..util import text_to_html


class ComposeWindow(QMainWindow):
    def __init__(self, main, account_id=None, to="", cc="", subject="", body_html="", quote_html="", in_reply_to="", references="",
                 attachments=None, draft_id=None, raw=False, ai_suggested_text=""):
        super().__init__(main)
        self.main, self.engine = main, main.engine
        self.accounts = self.engine.accounts()
        self.in_reply_to, self.references, self.draft_id = in_reply_to, references, draft_id
        self.attachments, self.body_html, self.quote_html, self.raw = list(attachments or []), body_html, quote_html, raw
        self.ai_text, self.sent, self.initial = ai_suggested_text, False, None
        self.setWindowTitle(tr("Nouveau message"))
        self.resize(860, 720)
        self.setMinimumSize(620, 480)
        self.setAttribute(Qt.WA_DeleteOnClose, True)

        th = self.main.t
        dim, accent, on = th["dim"], th["accent"], th["on"]
        self.setStyleSheet("""
            #composeroot { background: %(bg)s; }
            #composehead { background: %(card)s; border: 1px solid %(line)s; border-radius: %(rc)dpx; }
            #composehead QLineEdit, #composehead QComboBox { background: transparent; border: none; padding: 10px 4px; font-size: 14px; }
            #composehead QLineEdit:focus, #composehead QComboBox:focus { border: none; }
            #composehead QComboBox::drop-down { width: 0; border: none; }
            #composehead #subjectedit { font-weight: 600; font-size: 15px; }
            #fieldlabel { color: %(dim)s; font-size: 13px; }
            #rowsep { background: %(line)s; border: none; }
            #composefmt { background: transparent; }
            #composefmt QToolButton, #composebar QToolButton { background: transparent; border: none; border-radius: %(rs)dpx; padding: 6px; color: %(dim)s; }
            #composefmt QToolButton:hover, #composebar QToolButton:hover { background: %(hover)s; color: %(text)s; }
            #composebar QToolButton:checked { background: %(hover)s; color: %(accent)s; }
            #fmtsep { background: %(line)s; border: none; }
            #composeeditor { background: %(card)s; border: 1px solid %(line)s; border-radius: %(rc)dpx; padding: 14px 18px; font-size: 14px; }
            #composeeditor:focus { border: 1px solid %(accent)s; }
            #composebar { background: %(card)s; border: 1px solid %(line)s; border-radius: %(rc)dpx; }
            #sendbtn { background: %(accent)s; color: %(on)s; border: none; border-radius: %(rp)dpx; padding: 9px 20px; font-weight: 700; }
            #sendbtn:hover { background: %(accent)s; }
            #linkbtn { background: transparent; border: none; color: %(dim)s; padding: 4px 8px; font-size: 13px; }
            #linkbtn:hover { color: %(accent)s; }
            #attchip { background: %(hover)s; border: none; border-radius: %(rp)dpx; padding: 5px 12px; color: %(text)s; }
            #attchip:hover { background: %(line)s; }
        """ % dict(th, rc=min(th["r"], 18) + (4 if th["r"] > 8 else 0)))

        def tool(layout, icon, text, shortcut, fn, checkable=False, owner=None):
            """Bouton à icône vectorielle + info-bulle (avec raccourci) lié à une action ; retourne l'action."""
            a = QAction(self)
            a.setText(text)
            a.setIcon(UI.icon(icon, dim, accent, 18))
            a.setCheckable(checkable)
            a.setToolTip(text + ("  (%s)" % shortcut if shortcut else ""))
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
                a.setShortcutContext(Qt.WindowShortcut)
                self.addAction(a)
            a.triggered.connect(lambda _c=False: fn())
            btn = QToolButton()
            btn.setDefaultAction(a)
            btn.setIconSize(UI.icon_size(18))
            btn.setToolButtonStyle(Qt.ToolButtonIconOnly if not a.icon().isNull() else Qt.ToolButtonTextOnly)
            btn.setCursor(Qt.PointingHandCursor)
            layout.addWidget(btn)
            return a

        def vsep(layout):
            s = QFrame()
            s.setObjectName("fmtsep")
            s.setFixedSize(1, 18)
            layout.addSpacing(4)
            layout.addWidget(s)
            layout.addSpacing(4)

        self.from_box = QComboBox()
        for key, label in C.from_choices(self.engine.config, self.accounts):
            self.from_box.addItem(label, key)
        i = self.from_box.findData(account_id)
        self.from_box.setCurrentIndex(i if i >= 0 else 0)
        self.to, self.cc, self.bcc, self.subject = QLineEdit(to), QLineEdit(cc), QLineEdit(), QLineEdit(subject)
        self.subject.setObjectName("subjectedit")
        self.to.setPlaceholderText(tr("Destinataires"))
        self.subject.setPlaceholderText(tr("Objet"))
        contacts = [("%s <%s>" % (n, e)) if n else e for n, e in self.engine.cache.contacts()]
        for edit in (self.to, self.cc, self.bcc):
            self._complete(edit, contacts)
        self.editor = QTextEdit()
        self.editor.setObjectName("composeeditor")
        self.editor.setAcceptRichText(True)
        self.editor.setFrameShape(QFrame.NoFrame)

        # -- en-tête : De / À (+ Cc, Cci) / Objet, dans une seule carte à lignes séparées
        def row(label, widget, extra=()):
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(14, 0, 8, 0)
            h.setSpacing(6)
            lb = QLabel(label)
            lb.setObjectName("fieldlabel")
            lb.setFixedWidth(54)
            h.addWidget(lb)
            h.addWidget(widget, 1)
            for e in extra:
                h.addWidget(e)
            return w

        def sep():
            s = QFrame()
            s.setObjectName("rowsep")
            s.setFixedHeight(1)
            return s
        self.cc_btn, self.bcc_btn = QPushButton("Cc"), QPushButton(tr("Cci"))
        for b_ in (self.cc_btn, self.bcc_btn):
            b_.setObjectName("linkbtn")
            b_.setCursor(Qt.PointingHandCursor)
        self.cc_btn.clicked.connect(lambda: self._show_cc("cc"))
        self.bcc_btn.clicked.connect(lambda: self._show_cc("bcc"))
        head = QFrame()
        head.setObjectName("composehead")
        hl = QVBoxLayout(head)
        hl.setContentsMargins(0, 2, 0, 2)
        hl.setSpacing(0)
        hl.addWidget(row(tr("De"), self.from_box))
        hl.addWidget(sep())
        hl.addWidget(row("À", self.to, (self.cc_btn, self.bcc_btn)))
        self.cc_row, self.bcc_row = row("Cc", self.cc), row(tr("Cci"), self.bcc)
        self.cc_sep, self.bcc_sep = sep(), sep()
        for w_ in (self.cc_sep, self.cc_row, self.bcc_sep, self.bcc_row):
            hl.addWidget(w_)
            w_.setVisible(False)
        hl.addWidget(sep())
        hl.addWidget(row(tr("Objet"), self.subject))
        if cc:
            self._show_cc("cc")

        # -- barre de mise en forme (au-dessus du texte)
        fmt = QWidget()
        fmt.setObjectName("composefmt")
        fl = QHBoxLayout(fmt)
        fl.setContentsMargins(6, 0, 6, 0)
        fl.setSpacing(2)
        tool(fl, "bold", tr("Gras"), "Ctrl+B", self._bold)
        tool(fl, "italic", tr("Italique"), "Ctrl+I", self._italic)
        tool(fl, "underline", tr("Souligné"), "Ctrl+U", self._underline)
        tool(fl, "strike", tr("Barré"), None, self._strike)
        vsep(fl)
        tool(fl, "bullets", tr("Liste à puces"), None, self._bullets)
        tool(fl, "numbered", tr("Liste numérotée"), None, self._numbered)
        tool(fl, "quote", tr("Citation"), None, self._quote)
        vsep(fl)
        tool(fl, "link", tr("Insérer un lien"), "Ctrl+K", self._link)
        tool(fl, "clear", tr("Effacer la mise en forme"), None, self._clear_format)
        fl.addStretch(1)
        tpl = QPushButton(tr("Modèles"))
        tpl.setObjectName("flat")
        tpl.setIcon(UI.icon("template", dim, accent, 18))
        tpl.setCursor(Qt.PointingHandCursor)
        tmenu = QMenu(tpl)
        for i, tp in enumerate(P.templates(self.engine.config)):
            tmenu.addAction(tp["name"], lambda i=i: self._insert_template(i))
        if not P.templates(self.engine.config):
            tmenu.addAction(tr("Aucun modèle (voir Paramètres)")).setEnabled(False)
        tpl.setMenu(tmenu)
        fl.addWidget(tpl)
        self.ai_btn = QPushButton(tr("IA"))
        self.ai_btn.setObjectName("chip")                          # bien visible : même pastille que « Charger les images »
        self.ai_btn.setIcon(UI.icon("sparkles", accent, accent, 16))
        self.ai_btn.setCursor(Qt.PointingHandCursor)
        self.ai_btn.setToolTip(tr("Aide IA à l'écriture : rédiger, améliorer, corriger, traduire…") + "  (Ctrl+J)")
        self.ai_btn.setShortcut("Ctrl+J")
        aimenu = QMenu(self.ai_btn)
        for entry in P.AI_OPS:
            if entry is None:
                aimenu.addSeparator()
            else:
                aimenu.addAction(entry[0], lambda op=entry[1]: self._ai_op(op))
        self.ai_btn.setMenu(aimenu)
        fl.addWidget(self.ai_btn)

        # -- pièces jointes (pastilles) et barre d'envoi en bas
        self.att_scroll = QScrollArea()
        self.att_scroll.setWidgetResizable(True)
        self.att_scroll.setFrameShape(QFrame.NoFrame)
        self.att_scroll.setFixedHeight(44)
        self.att_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.att_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.att_box = QWidget()
        self.att_lay = QHBoxLayout(self.att_box)
        self.att_lay.setContentsMargins(2, 4, 2, 4)
        self.att_lay.setSpacing(6)
        self.att_scroll.setWidget(self.att_box)

        bottom = QFrame()
        bottom.setObjectName("composebar")
        bl = QHBoxLayout(bottom)
        bl.setContentsMargins(10, 8, 10, 8)
        bl.setSpacing(4)
        self.send_btn = QPushButton(tr("Envoyer"))
        self.send_btn.setObjectName("sendbtn")
        self.send_btn.setIcon(UI.icon("send", on, on, 16))
        self.send_btn.setDefault(True)
        self.send_btn.setCursor(Qt.PointingHandCursor)
        self.send_btn.setToolTip(tr("Envoyer") + "  (Ctrl+Entrée)")
        self.send_btn.clicked.connect(lambda: self.do_send(0))
        bl.addWidget(self.send_btn)
        later = QToolButton()
        later.setIcon(UI.icon("clock", dim, accent, 18))
        later.setIconSize(UI.icon_size(18))
        later.setToolTip(tr("Envoyer plus tard"))
        later.setPopupMode(QToolButton.InstantPopup)
        later.setCursor(Qt.PointingHandCursor)
        menu = QMenu(later)
        menu.addAction(tr("Dans 1 heure"), lambda: self._schedule(lambda: time.time() + 3600))
        menu.addAction(tr("Demain à 8 h"), lambda: self._schedule(lambda: C.at(1, 8)))
        menu.addAction(tr("Lundi prochain à 8 h"), lambda: self._schedule(C.next_monday))
        menu.addAction(tr("Choisir une date…"), lambda: self._schedule(None))
        later.setMenu(menu)
        bl.addWidget(later)
        vsep(bl)
        tool(bl, "attach", tr("Joindre un fichier"), "Ctrl+Shift+A", self._attach)
        self.pgp_sign = self.pgp_encrypt = None
        if pgp.available():                                        # gpg installé : signer / chiffrer en PGP/MIME (facultatif)
            self.pgp_sign = tool(bl, "sign", tr("Signer ce message avec votre clé OpenPGP (gpg)"), None, lambda: None, checkable=True)
            self.pgp_encrypt = tool(bl, "lock", tr("Chiffrer ce message : il faut la clé publique de chaque destinataire"), None, lambda: None, checkable=True)
        bl.addStretch(1)
        tool(bl, "trash", tr("Supprimer le brouillon"), None, self._discard)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=lambda: self.do_send(0))

        root = QWidget()
        root.setObjectName("composeroot")
        lay = QVBoxLayout(root)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)
        lay.addWidget(head)
        lay.addWidget(fmt)
        lay.addWidget(self.editor, 1)
        lay.addWidget(self.att_scroll)
        lay.addWidget(bottom)
        self.setCentralWidget(root)
        self.from_box.currentIndexChanged.connect(self._from_changed)

        self.initial = C.initial_content(self.body_html, self.quote_html, self._signature(), self.raw, self.ai_text)
        raw_initial = self.initial
        self.editor.setHtml(SI.to_display(self.initial))
        self.initial = C.body_of_qt_html(self.editor.toHtml())        # forme Qt du contenu de départ : sert à savoir si l'on a écrit quelque chose

        def images_ready():                                           # logos distants téléchargés après l'ouverture : affichés si rien n'a encore été écrit
            if C.body_of_qt_html(self.editor.toHtml()) == self.initial:
                self.editor.setHtml(SI.to_display(raw_initial))
                self.initial = C.body_of_qt_html(self.editor.toHtml())
        F.prefetch_async(raw_initial, images_ready)
        self._refresh_atts()
        (self.subject if to else self.to).setFocus()
        self.show()

    # -- éléments
    def _complete(self, edit, contacts):
        comp = QCompleter(QStringListModel(contacts), edit)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        comp.setFilterMode(Qt.MatchContains)
        edit.setCompleter(comp)

    def _show_cc(self, which="cc"):
        rows = {"cc": (self.cc_sep, self.cc_row, self.cc_btn), "bcc": (self.bcc_sep, self.bcc_row, self.bcc_btn)}[which]
        rows[0].show()
        rows[1].show()
        rows[2].hide()
        (self.cc if which == "cc" else self.bcc).setFocus()

    def _account_ident(self):
        return C.resolve_from(self.engine.config, self.accounts, self.from_box.currentData())

    def _signature(self):
        acc, ident = self._account_ident()
        return C.signature_html(acc, ident)

    def _from_changed(self, _i):
        if self.initial is not None:
            self.editor.setHtml(SI.to_display(C.swap_signature(C.body_of_qt_html(self.editor.toHtml()), self._signature())))

    # -- mise en forme
    def _merge(self, fmt):
        cur = self.editor.textCursor()
        if not cur.hasSelection():
            cur.select(cur.SelectionType.WordUnderCursor)
        cur.mergeCharFormat(fmt)
        self.editor.mergeCurrentCharFormat(fmt)

    def _bold(self):
        f = QTextCharFormat()
        f.setFontWeight(400 if self.editor.fontWeight() > 400 else 700)
        self._merge(f)

    def _italic(self):
        f = QTextCharFormat()
        f.setFontItalic(not self.editor.fontItalic())
        self._merge(f)

    def _underline(self):
        f = QTextCharFormat()
        f.setFontUnderline(not self.editor.fontUnderline())
        self._merge(f)

    def _bullets(self):
        from PySide6.QtGui import QTextListFormat
        self.editor.textCursor().createList(QTextListFormat.ListDisc)

    def _numbered(self):
        from PySide6.QtGui import QTextListFormat
        self.editor.textCursor().createList(QTextListFormat.ListDecimal)

    def _strike(self):
        f = QTextCharFormat()
        f.setFontStrikeOut(not self.editor.currentCharFormat().fontStrikeOut())
        self._merge(f)

    def _quote(self):
        """Citation : le paragraphe (ou la sélection) est mis en retrait avec un filet à gauche ; un second clic l'enlève."""
        cur = self.editor.textCursor()
        cur.beginEditBlock()
        start, end = sorted((cur.selectionStart(), cur.selectionEnd()))
        probe = self.editor.textCursor()
        probe.setPosition(start)
        on = probe.blockFormat().leftMargin() >= 20
        blk = probe
        while True:
            fmt = blk.blockFormat()
            fmt.setLeftMargin(0 if on else 24)
            blk.setBlockFormat(fmt)
            if blk.block().position() + blk.block().length() > end or not blk.movePosition(blk.MoveOperation.NextBlock):
                break
        cur.endEditBlock()

    def _clear_format(self):
        """Efface gras, italique, souligné, barré… de la sélection (ou du mot sous le curseur), sans toucher au texte."""
        cur = self.editor.textCursor()
        if not cur.hasSelection():
            cur.select(cur.SelectionType.WordUnderCursor)
        plain = QTextCharFormat()
        cur.setCharFormat(plain)
        self.editor.setCurrentCharFormat(plain)

    def _link(self):
        url, ok = QInputDialog.getText(self, tr("Insérer un lien"), "URL")
        url = (url or "").strip()
        if ok and url and not url.lower().startswith(("http://", "https://", "mailto:", "tel:")):
            self.main.status.setText(tr("Lien refusé : seuls http, https, mailto et tel sont acceptés."))
        if ok and url.lower().startswith(("http://", "https://", "mailto:", "tel:")):          # jamais javascript: ni file:
            cur = self.editor.textCursor()
            label = cur.selectedText() or url
            cur.insertHtml('<a href="%s">%s</a>' % (url.replace('"', "%22"), label.replace("<", "&lt;")))

    # -- modèles de réponse
    def _insert_template(self, i):
        self.editor.textCursor().insertHtml(P.template_html(self.engine.config, i))

    # -- aide IA à l'écriture (✨) : opère sur le texte écrit (hors signature et citation), ou sur la sélection
    def _user_range(self):
        """(début, fin) du texte écrit : avant la signature (marqueur invisible) ou, à défaut, avant la citation."""
        doc = self.editor.document()
        end = doc.characterCount() - 1
        for mark in (C.SIG_MARK, C.QUOTE_MARK):
            found = doc.find(mark)
            if not found.isNull():
                end = min(end, found.selectionStart())
        return 0, max(0, end)

    def _ai_busy(self, busy):
        self.ai_btn.setEnabled(not busy)
        self.ai_btn.setText("✨ …" if busy else tr("✨ IA"))

    def _ai_op(self, op):
        main = self.main
        from . import assistant as AS
        ai = AS.ai_engine(self.engine)
        if not ai.enabled():
            main.status.setText(tr("IA non configurée : Paramètres → IA."))
            main.show_settings(page="ai")
            return
        cur = self.editor.textCursor()
        selection = cur.hasSelection()
        start, end = (cur.selectionStart(), cur.selectionEnd()) if selection else self._user_range()
        text = ""
        idea = ""
        if op == "write":
            idea, ok = QInputDialog.getMultiLineText(self, tr("✨ Rédiger avec l'IA"), tr("Que voulez-vous dire ? (quelques mots suffisent)"))
            idea = (idea or "").strip()
            if not ok or not idea:
                return
        else:
            probe = self.editor.textCursor()
            probe.setPosition(start)
            probe.setPosition(end, probe.MoveMode.KeepAnchor)
            text = probe.selectedText().replace("\u2029", "\n").replace(C.SIG_MARK, "").replace(C.QUOTE_MARK, "").strip()
            if not text:
                main.status.setText(tr("Écrivez d'abord un peu de texte."))
                return
        subject, to = self.subject.text().strip(), self.to.text().strip()
        from ..util import html_to_text
        quoted = html_to_text(self.quote_html) if self.quote_html else ""
        self._ai_busy(True)

        def done(res, err):
            self._ai_busy(False)
            if err:
                main.status.setText(tr("Erreur IA : %s") % str(err)[:90])
                return
            target, out = res
            if not out:
                main.status.setText(tr("L'IA n'a rien renvoyé."))
                return
            if target == "subject":
                self.subject.setText(out)
            else:
                c = self.editor.textCursor()
                c.setPosition(start)
                c.setPosition(end, c.MoveMode.KeepAnchor)
                c.insertHtml(text_to_html(out))
            main.status.setText(tr("✨ Fait. Relisez avant d'envoyer."))
        main.run_bg(lambda: P.ai_run(ai, op, text, subject, to, idea, quoted), done)

    # -- pièces jointes
    def _attach(self):
        files, _ = QFileDialog.getOpenFileNames(self, tr("Joindre un fichier"))
        for p in files:
            if p not in self.attachments:
                self.attachments.append(p)
        self._refresh_atts()

    def _refresh_atts(self):
        while self.att_lay.count():
            it = self.att_lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        for i, p in enumerate(self.attachments):
            size = human_size(os.path.getsize(p)) if os.path.exists(p) else ""
            name = os.path.basename(p)
            chip = QPushButton("%s  ·  %s  ✕" % (name if len(name) <= 32 else name[:29] + "…", size) if size else "%s  ✕" % name)
            chip.setObjectName("attchip")
            chip.setIcon(UI.icon("attach", self.main.t["dim"], self.main.t["dim"], 14))
            chip.setCursor(Qt.PointingHandCursor)
            chip.setToolTip(tr("Cliquer pour retirer cette pièce jointe") + "\n" + p)
            chip.clicked.connect(lambda _c=False, i=i: self._remove_attachment(i))
            self.att_lay.addWidget(chip)
        self.att_lay.addStretch(1)
        self.att_scroll.setVisible(bool(self.attachments))

    def _remove_attachment(self, i):
        if 0 <= i < len(self.attachments):
            del self.attachments[i]
            self._refresh_atts()

    # -- envoi
    def _body(self):
        return C.body_of_qt_html(self.editor.toHtml())

    def _schedule(self, fn):
        if fn is None:
            dlg = QDialog(self)
            dlg.setWindowTitle(tr("Envoyer plus tard"))
            cal, hour = QCalendarWidget(), QSpinBox()
            hour.setRange(0, 23)
            hour.setValue(9)
            lay = QVBoxLayout(dlg)
            lay.addWidget(cal)
            row = QHBoxLayout()
            row.addWidget(QLabel(tr("Heure :")))
            row.addWidget(hour)
            lay.addLayout(row)
            bb = QDialogButtonBox()
            bb.addButton(tr("Annuler"), QDialogButtonBox.RejectRole)
            bb.addButton(tr("Planifier"), QDialogButtonBox.AcceptRole)
            bb.accepted.connect(dlg.accept)
            bb.rejected.connect(dlg.reject)
            lay.addWidget(bb)
            if dlg.exec() != QDialog.Accepted:
                return
            d = cal.selectedDate()
            ts = datetime.datetime(d.year(), d.month(), d.day(), hour.value()).timestamp()
        else:
            ts = fn()
        self.do_send(max(0, ts - time.time()), scheduled=True)

    def do_send(self, delay, scheduled=False):
        if not C.valid_recipients(self.to.text(), self.cc.text(), self.bcc.text()):
            QMessageBox.warning(self, tr("Nouveau message"), tr("Adresse de destinataire manquante ou invalide."))
            self.to.setFocus()
            return
        if not self.subject.text().strip():
            if QMessageBox.question(self, tr("Nouveau message"), tr("Envoyer ce message sans objet ?")) != QMessageBox.Yes:
                return
        acc, ident = self._account_ident()
        out = C.build_outgoing(acc, ident, self.to.text(), self.cc.text(), self.bcc.text(), self.subject.text(), self._body(), self.attachments,
                               self.in_reply_to, self.references)
        out.pgp_sign = bool(self.pgp_sign and self.pgp_sign.isChecked())
        out.pgp_encrypt = bool(self.pgp_encrypt and self.pgp_encrypt.isChecked())
        self.sent = True
        if self.draft_id:
            self.engine.cache.delete(self.draft_id)
        self.main.queue_send(out, delay, scheduled)
        self.close()

    # -- fermeture / brouillon
    def _dirty(self):
        return bool(self.to.text().strip() or self.subject.text().strip() or self.attachments or self._body().strip() != (self.initial or "").strip())

    def _discard(self):
        self.sent = True
        if self.draft_id:
            self.engine.cache.delete(self.draft_id)
            self.main.reload()
        self.close()

    def _save(self):
        acc, _ident = self._account_ident()
        C.save_draft(self.engine.cache, acc, self.draft_id, self.to.text(), self.cc.text(), self.subject.text(), self._body(), self.attachments,
                     self.in_reply_to, self.references)
        self.main.reload()

    def closeEvent(self, ev):
        if self.sent or not self._dirty():
            ev.accept()
            return
        box = QMessageBox(QMessageBox.Question, tr("Nouveau message"), tr("Enregistrer ce message comme brouillon ?"), parent=self)
        save = box.addButton(tr("Enregistrer"), QMessageBox.AcceptRole)
        drop = box.addButton(tr("Supprimer"), QMessageBox.DestructiveRole)
        keep = box.addButton(tr("Continuer l'écriture"), QMessageBox.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is save:
            self._save()
            self.sent = True
            ev.accept()
        elif clicked is drop:
            self._discard_quiet()
            ev.accept()
        else:
            ev.ignore()

    def _discard_quiet(self):
        self.sent = True
        if self.draft_id:
            self.engine.cache.delete(self.draft_id)
            self.main.reload()
