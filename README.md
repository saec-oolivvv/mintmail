# MintMail

**Client de messagerie moderne pour Linux Mint (et Ubuntu / Debian) — GTK3, Python — avec une IA qui lit, trie, classe, résume, rédige et agit avec vous, toujours avec votre accord.**

*Modern GTK3 mail client for Linux Mint / Ubuntu / Debian with built-in AI: summaries, folder sorting, smart replies, Google Calendar, offline mode, encrypted sync between your machines. Interface in French and English (see [Langues](#langues--languages)).*

## Télécharger / Download

- **Paquet `.deb`** : onglet **Releases** de ce dépôt → `mintmail_X.Y.Z_all.deb`, puis :
  ```
  sudo apt install ./mintmail_X.Y.Z_all.deb
  ```
  Les dépendances (Python 3, GTK 3, WebKit2GTK) sont installées automatiquement. Mise à jour = réinstaller le `.deb` de la nouvelle version ; vos réglages et votre cache sont conservés.
- **Code source** : bouton **Code → Download ZIP**, ou `git clone`.
- **Construire soi-même** : `make deb` (nécessite `dpkg-deb` et `python3`) → `dist/mintmail_<version>_all.deb`.

Prérequis : Linux Mint 21+ / Ubuntu 22.04+ / Debian 12+ (Python ≥ 3.9). Compte e-mail IMAP/SMTP (Gmail, Outlook, OVH, Infomaniak…).

## Fonctions

- **Courrier** : multi-comptes, tous les dossiers IMAP (arborescence, créer / renommer / déplacer), conversations, recherche instantanée (+ recherche sur le serveur), pièces jointes (aperçu, tout enregistrer, glisser-déposer), signatures HTML, alias d'envoi, modèles, envoi annulable ou programmé (même fenêtre fermée), réception en temps réel (IMAP IDLE), mode hors ligne (actions rejouées, envois jamais perdus).
- **IA** (désactivée par défaut, fournisseur au choix : NVIDIA, **Ollama local**, ou tout service compatible OpenAI) : résumé de chaque message, tri par priorité, alerte d'hameçonnage, **classement dans des dossiers avec validation**, assistant capable d'agir (plan d'actions confirmé), recherche en langage naturel, aide à l'écriture, brouillons de réponse préparés (optionnels), apprentissage de vos habitudes de rangement.
- **Productivité** : page « Aujourd'hui » (touche `T`), tâches avec échéance lue en français, proposition de créneaux libres, invitations (accepter / refuser en un clic), contacts (vCard), **Google Agenda** (ajout sans doublon, alerte de conflit) ou CalDAV.
- **Contrôle** : spam / blocage par adresse ou domaine, règles automatiques, désabonnement en un clic (RFC 8058), images distantes bloquées, connexion **OAuth** Google / Microsoft sans mot de passe.
- **Synchronisation entre vos machines** sans serveur : comptes, signatures, règles, contacts, tâches… chiffrée et authentifiée.
- **Interface** : 3 styles (Aurora, Papier, Terminal), gestes de balayage, palette de commandes (`Ctrl+K`), raccourcis clavier, menu clic droit complet, **aide intégrée complète** (`F1`, recherche instantanée).

## Premiers pas

1. Lancer **MintMail** depuis le menu, ou `mintmail`. Sans compte, un mode démonstration s'affiche.
2. Paramètres (`Ctrl+,`) → Comptes → ajouter votre compte (mot de passe d'application pour Gmail / Yahoo / iCloud, ou connexion OAuth).
3. `F1` ouvre l'aide complète. Le texte est aussi disponible ici : [docs/AIDE.md](docs/AIDE.md).

**Connexion Google / Microsoft (OAuth)** : MintMail ne peut pas fournir d'identifiant commun ; un assistant intégré guide la création de **votre** identifiant (une seule fois, 4 étapes). Voir l'aide, rubrique « Connexion Google / Microsoft ». Les identifiants peuvent être préinstallés pour un parc de machines : `data/oauth-clients.json.example`.

## Captures d'écran

Les captures seront ajoutées dans [`docs/screenshots/`](docs/screenshots/README.md) (liste des 12 écrans et script de capture fournis). *Aucune image n'est incluse pour l'instant.*

## Langues / Languages

L'interface existe en **français, anglais, néerlandais, allemand et espagnol** : Paramètres → Apparence → « Langue de l'interface » (Automatique = langue du système ; redémarrage nécessaire).
L'aide (F1) et la ligne de commande existent en français et en anglais (anglais pour les autres langues). **Néerlandais, allemand et espagnol : traductions par IA, non relues par des locuteurs natifs** — signalez les
défauts. D'autres langues peuvent être pré-traduites avec `tools/translate_catalog.py`. Détails et limites : [docs/I18N.md](docs/I18N.md).

*The interface is available in **French, English, Dutch, German and Spanish** (Settings → Appearance → “Interface language”; Automatic = system language; restart required). Help (F1) and the command line are in French
and English (English for the other languages). **Dutch, German and Spanish are AI translations not reviewed by native speakers** — please report defects. See docs/I18N.md.*

## Mises à jour

Paramètres → **Mises à jour** : MintMail cherche une nouvelle version sur GitHub (une fois par jour, requête anonyme, désactivable) et l'installe en un clic après vérification d'une **signature** et avec votre
mot de passe administrateur. Fonctionnement, sécurité et mise en route : [docs/UPDATES.md](docs/UPDATES.md). Publier une version : [docs/RELEASING.md](docs/RELEASING.md) (`tools/release.sh`).

## Sécurité

Un audit de sécurité complet (failles trouvées et corrigées, risques restants, méthode et limites) est dans [SECURITY.md](SECURITY.md), avec la procédure pour signaler une faille.

## Développement

```
make test    # tous les tests (GTK simulé) + test de fumée
make deb     # construit dist/mintmail_<version>_all.deb
make docs    # régénère docs/AIDE.md et docs/HELP.md depuis l'aide intégrée
tools/bump-version.sh X.Y.Z   # nouvelle version (VERSION + CHANGELOG)
tools/release.sh              # publie une version signée (voir docs/RELEASING.md)
```

- `mintmail/` : application (`window.py` fenêtre, `listing.py` liste, `reader.py` lecteur, `compose.py` rédaction, `backend.py` IMAP/SMTP, `store.py` cache SQLite + réglages, `ai_*.py` IA, `syncdata.py` + `p2p.py` synchronisation, `oauth.py` / `gcal.py` / `caldav.py`, `help_content.py` aide…).
- `tests/` : tests automatisés ; l'interface GTK est **simulée** (doublures) — voir « État du projet ».
- `packaging/build-deb.sh` : construction du paquet ; `.github/workflows/` : tests (CI) et publication automatique du `.deb` à chaque étiquette `vX.Y.Z`.
- Historique des versions : [CHANGELOG.md](CHANGELOG.md) et [docs/NOUVEAUTES.md](docs/NOUVEAUTES.md). *Les commits antérieurs à v1.10.0 sont des instantanés reconstitués à partir des livraisons successives.*

## État du projet

Les tests couvrent la logique (stockage, IMAP/SMTP simulés, IA simulée, synchronisation, OAuth, agenda, aide…), mais l'**affichage GTK réel n'a pas pu être vérifié automatiquement** : signalez tout défaut visuel via les *Issues*. Google Agenda, OAuth et CalDAV ont été testés contre des serveurs simulés, pas contre les vrais services. Le chiffrement de la synchronisation est maison et **n'a pas fait l'objet d'un audit** : ne l'utilisez que sur des réseaux et avec des machines de confiance.

## Licence

Logiciel libre sous **licence MIT** — voir [LICENSE](LICENSE) : vous pouvez l'utiliser, le modifier et le redistribuer, y compris
commercialement, à condition de conserver la mention de copyright. Aucune garantie.

Développé par [SAEC](https://saec.me) · contact : contact@saec.me
