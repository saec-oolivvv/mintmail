# Aide de MintMail 1.14.1
_Généré par `make docs` depuis l'aide intégrée (touche F1 dans l'application)._

## Premiers pas

### Ajouter votre compte mail

Paramètres (⚙ ou Ctrl+,) → Comptes → « ＋ Ajouter un compte ».  
• Choisissez le fournisseur : les serveurs IMAP/SMTP se remplissent seuls (Gmail, Outlook, Yahoo, iCloud, OVH, Infomaniak…). Autre fournisseur : saisissez les serveurs et les ports à la main.  
• Cliquez « Tester la connexion » (IMAP + SMTP) puis « Enregistrer ». La première synchronisation démarre aussitôt.  
• Gmail, Yahoo, iCloud : créez un « mot de passe d'application » dans la sécurité du compte et utilisez-le à la place du mot de passe habituel — ou, pour Gmail et Outlook, choisissez le fournisseur « OAuth » (voir « Connexion Google / Microsoft »).  
• Plusieurs comptes : ajoutez-les tous ; la barre latérale montre un cercle coloré par compte et la boîte unifiée les réunit.

### Connexion Google / Microsoft (OAuth, sans mot de passe)

Paramètres → Comptes → fournisseur « Gmail — connexion Google (OAuth) » ou « Outlook / Microsoft 365 — connexion Microsoft (OAuth) ».  
• MintMail ne peut pas créer cet identifiant à votre place : Google et Microsoft exigent que ce soit vous, connecté à votre compte (ne donnez JAMAIS vos identifiants à un programme ou à un assistant pour cela). Au premier clic sur « Se connecter », un assistant vous guide en 2 à 4 étapes ; chaque bouton « Ouvrir ↗ » ouvre la bonne page de la console. Google : projet « MintMail », « Google Calendar API » activée, écran de consentement « Externe » avec les portées https://mail.google.com/ et calendar.events, vous comme utilisateur test, puis « Publier » ; identifiant de type « Application de bureau ». Microsoft : inscription d'application « client public » avec l'URI http://localhost.  
• À faire UNE FOIS : l'identifiant saisi se synchronise avec vos autres machines (Synchronisation P2P).  
• Plusieurs postes ou une équipe : un fichier /etc/mintmail/oauth-clients.json de la forme {"google": {"client_id": "…", "client_secret": "…"}} est utilisé par tous les utilisateurs de la machine, sans aucune saisie (un exemple est installé dans /usr/share/doc/mintmail/oauth-clients.json.example ; le paquet peut aussi l'embarquer).  
• Pour le courrier seul, sans rien créer chez Google : choisissez le fournisseur Gmail classique avec un « mot de passe d'application » (compte Google → Sécurité → validation en 2 étapes → mots de passe d'application) : 1 minute, mais pas d'agenda.  
• « Se connecter » ouvre la page du fournisseur dans votre navigateur ; MintMail ne voit jamais votre mot de passe. Il garde un jeton révocable à tout moment depuis votre compte Google ou Microsoft, stocké comme un mot de passe (trousseau) et synchronisé avec vos autres machines.  
• « Reconnecter » renouvelle le jeton si le fournisseur l'a révoqué.  
• Google, important : tant que l'écran de consentement est en mode « Test », Google fait EXPIRER le jeton au bout de 7 jours (il faut se reconnecter). Pour un usage personnel durable, passez l'application en « En production » dans la console Google Cloud : un écran « application non validée » s'affiche une fois, à accepter (jusqu'à 100 utilisateurs, aucune validation nécessaire).

### Mode démonstration

Sans compte configuré, MintMail affiche des messages d'exemple pour essayer l'interface (dossiers, IA, rédaction). Ajouter un vrai compte remplace automatiquement la démo.

### Découvrir la fenêtre

• Barre latérale : vues intelligentes (Boîte de réception, Non lus, Favoris, Épinglés, Reportés, Brouillons), comptes et leurs dossiers, recherches enregistrées, voyant de synchronisation entre machines (⇄) en pied.  
• Liste des messages au centre, lecteur à droite. Les séparateurs se déplacent à la souris et la position est retenue.  
• Un clic ouvre toujours le message. Le mode sélection (touche X ou bouton) affiche des cases à cocher pour agir sur plusieurs messages.  
• Menu ☰ : palette de commandes, paramètres (aussi en fenêtre séparée), clair / sombre, tout marquer comme lu, journal d'erreurs, à propos.  
• Fenêtre étroite : la barre latérale se replie et le lecteur passe en pleine largeur (bouton Retour). F11 : plein écran.  
Astuce : Ctrl+K ouvre la palette de commandes ; tapez quelques lettres pour trouver n'importe quelle action.

### Disposition de la liste et du lecteur

Paramètres → Gestes & disposition : colonnes (liste à gauche, lecteur à droite), liste en haut / lecteur en bas, ou liste seule. La touche \ bascule rapidement entre colonnes et liste seule. Le panneau latéral peut être réduit en rail d'icônes.

## Lire et organiser

### La liste des messages

