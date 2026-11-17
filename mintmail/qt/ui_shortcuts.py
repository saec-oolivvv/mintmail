"""Réglages → Raccourcis : la liste complète des raccourcis de MintMail, modifiables un par un (conflits refusés), avec retour aux valeurs d'origine."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (QHBoxLayout, QKeySequenceEdit, QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QWidget)

from .. import shortcuts as SC
from ..i18n import tr
from .ui_cards import Page


def shortcuts_tab(win):
    cfg = win.cfg
    page = Page(tr("Raccourcis"), tr("Cliquez dans la colonne « Raccourci » puis tapez la combinaison voulue. Une touche déjà prise par une autre action est refusée ; la croix désactive l'action, la flèche remet la valeur d'origine."))
    find = QLineEdit()
    find.setPlaceholderText(tr("Filtrer les actions…"))
    table = QTableWidget(0, 4)
    table.setHorizontalHeaderLabels([tr("Action"), tr("Raccourci"), "", ""])
    table.verticalHeader().setVisible(False)
    table.setSelectionMode(QTableWidget.NoSelection)
    table.setEditTriggers(QTableWidget.NoEditTriggers)
    table.horizontalHeader().setStretchLastSection(False)
    table.setColumnWidth(0, 300)
    table.setColumnWidth(1, 180)
    table.setColumnWidth(2, 40)
    table.setColumnWidth(3, 40)
    table.setMinimumHeight(520)
    rows = []

    def fill():
        table.setRowCount(0)
        rows.clear()
        last = None
        needle = find.text().strip().lower()
        for aid, scope, group, label, defaults in SC.catalog():
            if needle and needle not in label.lower() and needle not in group.lower():
                continue
            if group != last:
                r = table.rowCount()
                table.insertRow(r)
                head = QTableWidgetItem(group.upper())
                f = head.font()
                f.setBold(True)
                head.setFont(f)
                head.setFlags(Qt.NoItemFlags)
                table.setItem(r, 0, head)
                table.setSpan(r, 0, 1, 4)
                last = group
            r = table.rowCount()
            table.insertRow(r)
            item = QTableWidgetItem(label + ("  (%s)" % tr("fenêtre de rédaction") if scope == SC.COMPOSE else ""))
            item.setFlags(Qt.ItemIsEnabled)
            table.setItem(r, 0, item)
            edit = QKeySequenceEdit()
            current = SC.keys_of(cfg, aid)
            edit.setKeySequence(QKeySequence(current[0] if current else ""))
            edit.setMaximumSequenceLength(1)
            edit.editingFinished.connect(lambda a=aid, e=edit: apply(a, e))
            table.setCellWidget(r, 1, edit)
            off = QPushButton("✕")
            off.setFlat(True)
            off.setToolTip(tr("Désactiver ce raccourci"))
            off.clicked.connect(lambda _c=False, a=aid: change(a, ""))
            table.setCellWidget(r, 2, off)
            back = QPushButton("↺")
            back.setFlat(True)
            back.setToolTip(tr("Valeur d'origine : %s") % ", ".join(SC.display(d) for d in defaults))
            back.clicked.connect(lambda _c=False, a=aid: (SC.reset(cfg, a), refresh()))
            table.setCellWidget(r, 3, back)

    def refresh():
        fill()
        win.main.reapply_shortcuts()

    def change(aid, seq):
        other = SC.set_key(cfg, aid, seq)
        if other:
            QMessageBox.warning(win, tr("Raccourcis"), tr("Ce raccourci est déjà utilisé par « %s ».") % other)
        refresh()

    def apply(aid, edit):
        seq = edit.keySequence().toString(QKeySequence.PortableText)
        if seq == (SC.keys_of(cfg, aid) or ("",))[0]:
            return
        change(aid, seq)

    find.textChanged.connect(lambda _t: fill())
    card = page.card(tr("Raccourcis clavier"))
    card.add(find)
    card.add(table)
    row = QWidget()
    rl = QHBoxLayout(row)
    rl.setContentsMargins(0, 0, 0, 0)
    reset_all = QPushButton(tr("Tout remettre à la valeur d'origine"))
    reset_all.clicked.connect(lambda: (SC.reset(cfg), refresh()))
    rl.addWidget(reset_all)
    rl.addStretch(1)
    card.add(row)
    fill()
    return page.finish()
