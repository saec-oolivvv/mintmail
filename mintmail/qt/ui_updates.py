"""Bandeau de mise à jour du lecteur Qt : affiche l'état décrit par UpdateState.banner (aucune logique ici)."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout

from ..i18n import tr

LABELS = {"install": tr("Installer maintenant"), "notes": tr("Notes de version"), "later": tr("Plus tard"),
          "close": tr("Fermer"), "restart": tr("Relancer maintenant"), "retry": tr("Réessayer")}


class UpdateBanner(QFrame):
    action = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("updatebanner")
        row = QHBoxLayout(self)
        row.setContentsMargins(18, 10, 14, 10)
        self.icon = QLabel()
        self.icon.setStyleSheet("font-size:22px")
        row.addWidget(self.icon)
        col = QVBoxLayout()
        col.setSpacing(2)
        self.title, self.sub, self.notes = QLabel(), QLabel(), QLabel()
        self.title.setObjectName("subject")
        for lab in (self.sub, self.notes):
            lab.setObjectName("dim")
            lab.setWordWrap(True)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        for w in (self.title, self.sub, self.notes, self.bar):
            col.addWidget(w)
        row.addLayout(col, 1)
        self.buttons = {}
        for key, label in LABELS.items():
            b = QPushButton(label)
            b.setObjectName("primary" if key in ("install", "restart", "retry") else "flat")
            b.clicked.connect(lambda _=False, k=key: self.action.emit(k))
            row.addWidget(b)
            self.buttons[key] = b
        self.hide()

    def render(self, b):
        if b["state"] == "hidden":
            self.hide()
            return
        self.icon.setText(b["icon"])
        self.title.setText(b["title"])
        self.sub.setText(b["sub"])
        self.notes.setText(b["notes"])
        self.notes.setVisible(bool(b["notes"]))
        self.bar.setVisible(b["state"] == "progress")
        if b["fraction"] is None:
            self.bar.setRange(0, 0)                                  # progression indéterminée
        else:
            self.bar.setRange(0, 100)
            self.bar.setValue(int(max(0.0, min(1.0, b["fraction"])) * 100))
        for k, btn in self.buttons.items():
            btn.setVisible(k in b["buttons"])
        self.show()
