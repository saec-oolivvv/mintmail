"""Éléments de mise en page des Réglages : une PAGE (défilante) faite de CARTES titrées et bien séparées. Aucune logique métier ici."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFormLayout, QFrame, QLabel, QScrollArea, QVBoxLayout, QWidget


class Card(QFrame):
    """Bloc titré : fond et bordure propres, titre, texte d'aide facultatif, puis le contenu (champs, listes, boutons)."""

    def __init__(self, title="", hint=""):
        super().__init__()
        self.setObjectName("settingscard")
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(20, 16, 20, 18)
        self._lay.setSpacing(10)
        if title:
            head = QLabel(title)
            head.setObjectName("cardtitle")
            self._lay.addWidget(head)
        if hint:
            note = QLabel(hint)
            note.setObjectName("dim")
            note.setWordWrap(True)
            self._lay.addWidget(note)

    def add(self, widget, stretch=0):
        self._lay.addWidget(widget, stretch)
        return widget

    def addLayout(self, layout, stretch=0):
        self._lay.addLayout(layout, stretch)
        return layout

    def form(self):
        """Formulaire (étiquette à gauche, champ à droite) placé dans la carte."""
        f = QFormLayout()
        f.setContentsMargins(0, 4, 0, 0)
        f.setHorizontalSpacing(16)
        f.setVerticalSpacing(10)
        f.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        self._lay.addLayout(f)
        return f


class Page(QScrollArea):
    """Page de réglages : titre, phrase d'introduction, puis des cartes les unes sous les autres ; défile si la fenêtre est petite."""

    def __init__(self, title, intro=""):
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        inner.setObjectName("settingspage")
        self._lay = QVBoxLayout(inner)
        self._lay.setContentsMargins(8, 4, 14, 20)
        self._lay.setSpacing(16)
        head = QLabel(title)
        head.setObjectName("pagetitle")
        self._lay.addWidget(head)
        if intro:
            sub = QLabel(intro)
            sub.setObjectName("dim")
            sub.setWordWrap(True)
            self._lay.addWidget(sub)
        self._tail = None
        self.setWidget(inner)

    def card(self, title="", hint=""):
        c = Card(title, hint)
        self._lay.addWidget(c)
        return c

    def add(self, widget):
        self._lay.addWidget(widget)
        return widget

    def finish(self):
        self._lay.addStretch(1)
        return self

    @staticmethod
    def wrap(widget, title, intro="", card_title="", min_height=420):
        """Présente un ancien onglet (déjà construit) dans une page à carte unique."""
        page = Page(title, intro)
        widget.setMinimumHeight(min_height)
        page.card(card_title).add(widget, 1)
        return page.finish()
