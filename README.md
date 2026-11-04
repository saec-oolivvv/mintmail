# MintMail 1.0.0

Client mail moderne pour Linux Mint (Python / GTK3), inspiré de Spark Mail.

## Installation / mise à jour
```bash
unzip mintmail-1.0.0.zip && cd mintmail-1.0.0
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

## Notes
- Gmail / Yahoo / iCloud : utiliser un « mot de passe d'application ».
- Les épingles et reports sont locaux (non synchronisés avec le serveur).
- Mots de passe : trousseau système si `python3-keyring` est présent, sinon `~/.config/mintmail/config.json` (droits 600).
- Données : `~/.config/mintmail` (réglages), `~/.local/share/mintmail` (cache, pièces jointes).
