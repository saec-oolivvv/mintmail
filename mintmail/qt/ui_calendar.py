"""Onglet « Agenda » des réglages Qt : Google Agenda et CalDAV. Logique : calendars.py (testée sans Qt)."""
import threading

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget)

from ..i18n import tr
from . import calendars as CA


class _Sig(QObject):
    google = Signal(bool, str)
    caldav = Signal(bool, str)
    url = Signal(str)
    auth_done = Signal(bool, str)


def calendar_tab(dlg):
    cfg = dlg.cfg
    page = QWidget()
    lay = QVBoxLayout(page)
    sig = _Sig()
    sig.url.connect(lambda u: QDesktopServices.openUrl(QUrl(u)))
    lay.addWidget(QLabel(tr("<b>Google Agenda</b> — avec votre compte Gmail connecté en OAuth")))
    form = QFormLayout()
    lay.addLayout(form)
    accs, chosen, on_ = CA.google_state(cfg)
    combo = QComboBox()
    for a in accs:
        combo.addItem(a["email"], a["id"])
    combo.setCurrentIndex(max(0, combo.findData(chosen)))
    use = QCheckBox(tr("Utiliser Google Agenda"))
    use.setChecked(on_)
    form.addRow(tr("Compte Gmail"), combo)
    form.addRow("", use)
    gstatus = QLabel()
    gstatus.setWordWrap(True)
    gstatus.setTextInteractionFlags(Qt.TextSelectableByMouse)
    auth, test = QPushButton(tr("🔑 Autoriser Google Agenda")), QPushButton(tr("Tester (7 prochains jours)"))
    row = QHBoxLayout()
    row.addWidget(auth)
    row.addWidget(test)
    row.addStretch(1)
    form.addRow("", row)
    form.addRow("", gstatus)
    help1 = QLabel(CA.GOOGLE_HELP)
    help1.setWordWrap(True)
    help1.setEnabled(False)
    lay.addWidget(help1)

    def say(label, text, error=False):
        label.setText("<span style='color:%s'>%s</span>" % ("#dc2626" if error else "#16a34a", text.replace("<", "&lt;")))

    def account():
        return next((a for a in accs if a["id"] == combo.currentData()), None)

    def save(*_):
        CA.google_save(cfg, combo.currentData(), use.isChecked())
    use.toggled.connect(save)
    combo.currentIndexChanged.connect(save)

    def do_auth():
        acc = account()
        if not acc:
            say(gstatus, tr("Ajoutez d'abord un compte Gmail avec le fournisseur « OAuth » (Paramètres → Comptes)."), True)
            return
        say(gstatus, tr("Autorisation dans le navigateur… (3 minutes maximum)"), False)
        auth.setEnabled(False)

        def work():
            ok, msg = CA.google_authorize(cfg, acc, lambda u: sig.url.emit(u))
            sig.auth_done.emit(ok, msg)
        threading.Thread(target=work, daemon=True).start()

    def auth_done(ok, msg):
        auth.setEnabled(True)
        if ok:
            use.blockSignals(True)
            use.setChecked(True)
            use.blockSignals(False)
        say(gstatus, msg, not ok)
    sig.auth_done.connect(auth_done)

    def do_test():
        say(gstatus, tr("Test…"))
        acc = account()
        threading.Thread(target=lambda: sig.google.emit(*CA.google_test(cfg, acc)), daemon=True).start()
    sig.google.connect(lambda ok, msg: say(gstatus, msg, not ok))
    auth.clicked.connect(do_auth)
    test.clicked.connect(do_test)

    lay.addWidget(QLabel(tr("   <b>Autre calendrier : CalDAV</b> (Nextcloud, Radicale, Fastmail, iCloud…) — utilisé si Google Agenda est désactivé")))
    f2 = QFormLayout()
    lay.addLayout(f2)
    url_, user_, has_pw = CA.caldav_state(cfg)
    url, user, pw = QLineEdit(url_), QLineEdit(user_), QLineEdit()
    pw.setEchoMode(QLineEdit.Password)
    pw.setPlaceholderText(tr("Enregistré — laisser vide pour le conserver") if has_pw else tr("Mot de passe (ou mot de passe d'application)"))
    url.setPlaceholderText("https://cloud.exemple.be/remote.php/dav/calendars/moi/personnel/")
    f2.addRow(tr("Adresse du calendrier"), url)
    f2.addRow(tr("Identifiant"), user)
    f2.addRow(tr("Mot de passe"), pw)
    cstatus = QLabel()
    cstatus.setWordWrap(True)
    ctest, csave, cclear = QPushButton(tr("Tester")), QPushButton(tr("Enregistrer")), QPushButton(tr("Désactiver"))
    crow = QHBoxLayout()
    for b in (ctest, csave, cclear):
        crow.addWidget(b)
    crow.addStretch(1)
    f2.addRow("", crow)
    f2.addRow("", cstatus)
    help2 = QLabel(CA.CALDAV_HELP)
    help2.setWordWrap(True)
    help2.setEnabled(False)
    lay.addWidget(help2)
    lay.addStretch(1)
    sig.caldav.connect(lambda ok, msg: cstatus.setText(msg))

    def c_test():
        cstatus.setText(tr("Test…"))
        u, us, p = url.text(), user.text(), pw.text()
        threading.Thread(target=lambda: sig.caldav.emit(*CA.caldav_test(cfg, u, us, p)), daemon=True).start()

    def c_save():
        ok, msg = CA.caldav_save(cfg, url.text(), user.text(), pw.text())
        if ok:
            pw.clear()
        cstatus.setText(msg)

    def c_clear():
        cstatus.setText(CA.caldav_clear(cfg))
        url.clear()
        user.clear()
    ctest.clicked.connect(c_test)
    csave.clicked.connect(c_save)
    cclear.clicked.connect(c_clear)
    sc = QScrollArea()
    sc.setWidgetResizable(True)
    sc.setWidget(page)
    return sc
