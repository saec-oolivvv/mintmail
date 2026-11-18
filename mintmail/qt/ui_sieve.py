"""Boutons Sieve : envoyer absence + règles au serveur (elles tournent même MintMail fermé) ; importer les filtres Thunderbird."""
import glob
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from .. import absence as AB
from .. import importer as IM
from .. import sieve as SV
from ..i18n import tr


def push_to_server(win):
    """Envoie le script Sieve (règles + absence) aux boîtes qui l'acceptent ; affiche un résumé par boîte."""
    cfg = win.cfg
    accounts = [a for a in cfg.get("accounts") or [] if a.get("id") and not a.get("demo")]
    QApplication.setOverrideCursor(Qt.WaitCursor)
    try:
        res = SV.publish_accounts(accounts, cfg.password, cfg.get("rules") or [], AB.settings(cfg), own_of=lambda a: AB.own_addresses(cfg, a))
    finally:
        QApplication.restoreOverrideCursor()
    lines = []
    for email, state in res:
        lines.append("%s : %s" % (email, tr("envoyé et activé") if state == "ok" else tr("pas de Sieve sur ce service (Gmail, Microsoft, iCloud, Yahoo : MintMail doit rester ouvert)") if state == "unsupported" else tr("échec : %s") % state))
    QMessageBox.information(win, tr("Sur le serveur"), "\n".join(lines) or tr("Aucune boîte mail."))
    return res


def import_thunderbird(win):
    """Importe les règles simples (une condition « contient ») des filtres Thunderbird ; dit combien n'ont pas pu l'être."""
    found = []
    for prefs in IM.thunderbird_prefs_files():
        found += glob.glob(os.path.join(os.path.dirname(prefs), "ImapMail", "*", "msgFilterRules.dat"))
    if not found:
        f, _ = QFileDialog.getOpenFileName(win, tr("Fichier de filtres Thunderbird (msgFilterRules.dat)"), os.path.expanduser("~"), "msgFilterRules.dat (*.dat)")
        found = [f] if f else []
    rules, skipped = [], 0
    for f in found:
        try:
            with open(f, encoding="utf-8", errors="replace") as fh:
                r, s = SV.parse_thunderbird_filters(fh.read())
        except OSError:
            continue
        rules += r
        skipped += s
    if not found:
        return 0
    merged, added = SV.merge_rules(cfg_rules(win), rules)
    win.cfg["rules"] = merged
    win.cfg.save()
    QMessageBox.information(win, tr("Importer de Thunderbird"), tr("%d règle(s) ajoutée(s). %d filtre(s) ignoré(s) (conditions multiples, désactivés ou actions non reprises).") % (added, skipped))
    return added


def cfg_rules(win):
    return list(win.cfg.get("rules") or [])
