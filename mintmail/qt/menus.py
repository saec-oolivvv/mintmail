"""Menu contextuel (clic droit) et palette de commandes (Ctrl+K) de l'interface Qt : contenu et recherche purs, sans Qt — mêmes entrées que la version GTK.
Chaque entrée est (clé, libellé) ; la fenêtre associe une action à chaque clé (MainWindow._run_cmd)."""
from typing import Dict, List, Optional, Tuple

from ..i18n import tr
from .viewmodel import VIEWS, dest_of

Item = Optional[Tuple[str, str]]                                    # None = séparateur


def integration_items(avail) -> List[Tuple[str, str]]:
    """« Envoyer vers … » pour les services réglés (voir integrations.available)."""
    from .. import integrations as IG
    names = IG.labels()
    out = []
    for k in avail or ():
        out.append(("integ:" + k, {"notes": tr("Enregistrer en note Markdown"), "obsidian": tr("Ouvrir dans Obsidian"), "bear": tr("Ouvrir dans Bear"),
                                    "todoist": tr("Créer une tâche Todoist")}.get(k) or tr("Envoyer vers %s") % names[k]))
    return out


def context_items(msg, blocked: bool = False, integ=()) -> List[Item]:
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
        ("summarize", tr("✨ Résumer / analyser ce message")), ("translate", tr("✨ Traduire ce message")), None,
        ("print", tr("Imprimer…")), ("print_pdf", tr("Enregistrer en PDF…")),
        *([None] + integration_items(integ) if integ else []),
    ]


def more_items(msg, blocked: bool = False, integ=()) -> List[Item]:
    """Menu « … » du lecteur, comme dans Spark : Répondre, Envoyer à nouveau, Bloquer, Déplacer, Spam, Imprimer, Copier en Markdown, Exporter vers, Toutes les actions."""
    return [
        ("reply", tr("Répondre")), ("resend", tr("Envoyer à nouveau")), ("assign", tr("Attribuer à…")), ("share", tr("Partager…")), None,
        ("block", tr("Débloquer ") + msg.sender_email if blocked else tr("Bloquer l'expéditeur")), ("move", tr("Déplacer vers…")),
        ("spam", tr("Marquer comme spam")), ("print", tr("Imprimer…")), ("copy_md", tr("Copier en Markdown")),
        *([None] + integration_items(integ) if integ else []), None,
        ("all_actions", tr("Toutes les actions")),
    ]


SNOOZES = [("snooze_tomorrow", tr("Demain 8 h")), ("snooze_monday", tr("Lundi prochain 8 h"))]

# Couleurs des icônes du clic droit (mi-teintes : lisibles en thème clair comme sombre)
BLUE, GREEN, RED, AMBER, ORANGE, PURPLE, TEAL, VIOLET, SLATE = "#3b82f6", "#22c55e", "#ef4444", "#f59e0b", "#f97316", "#a855f7", "#14b8a6", "#8b5cf6", "#64748b"


