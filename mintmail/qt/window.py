"""Fenêtre Qt (PySide6) : dossiers · liste des messages · lecteur. Seul module de l'interface Qt qui importe PySide6.
Le travail réseau tourne dans un fil de fond ; l'interface ne touche jamais le réseau."""
import os
import sys
import threading
import time

from PySide6.QtCore import QAbstractListModel, QModelIndex, QObject, QRect, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QDesktopServices, QFont, QKeySequence
from PySide6.QtWidgets import (QApplication, QLabel, QMenu, QMessageBox, QLineEdit, QListView, QListWidget, QListWidgetItem, QMainWindow,
                               QPushButton, QSplitter, QStyle, QStyledItemDelegate, QTextBrowser, QToolBar, QVBoxLayout, QWidget)


from .. import APP_NAME, __version__
from ..htmlsafe import safe_to_open
from ..i18n import tr
from ..store import Cache, Config
from . import composing as C
from . import viewmodel as vm
from .compose_window import ComposeWindow

IdRole = Qt.UserRole + 1
InfoRole = Qt.UserRole + 2


class MessageModel(QAbstractListModel):
    """Liste des messages d'une vue (versions allégées du cache)."""

    def __init__(self):
        super().__init__()
        self.msgs, self.infos = [], []

    def set_messages(self, msgs):
        self.beginResetModel()
        self.msgs = list(msgs)
        self.infos = [vm.row_info(m) for m in self.msgs]
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.msgs)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.msgs):
            return None
        if role == IdRole:
            return self.msgs[index.row()].id
        if role == InfoRole:
            return self.infos[index.row()]
        if role == Qt.DisplayRole:
            i = self.infos[index.row()]
            return "%s — %s" % (i["sender"], i["subject"])
        return None

    def row_of(self, mid):
        return next((r for r, m in enumerate(self.msgs) if m.id == mid), -1)


class MessageDelegate(QStyledItemDelegate):
    """Trois lignes par message : expéditeur + heure, objet, extrait. Gras si non lu."""
    H = 70

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), self.H)

    def paint(self, painter, option, index):
        info = index.data(InfoRole)
        painter.save()
        pal = option.palette
        if option.state & QStyle.State_Selected:
            painter.fillRect(option.rect, pal.highlight())
            fg, sub = pal.highlightedText().color(), pal.highlightedText().color()
        else:
            fg, sub = pal.text().color(), QColor(pal.text().color())
            sub.setAlpha(150)
        r = option.rect.adjusted(14, 8, -12, -6)
        bold = QFont(option.font)
        bold.setBold(bool(info["unread"]))
        painter.setFont(bold)
        painter.setPen(fg)
        mark = ("📌 " if info["pinned"] else "") + ("★ " if info["starred"] else "")
        w = painter.fontMetrics().horizontalAdvance(info["time"]) + 8
        painter.drawText(QRect(r.left(), r.top(), r.width() - w, 20), Qt.AlignLeft | Qt.AlignVCenter,
                         painter.fontMetrics().elidedText(mark + info["sender"], Qt.ElideRight, r.width() - w))
        painter.setPen(sub)
        painter.drawText(QRect(r.right() - w, r.top(), w, 20), Qt.AlignRight | Qt.AlignVCenter, info["time"])
        painter.setFont(bold)
        painter.setPen(fg)
        subj = ("📎 " if info["attachments"] else "") + (info["subject"] or "")
        painter.drawText(QRect(r.left(), r.top() + 21, r.width(), 20), Qt.AlignLeft | Qt.AlignVCenter,
                         painter.fontMetrics().elidedText(subj, Qt.ElideRight, r.width()))
        painter.setFont(option.font)
        painter.setPen(sub)
        painter.drawText(QRect(r.left(), r.top() + 41, r.width(), 20), Qt.AlignLeft | Qt.AlignVCenter,
                         painter.fontMetrics().elidedText(info["snippet"], Qt.ElideRight, r.width()))
        if info["unread"]:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#1a73ff"))
            painter.drawEllipse(option.rect.left() + 4, option.rect.top() + 14, 7, 7)
        painter.restore()


