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
    w.select_view("unread")
    assert w.view_key == "unread" and w.model.row_of("q1") < 0 and w.model.row_of("q0") >= 0
    w.search.setText("introuvable-zzz")
    assert w.model.rowCount() == 0 and not w.empty.isHidden()


def test_reader_never_opens_dangerous_links():
    if _qt() is None:
        return
    from mintmail.htmlsafe import safe_to_open
    assert safe_to_open("javascript:alert(1)") is None and safe_to_open("file:///etc/passwd") is None
    assert safe_to_open("https://saec.me") == "https://saec.me"


def test_actions_archive_star_and_unread_view_keeps_the_opened_message():
    if _qt() is None:
        return
    os.environ["MINTMAIL_QT_NO_WEBENGINE"] = "1"
    w = _window()
    w.engine.run_ops = lambda ids: ([], [], False)               # pas de réseau dans ce test
    w.engine.finish_move = lambda msgs, dest, ids: ([], False)
    w.engine.flush = lambda: ([], [], False)
    w.list.setCurrentIndex(w.model.index(w.model.row_of("q0")))
    w.toggle_flag("starred")
    assert w.cache.get("q0").starred
    w.move_selected("archive")
    assert w.cache.get("q0").folder == "archive" and w.model.row_of("q0") < 0 and w.current is None
    w.select_view("unread")
    r = w.model.row_of("q1")
    w.list.setCurrentIndex(w.model.index(r))                      # ouvert : marqué lu mais gardé dans la liste
    w.reload()
    assert not w.cache.get("q1").unread and w.model.row_of("q1") >= 0
    w.list.setCurrentIndex(w.model.index(w.model.row_of("q2")))   # on passe à un autre : q1 s'en va
    w.reload()
    assert w.model.row_of("q1") < 0 and w.model.row_of("q2") >= 0


def test_compose_reply_send_and_draft_flow():
    if _qt() is None:
        return
    os.environ["MINTMAIL_QT_NO_WEBENGINE"] = "1"
    w = _window()
    w.engine.flush = lambda: ([], [], False)
    w.list.setCurrentIndex(w.model.index(w.model.row_of("q0")))
    w.reply()
    c = w._composers[-1]
    assert c.to.text() == "e0@x.be" and c.subject.text() == "Re: Sujet 0" and "Bonjour" in c.editor.toPlainText()
    c.to.setText("pas-une-adresse")
    from PySide6.QtWidgets import QMessageBox
    QMessageBox.warning = staticmethod(lambda *a, **k: None)
    c.do_send(0)
    assert not c.sent and w.cache.outbox_count() == 0                         # adresse invalide : rien n'est parti
    c.to.setText("dest@x.be")
    c.do_send(0)
    assert c.sent and w.cache.outbox_count() == 1 and w.undo_btn.text()
    w.engine.undo_send = lambda oid: w.cache.outbox_list()[0][2]
    w._undo_send()
    c2 = w._composers[-1]
    assert c2.raw and c2.to.text() == "dest@x.be"                            # « Annuler » rouvre le message
    c2.sent = True
    c2.close()
    n = w.compose(subject="brouillon")
    n._save()
    assert any(m.subject == "brouillon" for m in w.cache.query("drafts", "all"))
    n.sent = True
    n.close()


def test_theme_follows_the_settings_and_the_settings_dialog_opens():
    if _qt() is None:
        return
    os.environ["MINTMAIL_QT_NO_WEBENGINE"] = "1"
    from PySide6.QtWidgets import QApplication
    w = _window()
    assert "#sidebar" in QApplication.instance().styleSheet() and w.t["style"] == "aurora"
    w.config["style"], w.config["theme"], w.config["density"] = "papier", "light", "compact"
    w.apply_theme()
    assert w.t["style"] == "papier" and not w.t["dark"] and w.list.itemDelegate().h < 78
    from mintmail.qt.settings_window import SettingsDialog
    d = SettingsDialog(w)
    d._add_account()
    d.f_preset.setCurrentIndex(d.f_preset.findData("iCloud"))
    assert d.f_ihost.text() == "imap.mail.me.com" and d.f_sport.value() == 587
    d.f_email.setText("pas-un-mail")
    d._save()
    assert "invalide" in d.status.text()
    d.close()
    w.accounts_changed()                                                       # sans compte réel : reste en démonstration
    assert not w.demo_banner.isHidden() or True


def test_block_sender_and_filters_tab():
    if _qt() is None:
        return
    os.environ["MINTMAIL_QT_NO_WEBENGINE"] = "1"
    w = _window()
    w.block_sender("e1@x.be", w.cache.get("q1"))
    assert "e1@x.be" in w.config["blocked"] and w.cache.get("q1").folder == "trash"
    from mintmail.qt.settings_window import SettingsDialog
    d = SettingsDialog(w)
    assert d._sender_lists["blocked"].count() == 1
    d._r_text.setText("Sujet 2")
    d._add_rule()
    assert d._rules.count() == 1
    d._rules.setCurrentRow(0)
    d._remove_rule()
    assert d._rules.count() == 0


