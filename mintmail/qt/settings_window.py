"""Paramètres Qt : comptes (IMAP/SMTP, connexion OAuth Gmail / Microsoft, test, suppression) et apparence / messagerie.
Toute la logique (validation, enregistrement, test) est dans accounts.py, testée sans Qt."""
import threading

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMenu, QMessageBox, QPushButton, QSpinBox, QTabWidget, QVBoxLayout, QWidget)

from .. import oauth
from ..i18n import tr
from ..style import ACCENTS, STYLES
from . import accounts as A
from . import assistant as AS
from . import automation as AU
from . import gestures as GS
from . import imagetrust as IT
from . import ui_personal as UP
from . import ui_calendar as UC
from . import ui_sync as US
from .gestures import LAYOUTS
from .. import __version__, updater


class _Signals(QObject):
    ai_say = Signal(str, bool)
    ai_models = Signal(object, str)
    say = Signal(str, bool)
    oauth_done = Signal(object, str)


class SettingsDialog(QDialog):
    def __init__(self, main):
        super().__init__(main)
        self.main, self.cfg = main, main.config
        self.setWindowTitle(tr("Paramètres"))
        self.resize(860, 620)
        self.sig = _Signals()
        self.sig.say.connect(self._say)
        self.sig.ai_say.connect(self._ai_say)
        self.sig.ai_models.connect(self._ai_models)
        self.sig.oauth_done.connect(self._oauth_done)
        self.current, self._oauth, self._oauth_token = {}, None, None
        tabs = QTabWidget()
        tabs.addTab(self._accounts_tab(), tr("Comptes"))
        tabs.addTab(self._look_tab(), tr("Apparence"))
        tabs.addTab(self._filters_tab(), tr("Filtres & blocage"))
        tabs.addTab(self._ai_tab(), "✨ IA")
        tabs.addTab(self._updates_tab(), tr("Mises à jour"))
        tabs.addTab(self._gestures_tab(), tr("Gestes & disposition"))
        tabs.addTab(UP.signatures_tab(self), tr("Signatures"))
        tabs.addTab(UP.identities_tab(self), tr("Identités d'envoi"))
        tabs.addTab(UP.templates_tab(self), tr("Modèles de réponse"))
        tabs.addTab(UP.contacts_tab(self), tr("Contacts"))
        tabs.addTab(UC.calendar_tab(self), tr("Agenda"))
        tabs.addTab(US.p2p_tab(self), tr("Synchronisation"))
        self.tabs = tabs
        close = QPushButton(tr("Fermer"))
        close.clicked.connect(self.accept)
        lay = QVBoxLayout(self)
        lay.addWidget(tabs, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(close)
        lay.addLayout(row)
        self._reload_accounts()

    def open_page(self, page):
        """Ouvre l'onglet demandé (par l'assistant ou « réglages de l'IA ») : accounts, look, filters ou ai."""
        idx = {"accounts": 0, "look": 1, "appearance": 1, "filters": 2, "ai": 3, "updates": 4, "gestures": 5, "layout": 5, "sig": 6, "signatures": 6, "identities": 7, "templates": 8, "contacts": 9, "calendar": 10, "agenda": 10, "p2p": 11, "sync": 11}.get(page)
        if idx is not None:
            self.tabs.setCurrentIndex(idx)

    # ------------------------------------------------------------ comptes
    def _accounts_tab(self):
        w = QWidget()
        h = QHBoxLayout(w)
        left = QVBoxLayout()
        self.acc_list = QListWidget()
        self.acc_list.setFixedWidth(220)
        self.acc_list.currentRowChanged.connect(self._acc_selected)
        add = QPushButton(tr("＋ Ajouter un compte"))
        add.clicked.connect(self._add_account)
        left.addWidget(self.acc_list, 1)
        left.addWidget(add)
        h.addLayout(left)
        form = QFormLayout()
        self.f_preset = QComboBox()
        for key, label in A.preset_choices():
            self.f_preset.addItem(label, key)
        self.f_preset.setCurrentIndex(-1)
        self.f_preset.currentIndexChanged.connect(self._preset)
        self.f_name, self.f_email, self.f_user = QLineEdit(), QLineEdit(), QLineEdit()
        self.f_pass = QLineEdit()
        self.f_pass.setEchoMode(QLineEdit.Password)
        self.f_ihost, self.f_iport, self.f_shost, self.f_sport = QLineEdit(), QSpinBox(), QLineEdit(), QSpinBox()
        for sp in (self.f_iport, self.f_sport):
            sp.setRange(1, 65535)
        self.f_ssl = QCheckBox(tr("IMAP en SSL/TLS direct (port 993)"))
        form.addRow(tr("Fournisseur"), self.f_preset)
        form.addRow(tr("Nom affiché"), self.f_name)
        form.addRow(tr("Adresse e-mail"), self.f_email)
        form.addRow(tr("Identifiant"), self.f_user)
        form.addRow(tr("Mot de passe"), self.f_pass)
        form.addRow(tr("Serveur IMAP"), self.f_ihost)
        form.addRow(tr("Port IMAP"), self.f_iport)
        form.addRow(tr("Serveur SMTP"), self.f_shost)
        form.addRow(tr("Port SMTP"), self.f_sport)
        form.addRow("", self.f_ssl)
        self.oauth_btn = QPushButton()
        self.oauth_btn.clicked.connect(self._oauth_login)
        self.test_btn, self.save_btn, self.rm_btn = QPushButton(tr("Tester la connexion")), QPushButton(tr("Enregistrer")), QPushButton(tr("Supprimer ce compte"))
        self.save_btn.setObjectName("primary")
        self.test_btn.clicked.connect(self._test)
        self.save_btn.clicked.connect(self._save)
        self.rm_btn.clicked.connect(self._remove)
        btns = QHBoxLayout()
        for b in (self.oauth_btn, self.test_btn, self.save_btn, self.rm_btn):
            btns.addWidget(b)
        self.status = QLabel()
        self.status.setWordWrap(True)
        note = QLabel(tr("Gmail / Yahoo / iCloud : créez un « mot de passe d'application » dans les paramètres de sécurité du compte."))
        note.setWordWrap(True)
        note.setObjectName("dim")
        right = QVBoxLayout()
        right.addLayout(form)
        right.addLayout(btns)
        right.addWidget(self.status)
        right.addWidget(note)
        right.addStretch(1)
        h.addLayout(right, 1)
        return w

    def _say(self, text, error=False):
        self.status.setText(text)
        self.status.setStyleSheet("color:#e5484d" if error else "")

    def _reload_accounts(self, select=None):
        self.acc_list.blockSignals(True)
        self.acc_list.clear()
        for a in self.cfg["accounts"]:
            it = QListWidgetItem(a.get("name") or a["email"])
            it.setData(Qt.UserRole, a)
            self.acc_list.addItem(it)
        self.acc_list.blockSignals(False)
        row = next((i for i, a in enumerate(self.cfg["accounts"]) if a["id"] == select), 0) if self.cfg["accounts"] else -1
        self.acc_list.setCurrentRow(row)
        if row < 0:
            self._acc_selected(-1)

    def _acc_selected(self, row):
        it = self.acc_list.item(row) if row >= 0 else None
        a = it.data(Qt.UserRole) if it else None
        self.current = dict(a) if a else {}
        a = self.current
        self.f_preset.blockSignals(True)
        self.f_preset.setCurrentIndex(-1)
        self.f_preset.blockSignals(False)
        self.f_name.setText(a.get("name", ""))
        self.f_email.setText(a.get("email", ""))
        self.f_user.setText(a.get("username", ""))
        self.f_pass.clear()
        self.f_pass.setPlaceholderText(tr("Enregistré — laisser vide pour le conserver") if a.get("email") and a.get("has_password", True) else tr("Mot de passe"))
        self.f_ihost.setText(a.get("imap_host", ""))
        self.f_iport.setValue(int(a.get("imap_port", 993)))
        self.f_shost.setText(a.get("smtp_host", ""))
        self.f_sport.setValue(int(a.get("smtp_port", 587)))
        self.f_ssl.setChecked(a.get("imap_ssl", True))
        self._oauth = a.get("oauth_provider") if a.get("auth") == "oauth2" else None
        self._oauth_token = None
        self.rm_btn.setEnabled(bool(a.get("id")))
        self._say("")
        self._oauth_ui()

    def _add_account(self):
        self.acc_list.blockSignals(True)
        self.acc_list.clearSelection()
        self.acc_list.setCurrentRow(-1)
        self.acc_list.blockSignals(False)
        self._acc_selected(-1)
        self.f_preset.setCurrentIndex(0)
        self.f_email.setFocus()

    def _preset(self, _i):
        key = self.f_preset.currentData()
        p = A.apply_preset(key)
        self._oauth = p.get("oauth")
        self._oauth_token = None
        if p:
            self.f_ihost.setText(p["imap_host"])
            self.f_iport.setValue(p["imap_port"])
            self.f_shost.setText(p["smtp_host"])
            self.f_sport.setValue(p["smtp_port"])
        self._oauth_ui()

    def _oauth_ui(self):
        prov = oauth.PROVIDERS.get(self._oauth or "")
        self.oauth_btn.setVisible(bool(prov))
        self.f_pass.setEnabled(not prov)
        if prov:
            connected = bool(self._oauth_token) or bool(self.current.get("auth") == "oauth2" and self.current.get("has_password", True)
                                                        and self.cfg.password(self.current.get("id", "")))
            self.oauth_btn.setText(tr("🔑 Reconnecter avec %s") % prov["label"] if connected else tr("🔑 Se connecter avec %s") % prov["label"])
            self.f_pass.setPlaceholderText(tr("Connexion OAuth : pas de mot de passe"))

    def _form(self):
        return dict(name=self.f_name.text(), email=self.f_email.text(), username=self.f_user.text(), imap_host=self.f_ihost.text(),
                    imap_port=self.f_iport.value(), smtp_host=self.f_shost.text(), smtp_port=self.f_sport.value(), imap_ssl=self.f_ssl.isChecked())

    def _collect(self):
        a, err = A.collect(self.current, self._form(), self._oauth)
        if err:
            self._say(err, True)
        return a

    def _test(self):
        a = self._collect()
        if not a:
            return
        typed = self._oauth_token or self.f_pass.text()
        if not typed and not a.get("has_password", True):
            self._say(tr("Saisissez le mot de passe (ou mot de passe d'application)."), True)
            return
        self._say(tr("Test de connexion en cours…"))

        def work():
            err = A.test_account(self.cfg, a, typed)
            self.sig.say.emit(tr("Connexion réussie (IMAP + SMTP).") if not err else err, bool(err))
        threading.Thread(target=work, daemon=True).start()

    def _save(self):
        a = self._collect()
        if not a:
            return
        first = not [x for x in self.cfg["accounts"] if not x.get("demo")]
        err = A.save_account(self.cfg, self.main.cache, a, self._oauth_token or self.f_pass.text(), self._oauth)
        if err:
            self._say(err, True)
            return
        self.main.accounts_changed()
        self._reload_accounts(select=a["id"])
        self._say(tr("Compte enregistré. Synchronisation en cours…"))

    def _remove(self):
        aid = self.current.get("id")
        if not aid or not any(x["id"] == aid for x in self.cfg["accounts"]):
            return
        box = QMessageBox(QMessageBox.Question, tr("Paramètres"), tr("Supprimer ce compte de MintMail ?"), parent=self)
        box.setInformativeText(tr("Les messages en cache seront effacés. Vos mails restent sur le serveur."))
        yes = box.addButton(tr("Supprimer"), QMessageBox.DestructiveRole)
        box.addButton(tr("Annuler"), QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is yes:
            A.remove_account(self.cfg, self.main.cache, aid)
            self.main.accounts_changed()
            self._reload_accounts()

    # -- OAuth (Gmail, Microsoft)
    def _oauth_client_dialog(self, provider):
        prov = oauth.PROVIDERS[provider]
        cur = oauth.client_for(self.cfg, provider)
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("Configurer %s — une seule fois") % prov["label"])
        lay = QVBoxLayout(dlg)
        note = QLabel(tr("MintMail ne peut pas créer cet identifiant à votre place (Google exige que ce soit vous, connecté à votre compte). "
                         "Suivez les étapes ci-dessous : chaque bouton ouvre la bonne page. Ensuite, collez l'ID client et le secret. "
                         "C'est à faire UNE FOIS : le réglage se synchronise avec vos autres machines (ou voir l'aide F1 pour le déployer "
                         "sur plusieurs postes)."))
        note.setWordWrap(True)
        lay.addWidget(note)
        for i, (text, url) in enumerate(oauth.WIZARD.get(provider, []), 1):
            row = QHBoxLayout()
            lab = QLabel("%d. %s" % (i, text))
            lab.setWordWrap(True)
            b = QPushButton(tr("Ouvrir ↗"))
            b.clicked.connect(lambda _c=False, u=url: QDesktopServices.openUrl(QUrl(u)))
            row.addWidget(lab, 1)
            row.addWidget(b)
            lay.addLayout(row)
        cid, secret = QLineEdit(cur.get("client_id", "")), QLineEdit(cur.get("client_secret", ""))
        cid.setPlaceholderText(tr("ID client"))
        secret.setPlaceholderText(tr("Secret client (facultatif selon le fournisseur)"))
        lay.addWidget(cid)
        lay.addWidget(secret)
        bb = QDialogButtonBox()
        bb.addButton(tr("Annuler"), QDialogButtonBox.RejectRole)
        bb.addButton(tr("Enregistrer"), QDialogButtonBox.AcceptRole)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        ok = dlg.exec() == QDialog.Accepted and cid.text().strip()
        if ok:
            clients = dict(self.cfg.get("oauth_clients") or {})
            clients[provider] = {"client_id": cid.text().strip(), "client_secret": secret.text().strip()}
            self.cfg["oauth_clients"] = clients
            self.cfg.save()
        return bool(ok)

    def _oauth_login(self):
        provider = self._oauth
        if not provider:
            return
        client = oauth.client_for(self.cfg, provider)
        if not client.get("client_id") and not self._oauth_client_dialog(provider):
            return
        client = oauth.client_for(self.cfg, provider)
        self._say(tr("Connexion dans le navigateur… (3 minutes maximum)"))
        self.oauth_btn.setEnabled(False)
        hint = self.f_email.text().strip()

        def work():
            try:
                res, err = oauth.run_loopback_flow(provider, client["client_id"], client.get("client_secret", ""),
                                                   lambda url: QDesktopServices.openUrl(QUrl(url)), login_hint=hint), ""
            except Exception as e:
                res, err = None, str(e)
            self.sig.oauth_done.emit(res, err)
        threading.Thread(target=work, daemon=True).start()

    def _oauth_done(self, res, err):
        self.oauth_btn.setEnabled(True)
        if err:
            self._say(tr("Connexion OAuth : %s") % err, True)
            return
        if not res.get("refresh_token"):
            self._say(tr("Le fournisseur n'a pas renvoyé de jeton durable (réessayez ; Google : consentement requis)."), True)
            return
        self._oauth_token = res["refresh_token"]
        if res.get("email") and not self.f_email.text().strip():
            self.f_email.setText(res["email"])
        if not self.f_user.text().strip():
            self.f_user.setText(self.f_email.text().strip())
        self._oauth_ui()
        self._say(tr("Connecté ✔ — cliquez sur « Enregistrer »."))

    # ------------------------------------------------------------ apparence et messagerie
    def _gestures_tab(self):
        w = QWidget()
        form = QFormLayout(w)
        intro = QLabel(tr("Faites glisser un message vers la droite ou la gauche (souris, pavé tactile à deux doigts, écran tactile). Un glissement court déclenche l'action principale, un glissement long l'action secondaire."))
        intro.setWordWrap(True)
        intro.setObjectName("dim")
        form.addRow(intro)
        lay = QComboBox()
        for k, label in LAYOUTS:
            lay.addItem(label, k)
        lay.setCurrentIndex(max(0, lay.findData(self.cfg.get("layout"))))
        lay.currentIndexChanged.connect(lambda _i: self.main.set_layout(lay.currentData()))
        form.addRow(tr("Disposition"), lay)
        cur = GS.settings(self.cfg)
        for key, label in (("right", tr("Glisser vers la droite")), ("right_long", tr("… jusqu'au bout (droite)")),
                           ("left", tr("Glisser vers la gauche")), ("left_long", tr("… jusqu'au bout (gauche)"))):
            c = QComboBox()
            for k, v in GS.SWIPE_ACTIONS.items():
                c.addItem(v[0], k)
            c.setCurrentIndex(max(0, c.findData(cur[key])))
            c.currentIndexChanged.connect(lambda _i, c=c, k=key: self._set_swipe(k, c.currentData()))
            form.addRow(label, c)
        for key, label in (("swipe_invert", tr("Inverser le sens au pavé tactile")), ("threads", tr("Regrouper en conversations"))):
            sw = QCheckBox(label)
            sw.setChecked(bool(self.cfg.get(key, key == "threads")))
            sw.toggled.connect(lambda v, k=key: self._set(k, bool(v)))
            form.addRow("", sw)
        return w

    def _set_swipe(self, key, value):
        sw = dict(GS.settings(self.cfg))
        sw[key] = value
        self._set("swipe", sw)

    def _look_tab(self):
        w = QWidget()
        form = QFormLayout(w)
        style = self._combo([(k, v["label"]) for k, v in STYLES.items()], "style")
        mode = self._combo(A.THEMES, "theme")
        dens = self._combo(A.DENSITIES, "density")
        accent = self._combo([(c, n) for n, c in ACCENTS], "accent")
        form.addRow(tr("Style visuel"), style)
        form.addRow(tr("Mode"), mode)
        form.addRow(tr("Densité de la liste"), dens)
        form.addRow(tr("Couleur d'accent"), accent)
        for key, label in (("load_images", tr("Charger les images distantes")), ("notifications", tr("Notifications de bureau"))):
            c = QCheckBox(label)
            c.setChecked(bool(self.cfg.get(key)))
            c.toggled.connect(lambda v, k=key: self._set(k, bool(v)))
            form.addRow("", c)
        for key, label, lo, hi in (("refresh_minutes", tr("Actualiser toutes les (min)"), 1, 120), ("undo_seconds", tr("Délai d'annulation d'envoi (s)"), 0, 30)):
            sp = QSpinBox()
            sp.setRange(lo, hi)
            sp.setValue(int(self.cfg.get(key) or lo))
            sp.valueChanged.connect(lambda v, k=key: self._set(k, int(v)))
            form.addRow(label, sp)
        reset = QPushButton(tr("Rétablir l'apparence et la disposition par défaut"))
        reset.clicked.connect(self._reset_look)
        form.addRow("", reset)
        return w

    # ------------------------------------------------------------ filtres, expéditeurs bloqués, règles
    def _filters_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        self._sender_lists = {}
        for kind, title, hint in (("blocked", tr("Expéditeurs bloqués"), ""),
                                  ("spam_senders", tr("Expéditeurs envoyés en spam"), tr("Leurs messages vont directement dans le dossier Spam.")),
                                  ("image_senders", tr("Expéditeurs dont les images sont toujours chargées"),
                                   tr("Les images distantes de leurs messages s'affichent sans confirmation (adresse ou @domaine)."))):
            lay.addWidget(QLabel("<b>%s</b>" % title))
            if hint:
                lay.addWidget(QLabel(hint))
            lst = QListWidget()
            lst.setMaximumHeight(90)
            self._sender_lists[kind] = lst
            row = QHBoxLayout()
            edit = QLineEdit()
            edit.setPlaceholderText(tr("adresse@exemple.com ou @domaine.com"))
            add, rem = QPushButton(tr("Ajouter")), QPushButton(tr("Retirer"))
            add.clicked.connect(lambda _=False, k=kind, e=edit: self._add_sender(k, e))
            edit.returnPressed.connect(add.click)
            rem.clicked.connect(lambda _=False, k=kind: self._remove_sender(k))
            for x in (edit, add, rem):
                row.addWidget(x, 1 if x is edit else 0)
            lay.addWidget(lst)
            lay.addLayout(row)
        lay.addWidget(QLabel(tr("<b>Règles automatiques</b>")))
        lay.addWidget(QLabel(tr("Appliquées à chaque nouveau message de la boîte de réception.")))
        self._rules = QListWidget()
        lay.addWidget(self._rules, 1)
        row = QHBoxLayout()
        self._r_field, self._r_action = QComboBox(), QComboBox()
        for k, label in AU.RULE_FIELDS:
            self._r_field.addItem(label, k)
        for k, label in AU.RULE_ACTIONS:
            self._r_action.addItem(label, k)
        self._r_text, self._r_folder = QLineEdit(), QLineEdit()
        self._r_folder.setPlaceholderText(tr("dossier (pour « Ranger »)"))
        add = QPushButton(tr("Ajouter la règle"))
        add.clicked.connect(self._add_rule)
        rem = QPushButton(tr("Retirer"))
        rem.clicked.connect(self._remove_rule)
        for x in (self._r_field, self._r_text, self._r_action, self._r_folder, add, rem):
            row.addWidget(x, 1 if x is self._r_text else 0)
        lay.addLayout(row)
        now = QPushButton(tr("Appliquer maintenant à la boîte de réception"))
        now.clicked.connect(self._apply_rules_now)
        lay.addWidget(now)
        self._fill_filters()
        return w

    def _fill_filters(self):
        for kind, lst in self._sender_lists.items():
            lst.clear()
            lst.addItems(list(self.cfg[kind]))
        self._rules.clear()
        fields, actions = dict(AU.RULE_FIELDS), dict(AU.RULE_ACTIONS)
        for r in self.cfg["rules"]:
            txt = "%s « %s » → %s" % (fields.get(r.get("field"), r.get("field")), r.get("text"), actions.get(r.get("action"), r.get("action")))
            self._rules.addItem(txt + ((" " + r.get("folder", "")) if r.get("action") == "move" else ""))

    def _add_sender(self, kind, edit):
        key = edit.text().strip().lower()
        if not key or ("@" not in key):
            return
        if kind == "image_senders":                                      # simple liste de confiance : aucun message n'est déplacé
            IT.trust(self.main.engine.config, key)
            edit.clear()
            self._fill_filters()
            return
        msgs, dest = AU.filter_sender(self.main.engine, key, kind)
        edit.clear()
        self._fill_filters()
        self.main.move_messages(msgs, dest)

    def _remove_sender(self, kind):
        it = self._sender_lists[kind].currentItem()
        if it:
            AU.unfilter_sender(self.main.engine, kind, it.text())
            self._fill_filters()

    def _add_rule(self):
        action, folder = self._r_action.currentData(), self._r_folder.text().strip()
        if action == "move" and not folder:
            self.main.status.setText(tr("Indiquez le dossier de destination"))
            return
        if AU.add_rule(self.main.engine, self._r_field.currentData(), self._r_text.text(), action, folder):
            self._r_text.clear()
            self._fill_filters()

    def _remove_rule(self):
        if AU.remove_rule(self.main.engine, self._rules.currentRow()):
            self._fill_filters()

    def _apply_rules_now(self):
        self.main.apply_rules_now()

    # ------------------------------------------------------------ mises à jour
    def _updates_tab(self):
        w = QWidget()
        form = QFormLayout(w)
        form.addRow(QLabel(tr("Version installée : %s") % __version__))
        auto = QCheckBox(tr("Rechercher automatiquement (au démarrage, puis toutes les heures)"))
        auto.setChecked(bool(self.cfg.get("update_check", True)))
        auto.toggled.connect(lambda v: self._set("update_check", bool(v)))
        form.addRow("", auto)
        repo = QLineEdit(self.cfg.get("update_repo") or updater.DEFAULT_REPO)
        repo.setToolTip(tr("Dépôt GitHub des versions, au format propriétaire/nom"))

        def repo_changed(text):
            v = text.strip()
            if updater.valid_repo(v):
                self.cfg["update_repo"], self.cfg["update_etag"] = v, ""
                self.cfg.save()
        repo.textChanged.connect(repo_changed)
        form.addRow(tr("Dépôt GitHub"), repo)
        self._up_status = QLabel()
        self._up_status.setWordWrap(True)
        form.addRow(self._up_status)
        row = QHBoxLayout()
        self._up_check = QPushButton(tr("Vérifier maintenant"))
        self._up_install = QPushButton(tr("Installer la mise à jour"))
        self._up_install.setObjectName("primary")
        self._up_restart = QPushButton(tr("Relancer maintenant"))
        self._up_restart.setObjectName("primary")
        self._up_check.clicked.connect(lambda: self.main.check_updates(manual=True))
        self._up_install.clicked.connect(lambda: self.main.install_update())
        self._up_restart.clicked.connect(lambda: self.main.restart_app())
        for b in (self._up_check, self._up_install, self._up_restart):
            row.addWidget(b)
        row.addStretch(1)
        form.addRow(row)
        self._up_key = QLabel()
        self._up_key.setObjectName("dim")
        self._up_key.setWordWrap(True)
        form.addRow(self._up_key)
        note = QLabel(tr("Chaque version est signée par SAEC. MintMail refuse tout paquet dont la signature ne correspond pas à la clé de vérification installée avec le programme "
                         "(GitHub ne sert que de transport), refuse de revenir à une ancienne version, et demande votre mot de passe administrateur pour installer. "
                         "Seule une requête anonyme est envoyée à GitHub ; désactivez la recherche automatique si vous préférez ne rien envoyer."))
        note.setObjectName("dim")
        note.setWordWrap(True)
        form.addRow(note)
        self.main.update_views.append(self._updates_refresh)
        self.destroyed.connect(lambda *_: self._updates_refresh in self.main.update_views and self.main.update_views.remove(self._updates_refresh))
        self._updates_refresh()
        return w

    def _updates_refresh(self):
        st = self.main.updates
        self._up_status.setText("\n".join(st.status_lines()))
        pend = updater.restart_pending()
        self._up_install.setVisible(st.update is not None and not pend)
        self._up_install.setEnabled(not st.busy)
        self._up_restart.setVisible(bool(pend) and not st.busy)
        self._up_key.setText(st.key_line())
        self._up_check.setEnabled(not st.busy)

    # ------------------------------------------------------------ intelligence artificielle
    def _ai_tab(self):
        w = QWidget()
        form = QFormLayout(w)
        for key, label, default in AS.AI_SWITCHES:
            c = QCheckBox(label)
            c.setChecked(bool(self.cfg.get(key, default)))
            c.toggled.connect(lambda v, k=key: self._set(k, bool(v)))
            form.addRow("", c)
        for key, label, default, options in AS.AI_CHOICES:
            c = QComboBox()
            for k, v in options:
                c.addItem(v, k)
            i = c.findData(self.cfg.get(key, default))
            c.setCurrentIndex(i if i >= 0 else 0)
            c.currentIndexChanged.connect(lambda _i, c=c, k=key: self._set(k, c.currentData()))
            form.addRow(label, c)
        self._ai_prov = QComboBox()
        for k, (label, _b, _m, _n) in AS.PROVIDERS.items():
            self._ai_prov.addItem(label, k)
        i = self._ai_prov.findData(self.cfg.get("ai_provider", "nvidia"))
        self._ai_prov.setCurrentIndex(max(i, 0))
        form.addRow(tr("Fournisseur"), self._ai_prov)
        has_key = bool(self.cfg.get("ai_has_key") or self.cfg.get("nvidia_api_key"))
        self._ai_key = QLineEdit()
        self._ai_key.setEchoMode(QLineEdit.Password)
        save = QPushButton(tr("Enregistrer la clé"))
        row = QHBoxLayout()
        row.addWidget(self._ai_key, 1)
        row.addWidget(save)
        form.addRow(tr("Clé API"), row)
        self._ai_base, self._ai_model = QLineEdit(), QLineEdit()
        self._ai_base.setText(self.cfg.get("nvidia_api_base") or "")
        self._ai_model.setText(self.cfg.get("ai_model") or "")
        form.addRow(tr("Endpoint API"), self._ai_base)
        form.addRow(tr("Modèle"), self._ai_model)
        detect, test = QPushButton(tr("🔍 Détecter les modèles installés")), QPushButton(tr("Tester la connexion"))
        self._ai_clear = QPushButton(tr("Vider le cache IA (%d éléments)") % self.main.cache.ai_count())
        learn = QPushButton(tr("Oublier mes habitudes de rangement"))
        for b in (detect, test, self._ai_clear, learn):
            form.addRow("", b)
        self._ai_status = QLabel("")
        self._ai_status.setWordWrap(True)
        form.addRow("", self._ai_status)

        def placeholders():
            base, model, needs = AS.set_provider(self.cfg, self._ai_prov.currentData())
            self._ai_base.setPlaceholderText(base or "https://…/v1 (compatible OpenAI)")
            self._ai_model.setPlaceholderText(model or tr("nom du modèle"))
            self._ai_key.setPlaceholderText(tr("Clé enregistrée — saisir pour la remplacer") if has_key or self.cfg.get("ai_has_key") else (
                tr("Clé API NVIDIA (nvapi-…)") if needs else tr("Facultatif (service local : aucune clé nécessaire)")))

        def provider_changed(_i):
            before = self.cfg.get("ai_provider", "nvidia")
            placeholders()
            if before != self.cfg.get("ai_provider"):
                self._ai_base.clear()
                self._ai_model.clear()
        self._ai_prov.currentIndexChanged.connect(provider_changed)
        placeholders()

        def store_key():
            if AS.save_key(self.cfg, self._ai_key.text()):
                self._ai_key.clear()
                self._ai_say(tr("Clé enregistrée dans le trousseau."), False)
                placeholders()
        save.clicked.connect(store_key)
        self._ai_key.returnPressed.connect(store_key)

        def store_base():
            err = AS.save_endpoint(self.cfg, self._ai_base.text())
            if err:
                self._ai_say(err, True)
        self._ai_base.editingFinished.connect(store_base)
        self._ai_model.editingFinished.connect(lambda: (self.cfg.__setitem__("ai_model", self._ai_model.text().strip()), self.cfg.save()))

        def do_test():
            self._ai_say(tr("Test en cours…"), False)
            args = (self._ai_key.text(), self._ai_base.text(), self._ai_model.text())

            def work():
                err, ok = AS.test_connection(self.cfg, *args)
                self.sig.ai_say.emit(tr("Connexion réussie.") if ok else str(err), not ok)
            threading.Thread(target=work, daemon=True).start()
        test.clicked.connect(do_test)

        def do_detect():
            self._ai_say(tr("Recherche des modèles…"), False)
            args = (self._ai_base.text(), self._ai_key.text())

            def work():
                try:
                    self.sig.ai_models.emit(AS.detect_models(self.cfg, *args), "")
                except AS.AIServiceError as e:
                    self.sig.ai_models.emit([], str(e))
            threading.Thread(target=work, daemon=True).start()
        detect.clicked.connect(do_detect)
        self._ai_detect = detect

        def clear():
            self.main.cache.ai_clear()
            self._ai_clear.setText(tr("Vider le cache IA (0 élément)"))
            self.main.reload()
        self._ai_clear.clicked.connect(clear)
        learn.clicked.connect(lambda: (self.main.cache.learn_clear(), self._ai_say(tr("Habitudes de rangement effacées."), False)))
        return w

    def _ai_say(self, text, error):
        self._ai_status.setText(text)
        self._ai_status.setStyleSheet("color: %s;" % ("#dc2626" if error else "#16a34a"))

    def _ai_models(self, names, err):
        if err:
            self._ai_say(err + tr(" — Ollama est-il lancé (ollama serve) et un modèle installé (ollama pull llama3.2) ?"), True)
            return
        menu = QMenu(self)
        for n in names[:40]:
            menu.addAction(n, lambda n=n: (self._ai_model.setText(n), self.cfg.__setitem__("ai_model", n), self.cfg.save()))
        self._ai_say(tr("%d modèle(s) trouvé(s) : choisissez-en un.") % len(names), False)
        menu.exec(self._ai_detect.mapToGlobal(self._ai_detect.rect().bottomLeft()))

    def _combo(self, items, key):
        c = QComboBox()
        for k, label in items:
            c.addItem(label, k)
        i = c.findData(self.cfg.get(key))
        c.setCurrentIndex(i if i >= 0 else 0)
        c.currentIndexChanged.connect(lambda _i, c=c, k=key: self._set(k, c.currentData()))
        return c

    def _set(self, key, value):
        self.cfg[key] = value
        self.cfg.save()
        if key in ("threads", "swipe", "swipe_invert"):
            self.main.reload()
        if key in ("theme", "style", "accent", "density", "load_images"):
            self.main.apply_theme()
            self.main.reload()

    def _reset_look(self):
        A.reset_appearance(self.cfg)
        self.main.apply_theme()
        self.main.reload()
        self.accept()
