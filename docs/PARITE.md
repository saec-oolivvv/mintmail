# Parité Qt / GTK — historique

Depuis la **1.35.0**, l'interface GTK n'existe plus : MintMail a une seule interface, **Qt** (PySide6), identique sur Linux, macOS et (à venir) Windows.
L'option `--gtk` est ignorée.

## Contrôle avant le retrait
Les réglages et les textes de l'ancienne interface ont été comparés un par un à ceux de Qt. Fonctions qui manquaient encore et ont été portées en 1.35.0 :
gestion des dossiers (nouveau, sous-dossier, renommer, supprimer — clic droit dans la barre latérale), envoi des épingles vers la boîte, recherche « aussi sur le serveur »,
journal d'erreurs, plein écran (F11), « Copier l'adresse », choix de la langue de l'interface, ouverture de « Aujourd'hui » au lancement, barre de mise en forme complète
de la rédaction (barré, liste numérotée, citation, effacer la mise en forme, liens tel:).

## Fichiers retirés
`app.py`, `window.py`, `listing.py`, `folders.py`, `widgets.py`, `reader.py`, `compose.py`, `settings*.py`, `help_view.py`, `updates_ui.py`, `extras.py`, `style.py`,
`assistant.py` (panneau GTK), `ai_features.py`, `tests/gtkstub.py`. Les couleurs et styles (Aurora, Papier, Terminal) vivent dans `themes.py`.
Les tests qui pilotaient la fenêtre GTK ont été retirés ; leurs équivalents Qt sont dans `tests/test_qt_viewmodel.py`, `tests/test_organizer_ai.py` et `tests/test_qt_window.py` (ce dernier exige PySide6).

## macOS
`packaging/build-macos.sh` (sur un Mac) construit `MintMail-<version>-macos.dmg` (PyInstaller + PySide6) ; `packaging/mac-essai.command` lance MintMail sur un Mac sans rien installer de définitif.
Non signé par Apple : clic droit → Ouvrir au premier lancement. La mise à jour automatique reste propre à Linux (.deb) ; sur Mac la nouvelle version est annoncée, à télécharger.
À faire : signature + notarisation (compte Apple Developer), Windows (.msi).