Chaque ligne montre l'expéditeur, l'objet, un aperçu (ou le résumé IA ✨ s'il existe), l'heure, une barre colorée de priorité (rouge : important ou suspect, bleue : non lu) et des pastilles (pièce jointe, favori, épingle, nombre de messages d'une conversation). La liste se charge par pages et en continu : descendez pour afficher les messages plus anciens (jusqu'aux plus vieux du serveur).

### Conversations

Les messages d'un même fil sont regroupés en UNE ligne avec le nombre de messages. Ouvrir la ligne affiche le dernier message ; « Conversation · N autres messages » au-dessus du corps liste les précédents (cliquez pour les lire). Archiver, supprimer, marquer, reporter ou ranger une conversation vaut pour tous ses messages du même dossier. Ouvrir une conversation la marque lue.  
Désactivation : Paramètres → Gestes & disposition → « Regrouper en conversations ». Les résultats de recherche restent à plat.

### Catégories

Dans la boîte de réception, les pastilles Tout / Personnes / Notifications / Newsletters filtrent selon le type d'expéditeur (détecté automatiquement : mails de vraies personnes, notifications de services, newsletters et promotions).

### Dossiers de vos boîtes

Tous les dossiers IMAP de chaque compte sont visibles dans la barre latérale (arborescence repliable, nombre de non lus). • Cliquez un dossier pour le parcourir ; le bouton « anciens messages » charge plus loin dans l'historique.  
• Déplacer : touche V, menu clic droit ou ☰, palette (« Déplacer vers… »), ou l'IA.  
• Créer, renommer, supprimer un dossier ou un sous-dossier : clic droit sur un dossier ou un compte.  
• Les dossiers spéciaux (Envoyés, Brouillons, Archives, Spam, Corbeille) sont reconnus quelle que soit la langue du serveur.

### Favoris, épingles, reports, relances

• Favori (S) : étoile synchronisée avec le serveur. Épingle (P) : garde le message en haut de la liste ; elle est AUSSI enregistrée sur la boîte (mot-clé IMAP), donc visible sur vos autres postes à leur prochaine synchronisation. Sur Gmail, c'est une ÉTIQUETTE « MintMail-Epingles », visible dans Gmail (web et mobile) ; sur un serveur IMAP standard, un mot-clé IMAP, invisible dans la plupart des messageries web mais vu par vos autres postes MintMail. Si le serveur ne peut pas la garder, MintMail vous prévient au premier essai et l'épingle reste sur ce poste seulement ; « mintmail --check-pins » donne le verdict exact. Palette → « Envoyer mes épingles vers la boîte » envoie celles faites avant la 1.13.2.  
• Reporter (H = demain 8 h, ou clic droit → Reporter) : le message disparaît puis revient en haut de la boîte à l'heure choisie (plus tard aujourd'hui, demain, ce week-end, lundi, la semaine prochaine…).  
• « Me rappeler si pas de réponse » (menu ⋯ du lecteur ou clic droit) : MintMail vous prévient si le destinataire n'a pas répondu après 3 jours.

### Rechercher

Ctrl+F ou / : la recherche est instantanée sur l'objet, l'expéditeur, les destinataires et le corps des messages téléchargés.  
Opérateurs combinables : from:marie · is:unread · is:starred · has:attachment (ex. « from:marie facture is:unread »).  
• « 🔎 Chercher aussi sur le serveur » (sous la recherche, ou palette) interroge tout le serveur, même les messages jamais téléchargés, et ajoute les résultats à la liste.  
• Recherche en langage naturel : commencez par « ? » (ex. « ? les mails non lus de Marie cette semaine ») — l'IA traduit votre phrase en critères.  
• « Enregistrer la recherche » en fait une vue permanente dans la barre latérale.  
Astuce : commencez la recherche par ? pour poser une question à l'IA (par exemple « ? factures de mars »).

### Actions sur plusieurs messages

Mode sélection (X) → cochez ou Ctrl+A, puis archiver (E), supprimer, marquer, déplacer (V), spam (!)… Une barre d'actions groupées s'affiche. Les actions sont instantanées ; un bandeau « Annuler » reste disponible quelques secondes.  
Astuce : X active le mode sélection, Ctrl+A sélectionne tout.

### Gestes de balayage (swipe)

Faites glisser une ligne à la souris, au pavé tactile ou au doigt. Par défaut : droite = archiver, droite longue = supprimer, gauche = reporter, gauche longue = lu/non lu. Personnalisable dans Paramètres → Gestes & disposition (archiver, supprimer, reporter, lu, favori, épingle, spam, bloquer, rien) et inversion du sens pour le pavé tactile.

## Aujourd'hui, tâches et créneaux

### Page « Aujourd'hui » (touche T)

Touche T, menu ☰ → Aujourd'hui, ou palette. Une seule fenêtre pour démarrer la journée :  
• 📅 Agenda du jour (Google Agenda, si activé : Paramètres → Agenda). Option : Paramètres → Apparence → « Ouvrir la page Aujourd'hui au lancement ».  
• ⚡ À traiter en priorité : vos messages NON LUS que le tri IA juge importants (clic = ouvre le message). Sans IA, le tri se limite à des indices simples.  
• ☑ Tâches ouvertes, en retard d'abord (cochez pour terminer, ✉ pour ouvrir le message d'origine) et un champ pour en ajouter une.  
• ⏳ En attente de réponse : vos relances programmées (« Me rappeler si pas de réponse »).  
• ✨ Brouillons de réponse préparés par l'IA, à relire (voir plus bas).

### Tâches et échéances

