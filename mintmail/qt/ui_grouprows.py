"""Rangées de groupes en haut de la boîte unifiée, comme dans Spark : sous le titre de période, une rangée par groupe (Épinglés, Notifications,
Newsletters, Invitations…) avec son icône, le nombre de messages, un point bleu s'il y a des non lus, et SEULEMENT les expéditeurs (avatar + nom).
Un clic ouvre le groupe."""
from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QFont, QPainter
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .. import groups as G
from .ui_widgets import draw_avatar

ICONS = {"pinned": "📌", "notif": "🔔", "news": "📰", "invite": "📅", "reply": "↩", "mine": "👤"}


class _Who(QWidget):
    """Expéditeurs d'un groupe : avatar + nom, côte à côte, tronqués à la largeur disponible."""

    def __init__(self, theme_fn):
        super().__init__()
        self.theme_fn, self.people = theme_fn, []
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setMinimumWidth(10)
        self.setFixedHeight(26)

    def sizeHint(self):
        return QSize(200, 26)

    def paintEvent(self, _e):
        t = self.theme_fn()
        p = QPainter(self)
        f = QFont(self.font())
        f.setPixelSize(14)
        p.setFont(f)
        x, fm = 0, p.fontMetrics()
        for name, key in self.people:
            w = fm.horizontalAdvance(name) + 24 + 18
            if x + 60 > self.width():
                break
            draw_avatar(p, QRect(x, 3, 20, 20), name, key, t)
            room = min(fm.horizontalAdvance(name), self.width() - x - 26)
            p.setPen(self.palette().text().color())
            p.drawText(QRect(x + 26, 0, room, 26), Qt.AlignVCenter | Qt.AlignLeft, fm.elidedText(name, Qt.ElideRight, room))
            x += w
        p.end()


class GroupRows(QWidget):
    opened = Signal(str)

    def __init__(self, theme_fn):
        super().__init__()
        self.theme_fn = theme_fn
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 0, 12, 4)
        lay.setSpacing(2)
        self.heading = QLabel()
        self.heading.setContentsMargins(8, 8, 0, 2)
        f = QFont(self.font())
        f.setBold(True)
        f.setPixelSize(12)
        self.heading.setFont(f)
        self.heading.setStyleSheet("color: palette(placeholder-text);")
        lay.addWidget(self.heading)
        self.rows = {}
        for key in G.ROW_ORDER:
            b = QPushButton()
            b.setObjectName("grouprow")
            b.setFlat(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.NoFocus)
            b.setMinimumHeight(48)
            row = QHBoxLayout(b)
            row.setContentsMargins(8, 4, 12, 4)
            dot, icon, name, count, who, chev = QLabel("●"), QLabel(ICONS[key]), QLabel(), QLabel(), _Who(theme_fn), QLabel("›")
            for w in (dot, icon, name, count, chev):
                w.setAttribute(Qt.WA_TransparentForMouseEvents)
            dot.setFixedWidth(14)
            dot.setStyleSheet("color: #3b82f6; font-size: 9px;")
            icon.setFixedWidth(34)
            icon.setAlignment(Qt.AlignCenter)
            icon.setStyleSheet("font-size: 17px;")
            name.setStyleSheet("font-weight: 600;")
            count.setStyleSheet("color: palette(placeholder-text); font-size: 11px;")
            chev.setStyleSheet("color: palette(placeholder-text); font-size: 18px;")
            name.setMinimumWidth(110)
            for w in (dot, icon, name, count):
                row.addWidget(w)
            row.addSpacing(18)
            row.addWidget(who, 1)
            row.addWidget(chev)
            b.clicked.connect(lambda _c=False, k=key: self.opened.emit(k))
            lay.addWidget(b)
            self.rows[key] = (b, dot, name, count, who)
            b.hide()
        self.hide()

    def update_rows(self, digest, heading=""):
        """digest : sortie de groups.digest ; seuls les groupes qui ont des messages sont montrés ; `heading` : titre de période au-dessus."""
        labels, any_ = G.labels(), False
        for key, (b, dot, name, count, who) in self.rows.items():
            d = (digest or {}).get(key)
            b.setVisible(bool(d))
            if not d:
                continue
            any_ = True
            name.setText(labels[key])
            count.setText(str(d["n"]))
            dot.setText("●" if d["unread"] else " ")
            who.people = list(zip(d["senders"], d["keys"]))
            who.update()
        self.heading.setText(heading)
        self.heading.setVisible(bool(heading))
        self.setVisible(any_)
