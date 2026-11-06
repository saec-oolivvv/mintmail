# MintMail 1.2.0

Client mail moderne pour Linux Mint (Python / GTK3), inspiré de Spark Mail.

## Installation / mise à jour
```bash
unzip mintmail-1.2.0.zip && cd mintmail-1.2.0
./install.sh            # pour l'utilisateur courant (~/.local)
./install.sh --system   # pour tous les utilisateurs (/opt, sudo)
```
Relancer `install.sh` d'une version plus récente = mise à jour : configuration et courrier en cache sont conservés,
l'ancienne version est gardée dans `app.previous`. Sans installer : `./run.sh`. Désinstaller : `./uninstall.sh [--purge]`.

Dépendances (installées automatiquement via apt) : `python3-gi`, `gir1.2-gtk-3.0`, `gir1.2-webkit2-4.1` (ou 4.0), `python3-keyring` (optionnel, trousseau).

## Fonctions
- Boîte intelligente : onglets Personnes / Notifications / Newsletters, groupes par date, messages épinglés
- Vues : non lus, favoris, épinglés, reportés, brouillons, envoyés, archives, spam, corbeille
- Multi-comptes IMAP/SMTP (Gmail, Outlook, iCloud, Yahoo, Infomaniak, OVH, manuel), test de connexion
- Lecteur HTML (JavaScript désactivé, images distantes bloquées par défaut), pièces jointes, désabonnement en un clic
- Reporter (snooze), envoi annulable, envoi programmé, réponses rapides, sélection multiple et actions groupées
- Rédaction riche (gras, listes, liens, citations), signatures HTML par compte, auto-complétion des contacts, brouillons
- Recherche : `from:`, `is:unread`, `is:starred`, `has:attachment`
- Palette de commandes `Ctrl+K`, raccourcis clavier (voir Paramètres → Raccourcis), thème clair/sombre, couleur d'accent
- Interface adaptative (panneau latéral escamotable, mode une colonne en fenêtre étroite), notifications de bureau, gestionnaire `mailto:`
- Sans compte configuré : mode démonstration avec messages d'exemple

## Nouveautés 1.2.0
- **Paramètres accessibles partout** : icône ⚙ dans la barre d'en-tête, bouton en bas de la barre latérale, `Ctrl+,`, menu ☰ et palette `Ctrl+K`. Ils s'ouvrent comme une page dans la fenêtre (bouton « Retour » ou Échap) — plus de fenêtre qui se perd.
- Après l'ajout d'un premier compte, retour automatique à la boîte de réception
- **Nouveau design inspiré de Spark** : grand bouton « Nouveau message », messages en cartes arrondies, avatars colorés, onglets en pastilles (Personnes / Notifications / Newsletters), en-tête épuré avec recherche en pilule, boutons ronds, lecteur aéré, thème clair et sombre revus

## Nouveautés 1.1.0
- **Volets redimensionnables** : poignée large entre la liste et la lecture (et entre la barre latérale et la liste), tailles mémorisées
- **3 dispositions** : colonnes, lecture en bas, liste seule (menu « Disposition » de la barre d'en-tête, ou touche `\`)
- **Responsive** : barre latérale auto (étendue → icônes → masquée), barres d'outils défilantes, mode une colonne en fenêtre étroite
- **Swipe** sur les messages (souris, pavé tactile à deux doigts, écran tactile) : action courte / longue configurables
- **Spam & blocage** : message, expéditeur ou domaine ; commandes dans `Ctrl+K`, menu clic droit, menu « … » du lecteur et gestes ; liste de blocage gérable dans Paramètres
- **Règles automatiques** (expéditeur / objet / destinataires → archiver, supprimer, spam, lu, favori, épingler)
- **Recherches enregistrées** dans la barre latérale, rappels « si pas de réponse », modèles de réponse, zoom du texte
- **Paramètres revus** : validations, test de connexion, fenêtre unique, remise à zéro de l'apparence, vidage du cache

## Notes
- Gmail / Yahoo / iCloud : utiliser un « mot de passe d'application ».
- Les épingles et reports sont locaux (non synchronisés avec le serveur).
- Mots de passe : trousseau système si `python3-keyring` est présent, sinon `~/.config/mintmail/config.json` (droits 600).
- Données : `~/.config/mintmail` (réglages), `~/.local/share/mintmail` (cache, pièces jointes).
