# Parité Qt / GTK — avant de retirer l'ancienne interface

Depuis la 1.31.0, MintMail ouvre l'interface **Qt** par défaut (dès que PySide6 est installé) ; l'ancienne interface GTK reste en secours
(`mintmail --gtk` ou `MINTMAIL_UI=gtk`). Le code GTK sera retiré quand la liste « à porter » ci-dessous sera vide.

## Déjà dans Qt
Dossiers repliables et sections par compte · liste en bulles, densités, dispositions (colonnes / bas / liste seule) · gestes de balayage ·
sélection multiple · clic droit · palette Ctrl+K · recherches enregistrées · rédaction, boîte d'envoi, annulation d'envoi, brouillons, alias ·
paramètres (comptes IMAP/SMTP, Gmail et Microsoft OAuth, apparence, filtres et blocage, règles, IA, mises à jour, gestes) ·
assistant IA (Ctrl+J) et carte IA du lecteur, réponse rapide · aide F1 · bandeau et installation des mises à jour · icône ·
signatures HTML, identités d'envoi, modèles de réponse (menu « Modèles ») et aide IA à l'écriture ✨ dans la rédaction · contacts (carnet, import/export .vcf,
complétion, « Ajouter aux contacts ») · images distantes persistantes par expéditeur · logos SVG de signature · conversations · vérification des bibliothèques système (jamais de plantage silencieux).

## Porté en 1.34.0 (code écrit, à valider à l'écran)
Aujourd'hui (agenda, priorités, tâches, relances) · Google Agenda / CalDAV, invitations (.ics), créneaux proposés · pièces jointes (puces, aperçu, enregistrement) et
désabonnement · synchronisation chiffrée entre postes (réglages et état) · barre latérale réduite, zoom, indicateur hors ligne, notifications · catégories ·
autres messages du fil dans le lecteur · IA partout : tri automatique avec pastilles « Important » / « Suspect » et résumé dans la liste, « En bref », brouillons préparés,
recherche en langage naturel (« ? … »), clic droit IA complet, notification des messages importants.

## À porter (GTK seulement)
Rien de connu. Reste : une période d'essai de l'interface Qt par l'utilisateur (le rendu n'a jamais pu être vérifié sans écran), puis retrait de GTK.

## Retrait de GTK (une fois la liste vide)
Fichiers propres à GTK : `app.py`, `window.py`, `listing.py`, `folders.py`, `widgets.py`, `reader.py`, `compose.py`, `settings*.py`, `help_view.py`,
`updates_ui.py`, `extras.py`, `style.py` (partie GTK), `assistant.py` (panneau), `tests/gtkstub.py`. Le moteur (backend, store, offline, ai_*, syncdata, p2p…)
est partagé et reste. Dépendances du paquet : retirer `python3-gi`, `gir1.2-*`, ajouter `python3-pyside6.*`.

## macOS
`packaging/build-macos.sh` (sur un Mac) et le workflow `.github/workflows/macos.yml` construisent `MintMail-<version>-macos.dmg` (PyInstaller + PySide6). Non signé par Apple :
clic droit → Ouvrir au premier lancement. La mise à jour automatique reste propre à Linux (.deb) ; sur Mac la nouvelle version est annoncée, à télécharger.
À faire : signature + notarisation (compte Apple Developer), Windows (.msi).
