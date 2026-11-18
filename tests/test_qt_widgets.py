"""Widgets Qt isolés (sans fenêtre complète) : clic simple / glissé / clic droit de la liste, colonne d'informations. Ignorés sans PySide6 ; offscreen."""
import os, sys, types
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _qt():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PySide6.QtWidgets import QApplication
        from PySide6.QtTest import QTest  # noqa: F401
    except Exception:
        return None
    return QApplication.instance() or QApplication([])


_LIVE = []


def _keep(w):
    """Les widgets de test sont fermés et détruits à la fin du fichier (pas laissés au démontage de Qt, qui peut planter)."""
    _LIVE.append(w)
    return w


def test_zz_cleanup():
    app = _qt()
    if app is None:
        return
    while _LIVE:
        w = _LIVE.pop()
        try:
            w.hide()
            w.deleteLater()
        except RuntimeError:
            pass
    app.processEvents()


def _list(n=5, cfg=None):
    from PySide6.QtGui import QStandardItem, QStandardItemModel
    from mintmail.qt.ui_widgets import MessageList
    cfg = cfg or {"right": "archive", "right_long": "trash", "left": "read", "left_long": "star"}
    d = types.SimpleNamespace(swipe=None, wide=False)
    lst = _keep(MessageList(d, lambda: (cfg, False)))
    model = QStandardItemModel()
    for i in range(n):
        model.appendRow(QStandardItem("ligne %d" % i))
    lst.setModel(model)
    lst.resize(500, 400)
    lst.show()
    lst.swiped_log, lst.clicked_log = [], []
    lst.swiped.connect(lambda r, a: lst.swiped_log.append((r, a)))
    lst.clickedRow.connect(lambda i: lst.clicked_log.append(i.row()))
    return lst


def _send(lst, kind, pos, button, buttons):
    """Événement souris réel avec l'état des boutons (QTest.mouseMove ne garde pas le bouton enfoncé)."""
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication
    kinds = {"press": QEvent.MouseButtonPress, "move": QEvent.MouseMove, "release": QEvent.MouseButtonRelease}
    p = QPointF(pos)
    ev = QMouseEvent(kinds[kind], p, lst.viewport().mapToGlobal(p), button, buttons, Qt.NoModifier)
    QApplication.sendEvent(lst.viewport(), ev)


def _drag(lst, start, dxs):
    from PySide6.QtCore import QPoint, Qt
    _send(lst, "press", start, Qt.LeftButton, Qt.LeftButton)
    for dx in dxs:
        _send(lst, "move", start + QPoint(dx, 0), Qt.NoButton, Qt.LeftButton)
    _send(lst, "release", start + QPoint(dxs[-1], 0), Qt.LeftButton, Qt.NoButton)


def _center(lst, row):
    return lst.visualRect(lst.model().index(row, 0)).center()


def test_simple_click_opens_once_and_does_not_swipe():
    app = _qt()
    if app is None:
        return
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    lst = _list()
    QTest.mouseClick(lst.viewport(), Qt.LeftButton, Qt.NoModifier, _center(lst, 2))
    assert lst.clicked_log == [2] and lst.swiped_log == [] and not lst.mouse_down


def test_right_click_never_opens_the_message():
    app = _qt()
    if app is None:
        return
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    lst = _list()
    QTest.mouseClick(lst.viewport(), Qt.RightButton, Qt.NoModifier, _center(lst, 1))
    assert lst.clicked_log == [] and lst.swiped_log == [] and not lst.mouse_down


def test_drag_right_triggers_action_without_opening():
    app = _qt()
    if app is None:
        return
    lst = _list()
    _drag(lst, _center(lst, 0), [60, 150])
    assert lst.swiped_log == [(0, "archive")] and lst.clicked_log == []


def test_drag_back_to_origin_cancels():
    app = _qt()
    if app is None:
        return
    lst = _list()
    _drag(lst, _center(lst, 0), [200, 5])
    assert lst.swiped_log == [] and lst.clicked_log == []


def test_info_column_scrolls_and_hides_title_without_facts():
    app = _qt()
    if app is None:
        return
    from PySide6.QtWidgets import QLabel
    from mintmail.qt.ui_infocol import InfoColumn
    col = _keep(InfoColumn())
    col.resize(300, 200)
    col.show()
    col.set_facts([("De", "a@x.be"), ("<b>", "x & y")])
    assert col.title.isVisibleTo(col) and "&lt;b&gt;" in col.facts.text()
    col.set_facts([])
    assert not col.title.isVisibleTo(col)
    long = QLabel("mot " * 400)
    long.setWordWrap(True)
    col.add(long)
    col.widget().adjustSize()
    app.processEvents()
    assert col.horizontalScrollBar().maximum() == 0                # jamais de défilement horizontal : le texte se replie


def test_body_split_switches_orientation_with_width():
    app = _qt()
    if app is None:
        return
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QWidget
    from mintmail.qt.ui_infocol import WIDE_MIN, BodySplit, InfoColumn
    sp = _keep(BodySplit(QWidget(), InfoColumn()))
    sp.resize(WIDE_MIN + 200, 500)
    sp.show()
    app.processEvents()
    assert sp.orientation() == Qt.Horizontal
    sp.resize(WIDE_MIN - 300, 500)
    app.processEvents()
    assert sp.orientation() == Qt.Vertical and sp.widget(0) is sp.info


def test_arrows_only_highlight_and_enter_opens():
    app = _qt()
    if app is None:
        return
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    lst = _list()
    lst.highlight_only = True
    seen = []
    lst.selectionModel().currentChanged.connect(lambda cur, _p: seen.append((cur.row(), lst.keynav)))
    lst.setCurrentIndex(lst.model().index(0, 0))
    lst.setFocus()
    QTest.keyClick(lst, Qt.Key_Down)
    QTest.keyClick(lst, Qt.Key_Down)
    assert lst.currentIndex().row() == 2 and lst.clicked_log == []
    assert all(k for r, k in seen[1:])                              # chaque déplacement s'est fait avec le drapeau « touche de navigation »
    QTest.keyClick(lst, Qt.Key_Return)
    assert lst.clicked_log == [2]
    lst.highlight_only = False
    QTest.keyClick(lst, Qt.Key_Up)
    assert lst.currentIndex().row() == 1 and not lst.keynav


def test_quick_reply_bubble_grows_sends_with_ctrl_enter_and_offers_reply_all():
    app = _qt()
    if app is None:
        return
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from mintmail.qt.ui_readercard import QuickReply
    q = _keep(QuickReply())
    q.resize(500, 300)
    q.show()
    sent, full = [], []
    q.send.connect(sent.append)
    q.expand_full.connect(full.append)
    h0 = q.entry.height()
    q.entry.setText("\n".join("ligne %d" % i for i in range(6)))
    app.processEvents()
    assert q.entry.height() > h0 and q.entry.height() <= q.entry.fontMetrics().lineSpacing() * 8 + 40
    q.entry.setText("Bonjour")
    QTest.keyClick(q.entry, Qt.Key_Return)                           # Entrée seule : nouvelle ligne, pas d'envoi
    assert sent == [] and "\n" in q.entry.text()
    QTest.keyClick(q.entry, Qt.Key_Return, Qt.ControlModifier)
    assert sent == ["Bonjour"] and q.entry.text() == ""
    assert not q.reply_all()
    q.set_all_available(True)
    q.all_box.setChecked(True)
    assert q.reply_all()
    q.set_all_available(False)
    assert not q.reply_all()
