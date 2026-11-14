"""Palette de commandes Qt (Ctrl+K) : champ de recherche + liste ; Entrée lance la commande choisie, ou confie le texte à l'assistant s'il n'y en a pas."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDialog, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout

from ..i18n import tr
from . import menus as M


class Palette(QDialog):
    chosen = Signal(str)                    # clé de commande
    asked = Signal(str)                     # texte libre pour l'assistant

    def __init__(self, parent, cmds):
        super().__init__(parent, Qt.Dialog | Qt.FramelessWindowHint)
        self.cmds = cmds
        self.setModal(True)
        self.resize(580, 420)
        self.edit = QLineEdit()
        self.edit.setObjectName("search")
        self.edit.setPlaceholderText(tr("Tapez une commande — ou demandez n'importe quoi à l'IA…"))
        self.lst = QListWidget()
        lay = QVBoxLayout(self)
        lay.addWidget(self.edit)
        lay.addWidget(self.lst, 1)
        self.edit.textChanged.connect(self._fill)
        self.edit.returnPressed.connect(self._go)
        self.lst.itemActivated.connect(lambda it: self._run(it))
        self._fill("")

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Down, Qt.Key_Up):
            self.lst.setCurrentRow(max(0, min(self.lst.count() - 1, self.lst.currentRow() + (1 if e.key() == Qt.Key_Down else -1))))
            return
        super().keyPressEvent(e)

    def _fill(self, text):
        found = M.search(self.cmds, text)
        self.lst.clear()
        if M.wants_ai(text, found):
            it = QListWidgetItem(tr("✨ Demander à l'assistant : « %s »") % text.strip())
            it.setData(Qt.UserRole, "ai:" + text.strip())
            self.lst.addItem(it)
        for label, key in found[:200]:
            it = QListWidgetItem(label)
            it.setData(Qt.UserRole, key)
            self.lst.addItem(it)
        self.lst.setCurrentRow(0)

    def _go(self):
        it = self.lst.currentItem()
        if it is not None:
            self._run(it)

    def _run(self, it):
        key = it.data(Qt.UserRole)
        self.accept()
        (self.asked.emit(key[3:]) if key.startswith("ai:") else self.chosen.emit(key))