def _make_reader(on_link):
    """Lecteur HTML : QtWebEngine (JavaScript coupé, navigation interdite, liens filtrés) ; QTextBrowser si QtWebEngine manque."""
    if os.environ.get("MINTMAIL_QT_NO_WEBENGINE") != "1":
        try:
            from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
            from PySide6.QtWebEngineWidgets import QWebEngineView

            class SafePage(QWebEnginePage):
                def acceptNavigationRequest(self, url, nav_type, is_main_frame):
                    if nav_type == QWebEnginePage.NavigationTypeTyped or url.scheme() in ("about", "data"):
                        return True                        # chargement du message lui-même
                    on_link(url.toString())                # clic sur un lien : jamais ouvert dans le lecteur
                    return False

            view = QWebEngineView()
            view.setPage(SafePage(view))
            s = view.settings()
            s.setAttribute(QWebEngineSettings.JavascriptEnabled, False)
            s.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, False)
            s.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, False)
            s.setAttribute(QWebEngineSettings.PluginsEnabled, False)
            s.setAttribute(QWebEngineSettings.AllowRunningInsecureContent, False)
            view.show_html = lambda html: view.setHtml(html, QUrl("about:blank"))
            view.kind = "webengine"
            return view
        except Exception:
            pass
    view = QTextBrowser()
    view.setOpenLinks(False)
    view.anchorClicked.connect(lambda u: on_link(u.toString()))
    view.show_html = view.setHtml
    view.kind = "text"
    return view


class _Bridge(QObject):
    done = Signal(object)          # résultat d'une tâche de fond, remis dans le fil de l'interface


