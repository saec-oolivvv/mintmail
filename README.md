# MintMail 1.5.0

Client mail moderne pour Linux Mint (Python / GTK3), inspiré de Spark Mail.

## Installation / mise à jour
```bash
unzip mintmail-1.5.0.zip && cd mintmail-1.5.0
./install.sh            # pour l'utilisateur courant (~/.local) — si « Permission denied » : bash install.sh
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

## Nouveautés 1.5.0 — tous vos dossiers, une identité visuelle à part
- **Tous les dossiers de chaque boîte** dans la barre latérale : arborescence complète (sous-dossiers repliables, dossiers « parents » comme `[Gmail]`, accents décodés), compteurs de non lus par dossier, un compte = un groupe repliable
- **Navigation partout** : clic sur n'importe quel dossier (synchronisation à l'ouverture, chargement des anciens messages en bas de liste), `Ctrl+K` → « Aller au dossier : … »
- **Déplacer vers un dossier** : bouton du lecteur, clic droit, touche `V`, palette (« Déplacer vers un dossier… ») et assistant IA (« range mes factures dans Factures »)
- **Gérer les dossiers** (clic droit) : créer, sous-dossier, renommer, supprimer, actualiser
- **Trois identités visuelles** (Paramètres → Apparence → Style visuel), chacune en clair et en sombre :
  **Aurora** (verre dépoli sur dégradé nuit, lueurs de l'IA), **Papier** (éditorial : encre sur papier chaud, titres en empattement, filets fins), **Terminal** (monospace, angles droits, vert phosphore)
- **Structure inédite** : pastilles de comptes, rail de priorité coloré sur chaque message, barre d'outils flottante, filet dégradé, compteurs de liste

## Nouveautés 1.4.0 — l'IA au cœur de l'application
- **Assistant IA** (`Ctrl+J`) : panneau de conversation qui comprend votre boîte et propose des actions (archiver, spam, blocage, règles, brouillons, réglages…). Rien ne s'exécute sans votre clic.
- **Carte IA sur chaque message** : résumé, points clés, priorité, alerte hameçonnage, 3 réponses suggérées, ajout à l'agenda (.ics), traduction, questions libres
- **Liste augmentée** : résumé d'une ligne, badges « Important » / « Suspect », bloc « En bref » en haut de la boîte
- **Rédaction assistée** : écrire depuis une idée, améliorer, corriger, raccourcir, ton formel/amical, traduction, objet
- **Palette `Ctrl+K` et recherche** : toute phrase libre peut être confiée à l'IA (`? mails non lus de Marie`)
- **Rapidité** : liste mise à jour sans reconstruction, actions en une transaction (archiver / supprimer / spam d'expéditeur : quelques millisecondes), connexions IMAP persistantes, messages affichés par lots, réception en temps réel (IMAP IDLE), pagination
- **Un clic suffit** pour ouvrir un message (sélection simple ; sélection multiple à la demande avec `Ctrl+A` ou le bouton dédié)
- **Boutons réduire / agrandir / fermer** toujours présents ; `F11` plein écran
- **Design repensé** : cartes, actions au survol, identité visuelle IA, couleurs prédéfinies
- Sécurité IA : contenu des messages traité comme non fiable, sorties validées, confirmations, clé dans le trousseau, niveau de confidentialité réglable

## Nouveautés 1.3.0 — correctifs et sécurité
- **Démarrage** : correction du plantage au lancement (import `httpx` invalide) et de l'erreur d'initialisation de la fenêtre (synchro)
- **Paramètres** : la page s'ouvre de nouveau (erreur de nom dans la page de synchronisation, `set_border_width` sur un libellé) ; repli automatique sur une fenêtre séparée + journal d'erreurs (menu ☰ → Journal d'erreurs) ; `mintmail --diagnose`
- **IA NVIDIA** : endpoint et modèle valides par défaut, plus aucune dépendance (stdlib), vraies erreurs (clé refusée, quota…), appels hors de l'interface (plus de gel), clé stockée dans le trousseau, texte généré toujours échappé, classification automatique optionnelle
- **Synchronisation entre machines** : réécrite. Désactivée par défaut, code de jumelage obligatoire (authentification HMAC mutuelle), **mots de passe, comptes et clés jamais échangés**, données validées, ajouts uniquement
- Trousseau non bloquant, installeur `--full-reset` corrigé (confirmation demandée)

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
