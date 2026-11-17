"""Réglages → Intégrations : Teams, Slack, notes Markdown (dossier, Obsidian, Bear), Todoist, Notion. Les clés vont dans le trousseau."""
import threading
from types import SimpleNamespace

from PySide6.QtWidgets import QCheckBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QWidget

from .. import integrations as IG
from ..i18n import tr
from .ui_cards import Page


def _secret_edit(win, key, placeholder):
    e = QLineEdit()
    e.setEchoMode(QLineEdit.Password)
    e.setPlaceholderText(tr("enregistré dans le trousseau") if win.cfg.password(key) else placeholder)
    return e


def _save_secret(win, key, flag, edit):
    text = edit.text().strip()
    if text:
        win.cfg.set_password(key, text)
        edit.clear()
        edit.setPlaceholderText(tr("enregistré dans le trousseau"))
    s = dict(IG.settings(win.cfg))
    s[flag] = bool(win.cfg.password(key))
    win.cfg["integrations"] = s
    win.cfg.save()


def _set(win, key, value):
    s = dict(IG.settings(win.cfg))
    s[key] = value
    win.cfg["integrations"] = s
    win.cfg.save()


def _test_msg():
    import time
    return SimpleNamespace(subject=tr("Test MintMail"), sender_name="MintMail", sender_email="mintmail@localhost", date=time.time(),
                           text=tr("Ceci est un message de test envoyé depuis MintMail."), html="", snippet="")


def integrations_tab(win):
    cfg = win.cfg
    s = IG.settings(cfg)
    page = Page(tr("Intégrations"), tr("Comme dans Spark, envoyez un message vers vos autres outils (clic droit sur un message, ou Ctrl+K). Rien n'est envoyé sans votre geste ; les clés et adresses de webhook sont gardées dans le trousseau du système."))
    note = QLabel("")
    note.setWordWrap(True)

    def say(ok, text):
        note.setText(("✔ " if ok else "✖ ") + text)

    for kind, hint in (("teams", tr("Adresse du webhook entrant de votre canal Teams (Workflows ou connecteur « Incoming Webhook »)")),
                       ("slack", tr("Adresse du webhook entrant Slack (api.slack.com → Incoming Webhooks)"))):
        form = page.card(IG.labels()[kind]).form()
        edit = _secret_edit(win, IG.SECRET_KEYS[kind], hint)
        form.addRow(tr("Adresse du webhook"), edit)
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        save, test = QPushButton(tr("Enregistrer")), QPushButton(tr("Envoyer un test"))
        save.clicked.connect(lambda _c=False, k=kind, e=edit: (_save_secret(win, IG.SECRET_KEYS[k], k, e), say(True, tr("Enregistré"))))
        test.clicked.connect(lambda _c=False, k=kind, e=edit: _run_test(win, say, lambda: IG.send_webhook(
            k, e.text().strip() or win.cfg.password(IG.SECRET_KEYS[k]), _test_msg())))
        rl.addWidget(save)
        rl.addWidget(test)
        rl.addStretch(1)
        form.addRow("", row)
    form = page.card(tr("Notes Markdown")).form()
    folder = QLineEdit(s.get("notes_dir", ""))
    folder.setPlaceholderText(tr("Dossier où enregistrer les notes (ex. ~/Notes)"))
    folder.editingFinished.connect(lambda: _set(win, "notes_dir", folder.text().strip()))
    pick = QPushButton(tr("Choisir…"))
    pick.clicked.connect(lambda: (folder.setText(QFileDialog.getExistingDirectory(win, tr("Dossier des notes")) or folder.text()), _set(win, "notes_dir", folder.text().strip())))
    row = QWidget()
    rl = QHBoxLayout(row)
    rl.setContentsMargins(0, 0, 0, 0)
    rl.addWidget(folder, 1)
    rl.addWidget(pick)
    form.addRow(tr("Dossier"), row)
    vault = QLineEdit(s.get("obsidian_vault", ""))
    vault.setPlaceholderText(tr("Nom du coffre Obsidian (laisser vide pour ne pas l'utiliser)"))
    vault.editingFinished.connect(lambda: _set(win, "obsidian_vault", vault.text().strip()))
    form.addRow("Obsidian", vault)
    bear = QCheckBox(tr("Proposer « Ouvrir dans Bear » (Mac)"))
    bear.setChecked(bool(s.get("bear")))
    bear.toggled.connect(lambda v: _set(win, "bear", bool(v)))
    form.addRow("Bear", bear)
    form = page.card(IG.labels()["todoist"]).form()
    tok = _secret_edit(win, IG.SECRET_KEYS["todoist"], tr("Jeton d'API (Todoist → Paramètres → Intégrations → Développeur)"))
    proj = QLineEdit(s.get("todoist_project", ""))
    proj.setPlaceholderText(tr("Identifiant du projet (facultatif ; sinon la boîte de réception Todoist)"))
    proj.editingFinished.connect(lambda: _set(win, "todoist_project", proj.text().strip()))
    form.addRow(tr("Jeton d'API"), tok)
    form.addRow(tr("Projet"), proj)
    sv = QPushButton(tr("Enregistrer le jeton"))
    sv.clicked.connect(lambda: (_save_secret(win, IG.SECRET_KEYS["todoist"], "todoist", tok), say(True, tr("Enregistré"))))
    form.addRow("", sv)
    form = page.card(IG.labels()["notion"]).form()
    ntok = _secret_edit(win, IG.SECRET_KEYS["notion"], tr("Jeton de l'intégration Notion (notion.so/my-integrations)"))
    db = QLineEdit(s.get("notion_db", ""))
    db.setPlaceholderText(tr("Identifiant de la base de données (la partager avec l'intégration)"))
    db.editingFinished.connect(lambda: _set(win, "notion_db", db.text().strip()))
    form.addRow(tr("Jeton"), ntok)
    form.addRow(tr("Base de données"), db)
    nsv = QPushButton(tr("Enregistrer le jeton"))
    nsv.clicked.connect(lambda: (_save_secret(win, IG.SECRET_KEYS["notion"], "notion", ntok), say(True, tr("Enregistré"))))
    form.addRow("", nsv)
    page.card(tr("Résultat")).add(note)
    return page.finish()


def _run_test(win, say, fn):
    say(True, tr("Envoi du test…"))

    def work():
        try:
            ok, text = fn()
        except Exception as e:                                    # jamais d'exception dans le fil de fond
            ok, text = False, str(e)[:120]
        win.sig.say.emit(("✔ " if ok else "✖ ") + text, not ok)
    threading.Thread(target=work, daemon=True).start()
