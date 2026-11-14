#!/bin/sh
# Construit dist/mintmail_<version>_all.deb à partir de ce dépôt (seuls dpkg-deb et python3 sont nécessaires).
# Usage : packaging/build-deb.sh        (la version vient du fichier VERSION ; epoch « 1: » conservé pour toutes les versions)
set -e
SRC=$(cd "$(dirname "$0")/.." && pwd)
FVER=$(tr -d '[:space:]' < "$SRC/VERSION")
VER="1:$FVER"
OUT="$SRC/dist"
ROOT="$OUT/build/mintmail_${FVER}_all"
CHG=$(mktemp)
# journal Debian : puces de la première section de CHANGELOG.md
awk '/^## /{n++; next} n==1 && /^- /{sub(/^- /,"  * "); print}' "$SRC/CHANGELOG.md" > "$CHG"
[ -s "$CHG" ] || echo "  * Version $FVER." > "$CHG"
rm -rf "$OUT/build" && mkdir -p $ROOT/DEBIAN $ROOT/usr/lib/python3/dist-packages $ROOT/usr/bin $ROOT/usr/share/applications $ROOT/usr/share/icons/hicolor/scalable/apps $ROOT/usr/share/doc/mintmail
cp -r $SRC/mintmail $ROOT/usr/lib/python3/dist-packages/mintmail
find $ROOT -name __pycache__ -prune -exec rm -rf {} +
printf '#!/bin/sh\nexec /usr/bin/python3 -I -m mintmail "$@"\n' > $ROOT/usr/bin/mintmail
sed 's|@EXEC@|mintmail|' $SRC/data/me.saec.mintmail.desktop > $ROOT/usr/share/applications/me.saec.mintmail.desktop
cp $SRC/mintmail/icons/mintmail.svg $ROOT/usr/share/icons/hicolor/scalable/apps/mintmail.svg
for f in $SRC/mintmail/icons/mintmail-*.png; do n=$(basename $f .png); n=${n#mintmail-}; mkdir -p $ROOT/usr/share/icons/hicolor/${n}x${n}/apps; cp $f $ROOT/usr/share/icons/hicolor/${n}x${n}/apps/mintmail.png; done
mkdir -p $ROOT/usr/share/pixmaps && cp $SRC/mintmail/icons/mintmail-48.png $ROOT/usr/share/pixmaps/mintmail.png
mkdir -p $ROOT/usr/lib/systemd/user
cat > $ROOT/usr/lib/systemd/user/mintmail-outbox.service <<'EOT'
[Unit]
Description=MintMail : envoi des messages programmés ou en attente

[Service]
Type=oneshot
ExecStart=/usr/bin/mintmail --send-due
Nice=10
EOT
cat > $ROOT/usr/lib/systemd/user/mintmail-outbox.timer <<'EOT'
[Unit]
Description=MintMail : minuterie des envois programmés (fenêtre fermée)

[Timer]
OnBootSec=2min
OnUnitActiveSec=1min
AccuracySec=15s

[Install]
WantedBy=timers.target
EOT
# --- mises à jour automatiques : programme d'installation (root), règle polkit, clé publique de vérification ---
mkdir -p $ROOT/usr/lib/mintmail $ROOT/usr/share/polkit-1/actions $ROOT/usr/share/mintmail
cat > $ROOT/usr/lib/mintmail/apply-update <<'EOT'
#!/bin/sh
# Exécuté en administrateur par pkexec (règle polkit me.saec.mintmail.update). -I : ni dossier courant, ni variables Python, ni site utilisateur.
exec /usr/bin/python3 -I -c 'import sys; from mintmail.apply_update import main; sys.exit(main())' "$@"
EOT
chmod 755 $ROOT/usr/lib/mintmail/apply-update
cp $SRC/data/me.saec.mintmail.update.policy $ROOT/usr/share/polkit-1/actions/me.saec.mintmail.update.policy
chmod 644 $ROOT/usr/share/polkit-1/actions/me.saec.mintmail.update.policy
if [ -f $SRC/data/update-pubkey.pem ]; then
    openssl pkey -pubin -in $SRC/data/update-pubkey.pem -noout 2>/dev/null || { echo "data/update-pubkey.pem n'est pas une clé publique valide"; exit 1; }
    cp $SRC/data/update-pubkey.pem $ROOT/usr/share/mintmail/update-pubkey.pem
    chmod 644 $ROOT/usr/share/mintmail/update-pubkey.pem
    echo "clé de vérification des mises à jour : incluse"
else
    echo "ATTENTION : data/update-pubkey.pem absente -> ce paquet n'installera PAS de mises à jour automatiquement (annonce seulement). Voir tools/make-signing-key.sh"
fi
for f in UPDATES.md RELEASING.md; do [ -f $SRC/docs/$f ] && cp $SRC/docs/$f $ROOT/usr/share/doc/mintmail/$f; done
cp $SRC/README.md $ROOT/usr/share/doc/mintmail/README.md
cp $SRC/LICENSE $ROOT/usr/share/doc/mintmail/LICENSE
cp $SRC/SECURITY.md $ROOT/usr/share/doc/mintmail/SECURITY.md
cp $SRC/data/oauth-clients.json.example $ROOT/usr/share/doc/mintmail/oauth-clients.json.example 2>/dev/null || true
if [ -f $SRC/data/oauth-clients.json ]; then   # identifiants OAuth préinstallés (facultatif) : aucun assistant à suivre sur les postes
    mkdir -p $ROOT/etc/mintmail && cp $SRC/data/oauth-clients.json $ROOT/etc/mintmail/oauth-clients.json
fi
PYTHONPATH=$SRC python3 -c "from mintmail import help_content as H; print(H.full_text({'version': '$FVER', 'config': '~/.config/mintmail', 'data': '~/.local/share/mintmail', 'log': '~/.local/share/mintmail/mintmail.log'}))" > $ROOT/usr/share/doc/mintmail/AIDE.txt
PYTHONPATH=$SRC python3 -c "from mintmail import i18n, help_content as H; i18n.set_language('en'); print(H.full_text({'version': '$FVER', 'config': '~/.config/mintmail', 'data': '~/.local/share/mintmail', 'log': '~/.local/share/mintmail/mintmail.log'}))" > $ROOT/usr/share/doc/mintmail/HELP-en.txt
cat > $ROOT/usr/share/doc/mintmail/copyright <<'EOT'
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: MintMail
Upstream-Contact: SAEC <contact@saec.me>
Source: https://saec.me

Files: *
Copyright: 2026 SAEC
License: Expat

License: Expat
 Permission is hereby granted, free of charge, to any person obtaining a copy
 of this software and associated documentation files (the "Software"), to deal
 in the Software without restriction, including without limitation the rights
 to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 copies of the Software, and to permit persons to whom the Software is
 furnished to do so, subject to the following conditions:
 .
 The above copyright notice and this permission notice shall be included in all
 copies or substantial portions of the Software.
 .
 THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
 SOFTWARE.
EOT
{ printf 'mintmail (%s) stable; urgency=medium\n\n' "$VER"; cat "$CHG"; printf '\n -- SAEC <contact@saec.me>  %s\n' "$(date -R)"; } | gzip -9n > $ROOT/usr/share/doc/mintmail/changelog.Debian.gz
SIZE=$(du -sk --exclude=DEBIAN $ROOT | cut -f1)
cat > $ROOT/DEBIAN/control <<EOT
Package: mintmail
Version: $VER
Section: mail
Priority: optional
Architecture: all
Depends: python3 (>= 3.9), python3-gi, gir1.2-gtk-3.0, gir1.2-webkit2-4.1 | gir1.2-webkit2-4.0, openssl
Recommends: python3-pyside6.qtwidgets, python3-pyside6.qtwebenginewidgets, python3-keyring, libnotify-bin, pkexec | policykit-1
Installed-Size: $SIZE
Maintainer: SAEC <contact@saec.me>
Homepage: https://saec.me
Description: Client de messagerie moderne avec IA intégrée
 MintMail est un client mail IMAP/SMTP pour Linux (GTK3) : boîte intelligente,
 dossiers complets, assistant IA (résumés, réponses, tri, actions confirmées),
 envoi annulable, signatures HTML, règles, blocage, gestes de balayage et
 synchronisation chiffrée et automatique entre vos machines.
 Trois styles visuels : Aurora, Papier et Terminal. Interface en français et en anglais.
 .
 MintMail is a modern IMAP/SMTP mail client for Linux (GTK3) with built-in AI
 (summaries, replies, sorting, always-confirmed actions), undoable sending,
 HTML signatures, rules, blocking and encrypted sync between your machines.
 The interface is available in French and English.
EOT
cat > $ROOT/DEBIAN/preinst <<'EOT'
#!/bin/sh
set -e
# La clé publique de mises à jour ne doit JAMAIS disparaître lors d'une installation : si le paquet précédent en avait une, on la met à l'abri.
if [ -f /usr/share/mintmail/update-pubkey.pem ] && [ ! -L /usr/share/mintmail/update-pubkey.pem ]; then
    mkdir -p /var/lib/mintmail && cp -p /usr/share/mintmail/update-pubkey.pem /var/lib/mintmail/update-pubkey.pem.keep && chmod 644 /var/lib/mintmail/update-pubkey.pem.keep || true
fi
exit 0
EOT
cat > $ROOT/DEBIAN/postinst <<'EOT'
#!/bin/sh
set -e
if [ "$1" = "configure" ]; then
    # clé publique absente du nouveau paquet : on remet celle de l'installation précédente (propriété de root, comme exigé pour les mises à jour)
    if [ ! -f /usr/share/mintmail/update-pubkey.pem ] && [ -f /var/lib/mintmail/update-pubkey.pem.keep ]; then
        mkdir -p /usr/share/mintmail && cp /var/lib/mintmail/update-pubkey.pem.keep /usr/share/mintmail/update-pubkey.pem && chown root:root /usr/share/mintmail/update-pubkey.pem && chmod 644 /usr/share/mintmail/update-pubkey.pem || true
    fi
    if command -v py3compile >/dev/null 2>&1; then py3compile -p mintmail || true; fi
    if command -v update-desktop-database >/dev/null 2>&1; then update-desktop-database -q /usr/share/applications || true; fi
    if command -v gtk-update-icon-cache >/dev/null 2>&1; then gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true; fi
    if command -v systemctl >/dev/null 2>&1; then systemctl --global enable mintmail-outbox.timer >/dev/null 2>&1 || true; fi
    for h in /home/*; do
        if [ -e "$h/.local/bin/mintmail" ] || [ -d "$h/.local/share/mintmail-app" ]; then
            echo "mintmail : ancienne installation locale détectée dans $h (elle masque ce paquet)."
            echo "           Pour la liste (sans rien modifier), exécutez : /usr/bin/mintmail --remove-local-install"
        fi
    done
fi
exit 0
EOT
cat > $ROOT/DEBIAN/prerm <<'EOT'
#!/bin/sh
set -e
if [ "$1" = "remove" ] || [ "$1" = "upgrade" ] || [ "$1" = "deconfigure" ]; then
    if command -v py3clean >/dev/null 2>&1; then py3clean -p mintmail || true; fi
    if [ "$1" = "remove" ] && command -v systemctl >/dev/null 2>&1; then systemctl --global disable mintmail-outbox.timer >/dev/null 2>&1 || true; fi
fi
exit 0
EOT
cat > $ROOT/DEBIAN/postrm <<'EOT'
#!/bin/sh
set -e
if [ "$1" = "remove" ] || [ "$1" = "purge" ]; then
    if command -v update-desktop-database >/dev/null 2>&1; then update-desktop-database -q /usr/share/applications || true; fi
    if command -v gtk-update-icon-cache >/dev/null 2>&1; then gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true; fi
fi
exit 0
EOT
chmod 755 $ROOT/DEBIAN/preinst $ROOT/DEBIAN/postinst $ROOT/DEBIAN/prerm $ROOT/DEBIAN/postrm
find $ROOT -type d -exec chmod 755 {} +; find $ROOT/usr -type f -exec chmod 644 {} +; chmod 755 $ROOT/usr/bin/mintmail $ROOT/usr/lib/mintmail/apply-update   # pkexec exige un programme exécutable
[ -f $ROOT/etc/mintmail/oauth-clients.json ] && echo /etc/mintmail/oauth-clients.json > $ROOT/DEBIAN/conffiles && chmod 644 $ROOT/etc/mintmail/oauth-clients.json
(cd $ROOT && find usr -type f -exec md5sum {} + > DEBIAN/md5sums)
for f in preinst postinst prerm postrm; do sh -n $ROOT/DEBIAN/$f; done
dpkg-deb --root-owner-group -Zxz --build $ROOT $OUT/mintmail_${FVER}_all.deb >/dev/null
rm -rf "$OUT/build" "$CHG"
echo "construit : $OUT/mintmail_${FVER}_all.deb"