class MainWindow(QMainWindow):
    def __init__(self, config=None, cache=None):
        super().__init__()
        self.config, self.cache = config or Config(), cache or Cache()
        self.engine = vm.Engine(self.config, self.cache)
        self.view_key, self.account, self.load_images, self.current = "inbox", "all", False, None
        self._busy, self._kept, self._tick, self._sending, self._composers = False, set(), 0, False, []
        self.setWindowTitle("%s %s (Qt)" % (APP_NAME, __version__))
        self.resize(1280, 800)

        self.folders = QListWidget()
        self.folders.setFixedWidth(210)
        self._build_sidebar()
        self.folders.currentRowChanged.connect(self._view_changed)

        self.model = MessageModel()
        self.list = QListView()
        self.list.setModel(self.model)
        self.list.setItemDelegate(MessageDelegate())
        self.list.setUniformItemSizes(True)
        self.list.setSelectionMode(QListView.ExtendedSelection)
        self.list.selectionModel().currentChanged.connect(self._row_changed)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Rechercher"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _t: self.reload())
        self.empty = QLabel(tr("Aucun message"))
        self.empty.setAlignment(Qt.AlignCenter)
        mid = QWidget()
        lay = QVBoxLayout(mid)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.search)
        lay.addWidget(self.list, 1)
        lay.addWidget(self.empty)

        self.head = QLabel()
        self.head.setTextFormat(Qt.RichText)
        self.head.setWordWrap(True)
        self.head.setContentsMargins(22, 14, 22, 6)
        self.images_btn = QPushButton(tr("Charger les images distantes"))
        self.images_btn.clicked.connect(self._load_images)
        self.images_btn.hide()
        self.reader = _make_reader(self._open_link)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        rl.addWidget(self.head)
        rl.addWidget(self.images_btn)
        rl.addWidget(self.reader, 1)

        split = QSplitter()
        split.addWidget(self.folders)
        split.addWidget(mid)
        split.addWidget(right)
        split.setStretchFactor(1, 2)
        split.setStretchFactor(2, 3)
        split.setSizes([210, 420, 650])
        self.setCentralWidget(split)

        bar = QToolBar()
        bar.setMovable(False)
        self.addToolBar(bar)
        bar.addAction(tr("Synchronisation…").rstrip("…"), self.sync)
        bar.addSeparator()
        self._act(bar, tr("Nouveau message"), "C", lambda: self.compose())
        self._act(bar, tr("Répondre"), "R", lambda: self.reply())
        self._act(bar, tr("Répondre à tous"), "A", lambda: self.reply(True))
        self._act(bar, tr("Transférer"), "F", lambda: self.forward())
        bar.addSeparator()
        self._act(bar, tr("Archiver"), "E", lambda: self.move_selected("archive"))
        self._act(bar, tr("Supprimer"), "Delete", lambda: self.move_selected("trash"))
        self._act(bar, tr("Signaler comme spam"), "!", lambda: self.move_selected("spam"))
        self.notspam_act = self._act(bar, tr("Ce n'est pas du spam (retour en boîte de réception)"), None, lambda: self.move_selected("inbox"))
        self.notspam_act.setVisible(False)
        bar.addSeparator()
        self._act(bar, tr("Favori"), "S", lambda: self.toggle_flag("starred"))
        self._act(bar, tr("Épingler"), "P", lambda: self.toggle_flag("pinned"))
        self._act(bar, tr("Marquer comme non lu"), "U", lambda: self.toggle_flag("unread"))
        self.move_btn = QPushButton(tr("Déplacer vers…"))
        self.move_btn.setShortcut(QKeySequence("V"))
        self.move_btn.clicked.connect(self._move_menu)
        bar.addWidget(self.move_btn)
        self.status = QLabel()
        self.statusBar().addWidget(self.status)
        self.undo_btn = QPushButton()
        self.undo_btn.setFlat(True)
        self.undo_btn.clicked.connect(self._undo_send)
        self.undo_btn.hide()
        self.statusBar().addWidget(self.undo_btn)

        self.bridge = _Bridge()
        self.bridge.done.connect(self._task_done)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._on_timer)
        self.timer.start(60_000)
        self.outbox_timer = QTimer(self)
        self.outbox_timer.timeout.connect(self.process_outbox)
        self.outbox_timer.start(2000)
        self.reload()
        QTimer.singleShot(300, lambda: self.sync(quiet=True))
        QTimer.singleShot(600, self._refresh_folders)

    # ------------------------------------------------------------ affichage
    def is_dark(self):
        return QApplication.palette().window().color().lightness() < 128

    def reload(self):
        keep = self.current
        msgs = vm.list_view(self.cache, self.view_key, self.account, self.search.text())
        if self.view_key == "unread" and self._kept:
            have = {m.id for m in msgs}
            for mid in self._kept - have:                   # « Non lus » : le message ouvert reste affiché jusqu'à ce qu'on passe à un autre
                m = self.cache.get_light(mid)
                if m is not None:
                    msgs.append(m)
            msgs.sort(key=lambda m: m.date, reverse=True)
        self.model.set_messages(msgs)
        self.empty.setVisible(not msgs)
        self.list.setVisible(bool(msgs))
        if keep:
            r = self.model.row_of(keep)
            if r >= 0:
                self.list.blockSignals(True)
                self.list.selectionModel().blockSignals(True)
                self.list.setCurrentIndex(self.model.index(r))
                self.list.selectionModel().blockSignals(False)
                self.list.blockSignals(False)
        self._update_counts()

    def _build_sidebar(self, keep_key=None):
        self.folders.blockSignals(True)
        self.folders.clear()
        for key, label in vm.VIEWS:
            it = QListWidgetItem(label)
            it.setData(Qt.UserRole, key)
            it.setData(Qt.UserRole + 1, label)
            self.folders.addItem(it)
        for dest, label, depth, _aid in self.engine.nav_folders():
            it = QListWidgetItem("    " * min(depth, 3) + label)
            it.setData(Qt.UserRole, dest)
            it.setData(Qt.UserRole + 1, "    " * min(depth, 3) + label)
            self.folders.addItem(it)
        keep_key = keep_key or getattr(self, "view_key", "inbox")
        row = next((i for i in range(self.folders.count()) if self.folders.item(i).data(Qt.UserRole) == keep_key), 0)
        self.folders.setCurrentRow(row)
        self.folders.blockSignals(False)

    def _update_counts(self):
        c = vm.counts(self.cache, self.account)
        for i in range(self.folders.count()):
            it = self.folders.item(i)
            key, label = it.data(Qt.UserRole), it.data(Qt.UserRole + 1)
            n = c.get(key, 0)
            it.setText("%s  (%d)" % (label, n) if n and key != "drafts" else label)
        self.notspam_act.setVisible(self.view_key == "spam")

    def _view_changed(self, row):
        if row >= 0:
            self.view_key = self.folders.item(row).data(Qt.UserRole)
            self.current, self._kept = None, set()
            self.reload()
            self._show(None)

    def _row_changed(self, cur, _prev):
        mid = cur.data(IdRole) if cur.isValid() else None
        old = self.current
        self.current, self.load_images = mid, False
        if old and old != mid and old in self._kept:
            self._kept.discard(old)                          # on est passé à un autre message : l'ancien quitte « Non lus »
            QTimer.singleShot(0, self.reload)
        if mid and self.view_key == "unread":
            m = self.cache.get_light(mid)
            if m is not None and m.unread:
                self._kept.add(mid)
        if mid and self.view_key == "drafts":
            d = self.cache.get(mid)
            if d is not None and d.folder == "drafts":
                self.open_draft(d)
                return
        self._show(self.engine.open_message(mid) if mid else None)
        if mid:
            self._update_counts()
            self._repaint_row(mid)
            self._background(self.engine.flush)

    # ------------------------------------------------------------ actions
    def _act(self, bar, text, shortcut, fn):
        a = QAction(text, self)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        a.triggered.connect(lambda _c=False: fn())
        if bar is not None:
            bar.addAction(a)
        self.addAction(a)
        return a

    def _step(self, d):
        """Message suivant / précédent (J / K)."""
        n = self.model.rowCount()
        if not n:
            return
        r = self.model.row_of(self.current) if self.current else -1
        r = min(n - 1, max(0, r + d)) if r >= 0 else (0 if d > 0 else n - 1)
        self.list.setCurrentIndex(self.model.index(r))

    def selected_msgs(self):
        rows = sorted({i.row() for i in self.list.selectionModel().selectedRows()})
        if not rows and self.current:
            rows = [r for r in [self.model.row_of(self.current)] if r >= 0]
        return [self.model.msgs[r] for r in rows]

    def _after_action(self, msgs, op_ids, tag, extra=None):
        for m in msgs:
            self._kept.discard(m.id)
        self.current = None
        self.list.clearSelection()
        self.list.setCurrentIndex(QModelIndex())
        self._show(None)
        self.reload()
        self._background(lambda: (extra() if extra else self.engine.run_ops(op_ids)), tag)

    def move_selected(self, dest):
        msgs = self.selected_msgs()
        if not msgs:
            return
        if dest == "trash" and all(m.folder == "trash" for m in msgs):
            ok = QMessageBox.question(self, APP_NAME, tr("Supprimer définitivement %d message(s) ?") % len(msgs)) == QMessageBox.Yes
            if ok:
                op_ids = self.engine.delete_forever(msgs)
                self._after_action(msgs, op_ids, "ops")
            return
        op_ids = self.engine.move(msgs, dest)
        self._after_action(msgs, op_ids, "move", lambda: self.engine.finish_move(msgs, dest, op_ids))

    def toggle_flag(self, field):
        msgs = self.selected_msgs()
        if not msgs:
            return
        value = not getattr(msgs[0], field)                  # l'état du premier message décide pour tous
        op_ids = self.engine.set_flag(msgs, field, value)
        if field == "unread" and value:
            self._kept.discard(msgs[0].id)
        for m in msgs:
            setattr(m, field, value)
        self.reload()
        self._background(lambda: self.engine.run_ops(op_ids), "ops")

    def _move_menu(self):
        msgs = self.selected_msgs()
        if not msgs:
            return
        menu = QMenu(self)
        for dest, label in self.engine.move_targets(msgs[0].account):
            menu.addAction(label, lambda d=dest: self.move_selected(d))
        menu.exec(self.move_btn.mapToGlobal(self.move_btn.rect().bottomLeft()))

    # ------------------------------------------------------------ rédaction
    def compose(self, **kw):
        kw.setdefault("account_id", self.engine.default_account(None, self.account))
        w = ComposeWindow(self, **kw)
        self._composers.append(w)
        w.destroyed.connect(lambda _o=None, w=w: self._composers.remove(w) if w in self._composers else None)
        return w

    def _open_msg(self):
        """Message complet affiché dans le lecteur, ou celui qui est sélectionné dans la liste."""
        m = getattr(self, "shown", None)
        if m is None:
            sel = self.selected_msgs()
            m = self.cache.get(sel[0].id) if sel else None
        return m

    def reply(self, all_=False):
        m = self._open_msg()
        if m:
            self.compose(**C.reply_args(self.config, self.engine.accounts(), m, all_, self.engine.default_account(m, self.account)))

    def forward(self):
        m = self._open_msg()
        if m:
            self.compose(**C.forward_args(m, self.engine.default_account(m, self.account)))

    def open_draft(self, msg):
        self.compose(**C.draft_args(msg))

    def snooze_tomorrow(self):
        msgs = self.selected_msgs()
        if msgs:
            self.engine.snooze(msgs, C.at(1, 8))
            self._after_action(msgs, [], "ops", lambda: ([], [], False))

    # ------------------------------------------------------------ envoi
    def queue_send(self, out, delay=0, scheduled=False):
        oid = self.engine.queue_send(out, delay, scheduled)
        if scheduled:
            self.status.setText(tr("Envoi programmé pour le %s") % __import__("mintmail.util", fromlist=["format_full"]).format_full(time.time() + delay))
            return
        self._undo = oid
        self.undo_btn.setText(tr("Annuler"))
        self.undo_btn.show()
        self.status.setText(tr("Envoi du message…"))
        QTimer.singleShot(max(2, int(self.config["undo_seconds"])) * 1000, self._hide_undo)

    def _hide_undo(self):
        self.undo_btn.hide()
        self._undo = None

    def _undo_send(self):
        oid, self._undo = getattr(self, "_undo", None), None
        self.undo_btn.hide()
        out = self.engine.undo_send(oid) if oid else None
        if out is not None:
            self.compose(account_id=out.account, to=out.to, cc=out.cc, subject=out.subject, body_html=out.html, raw=True,
                         in_reply_to=out.in_reply_to, references=out.references, attachments=out.attachments)
            self.status.setText("")

    def process_outbox(self):
        if self._sending or not self.cache.outbox_due():
            return
        self._sending = True
        self._background(self.engine.process_outbox, "outbox")

    # ------------------------------------------------------------ dossiers
    def _refresh_folders(self):
        self._background(self.engine.refresh_folders, "folders")

    def _on_timer(self):
        self._tick += 1
        self.sync(quiet=True)
        if self._tick % 5 == 0:
            self._refresh_folders()

    def _repaint_row(self, mid):
        r = self.model.row_of(mid)
        if r >= 0:
            self.model.infos[r]["unread"] = False
            self.model.dataChanged.emit(self.model.index(r), self.model.index(r))

    def _show(self, msg):
        self.shown = msg
        if msg is None:
            self.head.setText("")
            self.images_btn.hide()
            self.reader.show_html("<html><body></body></html>")
            return
        h = vm.header_lines(msg)
        esc = lambda s: (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        self.head.setText("<b style='font-size:15px'>%s</b><br><span style='color:gray'>%s · %s<br>%s</span>"
                          % (esc(h["subject"]), esc(h["from"]), esc(h["date"]), esc(h["to"])))
        from ..util import has_remote_content
        self.images_btn.setVisible(bool(msg.html) and has_remote_content(msg.html) and not self.load_images)
        self.reader.show_html(vm.render_html(msg, self.load_images, self.is_dark()))

    def _load_images(self):
        self.load_images = True
        if getattr(self, "shown", None) is not None:
            self._show(self.shown)

    def _open_link(self, url):
        safe = safe_to_open(url)
        if safe:
            QDesktopServices.openUrl(QUrl(safe))

    # ------------------------------------------------------------ réseau (fil de fond)
    def _background(self, fn, tag=None):
        def work():
            try:
                res = (fn(), None)
            except Exception as e:                            # jamais d'exception dans le fil de fond
                res = (None, e)
            self.bridge.done.emit((tag, res))
        threading.Thread(target=work, daemon=True).start()

    def sync(self, quiet=False):
        if self._busy:
            return
        self._busy = True
        if not quiet:
            self.status.setText(tr("Synchronisation…"))
        self._background(lambda: (self.engine.flush(), self.engine.sync()), "sync")

    def _task_done(self, payload):
        tag, (res, err) = payload
        if tag == "outbox":
            self._sending = False
            for kind, out, e in (res or []):
                if kind == "sent":
                    self.status.setText(tr("Message envoyé ✔"))
                elif kind == "retry":
                    self.status.setText(tr("Hors ligne : message conservé, nouvel essai automatique."))
                else:
                    self.status.setText(tr("Échec de l'envoi : %s") % str(e)[:90])
                    self.compose(account_id=out.account, to=out.to, cc=out.cc, subject=out.subject, body_html=out.html, raw=True,
                                 attachments=out.attachments)
            if err:
                self.status.setText("⚠ " + str(err)[:120])
            self.reload()
            return
        if tag == "folders":
            if res:
                self._build_sidebar(self.view_key)
            return
        if tag in ("move", "ops"):
            errs = [str(err)] if err else (list(res[0]) if tag == "move" and res else list(res[1]) if res else [])
            if errs:
                self.status.setText("⚠ " + errs[0][:120])
            self.reload()
            return
        if tag != "sync":
            return
        self._busy = False
        errors = [str(err)] if err else list(res[1][1])
        self.status.setText(("⚠ " + errors[0][:120]) if errors else tr("Synchronisé à ") + time.strftime("%H:%M"))
        self.reload()


def run(argv=None):
    app = QApplication.instance() or QApplication(list(argv if argv is not None else sys.argv))
    app.setApplicationName(APP_NAME)
    win = MainWindow()
    win.show()
    return app.exec()
