"""Gestion des dossiers de l'interface Qt (créer, sous-dossier, renommer, supprimer) : logique pure, sans Qt — mêmes règles que la version GTK.
Les opérations réseau sont synchrones : l'interface les lance en fond (run_bg)."""
from typing import Dict, Optional, Tuple

from ..ai_engine import sanitize_folder_name
from ..backend import utf7_decode
from ..i18n import tr
from . import assistant as AS


def entry_of(engine, aid, name) -> Optional[Dict]:
    """Entrée de l'arbre des dossiers (compte, nom brut sur le serveur)."""
    return next((e for e in engine.folder_entries(aid) if e.get("name") == name), None)


def menu_plan(entry: Optional[Dict]) -> list:
    """Entrées du clic droit sur un dossier ou un compte : [clé]. Renommer / supprimer jamais sur un dossier spécial (Boîte, Envoyés…)."""
    keys = []
    if entry is not None and entry.get("selectable", True):
        keys.append("sync")
    keys.append("new" if entry is None else "sub")
    if entry is not None and not entry.get("special"):
        keys += ["rename", "delete"]
    keys.append("refresh")
    return keys


def label_of(key: str) -> str:
    return {"sync": tr("Actualiser ce dossier"), "new": tr("Nouveau dossier…"), "sub": tr("Nouveau sous-dossier…"), "rename": tr("Renommer…"),
            "delete": tr("Supprimer…"), "refresh": tr("Actualiser la liste des dossiers")}[key]


def check_name(name: str, parent: Optional[Dict]) -> Tuple[str, str]:
    """(nom propre, erreur) : un nom ne contient jamais le séparateur de hiérarchie du serveur."""
    delim = (parent or {}).get("delim") or "/"
    name = (name or "").strip()
    if not name:
        return "", ""
    if delim in name:
        return "", tr("Le nom ne peut pas contenir « %s »") % delim
    clean = sanitize_folder_name(name)
    return clean, "" if clean else tr("Le nom ne peut pas contenir « %s »") % delim


def create(engine, aid, name, parent=None) -> str:
    """Crée le dossier (premier niveau ou sous `parent`), visible tout de suite ; retourne le message à afficher."""
    clean, err = check_name(name, parent)
    if err or not clean:
        return err
    e = AS.create_folder(engine, aid, clean, parent)
    return tr("Dossier « %s » créé") % (e["label"] if e else clean)


def rename(engine, aid, entry, name) -> str:
    name = (name or "").strip()
    if not name or name == (entry.get("label") or entry["name"]):
        return ""
    delim = entry.get("delim") or ""
    if delim and delim in name:
        return tr("Le nom ne peut pas contenir « %s »") % delim
    decoded = utf7_decode(entry["name"])
    new_path = (decoded[:decoded.rfind(delim)] + delim + name) if delim and delim in decoded else name
    engine.backend(aid).rename_folder(entry["name"], new_path)
    engine.refresh_folders()
    return tr("Dossier renommé en « %s »") % name


def delete(engine, aid, entry) -> str:
    """Supprime le dossier sur le serveur (ses messages avec) puis dans le cache."""
    engine.backend(aid).delete_folder(entry["name"])
    engine.cache.delete_folder(aid, "f:" + entry["name"])
    engine.refresh_folders()
    return tr("Dossier supprimé")
