"""Colonne « Informations » à droite du message : informations sur le message, alertes (suspect, accusé de lecture, traduction), images, pièces jointes,
résumé / traduction IA. Elle défile : une traduction longue ou un petit écran ne cachent plus le message. Étroite (écran étroit) : elle passe au-dessus du message."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QScrollArea, QSplitter, QVBoxLayout, QWidget

from ..i18n import tr

WIDE_MIN = 900        # largeur du lecteur à partir de laquelle la colonne se met à droite


class InfoColumn(QScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("infocol")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setMinimumWidth(250)
        body = QWidget()
        body.setObjectName("infobody")
        self.lay = QVBoxLayout(body)
        self.lay.setContentsMargins(8, 8, 8, 8)
        self.lay.setSpacing(8)
        self.title = QLabel(tr("INFORMATIONS"))
        self.title.setObjectName("caption")
        self.facts = QLabel()
        self.facts.setTextFormat(Qt.RichText)
        self.facts.setWordWrap(True)
        self.facts.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lay.addWidget(self.title)
        self.lay.addWidget(self.facts)
        self.lay.addStretch(1)
        self.setWidget(body)

    def add(self, widget):
        """Ajoute une carte (avant l'étirement final)."""
        self.lay.insertWidget(self.lay.count() - 1, widget)

    def set_facts(self, rows, dim="#888"):
        esc = lambda x: str(x).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        self.facts.setText("".join("<div style='margin:2px 0'><span style='color:%s'>%s</span><br><b>%s</b></div>" % (dim, esc(k), esc(v)) for k, v in rows))
        self.title.setVisible(bool(rows))


class BodySplit(QSplitter):
    """Message + colonne d'informations : côte à côte si la place le permet, sinon la colonne passe au-dessus (hauteur limitée, elle défile)."""

    def __init__(self, reader_col, info, parent=None):
        super().__init__(Qt.Horizontal, parent)
        self.reader_col, self.info = reader_col, info
        self.addWidget(reader_col)
        self.addWidget(info)
        self.setChildrenCollapsible(False)
        self.setHandleWidth(8)
        self.setStretchFactor(0, 1)
        self.setStretchFactor(1, 0)
        self._wide = True
        self.info_width = 320

    def resizeEvent(self, e):
        super().resizeEvent(e)
        wide = self.width() >= WIDE_MIN
        if wide != self._wide:
            self._wide = wide
            self.setOrientation(Qt.Horizontal if wide else Qt.Vertical)
            self.insertWidget(1 if wide else 0, self.info)             # étroit : les informations d'abord, le message dessous
            self._sizes()
        elif not e.oldSize().isValid() or e.oldSize().width() <= 0:
            self._sizes()

    def _sizes(self):
        if self._wide:
            self.setSizes([max(300, self.width() - self.info_width), self.info_width])
        else:
            h = max(120, int(self.height() * 0.34))
            self.setSizes([h, max(200, self.height() - h)])
