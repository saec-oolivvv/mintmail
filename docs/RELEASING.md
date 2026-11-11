# Publier une version

Le dépôt est **versionné** : un numéro unique `X.Y.Z` (fichier `VERSION`, copié dans `mintmail/VERSION`), un journal `CHANGELOG.md`, une étiquette git `vX.Y.Z`
et une Release GitHub **signée**. MintMail compare son numéro à celui de la dernière Release.

## Règles de numérotation (SemVer)

- `X` (majeur) : changement qui casse la compatibilité (formats de données, protocole de synchronisation entre machines).
- `Y` (mineur) : nouvelle fonction. `Z` (correctif) : correction sans nouvelle fonction (dont les correctifs de sécurité).
- Toutes les machines synchronisées doivent avoir la même version de protocole (`PROTOCOL` dans `mintmail/p2p.py`) : changez-le seulement si l'échange change.

> **Clé de signature** : sauvegarde (`tools/backup-signing-key.sh`), perte, vol et rotation sans réinstallation : [KEY-RECOVERY.md](KEY-RECOVERY.md).

## Mettre à jour le dépôt depuis un correctif (`tools/mintmail-maj.sh`)

Quand une nouvelle version est livrée sous forme de fichier `mintmail-X.Y.Z….patch`, un seul script fait toute la procédure :

```
sh tools/mintmail-maj.sh --dry-run     # vérifie tout sans rien modifier
sh tools/mintmail-maj.sh               # trouve le bon correctif (Téléchargements…), l'applique, change la version, complète le journal, enregistre, publie
```

- Il lit l'en-tête du correctif (`# mintmail-patch`, `# version:`, `# base:` = versions auxquelles il s'applique, `# note:` = lignes du journal des changements) et choisit **le bon fichier d'après votre version actuelle**, pas d'après son nom.
- Il refuse un dépôt non propre, un correctif prévu pour une autre version, un GitHub en avance sur votre dépôt ; il reconnaît un correctif déjà appliqué.
- Si une étape échoue **avant l'enregistrement**, tout est annulé (le dépôt revient exactement à son état d'avant). Si la publication échoue, votre code reste enregistré : corrigez la cause puis `tools/release.sh`.
- Un `.patch` oublié dans le dépôt est rangé dans Téléchargements (il n'entre jamais dans un commit). Options : `--no-release`, `--yes`, `--repo DOSSIER`, `--version X.Y.Z --note "…"` (correctif sans en-tête).

## Étapes

```
tools/bump-version.sh 1.12.0     # VERSION, mintmail/VERSION, nouvelle section dans CHANGELOG.md
# ... développement, puis complétez la section « 1.12.0 » du CHANGELOG.md ...
git add -A && git commit -m "MintMail 1.12.0"
tools/release.sh                 # contrôle version, dépôt propre, tests, paquet, signature, étiquette v1.12.0, push, Release GitHub
```

`tools/release.sh --dry-run` fait tout sauf l'étiquette, l'envoi et la Release. Il refuse : version incohérente, `CHANGELOG` vide ou « (à compléter) », dépôt non enregistré,
étiquette déjà existante, clé publique absente ou non enregistrée, clé privée absente, tests en échec, paquet qui ne contient pas la clé publique du dépôt, signature qui ne correspond pas.

Première mise en route (génération de la clé) : voir `docs/UPDATES.md`. Les Releases doivent toujours venir de `tools/release.sh` : une Release sans signature est ignorée par les MintMail installés
(ils l'annoncent mais refusent de l'installer). Le workflow GitHub Actions ne publie rien : il construit et teste, sans jamais détenir la clé privée.
