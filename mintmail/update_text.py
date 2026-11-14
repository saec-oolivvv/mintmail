"""Textes (traduits) des codes de mise à jour : module SANS GTK, partagé par l'interface et par `mintmail --check-update`."""
from .i18n import tr


def explain(code, detail=""):
    """Texte (traduit) d'un code d'erreur de mise à jour."""
    table = {
        "network": tr("Impossible de joindre GitHub (réseau)."),
        "ratelimit": tr("GitHub limite les requêtes : réessayez plus tard."),
        "norelease": tr("Aucune version publiée dans ce dépôt."),
        "badrepo": tr("Dépôt invalide : écrivez « propriétaire/nom »."),
        "badjson": tr("Réponse illisible de GitHub."),
        "badversion": tr("Numéro de version illisible."),
        "noasset": tr("La version publiée ne contient pas le paquet attendu."),
        "badurl": tr("Adresse de téléchargement refusée (hôte non autorisé)."),
        "toobig": tr("Fichier trop volumineux : refusé."),
        "badsize": tr("Téléchargement incomplet."),
        "checksum": tr("Somme de contrôle incorrecte : téléchargement corrompu, refusé."),
        "http": tr("Erreur du serveur de téléchargement."),
        "nodmg": tr("L'image disque (.dmg) de cette version n'est pas encore publiée pour votre Mac : réessayez dans quelques minutes (ou ouvrez la page de la version)."),
        "macos": tr("Sur Mac, la mise à jour se fait à la main : téléchargez le nouveau fichier .dmg sur la page de la version, puis remplacez l'application MintMail."),
        "nokey": tr("Clé de vérification absente : installation automatique désactivée."),
        "unsigned": tr("Version non signée : refusée par sécurité."),
        "bad_signature": tr("SIGNATURE INVALIDE : paquet refusé (il ne vient pas de SAEC ou a été modifié)."),
        "bad_package": tr("Ce fichier n'est pas un paquet MintMail valide : refusé."),
        "not_newer": tr("Cette version n'est pas plus récente que celle installée : refusée."),
        "bad_file": tr("Fichier de mise à jour invalide : refusé."),
        "key_untrusted": tr("La clé de vérification installée n'est pas protégée : refusé."),
        "install_failed": tr("L'installation a échoué (le détail est dans le journal)."),
        "cancelled": tr("Authentification annulée : rien n'a été installé."),
        "nohelper": tr("Installation automatique indisponible sur cette machine (pkexec ou programme d'installation absent)."),
        "not_root": tr("Droits administrateur requis."),
        "usage": tr("Appel invalide du programme d'installation."),
        "git": tr("La mise à jour du dépôt de sources a échoué (modifications locales ou historique divergent) : lancez « sh mintmail-sync.sh » dans le terminal."),
        "internal": tr("Erreur interne pendant la mise à jour."),
    }
    return table.get(code, tr("Erreur de mise à jour (%s).") % code)
