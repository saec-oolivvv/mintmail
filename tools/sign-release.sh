#!/bin/sh
# Signe un paquet .deb (RSA / SHA-256) et écrit paquet.deb.sig + SHA256SUMS à côté ; contrôle immédiatement la signature avec data/update-pubkey.pem.
# Usage : tools/sign-release.sh dist/mintmail_X.Y.Z_all.deb [clé-privée]
set -e
DEB="$1"
KEY="${2:-${MINTMAIL_SIGNING_KEY:-$HOME/.config/mintmail-release/signing.key}}"
PUB="$(cd "$(dirname "$0")/.." && pwd)/data/update-pubkey.pem"; LABEL="data/update-pubkey.pem"
# Rotation de clé UNIQUEMENT (tools/release.sh --rotation) : la signature est contrôlée avec la clé que les machines installées utilisent encore.
[ -z "$MINTMAIL_VERIFY_PUBKEY" ] || { PUB="$MINTMAIL_VERIFY_PUBKEY"; LABEL="la clé publique actuelle des machines (rotation)"; }
[ -n "$DEB" ] && [ -f "$DEB" ] || { echo "Usage : $0 paquet.deb [clé-privée]"; exit 1; }
[ -f "$KEY" ] || { echo "Clé privée introuvable : $KEY (tools/make-signing-key.sh)"; exit 1; }
[ -f "$PUB" ] || { echo "data/update-pubkey.pem absente"; exit 1; }
openssl dgst -sha256 -sign "$KEY" -out "$DEB.sig" "$DEB"
if ! openssl dgst -sha256 -verify "$PUB" -signature "$DEB.sig" "$DEB" 2>/dev/null | grep -q "Verified OK"; then
    rm -f "$DEB.sig"
    echo "La signature ne correspond PAS à $LABEL (mauvaise clé privée ?) : rien n'a été signé."
    exit 1
fi
( cd "$(dirname "$DEB")" && sha256sum "$(basename "$DEB")" > SHA256SUMS )
echo "signé : $DEB.sig (vérifié avec $LABEL) + $(dirname "$DEB")/SHA256SUMS"
