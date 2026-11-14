# Changelog

## 1.33.3
- Images distantes persistantes : « cette fois » / « toujours pour cette adresse » / « toujours pour le domaine » ; liste modifiable dans Réglages → Filtres et synchronisée entre postes
- Signatures : les logos SVG s'affichent (rédaction, aperçu) ; à l'envoi, signature d'origine conservée et logo envoyé en PNG joint en ligne (lisible par Gmail/Outlook)
- Réglages : sélection des listes bien visible (couleur d'accent, survol)

## 1.33.2
- Correctif de la publication 1.33.1 : import local de « time » retiré d'entry.py (le test de masquage d'imports échouait)

## 1.33.1
- Correctif : MintMail 1.33.0 ne se lançait plus (UnboundLocalError : DATA_DIR) ; nouveau test contre ce type de masquage

## 1.33.0
- Interface Qt : réglages Signatures (aperçu en direct), Identités d'envoi (alias), Modèles de réponse et Contacts (carnet, recherche, import/export .vcf, « Écrire ») ; rédaction : menu « Modèles » et menu ✨ IA (rédiger depuis une idée, améliorer, corriger, raccourcir, développer, ton, traduire, suggérer un objet — sur la sélection ou sur le texte écrit) ; clic droit et palette « Ajouter aux contacts »
- Interface Qt : correctif — changer d'expéditeur dans la rédaction dupliquait la signature (Qt perd les attributs id du HTML) ; la signature et la citation sont maintenant repérées par des marqueurs invisibles, retirés à l'envoi
- macOS : packaging/build-macos.sh et workflow GitHub « Application macOS » construisent un .dmg (non signé par Apple) joint à chaque Release

## 1.32.2
- Interface Qt : plus jamais de plantage silencieux au lancement — les bibliothèques système exigées par Qt (ex. libxcb-cursor0) sont vérifiées avant d'ouvrir la fenêtre ; si elles manquent, MintMail tente de les installer (une fois par jour, mot de passe demandé par la fenêtre du système), sinon il affiche la commande exacte (sudo apt install …) et ouvre l'ancienne interface ; un démarrage Qt qui s'arrête brutalement est détecté au lancement suivant (ancienne interface + indication QT_DEBUG_PLUGINS=1) ; le .deb installe ces bibliothèques d'office ; mintmail --diagnose les contrôle

## 1.32.1
- Correctif interface Qt : la fenêtre principale ne s'ouvrait pas (« QTextBrowser » non importé dans qt/window.py, révélé par les tests chez vous avec le vrai PySide6) ; nouveau test qui détecte tout nom utilisé sans être défini ou importé, même sans PySide6

## 1.32.0
- Interface Qt installée automatiquement : le paquet .deb installe PySide6 dans son venv privé (/usr/lib/mintmail/venv) à l'installation et à chaque mise à jour s'il manque, sans jamais bloquer l'installation en cas d'échec (réseau) ; sans paquet (sources), MintMail installe PySide6 en arrière-plan dans ~/.local/share/mintmail/qt-venv au premier démarrage (une tentative par jour, notification) en gardant l'ancienne interface en attendant, puis s'y relance tout seul ; commande « mintmail --install-qt » pour le faire à la main
- Interface Qt : conversations comme dans la version GTK — un message par fil dans la liste avec le nombre de messages, gras tant qu'un message du fil est non lu, ouvrir un fil marque tous ses messages lus, archiver / supprimer / spam / favori / reporter / geste de balayage valent pour tout le fil ; réglage « Regrouper en conversations » actif