• Créer : clic droit sur un message → « ✔ Ajouter aux tâches… », ou « ✨ Ajouter les N tâche(s) détectée(s) » (celles trouvées par l'analyse IA du message), ou palette → « Nouvelle tâche… », ou le champ de la page Aujourd'hui.  
• L'échéance est lue dans le texte, en français : « demain », « après-demain », « avant vendredi », « ce vendredi », « le 15/11 », « avant le 20 novembre », « dans 3 jours », « dans 2 semaines », « la semaine prochaine », « fin de semaine », « fin du mois », « le 20 ». Un nom de jour désigne sa prochaine occurrence (aujourd'hui exclu, sauf « ce lundi »). Aucune date trouvée : la tâche n'a pas d'échéance. Les dates et heures anglaises ne sont pas lues.  
• Une tâche déjà ajoutée pour le même message n'est jamais dupliquée. Les tâches se synchronisent entre vos machines (la modification la plus récente l'emporte).

### Proposer des créneaux (d'après Google Agenda)

Clic droit sur un message → « 📅 Proposer des créneaux (agenda) » → 30 min / 1 h / 1 h 30. MintMail lit votre agenda, trouve 3 créneaux libres sur des jours ouvrables DIFFÉRENTS et ouvre la réponse avec le texte « Je vous propose les créneaux suivants : … » à relire et envoyer.  
Règles fixes : lundi–vendredi, de 9h00 à 17h30, à partir de dans 2 heures, sur les 15 prochains jours ; les événements « occupés » (y compris les journées entières) bloquent, les événements marqués « disponible » non. Le texte suit la langue de l'interface. Nécessite Google Agenda activé (Paramètres → Agenda) ; l'option n'apparaît pas sinon.

### Brouillons de réponse préparés par l'IA (optionnel)

Paramètres → IA → « Préparer des brouillons de réponse (messages importants) » (désactivé par défaut).  
• Quand arrive un message que l'IA juge important, de type « personne », qui attend une réponse (moins de 3 jours), MintMail prépare un brouillon dans Brouillons (3 par passage au maximum). Il n'est JAMAIS envoyé : vous l'ouvrez, le relisez, le corrigez, puis vous envoyez.  
• Le brouillon imite votre style d'après quelques-uns de vos messages envoyés : ces extraits sont donc envoyés au fournisseur d'IA (jamais avec Ollama).  
• L'IA a pour consigne de ne rien inventer : toute information manquante est marquée [À COMPLÉTER : …] — relisez avant d'envoyer, un modèle peut se tromper.  
• Les brouillons préparés apparaissent aussi dans la page Aujourd'hui (touche T).

## Clic droit, palette et raccourcis

### Menu clic droit sur un message

• Répondre, Répondre à tous, Transférer, ✨ Répondre avec l'IA.  
• Archiver, Supprimer, Marquer lu/non lu, Favori, Épingler, Reporter, Déplacer vers un dossier.  
• Signaler comme spam, Mettre l'expéditeur en spam, Bloquer l'expéditeur, Voir tous ses messages, Ajouter aux contacts, Se désabonner (si le message le propose).  
• Section ✨ IA : Ranger dans le dossier suggéré (ou « selon vos habitudes », ou « Suggérer un dossier… »), Classer tous les messages de l'expéditeur, Classer ma boîte de réception, Toujours ranger cet expéditeur dans ce dossier (règle), Répondre avec l'IA ▸ (adaptée, accepter, refuser poliment, demander des précisions, autre créneau, ton formel, ton amical, très courte), Résumer la conversation, Résumer / analyser, Traduire, Ajouter à l'agenda (si un rendez-vous est détecté), Demander à l'assistant à propos de ce message.  
Si l'IA n'est pas activée, la section propose « Activer l'IA ».

### Barre du lecteur

Répondre, Répondre à tous, Transférer, Archiver, Supprimer, ✨ Répondre avec l'IA, Spam ▾ et Bloquer ▾ (ce message, l'adresse ou tout le domaine — avec l'adresse réelle écrite dans le choix), Déplacer, Reporter, Favori, Épingler, et le menu ⋯ (lu/non lu, spam, blocage, débloquer, rappel de relance, etc.).

### Palette de commandes (Ctrl+K)

Tapez quelques lettres pour retrouver une action : répondre, archiver, déplacer vers un dossier, spam / bloquer l'expéditeur ou son domaine, se désabonner, résumer, traduire, ouvrir les contacts ou les identités, agenda et nouvel événement, boîte d'envoi, chercher sur le serveur, changer de vue, de style, de disposition, d'affichage… Entrée exécute, Échap ferme.

### Tous les raccourcis clavier

```
C                  Nouveau message
R                  Répondre
A                  Répondre à tous
F                  Transférer
E                  Archiver
# / Suppr          Supprimer
S                  Favori
P                  Épingler
U                  Marquer lu / non lu
H                  Reporter à demain 8 h
J / K              Message suivant / précédent
/  ou  Ctrl+F      Rechercher
Ctrl+K             Palette de commandes
Ctrl+A             Tout sélectionner
!                  Signaler comme spam
B                  Menu Bloquer (adresse / domaine)
\                  Basculer colonnes / liste seule
X                  Mode sélection
Ctrl+J             Assistant IA
F11                Plein écran
? … (recherche)    Poser une question à l'IA
Ctrl+,             Ouvrir les paramètres
Ctrl+R             Actualiser
Échap              Annuler la sélection / la recherche
V                  Déplacer vers un dossier
T                  Aujourd'hui (agenda, priorités, tâches)
Ctrl+N             Nouveau message
Ctrl+Maj+,         Paramètres dans une fenêtre séparée
F1                 Aide
```

## Rédiger et envoyer

### Nouveau message, réponse, transfert

C ou Ctrl+N : nouveau message. R / A / F : répondre, répondre à tous, transférer (le message cité est repris). Les adresses se complètent d'après votre carnet d'adresses et vos correspondants récents ; Cc et Cci s'affichent à la demande. Fermer la rédaction avec du contenu propose d'enregistrer un brouillon (retrouvé dans Brouillons).

