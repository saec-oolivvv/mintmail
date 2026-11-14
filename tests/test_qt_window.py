"""Fenêtre Qt : ne tourne que si PySide6 est installé (CI Windows / macOS / Linux) ; ignorée ailleurs. Sans écran (offscreen), lecteur texte par défaut."""
import os, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _qt():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PySide6.QtWidgets import QApplication
    except Exception:
        return None
    return QApplication.instance() or QApplication([])


def _window(demo=True):
    from mintmail.store import Cache, Config
    from mintmail.qt.window import MainWindow
    from mintmail.models import Message
    cfg = Config(os.path.join(tempfile.mkdtemp(), "c.json"))
    cache = Cache(os.path.join(tempfile.mkdtemp(), "c.db"))
    cache.upsert_many([Message(id="q%d" % i, account="demo", folder="inbox", uid=0, sender_name="Expéditeur %d" % i, sender_email="e%d@x.be" % i,
                               subject="Sujet %d" % i, date=time.time() - i, snippet="extrait", text="Bonjour %d" % i,
                               html="<p>Bonjour <b>%d</b></p><script>1</script>" % i, unread=True) for i in range(3)])
    return MainWindow(cfg, cache)


def test_window_lists_messages_and_opens_one_in_the_reader():
    if _qt() is None:
        return
    os.environ["MINTMAIL_QT_NO_WEBENGINE"] = "1"
    w = _window()
    assert w.model.rowCount() >= 3 and w.reader.kind == "text"
    idx = w.model.index(w.model.row_of("q1"))
    w.list.setCurrentIndex(idx)
    assert w.current == "q1" and "Bonjour" in w.reader.toPlainText() and "Sujet 1" in w.head.text()
    assert not w.cache.get("q1").unread                                       # ouvert : marqué lu
    w.folders.setCurrentRow(1)                                                # « Non lus »
    assert w.view_key == "unread" and w.model.row_of("q1") < 0 and w.model.row_of("q0") >= 0
    w.search.setText("introuvable-zzz")
    assert w.model.rowCount() == 0 and not w.empty.isHidden()


def test_reader_never_opens_dangerous_links():
    if _qt() is None:
        return
    from mintmail.htmlsafe import safe_to_open
    assert safe_to_open("javascript:alert(1)") is None and safe_to_open("file:///etc/passwd") is None
    assert safe_to_open("https://saec.me") == "https://saec.me"
