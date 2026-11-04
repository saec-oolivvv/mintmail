#!/usr/bin/env bash
# Désinstalle MintMail. Option --purge : supprime aussi configuration et cache de courrier.
set -u
PURGE=0; [ "${1:-}" = "--purge" ] && PURGE=1
rm -rf "$HOME/.local/share/mintmail-app" "$HOME/.local/bin/mintmail" \
  "$HOME/.local/share/applications/mintmail.desktop" "$HOME/.local/share/icons/hicolor/scalable/apps/mintmail.svg"
if [ -d /opt/mintmail ]; then
  sudo rm -rf /opt/mintmail /usr/local/bin/mintmail /usr/share/applications/mintmail.desktop \
    /usr/share/icons/hicolor/scalable/apps/mintmail.svg
fi
if [ "$PURGE" = 1 ]; then rm -rf "$HOME/.config/mintmail" "$HOME/.local/share/mintmail"; echo "Configuration et cache supprimés."; fi
echo "MintMail désinstallé."
