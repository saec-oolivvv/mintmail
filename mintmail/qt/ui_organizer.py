"""Widgets Qt de l'organisation : extras du lecteur (conversation, invitation, pièces jointes, désabonnement) et dialogues
Aujourd'hui, Agenda, Nouvel événement, Ajouter une tâche, aperçu de pièce jointe. La logique est dans organizer.py (testée sans Qt)."""
import datetime

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QGuiApplication, QIcon, QPixmap
from PySide6.QtWidgets import (QCheckBox, QDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu, QPlainTextEdit, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from ..i18n import tr
from . import organizer as O

KIND_ICON = {"image": "🖼", "text": "📄", "pdf": "📕", "archive": "🗜", "file": "📎"}


def _clear(layout):
    while layout.count():
        it = layout.takeAt(0)
        if it.widget():
            it.widget().deleteLater()
        elif it.layout():
            _clear(it.layout())


def _label(text="", dim=False, wrap=True):
    lab = QLabel(text)
    lab.setWordWrap(wrap)
    lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
    if dim:
        lab.setEnabled(False)
    return lab


class MessageExtras(QFrame):
    """Bandeau entre l'en-tête et le corps du message : conversation, invitation, pièces jointes, désabonnement."""
    attachment = Signal(object, str)          # pièce jointe, action : open | preview | save | copy
    save_all = Signal()
    unsubscribe = Signal()
    invite = Signal(str)                      # accept | tentative | decline | add | slots
    open_message = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("extras")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 6, 22, 6)
        lay.setSpacing(6)
        self.thread_box = QVBoxLayout()
        self.thread_box.setSpacing(0)
        lay.addLayout(self.thread_box)
        self.invite_card = QFrame()
        self.invite_card.setObjectName("invitecard")
        il = QVBoxLayout(self.invite_card)
        self.inv_title, self.inv_when, self.inv_note = _label(), _label(dim=True), _label()
        il.addWidget(self.inv_title)
        il.addWidget(self.inv_when)
        il.addWidget(self.inv_note)
        self.inv_btns = QHBoxLayout()
        il.addLayout(self.inv_btns)
        lay.addWidget(self.invite_card)
        self.att_scroll = QScrollArea()
        self.att_scroll.setWidgetResizable(True)
        self.att_scroll.setFrameShape(QFrame.NoFrame)
        self.att_scroll.setFixedHeight(62)
        self.att_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        self.att_row = QHBoxLayout(inner)
        self.att_row.setContentsMargins(0, 0, 0, 0)
        self.att_scroll.setWidget(inner)
        lay.addWidget(self.att_scroll)
        self.unsub_btn = QPushButton(tr("Désabonner"))
        self.unsub_btn.setObjectName("chip")
        self.unsub_btn.clicked.connect(self.unsubscribe.emit)
        row = QHBoxLayout()
        row.addWidget(self.unsub_btn)
        row.addStretch(1)
        lay.addLayout(row)
        self.hide()

    # -- remplissage
    def set_message(self, msg, thread, can_unsubscribe, invite, chips, total):
        self._thread(thread)
        self._invite(invite)
        self._attachments(chips, total, msg)
        self.unsub_btn.setVisible(bool(can_unsubscribe))
        self.setVisible(bool(thread) or bool(invite) or bool(chips) or bool(can_unsubscribe))

    def clear(self):
        self.set_message(None, [], False, None, [], "")

    def set_invite_note(self, text):
        self.inv_note.setText(text)
        self.inv_note.setVisible(bool(text))

    def _thread(self, rows):
        _clear(self.thread_box)
        if not rows:
            return
        self.thread_box.addWidget(_label("<b>" + tr("💬 Conversation (%d messages)") % len(rows) + "</b>", wrap=False))
        for r in rows[-8:]:
            b = QPushButton("%s%s · %s — %s" % ("● " if r["unread"] else "", r["who"], r["date"], r["snippet"]))
            b.setFlat(True)
            b.setStyleSheet("text-align:left;padding:3px 6px;%s" % ("font-weight:bold;" if r["current"] or r["unread"] else ""))
            b.setEnabled(not r["current"])
            b.clicked.connect(lambda _c=False, mid=r["id"]: self.open_message.emit(mid))
            self.thread_box.addWidget(b)

    def _invite(self, inv):
        _clear(self.inv_btns)
        self.invite_card.setVisible(bool(inv))
        if not inv:
            return
        self.inv_title.setText("<b>%s</b>%s" % (("📅 " + (inv["title"] or tr("Invitation")))[:120], tr("  — ANNULÉ") if inv["cancelled"] else ""))
        self.inv_when.setText("%s %s%s" % (inv["start"].replace("T", " "), ("→ " + inv["end"].replace("T", " ")) if inv["end"] else "",
                                           ("   📍 " + inv["where"]) if inv["where"] else ""))
        self.set_invite_note("")
        if inv["can_reply"] and not inv["cancelled"]:
            for key, text in (("accept", tr("✔ Accepter")), ("tentative", tr("Peut-être")), ("decline", tr("✖ Refuser"))):
                b = QPushButton(text)
                b.clicked.connect(lambda _c=False, k=key: self.invite.emit(k))
                self.inv_btns.addWidget(b)
        if inv["can_add"]:
            b = QPushButton(tr("Ajouter à l'agenda"))
            b.clicked.connect(lambda: self.invite.emit("add"))
            self.inv_btns.addWidget(b)
        self.inv_btns.addStretch(1)

    def _attachments(self, chips, total, msg):
        _clear(self.att_row)
        self.att_scroll.setVisible(bool(chips))
        for c in chips:
            b = QPushButton()
            b.setObjectName("chip")
            label = "%s %s\n%s" % (KIND_ICON.get(c["kind"], "📎"), c["name"][:36], c["size"])
            b.setText(label)
            if c["kind"] == "image" and c["exists"]:
                pm = QPixmap(c["att"]["path"])
                if not pm.isNull():
                    b.setIcon(QIcon(pm.scaled(36, 36, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
                    b.setText("%s\n%s" % (c["name"][:36], c["size"]))
            if c["risk"] != "ok":
                b.setToolTip(tr("Fichier à risque : MintMail demande confirmation ou refuse de l'ouvrir."))
            else:
                b.setToolTip(tr("Cliquer pour ouvrir · clic droit : enregistrer, copier le chemin · glisser vers un dossier"))
            b.setEnabled(c["exists"])
            b.clicked.connect(lambda _c=False, a=c["att"]: self.attachment.emit(a, "open"))
            b.setContextMenuPolicy(Qt.CustomContextMenu)
            b.customContextMenuRequested.connect(lambda pos, a=c["att"], w=b: self._menu(w, pos, a))
            self.att_row.addWidget(b)
        if len(chips) > 1:
            allb = QPushButton(tr("⬇ Tout enregistrer (%s)") % total)
            allb.setObjectName("chip")
            allb.clicked.connect(self.save_all.emit)
            self.att_row.addWidget(allb)
        self.att_row.addStretch(1)

    def _menu(self, w, pos, a):
        m = QMenu(w)
        for text, act in ((tr("Ouvrir"), "open"), (tr("Aperçu"), "preview"), (tr("Enregistrer sous…"), "save"), (tr("Copier le chemin"), "copy")):
            m.addAction(text, lambda act=act: self.attachment.emit(a, act))
        m.exec(w.mapToGlobal(pos))


class AttachmentPreview(QDialog):
    """Aperçu intégré d'une image ou d'un texte."""
    open_with = Signal()

    def __init__(self, parent, att, kind):
        super().__init__(parent)
        self.setWindowTitle(att["filename"])
        self.resize(820, 620)
        lay = QVBoxLayout(self)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        try:
            if kind == "image":
                pm = QPixmap(att["path"])
                if pm.isNull():
                    raise OSError("image")
                lab = QLabel()
                lab.setPixmap(pm.scaled(1600, 1600, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                lab.setAlignment(Qt.AlignCenter)
                sc.setWidget(lab)
            else:
                te = QPlainTextEdit(O.read_text_preview(att))
                te.setReadOnly(True)
                sc.setWidget(te)
        except OSError:
            sc.setWidget(QLabel(tr("Aperçu impossible : ouvrez le fichier avec « Ouvrir ».")))
        lay.addWidget(sc, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        ow, close = QPushButton(tr("Ouvrir avec…")), QPushButton(tr("Fermer"))
        ow.clicked.connect(lambda: (self.open_with.emit(), self.accept()))
        close.clicked.connect(self.accept)
        row.addWidget(ow)
        row.addWidget(close)
        lay.addLayout(row)


class TaskDialog(QDialog):
    def __init__(self, parent, msg=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Ajouter une tâche"))
        self.resize(560, 140)
        form = QFormLayout(self)
        self.text, self.due = QLineEdit(), QLineEdit()
        if msg is not None:
            self.text.setText(O.task_default_text(msg))
        self.due.setPlaceholderText(tr("facultatif : vendredi, 15/11, dans 3 jours… (sinon lue dans le texte)"))
        form.addRow(tr("Tâche"), self.text)
        form.addRow(tr("Échéance"), self.due)
        row = QHBoxLayout()
        cancel, ok = QPushButton(tr("Annuler")), QPushButton(tr("Ajouter"))
        ok.setDefault(True)
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self.accept)
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(ok)
        form.addRow(row)


class EventDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle(tr("Nouvel événement"))
        self.resize(420, 220)
        form = QFormLayout(self)
        now = datetime.datetime.now() + datetime.timedelta(hours=1)
        self.f = {k: QLineEdit() for k in ("title", "date", "time", "dur", "place")}
        self.f["date"].setText(now.strftime("%Y-%m-%d"))
        self.f["time"].setText(now.strftime("%H:00"))
        self.f["dur"].setText("60")
        for k, lab in (("title", tr("Titre")), ("date", tr("Date (AAAA-MM-JJ)")), ("time", tr("Heure (HH:MM)")), ("dur", tr("Durée (minutes)")), ("place", tr("Lieu"))):
            form.addRow(lab, self.f[k])
        row = QHBoxLayout()
        cancel, ok = QPushButton(tr("Annuler")), QPushButton(tr("Ajouter"))
        ok.setDefault(True)
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self.accept)
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(ok)
        form.addRow(row)

    def event(self):
        v = {k: w.text() for k, w in self.f.items()}
        return O.new_event(v["title"], v["date"], v["time"], v["dur"], v["place"])


class AgendaDialog(QDialog):
    new_event = Signal()

    def __init__(self, parent, res):
        super().__init__(parent)
        self.setWindowTitle(tr("Agenda — 14 prochains jours"))
        self.resize(540, 480)
        lay = QVBoxLayout(self)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        inner = QWidget()
        il = QVBoxLayout(inner)
        day = None
        for d, text in O.agenda_text(res):
            if d and d != day:
                day = d
                il.addWidget(_label("<b>%s</b>" % d.capitalize(), wrap=False))
            il.addWidget(_label(text))
        il.addStretch(1)
        sc.setWidget(inner)
        lay.addWidget(sc, 1)
        row = QHBoxLayout()
        new, close = QPushButton(tr("Nouvel événement…")), QPushButton(tr("Fermer"))
        new.clicked.connect(lambda: (self.new_event.emit(), self.accept()))
        close.clicked.connect(self.accept)
        row.addWidget(new)
        row.addStretch(1)
        row.addWidget(close)
        lay.addLayout(row)


class TodayDialog(QDialog):
    """Page « Aujourd'hui » : agenda, messages importants, tâches, relances, brouillons préparés."""
    chosen = Signal(object)

    def __init__(self, main, agenda):
        super().__init__(main)
        self.main, self.engine, self.agenda = main, main.engine, agenda
        self.setWindowTitle(tr("Aujourd'hui — %s") % datetime.date.today().strftime("%d/%m/%Y"))
        self.resize(640, 680)
        outer = QVBoxLayout(self)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        self.body = QWidget()
        self.lay = QVBoxLayout(self.body)
        sc.setWidget(self.body)
        outer.addWidget(sc, 1)
        row = QHBoxLayout()
        close = QPushButton(tr("Fermer"))
        close.clicked.connect(self.accept)
        row.addStretch(1)
        row.addWidget(close)
        outer.addLayout(row)
        self.fill()

    def _head(self, text):
        self.lay.addSpacing(8)
        self.lay.addWidget(_label("<b>%s</b>" % text, wrap=False))

    def _msg_button(self, m, prefix=""):
        b = QPushButton(("%s%s — %s" % (prefix, m.display_sender, m.subject))[:110])
        b.setFlat(True)
        b.setStyleSheet("text-align:left;padding:4px 6px")
        b.clicked.connect(lambda _c=False: (self.chosen.emit(m), self.accept()))
        self.lay.addWidget(b)

    def fill(self):
        _clear(self.lay)
        cfg = self.engine.config
        data = O.today_local(self.engine)
        self._head(tr("📅 Agenda du jour"))
        for _d, text in O.agenda_text(self.agenda, empty=tr("Aucun rendez-vous aujourd'hui.")):
            self.lay.addWidget(_label(text, dim=self.agenda is None or not self.agenda[0] or not self.agenda[1]))
        self._head(tr("⚡ À traiter en priorité (non lus, jugés importants)"))
        if data["important"]:
            for m in data["important"]:
                self._msg_button(m)
        else:
            self.lay.addWidget(_label(tr("Rien d'urgent détecté.") + ("" if self.main.ai_enabled() else tr(" (L'IA n'est pas activée : le tri se limite à des indices simples.)")), dim=True))
        self._head(tr("☑ Tâches"))
        if data["tasks"]:
            for t in data["tasks"]:
                row = QHBoxLayout()
                text, due, late = O.task_row(t)
                cb = QCheckBox(text)
                cb.toggled.connect(lambda on, tid=t["id"]: (O.task_set_done(cfg, tid, on), self.fill()))
                row.addWidget(cb, 1)
                if due:
                    lab = QLabel("<span style='color:%s'>%s</span>" % ("#dc2626" if late else "#888888", due))
                    row.addWidget(lab)
                if t.get("msg") and self.engine.cache.get(t["msg"]):
                    ob = QPushButton("✉")
                    ob.setFlat(True)
                    ob.setToolTip(tr("Ouvrir le message d'origine"))
                    ob.clicked.connect(lambda _c=False, mid=t["msg"]: (self.chosen.emit(self.engine.cache.get(mid)), self.accept()))
                    row.addWidget(ob)
                self.lay.addLayout(row)
        else:
            self.lay.addWidget(_label(tr("Aucune tâche ouverte."), dim=True))
        add = QHBoxLayout()
        entry = QLineEdit()
        entry.setPlaceholderText(tr("Nouvelle tâche (ex. « envoyer le devis avant vendredi »)"))

        def do_add():
            if entry.text().strip():
                O.task_add(cfg, entry.text())
                self.fill()
        entry.returnPressed.connect(do_add)
        btn = QPushButton(tr("Ajouter"))
        btn.clicked.connect(do_add)
        add.addWidget(entry, 1)
        add.addWidget(btn)
        self.lay.addLayout(add)
        self._head(tr("⏳ En attente de réponse"))
        if data["followups"]:
            for f in data["followups"][:8]:
                self.lay.addWidget(_label(O.followup_line(f)))
        else:
            self.lay.addWidget(_label(tr("Aucune relance programmée."), dim=True))
        if data["drafts"]:
            self._head(tr("✨ Brouillons de réponse préparés (à relire avant envoi)"))
            for m in data["drafts"]:
                self._msg_button(m, "Re : ")
        self.lay.addStretch(1)