### Réponse rapide

Sous chaque message : quatre réponses toutes faites (« Merci ! », « OK, bien reçu 👍 »…) et un champ « Réponse rapide… » qui envoie une réponse courte sans ouvrir la rédaction. Le bouton ✨ développe votre phrase en réponse complète avec l'IA.

### Signatures HTML

Paramètres → Signatures : une signature par compte (mise en forme, liens, images), aperçu en direct. Elle est insérée automatiquement ; changer de compte dans le champ « De » change la signature.

### Identités d'envoi (alias)

Paramètres → Identités d'envoi : ajoutez une adresse supplémentaire (alias) rattachée à un compte, avec son nom affiché et sa signature. Elle apparaît dans le champ « De » de la rédaction (« · alias »). Quand un message reçu était adressé à un alias, la réponse part automatiquement de cet alias. Le serveur du compte doit autoriser l'alias.

### Modèles de réponse

Paramètres → Modèles de réponse : textes prêts à insérer (accusé de réception, proposition de rendez-vous…). Ils se synchronisent entre vos machines.

### Envoi annulable et envoi différé

• Après « Envoyer », un bandeau « Annuler » reste affiché quelques secondes (3 à 30 s, Paramètres → Apparence).  
• « Envoyer plus tard » (horloge) : choisissez ce soir, demain, lundi ou une date précise.  
• Les messages programmés partent même fenêtre fermée : une minuterie utilisateur (mintmail-outbox) lance « mintmail --send-due » chaque minute. Si elle n'est pas encore active dans votre session : systemctl --user daemon-reload && systemctl --user enable --now mintmail-outbox.timer.  
• Un double envoi est impossible (réservation atomique entre la fenêtre et la minuterie).  
• Palette → « Boîte d'envoi » : voir les messages en attente ou programmés, « Envoyer maintenant » ou « Annuler l'envoi ».

### Pièces jointes à l'envoi

Bouton trombone, ou glissez des fichiers depuis votre gestionnaire de fichiers sur la fenêtre de rédaction (zone des pièces jointes). Le total s'affiche ; au-delà de 20 Mo il passe en rouge : la plupart des serveurs refusent plus de 20-25 Mo.

### ✨ Aide à l'écriture

Menu « ✨ IA » de la rédaction : rédiger à partir d'une idée, améliorer le texte, corriger l'orthographe, raccourcir, développer, ton plus formel, ton plus amical, traduire, suggérer un objet. L'opération s'applique à la sélection, sinon à tout votre texte (signature et citation exclues). Relisez toujours avant d'envoyer.

## Intelligence artificielle

### Activer l'IA et choisir le fournisseur

