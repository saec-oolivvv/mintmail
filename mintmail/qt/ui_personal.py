"""Onglets des réglages Qt : Signatures, Identités d'envoi, Modèles de réponse, Contacts. Toute la logique est dans personal.py (testée sans Qt)."""
from PySide6.QtWidgets import (QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit,
                               QPushButton, QTextBrowser, QVBoxLayout, QWidget)
from PySide6.QtCore import Qt

from ..i18n import tr
from . import personal as P

ROLE = Qt.UserRole


def _note(text):
    lab = QLabel(text)
    lab.setWordWrap(True)
    lab.setEnabled(False)
    return lab


def _accounts_combo(cfg):
    box = QComboBox()
    for a in cfg["accounts"]:
        box.addItem("%s <%s>" % (a.get("name", ""), a["email"]) if a.get("name") else a["email"], a["id"])
    return box


def signatures_tab(dlg):
    cfg = dlg.cfg
    w = QWidget()
    lay = QVBoxLayout(w)
    top = QHBoxLayout()
    acc = _accounts_combo(cfg)
    tpl, save = QPushButton(tr("Insérer un modèle")), QPushButton(tr("Enregistrer la signature"))
    top.addWidget(QLabel(tr("Compte :")))
    top.addWidget(acc, 1)
    top.addWidget(tpl)
    top.addWidget(save)
    lay.addLayout(top)
    lay.addWidget(QLabel(tr("Signature HTML (balises <b>, <a>, <img>… autorisées) :")))
    edit = QPlainTextEdit()
    edit.setMaximumHeight(170)
    lay.addWidget(edit)
    lay.addWidget(QLabel(tr("Aperçu :")))
    view = QTextBrowser()
    view.setOpenLinks(False)
    lay.addWidget(view, 1)
    status = QLabel("")
    lay.addWidget(status)

    def load(_i=0):
        edit.setPlainText(P.get_signature(cfg, acc.currentData()) if acc.count() else "")

    def preview():
        view.setHtml(P.signature_preview(edit.toPlainText()))

    def do_save():
        ok = P.set_signature(cfg, acc.currentData(), edit.toPlainText())
        status.setText(tr("Signature enregistrée") if ok else "")
    acc.currentIndexChanged.connect(load)
    edit.textChanged.connect(preview)
    tpl.clicked.connect(lambda: edit.setPlainText(P.SIG_TEMPLATE))
    save.clicked.connect(do_save)
    load()
    return w


