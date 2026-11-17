"""Rangées de groupes en haut de la boîte unifiée (comme Spark) : Épinglés, Notifications, Newsletters, Invitations… Chaque rangée montre
le nombre de non lus et SEULEMENT les noms des expéditeurs ; un clic ouvre le groupe."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .. import groups as G

ICONS = {"pinned": "📌", "notif": "🔔", "news": "📰", "invite": "📅", "reply": "↩", "mine": "👤"}


class GroupRows(QWidget):
    opened = Signal(str)

    def __init__(self):
        super().__init__()
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(12, 0, 12, 4)
        self.lay.setSpacing(2)
        self.rows = {}
        for key in G.ROW_ORDER:
            b = QPushButton()
            b.setObjectName("grouprow")
            b.setFlat(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.NoFocus)
            lay = QHBoxLayout(b)
            lay.setContentsMargins(10, 6, 10, 6)
            icon, name, who, badge = QLabel(ICONS[key]), QLabel(), QLabel(), QLabel()
            for w in (icon, name, who, badge):
                w.setAttribute(Qt.WA_TransparentForMouseEvents)
            name.setStyleSheet("font-weight: 600;")
            who.setStyleSheet("color: palette(placeholder-text);")
            who.setMinimumWidth(10)
            badge.setStyleSheet("font-weight: 600; padding: 0 6px; border-radius: 9px; background: palette(highlight); color: palette(highlighted-text);")
            lay.addWidget(icon)
            lay.addWidget(name)
            lay.addWidget(who, 1)
            lay.addWidget(badge)
            b.clicked.connect(lambda _c=False, k=key: self.opened.emit(k))
            self.lay.addWidget(b)
            self.rows[key] = (b, name, who, badge)
            b.hide()
        self.hide()

    def update_rows(self, digest):
        """digest : sortie de groups.digest ; seuls les groupes qui ont des messages sont montrés."""
        labels, any_ = G.labels(), False
        for key, (b, name, who, badge) in self.rows.items():
            d = (digest or {}).get(key)
            b.setVisible(bool(d))
            if not d:
                continue
            any_ = True
            name.setText(labels[key])
            more = " …" if d["n"] > len(d["senders"]) and len(d["senders"]) >= 4 else ""
            who.setText(", ".join(d["senders"]) + more)
            badge.setText(str(d["unread"]))
            badge.setVisible(d["unread"] > 0)
        self.setVisible(any_)
