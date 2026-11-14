"""Fenêtre d'aide (F1) de l'interface Qt : navigation par sections, recherche, liens internes. Le contenu vient de helpdoc.py (testé sans Qt)."""
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QTextBrowser, QVBoxLayout

from .. import APP_NAME, __version__
from ..htmlsafe import safe_to_open
from ..i18n import tr
from . import helpdoc as D


class HelpDialog(QDialog):
    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.setWindowTitle(tr("Aide — %s %s") % (APP_NAME, __version__))
        self.resize(980, 680)
        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText(tr("Rechercher dans l'aide (ex. OAuth, spam, hors ligne, raccourcis)"))
        self.search.textChanged.connect(self._searched)
        self.nav = QListWidget()
        self.nav.setFixedWidth(250)
        for sid, icon, title in D.nav():
            it = QListWidgetItem("%s   %s" % (icon, title))
            it.setData(Qt.UserRole, sid)
            self.nav.addItem(it)
        self.nav.currentItemChanged.connect(self._picked)
        self.page = QTextBrowser()
        self.page.setOpenLinks(False)
        self.page.anchorClicked.connect(self._link)
        left = QVBoxLayout()
        left.addWidget(self.search)
        left.addWidget(self.nav, 1)
        lay = QHBoxLayout(self)
        lay.addLayout(left)
        lay.addWidget(self.page, 1)
        self.goto("sec:" + D.HOME_ID)

    def _t(self):
        return self.main.t

    def goto(self, target):
        kind, _, arg = target.partition(":")
        if kind == "sec":
            self.nav.blockSignals(True)
            for i in range(self.nav.count()):
                if self.nav.item(i).data(Qt.UserRole) == arg:
                    self.nav.setCurrentRow(i)
            self.nav.blockSignals(False)
            if self.search.text():
                self.search.blockSignals(True)
                self.search.clear()
                self.search.blockSignals(False)
        self.page.setHtml(D.page_html(target, self._t()))
        self.page.verticalScrollBar().setValue(0)

    def _picked(self, cur, _prev):
        if cur is not None:
            self.goto("sec:" + cur.data(Qt.UserRole))

    def _searched(self, text):
        text = text.strip()
        if text:
            self.nav.blockSignals(True)
            self.nav.clearSelection()
            self.nav.setCurrentRow(-1)
            self.nav.blockSignals(False)
            self.page.setHtml(D.results_html(text, self._t()))
        else:
            self.goto("sec:" + D.HOME_ID)

    def _link(self, url: QUrl):
        s = url.toString()
        if s.startswith(("sec:", "tip:")):
            self.goto(s)
        else:
            safe = safe_to_open(s)
            if safe:
                QDesktopServices.openUrl(QUrl(safe))