def identities_tab(dlg):
    cfg = dlg.cfg
    w = QWidget()
    row = QHBoxLayout(w)
    left = QVBoxLayout()
    lst = QListWidget()
    lst.setMinimumWidth(230)
    add = QPushButton(tr("＋ Ajouter une identité"))
    left.addWidget(lst, 1)
    left.addWidget(add)
    row.addLayout(left)
    form = QFormLayout()
    acc, name, email = _accounts_combo(cfg), QLineEdit(), QLineEdit()
    sig = QPlainTextEdit()
    sig.setMaximumHeight(150)
    save, rm = QPushButton(tr("Enregistrer")), QPushButton(tr("Supprimer"))
    status = QLabel("")
    form.addRow(tr("Compte d'envoi"), acc)
    form.addRow(tr("Nom affiché"), name)
    form.addRow(tr("Adresse (alias)"), email)
    form.addRow(tr("Signature (HTML)"), sig)
    btns = QHBoxLayout()
    btns.addWidget(save)
    btns.addWidget(rm)
    btns.addStretch(1)
    form.addRow("", btns)
    form.addRow("", status)
    form.addRow("", _note(tr("Une identité est une adresse supplémentaire (alias) depuis laquelle vous pouvez écrire, avec sa propre signature. "
                             "Le serveur du compte doit autoriser cet alias. Quand un message reçu était adressé à un alias, la réponse part "
                             "automatiquement de cet alias. Choix possible dans le champ « De » de la rédaction.")))
    row.addLayout(form, 1)
    cur = {"id": None}

    def refresh(select=None):
        lst.blockSignals(True)
        lst.clear()
        for i in P.identities(cfg):
            it = QListWidgetItem("%s <%s>" % (i.get("name", ""), i["email"]))
            it.setData(ROLE, i["id"])
            lst.addItem(it)
            if select == i["id"]:
                lst.setCurrentItem(it)
        lst.blockSignals(False)

    def fill(i):
        i = i or {}
        cur["id"] = i.get("id")
        k = acc.findData(i.get("account"))
        acc.setCurrentIndex(k if k >= 0 else 0)
        name.setText(i.get("name", ""))
        email.setText(i.get("email", ""))
        sig.setPlainText(i.get("signature_html", ""))

    def picked(item):
        fill(next((i for i in P.identities(cfg) if i["id"] == item.data(ROLE)), None) if item else None)

    def do_add():
        lst.clearSelection()
        lst.setCurrentRow(-1)
        fill(None)
        email.setFocus()

    def do_save():
        ident, msg = P.identity_save(cfg, cur["id"], acc.currentData(), name.text(), email.text(), sig.toPlainText())
        status.setText(msg)
        if ident:
            cur["id"] = ident["id"]
            refresh(ident["id"])

    def do_rm():
        if cur["id"] and P.identity_delete(cfg, cur["id"]):
            refresh()
            fill(None)
    lst.currentItemChanged.connect(lambda item, _p=None: picked(item))
    add.clicked.connect(do_add)
    save.clicked.connect(do_save)
    rm.clicked.connect(do_rm)
    refresh()
    return w


def templates_tab(dlg):
    cfg = dlg.cfg
    w = QWidget()
    row = QHBoxLayout(w)
    left = QVBoxLayout()
    lst = QListWidget()
    lst.setMinimumWidth(200)
    new = QPushButton(tr("＋ Nouveau modèle"))
    left.addWidget(lst, 1)
    left.addWidget(new)
    row.addLayout(left)
    right = QVBoxLayout()
    name = QLineEdit()
    name.setPlaceholderText(tr("Nom du modèle"))
    body = QPlainTextEdit()
    save, rm = QPushButton(tr("Enregistrer")), QPushButton(tr("Supprimer"))
    right.addWidget(name)
    right.addWidget(_note(tr("Contenu HTML. Insertion depuis le bouton « Modèles » de la fenêtre de rédaction.")))
    right.addWidget(body, 1)
    btns = QHBoxLayout()
    btns.addWidget(save)
    btns.addWidget(rm)
    btns.addStretch(1)
    right.addLayout(btns)
    row.addLayout(right, 1)
    cur = {"i": None}

    def refresh(select=None):
        lst.blockSignals(True)
        lst.clear()
        for t in P.templates(cfg):
            lst.addItem(t["name"])
        lst.blockSignals(False)
        if select is not None and P.templates(cfg):
            lst.setCurrentRow(min(select, len(P.templates(cfg)) - 1))
            picked(lst.currentRow())

    def picked(r):
        if 0 <= r < len(P.templates(cfg)):
            cur["i"] = r
            t = P.templates(cfg)[r]
            name.setText(t["name"])
            body.setPlainText(t["html"])

    def on_new():
        refresh(P.template_add(cfg))

    def on_save():
        i = cur["i"]
        if P.template_save(cfg, i, name.text(), body.toPlainText()):
            refresh(i)
            dlg.main.status.setText(tr("Modèle enregistré"))

    def on_rm():
        if P.template_delete(cfg, cur["i"]):
            cur["i"] = None
            name.clear()
            body.clear()
            refresh(0)
    lst.currentRowChanged.connect(picked)
    new.clicked.connect(on_new)
    save.clicked.connect(on_save)
    rm.clicked.connect(on_rm)
    refresh(0)
    return w


