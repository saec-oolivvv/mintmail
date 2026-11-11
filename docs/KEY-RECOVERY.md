# Clé de signature : sauvegarde, perte, vol, rotation

La clé **privée** de signature (`~/.config/mintmail-release/signing.key`, protégée par une phrase secrète) signe chaque version. Les MintMail installés ne font
confiance qu'à la clé **publique** livrée avec leur paquet (`/usr/share/mintmail/update-pubkey.pem`). Pour faire installer un faux programme à vos machines, il faut
**les deux** : la clé privée **et** un accès en écriture à votre dépôt GitHub (les Releases). Protégez donc les deux : phrase secrète longue, authentification
à deux facteurs sur le compte GitHub, jamais la clé dans le dépôt ni dans une CI.

## 1. Sauvegarder (à faire maintenant, une fois)

```
tools/backup-signing-key.sh /media/saec/CLE_USB --verify
```

- copie la clé dans un dossier daté, vérifie que la copie est **identique** et — avec `--verify` — qu'elle **signe vraiment** (la phrase secrète est demandée) ;
- refuse un dossier situé dans le dépôt git ou dans le dossier de la clé ;
- affiche l'**empreinte** de la clé publique : notez-la **sur papier**. Elle prouvera plus tard que la clé retrouvée est la bonne.

Gardez la copie **hors ligne** (clé USB rangée, coffre), et la phrase secrète **ailleurs et séparément** (gestionnaire de mots de passe, papier). Refaites une sauvegarde
après chaque rotation, et testez-la une fois par an (`--verify`).

## 2. Rotation planifiée (conseillée tous les 1 à 2 ans, ou si une personne qui a eu la clé quitte l'équipe)

Principe : une version **signée avec l'ancienne clé** et **contenant la nouvelle clé publique** est acceptée par les machines installées ; une fois installée, elles
font confiance à la nouvelle clé. **Aucune machine n'est à réinstaller à la main.**

```
tools/rotate-signing-key.sh                 # crée la nouvelle clé dans <dossier de clés>/next/, met la nouvelle clé publique dans data/update-pubkey.pem
tools/bump-version.sh X.Y.Z                 # complétez CHANGELOG.md
git add -A && git commit -m "Rotation de la clé de signature"
MINTMAIL_SIGNING_KEY=~/.config/mintmail-release/signing.key MINTMAIL_VERIFY_PUBKEY=~/.config/mintmail-release/previous-pubkey.pem tools/release.sh --rotation
# attendez que vos machines aient installé cette version, puis :
tools/rotate-signing-key.sh --finish        # la nouvelle clé devient la clé courante ; l'ancienne est rangée dans retired-<date>/
tools/backup-signing-key.sh DOSSIER --verify
```

Garde-fous vérifiés par les tests : l'ancienne clé n'est jamais écrasée ; une rotation déjà préparée n'est pas écrasée ; `release.sh` sans `--rotation` refuse de signer
avec une clé qui ne correspond pas à `data/update-pubkey.pem` ; `--rotation` refuse si l'ancienne clé publique est identique à la nouvelle.

## 3. Clé perdue

- **Vous avez une sauvegarde** : restaurez-la dans `~/.config/mintmail-release/` (`signing.key`, droits 600) ; contrôlez l'empreinte avec celle notée sur papier. Rien d'autre à faire.
- **Pas de sauvegarde** : aucune version signée par une nouvelle clé ne sera acceptée par les machines déjà installées (elles ne connaissent que l'ancienne clé publique).
  1. `tools/make-signing-key.sh` crée une nouvelle paire (il faut d'abord déplacer l'ancien dossier de clés s'il en reste des morceaux) ;
  2. commit de la nouvelle clé publique, `tools/release.sh` ;
  3. sur **chaque machine**, une seule fois : `sudo apt install ./mintmail_X.Y.Z_all.deb` (le paquet porte la nouvelle clé) ; ensuite les mises à jour automatiques reprennent.

## 4. Clé volée ou soupçonnée de l'être

Ce plan limite les dégâts, il ne garantit rien : **il n'y a pas de révocation automatique** (voir limites).

1. **Coupez l'accès GitHub** de l'attaquant : changez le mot de passe, révoquez les jetons (`gh auth logout` puis reconnexion), activez/contrôlez l'authentification à deux facteurs. Sans écriture sur le dépôt, la clé seule ne permet pas de publier.
2. **Contrôlez les Releases** (`https://github.com/<compte>/mintmail/releases`) : supprimez toute version que vous n'avez pas publiée vous-même.
3. **Faites la rotation tout de suite** (§2) : l'ancienne clé est celle que vos machines reconnaissent encore, c'est donc elle qui doit signer le paquet de transition.
   Vos machines passent à la nouvelle clé dès qu'elles installent ce paquet ; l'attaquant, lui, ne peut plus rien signer d'accepté **par les machines qui ont fait la transition**.
4. **Machines ayant installé une version suspecte** : `mintmail --check-update` et `dpkg -s mintmail` montrent la version ; si elle n'est pas l'une des vôtres, considérez la machine comme compromise (réinstallation propre).
5. Détruisez l'ancienne clé (`retired-*`) quand toutes les machines ont fait la transition.

## 5. Limites (honnêtes)

- **Pas de révocation automatique** : tant qu'une machine n'a pas installé le paquet de transition, elle accepte encore l'ancienne clé.
- **Course contre l'attaquant** : si le voleur publie une fausse version signée avant votre rotation, les machines qui la téléchargent entre-temps l'installent (avec le mot de passe administrateur demandé à l'utilisateur).
- **Attaque par gel** non détectée : on peut empêcher une machine d'apprendre qu'une version existe (voir SECURITY.md R11).
- **Une seule signature** : pas de seuil (« 2 clés sur 3 »). Évolution possible : un cadre de type TUF avec clés racine hors ligne et clés de publication à courte durée de vie.
