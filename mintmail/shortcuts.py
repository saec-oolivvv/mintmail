"""Raccourcis clavier : liste complète des actions de MintMail avec leur raccourci par défaut, et personnalisation (Réglages → Raccourcis).
Un raccourci personnalisé est mémorisé par action (config « shortcuts » : {action: séquence}) ; une séquence vide désactive l'action.
Module SANS Qt, testable partout (la saisie de la touche est faite par Qt)."""
from typing import Dict, List, Optional, Tuple

from .i18n import tr

MAIN, COMPOSE = "main", "compose"

# (identifiant, portée, groupe, libellé, raccourcis par défaut)
def catalog() -> List[Tuple[str, str, str, str, Tuple[str, ...]]]:
    msg, nav, app, comp = tr("Messages"), tr("Navigation"), tr("Application"), tr("Rédaction")
    return [
        ("reply", MAIN, msg, tr("Répondre"), ("R",)), ("reply_all", MAIN, msg, tr("Répondre à tous"), ("A",)), ("forward", MAIN, msg, tr("Transférer"), ("F",)),
        ("archive", MAIN, msg, tr("Archiver"), ("E",)), ("trash", MAIN, msg, tr("Supprimer"), ("Delete",)), ("spam", MAIN, msg, tr("Signaler comme spam"), ("!",)),
        ("star", MAIN, msg, tr("Favori"), ("S",)), ("pin", MAIN, msg, tr("Épingler"), ("P",)), ("unread", MAIN, msg, tr("Marquer comme non lu"), ("U",)),
        ("move", MAIN, msg, tr("Déplacer vers un dossier"), ("V",)), ("snooze", MAIN, msg, tr("Reporter à demain"), ("H",)),
        ("print", MAIN, msg, tr("Imprimer le message"), ("Ctrl+P",)),
        ("next", MAIN, nav, tr("Message suivant"), ("J",)), ("prev", MAIN, nav, tr("Message précédent"), ("K",)),
        ("back", MAIN, nav, tr("Retour à la liste / annuler"), ("Escape",)), ("search", MAIN, nav, tr("Rechercher"), ("/",)),
        ("today", MAIN, nav, tr("Aujourd'hui"), ("T",)), ("select", MAIN, nav, tr("Mode sélection"), ("X",)),
        ("select_all", MAIN, nav, tr("Tout sélectionner"), ("Ctrl+A",)), ("layout", MAIN, nav, tr("Changer la disposition"), ("\\",)),
        ("rail", MAIN, nav, tr("Barre latérale réduite / étendue"), ("Ctrl+B",)),
        ("compose", MAIN, app, tr("Nouveau message"), ("C",)), ("settings", MAIN, app, tr("Paramètres"), ("Ctrl+,",)),
        ("help", MAIN, app, tr("Aide"), ("F1",)), ("fullscreen", MAIN, app, tr("Plein écran"), ("F11",)),
        ("sync", MAIN, app, tr("Actualiser"), ("Ctrl+R",)), ("palette", MAIN, app, tr("Palette de commandes"), ("Ctrl+K",)),
        ("assistant", MAIN, app, tr("Assistant IA"), ("Ctrl+J",)),
        ("zoom_in", MAIN, app, tr("Agrandir le texte des messages"), ("Ctrl++", "Ctrl+=")), ("zoom_out", MAIN, app, tr("Réduire le texte des messages"), ("Ctrl+-",)),
        ("zoom_reset", MAIN, app, tr("Taille normale du texte"), ("Ctrl+0",)),
        ("compose_send", COMPOSE, comp, tr("Envoyer le message"), ("Ctrl+Return",)), ("compose_ai", COMPOSE, comp, tr("Aide IA à l'écriture"), ("Ctrl+J",)),
        ("compose_attach", COMPOSE, comp, tr("Joindre un fichier"), ("Ctrl+Shift+A",)),
    ]


def overrides(config) -> Dict[str, str]:
    d = config.get("shortcuts") or {}
    return {k: v for k, v in d.items() if isinstance(k, str) and isinstance(v, str)} if isinstance(d, dict) else {}


def action_of(default: str, scope: str = MAIN) -> Optional[str]:
    for aid, sc, _g, _l, defaults in catalog():
        if sc == scope and default in defaults:
            return aid
    return None


def keys_of(config, action_id: str) -> Tuple[str, ...]:
    """Séquences actives d'une action : la personnalisée (une seule) ou les raccourcis par défaut ; vide : désactivée."""
    ov = overrides(config)
    if action_id in ov:
        return (ov[action_id],) if ov[action_id] else ()
    for aid, _sc, _g, _l, defaults in catalog():
        if aid == action_id:
            return defaults
    return ()


def resolve(config, default: str, scope: str = MAIN) -> str:
    """Séquence à lier pour un raccourci par défaut du code (chaîne vide : rien à lier)."""
    aid = action_of(default, scope)
    if aid is None:
        return default
    ov = overrides(config)
    if aid not in ov:
        return default
    first = next(a[4][0] for a in catalog() if a[0] == aid)
    return ov[aid] if default == first else ""


def conflict(config, action_id: str, seq: str) -> Optional[str]:
    """Autre action de la même portée qui utilise déjà `seq` (None si libre)."""
    if not seq:
        return None
    scope = next((sc for aid, sc, *_ in catalog() if aid == action_id), MAIN)
    low = seq.lower()
    for aid, sc, _g, label, _d in catalog():
        if aid != action_id and sc == scope and any(k.lower() == low for k in keys_of(config, aid)):
            return label
    return None


def set_key(config, action_id: str, seq: str) -> Optional[str]:
    """Personnalise une action ; retourne le libellé de l'action en conflit (rien n'est changé dans ce cas), sinon None."""
    if action_id not in {a[0] for a in catalog()}:
        raise KeyError(action_id)
    other = conflict(config, action_id, seq)
    if other:
        return other
    default = next(a[4] for a in catalog() if a[0] == action_id)
    ov = dict(overrides(config))
    if seq == default[0] and len(default) == 1:
        ov.pop(action_id, None)                                                    # retour au réglage d'origine
    else:
        ov[action_id] = seq
    config["shortcuts"] = ov
    config.save()
    return None


def reset(config, action_id: Optional[str] = None) -> None:
    ov = dict(overrides(config))
    if action_id is None:
        ov = {}
    else:
        ov.pop(action_id, None)
    config["shortcuts"] = ov
    config.save()


def display(seq: str) -> str:
    suppr, echap = tr("Suppr"), tr("Échap")
    return (seq or "").replace("Delete", suppr).replace("Escape", echap) or tr("(aucun)")