def contacts_tab(dlg):
    cfg, main = dlg.cfg, dlg.main
    cache = main.engine.cache
    w = QWidget()
    row = QHBoxLayout(w)
    left = QVBoxLayout()
    search = QLineEdit()
    search.setPlaceholderText(tr("Rechercher un contact"))
    lst = QListWidget()
    lst.setMinimumWidth(280)
    io = QHBoxLayout()
    imp, exp = QPushButton(tr("Importer .vcf")), QPushButton(tr("Exporter .vcf"))
    io.addWidget(imp)
    io.addWidget(exp)
    left.addWidget(search)
    left.addWidget(lst, 1)
    left.addLayout(io)
    row.addLayout(left)
    form = QFormLayout()
    f = {k: QLineEdit() for k in ("name", "email", "phone", "org", "notes")}
    for k, lab in (("name", tr("Nom")), ("email", tr("Adresse e-mail")), ("phone", tr("Téléphone")), ("org", tr("Société")), ("notes", tr("Notes"))):
        form.addRow(lab, f[k])
    new, save, rm, write = QPushButton(tr("Nouveau")), QPushButton(tr("Enregistrer")), QPushButton(tr("Supprimer")), QPushButton(tr("✉ Écrire"))
    btns = QHBoxLayout()
    for b in (new, save, rm, write):
        btns.addWidget(b)
    btns.addStretch(1)
    status = QLabel("")
    form.addRow("", btns)
    form.addRow("", status)
    form.addRow("", _note(tr("Les fiches enregistrées ici se synchronisent entre vos machines. Les autres correspondants (marqués auto) sont "
                             "repérés dans vos messages et servent à l'auto-complétion.")))
    row.addLayout(form, 1)

    def fill(c):
        for k in f:
            f[k].setText((c or {}).get(k, "") or "")
        f["email"].setEnabled(not c)

    def refresh(*_):
        lst.clear()
        for c in cache.contacts_list(search.text().strip(), limit=300):
            it = QListWidgetItem("%s\n%s" % (P.contact_label(c), c["email"]))
            it.setData(ROLE, c)
            lst.addItem(it)

    def picked(item):
        if item is not None:
            fill(item.data(ROLE))

    def do_new():
        lst.clearSelection()
        fill(None)
        f["email"].setFocus()

    def do_save():
        ok = P.contact_save(cfg, cache, f["email"].text(), f["name"].text(), f["phone"].text(), f["org"].text(), f["notes"].text())
        status.setText(tr("Enregistré ✔") if ok else tr("Adresse e-mail invalide."))
        refresh()

    def do_rm():
        e = f["email"].text().strip()
        if e:
            P.contact_remove(cfg, cache, e)
            do_new()
            refresh()

    def do_import():
        path, _ = QFileDialog.getOpenFileName(w, tr("Importer des contacts (vCard)"), "", "vCard (*.vcf)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                n = P.import_vcf(cfg, cache, fh.read())
            status.setText(tr("%d contact(s) importé(s).") % n)
        except OSError as e:
            status.setText(tr("Lecture impossible : %s") % e)
        refresh()

    def do_export():
        path, _ = QFileDialog.getSaveFileName(w, tr("Exporter les contacts"), "contacts-mintmail.vcf", "vCard (*.vcf)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8", newline="") as fh:
                fh.write(P.export_vcf(cache))
            status.setText(tr("Contacts exportés."))
        except OSError as e:
            status.setText(tr("Écriture impossible : %s") % e)
    lst.currentItemChanged.connect(lambda item, _p=None: picked(item))
    search.textChanged.connect(refresh)
    new.clicked.connect(do_new)
    save.clicked.connect(do_save)
    rm.clicked.connect(do_rm)
    write.clicked.connect(lambda: f["email"].text().strip() and main.compose(to=f["email"].text().strip()))
    imp.clicked.connect(do_import)
    exp.clicked.connect(do_export)
    refresh()
    return w
