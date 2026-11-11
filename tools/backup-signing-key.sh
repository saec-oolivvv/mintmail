#!/bin/sh
# Sauvegarde la clé de signature (déjà protégée par sa phrase secrète) dans un dossier de votre choix : clé USB, disque chiffré, coffre.
# Contrôle que la copie est identique ; avec --verify, signe un fichier d'essai avec la COPIE pour prouver qu'elle sert vraiment.
# Refuse un dossier situé dans le dépôt git (la clé privée n'y a pas sa place). Affiche l'empreinte de la clé publique : à noter sur papier.
# Usage : tools/backup-signing-key.sh DOSSIER_DE_DESTINATION [--verify]
set -e
KEYDIR="${MINTMAIL_KEYDIR:-$HOME/.config/mintmail-release}"
HERE="$(cd "$(dirname "$0")/.." && pwd -P)"
DEST="$1"
[ -n "$DEST" ] && [ -d "$DEST" ] || { echo "Usage : $0 DOSSIER_DE_DESTINATION [--verify]   (le dossier doit exister : clé USB, disque chiffré…)"; exit 1; }
[ -f "$KEYDIR/signing.key" ] || { echo "Clé introuvable : $KEYDIR/signing.key"; exit 1; }
DESTABS="$(cd "$DEST" && pwd -P)"
case "$DESTABS/" in
    "$HERE"/*) echo "Refusé : $DESTABS est dans le dépôt git. Choisissez un dossier HORS du dépôt (clé USB, disque chiffré)."; exit 1 ;;
    "$(cd "$KEYDIR" && pwd -P)"/*) echo "Refusé : c'est le dossier de la clé elle-même : une sauvegarde doit être ailleurs."; exit 1 ;;
esac
umask 077
OUT="$DESTABS/mintmail-signing-backup-$(date +%Y%m%d-%H%M%S)"
mkdir "$OUT"
cp "$KEYDIR/signing.key" "$OUT/signing.key"
if [ -f "$KEYDIR/update-pubkey.pem" ]; then cp "$KEYDIR/update-pubkey.pem" "$OUT/update-pubkey.pem"; else cp "$HERE/data/update-pubkey.pem" "$OUT/update-pubkey.pem"; fi
chmod 600 "$OUT/signing.key"
cmp -s "$KEYDIR/signing.key" "$OUT/signing.key" || { echo "La copie n'est pas identique à la clé : sauvegarde invalide."; exit 1; }
grep -q "PRIVATE KEY" "$OUT/signing.key" || { echo "Le fichier copié n'est pas une clé privée PEM : sauvegarde invalide."; exit 1; }
( cd "$OUT" && sha256sum signing.key update-pubkey.pem > SHA256SUMS )
if [ "$2" = "--verify" ]; then
    T="$(mktemp)"; echo "essai" > "$T"
    openssl dgst -sha256 -sign "$OUT/signing.key" -out "$T.sig" "$T"
    openssl dgst -sha256 -verify "$OUT/update-pubkey.pem" -signature "$T.sig" "$T" 2>/dev/null | grep -q "Verified OK" || { rm -f "$T" "$T.sig"; echo "La copie ne signe pas correctement avec la clé publique : sauvegarde inutilisable."; exit 1; }
    rm -f "$T" "$T.sig"
    echo "Contrôle fonctionnel : la copie signe et la signature se vérifie avec la clé publique."
fi
FP="$(openssl pkey -pubin -in "$OUT/update-pubkey.pem" -outform DER | sha256sum | cut -d' ' -f1)"
cat <<MSG
Sauvegarde créée : $OUT   (signing.key + update-pubkey.pem + SHA256SUMS)
Empreinte de la clé publique (SHA-256) — notez-la sur papier, elle prouve plus tard que la clé retrouvée est la bonne :
  $FP
Rappels : la clé reste protégée par sa phrase secrète (notez-la ailleurs, séparément) ; gardez une copie HORS LIGNE ; sans cette clé, plus de mise à jour automatique (docs/KEY-RECOVERY.md).
MSG
