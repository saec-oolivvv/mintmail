# Parité Qt / GTK — avant de retirer l'ancienne interface

Depuis la 1.31.0, MintMail ouvre l'interface **Qt** par défaut (dès que PySide6 est installé) ; l'ancienne interface GTK reste en secours
(`mintmail --gtk` ou `MINTMAIL_UI=gtk`). Le code GTK sera retiré quand la liste « à porter » ci-dessous sera vide.

## Déjà dans Qt
Dossiers repliables et sections par compte · liste en bulles, densités, dispositions (colonnes / bas / liste seule) · gestes de balayage ·
sélection multiple · clic droit · palette Ctrl+K · recherches enregistrées · rédaction, boîte d'envoi, annulation d'envoi, brouillons, alias ·
paramètres (comptes IMAP/SMTP, Gmail et Microsoft OAuth, apparence, filtres et blocage, règles, IA, mises à jour, gestes) ·
assistant IA (Ctrl+J) et carte IA du lecteur, réponse rapide · aide F1 · bandeau et installation des mises à jour · icône.

## À porter (GTK seulement)
1. Conversations (regroupement par fil, compteur, déploiement)
2. Aujourd'hui : agenda, priorités, tâches avec échéances, relances (« Me rappeler si pas de réponse »)
3. Google Agenda / CalDAV : événements, créneaux proposés, invitations (.ics)
4. Contacts : carnet, complétion, « Ajouter aux contacts »
5. Identités d'envoi et signatures HTML (éditeur dans les réglages)
6. Modèles de réponse, aide à l'écriture ✨ dans la rédaction
7. Pièces jointes : puces, aperçu, enregistrement ; désabonnement en un clic
8. Synchronisation chiffrée entre postes (P2P) : réglages et état
9. Barre latérale réduite (rail), zoom, mode hors ligne (indicateur), notifications de bureau
10. « Voir tous ses messages », catégories (pastilles)

## Retrait de GTK (une fois la liste vide)
Fichiers propres à GTK : `app.py`, `window.py`, `listing.py`, `folders.py`, `widgets.py`, `reader.py`, `compose.py`, `settings*.py`, `help_view.py`,
`updates_ui.py`, `extras.py`, `style.py` (partie GTK), `assistant.py` (panneau), `tests/gtkstub.py`. Le moteur (backend, store, offline, ai_*, syncdata, p2p…)
est partagé et reste. Dépendances du paquet : retirer `python3-gi`, `gir1.2-*`, ajouter `python3-pyside6.*`.
