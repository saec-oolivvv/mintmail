"""Fenêtre Qt (PySide6) : dossiers · liste des messages · lecteur. Seul module de l'interface Qt qui importe PySide6.
Le travail réseau tourne dans un fil de fond ; l'interface ne touche jamais le réseau."""
import os
import sys
import threading
import time

from PySide6.QtCore import QAbstractListModel, QModelIndex, QObject, QRect, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont
from PySide6.QtWidgets import (QApplication, QLabel, QLineEdit, QListView, QListWidget, QListWidgetItem, QMainWindow,
                               QPushButton, QSplitter, QStyle, QStyledItemDelegate, QTextBrowser, QToolBar, QVBoxLayout, QWidget)

from .. import APP_NAME, __version__
from ..htmlsafe import safe_to_open
from ..i18n import tr
from ..store import Cache, Config
from . import viewmodel as vm

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
        self._busy = False
        self.setWindowTitle("%s %s (Qt)" % (APP_NAME, __version__))
        self.resize(1280, 800)

        self.folders = QListWidget()
        self.folders.setFixedWidth(210)
        for key, label in vm.VIEWS:
            it = QListWidgetItem(label)
            it.setData(Qt.UserRole, key)
            self.folders.addItem(it)
        self.folders.setCurrentRow(0)
        self.folders.currentRowChanged.connect(self._view_changed)

        self.model = MessageModel()
        self.list = QListView()
        self.list.setModel(self.model)
        self.list.setItemDelegate(MessageDelegate())
        self.list.setUniformItemSizes(True)
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
        self.status = QLabel()
        self.statusBar().addWidget(self.status)

        self.bridge = _Bridge()
        self.bridge.done.connect(self._task_done)
        self.timer = QTimer(self)
        self.timer.timeout.connect(lambda: self.sync(quiet=True))
        self.timer.start(60_000)
        self.reload()
        QTimer.singleShot(300, lambda: self.sync(quiet=True))

    # ------------------------------------------------------------ affichage
    def is_dark(self):
        return QApplication.palette().window().color().lightness() < 128

    def reload(self):
        keep = self.current
        msgs = vm.list_view(self.cache, self.view_key, self.account, self.search.text())
        self.model.set_messages(msgs)
        self.empty.setVisible(not msgs)
        self.list.setVisible(bool(msgs))
        if keep:
            r = self.model.row_of(keep)
            if r >= 0:
                self.list.blockSignals(True)
                self.list.setCurrentIndex(self.model.index(r))
                self.list.blockSignals(False)
        self._update_counts()

    def _update_counts(self):
        c = vm.counts(self.cache, self.account)
        for i, (key, label) in enumerate(vm.VIEWS):
            n = c.get(key, 0)
            self.folders.item(i).setText("%s  (%d)" % (label, n) if n and key != "drafts" else label)

    def _view_changed(self, row):
        if row >= 0:
            self.view_key = self.folders.item(row).data(Qt.UserRole)
            self.current = None
            self.reload()
            self._show(None)

    def _row_changed(self, cur, _prev):
        mid = cur.data(IdRole) if cur.isValid() else None
        self.current, self.load_images = mid, False
        self._show(self.engine.open_message(mid) if mid else None)
        if mid:
            self._update_counts()
            self._repaint_row(mid)
            self._background(self.engine.flush)

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
