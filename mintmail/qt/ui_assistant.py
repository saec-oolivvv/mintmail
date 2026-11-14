"""Panneau « Assistant IA » (Qt) : conversation, suggestions, plans d'actions validés un par un ou d'un coup.
Aucune logique ici : tout vient de assistant.py (testé sans Qt)."""
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget

from ..i18n import tr
from .assistant import SUGGESTIONS


class AssistantPanel(QFrame):
    asked = Signal(str)
    closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("assistant")
        self.setMinimumWidth(330)
        self.setMaximumWidth(380)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        head = QFrame()
        head.setObjectName("assistanthead")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(16, 10, 10, 10)
        title = QLabel(tr("<b>✨ Assistant</b>"))
        title.setObjectName("subject")
        hl.addWidget(title, 1)
        for glyph, tip, fn in (("↺", tr("Nouvelle conversation"), self.clear), ("✕", tr("Fermer (Ctrl+J)"), self.closed.emit)):
            b = QPushButton(glyph)
            b.setObjectName("flat")
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, f=fn: f())
            hl.addWidget(b)
        lay.addWidget(head)

        self.body = QWidget()
        self.log = QVBoxLayout(self.body)
        self.log.setContentsMargins(12, 12, 12, 12)
        self.log.setSpacing(8)
        self.log.addStretch(1)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setWidget(self.body)
        lay.addWidget(self.scroll, 1)

        self.chips = QWidget()
        cl = QVBoxLayout(self.chips)
        cl.setContentsMargins(12, 0, 12, 8)
        cl.setSpacing(6)
        for t in SUGGESTIONS:
            b = QPushButton(t)
            b.setObjectName("chip")
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, tx=t: self.asked.emit(tx))
            cl.addWidget(b, 0, Qt.AlignLeft)
        lay.addWidget(self.chips)

        row = QHBoxLayout()
        row.setContentsMargins(12, 8, 12, 12)
        self.entry = QLineEdit()
        self.entry.setPlaceholderText(tr("Demandez n'importe quoi à votre boîte mail…"))
        self.entry.returnPressed.connect(self._send)
        send = QPushButton("➤")
        send.setObjectName("primary")
        send.clicked.connect(self._send)
        row.addWidget(self.entry, 1)
        row.addWidget(send)
        lay.addLayout(row)
        self._busy = None

    def _send(self):
        t = self.entry.text().strip()
        if t:
            self.entry.clear()
            self.asked.emit(t)

    def _add(self, w, align=Qt.AlignLeft):
        self.chips.hide()
        self.log.insertWidget(self.log.count() - 1, w, 0, align)
        QTimer.singleShot(30, lambda: self.scroll.verticalScrollBar().setValue(self.scroll.verticalScrollBar().maximum()))

    def _bubble(self, text, kind):
        lab = QLabel(text)
        lab.setObjectName("bubble_" + kind)
        lab.setWordWrap(True)
        lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lab.setMaximumWidth(300)
        return lab

    def add_user(self, text):
        self._add(self._bubble(text, "user"), Qt.AlignRight)

    def add_ai(self, text):
        lab = self._bubble(text, "ai")
        self._add(lab)
        return lab

    def set_busy(self, busy):
        if busy and self._busy is None:
            self._busy = self._bubble("…", "ai")
            self._add(self._busy)
        elif not busy and self._busy is not None:
            self._busy.deleteLater()
            self.log.removeWidget(self._busy)
            self._busy = None
        self.entry.setEnabled(not busy)
        if not busy:
            self.entry.setFocus()

    def add_plan(self, items):
        """items : [(description, rappel ou None)] ; chaque action est confirmée par un clic, « Tout exécuter » les lance toutes."""
        buttons = []
        for desc, fn in items:
            row = QFrame()
            row.setObjectName("planrow")
            rl = QHBoxLayout(row)
            rl.setContentsMargins(10, 6, 6, 6)
            lab = QLabel(desc)
            lab.setWordWrap(True)
            rl.addWidget(lab, 1)
            if fn is not None:
                btn = QPushButton(tr("Exécuter"))
                btn.setObjectName("chip")
                btn.clicked.connect(lambda _=False, b=btn, f=fn: self._go(b, f))
                rl.addWidget(btn)
                buttons.append((btn, fn))
            self._add(row)
        if len(buttons) > 1:
            allb = QPushButton(tr("Tout exécuter"))
            allb.setObjectName("primary")
            allb.clicked.connect(lambda _=False, b=allb: self._all(b, buttons))
            self._add(allb, Qt.AlignRight)

    @staticmethod
    def _go(btn, fn):
        if btn.isEnabled():
            btn.setEnabled(False)
            btn.setText(tr("✓ Fait"))
            fn()

    def _all(self, allb, buttons):
        allb.setEnabled(False)
        for b, fn in buttons:
            self._go(b, fn)

    def clear(self):
        while self.log.count() > 1:
            w = self.log.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        self._busy = None
        self.entry.setEnabled(True)
        self.chips.show()

    def focus_entry(self):
        self.entry.setFocus()