Paramètres → ✨ Intelligence artificielle. L'IA est désactivée par défaut.  
• NVIDIA (cloud) : collez votre clé API (nvapi-…), elle est stockée dans le trousseau du système.  
• Ollama (local) : tout reste sur votre machine, aucune clé. Installez Ollama, lancez « ollama serve » et téléchargez un modèle (« ollama pull llama3.2 »), puis cliquez « Détecter les modèles installés ».  
• Autre service compatible OpenAI : adresse (https://… ; http:// seulement sur cette machine ou le réseau local), modèle, clé facultative.  
« Tester la connexion » vérifie le tout. Le fournisseur, l'adresse et le modèle se synchronisent entre vos machines (la clé aussi, chiffrée).

### Confidentialité

Une fois l'IA activée, le texte des messages traités est envoyé au fournisseur choisi (jamais avec Ollama). Réglage « Confidentialité » : texte complet (meilleurs résultats) ou minimal (500 premiers caractères). Les résultats sont gardés en cache local ; « Vider le cache IA » les efface. L'IA ne fait JAMAIS d'action sans votre accord : elle propose, vous confirmez.

### Résumé de chaque message

À l'ouverture, un encadré ✨ RÉSUMÉ affiche : une phrase de synthèse, les points clés, les tâches à faire, l'indication URGENT / peu important, et une alerte ⚠ si le message ressemble à de l'hameçonnage. Sans IA, un résumé local simple est affiché. Interrupteur « Analyser chaque message à l'ouverture » dans les réglages ; sinon, clic droit → Résumer / analyser. Pas de barre de boutons : toutes les actions sont dans le clic droit.

### Assistant (Ctrl+J)

Un panneau conversationnel capable d'AGIR sur votre boîte. Exemples :  
• « Résume ma boîte » · « Quels messages sont urgents ? »  
• « Classe mes derniers emails dans des dossiers »  
• « Crée un dossier Factures et range mes factures dedans »  
• « Archive les newsletters déjà lues » · « Mets en spam les mails promotionnels »  
• « Bloque le domaine exemple.com » · « Crée une règle pour les notifications GitHub »  
• « Rédige une relance polie à Marie » · « Ouvre les paramètres de l'IA »  
L'assistant affiche un plan d'actions (« 12 messages seront archivés »…). Vous validez ligne par ligne ou « Tout exécuter ». Les actions possibles : archiver, supprimer, spam, lu/non lu, favori, épingle, reporter, déplacer (le dossier est créé s'il manque), classer, créer un dossier, créer une règle, bloquer un expéditeur, rédiger, ouvrir une page de paramètres, résumer.

### Classement par l'IA dans des dossiers

• Dans l'assistant : « classe mes emails » ; ou clic droit → ✨ Classer tous les messages de l'expéditeur / Classer ma boîte de réception.  
• L'IA propose un dossier par message : un dossier existant en priorité, sinon un nouveau nom court (6 nouveaux dossiers au maximum). Elle suit vos habitudes de rangement, la langue de l'interface.  
• Rien n'est déplacé ni créé avant votre validation (ligne par ligne ou en bloc). Les dossiers manquants sont créés sur le serveur au moment de valider.  
• Pour un seul message : ✨ Ranger dans « … » (suggéré par l'analyse, ou « selon vos habitudes »), ou « Suggérer un dossier… ».

### Vos habitudes de rangement

Quand vous rangez des messages à la main dans un dossier, MintMail retient « expéditeur → dossier » (en local seulement). Dès la 2e fois, il suggère ce dossier (« selon vos habitudes ») ; à la 3e, il propose de créer une règle automatique. Paramètres → IA → « Oublier mes habitudes de rangement » efface tout.

### Tri automatique et « En bref »

• Tri : les nouveaux messages reçoivent une priorité (barre colorée, pastille « Important ») et les suspects sont signalés « Suspect ».  
• « En bref » : en haut de la boîte, un résumé de ce qui compte aujourd'hui. Chaque fonction a son interrupteur dans les réglages de l'IA.

### Traduction, questions, agenda

Clic droit → Traduire ce message (dans la langue réglée). Assistant ou « ? » : posez une question sur le message ouvert. Si l'IA détecte un rendez-vous : « Ajouter à l'agenda » (voir « Invitations et agenda »).

### Langue et ton

Paramètres → IA : langue de l'IA (français, anglais, néerlandais, allemand, espagnol) et ton des rédactions (neutre, formel, amical).

### Limites à connaître

Les modèles peuvent se tromper : vérifiez les résumés, les classements et les brouillons. Un petit modèle local est plus lent et moins précis qu'un grand modèle cloud. Une erreur de réseau ou de clé s'affiche en clair, sans bloquer le reste de MintMail.

## Spam, blocage, règles, désabonnement

### Spam et blocage

• Signaler comme spam (!) : déplace le message dans Spam.  
• Spam ▾ / Bloquer ▾ (lecteur) ou menu clic droit : choisissez le message seul, l'adresse de l'expéditeur, ou tout son domaine (@exemple.com). Tous les messages concernés sont déplacés aussitôt, et les prochains aussi (spam → Spam, bloqué → Corbeille).  
• Touche B : menu Bloquer. Débloquer : menu ⋯ du lecteur ou Paramètres → Filtres & blocage. Un bandeau Annuler reste disponible.  
• Les listes (bloqués, spam) se gèrent dans Paramètres → Filtres & blocage et se synchronisent entre vos machines.

### Règles automatiques

Paramètres → Filtres & blocage → Règles : « Si l'expéditeur / l'objet / le destinataire contient … alors » archiver, supprimer, spam, marquer lu, favori, épingler, ou ranger dans le dossier … Elles s'appliquent aux nouveaux messages (et « Appliquer maintenant » à la boîte). Une règle peut aussi naître du clic droit (« Toujours ranger… ») ou de l'assistant.

### Se désabonner

Quand un message contient un lien de désabonnement (newsletters), le bouton « Désabonner » apparaît sous l'en-tête, et la commande existe dans le clic droit et la palette. • Désabonnement en un clic (RFC 8058) : MintMail envoie la demande directement, de façon sécurisée (HTTPS), après votre confirmation. • Sinon par e-mail : le message de désabonnement est envoyé pour vous. • Sinon la page du service s'ouvre dans le navigateur. Ensuite, MintMail propose « Mettre en spam » si des messages arrivent encore.

### Images distantes et hameçonnage

Les images distantes (pixels espions) sont bloquées par défaut : bandeau « Images distantes bloquées » → Afficher, ou réglage global dans Apparence. Le HTML des messages est nettoyé (pas de scripts). Les messages suspects sont signalés.

## Pièces jointes, invitations, contacts, agenda

### Pièces jointes reçues

Sous l'en-tête : une pastille par fichier (miniature pour les images, nom, taille).  
• Clic : aperçu intégré des images et des fichiers texte (txt, csv, json, md, log…), sinon ouverture avec l'application par défaut (PDF, Office…).  
• Clic droit : Ouvrir, Aperçu, Enregistrer sous…, Copier le chemin.  
• « ⬇ Tout enregistrer » (2 fichiers ou plus) copie tout dans un dossier sans rien écraser.  
• Glisser une pastille vers le gestionnaire de fichiers ou le bureau copie le fichier.  
• Sécurité : les programmes et scripts (.exe, .sh, .desktop, .AppImage…) ne sont jamais ouverts depuis MintMail (enregistrement seulement) ; les fichiers HTML, SVG et Office avec macros demandent une confirmation.

### Invitations

Un message contenant une invitation (fichier .ics) affiche un encadré 📅 avec le titre, la date et le lieu :  
• Accepter / Peut-être / Refuser envoient la réponse iCalendar à l'organisateur (compris par Outlook, Google, Apple…), depuis l'adresse qui a reçu l'invitation.  
• « Ajouter à l'agenda » : envoi à Google Agenda s'il est activé (sans doublon si vous cliquez deux fois), sinon à votre agenda CalDAV, sinon ouverture du .ics dans l'agenda de votre système.  
• Avec Google Agenda activé, MintMail vérifie à l'ouverture si le créneau est libre : « ✔ Vous êtes libre » ou « ⚠ Conflit avec … (14:00–15:00) ».  
Une annulation d'événement est signalée.

### Contacts

Paramètres → Contacts : fiches (nom, e-mail, téléphone, société, notes), recherche, import et export vCard (.vcf). Les fiches manuelles se synchronisent entre vos machines ; les correspondants repérés automatiquement dans vos messages (« auto ») alimentent la complétion des adresses. Clic droit sur un message → Ajouter aux contacts.

### Google Agenda (Gmail)

Paramètres → Agenda (Google / CalDAV) → section Google Agenda. Mise en place, une seule fois :  
1. Connectez votre compte Gmail avec le fournisseur « OAuth » (Paramètres → Comptes).  
2. Console Google Cloud (même projet que pour Gmail) → API et services → Bibliothèque → « Google Calendar API » → Activer.  
3. « Autoriser Google Agenda » : une page Google s'ouvre et l'autorisation « calendar.events » est AJOUTÉE à celle de Gmail ; activez ensuite l'interrupteur « Utiliser Google Agenda » et cliquez « Tester ».  
Ce que ça apporte :  
• Les invitations acceptées et les rendez-vous détectés par l'IA (« Ajouter à l'agenda ») arrivent directement dans Google Agenda, sans doublon.  
• Palette (Ctrl+K) → « Agenda : prochains rendez-vous » : vos 14 prochains jours ; bouton « Nouvel événement… » pour en créer un (titre, date, heure, durée, lieu).  
• À l'ouverture d'une invitation, alerte de conflit ou confirmation que vous êtes libre sur ce créneau.  
Si « autorisation de l'agenda manquante » apparaît : refaites l'étape 3. Si « l'API Google Calendar n'est pas activée » : refaites l'étape 2. Jeton expiré après 7 jours : voir la remarque sur le mode « Test » dans « Connexion Google / Microsoft ». Le réglage se synchronise entre vos machines.

### Agenda CalDAV (autre calendrier)

Paramètres → Agenda (Google / CalDAV), section CalDAV : adresse du calendrier (Nextcloud, Radicale, Fastmail, iCloud…), identifiant, mot de passe, bouton « Tester ». HTTPS obligatoire (HTTP seulement sur le réseau local). Utilisé seulement si Google Agenda est désactivé ; MintMail y ajoute les événements, il ne lit pas ce calendrier.

## Synchronisation entre vos machines

### Principe

MintMail synchronise automatiquement vos réglages entre vos ordinateurs, sans serveur ni compte : détection sur le réseau local, échange chiffré et authentifié. Synchronisés : comptes (avec mots de passe ou jetons OAuth), signatures, IA (fournisseur, modèle, clé), modèles de réponse, règles, blocages et spam, recherches enregistrées, identités d'envoi, contacts, apparence, gestes, conversations, CalDAV. Non synchronisés : le courrier lui-même (chaque machine le lit sur le serveur), la taille de fenêtre, la disposition, le zoom, les dossiers repliés, vos habitudes de rangement.

### Mise en place

Paramètres → Synchronisation P2P : activez-la et saisissez le MÊME code de jumelage (12 caractères minimum ; « Générer » en propose un) sur chaque machine. Un ancien code plus court désactive la synchro : générez-en un nouveau. Les machines doivent être sur le même réseau (ou saisissez l'adresse IP d'une machine dans « Pairs fixes » — utile à travers un VPN), avec les horloges à l'heure (la modification la plus récente l'emporte). Ports : UDP 54321 (découverte) et TCP 54322 (échange) à autoriser dans un pare-feu.

### Le voyant ⇄ et le diagnostic

Le voyant en pied de barre latérale indique l'état (« 1 pair(s) », « synchronisé à 14:32 », « aucune machine vue »…). La page de synchronisation montre le diagnostic réseau : adresses, ports en écoute, annonces envoyées / reçues, machines d'une autre version, code trop court. « Rechercher les machines » sonde le réseau local si la détection automatique est bloquée (box, VPN, Wi-Fi invité). Toutes les machines doivent avoir la même version de MintMail.

### Sécurité de la synchro

Le canal est chiffré et authentifié par le code de jumelage ; les mots de passe ne circulent jamais en clair ; les données reçues sont strictement validées avant d'être appliquées. Gardez le code secret : quiconque le connaît et partage votre réseau peut se jumeler.

## Hors ligne et fiabilité

### Mode hors ligne

Si le réseau tombe, vos actions (déplacer, archiver, supprimer, marquer lu, favori) restent instantanées dans l'interface et sont enregistrées : elles sont rejouées dans l'ordre dès le retour du réseau. Le message d'état indique « Hors ligne — N action(s) en attente ». Un refus définitif du serveur abandonne l'action avec un message clair (jamais de boucle infinie).

### Envois jamais perdus

Un message dont l'envoi échoue à cause du réseau est conservé et réessayé automatiquement (chaque minute, jusqu'à 10 fois). Un refus du serveur (adresse refusée, identifiants…) vous est rendu avec « Rouvrir » pour corriger. Les messages programmés partent aussi fenêtre fermée (voir « Envoi annulable et envoi différé »).