## 1.31.0
- MintMail ouvre désormais l'interface Qt par défaut dès que PySide6 est disponible (système, ou venv ~/mintmail-qt-venv / MINTMAIL_QT_PYTHON où le programme se relance tout seul) ; l'ancienne interface GTK reste en secours : « mintmail --gtk » ou MINTMAIL_UI=gtk, et sert automatiquement si PySide6 est absent ; paquet : PySide6 recommandé ; docs/PARITE.md liste ce qui reste à porter avant de retirer GTK (conversations, Aujourd'hui / agenda, contacts, signatures, modèles, pièces jointes, synchronisation entre postes…)

## 1.30.1
- Mises à jour : « clé de vérification absente » corrigée à la source — le paquet .deb ne supprime plus jamais la clé publique de mises à jour lors d'une installation (elle est mise à l'abri puis remise si le nouveau paquet n'en contient pas) ; MintMail lancé depuis les sources (dépôt cloné, venv) se met à jour avec git (fetch + pull --ff-only) puis propose de relancer, au lieu de s'arrêter sur l'absence de clé
- Interface Qt : icône du programme sur toutes les fenêtres et dans la barre des tâches (X11 et Wayland), logo dans la barre latérale

## 1.30.0
- Interface Qt (expérimentale, mintmail --qt) : recherches enregistrées comme dans la version GTK — « Enregistrer la recherche actuelle » (palette Ctrl+K), section « Recherches » dans la barre latérale (les recherches de la version GTK y apparaissent aussi, elles sont synchronisées), ouverture en un clic, suppression par clic droit ou par la palette

## 1.29.1
- Correctif des tests de relecture des traductions : les catalogues de langue (en, nl, de, es et leurs fichiers d'état) ne se terminent plus par un saut de ligne superflu ; l'export / import à vide de l'outil de relecture ne les modifie plus (le test test_review_tools bloquait la publication depuis la 1.25.0)
- Interface Qt : refonte graphique (cartes arrondies, messages en bulles) et mode sélection multiple (X, cases, barre « n sélectionnés », Ctrl+A, tout marquer comme lu)

## 1.27.0
- Interface Qt (expérimentale, mintmail --qt) : clic droit sur un message comme dans la version GTK — répondre, transférer, archiver, supprimer, lu / non lu, favori, épingle, spam, bloquer ou débloquer l'expéditeur, voir tous ses messages, résumer / traduire / répondre avec l'IA, reporter, déplacer vers un dossier ; il agit sur la sélection
- Interface Qt : palette de commandes (Ctrl+K) — actions sur le message courant, aller à un dossier ou à une vue, déplacer vers un dossier, dispositions, réglages, aide, mises à jour ; un texte sans commande correspondante est confié à l'assistant IA

## 1.26.0
- Interface Qt (expérimentale, mintmail --qt) : dossiers repliables comme dans la version GTK — chevrons pour plier / déplier chaque dossier (état mémorisé), une section par compte quand il y en a plusieurs, compteur de non lus par dossier ; les sous-dossiers ne sont plus tous dépliés
- Interface Qt : gestes de balayage sur la liste des messages (souris ou deux doigts sur le pavé tactile) avec fond coloré et libellé de l'action, glissement court ou long, mêmes actions et seuils que la version GTK ; disposition colonnes / lecture en bas / liste seule (touche « \ », Échap pour revenir à la liste) ; onglet « Gestes & disposition » des réglages (actions, inversion au pavé tactile, conversations)

## 1.25.0
- Interface Qt (expérimentale, mintmail --qt) : carte IA du lecteur comme dans la version GTK — résumé, points clés, tâches, alerte d'hameçonnage, suggestion « Ce n'est pas du spam » (avec rangement), traduction, question sur le message, bouton « ✨ Répondre » qui rédige une réponse à relire ; barre « Réponse rapide » avec réponses toutes faites, envoi immédiat avec la signature du bon compte ou alias, et développement du texte par l'IA
- Interface Qt : connexion IMAP « bad login » corrigée à la source — l'interface Qt tournait dans un venv sans le module « keyring », donc sans accès au mot de passe enregistré dans le trousseau ; MintMail le signale désormais clairement (message dans la barre d'état et dans le terminal, avec la commande d'installation) au lieu de tenter une connexion sans mot de passe, et lit le trousseau en fond dès l'ouverture ; le test des traductions couvre maintenant aussi le paquet Qt
- Interface Qt (expérimentale, mintmail --qt) : aide intégrée (F1 ou bouton « ? ») avec accueil, sections, recherche et astuce du jour, même contenu que la version GTK ; mises à jour comme dans la version GTK — bandeau « MintMail X est disponible » (installer, notes, plus tard), pastille dans la barre latérale, recherche 8 s après chaque démarrage puis toutes les heures, installation avec vérification de la signature, relance de MintMail, onglet « Mises à jour » des réglages

## 1.23.0
- Interface Qt (expérimentale, mintmail --qt) : assistant IA comme dans la version GTK — panneau Ctrl+J avec suggestions, plans d'actions à valider un par un ou d'un coup (archiver, supprimer, spam, ranger, créer un dossier ou une règle, bloquer un expéditeur, reporter, rédiger, résumer la boîte, rechercher), classement des messages par l'IA avec création des dossiers seulement après votre accord ; onglet « IA » des réglages (fournisseur NVIDIA / Ollama / autre, clé dans le trousseau, modèle, test de connexion, confidentialité, langue, ton)

## 1.22.0
- Interface Qt (expérimentale, mintmail --qt) : filtres et blocage comme dans la version GTK — expéditeurs bloqués ou envoyés en spam (adresse ou domaine entier), bouton « Bloquer », « Ce n'est pas du spam » pour tout l'expéditeur, règles automatiques (archiver, supprimer, spam, lu, favori, épingle, ranger dans un dossier) appliquées aux seuls nouveaux messages après chaque synchronisation, onglet « Filtres & blocage » des paramètres avec « Appliquer maintenant »

## 1.21.0
- Interface Qt (expérimentale, mintmail --qt) : refonte graphique aux couleurs de MintMail (styles Aurora, Papier et Terminal, clair ou sombre, couleur d'accent, densité de liste) avec pastilles d'initiales, barre latérale à compteurs et lecteur à en-tête ; fenêtre Paramètres (Ctrl+,) pour ajouter, tester, modifier et supprimer des comptes (mot de passe ou connexion Google / Microsoft) et régler l'apparence ; bannière du mode démonstration ; test de synchronisation rendu indépendant de l'ordre de démarrage des deux machines (échec aléatoire à la publication)

## 1.20.1
- Correctif de démarrage : MintMail ne plante plus (« _nav_initial ») quand la dernière vue ouverte est Envoyés, Archives ou un dossier ; la barre latérale la retrouve toute seule

## 1.20.0
- Interface Qt (expérimentale, mintmail --qt) : rédaction complète (nouveau message, répondre, répondre à tous, transférer, brouillons, alias et signatures, pièces jointes, Cc/Cci, envoi différé, annulation de l'envoi) avec boîte d'envoi qui renvoie hors ligne, reporter au lendemain, raccourcis C R A F H J K et /

## 1.19.0
- Interface Qt (expérimentale, mintmail --qt) : dossiers de rangement dans la barre latérale, archiver, supprimer, spam et « ce n'est pas du spam », favori, épingle, non lu, déplacer vers un dossier (raccourcis E, Suppr, !, S, P, U, V), vue « Non lus » qui garde le message ouvert jusqu'à ce qu'on passe à un autre ; actions enregistrées d'abord et rejouées hors ligne

## 1.18.0
- Interface Qt (expérimentale) : « mintmail --qt » ouvre une fenêtre PySide6 avec dossiers, liste des messages et lecteur (HTML assaini, JavaScript coupé, liens filtrés), synchronisation en arrière-plan et message marqué lu sur le serveur ; l'interface habituelle ne change pas, et la CI teste aussi la fenêtre Qt sur Linux, Windows et macOS

## 1.17.0
- Préparation du portage Windows et macOS (interface Qt) : le moteur (courrier, synchro, IA, règles) est isolé de l'interface Linux et vérifié par des tests, les dossiers et notifications passent par une couche système, et une intégration continue teste le moteur sur Linux, Windows et macOS ; rien ne change à l'usage sous Linux

## 1.16.1
- Vue « Non lus » : le message que vous ouvrez y reste affiché (liste et lecteur) tant que vous ne passez pas à un autre ; il n'en sort qu'à ce moment-là, ou si vous agissez dessus (archiver, supprimer…), au lieu de disparaître dès son ouverture

## 1.16.0
- Vue « Non lus » : elle réunit maintenant les messages non lus de la boîte de réception ET de tous vos dossiers de rangement et archives (règles, IA, rangement manuel), sauf Spam, Corbeille, Envoyés et Brouillons ; le badge compte tout. MintMail relit ces dossiers en arrière-plan (environ chaque minute) sans télécharger ce qui est déjà lu, et notifie les non lus récents qui y arrivent
- Sécurité du déplacement côté serveur : une copie ou un déplacement refusé par le serveur est maintenant une erreur franche et ne supprime plus jamais le message d'origine (avant, le refus n'était pas lu) ; l'effacement ne touche que les messages visés (UID EXPUNGE) et plus tout le dossier
- Un dossier où l'on vient de ranger des messages (ex. LTD) est resynchronisé sans attendre : la demande faite pendant une autre synchronisation est conservée et rejouée

## 1.15.1
- Correction : « ranger tous les messages de X dans le dossier Y » créait le dossier mais ne déplaçait rien quand « créer le dossier » et « déplacer » étaient validés d'un coup (double création refusée par le serveur, déplacement abandonné sans message) ; la création est désormais unique, tolère « existe déjà », et le dossier sert immédiatement
- Réplication entre postes : la liste des dossiers est relue toutes les minutes environ (elle ne l'était qu'au démarrage) et aussitôt après un changement signalé par le serveur ; la boîte de réception est resynchronisée chaque minute (épingles, lu, favoris posés sur un autre poste)
- Temps réel : l'écoute IDLE réagit maintenant aussi aux changements de drapeaux faits depuis un autre poste (épingle, lu, favori), pas seulement aux arrivées et départs de messages

## 1.15.0
- Nouveau « Ce n'est pas du spam » (dossier Spam) : bouton « ✔ Pas du spam » dans le lecteur, menus ⋯ / clic droit / Spam ▾ / palette Ctrl+K — le message ET tous ceux du même expéditeur (variante : tout le domaine) retournent en boîte de réception, avec Annuler
- Propagation au serveur : marqueur $Junk retiré et $NotJunk posé, puis sortie du dossier Spam (sur Gmail, le message perd l'étiquette Spam) ; conservé hors ligne et envoyé au retour du réseau ; l'expéditeur sort de la liste « envoyés en spam »
- L'IA le suggère : dans le dossier Spam, un message jugé légitime reçoit « Ce n'est pas du spam » et « Pas du spam, ranger dans … » (carte de résumé et clic droit) ; l'assistant comprend « ce n'est pas du spam » ; aide FR/EN et traductions nl/de/es

## 1.14.2
- Page Paramètres → Mises à jour : bouton « Relancer maintenant » après l'installation (comme sur le bandeau) ; l'état affiche « installé » tant que l'ancienne version tourne encore
- Recherche de mise à jour toutes les heures (et à chaque démarrage) au lieu de toutes les 6 heures

## 1.14.1
- Épingles sur Gmail : étiquette « MintMail-Epingles » (visible dans Gmail, web et mobile) et vue par vos autres postes ; autres serveurs IMAP : mot-clé IMAP ; l'étiquette technique est masquée dans la liste de dossiers
- Nouvelle commande « mintmail --check-pins » : verdict réel du serveur pour chaque compte (connexion, nombre de messages épinglés, essai réversible sur le message le plus récent ; --no-test = lecture seule)

## 1.14.0
- Aide intégrée entièrement refondue : page d'accueil (démarrage en 4 étapes, astuce du jour, cartes vers chaque section), navigation avec icônes, sections illustrées avec accroche, touches de clavier, noms d'écrans en gras, encadrés d'astuces, commandes en blocs, raccourcis en tableau de touches
- Recherche dans l'aide : résultats en cartes, extrait surligné et bouton « Ouvrir la section »
- Style de l'aide adapté aux trois styles (Aurora, Papier, Terminal), en clair comme en sombre

## 1.13.3
- Épingles enregistrées SUR LA BOÎTE (mot-clé IMAP) : visibles sur vos autres postes ; vérification au premier essai et avertissement pour les serveurs qui refusent (Gmail, Outlook.com) ; anciennes épingles envoyées une fois ; commande « Envoyer mes épingles vers la boîte »
- Script de mise à jour du dépôt depuis un correctif (tools/mintmail-maj.sh) : ignore les fichiers non suivis, n'enregistre que ce que le correctif touche, choisit la version la plus haute ; la publication n'est plus bloquée par des fichiers à la racine du dépôt
- Recherche de mise à jour à CHAQUE démarrage (même si une vérification date de moins de 24 h) puis toutes les 6 heures : une version publiée entre-temps est annoncée tout de suite par le bandeau
- Diagnostic : mintmail --check-update indique si une mise à jour est mémorisée pour le bandeau ou repoussée

## 1.13.1
- Mise à jour déjà installée : le bandeau propose « Relancer maintenant » ; notification de bureau ; dernier résultat dans Paramètres → Mises à jour ; commande mintmail --check-update
- Option « Ouvrir la page Aujourd'hui au lancement » (Paramètres → Apparence)
- Clé de signature : sauvegarde contrôlée (tools/backup-signing-key.sh), rotation sans réinstallation (tools/rotate-signing-key.sh, release.sh --rotation), guide docs/KEY-RECOVERY.md
- Relecture des traductions par un locuteur : tools/review_translations.py (export / import CSV validé)

## 1.13.0
- Bandeau de mise à jour visible dès le lancement (installer maintenant, plus tard, notes de version, progression, relance) et pastille dans la barre latérale

## 1.12.2
- Essai de la mise à jour automatique depuis l'application

## 1.12.1
- Correctif des tests : ils n'utilisent plus jamais le trousseau, le dossier personnel ni les réglages réels (sur une machine avec trousseau, la batterie écrasait la clé d'API enregistrée) ; la variable MINTMAIL_NO_KEYRING=1 désactive l'accès au trousseau
- Test de synchronisation plus robuste (attend la fin de l'échange et affiche les valeurs reçues en cas d'échec)

## 1.12.0
- Nouvelles langues de l'interface : néerlandais, allemand et espagnol (traduction par IA, non relue par des locuteurs natifs : signalez les défauts) ; l'aide intégrée (F1) retombe sur l'anglais pour ces langues

## 1.11.0
- Mises à jour automatiques depuis GitHub (Paramètres → Mises à jour) : recherche une fois par jour (désactivable), annonce, installation en un clic ; chaque paquet doit porter une signature RSA vérifiée avec une clé publique intégrée au programme, retour en arrière refusé, mot de passe administrateur demandé (polkit)
- Dépôt versionné : numéro de version unique contrôlé, tools/bump-version.sh, tools/make-signing-key.sh, tools/release.sh (publie une Release signée), docs/UPDATES.md et docs/RELEASING.md
- Traduction : l'interface (≈ 1 000 textes), l'aide intégrée (F1) et la ligne de commande existent en français et en ANGLAIS ; choix dans Paramètres → Apparence → « Langue de l'interface » (Automatique = langue du système ; redémarrage nécessaire)
- Moteur de traduction à catalogues JSON (mintmail/locale/) : le français reste la langue source, sans aucun changement de comportement
- Outils : tools/i18n_wrap.py (enveloppe les nouveaux textes), tools/translate_catalog.py (pré-traduction d'autres langues par un service d'IA, avec validation automatique), tests de couverture exacte
- Détection du mode hors ligne indépendante de la langue des messages ; libellé de synchronisation compact sans découpage de texte traduit

## 1.10.2
- Audit de sécurité (voir SECURITY.md) : nettoyeur HTML à liste blanche + politique de sécurité de contenu (lecteur et rédaction), navigation et liens filtrés (http / https / mailto), WebKit durci, pièces jointes dangereuses bloquées ou confirmées
- Données au repos : dossiers 0700 et fichiers 0600 dès la création (courrier, pièces jointes, journal, réglages)
- Lanceur en mode isolé (-I) : plus de détournement par le dossier courant
- Synchronisation : connexions limitées au réseau local, délai total, ports et tables bornés, code de jumelage faible refusé, nouveau générateur de code
- Désabonnement : plus de requête vers le réseau interne, une seule adresse mailto valide ; noms de dossiers IMAP sans caractères de contrôle

## 1.10.1
- Licence MIT (logiciel libre) ; mention dans « À propos » et dans l'aide

## 1.10.0
- Page Aujourd'hui (T), tâches avec échéances en français (synchronisées), proposition de créneaux d'après Google Agenda, brouillons de réponse préparés (optionnels)

## 1.9.2
- Correctif : le clic droit visait toujours le premier message de la liste (coordonnées relatives à la carte) ; ligne retrouvée via le widget cliqué (liste, mode sélection, dossiers)

## 1.9.1
- Assistant guidé de création de l'identifiant OAuth (liens exacts), identifiants préinstallables (/etc/mintmail/oauth-clients.json), aide mise à jour

## 1.9.0
- Google Agenda : ajout sans doublon des invitations et rendez-vous IA, agenda des 14 jours, nouvel événement, alerte de conflit ; autorisation « calendar.events » ajoutée séparément à celle de Gmail
- Aide mise à jour (Google Agenda, expiration à 7 jours du jeton en mode Test)

## 1.8.1
- Aide intégrée complète et consultable (F1, recherche instantanée) ; mintmail --help ; AIDE.txt installé ; tests d'alignement aide / code

## 1.8.0
- Suppression de la barre d'actions au survol des messages
- Conversations, recherche sur le serveur, OAuth Google/Microsoft, IA locale (Ollama), apprentissage des rangements
- Pièces jointes (aperçu, tout enregistrer, glisser-déposer), mode hors ligne, contacts, invitations, CalDAV, identités d'envoi
- Envoi programmé fenêtre fermée (--send-due + minuterie systemd utilisateur), désabonnement en un clic

## 1.7.0
- IA : classement des emails avec validation, création de dossiers, actions « classer » et « créer un dossier » pour l'assistant, règles « ranger dans un dossier »
- Clic droit : section ✨ IA (ranger, classer, répondre selon l'intention, résumer, traduire, agenda, assistant)
- Résumé : barre d'options supprimée ; affichage du texte du résumé corrigé
- Icône de l'application (SVG + PNG), association fenêtre / lanceur (me.saec.mintmail, classe mintmail)
- Synchro : découverte réseau fiabilisée (toutes les interfaces, VPN, identifiants dupliqués, recherche active, diagnostic)

## 1.6.6
- --remove-local-install : liste d'abord (versions comprises), met de côté avec --yes au lieu de supprimer, ne touche jamais /usr/local ni /opt
- --diagnose : version de chaque lanceur du PATH, sans les exécuter

## 1.6.5
- Nettoyage de l'ancienne installation locale : commande à lancer avec le chemin complet (/usr/bin/mintmail --remove-local-install)

## 1.6.4
- Lanceur : /usr/bin/python3 explicite (Python de conda / pyenv / venv sans PyGObject)
- --diagnose (rapport sans secrets), --reset (mise de côté des données), démarrage protégé avec boîte de dialogue, message clair sans GTK

## 1.6.3
- Paquet .deb avec epoch (1:1.6.3) : remplace toute version précédemment installée, même de numéro plus élevé

## 1.6.2
- Barre d'actions des messages et barre du lecteur : boutons directs Spam ▾ / Bloquer ▾ (message, adresse ou domaine entier, débloquer) et menu ⋯ ; touche B

## 1.6.1
- Correctif : la barre d'actions au survol d'un message clignotait et n'était pas utilisable (masquage différé, boutons surveillés)
- Livraison sous forme de paquet .deb ; option --remove-local-install pour retirer l'ancienne installation locale

## 1.6.0
- Synchro entre machines entièrement automatique : comptes + mots de passe, signatures, IA (clé comprise), modèles de réponse rapide, règles, blocages, recherches, apparence ; ajouts, modifications et suppressions
- Canal chiffré + authentifié (code de jumelage ≥ 12 caractères), détection continue des modifications locales, échange toutes les 30 s et à chaque changement, voyant dans la barre latérale
- Correctif : un compte ajouté sur un poste n'arrivait jamais sur les autres (les comptes n'étaient volontairement pas échangés depuis la 1.3.0)

## 1.5.0
- Dossiers : arborescence IMAP complète par compte (hiérarchie, mUTF-7, non lus par dossier), navigation, anciens messages, déplacer vers un dossier (menu, touche V, palette, IA), création / renommage / suppression
- Design : trois styles (Aurora, Papier, Terminal) clair/sombre, pastilles de comptes, rail de priorité, barre d'outils flottante, filet aurore ; migration automatique vers Aurora sombre à la première ouverture

## 1.4.0
- IA omniprésente : assistant conversationnel à actions confirmées, carte d'analyse par message, tri et résumés dans la liste, bloc « En bref », rédaction assistée, recherche en langage naturel, agenda (.ics), traduction
- Performance : cache allégé (méta sans corps), mises à jour par colonnes en une transaction, liste incrémentale, pagination, connexions IMAP persistantes, lots progressifs, IMAP IDLE
- Un clic ouvre un message (sélection simple) ; multi-sélection à la demande
- Boutons réduire / agrandir / fermer garantis ; plein écran F11
- Design : cartes, actions au survol, thème IA, couleurs prédéfinies, bouton Assistant

## 1.3.0
- Correctif : plantage au démarrage (`httpx` absent) et NameError à l'initialisation de la fenêtre
- Correctif : page des paramètres inutilisable (NameError dans la page de synchro, set_border_width sur Gtk.Label)
- Paramètres : ouverture robuste (repli fenêtre séparée), journal d'erreurs, `--diagnose`, `--settings`
- IA NVIDIA : service réécrit (urllib), endpoint/modèle corrects, erreurs explicites, threads, clé dans le trousseau
- Synchro P2P : réécrite, désactivée par défaut, code de jumelage + HMAC, aucun identifiant échangé, validation des données
- Installeur : `--full-reset` corrigé ; trousseau non bloquant ; enregistrement de la config thread-safe

## 1.2.0
- Page des paramètres intégrée à la fenêtre, accessible via ⚙, Ctrl+, , menu, barre latérale et palette
- Refonte visuelle proche de Spark Mail (cartes, avatars, pastilles, boutons ronds, en-tête épuré)
- Bleu d'accent par défaut mis à jour ; CSS avec repli automatique si le thème GTK refuse les effets

## 1.1.0
- Volets redimensionnables (poignées larges, positions mémorisées), dispositions colonnes / lecture en bas / liste seule
- Interface responsive : barre latérale étendue / réduite / masquée, barres défilantes, mode une colonne
- Gestes de swipe configurables (souris, pavé tactile, tactile)
- Spam d'expéditeur / de domaine, blocage, liste de blocage, règles automatiques
- Recherches enregistrées, rappels sans réponse, modèles de réponse, zoom du lecteur
- Déplacements groupés IMAP (une seule connexion)
- Paramètres : validations, fenêtre unique, remise à zéro, vidage du cache, pages défilantes

## 1.0.0
- Première version
