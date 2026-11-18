"""Réglages → Notifications : qui mérite une alerte (tous, personnes, VIP), par boîte, silence horaire."""
from PySide6.QtCore import QTime
from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel, QPlainTextEdit, QTimeEdit, QWidget

from .. import notifyrules as NR
from ..i18n import tr
from .ui_cards import Page


def notify_tab(win):
    cfg = win.cfg
    s = NR.settings(cfg)
    page = Page(tr("Notifications"), tr("Choisissez ce qui mérite une alerte et un son. Les messages restent toujours dans votre boîte ; seules les alertes sont filtrées."))
    top = page.card(tr("Alertes"))
    mode = QComboBox()
    for key, label in (("all", tr("Tous les nouveaux messages")), ("people", tr("Personnes seulement (ni newsletters ni notifications)")),
                       ("vip", tr("Contacts et VIP seulement")), ("none", tr("Aucune alerte"))):
        mode.addItem(label, key)
    mode.setCurrentIndex(max(0, mode.findData(s["notify_mode"])))
    top.form().addRow(tr("Prévenir pour"), mode)

    boxes = page.card(tr("Boîtes mail"), tr("Décochez une boîte pour ne plus recevoir d'alerte pour elle."))
    checks = {}
    for acct in [x for x in cfg.get("accounts") or [] if x.get("id") and not x.get("demo")]:
        c = QCheckBox("%s  <%s>" % (acct.get("name") or acct["email"], acct["email"]))
        c.setChecked(acct["id"] not in s["notify_off_accounts"])
        checks[acct["id"]] = c
        boxes.addWidget(c)

    vip = page.card(tr("VIP"), tr("Une adresse par ligne. Vos contacts comptent aussi comme VIP dans le mode « Contacts et VIP »."))
    vips = QPlainTextEdit("\n".join(s["vips"]))
    vips.setMinimumHeight(90)
    vip.addWidget(vips)

    quiet = page.card(tr("Silence"), tr("Pas d'alerte ni de son pendant ces heures (le courrier arrive quand même)."))
    on = QCheckBox(tr("Activer le silence horaire"))
    on.setChecked(s["quiet_enabled"])
    quiet.addWidget(on)
    a, b = QTimeEdit(QTime.fromString(s["quiet_from"], "HH:mm")), QTimeEdit(QTime.fromString(s["quiet_to"], "HH:mm"))
    row = QHBoxLayout()
    for w in (QLabel(tr("Début")), a, QLabel(tr("Fin")), b):
        row.addWidget(w)
    row.addStretch(1)
    row.setContentsMargins(0, 0, 0, 0)
    holder = QWidget()
    holder.setLayout(row)
    quiet.addWidget(holder)

    def save(*_):
        off = [i for i, c in checks.items() if not c.isChecked()]
        lines = [x.strip() for x in vips.toPlainText().splitlines() if "@" in x]
        NR.update(cfg, notify_mode=mode.currentData(), notify_off_accounts=off, vips=lines, quiet_enabled=on.isChecked(),
                  quiet_from=a.time().toString("HH:mm"), quiet_to=b.time().toString("HH:mm"))

    mode.currentIndexChanged.connect(save)
    on.toggled.connect(save)
    a.timeChanged.connect(save)
    b.timeChanged.connect(save)
    vips.textChanged.connect(save)
    for c in checks.values():
        c.toggled.connect(save)
    return page.finish()