### Réception en temps réel

MintMail utilise IMAP IDLE : les nouveaux messages arrivent en quelques secondes, avec une notification de bureau (désactivable). Une actualisation complète a lieu toutes les N minutes (Apparence, 1 à 60) ou à la demande (Ctrl+R).

### Performances

Connexions IMAP persistantes, chargement progressif, liste mise à jour sans reconstruction, actions groupées en une transaction : archiver ou mettre un expéditeur en spam se fait en quelques millisecondes dans l'interface, le serveur suit en arrière-plan.

## Apparence et réglages

### Styles et thème

Paramètres → Apparence : trois styles — Aurora (sombre lumineux, défaut), Papier (clair chaleureux), Terminal (vert sur noir) — chacun en clair ou sombre (ou selon le système), couleur d'accent, densité de la liste (compacte, confortable, aérée), zoom du texte des messages. ☰ → « Basculer clair / sombre » pour changer en un clic.

### Autres réglages

• Charger les images distantes (non recommandé) · notifications de bureau · fréquence d'actualisation · délai d'annulation d'envoi · langue de l'interface (redémarrage nécessaire). Langues : français, anglais, néerlandais, allemand, espagnol — les trois dernières sont des traductions par IA non relues par des locuteurs natifs, et l'aide F1 reste en anglais pour elles.  
• Gestes & disposition : disposition, gestes de balayage, inversion pavé tactile, conversations.  
• Paramètres → Raccourcis : liste des touches. « Réinitialiser l'apparence » remet les valeurs par défaut.

