"""Cadence de la veille des boîtes : assez vive pour voir un changement en quelques secondes, assez douce pour ne pas déclencher les limites des fournisseurs
(Gmail : 15 connexions simultanées, débit et nombre de commandes par jour ; erreurs 429 « trop de requêtes »). Pur, sans Qt."""
PRONE = ("gmail.", "googlemail.", "google.", "outlook.", "office365.", "hotmail.", "live.", "yahoo.", "icloud.", "me.com")     # i18n: skip — fournisseurs qui limitent vite
VIRTUAL = ("all mail", "tous les messages", "important", "starred", "suivis", "alle berichten", "todos los mensajes", "chats")   # i18n: skip — vues Gmail qui doublent d'autres dossiers


def is_prone(account) -> bool:
    host = ((account or {}).get("imap_host") or "").lower()
    return any(p in host for p in PRONE)


def is_virtual(folder_name) -> bool:
    low = (folder_name or "").lower()
    return low.startswith("[gmail]") and low.rsplit("/", 1)[-1] in VIRTUAL        # seulement les vues du dossier système de Gmail, jamais vos propres dossiers


def plan(accounts, push_state=None):
    """{'live': ms, 'folders': ms, 'max_folders': n} : veille légère (STATUS boîte + envoyés), passage sur tous les dossiers, plafond de dossiers interrogés.
    IDLE actif sur toutes les boîtes → la veille légère n'est qu'un filet de sécurité ; fournisseur à limites → cadence encore plus douce."""
    real = [a for a in accounts or [] if not a.get("demo")]
    st = push_state or {}
    idle_ok = bool(real) and all(st.get(a.get("id")) == "ok" for a in real)
    prone = any(is_prone(a) for a in real)
    live = 20_000 if idle_ok else 8_000
    folders = 90_000
    if prone:
        live, folders = live * 2, 240_000
    return {"live": live, "folders": folders, "max_folders": 30 if prone else 80}
