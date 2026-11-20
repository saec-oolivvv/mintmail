"""Auto-complétion des destinataires (À / Cc / Cci) : cherche à chaque frappe dans le carnet ET dans tous les expéditeurs / destinataires déjà vus,
par nom, adresse ou société (sans accents ni casse), et ne remplace que l'adresse en cours de saisie (plusieurs destinataires séparés par des virgules)."""
from PySide6.QtCore import QStringListModel, Qt, QTimer
from PySide6.QtWidgets import QCompleter

from .. import contacts as CT


class AddressCompleter(QCompleter):
    def __init__(self, edit, cache):
        super().__init__(QStringListModel([], edit), edit)
        self.edit, self.cache = edit, cache
        self._rows = []                                   # [(texte affiché, entrée à insérer)]
        self._head = ""
        self._tail = ""
        self.setCaseSensitivity(Qt.CaseInsensitive)
        self.setFilterMode(Qt.MatchContains)
        self.setCompletionMode(QCompleter.PopupCompletion)
        self.setMaxVisibleItems(8)
        self.setWidget(edit)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(120)
        self._timer.timeout.connect(self.refresh)
        edit.textEdited.connect(lambda _t: self._timer.start())

    def refresh(self):
        text, pos = self.edit.text(), self.edit.cursorPosition()
        tok = CT.current_token(text, pos)
        s, _e = CT.token_bounds(text, pos)
        self._head = text[:s]
        self._tail = text[CT.token_bounds(text, pos)[1]:]
        if len(tok.strip()) < 1:
            self.popup().hide()
            return
        self._rows = []
        for name, email, org in self.cache.contact_search(tok, 10):
            entry = CT.format_entry(name, email)
            self._rows.append((entry + (("  ·  " + org) if org else ""), entry))
        self.model().setStringList([r[0] for r in self._rows])
        # le filtrage de Qt (contient la saisie) est contourné : les propositions sont déjà filtrées sans accents ni casse, et peuvent venir de la société
        self.setCompletionPrefix("")
        if self._rows:
            self.complete()
        else:
            self.popup().hide()

    def pathFromIndex(self, index):
        row = index.row()
        entry = self._rows[row][1] if 0 <= row < len(self._rows) else index.data()
        new, _cur = CT.apply_choice(self._head + "x" + self._tail, len(self._head) + 1, entry)      # remplace seulement l'adresse en cours, garde les autres
        return new

    def splitPath(self, path):
        return [""]                                     # préfixe vide : toutes les propositions fournies restent affichées