### Pages de paramètres

Comptes · Signatures · Apparence · ✨ Intelligence artificielle · Synchronisation P2P · Gestes & disposition · Filtres & blocage · Modèles de réponse · Contacts · Identités d'envoi · Agenda (Google / CalDAV) · Raccourcis · Mises à jour · Aide & Crédits. Échap revient à la boîte de réception.

## Mises à jour automatiques

### Comment ça marche

MintMail cherche une nouvelle version sur GitHub (dépôt réglé dans Paramètres → Mises à jour) au plus UNE FOIS PAR JOUR et vous l'annonce. Une seule requête anonyme est envoyée, sans aucune donnée personnelle. Désactivable dans Paramètres → Mises à jour ; palette → « Rechercher les mises à jour » pour vérifier tout de suite. Quand une version est disponible, un BANDEAU apparaît en haut de la fenêtre dès l'ouverture (« Installer maintenant », « Notes de version », « Plus tard ») et une pastille « ⬆ Mise à jour X » reste dans la barre latérale. « Plus tard » repousse le bandeau de 24 h pour cette version ; ✕ le masque jusqu'au prochain lancement. Si la fenêtre n'est pas au premier plan, une notification de bureau annonce aussi la nouvelle version (une fois). Si la mise à jour est déjà installée, le bandeau propose simplement « Relancer maintenant ». « mintmail --check-update » donne le détail dans un terminal.

### Installer en un clic

Paramètres → Mises à jour → « Installer la mise à jour » (ou « Installer maintenant » dans le bandeau) : le paquet est téléchargé avec une barre de progression, sa signature est vérifiée, puis le système demande votre mot de passe administrateur. Le bandeau passe à « installé » avec un bouton « Relancer maintenant », qui apparaît aussi dans Paramètres → Mises à jour. Rien ne s'installe sans votre accord.

### Sécurité des mises à jour

• Chaque version est signée par SAEC. La clé de vérification est installée avec MintMail (/usr/share/mintmail/update-pubkey.pem, propriété de root) : aucun réglage, aucune « Release » et aucun compte GitHub piraté ne peut la remplacer. GitHub ne sert que de transport.  
• Refusés : signature absente ou invalide, paquet qui n'est pas MintMail, version qui n'est pas strictement plus récente (aucun retour en arrière), téléchargement corrompu ou trop gros, hôte inattendu.  
• Le programme qui installe s'exécute en administrateur, copie le paquet dans un dossier privé, re-vérifie tout sur cette copie, puis installe avec apt.  
• Sans clé de vérification installée, MintMail vous INFORME seulement des nouvelles versions.

### Si l'installation automatique est désactivée

La page Mises à jour en donne la raison. Clé de vérification absente : ce MintMail n'a pas été construit par la chaîne de publication signée. pkexec absent : sudo apt install policykit-1. Dans tous les cas, vous pouvez télécharger le .deb de la « Release » sur GitHub et faire : sudo apt install ./mintmail_X.Y.Z_all.deb.

### Publier une version (développeurs)

Voir docs/RELEASING.md dans le dépôt : numéro de version unique (fichier VERSION), journal CHANGELOG.md, étiquette vX.Y.Z, paquet signé par tools/release.sh.

## Sécurité et vie privée

### Où sont vos données

• Réglages : ~/.config/mintmail/config.json (mots de passe et clés dans le trousseau du système quand il est disponible).  
• Cache des messages : ~/.local/share/mintmail/cache.db · Journal : ~/.local/share/mintmail/mintmail.log · Rapport de diagnostic : ~/.local/share/mintmail/diagnostic.txt.  
• Le courrier reste sur votre serveur ; le cache local est une copie. Supprimer un compte efface son cache, pas vos mails.

### Ce qui protège

• Connexions IMAP/SMTP chiffrées (TLS) avec vérification des certificats ; OAuth sans mot de passe pour Gmail et Outlook.  
• Courrier reçu : le HTML est reconstruit par liste blanche (scripts, formulaires, cadres, redirections, styles dangereux supprimés) et affiché sous une politique de sécurité de contenu ; images distantes bloquées par défaut ; JavaScript désactivé ; aucun cookie ni cache conservé.  
• Liens : seuls http, https et mailto s'ouvrent (jamais file:, javascript:, smb:, ssh:…). Pièces jointes : programmes et scripts (.exe, .sh, .desktop, .AppImage…) jamais ouverts depuis MintMail (enregistrement seulement) ; fichiers à risque (HTML, SVG, macros Office…) demandent une confirmation.  
• Vos données : dossiers de MintMail en 0700 et fichiers en 0600 (courrier, pièces jointes, réglages, journal : illisibles par les autres comptes de la machine).  
• Synchronisation chiffrée et authentifiée, limitée au réseau local ; codes faibles refusés ; désabonnement et CalDAV en HTTPS, sans requête vers votre réseau interne.  
• IA : envoi de texte seulement si vous l'activez, jamais avec Ollama, aucune action sans validation ; un message piégé peut cependant tromper un modèle (résumé ou classement faussé) : vérifiez avant de valider.  
• Limites connues et rapport d'audit : fichier SECURITY.md (dépôt du projet et /usr/share/doc/mintmail/).

