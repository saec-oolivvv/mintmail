"""Fenêtre Qt (PySide6) : dossiers · liste des messages · lecteur. Module principal de l'interface Qt.
Le travail réseau tourne dans un fil de fond ; l'interface ne touche jamais le réseau."""
import os
import sys
import threading
import time

from PySide6.QtCore import QAbstractListModel, QModelIndex, QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit, QListView, QListWidget, QListWidgetItem, QMainWindow, QMenu,
                               QInputDialog, QMessageBox, QPushButton, QSplitter, QTextBrowser, QVBoxLayout, QWidget)

from .. import APP_NAME, __version__
from ..htmlsafe import safe_to_open
from ..i18n import tr
from ..store import Cache, Config
from .. import updater
from . import assistant as AS
from . import automation as AU
from . import composing as C
from . import readerai as RA
from . import theme as T
from . import viewmodel as vm
from .compose_window import ComposeWindow
from .settings_window import SettingsDialog
from .help_window import HelpDialog
from .updating import UpdateState, restart_command
from .ui_updates import UpdateBanner
from .ui_assistant import AssistantPanel
from .ui_readercard import QuickReply, ReaderCard
from . import navtree as NT
from . import gestures as GS
from . import menus as MN
from . import ui_appicon as AI
from . import savedsearch as SS
from . import imagetrust as IT
from . import aiwork as AW
from . import organizer as O
from . import syncing as SY
from .ai_window import AIMixin
from .organizer_window import OrganizerMixin
from .ui_organizer import MessageExtras
from . import organizer_window as OW
from .. import qtdeps as QD
from ..store import DATA_DIR
from .ui_palette import Palette
from .ui_widgets import (AccountRole, AvatarWidget, CountRole, DepthRole, FoldedRole, InfoRole, KeyRole, KindRole, LabelRole, MessageDelegate, MessageList, NameRole,
                         NavDelegate, NavList, ToggleRole)

IdRole = Qt.UserRole + 1


class MessageModel(QAbstractListModel):
    """Liste des messages d'une vue (versions allégées du cache)."""

    def __init__(self):
        super().__init__()
        self.msgs, self.infos = [], []

    def set_messages(self, msgs, meta=None):
        self.beginResetModel()
        self.msgs = list(msgs)
        self.infos = [vm.row_info(m) for m in self.msgs]
        if meta:
            AW.decorate(self.infos, self.msgs, meta)                       # résumé IA, « Important », « Suspect »
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
    progress = Signal(object)      # avancement d'une mise à jour (version, texte, fraction)
    p2p = Signal()                 # éléments reçus d'un autre poste à appliquer dans le fil de l'interface


