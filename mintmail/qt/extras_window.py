"""Fenêtre principale Qt — fonctions reprises de l'ancienne interface : gestion des dossiers (clic droit), recherche sur le serveur,
épingles envoyées vers la boîte, journal d'erreurs, plein écran, copie d'adresse. Mélangé à MainWindow (voir window.py) ;
la logique est dans folderops.py / maintenance.py, testée sans Qt."""
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QInputDialog, QMenu, QMessageBox, QPlainTextEdit, QVBoxLayout

from ..i18n import tr
from . import folderops as FO
from . import maintenance as MT
from .ui_widgets import AccountRole, KindRole, NameRole


class ExtrasMixin:
    # ------------------------------------------------------------ dossiers
    def folder_menu(self, item, global_pos):
        """Clic droit sur un dossier ou sur un compte de la barre latérale. Retourne True si un menu a été affiché."""
        if item is None or item.data(KindRole) not in ("folder", "account"):
            return False
        aid = item.data(AccountRole)
        if not aid:
            return False
        entry = FO.entry_of(self.engine, aid, item.data(NameRole)) if item.data(KindRole) == "folder" else None
        actions = {"sync": lambda: self.sync_folder(aid, entry), "new": lambda: self.folder_create(aid, None),
                   "sub": lambda: self.folder_create(aid, entry), "rename": lambda: self.folder_rename(aid, entry),
                   "delete": lambda: self.folder_delete(aid, entry), "refresh": self.refresh_folder_list}
        menu = QMenu(self)
        for key in FO.menu_plan(entry):
            menu.addAction(FO.label_of(key), actions[key])
        menu.exec(global_pos)
        return True

    def _folder_job(self, fn):
        def done(text, err):
            self.say(("⚠ " + tr("Dossier : %s") % str(err)[:100]) if err else (text or ""))
            self._build_sidebar(self.view_key)                    # l'arbre local est déjà à jour (créé, renommé ou supprimé)
        self.run_bg(fn, done)

    def refresh_folder_list(self, quiet=False):
        if not quiet:
            self.say(tr("Actualiser la liste des dossiers") + "…")
        self._background(self.engine.refresh_folders, "folders")

    def sync_folder(self, aid, entry):
        """Actualise ce dossier seulement (hors boîte et envoyés, déjà couverts par l'actualisation générale)."""
        from .viewmodel import dest_of
        dest = dest_of(entry)
        self.say(tr("Synchronisation…"))
        self.run_bg(lambda: self.engine.sync(folders=(dest,)), lambda _r, err: (self.say("⚠ " + str(err)[:120]) if err else self.say(""), self.reload()))

    def folder_create(self, aid, parent):
        label = tr("Nom du dossier") + (tr(" (dans « %s »)") % (parent.get("label") or parent["name"]) if parent else "")
        name, ok = QInputDialog.getText(self, tr("Nouveau dossier"), label)
        if not ok or not name.strip():
            return
        clean, err = FO.check_name(name, parent)
        if err:
            self.say(err)
            return
        self._folder_job(lambda: FO.create(self.engine, aid, clean, parent))

    def folder_rename(self, aid, entry):
        cur = entry.get("label") or entry["name"]
        name, ok = QInputDialog.getText(self, tr("Renommer le dossier"), tr("Nouveau nom"), text=cur)
        if not ok or not name.strip() or name.strip() == cur:
            return
        self._folder_job(lambda: FO.rename(self.engine, aid, entry, name.strip()))

    def folder_delete(self, aid, entry):
        box = QMessageBox(QMessageBox.Warning, tr("Supprimer…"), tr("Supprimer le dossier « %s » ?") % (entry.get("path") or entry["name"]), parent=self)
        box.setInformativeText(tr("Les messages qu'il contient seront supprimés du serveur."))
        yes = box.addButton(tr("Supprimer"), QMessageBox.DestructiveRole)
        box.addButton(tr("Annuler"), QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is not yes:
            return
        if self.view_key == "f:" + entry["name"]:
            self.select_view("inbox")
        self._folder_job(lambda: FO.delete(self.engine, aid, entry))

    # ------------------------------------------------------------ recherche sur le serveur
    def search_server_now(self):
        text = self.search.text().strip()
        if text.startswith("?") or not text or not [a for a in self.engine.accounts() if not a.get("demo")]:
            self.say(tr("Saisissez d'abord une recherche (compte réel requis)."))
            return
        self.say(tr("Recherche sur le serveur…"))

        def done(n, err):
            self.say(("⚠ " + tr("Recherche serveur : %s") % str(err)[:90]) if err else MT.server_search_text(n))
            self.reload()
        self.run_bg(lambda: MT.search_server(self.engine, text, self.view_key), done)

    # ------------------------------------------------------------ épingles
    def push_local_pins(self, quiet=False):
        """Envoie vers la boîte les épingles faites sur ce poste : les autres postes les verront."""
        self.run_bg(lambda: MT.push_pins(self.engine), lambda n, err: None if quiet else self.say(("⚠ " + str(err)[:100]) if err else MT.pins_text(n or 0)))

    def after_sync_pins(self):
        """Après une synchronisation : mémorise ce que le serveur garde, envoie une fois les épingles locales des comptes concernés."""
        for aid in MT.save_pin_states(self.engine):
            self.run_bg(lambda aid=aid: MT.push_pins(self.engine, aid), lambda _r, _e: None)

    # ------------------------------------------------------------ divers
    def show_log(self):
        d = QDialog(self)
        d.setWindowTitle(tr("Journal d'erreurs"))
        d.resize(760, 440)
        lay = QVBoxLayout(d)
        view = QPlainTextEdit(MT.log_text())
        view.setReadOnly(True)
        view.setStyleSheet("font-family: monospace;")
        lay.addWidget(view)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(d.reject)
        bb.button(QDialogButtonBox.Close).setText(tr("Fermer"))
        lay.addWidget(bb)
        d.exec()

    def toggle_fullscreen(self):
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    def copy_text(self, text):
        QGuiApplication.clipboard().setText(text)
        self.say(tr("Copié : ") + text)
