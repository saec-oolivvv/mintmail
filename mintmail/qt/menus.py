"""Menu contextuel (clic droit) et palette de commandes (Ctrl+K) de l'interface Qt : contenu et recherche purs, sans Qt — mêmes entrées que la version GTK.
Chaque entrée est (clé, libellé) ; la fenêtre associe une action à chaque clé (MainWindow._run_cmd)."""
from typing import Dict, List, Optional, Tuple

from ..i18n import tr
from .viewmodel import VIEWS, dest_of

Item = Optional[Tuple[str, str]]                                    # None = séparateur


def context_items(msg, blocked: bool = False) -> List[Item]:
    """Entrées du clic droit sur un message (l'état du message décide des libellés : lu / non lu, favori, épingle, pas du spam…)."""
    return [
        ("reply", tr("Répondre")), ("reply_all", tr("Répondre à tous")), ("forward", tr("Transférer")), ("ai_reply", tr("✨ Répondre avec l'IA")), None,
        ("archive", tr("Archiver")), ("trash", tr("Supprimer")),
        ("read", tr("Marquer comme %s") % ("lu" if msg.unread else tr("non lu"))),
        ("star", tr("Retirer des favoris") if msg.starred else tr("Ajouter aux favoris")),
        ("pin", tr("Désépingler") if msg.pinned else tr("Épingler")), None,
        *([("notspam", tr("✔ Ce n'est pas du spam"))] if msg.folder == "spam" else []),
        ("spam", tr("Signaler comme spam")), ("spam_sender", tr("Mettre l'expéditeur en spam")),
        ("block", tr("Débloquer ") + msg.sender_email if blocked else tr("Bloquer l'expéditeur")),
        ("from", tr("Voir tous ses messages")), ("copy_addr", tr("Copier l'adresse")), ("addcontact", tr("Ajouter aux contacts")), None,
        ("summarize", tr("✨ Résumer / analyser ce message")), ("translate", tr("✨ Traduire ce message")),
    ]


SNOOZES = [("snooze_tomorrow", tr("Demain 8 h")), ("snooze_monday", tr("Lundi prochain 8 h"))]


