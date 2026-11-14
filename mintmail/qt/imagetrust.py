"""Images distantes : expéditeurs (ou domaines) dont on charge TOUJOURS les images. Liste « image_senders » de la configuration,
synchronisée entre les postes (syncdata, élément « imgs »). Logique pure, testée sans Qt."""
import re

KEY_RE = re.compile(r"^@?[^\s@]+(@[^\s@]+)?$")


def norm(key) -> str:
    return (key or "").strip().lower()


def keys_for(sender_email):
    """(adresse, @domaine) d'un expéditeur ; chaîne vide si absent."""
    em = norm(sender_email)
    return em, ("@" + em.rsplit("@", 1)[1] if "@" in em else "")


def entries(config):
    return list(config.get("image_senders", []) or [])


def trusted(config, sender_email) -> bool:
    em, dom = keys_for(sender_email)
    known = {norm(x) for x in entries(config)}
    return bool(em) and (em in known or bool(dom and dom in known))


def trust(config, key) -> bool:
    key = norm(key)
    if not key or len(key) > 200 or not KEY_RE.match(key):
        return False
    lst = entries(config)
    if key not in {norm(x) for x in lst}:
        config["image_senders"] = lst + [key]
        config.save()
    return True


def untrust(config, key) -> None:
    config["image_senders"] = [x for x in entries(config) if norm(x) != norm(key)]
    config.save()
