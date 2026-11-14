"""Recherches enregistrées (logique pure) : mêmes données que la version GTK — liste « saved_searches » de {name, query} dans les réglages,
synchronisée entre les postes ; une recherche est une vue « saved:N » de la barre latérale."""
from typing import List, Optional, Tuple

PREFIX = "saved:"


def key(i: int) -> str:
    return PREFIX + str(i)


def rows(config) -> List[Tuple[str, str]]:
    """[(clé de vue, nom)] dans l'ordre d'enregistrement."""
    return [(key(i), s.get("name", "")) for i, s in enumerate(config.get("saved_searches") or [])]


def query_of(config, view: str) -> str:
    """Texte de la recherche enregistrée pour cette vue (vide si la vue n'en est pas une, ou si elle a disparu)."""
    if not view.startswith(PREFIX):
        return ""
    try:
        return (config["saved_searches"][int(view[len(PREFIX):])] or {}).get("query", "")
    except (ValueError, IndexError, KeyError, TypeError):
        return ""


def add(config, name: str, query: str) -> Optional[str]:
    """Enregistre (une recherche de même nom est remplacée) ; retourne la clé de la vue, ou None si le nom ou la recherche est vide."""
    name, query = (name or "").strip(), (query or "").strip()
    if not name or not query:
        return None
    lst = [s for s in (config.get("saved_searches") or []) if s.get("name") != name]
    lst.append({"name": name, "query": query})
    config["saved_searches"] = lst
    config.save()
    return key(len(lst) - 1)


def delete(config, i: int) -> bool:
    lst = list(config.get("saved_searches") or [])
    if not 0 <= i < len(lst):
        return False
    del lst[i]
    config["saved_searches"] = lst
    config.save()
    return True
