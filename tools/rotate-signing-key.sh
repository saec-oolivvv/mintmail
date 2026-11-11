#!/bin/sh
# Rotation PLANIFIÉE de la clé de signature : crée une NOUVELLE paire, la met en attente dans <dossier de clés>/next/ et place la nouvelle clé publique dans data/update-pubkey.pem.
# Principe : une version signée avec l'ANCIENNE clé et contenant la NOUVELLE clé publique, une fois installée, fait faire confiance à la nouvelle clé. Aucune machine n'a besoin d'être réinstallée.
# Usage : tools/rotate-signing-key.sh [--no-passphrase]     prépare la rotation (ne touche pas à l'ancienne clé)
#         tools/rotate-signing-key.sh --finish               après publication de la version de rotation : la nouvelle clé devient la clé courante
set -e
KEYDIR="${MINTMAIL_KEYDIR:-$HOME/.config/mintmail-release}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
NEXT="$KEYDIR/next"
if [ "$1" = "--finish" ]; then
    [ -f "$NEXT/signing.key" ] || { echo "Aucune rotation en attente ($NEXT/signing.key absente)."; exit 1; }
    RET="$KEYDIR/retired-$(date +%Y%m%d-%H%M%S)"
    umask 077
    mkdir "$RET"
    mv "$KEYDIR/signing.key" "$RET/signing.key"
    [ ! -f "$KEYDIR/update-pubkey.pem" ] || mv "$KEYDIR/update-pubkey.pem" "$RET/update-pubkey.pem"
    [ ! -f "$KEYDIR/previous-pubkey.pem" ] || mv "$KEYDIR/previous-pubkey.pem" "$RET/previous-pubkey.pem"
    mv "$NEXT/signing.key" "$KEYDIR/signing.key"
    mv "$NEXT/update-pubkey.pem" "$KEYDIR/update-pubkey.pem"
    rmdir "$NEXT"
    echo "La nouvelle clé est en place : $KEYDIR/signing.key"
    echo "L'ancienne est conservée dans $RET : gardez-la HORS LIGNE tant que toutes vos machines n'ont pas installé la version de rotation, puis détruisez-la."
    echo "N'oubliez pas de refaire une sauvegarde : tools/backup-signing-key.sh DOSSIER"
    exit 0
fi
CIPHER="-aes-256-cbc"
[ "$1" = "--no-passphrase" ] && CIPHER=""
[ -f "$KEYDIR/signing.key" ] || { echo "Aucune clé actuelle dans $KEYDIR (tools/make-signing-key.sh)."; exit 1; }
[ -f "$HERE/data/update-pubkey.pem" ] || { echo "data/update-pubkey.pem absente."; exit 1; }
if [ -e "$NEXT/signing.key" ]; then
    echo "Une rotation est déjà préparée ($NEXT) : terminez-la (--finish) ; je n'écrase jamais une clé."
    exit 1
fi
umask 077
mkdir -p "$NEXT"
cp "$HERE/data/update-pubkey.pem" "$KEYDIR/previous-pubkey.pem"
[ -z "$CIPHER" ] || echo "Choisissez la phrase secrète de la NOUVELLE clé."
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 $CIPHER -out "$NEXT/signing.key"
openssl pkey -in "$NEXT/signing.key" -pubout -out "$NEXT/update-pubkey.pem"
chmod 600 "$NEXT/signing.key"
cp "$NEXT/update-pubkey.pem" "$HERE/data/update-pubkey.pem"
cat <<MSG

Nouvelle clé préparée : $NEXT/signing.key   (SECRÈTE)  — l'ancienne clé n'a PAS été touchée.
La nouvelle clé publique est dans data/update-pubkey.pem ; l'ancienne clé publique est conservée dans $KEYDIR/previous-pubkey.pem.

Étapes (dans l'ordre) :
  1. tools/bump-version.sh X.Y.Z   puis complétez CHANGELOG.md
  2. git add -A && git commit -m "Rotation de la clé de signature"
  3. MINTMAIL_SIGNING_KEY="$KEYDIR/signing.key" MINTMAIL_VERIFY_PUBKEY="$KEYDIR/previous-pubkey.pem" tools/release.sh --rotation
     (signée avec l'ANCIENNE clé, contient la NOUVELLE clé publique)
  4. attendez que vos machines aient installé cette version, puis : tools/rotate-signing-key.sh --finish
  5. les versions suivantes seront signées avec la nouvelle clé (comportement par défaut de tools/release.sh)
MSG
