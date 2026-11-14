"""Fenêtre principale Qt — IA partout : tri automatique, pastilles et résumé dans la liste, bloc « En bref », brouillons préparés,
recherche en langage naturel (« ? … »), clic droit IA. Mélangé à MainWindow ; la logique est dans aiwork.py (testée sans Qt)."""
import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from .. import sysdeps
from ..i18n import tr
from . import aiwork as AW
from . import assistant as AS
from . import composing as C


class AIMixin:
    # ------------------------------------------------------------ bloc « En bref »
    def build_digest_card(self):
        card = QFrame()
        card.setObjectName("aicard")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(4)
        head = QHBoxLayout()
        title = QLabel(tr("<b>✨ En bref</b>"))
        refresh = QPushButton(tr("Actualiser"))
        refresh.setObjectName("chip")
        refresh.clicked.connect(lambda: self.refresh_digest(force=True))
        hide = QPushButton("✕")
        hide.setObjectName("flat")
        hide.clicked.connect(self._hide_digest)
        head.addWidget(title, 1)
        head.addWidget(refresh)
        head.addWidget(hide)
        lay.addLayout(head)
        self.digest_lbl = QLabel()
        self.digest_lbl.setWordWrap(True)
        self.digest_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.digest_lbl)
        card.hide()
        self.digest_card = card
        self._digest_hidden, self._digest_key = False, None
        return card

    def _hide_digest(self):
        self._digest_hidden = True
        self.digest_card.hide()

    def update_digest_visibility(self):
        show = (self.view_key == "inbox" and not self.search.text().strip() and not self._digest_hidden
                and bool(self.config.get("ai_digest", True)))
        self.digest_card.setVisible(show)
        if show:
            self.refresh_digest()

    def refresh_digest(self, force=False):
        acc = self.account
        key = AW.digest_key(self.engine, acc, datetime.date.today().isoformat())
        if key == self._digest_key and not force:
            return
        self._digest_key = key
        self.digest_lbl.setText(AW.digest_local(self.engine, acc))
        if not AW.enabled(self.engine) or key[0] == 0:
            return
        self.digest_lbl.setText(tr("✨ Analyse de votre boîte…"))

        def done(text, err):
            if self._digest_key != key:
                return
            local = AW.digest_local(self.engine, acc)
            self.digest_lbl.setText(local + (tr("  (IA : %s)") % str(err)[:60]) if err else text)
        self.run_bg(lambda: AW.digest_ai(self.engine, acc, force), done)

    # ------------------------------------------------------------ tri automatique après chaque synchronisation
    def ai_after_sync(self):
        if not AW.enabled(self.engine) or getattr(self, "_triaging", False):
            return
        msgs = AW.to_triage(self.engine, self.account)
        if not msgs:
            return
        self._triaging = True

        def done(res, err):
            self._triaging = False
            if err or not res:
                return
            self.reload()
            urgent = AW.urgent(msgs, res)
            if urgent and self.config.get("notifications", True) and not self.isActiveWindow():
                sysdeps.notify(tr("✨ %d message(s) important(s)") % len(urgent),
                               "\n".join("%s — %s" % (m.display_sender, m.subject) for m in urgent[:3]))
            cands = AW.prepare_candidates(self.config, self.cache, msgs, res)
            if cands:
                self._prepare(cands)
        self.run_bg(lambda: AW.triage(self.engine, msgs), done)

    def _prepare(self, cands):
        if getattr(self, "_preparing", False):
            return
        self._preparing = True

        def done(n, err):
            self._preparing = False
            if n:
                self.reload()
                self.status.setText(tr("✨ %d brouillon(s) de réponse prêt(s) dans Brouillons — à relire avant envoi") % n)
        self.run_bg(lambda: AW.prepare_drafts(self.engine, cands, lambda m: C.addressed_identity(self.config, m)), done)

    # ------------------------------------------------------------ recherche en langage naturel
    def ai_search(self, text):
        if not AW.ai_query_text(text):
            return
        if not AW.enabled(self.engine):
            self.status.setText(tr("IA non configurée : Paramètres → IA."))
            return self.show_settings(page="ai")
        self.status.setText(tr("✨ Recherche : « %s »") % AW.ai_query_text(text)[:50])

        def done(q, err):
            if err:
                self.status.setText(tr("Erreur IA : %s") % str(err)[:90])
            else:
                self.search.setText(q)
                self.status.setText(tr("Recherche : %s") % q)
        self.run_bg(lambda: AW.nl_search(self.engine, text), done)

    # ------------------------------------------------------------ clic droit
    def add_ai_menu(self, menu, msg):
        menu.addSeparator()
        for it in AW.context_items(self.engine, msg, self.account):
            if it is None:
                menu.addSeparator()
            elif it[0] == "sub":
                sub = menu.addMenu(it[1])
                for k, label in it[2]:
                    sub.addAction(label, lambda _c=False, k=k: self.run_ai(k, msg))
            else:
                menu.addAction(it[1], lambda _c=False, k=it[0]: self.run_ai(k, msg))

    def run_ai(self, key, m):
        head, _, arg = key.partition(":")
        full = self.cache.get(m.id) or m
        if head == "ai_enable":
            return self.show_settings(page="ai")
        if head == "notspam":
            return self.not_spam_selected()
        if head in ("summarize", "translate"):
            return self._run_cmd(key, m)
        if not AW.enabled(self.engine):
            return self.show_settings(page="ai")
        if head == "ai_notspam_file":
            self.focus_message(m)
            return self._on_ai_action("not_spam_file", arg)
        if head == "ai_file":
            return self._file_into_folder([m], m.account, arg)
        if head == "ai_suggest":
            self.status.setText(tr("✨ Recherche du meilleur dossier…"))

            def done(r, err):
                folder, new = r if r else (None, False)
                if err:
                    self.status.setText(tr("Erreur IA : %s") % str(err)[:90])
                elif not folder:
                    self.status.setText(tr("✨ Cette conversation peut rester dans la boîte de réception."))
                else:
                    self.status.setText(tr("✨ Suggestion : « %s »%s") % (folder, tr(" (nouveau dossier)") if new else ""))
                    self._file_into_folder([m], m.account, folder) if self._confirm_ai(
                        tr("Ranger ce message dans « %s » ?") % folder) else None
            return self.run_bg(lambda: AW.suggest_folder(self.engine, m), done)
        if head in ("ai_classify_sender", "ai_classify_inbox"):
            msgs = (self.cache.by_sender(m.sender_email.lower(), ("inbox", "archive")) or [m]) if head == "ai_classify_sender" \
                else self.cache.query("inbox", self.account, limit=60)
            return self._assistant_run({"action": {"type": "classify"}, "msgs": msgs})
        if head == "ai_rule":
            if AW.add_rule_move(self.config, m, arg):
                self.status.setText(tr("Règle créée : les messages de %s iront dans « %s »") % (m.sender_email, arg))
            return
        if head == "ai_tasks":
            return self.tasks_from_message(full)
        if head == "ai_reply":
            idea = AW.reply_idea(key)
            self.status.setText(tr("✨ Rédaction de la réponse…"))
            from . import readerai as RA

            def done2(text, err):
                if err:
                    self.status.setText(tr("Erreur IA : %s") % str(err)[:90])
                else:
                    self.status.setText("")
                    self.compose(**dict(C.reply_args(self.config, self.engine.accounts(), full, False,
                                                     self.engine.default_account(full, self.account)), ai_suggested_text=text))
            return self.run_bg(lambda: RA.draft(self.engine, full, idea), done2)
        if head == "ai_thread":
            self.focus_message(m)
            self.ai_card.working(tr("Résumé de la conversation (%d messages)…") % AW.thread_size(self.engine, full))
            return self.run_bg(lambda: AW.thread_summary(self.engine, full),
                               lambda t, e: self.ai_card.text(tr("Conversation"), (tr("Erreur IA : %s") % str(e)[:100]) if e else t)
                               if self._same(m) else None)
        if head == "ai_event":
            ev = AW.event_of(self.engine, full)
            if ev:
                self.calendar_add(ev, "mintmail-" + m.id)
            else:
                self.status.setText(tr("Aucun rendez-vous détecté dans ce message."))
            return
        if head == "ai_about":
            self.focus_message(m)
            self.toggle_assistant(True)
            self.assistant.entry.setText(tr("À propos de ce message : "))
            self.assistant.focus_entry()

    def _confirm_ai(self, text):
        from PySide6.QtWidgets import QMessageBox
        return QMessageBox.question(self, tr("✨ IA"), text) == QMessageBox.Yes