def palette_commands(msg, engine=None) -> List[Tuple[str, str]]:
    """Commandes de la palette : [(libellé, clé)] — actions sur le message courant, application, réglages, dispositions, dossiers, vues."""
    cmds: List[Tuple[str, str]] = []
    if msg is not None:
        who = msg.sender_email
        dom = "@" + who.split("@")[-1]
        cmds += [(tr("Répondre"), "reply"), (tr("Répondre à tous"), "reply_all"), (tr("Transférer"), "forward"),
                 (tr("✨ Résumer / analyser ce message"), "summarize"), (tr("✨ Répondre avec l'IA"), "ai_reply"), (tr("✨ Traduire ce message"), "translate"),
                 (tr("Archiver"), "archive"), (tr("Supprimer"), "trash"),
                 *([(tr("✔ Ce n'est pas du spam — ") + who, "notspam")] if msg.folder == "spam" else []),
                 (tr("Signaler comme spam (ce message)"), "spam"), (tr("Mettre l'expéditeur en spam — ") + who, "spam_sender"),
                 (tr("Mettre le domaine en spam — ") + dom, "spam_domain"), (tr("Bloquer l'expéditeur — ") + who, "block"),
                 (tr("Bloquer le domaine — ") + dom, "block_domain"), (tr("Voir tous les messages de ") + who, "from"), (tr("Ajouter aux contacts — ") + who, "addcontact"),
                 (tr("Copier l'adresse ") + who, "copy_addr"),
                 (tr("Reporter à demain 8 h"), "snooze_tomorrow")]
    if msg is not None:
        cmds += [(tr("Créer une tâche depuis ce message"), "task_from"), (tr("Proposer des créneaux (agenda)"), "slots"),
                 (tr("Me le rappeler si pas de réponse sous 3 jours"), "followup3"), (tr("Se désabonner de cet expéditeur"), "unsubscribe")]
    cmds += [(tr("Aujourd'hui : agenda, priorités, tâches, relances"), "today"), (tr("Agenda des prochains jours"), "agenda"),
             (tr("Nouvel événement dans l'agenda"), "new_event"), (tr("Nouvelle tâche"), "new_task"),
             (tr("Barre latérale : réduire / agrandir (Ctrl+B)"), "rail"), (tr("Zoom du lecteur : agrandir"), "zoom_in"),
             (tr("Zoom du lecteur : réduire"), "zoom_out"), (tr("Zoom du lecteur : taille normale"), "zoom_reset"),
             (tr("Synchronisation entre mes postes (réglages)"), "settings:p2p"), (tr("Google Agenda / CalDAV (réglages)"), "settings:calendar"),
             (tr("Synchroniser maintenant avec mes autres postes"), "p2p_now"),
             (tr("✨ Résumer ma boîte de réception"), "digest"), (tr("✨ Classer ma boîte de réception (60 derniers)"), "ai_classify_inbox"),
             (tr("✨ Ouvrir l'assistant IA"), "assistant"), (tr("Nouveau message"), "compose"), (tr("Actualiser"), "sync"),
             (tr("Aide et raccourcis (F1)"), "help"), (tr("Gérer les expéditeurs bloqués et les règles"), "settings:filters"),
             (tr("Appliquer les règles à la boîte de réception"), "apply_rules"),
             (tr("Disposition : colonnes"), "layout:columns"), (tr("Disposition : lecture en bas"), "layout:bottom"), (tr("Disposition : liste seule"), "layout:list"),
             (tr("Paramètres (Ctrl+,)"), "settings"), (tr("Réglages de l'IA"), "settings:ai"), (tr("Rechercher les mises à jour"), "updates"),
             (tr("Mises à jour"), "settings:updates"), (tr("Gestes de swipe (réglages)"), "settings:gestures"), (tr("Rechercher"), "search"),
             (tr("Enregistrer la recherche actuelle"), "save_search"), (tr("Tout marquer comme lu"), "mark_all_read"), (tr("Tout sélectionner"), "select_all"), (tr("Mode sélection multiple"), "select_mode"),
             (tr("Chercher aussi sur le serveur"), "search_server"), (tr("Envoyer mes épingles vers la boîte"), "push_pins"), (tr("Journal d'erreurs"), "log"),
             (tr("Plein écran (F11)"), "fullscreen"), (tr("Actualiser la liste des dossiers"), "refresh_folders")]
    if engine is not None:
        many = len(engine.accounts()) > 1
        for acc in engine.accounts():
            for e in engine.folder_entries(acc["id"]):
                if e.get("selectable", True):
                    nm = (e.get("path") or e.get("label") or e["name"]) + ((" — " + (acc.get("name") or acc["email"])) if many else "")
                    cmds.append((tr("Aller au dossier : ") + nm, "goto:" + dest_of(e)))
                    if msg is not None:
                        cmds.append((tr("Déplacer vers : ") + nm, "move:" + dest_of(e)))
    cmds += [(tr("Aller à : ") + label, "goto:" + key) for key, label in VIEWS]
    for i, sv in enumerate((getattr(engine, "config", None) or {}).get("saved_searches") or []) if engine is not None else []:
        cmds.append((tr("Aller à : ") + sv.get("name", ""), "goto:saved:%d" % i))
        cmds.append((tr("Supprimer la recherche enregistrée : ") + sv.get("name", ""), "delsaved:%d" % i))
    return cmds


def search(cmds: List[Tuple[str, str]], text: str) -> List[Tuple[str, str]]:
    """Commandes dont le libellé contient tous les mots tapés (insensible à la casse), dans l'ordre de la liste."""
    words = (text or "").lower().split()
    return [c for c in cmds if all(w in c[0].lower() for w in words)]


def wants_ai(text: str, found: List) -> bool:
    """Texte libre sans commande correspondante : on propose de le confier à l'assistant."""
    return len((text or "").strip()) > 2 and not found