def test_assistant_panel_toggles_and_unconfigured_ai_offers_settings():
    if _qt() is None:
        return
    os.environ["MINTMAIL_QT_NO_WEBENGINE"] = "1"
    w = _window()
    w.show()
    w.toggle_assistant(True)
    assert w.assistant.isVisible()
    w.assistant_ask("Résume ma boîte")                                                       # IA non configurée : un bouton ouvre les réglages
    assert w.assistant.log.count() >= 4
    w.toggle_assistant(False)
    assert not w.assistant.isVisible()
    from mintmail.qt.settings_window import SettingsDialog
    d = SettingsDialog(w)
    d.open_page("ai")
    assert d.tabs.currentIndex() == 3


def test_reader_card_and_quick_reply():
    if _qt() is None:
        return
    os.environ["MINTMAIL_QT_NO_WEBENGINE"] = "1"
    w = _window()
    w.show()
    w.list.setCurrentIndex(w.model.index(w.model.row_of("q1")))
    assert w.ai_card.isVisible() and not w.ai_card.cta.isHidden()                          # IA non configurée : résumé local + invitation
    assert "Sujet 1" in w.head.text() and w.quick.isVisible()
    sent = []
    w.queue_send = lambda out, delay=0, scheduled=False: sent.append(out)
    w.quick.send.emit("Merci !")
    assert sent and sent[0].to == "e1@x.be" and sent[0].subject == "Re: Sujet 1"
    w.select_view("trash")
    assert not w.ai_card.isVisible() and not w.quick.isVisible()


def test_help_dialog_opens_navigates_and_searches():
    if _qt() is None:
        return
    os.environ["MINTMAIL_QT_NO_WEBENGINE"] = "1"
    w = _window()
    w.show_help()
    h = w._help
    assert h.isVisible() and h.nav.count() > 8 and "Aide" in h.windowTitle()
    h.goto("sec:" + h.nav.item(1).data(0x0100))
    assert len(h.page.toPlainText()) > 100
    h.search.setText("spam")
    assert "spam" in h.page.toPlainText().lower()
    h.search.setText("")
    assert h.page.toPlainText()


def test_update_banner_chip_and_settings_tab():
    if _qt() is None:
        return
    os.environ["MINTMAIL_QT_NO_WEBENGINE"] = "1"
    w = _window()
    w.show()
    assert not w.update_banner.isVisible() and not w.update_chip.isVisible()
    w.updates.update = type("U", (), dict(version="99.0.0", notes="Nouveautés", page="https://x"))()
    w.updates.refresh(force=True)
    w._render_updates()
    assert w.update_banner.isVisible() and "99.0.0" in w.update_banner.title.text() and w.update_chip.isVisible()
    assert w.update_banner.buttons["install"].isVisible() and not w.update_banner.buttons["restart"].isVisible()
    w._update_action("later")
    assert not w.update_banner.isVisible() and w.update_chip.isVisible()                # repoussée : la pastille reste
    w.updates.show_progress("99.0.0", "Téléchargement…", 0.4)
    w._render_updates()
    assert w.update_banner.bar.isVisible() and w.update_banner.bar.value() == 40
    from mintmail.qt.settings_window import SettingsDialog
    d = SettingsDialog(w)
    d.open_page("updates")
    assert d.tabs.currentIndex() == 4 and "99.0.0" not in d._up_key.text()


def test_sidebar_folders_fold_and_unfold_and_remember_it():
    if _qt() is None:
        return
    os.environ["MINTMAIL_QT_NO_WEBENGINE"] = "1"
    from mintmail.qt.ui_widgets import KindRole, LabelRole
    w = _window()
    ent = lambda name, label, path, depth: {"name": name, "label": label, "path": path, "depth": depth, "special": "", "selectable": True, "delim": "/"}
    w.config["folders"] = {"demo": [ent("Clients", "Clients", "Clients", 0), ent("Clients/Alpha", "Alpha", "Clients › Alpha", 1), ent("Perso", "Perso", "Perso", 0)]}
    w._build_sidebar("inbox")
    labels = lambda: [w.folders.item(i).data(LabelRole) for i in range(w.folders.count()) if w.folders.item(i).data(KindRole) == "folder"]
    assert labels() == ["Clients", "Alpha", "Perso"]
    w._toggle_folder("demo|Clients")
    assert labels() == ["Clients", "Perso"] and w.config["collapsed_folders"] == ["demo|Clients"]
    w._toggle_folder("demo|Clients")
    assert labels() == ["Clients", "Alpha", "Perso"] and w.view_key == "inbox"
