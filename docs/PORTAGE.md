# Portage Windows et macOS (interface Qt)

Objectif : MintMail sur Linux, Windows et macOS, avec une seule interface (Qt / PySide6) à terme et le même moteur partout.

## Architecture

| Couche | Modules | Dépend de |
|---|---|---|
| **Moteur** (portable) | `models util i18n log netutil htmlsafe ical caldav gcal contacts tasks slots unsub store offline backend ai_service ai_engine oauth syncdata p2p updater update_text help_format style` | Python, SQLite, `keyring` (facultatif) |
| **Couche système** | `sysdeps` | dossiers de données, notifications, ouverture de fichiers : un seul endroit par système |
| **Interface** (à remplacer par Qt) | `window listing reader folders settings* compose extras widgets assistant updates_ui help_view ai_features app` | GTK3 + WebKit2 (Linux seulement) |
| **Linux seulement** | `apply_update` (polkit), unités systemd, paquet `.deb`, `diagnose` | |

Garde-fou : `tests/test_core_portable.py` échoue si un module du moteur importe GTK ou Qt, et si un nouveau module n'est pas classé (moteur ou interface).
La CI (`.github/workflows/portable.yml`) exécute `tests/run_core.py` sur Ubuntu, Windows et macOS.

## Étapes

1. **Moteur isolé, couche système, CI trois systèmes** — fait (1.17.0). Rien ne change pour l'utilisateur Linux.
2. **Socle Qt** — fait (1.18.0) : `mintmail --qt` ouvre la fenêtre PySide6 (dossiers, liste, lecteur QtWebEngine sans JavaScript, synchronisation en fond, message marqué lu sur le serveur). Reste à vérifier sur de vraies machines. Prévu à l'origine : fenêtre à trois volets (dossiers, liste, lecteur), liste avec modèle/vue, lecteur HTML (QtWebEngine), synchronisation branchée sur le moteur.
3. **Fonctions** — en cours : dossiers de rangement, archiver / supprimer / spam / « pas du spam », favori, épingle, non lu, déplacer vers un dossier, vue « Non lus » qui garde le message ouvert (1.19.0) ; rédaction (nouveau, répondre, répondre à tous, transférer, brouillons, alias et signatures, pièces jointes, envoi différé, annuler l'envoi) et boîte d'envoi (1.20.0) ; refonte graphique (thèmes Aurora / Papier / Terminal, clair / sombre, accent, densité) et paramètres : comptes IMAP/SMTP, Gmail et Microsoft en OAuth, apparence, messagerie (1.21.0). Reste :  rédaction, paramètres, assistant IA, aide, bandeau de mise à jour, rangement, règles, « Non lus », épingles. Filtres (1.22.0) : `qt/automation.py` — expéditeurs bloqués ou envoyés en spam, « pas du spam » pour tout l'expéditeur, règles automatiques appliquées aux seuls nouveaux messages après chaque synchronisation, « Appliquer maintenant », onglet « Filtres & blocage » des paramètres, bouton « Bloquer ». Assistant IA (1.23.0) : `qt/assistant.py` + panneau Ctrl+J — plans d'actions validés un par un ou d'un coup (archiver, ranger, créer dossier/règle, bloquer, reporter, rédiger, résumer), classement par l'IA avec création de dossiers après accord, onglet « IA » des réglages. Carte IA du lecteur (1.24.0) : `qt/readerai.py` — résumé, points, tâches, alerte d'hameçonnage, suggestion « pas du spam », traduction, question, réponse rédigée par l'IA, barre « Réponse rapide » avec signature. Aide F1 et mises à jour (1.25.0) : `qt/helpdoc.py` (même contenu que GTK, recherche, astuce du jour) et `qt/updating.py` (bandeau, pastille, recherche au démarrage puis chaque heure, installation signée) ; l'installation automatique reste réservée au paquet .deb, Windows et macOS auront leur propre mise à jour à l'étape 4. Dossiers repliables et gestes (1.26.0) : `qt/navtree.py` (arbre comme dans la version GTK : chevrons, état mémorisé, sections par compte, compteurs de non lus par dossier) et `qt/gestures.py` + `MessageList` (balayage souris / pavé tactile, mêmes seuils et actions), disposition colonnes / bas / liste seule (touche `\\`, Échap pour revenir), onglet « Gestes & disposition ». Clic droit et palette (1.27.0) : `qt/menus.py` (entrées du menu contextuel selon l'état du message, commandes de la palette Ctrl+K avec recherche par mots, texte libre confié à l'assistant) et `qt/ui_palette.py`. Sélection multiple (1.29.0) : mode « ☑ » / touche X, cases rondes, barre « n sélectionnés », Ctrl+A, « Tout marquer comme lu » ; les boutons d'action agissent sur toute la sélection. Recherches enregistrées (1.30.0) : `qt/savedsearch.py` — section « Recherches » de la barre latérale, enregistrer la recherche actuelle (palette), suppression par clic droit, mêmes données que GTK (synchronisées). Restent : jour/agenda, contacts, signatures/identités, modèles, sync P2P, recherches enregistrées, palette.
4. **Emballage et mises à jour par système** : Windows (PyInstaller + installeur signé), macOS (`.app` + `.dmg` signé et notarisé, compte Apple Developer), Linux (`.deb` inchangé). L'installation automatique des mises à jour est aujourd'hui propre à Linux (polkit) : sur les autres systèmes, MintMail annonce la version et ouvre la page de téléchargement.
5. **Bascule** : quand l'interface Qt égale l'interface GTK, GTK est retiré.

## Limites connues

- Le code Qt ne peut pas être exécuté dans l'environnement où MintMail est développé (pas de PySide6, pas de Windows ni de macOS) : la CI et vos essais sur de vrais postes sont le seul contrôle réel. Attendre des retours de rendu à chaque étape.
- Les notifications Windows et macOS (`sysdeps.notify`) ne sont pas encore éprouvées sur de vraies machines.
- Les droits de fichiers 0600/0700 n'ont pas d'équivalent exact sous Windows : les données sont protégées par le profil de l'utilisateur.