### Signaler une faille de sécurité

Écrivez à contact@saec.me en décrivant le problème et comment le reproduire. Merci de ne pas le publier avant correction. Une version corrigée sera publiée dans les meilleurs délais ; seule la dernière version est maintenue.

### Journal d'erreurs

☰ → Journal d'erreurs affiche les derniers incidents. En cas de problème au démarrage, MintMail affiche un message clair et propose de mettre de côté réglages et cache (rien n'est supprimé).

## Ligne de commande et dépannage

### Options de la commande mintmail

```
mintmail
    Lance l'application.
mintmail --help
    Affiche cette liste d'options.
mintmail --version
    Affiche la version installée.
mintmail --settings
    Ouvre directement les paramètres. Avec --window : dans une fenêtre séparée.
mintmail mailto:adresse@exemple.be
    Ouvre la rédaction pour cette adresse (MintMail sait gérer les liens mailto:).
mintmail --diagnose
    Rapport complet SANS secret (système, Python, GTK, modules, données, synchro, trousseau, journal), enregistré dans ~/.local/share/mintmail/diagnostic.txt.
mintmail --reset
    Met de côté (sans rien supprimer) la configuration et le cache : MintMail repart propre.
mintmail --remove-local-install
    Liste les anciennes installations qui masquent le paquet ; avec --yes, les met de côté dans ~/mintmail-sauvegarde-<date>/. À lancer avec le chemin complet : /usr/bin/mintmail.
mintmail --send-due
    Envoie, sans interface, les messages programmés ou en attente dont l'heure est venue (appelé chaque minute par la minuterie utilisateur mintmail-outbox).
mintmail --check-pins
    Vérifie, pour chaque compte, si le serveur GARDE les épingles (étiquette Gmail ou mot-clé IMAP) : connexion, nombre de messages épinglés et essai réversible sur le message le plus récent. Avec --no-test : lecture seule.
mintmail --check-update
    Cherche une mise à jour et affiche le résultat détaillé (version, dépôt, signature, cause d'une erreur) : sans interface, sans rien installer. Code de sortie : 0 à jour, 10 mise à jour disponible, 1 erreur.
```

### MintMail ne démarre pas

1. Lancez « /usr/bin/mintmail » dans un terminal : le message indique la cause.  
2. « /usr/bin/mintmail --diagnose » : rapport complet (copiez-le si vous demandez de l'aide).  
3. Composant manquant : sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1.  
4. Données endommagées : « mintmail --reset » (sauvegarde puis repart propre ; les comptes reviennent seuls si la synchro est active).  
MintMail utilise toujours /usr/bin/python3 : un autre Python (conda, pyenv…) ne gêne pas.

### Une ancienne version s'ouvre / mauvaise icône

Une ancienne installation locale (dossier ~/.local, /usr/local, /opt) peut masquer le paquet : « /usr/bin/mintmail --remove-local-install » la liste, puis « --yes » la met de côté. L'icône de la barre des tâches se met à jour après avoir fermé et rouvert la session.

### Les machines ne se voient pas (synchro)

Vérifiez dans Paramètres → Synchronisation P2P : le MÊME code (12 caractères minimum) partout, la même version de MintMail, le même réseau, les ports UDP 54321 / TCP 54322 ouverts. Essayez « Rechercher les machines », ou saisissez l'IP de l'autre machine dans « Pairs fixes ».

### Gmail / Outlook refuse la connexion

Avec un mot de passe : utilisez un mot de passe d'application (Gmail, Yahoo, iCloud) et activez l'accès IMAP du compte. Sans mot de passe : fournisseur « OAuth » (voir « Connexion Google / Microsoft »). Google en mode test : ajoutez votre adresse aux utilisateurs test.

### L'IA ne répond pas

Paramètres → IA → « Tester la connexion » donne la cause. Clé invalide ou quota dépassé (NVIDIA) ; Ollama non lancé ou modèle absent (« ollama serve », « ollama pull … ») ; adresse sans https:// pour un service distant.

### Mise à jour et désinstallation

Mise à jour : sudo apt install ./mintmail_X.Y.Z_all.deb (vos réglages et votre cache sont conservés). Désinstallation : sudo apt remove mintmail (ajoutez purge pour retirer aussi les fichiers du paquet ; vos données personnelles restent dans ~/.config/mintmail et ~/.local/share/mintmail jusqu'à ce que vous les supprimiez).

## À propos et crédits

### MintMail 1.14.1

Le client mail pour Linux Mint dont l'IA est l'ADN : il lit, trie, résume, classe, rédige et agit avec vous — toujours avec votre accord.  
Développé par SAEC — https://saec.me · Logiciel libre sous licence MIT (© 2026 SAEC) : vous pouvez l'utiliser, le modifier et le redistribuer. Application GTK3 / Python, sans service cloud imposé : vos mails, vos clés et vos réglages restent chez vous.
