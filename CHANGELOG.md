# Changelog

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
