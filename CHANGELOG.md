# Changelog

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
