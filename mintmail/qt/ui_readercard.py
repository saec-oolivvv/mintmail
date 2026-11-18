"""Carte IA et barre « Réponse rapide » du lecteur Qt. Aucune logique : tout vient de readerai.py (testé sans Qt)."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QCheckBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

from ..i18n import tr
from . import readerai as RA


def _clear(layout):
    while layout.count():
        w = layout.takeAt(0).widget()
        if w is not None:
            w.deleteLater()


class ReaderCard(QFrame):
    """Résumé, points, tâches, alerte d'hameçonnage, suggestion « pas du spam », question et boutons d'action IA."""
    action = Signal(str, str)
    revealed = Signal()                       # la carte vient d'être affichée (la colonne qui la porte doit alors être visible)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("aicard")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 10, 16, 10)
        lay.setSpacing(4)
        top = QHBoxLayout()
        self.title = QLabel(tr("✨ RÉSUMÉ"))
        self.title.setObjectName("caption")
        top.addWidget(self.title, 1)
        for glyph, tip, act in (("↻", tr("✨ Résumer / analyser ce message"), "regen"), ("🌐", tr("Traduction"), "translate"), ("✕", "", "hide")):
            b = QPushButton(glyph)
            b.setObjectName("flat")
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, a=act: self.hide() if a == "hide" else self.action.emit(a, ""))
            top.addWidget(b)
        lay.addLayout(top)
        self.summary = self._label()
        self.points = QVBoxLayout()
        self.points.setSpacing(2)
        self.warn = self._label()
        self.warn.setObjectName("aiwarn")
        self.answer = self._label()
        self.sug = self._label()
        self.sug_btns = QVBoxLayout()
        self.cta = QPushButton(tr("Ouvrir les réglages de l'IA"))
        self.cta.setObjectName("chip")
        self.cta.clicked.connect(lambda: self.action.emit("enable_ai", ""))
        row = QHBoxLayout()
        self.ask = QLineEdit()
        self.ask.setPlaceholderText(tr("Demandez n'importe quoi à votre boîte mail…"))
        self.ask.returnPressed.connect(self._ask)
        row.addWidget(self.ask, 1)
        for w in (self.summary, self.warn, self.answer, self.sug):
            lay.addWidget(w)
        lay.insertLayout(2, self.points)
        lay.addLayout(self.sug_btns)
        lay.addWidget(self.cta, 0, Qt.AlignLeft)
        lay.addLayout(row)
        self.hide()

    def setVisible(self, visible):
        super().setVisible(visible)
        if visible:
            self.revealed.emit()

    @staticmethod
    def _label():
        lab = QLabel()
        lab.setWordWrap(True)
        lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
        return lab

    def _ask(self):
        q = self.ask.text().strip()
        if q:
            self.ask.clear()
            self.action.emit("ask", q)

    def _reset(self):
        _clear(self.points)
        _clear(self.sug_btns)
        for w in (self.warn, self.answer, self.sug):
            w.clear()
            w.hide()
        self.cta.hide()
        self.ask.show()

    def idle(self):
        self._reset()
        self.hide()

    def loading(self):
        self._reset()
        self.title.setText(tr("✨ RÉSUMÉ"))
        self.summary.setText(tr("Lecture du message…"))
        self.show()

    def working(self, text):
        self.answer.setText(text)
        self.answer.show()
        self.show()

    def text(self, title, body):
        self.answer.setText("<b>%s</b><br>%s" % (self._esc(title), self._esc(body).replace("\n", "<br>")))
        self.answer.setTextFormat(Qt.RichText)
        self.answer.show()
        self.show()

    @staticmethod
    def _esc(t):
        return (t or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def result(self, res, msg=None, cta=False, error=""):
        self._reset()
        self.title.setText(RA.title(res))
        self.summary.setText(res.get("summary") or "")
        for mark, items in (("•  ", res.get("points", [])), ("☐  ", res.get("tasks", []))):
            for t in items:
                lab = self._label()
                lab.setText(mark + t)
                self.points.addWidget(lab)
        w = RA.warning(res)
        if w:
            self.warn.setText(w)
            self.warn.show()
        if error or res.get("error"):
            self.answer.setText(tr("IA indisponible : %s") % (error or res["error"]))
            self.answer.setTextFormat(Qt.PlainText)
            self.answer.show()
        sug = RA.spam_suggestion(msg, res)
        if sug:
            self.sug.setText(sug[0])
            self.sug.show()
            for label, act, payload in sug[1]:
                b = QPushButton(label)
                b.setObjectName("chip")
                b.clicked.connect(lambda _=False, a=act, p=payload: self.action.emit(a, p))
                self.sug_btns.addWidget(b)
        self.cta.setVisible(cta)
        self.ask.setVisible(not cta)
        self.show()


class GrowEdit(QPlainTextEdit):
    """Zone de saisie de la réponse : grandit avec le texte (2 à 8 lignes). Entrée = nouvelle ligne ; Ctrl+Entrée envoie ; Échap rend la main à la liste."""
    submit = Signal()
    MIN_LINES, MAX_LINES = 2, 8

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTabChangesFocus(True)
        self.textChanged.connect(self._fit)
        self._fit()

    def text(self):
        return self.toPlainText()

    def setText(self, t):
        self.setPlainText(t)

    def clear(self):
        super().clear()
        self._fit()

    def _fit(self):
        fm = self.fontMetrics()
        doc_h = int(self.document().size().height())                       # hauteur réelle du texte (lignes repliées comprises), en pixels
        rows = max(self.MIN_LINES, min(self.MAX_LINES, -(-doc_h // max(1, fm.lineSpacing())))) if doc_h > 0 else self.MIN_LINES
        self.setFixedHeight(rows * fm.lineSpacing() + 18)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and (e.modifiers() & (Qt.ControlModifier | Qt.MetaModifier)):
            self.submit.emit()
            e.accept()
            return
        super().keyPressEvent(e)


class QuickReply(QWidget):
    """Bulle de réponse sous le message (comme Spark) : réponses toutes faites, texte sur plusieurs lignes, « Répondre à tous », envoi immédiat,
    « Agrandir » vers la fenêtre de rédaction complète, et ✨ pour développer le texte avec l'IA."""
    send = Signal(str)
    expand = Signal(str)
    expand_full = Signal(str)
    ai = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 6, 16, 12)
        lay.setSpacing(6)
        chips = QHBoxLayout()
        for t in RA.QUICK_REPLIES:
            b = QPushButton(t)
            b.setObjectName("chip")
            b.clicked.connect(lambda _=False, t=t: self.send.emit(t))
            chips.addWidget(b)
        chips.addStretch(1)
        lay.addLayout(chips)
        self.entry = GrowEdit()
        self.entry.setPlaceholderText(tr("Répondre…  (Ctrl+Entrée pour envoyer)"))
        self.entry.submit.connect(self._send)
        lay.addWidget(self.entry)
        row = QHBoxLayout()
        self.all_box = QCheckBox(tr("Répondre à tous"))
        self.all_box.hide()
        self.reply_ai = QPushButton(tr("✨ Répondre"))
        self.reply_ai.setToolTip(tr("Rédiger une réponse avec l'IA"))
        self.reply_ai.clicked.connect(self.ai.emit)
        self.expand_btn = QPushButton("✨")
        self.expand_btn.setToolTip(tr("Développer ce texte en réponse complète avec l'IA"))
        self.expand_btn.clicked.connect(lambda: self.entry.text().strip() and self.expand.emit(self.entry.text().strip()))
        big = QPushButton(tr("Agrandir"))
        big.setToolTip(tr("Continuer dans la fenêtre de rédaction complète"))
        big.clicked.connect(self._big)
        go = QPushButton(tr("Envoyer") + "  ➤")
        go.setObjectName("primary")
        go.setToolTip(tr("Envoyer la réponse"))
        go.clicked.connect(self._send)
        row.addWidget(self.all_box)
        row.addStretch(1)
        for x in (self.reply_ai, self.expand_btn, big, go):
            row.addWidget(x)
        lay.addLayout(row)

    def reply_all(self):
        return self.all_box.isVisibleTo(self) and self.all_box.isChecked()

    def set_all_available(self, on):
        """Affiche « Répondre à tous » seulement s'il y a d'autres destinataires que l'expéditeur."""
        self.all_box.setVisible(bool(on))
        if not on:
            self.all_box.setChecked(False)

    def _send(self):
        t = self.entry.text().strip()
        if t:
            self.entry.clear()
            self.send.emit(t)

    def _big(self):
        t = self.entry.text().strip()
        self.entry.clear()
        self.expand_full.emit(t)

    def set_ai(self, on):
        self.reply_ai.setVisible(bool(on))
        self.expand_btn.setVisible(bool(on))
