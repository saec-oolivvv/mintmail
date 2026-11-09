# MintMail 1.10.0

Client mail moderne pour Linux Mint (Python / GTK3), inspiré de Spark Mail.

## Installation / mise à jour
```bash
unzip mintmail-1.6.0.zip && cd mintmail-1.6.0
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

## Nouveautés 1.10.0
- **Page « Aujourd'hui » (touche T)** : agenda du jour (Google Agenda), messages non lus jugés importants, tâches (en retard d'abord), relances en attente, brouillons préparés.
- **Tâches avec échéance lue en français** (« avant vendredi », « le 15/11 », « dans 3 jours », « fin du mois »…) : clic droit → « Ajouter aux tâches… » ou « Ajouter les N tâches détectées » ; synchronisées entre vos machines.
- **Proposer des créneaux** (clic droit, nécessite Google Agenda) : 3 créneaux libres sur des jours différents, en jours ouvrables 9h00–17h30, insérés dans une réponse à relire.
- **Brouillons de réponse préparés par l'IA** (optionnel, désactivé par défaut) pour les messages importants qui attendent une réponse : jamais envoyés, style appris sur vos envois, informations manquantes marquées [À COMPLÉTER : …].

## Nouveautés 1.9.2
- **Correctif important — clic droit** : le menu (et donc toutes les actions ✨ IA, archiver, spam, ranger…) visait toujours le dernier message reçu au lieu du message cliqué. Il agit maintenant sur le message sous le clic, y compris en mode sélection et dans l'arborescence des dossiers.

## Nouveautés 1.9.1
- **Assistant de configuration Google / Microsoft** : au premier « Se connecter », une fenêtre guide pas à pas avec un bouton « Ouvrir ↗ » par page de la console (projet, API Agenda, écran de consentement, identifiant). À faire **une seule fois** : l'identifiant se synchronise avec vos autres machines.
- **Déploiement sans aucune saisie** : un fichier `/etc/mintmail/oauth-clients.json` (exemple : `/usr/share/doc/mintmail/oauth-clients.json.example`) est utilisé par tous les utilisateurs de la machine ; le paquet peut l'embarquer.

## Nouveautés 1.9.0
- **Google Agenda** (compte Gmail connecté en OAuth) : les invitations acceptées et les rendez-vous détectés par l'IA sont ajoutés directement à votre agenda, **sans doublon** ; palette → « Agenda : prochains rendez-vous » (14 jours) et « Nouvel événement… » ; à l'ouverture d'une invitation, **alerte de conflit** ou « vous êtes libre sur ce créneau ». Mise en place : Paramètres → Agenda (Google / CalDAV) → « Autoriser Google Agenda » (activer aussi « Google Calendar API » dans la console Google Cloud). CalDAV reste disponible pour les autres agendas.
- Attention : tant que l'écran de consentement Google est en mode « Test », le jeton expire après 7 jours ; passez l'application « En production » pour un usage durable (voir l'aide, F1).

## Nouveautés 1.8.1
- **Aide intégrée complète** (touche **F1**, ☰ → Aide, ou Paramètres → Aide & Crédits) : 13 sections et plus de 60 rubriques — premiers pas, OAuth, lecture et dossiers, conversations, recherche, clic droit, palette, tous les raccourcis, rédaction, alias, envoi différé, IA (fournisseurs, assistant, classement, habitudes), spam / règles / désabonnement, pièces jointes, invitations, contacts, CalDAV, synchronisation, hors ligne, apparence, sécurité, ligne de commande, dépannage. **Recherche instantanée** (sans accents) dans toute l'aide.
- `mintmail --help` liste les options ; le texte complet de l'aide est aussi installé dans `/usr/share/doc/mintmail/AIDE.txt`.
- Des tests vérifient que l'aide reste alignée sur le code (raccourcis, options, pages de paramètres, fonctions).

## Nouveautés 1.8.0
- **Barre d'actions au survol des cadres de messages : supprimée** (actions par clic droit, raccourcis, balayage).
- **Conversations** : une ligne par fil (nombre de messages), actions sur tout le fil, liste des autres messages dans le lecteur, « ✨ Résumer la conversation ». Désactivable : Paramètres → Gestes & disposition.
- **Connexion Google / Microsoft (OAuth)**, sans mot de passe : Paramètres → Comptes → fournisseur « OAuth ». Il faut créer votre propre identifiant client (gratuit) et le coller une fois ; le jeton est stocké comme un mot de passe et synchronisé.
- **Recherche sur le serveur** : bouton « Chercher aussi sur le serveur » sous une recherche (messages jamais téléchargés).
- **IA locale (Ollama)** ou tout service compatible OpenAI : Paramètres → IA → Fournisseur ; clé facultative ; « Détecter les modèles installés ».
- **Apprentissage de vos rangements** : suggestion « selon vos habitudes », règle proposée au 3e rangement identique, classement IA qui s'y conforme ; effaçable (Paramètres → IA).
- **Pièces jointes** : miniatures, aperçu (images, texte), « Tout enregistrer », glisser vers le gestionnaire de fichiers, dépôt de fichiers dans la rédaction, alerte au-delà de 20 Mo.
- **Mode hors ligne** : déplacements, drapeaux et suppressions conservés puis rejoués dans l'ordre ; envois jamais perdus (réessais automatiques, « Boîte d'envoi… » dans la palette).
- **Contacts** (import/export vCard, synchronisés) et **invitations** : Accepter / Peut-être / Refuser envoie la réponse iCalendar à l'organisateur ; ajout à l'agenda (CalDAV facultatif : Paramètres → Agenda).
- **Identités d'envoi (alias)** avec signature propre ; la réponse part de l'alias qui a reçu le message.
- **Envoi programmé fenêtre fermée** : `mintmail --send-due`, lancé chaque minute par la minuterie utilisateur `mintmail-outbox.timer` (activée à l'installation ; session en cours : `systemctl --user daemon-reload && systemctl --user enable --now mintmail-outbox.timer`). Réservation atomique : jamais d'envoi en double.
- **Désabonnement en un clic** (RFC 8058), sinon par e-mail, sinon dans le navigateur.

## Nouveautés 1.7.0
- **Classement par l'IA, pour de vrai** : demandez à l'assistant (`Ctrl+J`) « classe mes derniers emails dans des dossiers » ou « crée un dossier Factures et range mes factures dedans ». L'IA propose un classement (dossiers existants d'abord, nouveaux dossiers seulement si besoin, 6 au maximum) ; **rien n'est créé ni déplacé avant votre validation**, ligne par ligne ou en bloc. Les dossiers manquants sont créés sur le serveur au moment de valider.
- **Clic droit sur un message : section ✨ IA** — ranger dans le dossier suggéré (ou « Suggérer un dossier… »), classer tous les messages de l'expéditeur, classer la boîte, **toujours ranger cet expéditeur dans ce dossier** (règle automatique), répondre avec l'IA (adaptée / accepter / refuser / demander des précisions / autre créneau / formel / amical / très courte), résumer, traduire, ajouter à l'agenda, demander à l'assistant. Menu ⋯ de la barre au survol : mêmes raccourcis IA.
- **Règles « Ranger dans le dossier… »** (Paramètres → Filtres), synchronisées entre machines.
- **Résumé simplifié** : la barre d'options sous le résumé (réponses suggérées, boutons, champ de question) est supprimée ; le résumé affiche seulement la synthèse, les points clés, les tâches et l'alerte d'hameçonnage. (Correction au passage : le texte du résumé pouvait ne pas s'afficher.)
- **Icône de l'application** : nouvelle icône (enveloppe + étincelle IA) en SVG et PNG de 16 à 512 px ; le lanceur est associé à la fenêtre (nom de programme / classe `mintmail`, identifiant `me.saec.mintmail`), ce qui supprime la roue dentelée générique dans la barre des tâches et le menu.
- **Synchronisation entre machines plus robuste** : diffusion sur chaque interface réseau, réponse directe aux annonces, VPN / Tailscale acceptés, machines à identifiant identique tolérées, recherche active du réseau (bouton « Rechercher les machines »), diagnostic réseau lisible dans Paramètres → Synchronisation, avertissement si l'ancien code est trop court.

## Nouveautés 1.6.6
- **`/usr/bin/mintmail --remove-local-install` ne supprime plus rien** : il LISTE d'abord les installations hors paquet (avec la version de chacune, lue sans exécuter le lanceur) et signale les versions inconnues de ce paquet. Avec `--yes`, il **met de côté** (dans `~/mintmail-sauvegarde-<date>/`, restaurable) les éléments de votre dossier personnel. Les éléments système (`/usr/local`, `/opt`) ne sont jamais touchés : il affiche seulement la commande.
- `mintmail --diagnose` affiche la version de chaque lanceur trouvé dans le PATH.

## Nouveautés 1.6.5
- **Ancienne installation locale** (faite avec `install.sh`) : elle masque le paquet .deb. Pour la retirer, utilisez **le chemin complet** : `/usr/bin/mintmail --remove-local-install` (l'ancien lanceur local ne connaît pas cette option), puis ouvrez un nouveau terminal. Réglages et courrier en cache sont conservés.

## Nouveautés 1.6.4 — fiabilité d'une machine à l'autre
- **Le lanceur utilise toujours `/usr/bin/python3`** : sur une machine où `python3` pointe vers un autre Python (conda, pyenv, venv, version installée à la main), MintMail ne trouvait pas GTK (`python3-gi`) et ne démarrait pas.
- **`mintmail --diagnose`** : rapport complet (système, Python, GTK / WebKit, modules, données, trousseau, lanceurs qui se masquent, journal) **sans aucun secret**, enregistré dans `~/.local/share/mintmail/diagnostic.txt`.
- **Démarrage protégé** : si la fenêtre ne peut pas s'ouvrir, un message clair s'affiche (au lieu de rien) avec le journal, et le choix de **mettre de côté réglages et cache** (rien n'est supprimé : `config.json.bak-…`) puis de relancer. Les comptes reviennent seuls avec la synchro. Aussi disponible : `mintmail --reset`.
- Sans interface graphique disponible : message explicatif (au lieu d'une trace Python) avec la commande d'installation des composants manquants.

## Nouveautés 1.6.3
- **Paquet .deb** : numéro de version avec « epoch » (`1:1.6.3`) pour que l'installateur n'affiche plus « une version plus récente est déjà installée » quand un ancien paquet `mintmail` portait un numéro plus élevé. Toutes les versions suivantes gardent ce préfixe `1:`.

## Nouveautés 1.6.2
- **Spam et blocage en accès direct** : la barre d'actions de chaque message (au survol) et la barre du lecteur ont maintenant des boutons **Spam ▾** et **Bloquer ▾**. Chaque menu propose le message, l'**adresse** ou **tout le domaine** — avec l'adresse et le domaine réels écrits dans le libellé — et « Débloquer » quand l'expéditeur l'est déjà. Un bouton **⋯** donne le reste : lu/non lu, épingler, favori, répondre avec l'IA, déplacer vers un dossier, reporter, tous les messages de l'expéditeur, copier l'adresse, rappel sans réponse. Touche `B` : menu Bloquer.

## Nouveautés 1.6.1
- **Paquet `.deb`** : `sudo apt install ./mintmail_1.6.1_all.deb` (dépendances installées automatiquement, mise à jour = réinstaller le .deb). `mintmail --remove-local-install` supprime une ancienne installation par `install.sh`.
- **Correctif** : la barre d'actions qui apparaît au survol d'un message clignotait et n'était pas cliquable (le pointeur quittait la carte dès que la barre apparaissait). Elle reste maintenant affichée tant que le pointeur est sur le message ou sur la barre, et ses boutons fonctionnent.

## Nouveautés 1.6.0 — synchronisation automatique complète entre machines
- **Tout se synchronise tout seul** dès que deux machines se voient (même code de jumelage) : **comptes de messagerie avec leurs mots de passe**, signatures, **IA** (activation, modèle, endpoint, **clé API**), **modèles de réponse rapide**, règles, blocages / spam, recherches enregistrées, apparence et gestes. Aucun clic nécessaire.
- **Ajout, modification ET suppression** se propagent (dernière modification gagnante, avec « pierres tombales »). Un compte ajouté sur un poste apparaît sur les autres en quelques secondes et commence à se synchroniser.
- Vérifications automatiques : à la détection d'un pair, à chaque modification locale (surveillée en continu), au démarrage et toutes les 30 s ; voyant « ⇄ » en bas de la barre latérale.
- **Chiffré et authentifié** : puisque des identifiants circulent, canal chiffré (HMAC-SHA256 en mode compteur + étiquette), authentification mutuelle par code de jumelage (12 caractères minimum, bouton « Générer »), protection contre l'altération, le rejeu et le réordonnancement.
- Ce qui reste propre à chaque machine : taille de fenêtre, disposition, zoom, dossiers repliés, courrier téléchargé.
- Prérequis : horloges des machines à peu près à l'heure (NTP, par défaut sous Linux) ; pare-feu : UDP 54321 et TCP 54322 entre les machines (ou renseigner l'adresse IP de l'autre machine dans Paramètres → Synchronisation).

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
