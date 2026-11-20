"""Journal d'activité des boîtes : bande du pied de page (dernière action, en direct) et fenêtre d'historique. Les données viennent de mintmail/activity.py."""
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout

from .. import activity as AC
from ..i18n import tr

SPIN = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


class ActivityStrip(QLabel):
    """Ligne (2 lignes au plus) sous la liste des dossiers : ce que MintMail fait en ce moment avec vos boîtes. Un clic ouvre l'historique."""
    clicked = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("footer")
        self.setWordWrap(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setContentsMargins(20, 0, 14, 0)
        self.setMaximumHeight(44)
        self._frame = 0
        self.rail = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(250)
        self.setToolTip(tr("Activité des boîtes en direct — cliquez pour l'historique"))
        self.refresh()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(ev)

    def refresh(self):
        level, text = AC.LOG.current()
        if level is None or self.rail:
            self.setText("")
            self.setVisible(False)
            return
        if level == AC.BUSY:
            self._frame = (self._frame + 1) % len(SPIN)
            icon = SPIN[self._frame]
        else:
            icon = AC.ICONS.get(level, "•")
            self._timer.setInterval(1000)
        if level == AC.BUSY:
            self._timer.setInterval(250)
        self.setText("%s %s" % (icon, text))
        self.setVisible(True)


class ActivityDialog(QDialog):
    """Historique des actions sur les boîtes (relèves, suppressions, déplacements, refus du serveur…), mis à jour en direct."""

    def __init__(self, main):
        super().__init__(main)
        self.setWindowTitle(tr("Activité des boîtes e-mail"))
        self.resize(760, 480)
        self.info = QLabel(tr("Tout ce que MintMail fait avec vos boîtes, en direct. Les lignes rouges sont des actions refusées par le serveur : le message concerné réapparaît alors à la prochaine relève."))
        self.info.setWordWrap(True)
        self.list = QListWidget()
        self.list.setUniformItemSizes(True)
        self.busy = QLabel()
        self.copy_btn = QPushButton(tr("Copier"))
        self.clear_btn = QPushButton(tr("Effacer"))
        self.close_btn = QPushButton(tr("Fermer"))
        self.copy_btn.clicked.connect(self._copy)
        self.clear_btn.clicked.connect(AC.LOG.clear)
        self.close_btn.clicked.connect(self.close)
        row = QHBoxLayout()
        row.addWidget(self.busy, 1)
        for b in (self.copy_btn, self.clear_btn, self.close_btn):
            row.addWidget(b)
        lay = QVBoxLayout(self)
        lay.addWidget(self.info)
        lay.addWidget(self.list, 1)
        lay.addLayout(row)
        self._seen = -1
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(500)
        self.refresh()

    def refresh(self):
        if not self.isVisible() and self._seen != -1:
            return
        busy = AC.LOG.busy()
        self.busy.setText(("⟳ " + " · ".join(busy)) if busy else "")
        if AC.LOG.seq == self._seen:
            return
        self._seen = AC.LOG.seq
        self.list.clear()
        for it in AC.LOG.entries(300):
            row = QListWidgetItem(AC.line(it))
            if it["level"] == AC.ERR:
                row.setForeground(Qt.red)
            elif it["level"] == AC.WARN:
                row.setForeground(Qt.darkYellow)
            self.list.addItem(row)

    def _copy(self):
        QGuiApplication.clipboard().setText("\n".join(AC.line(i) for i in reversed(AC.LOG.entries(400))))

    def closeEvent(self, ev):
        self._timer.stop()
        super().closeEvent(ev)

    def showEvent(self, ev):
        self._seen = -1
        self._timer.start(500)
        self.refresh()
        super().showEvent(ev)