def quick_menu(msg, blocked: bool = False, integ=(), can_unsub: bool = False) -> List:
    """Clic droit d'un message, version courte : l'essentiel au premier niveau (répondre, ranger, marquer), le reste regroupé en quelques sous-menus.
    Entrées : (clé, libellé, icône, couleur) | ("sub", libellé, icône, couleur, [entrées]) | ("dyn", « move » | « ai ») pour un sous-menu rempli par la fenêtre | None (séparateur)."""
    spam = msg.folder == "spam"
    top: List = [
        ("reply", tr("Répondre"), "reply", BLUE), ("reply_all", tr("Répondre à tous"), "replyall", BLUE), ("forward", tr("Transférer"), "forward", BLUE), None,
        ("archive", tr("Archiver"), "archive", GREEN), ("trash", tr("Supprimer"), "trash", RED),
        ("notspam", tr("✔ Ce n'est pas du spam"), "check", GREEN) if spam else ("spam", tr("Spam"), "spam", ORANGE), None,
        ("read", tr("Marquer comme %s") % ("lu" if msg.unread else tr("non lu")), "mail", BLUE),
        ("star", tr("Retirer des favoris") if msg.starred else tr("Ajouter aux favoris"), "star", AMBER),
        ("pin", tr("Désépingler") if msg.pinned else tr("Épingler"), "pin", ORANGE), None,
        ("sub", tr("Reporter"), "clock", PURPLE, [(k, l, "clock", PURPLE) for k, l in SNOOZES]),
        ("dyn", "move", tr("Déplacer vers"), "folder", TEAL),
        ("sub", tr("Priorité"), "flag", RED, [("prio:1", tr("❗ Haute"), "flag", RED), ("prio:0", tr("Priorité normale"), "flag", SLATE), ("prio:-1", tr("⬇ Basse"), "flag", BLUE)]), None,
        ("dyn", "ai", tr("✨ IA"), "sparkles", VIOLET),
        ("sub", tr("Organiser"), "checklist", TEAL, [
            ("task_from", tr("Créer une tâche"), "checklist", TEAL), ("slots", tr("Proposer des créneaux"), "calendar", BLUE),
            ("followup3", tr("Me le rappeler sans réponse (3 jours)"), "bell", AMBER), ("assign", tr("Attribuer à…"), "userplus", PURPLE), ("share", tr("Partager…"), "share", BLUE),
            *([("unsubscribe", tr("Se désabonner"), "ban", ORANGE)] if can_unsub else [])]),
        ("sub", tr("Expéditeur"), "user", SLATE, [
            ("from", tr("Voir tous ses messages"), "search", BLUE), ("copy_addr", tr("Copier l'adresse"), "copy", SLATE), ("addcontact", tr("Ajouter aux contacts"), "userplus", GREEN), None,
            ("spam_sender", tr("Mettre l'expéditeur en spam"), "spam", ORANGE),
            ("block", tr("Débloquer ") + msg.sender_email if blocked else tr("Bloquer l'expéditeur"), "ban", RED)]),
        ("sub", tr("Plus"), "more", SLATE, [
            ("print", tr("Imprimer…"), "print", SLATE), ("print_pdf", tr("Enregistrer en PDF…"), "template", RED), ("copy_md", tr("Copier en Markdown"), "copy", SLATE),
            ("resend", tr("Envoyer à nouveau"), "send", BLUE),
            *([None] + [(k, l, "share", TEAL) for k, l in integration_items(integ)] if integ else [])]),
    ]
    return top


def flat_keys(entries) -> List[str]:
    """Toutes les clés d'action d'un menu (sous-menus compris) — pour les tests et pour vérifier que chaque clé est connue de _run_cmd."""
    out: List[str] = []
    for e in entries:
        if e is None:
            continue
        if e[0] == "sub":
            out += flat_keys(e[4])
        elif e[0] != "dyn":
            out.append(e[0])
    return out



def palette_commands(msg, engine=None, integ=()) -> List[Tuple[str, str]]:
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
                 (tr("Reporter à demain 8 h"), "snooze_tomorrow"), (tr("Imprimer ce message (Ctrl+P)"), "print"), (tr("Enregistrer ce message en PDF"), "print_pdf"), *integration_items(integ)]
    if msg is not None:
        cmds += [(tr("Créer une tâche depuis ce message"), "task_from"), (tr("Attribuer ce message à…"), "assign"), (tr("Partager ce message…"), "share"), (tr("Proposer des créneaux (agenda)"), "slots"),
                 (tr("Priorité : haute"), "prio:1"), (tr("Priorité : normale"), "prio:0"), (tr("Priorité : basse"), "prio:-1"),
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
             (tr("Chercher aussi sur le serveur"), "search_server"), (tr("Envoyer mes épingles vers la boîte"), "push_pins"), (tr("Journal d'erreurs"), "log"), (tr("Activité des boîtes en direct (relève, suppressions…)"), "activity"),
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