class MainWindow(OrganizerMixin, AIMixin, QMainWindow):
    def __init__(self, config=None, cache=None):
        super().__init__()
        self.config, self.cache = config or Config(), cache or Cache()
        self.engine = vm.Engine(self.config, self.cache)
        self.select_mode = False
        self.rail, self.category, self.sync_engine, self._p2p_job = bool(self.config.get("rail")), None, None, None
        self.view_key, self.account, self.load_images, self.current = "inbox", "all", False, None
        self._busy, self._kept, self._tick, self._sending, self._composers = False, set(), 0, False, []
        self.t = T.resolve(self.config, QApplication.palette().window().color().lightness() < 128)
        self.setWindowTitle("%s %s (Qt)" % (APP_NAME, __version__))
        self.setWindowIcon(AI.load())
        self.resize(1360, 840)
        self.setMinimumSize(900, 560)

        # -- barre latérale : marque, « Nouveau message », vues et dossiers, pied (état de synchronisation)
        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(250)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 18, 0, 10)
        sl.setSpacing(8)
        brand = QLabel(APP_NAME)
        brand.setObjectName("brand")
        logo = QLabel()
        logo.setPixmap(AI.load().pixmap(28, 28))
        brand.setContentsMargins(0, 0, 0, 0)
        brow = QHBoxLayout()
        brow.setContentsMargins(20, 0, 20, 4)
        brow.setSpacing(10)
        brow.addWidget(logo)
        brow.addWidget(brand, 1)
        sl.addLayout(brow)
        self.new_btn = QPushButton("✎   " + tr("Nouveau message"))
        self.new_btn.setObjectName("primary")
        self.new_btn.setCursor(Qt.PointingHandCursor)
        self.new_btn.clicked.connect(lambda: self.compose())
        nb = QHBoxLayout()
        nb.setContentsMargins(14, 4, 14, 8)
        nb.addWidget(self.new_btn)
        sl.addLayout(nb)
        self.brand_text = brand
        self.today_btn = QPushButton("📅   " + tr("Aujourd'hui"))
        self.today_btn.setObjectName("flat")
        self.today_btn.setCursor(Qt.PointingHandCursor)
        self.today_btn.setToolTip(tr("Aujourd'hui : agenda, priorités, tâches, relances") + "  (T)")
        self.today_btn.clicked.connect(lambda: self.show_today())
        tb = QHBoxLayout()
        tb.setContentsMargins(14, 0, 14, 4)
        tb.addWidget(self.today_btn)
        sl.addLayout(tb)
        self.sidebar = side
        self.folders = NavList()
        self.folders.toggled.connect(self._toggle_folder)
        self.folders.setContextMenuPolicy(Qt.CustomContextMenu)
        self.folders.customContextMenuRequested.connect(self._nav_menu)
        self.folders.setMouseTracking(True)
        self.folders.setFrameShape(QFrame.NoFrame)
        self.nav_delegate = NavDelegate(self.t)
        self.folders.setItemDelegate(self.nav_delegate)
        self.folders.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self._build_sidebar()
        self.folders.currentRowChanged.connect(self._view_changed)
        sl.addWidget(self.folders, 1)
        self.p2p_lbl = QLabel()
        self.p2p_lbl.setObjectName("footer")
        self.p2p_lbl.setContentsMargins(20, 0, 14, 0)
        self.p2p_lbl.hide()
        sl.addWidget(self.p2p_lbl)
        foot = QHBoxLayout()
        foot.setContentsMargins(20, 0, 14, 0)
        self.status = QLabel()
        self.status.setObjectName("footer")
        self.status.setWordWrap(True)
        foot.addWidget(self.status, 1)
        self.undo_btn = QPushButton()
        self.undo_btn.setObjectName("chip")
        self.undo_btn.clicked.connect(self._undo_send)
        self.undo_btn.hide()
        foot.addWidget(self.undo_btn)
        self.sync_btn = QPushButton("⟳")
        self.sync_btn.setObjectName("flat")
        self.sync_btn.setToolTip(tr("Synchronisation…").rstrip("…"))
        self.sync_btn.clicked.connect(lambda: self.sync())
        foot.addWidget(self.sync_btn)
        self.settings_btn = QPushButton("⚙")
        self.settings_btn.setObjectName("flat")
        self.settings_btn.setToolTip(tr("Paramètres") + "  (Ctrl+,)")
        self.settings_btn.clicked.connect(lambda: self.show_settings())
        foot.addWidget(self.settings_btn)
        self.help_btn = QPushButton("?")
        self.help_btn.setObjectName("flat")
        self.help_btn.setToolTip(tr("Aide") + "  (F1)")
        self.help_btn.clicked.connect(lambda: self.show_help())
        foot.addWidget(self.help_btn)
        self.update_chip = QPushButton()
        self.update_chip.setObjectName("chip")
        self.update_chip.clicked.connect(lambda: self.show_settings(page="updates"))
        self.update_chip.hide()
        foot.insertWidget(0, self.update_chip)
        sl.addLayout(foot)

        # -- colonne liste : recherche, actions, messages
        self.model = MessageModel()
        self.delegate = MessageDelegate(self.t, T.row_height(self.config.get("density") or "comfortable"))
        self.list = MessageList(self.delegate, lambda: (GS.settings(self.config), bool(self.config.get("swipe_invert"))))
        self.list.swiped.connect(self._swiped)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._context_menu)
        self.list.setModel(self.model)
        self.list.setMouseTracking(True)
        self.list.setFrameShape(QFrame.NoFrame)
        self.list.setVerticalScrollMode(QListView.ScrollPerPixel)
        self.list.setItemDelegate(self.delegate)
        self.list.setUniformItemSizes(True)
        self.list.setSelectionMode(QListView.ExtendedSelection)
        self.list.selectionModel().currentChanged.connect(self._row_changed)
        self.list.selectionModel().selectionChanged.connect(lambda *_: self._selection_changed())
        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText("🔍  " + tr("Rechercher  (« ? … » : recherche IA)"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _t: self.reload())
        self.search.returnPressed.connect(lambda: self.ai_search(self.search.text()) if AW.is_ai_query(self.search.text()) else None)
        self.title = QLabel()
        self.title.setObjectName("subject")
        self.count_lbl = QLabel()
        self.count_lbl.setObjectName("dim")
        self.empty = QLabel(tr("Aucun message"))
        self.empty.setObjectName("dim")
        self.empty.setAlignment(Qt.AlignCenter)
        listcol = QFrame()
        listcol.setObjectName("listcol")
        ll = QVBoxLayout(listcol)
        ll.setContentsMargins(0, 18, 0, 0)
        ll.setSpacing(6)
        top = QHBoxLayout()
        top.setContentsMargins(20, 0, 20, 0)
        top.addWidget(self.title)
        top.addStretch(1)
        top.addWidget(self.count_lbl)
        self.sel_btn = QPushButton("☑")
        self.sel_btn.setObjectName("flat")
        self.sel_btn.setCheckable(True)
        self.sel_btn.setCursor(Qt.PointingHandCursor)
        self.sel_btn.setToolTip(tr("Mode sélection multiple") + "  (X)")
        self.sel_btn.toggled.connect(self.set_select_mode)
        top.addWidget(self.sel_btn)
        ll.addLayout(top)
        self.bulk_lbl = QLabel()
        self.bulk_lbl.setObjectName("chip")
        self.bulk_lbl.setStyleSheet("padding: 5px 12px; border-radius: 12px; font-weight: 600;")
        self.bulk_lbl.setContentsMargins(0, 0, 0, 0)
        bb = QHBoxLayout()
        bb.setContentsMargins(20, 0, 20, 0)
        bb.addWidget(self.bulk_lbl)
        bb.addStretch(1)
        self.bulk_row = QWidget()
        self.bulk_row.setLayout(bb)
        self.bulk_row.hide()
        ll.addWidget(self.bulk_row)
        self.demo_banner = QFrame()
        dbl = QHBoxLayout(self.demo_banner)
        dbl.setContentsMargins(20, 2, 16, 2)
        dl = QLabel(tr("Mode démonstration"))
        dl.setObjectName("dim")
        dbl.addWidget(dl, 1)
        db = QPushButton(tr("Ajouter mon compte"))
        db.setObjectName("chip")
        db.clicked.connect(lambda: self.show_settings(add=True))
        dbl.addWidget(db)
        ll.addWidget(self.demo_banner)
        self.demo_banner.setVisible(not self.config["accounts"])
        sb = QHBoxLayout()
        sb.setContentsMargins(16, 4, 16, 2)
        sb.addWidget(self.search)
        ll.addLayout(sb)
        self.actions_row = QHBoxLayout()
        self.actions_row.setContentsMargins(14, 0, 14, 4)
        self.actions_row.setSpacing(0)
        ll.addLayout(self.actions_row)
        self.cat_bar = QWidget()
        cb = QHBoxLayout(self.cat_bar)
        cb.setContentsMargins(16, 0, 16, 2)
        cb.setSpacing(4)
        self.cat_buttons = {}
        for key, label in OW.CATEGORIES:
            b = QPushButton(label)
            b.setObjectName("flat")
            b.setCheckable(True)
            b.setChecked(key is None)
            b.clicked.connect(lambda _c=False, k=key: self.set_category(k))
            cb.addWidget(b)
            self.cat_buttons[key] = b
        cb.addStretch(1)
        ll.addWidget(self.cat_bar)
        ll.addWidget(self.build_digest_card())
        ll.addWidget(self.list, 1)
        ll.addWidget(self.empty, 1)

        # -- lecteur : en-tête (avatar, objet, expéditeur, actions de réponse) puis corps
        self.avatar = AvatarWidget(self.t)
        self.avatar.hide()
        self.head = QLabel()
        self.head.setTextFormat(Qt.RichText)
        self.head.setWordWrap(True)
        self.head.setTextInteractionFlags(Qt.TextSelectableByMouse)
        rb = QHBoxLayout()
        rb.setSpacing(2)
        self.reply_buttons = [self._tool("↩", tr("Répondre"), "R", lambda: self.reply(), self_layout=rb, label=True),
                              self._tool("↩↩", tr("Répondre à tous"), "A", lambda: self.reply(True), self_layout=rb),
                              self._tool("→", tr("Transférer"), "F", lambda: self.forward(), self_layout=rb)]
        headrow = QHBoxLayout()
        headrow.setContentsMargins(24, 16, 18, 12)
        headrow.setSpacing(14)
        headrow.addWidget(self.avatar, 0, Qt.AlignTop)
        headrow.addWidget(self.head, 1)
        headrow.addLayout(rb)
        readerhead = QFrame()
        readerhead.setObjectName("readerhead")
        readerhead.setLayout(headrow)
        self.images_btn = QPushButton(tr("Charger les images distantes"))
        self.images_btn.setObjectName("chip")
        self.images_menu = QMenu(self.images_btn)
        self.images_btn.setMenu(self.images_menu)             # un clic ouvre le choix : cette fois / toujours pour l'expéditeur / pour le domaine
        self.images_btn.hide()
        self.reader = _make_reader(self._open_link)
        right = QFrame()
        right.setObjectName("readerwrap")
        rl = QVBoxLayout(right)
        rl.setContentsMargins(6, 6, 6, 6)                    # marge intérieure : les coins du lecteur web restent dans l'arrondi
        rl.setSpacing(0)
        rl.addWidget(readerhead)
        ib = QHBoxLayout()
        ib.setContentsMargins(22, 8, 22, 0)
        ib.addWidget(self.images_btn)
        ib.addStretch(1)
        rl.addLayout(ib)
        self.extras = MessageExtras()
        self._wire_extras()
        rl.addWidget(self.extras)
        self.ai_card = ReaderCard()
        self.ai_card.action.connect(self._on_ai_action)
        rl.addWidget(self.ai_card)
        rl.addWidget(self.reader, 1)
        self.quick = QuickReply()
        self.quick.send.connect(self.quick_reply)
        self.quick.ai.connect(lambda: self._on_ai_action("reply_ai", ""))
        self.quick.expand.connect(lambda t: self._on_ai_action("quick_expand", t))
        self.quick.hide()
        rl.addWidget(self.quick)
        self._ai_token = 0

        self.listcol, self.right = listcol, right
        split = self.split = QSplitter()
        split.setHandleWidth(12)
        split.addWidget(listcol)
        split.addWidget(right)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 3)
        split.setSizes([430, 680])
        split.setChildrenCollapsible(False)
        root = QFrame()
        root.setObjectName("root")
        rh = QHBoxLayout(root)
        rh.setContentsMargins(12, 12, 12, 12)                # cartes flottantes aux angles arrondis, séparées par de l'air
        rh.setSpacing(12)
        rh.addWidget(side)
        rh.addWidget(split, 1)
        self.assistant = AssistantPanel()
        self.assistant.hide()
        self.assistant.asked.connect(self.assistant_ask)
        self.assistant.closed.connect(lambda: self.toggle_assistant(False))
        rh.addWidget(self.assistant)
        self.update_banner = UpdateBanner()
        self.update_banner.action.connect(self._update_action)
        outer = QWidget()
        ov = QVBoxLayout(outer)
        ov.setContentsMargins(0, 0, 0, 0)
        ov.setSpacing(0)
        ov.addWidget(self.update_banner)
        ov.addWidget(root, 1)
        self.setCentralWidget(outer)
        self.update_views = []
        self.updates = UpdateState(self.config)
        self._render_updates()

        # -- actions sur les messages (boutons de la colonne liste + raccourcis)
        self._tool("🗄", tr("Archiver"), "E", lambda: self.move_selected("archive"), self_layout=self.actions_row)
        self._tool("🗑", tr("Supprimer"), "Delete", lambda: self.move_selected("trash"), self_layout=self.actions_row)
        self._tool("⚠", tr("Signaler comme spam"), "!", lambda: self.move_selected("spam"), self_layout=self.actions_row)
        self.notspam_btn = self._tool("✔", tr("Ce n'est pas du spam (retour en boîte de réception)"), None, self.not_spam_selected,
                                      self_layout=self.actions_row)
        self.notspam_btn.hide()
        self.block_btn = self._tool("⛔", tr("Bloquer l'expéditeur"), None, self._block_menu, self_layout=self.actions_row)
        self.actions_row.addSpacing(10)
        self._tool("☆", tr("Favori"), "S", lambda: self.toggle_flag("starred"), self_layout=self.actions_row)
        self._tool("📌", tr("Épingler"), "P", lambda: self.toggle_flag("pinned"), self_layout=self.actions_row)
        self._tool("✉", tr("Marquer comme non lu"), "U", lambda: self.toggle_flag("unread"), self_layout=self.actions_row)
        self.move_btn = self._tool("📁", tr("Déplacer vers…"), "V", self._move_menu, self_layout=self.actions_row)
        self.actions_row.addStretch(1)
        self.ai_btn = self._tool("✨", tr("Assistant IA (Ctrl+J)"), "Ctrl+J", self.toggle_assistant, self_layout=self.actions_row)
        self._act(None, tr("Nouveau message"), "C", lambda: self.compose())
        self._act(None, tr("Paramètres"), "Ctrl+,", lambda: self.show_settings())
        self._act(None, tr("Rechercher"), "/", lambda: self.search.setFocus())
        self._act(None, tr("Aide"), "F1", self.show_help)
        self._act(None, "", "H", self.snooze_tomorrow)
        self._act(None, "", "J", lambda: self._step(1))
        self._act(None, "", "K", lambda: self._step(-1))

        self.bridge = _Bridge()
        threading.Thread(target=self.config.preload_passwords, daemon=True).start()      # trousseau lu une fois, hors du fil de l'interface
        self.bridge.done.connect(self._task_done)
        self.update_progress = self.bridge.progress
        self.bridge.progress.connect(self._stage)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._on_timer)
        self.timer.start(60_000)
        self.outbox_timer = QTimer(self)
        self.outbox_timer.timeout.connect(self.process_outbox)
        self.outbox_timer.start(2000)
        self.apply_theme()
        self.set_layout(self.config.get("layout") or "columns")
        self._act(None, "", "Escape", self._back_to_list)
        self._act(None, "", "Ctrl+K", self.show_palette)
        self._act(None, "", "X", lambda: self.sel_btn.toggle())
        self._act(None, "", "Ctrl+A", self.select_all)
        self._act(None, "", "\\", self.cycle_layout)
        self._act(None, "", "T", self.show_today)
        self._act(None, "", "Ctrl++", lambda: self.zoom_reader(OW.ZOOM_STEP))
        self._act(None, "", "Ctrl+=", lambda: self.zoom_reader(OW.ZOOM_STEP))
        self._act(None, "", "Ctrl+-", lambda: self.zoom_reader(-OW.ZOOM_STEP))
        self._act(None, "", "Ctrl+0", lambda: self.zoom_reader(0))
        self._act(None, "", "Ctrl+B", self.toggle_rail)
        self.bridge.p2p.connect(self._p2p_run)
        self.reload()
        self.set_rail(self.rail)
        self.apply_zoom()
        self.init_sync()
        self.open_today_at_start()
        QTimer.singleShot(300, lambda: self.sync(quiet=True))
        QTimer.singleShot(8000, lambda: self.check_updates(startup=True))               # 8 s après CHAQUE démarrage…
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(lambda: self.check_updates())                 # …puis toutes les heures (règle « due » : 55 min)
        self.update_timer.start(3600 * 1000)
        QTimer.singleShot(600, self._refresh_folders)

    def _tool(self, glyph, text, shortcut, fn, self_layout=None, label=False):
        """Bouton plat (glyphe + info-bulle) lié à une action à raccourci clavier ; ajouté à la rangée donnée."""
        a = self._act(None, text, shortcut, fn)
        b = QPushButton(("%s  %s" % (glyph, text)) if label else glyph)
        b.setObjectName("flat")
        b.setCursor(Qt.PointingHandCursor)
        b.setToolTip("%s  (%s)" % (text, shortcut.replace("Delete", "Suppr")) if shortcut else text)
        b.clicked.connect(lambda _c=False: a.trigger())
        if self_layout is not None:
            self_layout.addWidget(b)
        b.action = a
        return b

    def apply_theme(self):
        """Applique le style (Aurora, Papier ou Terminal ; clair ou sombre ; accent) à toute l'application Qt."""
        self.t = T.resolve(self.config, QApplication.palette().window().color().lightness() < 128)
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(T.build_qss(self.t))
        self.list.itemDelegate().h = T.row_height(self.config.get("density") or "comfortable")
        for view in (self.list, self.folders):
            view.itemDelegate().t = self.t
            view.viewport().update()
        self.list.doItemsLayout()
        self.avatar.t = self.t
        self.avatar.update()


    # ------------------------------------------------------------ affichage
    def is_dark(self):
        return bool(self.t["dark"])

    def reload(self):
        keep = self.current
        raw = self.search.text()
        q = ("" if AW.is_ai_query(raw) else raw) or SS.query_of(self.config, self.view_key)       # « ? … » : recherche IA, lancée par Entrée
        view = self.view_key if not self.view_key.startswith(SS.PREFIX) else "inbox"
        msgs = vm.list_view(self.cache, view, self.account, q, threads=vm.grouped(self.config, self.view_key, q),
                            category=self.category if self.view_key == "inbox" else None)
        if self.view_key == "unread" and self._kept:
            have = {m.id for m in msgs}
            for mid in self._kept - have:                   # « Non lus » : le message ouvert reste affiché jusqu'à ce qu'on passe à un autre
                m = self.cache.get_light(mid)
                if m is not None:
                    msgs.append(m)
            msgs.sort(key=lambda m: m.date, reverse=True)
        self.model.set_messages(msgs, self.cache.ai_meta([m.id for m in msgs]) if msgs else None)
        self.update_digest_visibility()
        self.update_category_bar()
        self.title.setText(self._view_title())
        self.count_lbl.setText("%d" % len(msgs) if msgs else "")
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

    def _caption(self, text):
        it = QListWidgetItem(text)
        it.setData(KindRole, "caption")
        it.setData(LabelRole, text)
        it.setFlags(Qt.NoItemFlags)
        self.folders.addItem(it)

    def _build_sidebar(self, keep_key=None):
        """Vues intelligentes, dossiers de base, puis vos dossiers de rangement (avec leur hiérarchie)."""
        self.folders.blockSignals(True)
        self.folders.clear()
        smart, base = vm.VIEWS[:6], vm.VIEWS[6:]
        for group in (smart, base):
            for key, label in group:
                it = QListWidgetItem(label)
                it.setData(KeyRole, key)
                it.setData(LabelRole, label)
                it.setData(CountRole, 0)
                it.setData(KindRole, "view")
                it.setData(KindRole + 1, 0)
                self.folders.addItem(it)
        saved = SS.rows(self.config)
        if saved:
            self._caption(tr("Recherches"))
            for key, name in saved:
                it = QListWidgetItem(name)
                it.setData(KeyRole, key)
                it.setData(LabelRole, name)
                it.setData(CountRole, 0)
                it.setData(KindRole, "folder")
                it.setData(DepthRole, 0)
                self.folders.addItem(it)
        rows = NT.build(self.engine, self.config.get("collapsed_folders") or [])
        if rows:
            self._caption(tr("Dossiers"))
        for r in rows:
            it = QListWidgetItem(r["label"])
            it.setData(LabelRole, r["label"])
            it.setData(CountRole, 0)
            it.setData(KindRole, r["kind"])
            it.setData(DepthRole, r["depth"])
            it.setData(ToggleRole, r["toggle"])
            it.setData(FoldedRole, r["collapsed"])
            it.setData(AccountRole, r["aid"])
            it.setData(NameRole, r["name"])
            if r["kind"] == "folder" and r["selectable"]:
                it.setData(KeyRole, r["key"])
            else:
                it.setFlags(Qt.ItemIsEnabled)                           # section d'un compte ou dossier de regroupement : ne se sélectionne pas
            self.folders.addItem(it)
        self.select_view(keep_key or getattr(self, "view_key", "inbox"), quiet=True)
        self.folders.blockSignals(False)

    def select_view(self, key, quiet=False):
        row = next((i for i in range(self.folders.count()) if self.folders.item(i).data(KeyRole) == key), 0)
        if quiet:
            self.folders.blockSignals(True)
        self.folders.setCurrentRow(row)
        if quiet:
            self.folders.blockSignals(False)

    def _view_title(self):
        for i in range(self.folders.count()):
            it = self.folders.item(i)
            if it.data(KeyRole) == self.view_key:
                return it.data(LabelRole)
        return ""

    def _toggle_folder(self, key):
        """Plie / déplie un dossier ou une boîte (chevron) ; l'état est mémorisé comme dans la version GTK."""
        NT.toggle(self.config, key)
        self._build_sidebar(self.view_key)
        self._update_counts()

    def _update_counts(self):
        c = vm.counts(self.cache, self.account)
        unread = self.engine.folder_unread
        for i in range(self.folders.count()):
            it = self.folders.item(i)
            kind, key = it.data(KindRole), it.data(KeyRole)
            if kind == "folder":
                it.setData(CountRole, int(unread.get((it.data(AccountRole), it.data(NameRole)), 0) or 0))
            elif kind == "account":
                aid = it.data(AccountRole)
                it.setData(CountRole, sum(int(v or 0) for (a, n), v in unread.items() if a == aid and n not in vm.SPECIAL))
            elif key is not None:
                it.setData(CountRole, c.get(key, 0))
        self.folders.viewport().update()
        self.notspam_btn.setVisible(self.view_key == "spam")

    def _view_changed(self, row):
        if row >= 0 and self.folders.item(row).data(KeyRole) is not None:
            self.view_key = self.folders.item(row).data(KeyRole)
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
            self._mark_thread_read(mid)
            self._update_counts()
            self._repaint_row(mid)
            self._background(self.engine.flush)

    # ------------------------------------------------------------ actions
    def _act(self, bar, text, shortcut, fn):
        a = QAction(text, self)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        a.triggered.connect(lambda _c=False: fn())
        self.addAction(a)
        return a

    def set_layout(self, layout):
        """Disposition : columns (liste | lecture), bottom (lecture en bas) ou list (liste seule, la lecture prend tout l'écran)."""
        layout = layout if layout in ("columns", "bottom", "list") else "columns"
        self.config["layout"] = layout
        self.config.save()
        self.split.setOrientation(Qt.Vertical if layout == "bottom" else Qt.Horizontal)
        self.listcol.show()
        self.right.setVisible(layout != "list")
        if layout == "bottom":
            self.split.setSizes([320, 520])

    def _mark_thread_read(self, mid):
        """Ouvrir une conversation en marque tous les messages lus (même dossier), comme dans la version GTK."""
        row = self.model.row_of(mid)
        m = self.model.msgs[row] if row >= 0 else None
        if m is None or getattr(m, "thread_count", 1) <= 1 or m.folder == "drafts" or not self.config.get("threads", True):
            return
        rest = [x for x in vm.expand_threads(self.cache, [m]) if x.unread and x.id != mid]
        if rest:
            op_ids = self.engine.set_flag(rest, "unread", False)
            self._background(lambda: self.engine.run_ops(op_ids), "ops")

    def save_current_search(self):
        """Enregistre le texte de la barre de recherche sous un nom ; la recherche apparaît dans la section « Recherches »."""
        q = self.search.text().strip() or SS.query_of(self.config, self.view_key)
        if not q:
            self.status.setText(tr("Tapez d'abord une recherche, puis enregistrez-la"))
            return
        name, ok = QInputDialog.getText(self, tr("Enregistrer la recherche"), tr("Enregistrer la recherche"), text=q)
        key = SS.add(self.config, name, q) if ok else None
        if key:
            self.search.clear()
            self._build_sidebar(key)
            self._view_changed(next((i for i in range(self.folders.count()) if self.folders.item(i).data(KeyRole) == key), -1))

    def _nav_menu(self, pos):
        it = self.folders.itemAt(pos)
        key = it.data(KeyRole) if it is not None else None
        if not key or not str(key).startswith(SS.PREFIX):
            return
        menu = QMenu(self)
        menu.addAction(tr("Supprimer la recherche enregistrée : ") + (it.data(LabelRole) or ""), lambda: self._delete_saved(int(key[len(SS.PREFIX):])))
        menu.exec(self.folders.viewport().mapToGlobal(pos))

    def _delete_saved(self, i):
        SS.delete(self.config, i)
        self._build_sidebar("inbox")
        self._view_changed(next((n for n in range(self.folders.count()) if self.folders.item(n).data(KeyRole) == "inbox"), -1))

    def set_select_mode(self, on):
        """Mode sélection multiple : cases rondes sur chaque message, un clic coche / décoche ; barre « n sélectionnés » au-dessus de la liste."""
        self.select_mode = bool(on)
        self.delegate.select_mode = self.select_mode
        self.list.setSelectionMode(QListView.MultiSelection if on else QListView.ExtendedSelection)
        self.list.clearSelection()
        self.list.viewport().update()
        self._selection_changed()

    def select_all(self):
        if not self.sel_btn.isChecked():
            self.sel_btn.setChecked(True)
        self.list.selectAll()

    def mark_all_read(self):
        """Tout marquer comme lu dans la vue affichée (comme la version GTK)."""
        msgs = [m for m in self.model.msgs if m.unread]
        if msgs:
            op_ids = self.engine.set_flag(msgs, "unread", False)
            for m in msgs:
                m.unread = False
            self.reload()
            self._background(lambda: self.engine.run_ops(op_ids), "ops")

    def _selection_changed(self):
        n = len({i.row() for i in self.list.selectionModel().selectedRows()})
        self.bulk_lbl.setText(tr("%d sélectionné%s") % (n, "s" if n > 1 else ""))
        self.bulk_row.setVisible(n >= 1 and (getattr(self, "select_mode", False) or n > 1))
        if n > 1:
            self._show(None)
            self.reader.show_html("<html><body style='font-family:sans-serif;color:%s;text-align:center;padding-top:140px'><h2>%s</h2></body></html>"
                                  % (self.t["dim"], tr("%d messages sélectionnés") % n))
        self.list.viewport().update()

    def cycle_layout(self):
        order = ["columns", "bottom", "list"]
        cur = self.config.get("layout") or "columns"
        self.set_layout(order[(order.index(cur) + 1) % 3 if cur in order else 0])

    def _back_to_list(self):
        if (self.config.get("layout") == "list") and self.listcol.isHidden():
            self.right.hide()
            self.listcol.show()

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
        return vm.expand_threads(self.cache, [self.model.msgs[r] for r in rows], bool(self.config.get("threads", True)))

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

    def not_spam_selected(self):
        msgs = self.selected_msgs()
        if msgs:
            back = AU.not_spam(self.engine, msgs[0])
            self.move_messages(back or msgs, "inbox")

    def _block_menu(self):
        msgs = self.selected_msgs()
        if not msgs:
            return
        m = msgs[0]
        menu = QMenu(self)
        for domain in (False, True):
            key = AU.sender_key(m, domain)
            menu.addAction(tr("Bloquer %s") % key, lambda k=key: self.block_sender(k, m))
        menu.exec(self.block_btn.mapToGlobal(self.block_btn.rect().bottomLeft()))

    def block_sender(self, key, msg=None):
        msgs, dest = AU.filter_sender(self.engine, key, "blocked", msg)
        self.status.setText(tr("Bloqué : ") + key)
        self.move_messages(msgs, dest)

    # ------------------------------------------------------------ carte IA du lecteur
    def _same(self, msg):
        return getattr(self, "shown", None) is not None and self.shown.id == msg.id

    def ai_open(self, msg):
        """Carte IA : cache tout de suite, sinon analyse légèrement temporisée (pas un appel par message quand on parcourt la liste)."""
        st, res = RA.state(self.engine, msg)
        if st in ("ready", "cta"):
            self.ai_card.result(res, msg, cta=(st == "cta"))
        elif st == "idle":
            self.ai_card.idle()
        else:
            self.ai_card.loading()
            self._ai_token += 1
            token = self._ai_token
            QTimer.singleShot(350, lambda: self.ai_fetch(msg) if token == self._ai_token and self._same(msg) else None)

    def ai_fetch(self, msg, force=False):
        self.ai_card.loading()

        def done(res, err):
            if not self._same(msg):
                return
            if err:
                from ..ai_engine import local_analysis
                self.ai_card.result(local_analysis(msg, AS.ai_engine(self.engine).lang), msg, error=str(err)[:120])
            else:
                self.ai_card.result(res, msg)
                self.reload()
        self.run_bg(lambda: RA.fetch(self.engine, msg, force=force), done)

    def _ai_text(self, msg, title, fn, working):
        self.ai_card.working(working)

        def done(t, err):
            if self._same(msg):
                self.ai_card.text(title, (tr("Erreur IA : %s") % str(err)[:100]) if err else t)
        self.run_bg(fn, done)

    def _on_ai_action(self, act, payload):
        msg = getattr(self, "shown", None)
        if act == "enable_ai":
            self.show_settings(page="ai")
        elif msg is None:
            return
        elif act in ("analyze", "regen"):
            self.ai_fetch(msg, force=(act == "regen"))
        elif act == "translate":
            self._ai_text(msg, tr("Traduction"), lambda: RA.translate(self.engine, msg), tr("Traduction…"))
        elif act == "ask":
            self._ai_text(msg, payload[:60], lambda: RA.ask(self.engine, msg, payload), tr("Réflexion…"))
        elif act == "reply_ai":
            self.ai_reply(msg)
        elif act == "quick_expand":
            self.ai_card.working(tr("Rédaction de votre réponse…"))

            def done(t, err):
                if not self._same(msg):
                    return
                if err:
                    self.status.setText(tr("Erreur IA : %s") % str(err)[:90])
                else:
                    self.quick.entry.setText(t.replace("\n", " ").strip())
                    self.quick.entry.setFocus()
                self.ai_card.answer.hide()
            self.run_bg(lambda: RA.draft(self.engine, msg, payload, 1200), done)
        elif act in ("not_spam", "not_spam_file"):
            back = AU.not_spam(self.engine, msg)
            if act == "not_spam_file" and payload:
                self._file_into_folder(back or [msg], msg.account, payload)
            else:
                self.move_messages(back or [msg], "inbox")

    def _file_into_folder(self, msgs, aid, folder):
        def done(n, err):
            if err:
                self.status.setText("⚠ " + str(err)[:120])
            else:
                self.reload()
                self._build_sidebar(self.view_key)
        self.run_bg(lambda: AS.apply_group(self.engine, aid, folder, msgs), done)

    def ai_reply(self, msg):
        """Rédige une réponse avec l'IA puis ouvre le composeur prérempli (à relire avant envoi)."""
        if not AS.ai_engine(self.engine).enabled():
            self.show_settings(page="ai")
            return
        self.status.setText(tr("✨ Rédaction de la réponse…"))
        full = self.cache.get(msg.id) or msg

        def done(text, err):
            if err:
                self.status.setText(tr("Erreur IA : %s") % str(err)[:90])
            else:
                self.compose(**dict(C.reply_args(self.config, self.engine.accounts(), full, False, self.engine.default_account(full, self.account)),
                                    ai_suggested_text=text))
        self.run_bg(lambda: RA.draft(self.engine, full), done)

    def quick_reply(self, text):
        msg = getattr(self, "shown", None)
        if msg is not None:
            self.queue_send(C.quick_reply_outgoing(self.config, self.engine.accounts(), msg, text,
                                                   self.engine.default_account(msg, self.account)), 0)

    # ------------------------------------------------------------ assistant IA
    def toggle_assistant(self, show=None):
        show = (not self.assistant.isVisible()) if show is None else show
        self.assistant.setVisible(bool(show))
        if show:
            self.assistant.focus_entry()

    def assistant_ask(self, text):
        p = self.assistant
        self.toggle_assistant(True)
        p.add_user(text)
        ai = AS.ai_engine(self.engine)
        if not ai.enabled():
            p.add_ai(tr("L'IA n'est pas encore configurée. Ajoutez votre clé API NVIDIA pour que je puisse vous aider."))
            p.add_plan([(tr("Ouvrir les réglages de l'IA"), lambda: self.show_settings(page="ai"))])
            return
        p.set_busy(True)
        sel = self.selected_msgs()
        args = (text, self.view_title(), self.account, self._open_msg(), sel)

        def done(res, err):
            p.set_busy(False)
            if err:
                p.add_ai(tr("Désolé, l'IA a rencontré une erreur : %s") % str(err)[:160])
                return
            if res["reply"]:
                p.add_ai(res["reply"])
            items = [(i["label"], (lambda i=i: self._assistant_run(i)) if i["action"] else None) for i in res["items"]]
            if items:
                p.add_plan(items)
            elif not res["reply"]:
                p.add_ai(tr("Je n'ai pas compris, pouvez-vous reformuler ?"))
        self.run_bg(lambda: AS.ask(self.engine, *args), done)

    def view_title(self):
        return dict(vm.VIEWS).get(self.view_key, self.view_key)

    def _assistant_run(self, item):
        a, msgs, sel, acc = item["action"], item["msgs"], self.selected_msgs(), self.account

        def done(out, err):
            if err:
                self.assistant.add_ai(tr("Désolé, l'IA a rencontré une erreur : %s") % str(err)[:160])
                return
            if out.get("changed"):
                self.reload()
                self._build_sidebar(self.view_key)
            if out.get("toast"):
                self.status.setText(out["toast"])
            if out.get("search") is not None:
                self.search.setText(out["search"])
            if out.get("compose"):
                self.compose(**out["compose"])
            if out.get("settings") is not None or a["type"] == "open_settings":
                self.show_settings(page=out.get("settings"))
            if out.get("text"):
                self.assistant.add_ai(out["text"])
            if out.get("plan") is not None:
                plan = out["plan"]
                if not plan:
                    self.assistant.add_ai(tr("Rien à ranger : ces messages restent dans la boîte de réception."))
                else:
                    self.assistant.add_plan([(g["label"], lambda g=g: self._apply_group(g)) for g in plan])
        if a["type"] == "classify":
            self.assistant.add_ai(tr("Je classe %d message(s)… Rien n'est déplacé ni créé avant votre accord.") % len(msgs))
            self.assistant.set_busy(True)
            inner = done
            done = lambda out, err: (self.assistant.set_busy(False), inner(out, err))
        self.run_bg(lambda: AS.run(self.engine, a, msgs, acc, sel), done)

    def _apply_group(self, g):
        def done(n, err):
            if err:
                self.status.setText("⚠ " + str(err)[:120])
            else:
                self.reload()
                self._build_sidebar(self.view_key)
        self.run_bg(lambda: AS.apply_group(self.engine, g["aid"], g["folder"], g["msgs"]), done)

    def move_messages(self, msgs, dest):
        """Déplace des messages (cache tout de suite, serveur en fond) — utilisé par les listes de blocage et les règles."""
        if not msgs:
            return
        if dest in ("trash", "spam"):
            self.cache.update_many([m.id for m in msgs], unread=False)
        op_ids = self.engine.move(msgs, dest)
        self.reload()
        self._background(lambda: self.engine.finish_move(msgs, dest, op_ids), "move")

    def apply_rules_now(self):
        left, groups = AU.apply_rules_now(self.engine)
        self.reload()
        self.status.setText(tr("Règles appliquées (%d message(s) restent dans la boîte)") % left)
        for msgs, dest, op_ids in groups:
            self._background(lambda m=msgs, d=dest, o=op_ids: self.engine.finish_move(m, d, o), "move")

    def _move_menu(self):
        msgs = self.selected_msgs()
        if not msgs:
            return
        menu = QMenu(self)
        for dest, label in self.engine.move_targets(msgs[0].account):
            menu.addAction(label, lambda d=dest: self.move_selected(d))
        menu.exec(self.move_btn.mapToGlobal(self.move_btn.rect().bottomLeft()))

    # ------------------------------------------------------------ paramètres et comptes
    def show_settings(self, add=False, page=None):
        dlg = SettingsDialog(self)
        dlg.open_page(page)
        if add or not [a for a in self.config["accounts"]]:
            dlg._add_account()
        dlg.exec()

    # ------------------------------------------------------------ mises à jour
    def _render_updates(self):
        st = self.updates
        self.update_banner.render(st.banner)
        self.update_chip.setVisible(bool(st.chip))
        self.update_chip.setText(st.chip)
        self.update_chip.setToolTip(tr("Cliquez pour voir la mise à jour de MintMail %s") % st.update.version if st.update else "")
        for f in list(self.update_views):
            try:
                f()
            except RuntimeError:                          # page de réglages fermée entre-temps
                self.update_views.remove(f)

    def _update_action(self, key):
        up = self.updates.update
        if key == "install":
            self.install_update()
        elif key == "later":
            self.updates.snooze()
        elif key == "close":
            self.updates.hide()
        elif key == "retry":
            self.updates.banner = {"state": "hidden"}
            self.updates.refresh(force=True)
            self.install_update(confirm=False)
        elif key == "restart":
            self.restart_app()
        elif key == "notes" and up is not None and up.page:
            self._open_link(up.page)
        self._render_updates()

    def check_updates(self, manual=False, startup=False):
        st = self.updates
        if not st.should_check(manual, startup):
            return
        repo, etag = st.begin_check()
        self._render_updates()

        def done(res, err):
            out = st.finish_check(res, err, manual)
            if out["toast"]:
                self.status.setText(out["toast"])
            self._render_updates()
            if out["notify"] is not None and not self.isActiveWindow() and self.config.get("notifications", True):
                from .. import sysdeps
                sysdeps.notify(tr("MintMail %s est disponible") % out["notify"].version,
                               updater.short_notes(out["notify"].notes) or tr("Cliquez pour voir la mise à jour de MintMail %s") % out["notify"].version)
        self.run_bg(lambda: updater.check(repo, etag=etag), done)

    def install_update(self, confirm=True):
        st = self.updates
        up = st.update
        if up is None or st.busy:
            return
        if confirm and updater.can_install()[0]:
            notes = (up.notes.strip()[:600] + "\n\n") if up.notes.strip() else ""
            if QMessageBox.question(self, APP_NAME, tr("Installer MintMail %s ?") % up.version + "\n\n" + notes + tr(
                    "Le paquet est téléchargé depuis GitHub, sa signature est vérifiée avec la clé de SAEC intégrée à MintMail, puis votre mot de passe "
                    "administrateur est demandé pour l'installer. Fermez et relancez MintMail ensuite.")) != QMessageBox.Yes:
                return
        msg = st.start_install()
        self._render_updates()
        if msg is not None:
            if msg:
                self.status.setText(msg)
            return
        bridge = self.update_progress

        def stage(version, text, fraction=None):
            bridge.emit((version, text, fraction))

        def done(res, err):
            text = st.finish_install(res, err)
            if text:
                self.status.setText(text)
            self._render_updates()
        self.run_bg(lambda: st.install_work(stage), done)

    def _stage(self, payload):
        version, text, fraction = payload
        self.updates.show_progress(version, text, fraction)
        self._render_updates()

    def restart_app(self):
        """Relance MintMail : une commande FIXE, lancée dans une session détachée après la fermeture de cette fenêtre."""
        import subprocess
        quiet = dict(close_fds=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if sys.platform == "win32":
            subprocess.Popen(restart_command(), creationflags=0x00000008, **quiet)            # DETACHED_PROCESS
        else:
            subprocess.Popen(["/bin/sh", "-c", 'sleep 2; cd /; exec "$0" "$@"'] + restart_command(), start_new_session=True, **quiet)
        self.close()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def show_help(self):
        """Aide intégrée (F1) : une seule fenêtre, non bloquante."""
        if getattr(self, "_help", None) is None:
            self._help = HelpDialog(self)
        self._help.goto("sec:home")
        self._help.show()
        self._help.raise_()
        self._help.activateWindow()

    def accounts_changed(self):
        """Comptes ajoutés, modifiés ou retirés : on repart sur des serveurs neufs, on sort du mode démo et on resynchronise."""
        for be in list(self.engine._backends.values()):
            try:
                be.close()
            except Exception:
                pass
        self.engine._backends.clear()
        if self.config["accounts"]:
            self.cache.delete_account("demo")
        self.demo_banner.setVisible(not self.config["accounts"])
        self._build_sidebar(self.view_key)
        self.reload()
        QTimer.singleShot(200, self.sync)
        QTimer.singleShot(1500, self._refresh_folders)

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

    # ------------------------------------------------------------ clic droit et palette
    def _context_menu(self, pos):
        idx = self.list.indexAt(pos)
        if not idx.isValid():
            return
        if not self.list.selectionModel().isRowSelected(idx.row(), QModelIndex()):
            self.list.setCurrentIndex(idx)
        msgs = self.selected_msgs()
        if not msgs:
            return
        m = msgs[0]
        menu = QMenu(self)
        for it in MN.context_items(m, m.sender_email.lower() in {x.lower() for x in self.config["blocked"]}):
            if it is None:
                menu.addSeparator()
            else:
                menu.addAction(it[1], lambda k=it[0]: self._run_cmd(k, m))
        self.add_extra_menu(menu, m)
        self.add_ai_menu(menu, m)
        menu.addSeparator()
        sn = menu.addMenu(tr("Reporter"))
        for key, label in MN.SNOOZES:
            sn.addAction(label, lambda k=key: self._run_cmd(k, m))
        mv = menu.addMenu(tr("Déplacer vers un dossier"))
        for dest, label in self.engine.move_targets(m.account):
            mv.addAction(label, lambda d=dest: self._run_cmd("move:" + d, m))
        menu.exec(self.list.viewport().mapToGlobal(pos))

    def show_palette(self):
        sel = self.selected_msgs()
        m = getattr(self, "shown", None) or (sel[0] if sel else None)
        dlg = Palette(self, MN.palette_commands(m, self.engine))
        dlg.chosen.connect(lambda k: QTimer.singleShot(0, lambda: self._run_cmd(k, m)))
        dlg.asked.connect(lambda t: QTimer.singleShot(0, lambda: (self.toggle_assistant(True), self.assistant_ask(t))))
        dlg.exec()

    def _run_cmd(self, key, m):
        """Exécute une commande du clic droit ou de la palette (même chemin que les boutons : cache d'abord, serveur ensuite)."""
        head, _, arg = key.partition(":")
        if m is not None:
            if key == "reply" or key == "reply_all" or key == "forward":
                return {"reply": self.reply, "reply_all": lambda: self.reply(True), "forward": self.forward}[key]()
            if key in ("archive", "trash", "spam"):
                return self.move_selected(key)
            if key in ("read", "star", "pin"):
                return self.toggle_flag({"read": "unread", "star": "starred", "pin": "pinned"}[key])
            if key == "notspam":
                return self.not_spam_selected()
            if key in ("spam_sender", "spam_domain"):
                keyv = AU.sender_key(m, key == "spam_domain")
                msgs, dest = AU.filter_sender(self.engine, keyv, "spam_senders", m)
                self.status.setText("Spam : " + keyv)
                return self.move_messages(msgs, dest)
            if key in ("block", "block_domain"):
                keyv = AU.sender_key(m, key == "block_domain")
                if keyv in {x.lower() for x in self.config["blocked"]}:
                    AU.unfilter_sender(self.engine, "blocked", keyv)
                    self.status.setText(tr("Débloqué : ") + keyv)
                    return
                return self.block_sender(keyv, m)
            if key == "addcontact":
                from . import personal as PE
                self.status.setText(PE.add_sender_to_contacts(self.config, self.cache, m)[1])
                return
            if key == "from":
                self.search.setText(m.sender_email)
                return
            if key in ("summarize", "translate", "ai_reply"):
                if getattr(self, "shown", None) is None or self.shown.id != m.id:
                    self._show(self.cache.get(m.id) or m)
                return self._on_ai_action({"summarize": "analyze", "translate": "translate", "ai_reply": "reply_ai"}[key], "")
            if key == "task_from":
                return self.add_task_dialog(self.cache.get(m.id) or m)
            if key == "slots":
                return self.propose_slots(self.cache.get(m.id) or m)
            if key == "followup3":
                return self.add_followup(self.cache.get(m.id) or m, 3)
            if key == "unsubscribe":
                return self.unsubscribe(m)
            if key in ("snooze_tomorrow", "snooze_monday"):
                msgs = self.selected_msgs() or [m]
                self.engine.snooze(msgs, C.at(1, 8) if key == "snooze_tomorrow" else C.next_monday())
                return self._after_action(msgs, [], "ops", lambda: ([], [], False))
            if head == "move":
                return self.move_selected(arg)
        if head == "goto":
            self.select_view(arg)
            return self._view_changed(next((i for i in range(self.folders.count()) if self.folders.item(i).data(KeyRole) == arg), -1))
        if head == "delsaved":
            return self._delete_saved(int(arg))
        if head == "layout":
            return self.set_layout(arg)
        if head == "settings":
            return self.show_settings(page=arg or None)
        if key == "ai_classify_inbox":
            return self.run_ai(key, m or (self.model.msgs[0] if self.model.msgs else None)) if (m or self.model.msgs) else None
        simple = {"today": self.show_today, "agenda": self.show_agenda, "new_event": self.new_event_dialog, "new_task": lambda: self.add_task_dialog(None),
                  "rail": self.toggle_rail, "zoom_in": lambda: self.zoom_reader(OW.ZOOM_STEP), "zoom_out": lambda: self.zoom_reader(-OW.ZOOM_STEP),
                  "zoom_reset": lambda: self.zoom_reader(0), "p2p_now": self.p2p_now, "digest": lambda: self.refresh_digest(force=True),
                  "assistant": lambda: self.toggle_assistant(True), "compose": self.compose, "sync": lambda: self.sync(False), "help": self.show_help,
                  "apply_rules": self.apply_rules_now, "save_search": self.save_current_search, "mark_all_read": self.mark_all_read, "select_all": self.select_all, "select_mode": lambda: self.sel_btn.toggle(), "updates": lambda: self.check_updates(manual=True), "search": self.search.setFocus}
        if key in simple:
            simple[key]()

    def _swiped(self, row, act):
        """Applique l'action d'un geste à la ligne balayée (même chemin que les boutons : cache d'abord, serveur ensuite)."""
        if not 0 <= row < len(self.model.msgs):
            return
        msg = self.model.msgs[row]
        grp = vm.expand_threads(self.cache, [msg], bool(self.config.get("threads", True)))
        fx = GS.effect(act, msg, C.at(1, 8))
        if "move" in fx:
            dest = fx["move"]
            if dest == "trash" and msg.folder == "trash":
                dest = "archive"
            op_ids = self.engine.move(grp, dest)
            self._after_action(grp, op_ids, "move", lambda: self.engine.finish_move(grp, dest, op_ids))
        elif "flag" in fx:
            field, value = fx["flag"]
            op_ids = self.engine.set_flag(grp, field, value)
            for x in grp:
                setattr(x, field, value)
            self.reload()
            self._background(lambda: self.engine.run_ops(op_ids), "ops")
        elif "snooze" in fx:
            self.engine.snooze(grp, fx["snooze"])
            self._after_action(grp, [], "ops", lambda: ([], [], False))
        elif "block" in fx:
            self.block_sender(fx["block"], msg)

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
            self.avatar.set_sender("", "")
            self.images_btn.hide()
            self.extras.clear()
            self.ai_card.idle()
            self.quick.hide()
            self.reader.show_html("<html><body></body></html>")
            return
        if self.config.get("layout") == "list":                      # liste seule : la lecture remplace la liste (Échap pour revenir)
            self.listcol.hide()
            self.right.show()
        h = vm.header_lines(msg)
        esc = lambda x: (x or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        dim = self.t["dim"]
        self.head.setText("<div style='font-size:19px;font-weight:%s'>%s</div>"
                          "<div style='margin-top:4px'><b>%s</b></div>"
                          "<div style='color:%s;margin-top:2px'>%s &nbsp;·&nbsp; %s</div>"
                          % (self.t["hw"], esc(h["subject"]) or "&nbsp;", esc(msg.display_sender), dim, esc(h["date"]), esc(msg.sender_email)))
        self.head.setToolTip("%s\n%s" % (h["from"], h["to"]))
        self.avatar.set_sender(msg.display_sender, msg.sender_email)
        from ..util import has_remote_content
        load = self.load_images or IT.trusted(self.config, msg.sender_email)        # expéditeur de confiance : images chargées d'office
        self.images_btn.setVisible(bool(msg.html) and has_remote_content(msg.html) and not load)
        self._fill_images_menu(msg)
        self.reader.show_html(vm.render_html(msg, load, self.is_dark()))
        self.apply_zoom()
        self.fill_extras(msg)
        self.quick.show()
        self.quick.set_ai(AS.ai_engine(self.engine).enabled())
        if msg.folder != "drafts":
            self.ai_open(msg)

    def _fill_images_menu(self, msg):
        m = self.images_menu
        m.clear()
        em, dom = IT.keys_for(msg.sender_email)
        m.addAction(tr("Charger les images cette fois")).triggered.connect(lambda _c=False: self._load_images())
        if em:
            m.addSeparator()
            m.addAction(tr("Toujours charger les images de %s") % em).triggered.connect(lambda _c=False, k=em: self._trust_images(k))
            m.addAction(tr("Toujours charger les images de %s") % dom).triggered.connect(lambda _c=False, k=dom: self._trust_images(k))

    def _trust_images(self, key):
        if IT.trust(self.config, key):
            self.status.setText(tr("Images toujours chargées pour %s (Réglages → Filtres pour revenir en arrière)") % key)
        self._load_images()

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
        self._background(lambda: (self.engine.flush(), AU.sync_and_route(self.engine), self.engine.refresh_folder_counts()), "sync")

    def run_bg(self, fn, cb):
        """Travail en fond puis cb(résultat, erreur) dans le fil de l'interface."""
        self._background(fn, cb)

    def _task_done(self, payload):
        tag, (res, err) = payload
        if callable(tag):
            tag(res, err)
            return
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
        offline = bool(res and res[0] and res[0][2])
        fresh = 0 if err else int(res[1][0] or 0)
        self.status.setText(("⚠ " + errors[0][:120]) if errors else (self.offline_text(offline) or tr("Synchronisé à ") + time.strftime("%H:%M")))
        self.reload()
        self._update_counts()
        self.p2p_footer()
        self.notify_new_mail(fresh if getattr(self, "_synced_once", False) else 0)
        self._synced_once = True
        self.check_followups()
        self.ai_after_sync()                                 # pastilles des dossiers de rangement (non lus annoncés par le serveur)


def _keyring_hint():
    """Le mot de passe des comptes vit dans le trousseau du système : sans le module « keyring » (venv isolé), la connexion échoue."""
    try:
        import keyring  # noqa: F401
    except Exception:
        sys.stderr.write("MintMail : module « keyring » absent de cet environnement Python — les mots de passe enregistrés (trousseau) "
                         "sont introuvables. Installez-le : pip install keyring (ou recréez le venv avec --system-site-packages).\n")


def run(argv=None):
    _keyring_hint()
    app = QApplication.instance() or QApplication(list(argv if argv is not None else sys.argv))
    from . import ui_svg
    ui_svg.install()                                      # rendu des logos SVG des signatures (sans QtSvg : simplement non affichés)
    app.setApplicationName("mintmail")                    # = StartupWMClass du lanceur : bonne icône dans la barre des tâches (X11)
    app.setApplicationDisplayName(APP_NAME)
    app.setDesktopFileName(AI.DESKTOP_ID)                  # idem sous Wayland
    app.setWindowIcon(AI.load())
    win = MainWindow()
    win.show()
    QTimer.singleShot(0, lambda: QD.end_start(QD.start_marker(str(DATA_DIR))))       # la fenêtre est arrivée jusqu'à l'écran : le démarrage a réussi
    return app.exec()
