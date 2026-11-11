# Mises à jour automatiques

MintMail se met à jour depuis les **Releases** de son dépôt GitHub. Résumé pour l'utilisateur : Paramètres → **Mises à jour** (recherche automatique à chaque démarrage puis toutes les 6 heures,
installation en un clic avec votre mot de passe administrateur). Ce document explique le fonctionnement et la **sécurité**, puis comment mettre le système en route.

## Ce que voit l'utilisateur

- **Dès le lancement**, si une version plus récente est connue, un **bandeau** glisse sous la barre de titre : « MintMail X est disponible », la version actuelle, la première nouveauté de la Release, et trois actions —
  **Installer maintenant**, **Notes de version** (page de la Release), **Plus tard** (repousse 24 h pour cette version ; une version encore plus récente réapparaît aussitôt). ✕ masque jusqu'au prochain lancement.
- Une **pastille « ⬆ Mise à jour X »** reste dans le pied de la barre latérale tant que la mise à jour n'est pas installée, même si le bandeau a été repoussé ; un clic ouvre Paramètres → Mises à jour.
- **Pendant l'installation**, le bandeau montre une barre de progression (téléchargement), puis « Vérification de la signature… », puis « Installation… (votre mot de passe administrateur est demandé) ». Ensuite : « MintMail X est installé »
  avec **Relancer maintenant** (relance la fenêtre via une commande fixe). En cas d'échec : le motif exact et **Réessayer**.
- La mise à jour détectée est **mémorisée** (réglages locaux, jamais synchronisés) : elle s'affiche immédiatement au lancement suivant, sans attendre le réseau. Cette mémoire est **revalidée à chaque lecture** (versions, hôtes GitHub) :
  un fichier de réglages modifié ne peut pas faire apparaître une fausse mise à jour pointant ailleurs, et la signature reste de toute façon vérifiée avant toute installation.
- **Déjà installée** : si la mise à jour a été installée entre-temps (ou depuis une autre fenêtre), le bandeau ne la propose pas une seconde fois : il affiche « installé » avec **Relancer maintenant**.
- **Notification de bureau** (une fois par version) si la fenêtre n'est pas au premier plan ; désactivable avec les notifications.
- **Diagnostic** : `mintmail --check-update` affiche la version, le dépôt, la présence de la clé de vérification, le résultat de la recherche et la cause exacte d'une erreur (sans interface, sans rien installer).
  Code de sortie : 0 à jour, 10 mise à jour disponible, 1 erreur. Le dernier résultat est aussi inscrit dans le journal et rappelé dans Paramètres → Mises à jour.
- La recherche se fait 8 secondes après **chaque** démarrage (même si une vérification date de ce matin : une version publiée entre-temps est annoncée tout de suite), puis toutes les 6 heures tant que MintMail tourne. Désactivable. Les requêtes sont conditionnelles (ETag : réponse « 304 », très légère).

## Principe de sécurité

Installer un paquet avec les droits administrateur permet de tout faire sur la machine : le système est donc conçu pour que **GitHub ne soit jamais cru sur parole**.

| Élément | Rôle |
|---|---|
| Clé **privée** de SAEC | Signe chaque `.deb` (RSA 3072 / SHA-256). Reste chez vous, protégée par une phrase secrète, jamais dans le dépôt. |
| Clé **publique** (`data/update-pubkey.pem`) | Intégrée au paquet : `/usr/share/mintmail/update-pubkey.pem`, propriété de root. Aucun réglage, aucune Release, aucun compte GitHub piraté ne peut la remplacer. |
| GitHub (Release) | Simple **transport** : `mintmail_X.Y.Z_all.deb`, `mintmail_X.Y.Z_all.deb.sig`, `SHA256SUMS`. |
| `apply_update.py` (root, via pkexec) | Copie le paquet dans un dossier privé (sans suivre de lien symbolique), re-vérifie la signature **sur la copie**, vérifie que c'est bien `mintmail` (type `all`) et que la version est **strictement plus récente**, puis installe avec apt. |
| polkit | `auth_admin` : mot de passe demandé à chaque installation. Jamais d'installation silencieuse. |

Refusés : signature absente ou invalide, signature d'une autre clé, paquet modifié d'un seul octet, autre paquet que MintMail, version identique ou plus ancienne (pas de retour en arrière),
téléchargement corrompu (somme de contrôle) ou trop gros, hôte autre que GitHub, redirection vers un hôte étranger, Release en brouillon ou préversion.
**Sans clé publique installée, MintMail annonce seulement les nouvelles versions** (aucune installation automatique).

Confidentialité : une seule requête GET anonyme à `api.github.com` (agent « MintMail/<version> »), au démarrage puis toutes les 6 heures, désactivable (requête conditionnelle, sans donnée personnelle).

## Mise en route (une seule fois)

1. `tools/make-signing-key.sh` : crée la paire de clés (phrase secrète demandée) ; copie la clé publique dans `data/update-pubkey.pem` ; **sauvegardez la clé privée hors ligne**.
2. `git add data/update-pubkey.pem && git commit -m "Clé publique de signature des mises à jour"`.
3. `tools/release.sh` : teste, construit, signe, étiquette et publie la Release.
4. Installez **une fois à la main** ce paquet signé (`sudo apt install ./dist/mintmail_X.Y.Z_all.deb`) : c'est lui qui apporte la clé publique aux machines. Dès lors, les versions suivantes
   s'installent depuis l'application. Les machines qui n'ont pas ce paquet ne reçoivent que des annonces.

## Limites et risques (à connaître)

- **Clé privée volée** = quiconque la possède peut faire installer n'importe quel programme sur toutes les machines. Phrase secrète, sauvegarde hors ligne, pas de CI qui la détient.
- **Clé perdue ou remplacée** : aucun mécanisme de rotation automatique (volontairement : il constituerait une porte dérobée). Il faut réinstaller à la main un paquet contenant la nouvelle clé publique.
- **Attaque par gel** : quelqu'un qui contrôle le réseau ou GitHub peut empêcher d'apprendre l'existence d'une nouvelle version (pas la falsifier). Ce n'est pas détecté.
- **Retour en arrière** : refusé pour la version installée, mais une version intermédiaire plus ancienne que la dernière, signée et authentique, peut être rejouée tant qu'elle est plus récente que celle installée.
- Le contrôle repose sur `openssl`, `dpkg` et `apt` du système (à jour de préférence) ; le dépôt à consulter est un réglage par machine (Paramètres → Mises à jour), **non synchronisé** entre machines.
- Non testé sur un vrai GitHub ni avec une vraie fenêtre polkit : testé avec un faux serveur GitHub, de vraies signatures openssl et un vrai `dpkg` (voir `SECURITY.md`).
