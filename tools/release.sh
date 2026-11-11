#!/bin/sh
# Publie une version SIGNÉE : vérifie, teste, construit, signe, étiquette vX.Y.Z et crée la « Release » GitHub que consultent les MintMail installés.
# Usage : tools/release.sh [--dry-run] [--skip-tests] [--rotation]       (--dry-run : tout sauf l'étiquette, l'envoi et la Release)
#   --rotation : change de clé de signature (voir docs/KEY-RECOVERY.md et tools/rotate-signing-key.sh)
set -e
cd "$(dirname "$0")/.."
DRY=""; SKIP=""; ROT=""
for a in "$@"; do
    case "$a" in --dry-run) DRY=1 ;; --skip-tests) SKIP=1 ;; --rotation) ROT=1 ;; *) echo "Option inconnue : $a"; exit 1 ;; esac
done
if [ -n "$ROT" ]; then
    [ -n "$MINTMAIL_VERIFY_PUBKEY" ] && [ -f "$MINTMAIL_VERIFY_PUBKEY" ] && [ -n "$MINTMAIL_SIGNING_KEY" ] || {
        echo "Rotation : indiquez l'ANCIENNE clé privée (MINTMAIL_SIGNING_KEY=…) et l'ANCIENNE clé publique, celle que vos machines utilisent encore (MINTMAIL_VERIFY_PUBKEY=…)."; exit 1; }
    ! cmp -s "$MINTMAIL_VERIFY_PUBKEY" data/update-pubkey.pem 2>/dev/null || { echo "Rotation : data/update-pubkey.pem est identique à l'ancienne clé publique : ce n'est pas une rotation (tools/rotate-signing-key.sh)."; exit 1; }
    echo "ROTATION DE CLÉ : ce paquet est signé avec l'ANCIENNE clé et contient la NOUVELLE clé publique ; les machines qui l'installeront feront ensuite confiance à la nouvelle clé."
else
    [ -z "$MINTMAIL_VERIFY_PUBKEY" ] || { echo "MINTMAIL_VERIFY_PUBKEY ne sert qu'à une rotation : relancez avec --rotation (ou retirez cette variable)."; exit 1; }
fi
KEY="${MINTMAIL_SIGNING_KEY:-$HOME/.config/mintmail-release/signing.key}"
python3 tools/check-version.py
VERSION="$(cat VERSION)"
[ -f data/update-pubkey.pem ] || { echo "data/update-pubkey.pem absente : lancez d'abord tools/make-signing-key.sh (puis git add / git commit)"; exit 1; }
[ -f "$KEY" ] || { echo "Clé de signature introuvable : $KEY"; exit 1; }
git ls-files --error-unmatch data/update-pubkey.pem >/dev/null 2>&1 || { echo "data/update-pubkey.pem n'est pas enregistrée dans git : git add data/update-pubkey.pem && git commit"; exit 1; }
[ -z "$(git status --porcelain --untracked-files=no)" ] || { echo "Le dépôt contient des modifications non enregistrées : faites d'abord un git commit."; git status --short --untracked-files=no; exit 1; }
# Des fichiers à la racine (un .patch, un script, des notes) ne sont pas livrés : ils ne bloquent pas. Mais le paquet embarque ces dossiers tels qu'ils sont sur le disque.
STRAY="$(git ls-files --others --exclude-standard -- mintmail data docs packaging)"
[ -z "$STRAY" ] || { echo "Fichiers non suivis dans un dossier embarqué dans le paquet (ils seraient livrés) : ajoutez-les (git add) ou retirez-les :"; echo "$STRAY"; exit 1; }
if git rev-parse "v$VERSION" >/dev/null 2>&1; then
    echo "L'étiquette v$VERSION existe déjà : changez le numéro de version (tools/bump-version.sh X.Y.Z)."
    exit 1
fi
[ -n "$SKIP" ] || python3 tests/run_all.py
packaging/build-deb.sh
DEB="dist/mintmail_${VERSION}_all.deb"
tools/sign-release.sh "$DEB" "$KEY"
dpkg-deb --fsys-tarfile "$DEB" | tar -xO ./usr/share/mintmail/update-pubkey.pem | cmp -s - data/update-pubkey.pem || { echo "Le paquet ne contient pas la clé publique du dépôt : abandon."; exit 1; }
if [ -n "$DRY" ]; then
    echo "[essai] v$VERSION prête : $DEB (+ .sig + SHA256SUMS). Rien n'a été étiqueté ni envoyé."
    exit 0
fi
NOTES="$(awk -v v="$VERSION" '$0 == "## " v {on=1; next} /^## / {on=0} on && /^- / {print}' CHANGELOG.md)"
[ -z "$ROT" ] || NOTES="$NOTES
- Rotation de la clé de signature : la nouvelle clé publique est incluse dans ce paquet"
git tag -a "v$VERSION" -m "MintMail $VERSION"
git push origin HEAD "v$VERSION"
gh release create "v$VERSION" "$DEB" "$DEB.sig" dist/SHA256SUMS --title "MintMail $VERSION" --notes "$NOTES"
echo "Publié : v$VERSION. Les MintMail installés la proposeront à leur prochain démarrage (ou tout de suite via « Rechercher les mises à jour »)."
