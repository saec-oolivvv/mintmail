"""Réglages → Maintenance : sauvegarde, restauration, contrôle de la base, rapport de diagnostic."""
import time

from PySide6.QtWidgets import QFileDialog, QLabel, QMessageBox, QPushButton

from .. import APP_NAME, __version__
from .. import backup as BK
from ..i18n import tr
from ..store import CONFIG_DIR, DATA_DIR
from .ui_cards import Page


def maintenance_tab(win):
    page = Page(tr("Maintenance"), tr("Sauvegardez vos réglages et votre cache, restaurez-les, ou vérifiez que tout est en bon état. Les mots de passe restent dans le trousseau du système : ils ne sont pas dans la sauvegarde."))
    card = page.card(tr("Sauvegarde"))
    info = QLabel()
    info.setObjectName("dim")
    info.setWordWrap(True)
    card.addWidget(info)

    def refresh():
        last = BK.list_backups(DATA_DIR)
        info.setText(tr("Dossier des sauvegardes : %s") % BK.default_dir(DATA_DIR) + ("\n" + tr("Dernière : %s") % last[0].name if last else ""))

    def make():
        name = "mintmail-backup-%s.zip" % time.strftime("%Y%m%d-%H%M%S")
        path, _ = QFileDialog.getSaveFileName(win, tr("Créer une sauvegarde"), str(BK.default_dir(DATA_DIR) / name), "ZIP (*.zip)")
        if not path:
            return
        try:
            out = BK.create(CONFIG_DIR, DATA_DIR, path, __version__)
            QMessageBox.information(win, APP_NAME, tr("Sauvegarde créée : %s") % out)
        except OSError as e:
            QMessageBox.warning(win, APP_NAME, tr("Impossible de créer la sauvegarde : %s") % e)
        refresh()

    def restore():
        path, _ = QFileDialog.getOpenFileName(win, tr("Restaurer une sauvegarde"), str(BK.default_dir(DATA_DIR)), "ZIP (*.zip)")
        if not path:
            return
        try:
            man = BK.inspect(path)
        except ValueError:
            QMessageBox.warning(win, APP_NAME, tr("Ce fichier n'est pas une sauvegarde MintMail valide."))
            return
        if QMessageBox.question(win, APP_NAME, tr("Restaurer la sauvegarde du %s ? L'état actuel est d'abord sauvegardé, puis MintMail doit être relancé.") % (man.get("date") or "?")) != QMessageBox.Yes:
            return
        try:
            res = BK.restore(path, CONFIG_DIR, DATA_DIR, __version__)
        except (OSError, ValueError) as e:
            QMessageBox.warning(win, APP_NAME, tr("La restauration a échoué : %s") % e)
            return
        QMessageBox.information(win, APP_NAME, tr("Restauration terminée. L'état précédent est gardé dans : %s\n\nFermez puis relancez MintMail.") % res["safety"])
        refresh()

    b1, b2 = QPushButton(tr("Créer une sauvegarde…")), QPushButton(tr("Restaurer une sauvegarde…"))
    b1.clicked.connect(make)
    b2.clicked.connect(restore)
    card.addWidget(b1)
    card.addWidget(b2)

    health = page.card(tr("Santé"), tr("Contrôle la base de messages et le fichier de réglages. Rien n'est supprimé : en cas de problème, le fichier est mis de côté."))
    result = QLabel()
    result.setWordWrap(True)
    result.setObjectName("dim")

    def check():
        ok_db, ok_cfg = BK.check_db(DATA_DIR / "cache.db"), BK.check_config(CONFIG_DIR / "config.json")
        result.setText(tr("Base de messages : %s — Réglages : %s") % (tr("saine") if ok_db else tr("endommagée (réparée au prochain démarrage)"), tr("sains") if ok_cfg else tr("illisibles (restaurez une sauvegarde)")))

    def diagnose():
        from ..diagnose import build_report
        from ..log import tail
        path, _ = QFileDialog.getSaveFileName(win, tr("Enregistrer le rapport"), str(DATA_DIR / "diagnostic.txt"), "Texte (*.txt)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(build_report() + "\n\n=== Journal ===\n" + tail(200))
            result.setText(tr("Rapport enregistré : %s (sans mot de passe).") % path)
        except OSError as e:
            result.setText(tr("Impossible d'écrire le rapport : %s") % e)

    b3, b4 = QPushButton(tr("Contrôler maintenant")), QPushButton(tr("Enregistrer un rapport de diagnostic…"))
    b3.clicked.connect(check)
    b4.clicked.connect(diagnose)
    health.addWidget(b3)
    health.addWidget(b4)
    health.addWidget(result)
    refresh()
    return page.finish()
