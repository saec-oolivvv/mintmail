"""Réglages → Absence : absence du bureau ou vacances en quelques clics, appliquée à une ou plusieurs boîtes mail (chacune avec SA signature)."""
import datetime

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QCheckBox, QComboBox, QDateEdit, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QSpinBox, QWidget

from .. import absence as AB
from ..i18n import tr
from . import ui_sieve
from .ui_cards import Page


def _qdate(iso):
    d = AB.parse_date(iso)
    return QDate(d.year, d.month, d.day) if d else QDate.currentDate()


def absence_tab(win):
    cfg = win.cfg
    a = AB.settings(cfg)
    page = Page(tr("Absence"), tr("Absence du bureau ou vacances : MintMail répond automatiquement aux personnes qui vous écrivent, une seule fois chacune, "
                                  "avec la signature de la boîte qui a reçu le message. MintMail doit rester ouvert (même réduit) pour envoyer les réponses."))
    top = page.card(tr("Absence"))
    on = QCheckBox(tr("Activer la réponse automatique"))
    on.setChecked(a["enabled"])
    top.addWidget(on)
    status = QLabel()
    status.setObjectName("dim")
    status.setWordWrap(True)
    top.addWidget(status)
    form = top.form()
    kind = QComboBox()
    kind.addItem(tr("Absence du bureau"), "office")
    kind.addItem(tr("Vacances"), "vacation")
    kind.setCurrentIndex(max(0, kind.findData(a["kind"])))
    form.addRow(tr("Type"), kind)
    start, end = QDateEdit(), QDateEdit()
    for w in (start, end):
        w.setCalendarPopup(True)
        w.setDisplayFormat("dd/MM/yyyy")
    start.setDate(_qdate(a["start"]))
    end.setDate(_qdate(a["end"] or a["start"]))
    days = QSpinBox()
    days.setRange(1, 365)
    days.setSuffix(tr(" jour(s)"))
    row = QHBoxLayout()
    for w in (QLabel(tr("Début")), start, QLabel(tr("Fin")), end, days):
        row.addWidget(w)
    row.addStretch(1)
    holder = QWidget()
    holder.setLayout(row)
    row.setContentsMargins(0, 0, 0, 0)
    form.addRow(tr("Période"), holder)

    boxes = page.card(tr("Boîtes mail concernées"), tr("Le même message est envoyé depuis chaque boîte cochée, avec sa propre signature."))
    real = [x for x in cfg.get("accounts") or [] if x.get("id") and not x.get("demo")]
    checks = {}
    for acct in real:
        c = QCheckBox("%s  <%s>" % (acct.get("name") or acct["email"], acct["email"]))
        c.setChecked(not a["accounts"] or acct["id"] in a["accounts"])
        checks[acct["id"]] = c
        boxes.addWidget(c)
    if not real:
        boxes.addWidget(QLabel(tr("Ajoutez d'abord une boîte mail (Réglages → Comptes).")))
    sigs = QLabel()
    sigs.setObjectName("dim")
    sigs.setWordWrap(True)
    boxes.addWidget(sigs)

    msg = page.card(tr("Message"), tr("Variables : {debut} {fin} {retour} {jours}. Laissez vide pour le message proposé."))
    mform = msg.form()
    subject = QLineEdit(a["subject"])
    subject.setPlaceholderText(AB.default_subject(a["kind"]))
    body = QPlainTextEdit(a["body"])
    body.setPlaceholderText(AB.default_body(a["kind"]))
    body.setMinimumHeight(150)
    mform.addRow(tr("Objet"), subject)
    mform.addRow(tr("Texte"), body)
    known = QCheckBox(tr("Répondre seulement à mes contacts"))
    known.setChecked(a["known_only"])
    msg.addWidget(known)
    preview = QLabel()
    preview.setWordWrap(True)
    preview.setObjectName("dim")
    msg.addWidget(preview)
    clear = QPushButton(tr("Désactiver maintenant"))
    clear.clicked.connect(lambda: on.setChecked(False))
    top.addWidget(clear)
    srv = page.card(tr("Aussi sur le serveur"), tr("Si votre serveur propose Sieve, la réponse d'absence part même quand MintMail est fermé. Gmail, Microsoft, iCloud et Yahoo n'ont pas Sieve : MintMail doit y rester ouvert."))
    push = QPushButton(tr("Envoyer au serveur (Sieve)"))
    push.clicked.connect(lambda: ui_sieve.push_to_server(win))
    srv.addWidget(push)
    busy = [False]

    def chosen():
        ids = [i for i, c in checks.items() if c.isChecked()]
        return [] if len(ids) == len(checks) else ids                # toutes cochées = toutes (y compris les futures boîtes)

    def refresh():
        cur = AB.settings(cfg)
        st = AB.state(cur)
        n = AB.days_count(cur)
        status.setText({"off": tr("Désactivée."), "soon": tr("Programmée du %s au %s.") % (start.text(), end.text()),
                        "active": tr("🌴 Active jusqu'au %s inclus (%d jour(s)).") % (end.text(), n), "over": tr("Terminée.")}[st])
        who = AB.targets(cur, cfg.get("accounts") or [])
        sigs.setText("\n".join("%s : %s" % (x["email"], tr("signature de la boîte") if (x.get("signature_html") or "").strip() else tr("sans signature")) for x in who))
        preview.setText(tr("Aperçu :") + "\n" + AB.subject_of(cur) + "\n\n" + AB.body_of(cur))

    def save(*_):
        if busy[0]:
            return
        d1, d2 = start.date().toPython(), end.date().toPython()
        AB.update(cfg, enabled=on.isChecked(), kind=kind.currentData(), start=d1.isoformat(), end=d2.isoformat(), accounts=chosen(),
                  subject=subject.text().strip(), body=body.toPlainText().strip(), known_only=known.isChecked())
        refresh()

    def set_end_from_days(n):
        if busy[0]:
            return
        busy[0] = True
        end.setDate(start.date().addDays(n - 1))
        busy[0] = False
        save()

    def dates_changed(*_):
        if busy[0]:
            return
        if end.date() < start.date():
            busy[0] = True
            end.setDate(start.date())
            busy[0] = False
        busy[0] = True
        days.setValue(start.date().daysTo(end.date()) + 1)
        busy[0] = False
        save()

    def kind_changed(*_):
        subject.setPlaceholderText(AB.default_subject(kind.currentData()))
        body.setPlaceholderText(AB.default_body(kind.currentData()))
        save()

    if not a["start"]:                                              # première ouverture : aujourd'hui, une semaine
        s0, e0 = AB.starting_today(7)
        start.setDate(_qdate(s0))
        end.setDate(_qdate(e0))
    days.setValue(start.date().daysTo(end.date()) + 1)
    on.toggled.connect(save)
    kind.currentIndexChanged.connect(kind_changed)
    start.dateChanged.connect(dates_changed)
    end.dateChanged.connect(dates_changed)
    days.valueChanged.connect(set_end_from_days)
    for c in checks.values():
        c.toggled.connect(save)
    subject.textChanged.connect(save)
    body.textChanged.connect(save)
    known.toggled.connect(save)
    refresh()
    return page.finish()
