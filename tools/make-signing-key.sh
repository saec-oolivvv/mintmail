#!/bin/sh
# Crée UNE FOIS la paire de clés qui signe vos versions (RSA 3072). La clé PRIVÉE signe ; la clé PUBLIQUE est intégrée à MintMail
# (data/update-pubkey.pem -> /usr/share/mintmail/update-pubkey.pem) : c'est elle qui permet aux machines de vérifier que les mises à jour viennent de vous.
# Usage : tools/make-signing-key.sh [--no-passphrase]
set -e
KEYDIR="${MINTMAIL_KEYDIR:-$HOME/.config/mintmail-release}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
CIPHER="-aes-256-cbc"
[ "$1" = "--no-passphrase" ] && CIPHER=""
if [ -e "$KEYDIR/signing.key" ]; then
    echo "Une clé existe déjà : $KEYDIR/signing.key — je ne l'écrase JAMAIS (les machines déjà installées ne vérifieraient plus vos versions)."
    exit 1
fi
umask 077
mkdir -p "$KEYDIR"
[ -z "$CIPHER" ] || echo "Choisissez une phrase secrète : elle protège la clé privée et sera demandée à chaque signature."
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 $CIPHER -out "$KEYDIR/signing.key"
openssl pkey -in "$KEYDIR/signing.key" -pubout -out "$KEYDIR/update-pubkey.pem"
cp "$KEYDIR/update-pubkey.pem" "$HERE/data/update-pubkey.pem"
chmod 600 "$KEYDIR/signing.key"
cat <<MSG

Clé privée  : $KEYDIR/signing.key   (SECRÈTE : ne la mettez jamais dans le dépôt, ne l'envoyez à personne, faites-en une sauvegarde hors ligne)
Clé publique : data/update-pubkey.pem (copiée dans le dépôt : à enregistrer avec « git add data/update-pubkey.pem && git commit »)

Pourquoi c'est important : quiconque possède la clé privée peut faire installer n'importe quel programme sur TOUTES vos machines.
 • perdue  : plus aucune mise à jour automatique possible (il faudra réinstaller à la main un paquet contenant une nouvelle clé publique) ;
 • volée   : changez de clé aussitôt et faites réinstaller à la main un paquet contenant la nouvelle clé publique.
Prochaine étape : tools/release.sh
MSG
