"""Réglages → Comptes → « Importer depuis un autre logiciel » : retrouve les boîtes de Thunderbird / Evolution sur cet ordinateur, ou crée les boîtes
d'après les adresses que l'on colle (Outlook, Spark, Apple Mail, Gmail…), avec signature et alias quand ils sont connus."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QFileDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton, QVBoxLayout)

from .. import importer as IM
from ..backend import new_account_id
from ..i18n import tr
from . import personal as P


class ImportDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowTitle(tr("Importer depuis un autre logiciel"))
        self.resize(640, 560)
        self.found = []
        lay = QVBoxLayout(self)
        intro = QLabel(tr("Thunderbird et Evolution sont lus directement sur cet ordinateur (en lecture seule). Pour Outlook, Spark, Apple Mail, Gmail ou tout autre "
                          "logiciel, collez vos adresses e-mail ci-dessous : MintMail retrouve les serveurs. Les mots de passe ne sont jamais importés : "
                          "vous les saisirez ensuite, ou vous cliquerez « Se connecter » pour Gmail et Outlook."))
        intro.setWordWrap(True)
        lay.addWidget(intro)
        row = QHBoxLayout()
        scan = QPushButton(tr("Chercher sur cet ordinateur"))
        scan.clicked.connect(self._scan)
        row.addWidget(scan)
        row.addStretch(1)
        lay.addLayout(row)
        self.addresses = QPlainTextEdit()
        self.addresses.setPlaceholderText(tr("Vos adresses e-mail (une par ligne) : Outlook, Spark, Apple Mail, Gmail…"))
        self.addresses.setMaximumHeight(90)
        lay.addWidget(self.addresses)
        add = QPushButton(tr("Retrouver les réglages de ces adresses"))
        add.clicked.connect(self._from_addresses)
        lay.addWidget(add)
        self.listing = QListWidget()
        lay.addWidget(self.listing, 1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setObjectName("dim")
        lay.addWidget(self.status)
        bottom = QHBoxLayout()
        contacts = QPushButton(tr("Importer des contacts (CSV / vCard)…"))
        contacts.clicked.connect(self._contacts)
        self.go = QPushButton(tr("Importer la sélection"))
        self.go.setObjectName("primary")
        self.go.clicked.connect(self._import)
        close = QPushButton(tr("Fermer"))
        close.clicked.connect(self.accept)
        bottom.addWidget(contacts)
        bottom.addStretch(1)
        bottom.addWidget(self.go)
        bottom.addWidget(close)
        lay.addLayout(bottom)
        self._scan()

    def _show(self, accounts):
        self.found = accounts
        self.listing.clear()
        have = {a["email"].lower() for a in self.win.cfg.get("accounts") or []}
        for a in accounts:
            txt = "%s  —  %s  (%s)" % (a["email"], a["imap_host"], a.get("source") or tr("adresse"))
            if a["email"].lower() in have:
                txt += "  · " + tr("déjà présent")
            elif a.get("note") == "check":
                txt += "  · " + tr("serveurs à vérifier")
            if a.get("aliases"):
                txt += "  · " + tr("%d alias") % len(a["aliases"])
            it = QListWidgetItem(txt)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Unchecked if a["email"].lower() in have else Qt.Checked)
            self.listing.addItem(it)
        self.go.setEnabled(bool(accounts))

    def _scan(self):
        accounts = [a for f in IM.detect() for a in f["accounts"]]
        self._show(accounts)
        self.status.setText(tr("%d boîte(s) trouvée(s) sur cet ordinateur.") % len(accounts) if accounts else
                            tr("Aucun Thunderbird ni Evolution trouvé ici : collez vos adresses pour Outlook, Spark, Apple Mail, Gmail…"))

    def _from_addresses(self):
        accounts = IM.from_addresses(self.addresses.toPlainText())
        self._show(accounts)
        self.status.setText(tr("%d adresse(s) reconnue(s).") % len(accounts) if accounts else tr("Aucune adresse e-mail valide dans le texte."))

    def _import(self):
        chosen = [a for i, a in enumerate(self.found) if self.listing.item(i).checkState() == Qt.Checked]
        r = IM.apply(self.win.cfg, chosen, new_account_id)
        self.win._reload_accounts(r["ids"][0] if r["ids"] else None)
        self.win.main.reload()
        self.status.setText(tr("%d boîte(s) importée(s), %d ignorée(s). Ouvrez chaque compte (Comptes) pour saisir son mot de passe ou cliquer « Se connecter ».")
                            % (r["added"], r["skipped"]))
        self._show([])

    def _contacts(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("Importer des contacts (vCard ou CSV)"), "", "Contacts (*.vcf *.csv)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                n = P.import_contacts(self.win.cfg, self.win.main.cache, fh.read())
            self.status.setText(tr("%d contact(s) importé(s).") % n)
        except OSError as e:
            self.status.setText(tr("Lecture impossible : %s") % e)
