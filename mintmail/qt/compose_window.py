"""Fenêtre de rédaction Qt : De / À / Cc / Cci / Objet, corps riche, signature, pièces jointes, envoi, envoi différé, brouillon.
La logique (signature, validation, message à envoyer, brouillon) est dans composing.py, testée sans Qt."""
import datetime
import os
import time

from PySide6.QtCore import QStringListModel, Qt
from PySide6.QtGui import QAction, QKeySequence, QTextCharFormat, QFont
from PySide6.QtWidgets import (QComboBox, QCompleter, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QMainWindow, QMenu, QMessageBox, QPushButton, QSpinBox, QTextEdit, QToolBar, QVBoxLayout, QWidget,
                               QCalendarWidget, QInputDialog)

from ..i18n import tr
from ..util import human_size
from . import composing as C
from . import sigimages as SI
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
        self.resize(800, 660)
        self.setAttribute(Qt.WA_DeleteOnClose, True)

        bar = QToolBar()
        bar.setMovable(False)
        self.addToolBar(bar)
        self.send_btn = QPushButton(tr("Envoyer"))
        self.send_btn.setDefault(True)
        self.send_btn.clicked.connect(lambda: self.do_send(0))
        later = QPushButton("▾")
        later.setToolTip(tr("Envoyer plus tard"))
        menu = QMenu(later)
        menu.addAction(tr("Dans 1 heure"), lambda: self._schedule(lambda: time.time() + 3600))
        menu.addAction(tr("Demain à 8 h"), lambda: self._schedule(lambda: C.at(1, 8)))
        menu.addAction(tr("Lundi prochain à 8 h"), lambda: self._schedule(C.next_monday))
        menu.addAction(tr("Choisir une date…"), lambda: self._schedule(None))
        later.setMenu(menu)
        bar.addWidget(self.send_btn)
        bar.addWidget(later)
        bar.addSeparator()
        bar.addAction(tr("Joindre un fichier"), self._attach)
        bar.addAction(tr("Supprimer le brouillon"), self._discard)
        bar.addSeparator()
        self._fmt_action(bar, tr("Gras"), "Ctrl+B", self._bold)
        self._fmt_action(bar, tr("Italique"), "Ctrl+I", self._italic)
        self._fmt_action(bar, tr("Souligné"), "Ctrl+U", self._underline)
        self._fmt_action(bar, tr("Liste à puces"), None, self._bullets)
        self._fmt_action(bar, tr("Insérer un lien"), "Ctrl+K", self._link)
        tpl = QPushButton(tr("Modèles"))
        tpl.setFlat(True)
        tmenu = QMenu(tpl)
        for i, t in enumerate(P.templates(self.engine.config)):
            tmenu.addAction(t["name"], lambda i=i: self._insert_template(i))
        if not P.templates(self.engine.config):
            tmenu.addAction(tr("Aucun modèle (voir Paramètres)")).setEnabled(False)
        tpl.setMenu(tmenu)
        bar.addWidget(tpl)
        self.ai_btn = QPushButton(tr("✨ IA"))
        self.ai_btn.setObjectName("chip")                          # bien visible : même pastille que « Charger les images »
        self.ai_btn.setToolTip(tr("Aide IA à l'écriture : rédiger, améliorer, corriger, traduire…") + "  (Ctrl+J)")
        self.ai_btn.setShortcut("Ctrl+J")
        aimenu = QMenu(self.ai_btn)
        for entry in P.AI_OPS:
            if entry is None:
                aimenu.addSeparator()
            else:
                aimenu.addAction(entry[0], lambda op=entry[1]: self._ai_op(op))
        self.ai_btn.setMenu(aimenu)
        bar.addWidget(self.ai_btn)

        self.from_box = QComboBox()
        for key, label in C.from_choices(self.engine.config, self.accounts):
            self.from_box.addItem(label, key)
        i = self.from_box.findData(account_id)
        self.from_box.setCurrentIndex(i if i >= 0 else 0)
        self.to, self.cc, self.bcc, self.subject = QLineEdit(to), QLineEdit(cc), QLineEdit(), QLineEdit(subject)
        contacts = [("%s <%s>" % (n, e)) if n else e for n, e in self.engine.cache.contacts()]
        for edit in (self.to, self.cc, self.bcc):
            self._complete(edit, contacts)
        self.editor = QTextEdit()
        self.editor.setAcceptRichText(True)
        self.att_list = QListWidget()
        self.att_list.setMaximumHeight(70)
        self.att_list.itemDoubleClicked.connect(self._remove_attachment)

        form = QFormLayout()
        form.addRow(tr("De"), self.from_box)
        form.addRow("À", self.to)
        self.cc_btn = QPushButton(tr("Cc / Cci"))
        self.cc_btn.setFlat(True)
        self.cc_btn.clicked.connect(self._show_cc)
        form.addRow("", self.cc_btn)
        self.cc_label, self.bcc_label = QLabel("Cc"), QLabel(tr("Cci"))
        form.addRow(self.cc_label, self.cc)
        form.addRow(self.bcc_label, self.bcc)
        form.addRow(tr("Objet"), self.subject)
        for w in (self.cc_label, self.cc, self.bcc_label, self.bcc):
            w.setVisible(bool(cc))
        if cc:
            self.cc_btn.hide()
        root = QWidget()
        lay = QVBoxLayout(root)
        lay.addLayout(form)
        lay.addWidget(self.editor, 1)
        lay.addWidget(self.att_list)
        self.setCentralWidget(root)
        self.from_box.currentIndexChanged.connect(self._from_changed)

        self.initial = C.initial_content(self.body_html, self.quote_html, self._signature(), self.raw, self.ai_text)
        self.editor.setHtml(SI.to_display(self.initial))
        self.initial = C.body_of_qt_html(self.editor.toHtml())        # forme Qt du contenu de départ : sert à savoir si l'on a écrit quelque chose
        self._refresh_atts()
        (self.subject if to else self.to).setFocus()
        self.show()

    # -- éléments
    def _fmt_action(self, bar, text, shortcut, fn):
        a = QAction(text, self)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        a.triggered.connect(lambda _c=False: fn())
        bar.addAction(a)

    def _complete(self, edit, contacts):
        comp = QCompleter(QStringListModel(contacts), edit)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        comp.setFilterMode(Qt.MatchContains)
        edit.setCompleter(comp)

    def _show_cc(self):
        for w in (self.cc_label, self.cc, self.bcc_label, self.bcc):
            w.show()
        self.cc_btn.hide()

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

    def _link(self):
        url, ok = QInputDialog.getText(self, tr("Insérer un lien"), "URL")
        url = (url or "").strip()
        if ok and url.lower().startswith(("http://", "https://", "mailto:")):          # jamais javascript: ni file:
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
        self.att_list.clear()
        for p in self.attachments:
            size = human_size(os.path.getsize(p)) if os.path.exists(p) else ""
            self.att_list.addItem("📎 %s  %s" % (os.path.basename(p), size))
        self.att_list.setVisible(bool(self.attachments))

    def _remove_attachment(self, item):
        r = self.att_list.row(item)
        if 0 <= r < len(self.attachments):
            del self.attachments[r]
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
