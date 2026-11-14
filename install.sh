#!/usr/bin/env bash
# MintMail — installeur / mise à jour (Linux Mint, Ubuntu, Debian)
# Usage : ./install.sh [--system] [--no-deps] [--full-reset]
#   (sans option)  installation pour l'utilisateur courant dans ~/.local
#   --system       installation pour tous les utilisateurs dans /opt (sudo requis)
#   --no-deps      ne tente pas d'installer les dépendances APT
#   --full-reset   supprime d'abord l'installation, la configuration et le cache (confirmation demandée)
# Relancer le script avec une version plus récente = mise à jour (config et mails conservés).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NEW_VERSION="$(cat "$HERE/VERSION")"
SYSTEM=0; DEPS=1; RESET=0
for a in "$@"; do case "$a" in --system) SYSTEM=1;; --no-deps) DEPS=0;; --full-reset) RESET=1;; -h|--help) sed -n '2,8p' "$0"; exit 0;; esac; done

if [ "$SYSTEM" = 1 ]; then
  PREFIX=/opt/mintmail; BIN=/usr/local/bin; APPS=/usr/share/applications; ICONS=/usr/share/icons/hicolor/scalable/apps
  SUDO=sudo
else
  PREFIX="$HOME/.local/share/mintmail-app"; BIN="$HOME/.local/bin"
  APPS="$HOME/.local/share/applications"; ICONS="$HOME/.local/share/icons/hicolor/scalable/apps"; SUDO=""
fi

# --- réinitialisation complète (option --full-reset : supprime aussi réglages, mots de passe en fichier et cache)
if [ "$RESET" = 1 ]; then
  if [ -t 0 ]; then
    read -r -p "Supprimer MintMail ET toute sa configuration/son cache ? Tapez OUI : " ANSWER
    [ "$ANSWER" = "OUI" ] || { echo "Abandon."; exit 1; }
  fi
  echo "==> Réinitialisation complète"
  $SUDO rm -rf "$PREFIX" "$BIN/mintmail" "$APPS/mintmail.desktop" "$ICONS/mintmail.svg"
  rm -rf "$HOME/.config/mintmail" "$HOME/.local/share/mintmail" 2>/dev/null || true
  echo "==> Configuration et cache supprimés"
fi

echo "==> MintMail $NEW_VERSION"
if [ -f "$PREFIX/VERSION" ]; then
  OLD_VERSION="$(cat "$PREFIX/VERSION")"
  echo "    Version installée : $OLD_VERSION  →  mise à jour vers $NEW_VERSION"
  if [ "$OLD_VERSION" = "$NEW_VERSION" ]; then echo "    (même version : réinstallation)"; fi
else
  echo "    Nouvelle installation"
fi

# --- dépendances
if [ "$DEPS" = 1 ] && command -v apt-get >/dev/null 2>&1; then
  MISSING=()
  python3 -c "import venv, ensurepip" 2>/dev/null || MISSING+=(python3-venv python3-pip)
  python3 -c "import keyring" 2>/dev/null || MISSING+=(python3-keyring)
  if [ "${#MISSING[@]}" -gt 0 ]; then
    echo "==> Installation des dépendances : ${MISSING[*]}"
    sudo apt-get update -qq && sudo apt-get install -y "${MISSING[@]}"
  fi
fi

# --- copie des fichiers (sauvegarde de l'ancienne version)
$SUDO mkdir -p "$PREFIX" "$BIN" "$APPS" "$ICONS"
if [ -d "$PREFIX/app" ]; then
  $SUDO rm -rf "$PREFIX/app.previous"
  $SUDO mv "$PREFIX/app" "$PREFIX/app.previous"
fi
$SUDO mkdir -p "$PREFIX/app"
$SUDO cp -r "$HERE/mintmail" "$PREFIX/app/"
$SUDO find "$PREFIX/app" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
$SUDO install -m 644 "$HERE/VERSION" "$PREFIX/VERSION"
$SUDO install -m 644 "$HERE/data/mintmail.svg" "$ICONS/mintmail.svg"

# --- lanceur
LAUNCHER="$(mktemp)"
cat > "$LAUNCHER" <<LAUNCH
#!/usr/bin/env bash
# -I : ni dossier courant, ni PYTHONPATH, ni site utilisateur dans le chemin d'import (un « mintmail/ » posé dans le dossier courant ne peut pas détourner le programme)
exec /usr/bin/python3 -I -c 'import sys, runpy; sys.path.insert(0, "$PREFIX/app"); runpy.run_module("mintmail", run_name="__main__", alter_sys=True)' "\$@"
LAUNCH
$SUDO install -m 755 "$LAUNCHER" "$BIN/mintmail"; rm -f "$LAUNCHER"

# --- entrée de menu
DESKTOP="$(mktemp)"
sed "s|@EXEC@|$BIN/mintmail|" "$HERE/data/me.saec.mintmail.desktop" > "$DESKTOP"
$SUDO rm -f "$APPS/mintmail.desktop"
$SUDO install -m 644 "$DESKTOP" "$APPS/me.saec.mintmail.desktop"; rm -f "$DESKTOP"
ICONROOT="$(dirname "$(dirname "$ICONS")")"
for f in "$HERE"/mintmail/icons/mintmail-*.png; do s="$(basename "$f" .png)"; s="${s#mintmail-}"; $SUDO mkdir -p "$ICONROOT/${s}x${s}/apps"; $SUDO install -m 644 "$f" "$ICONROOT/${s}x${s}/apps/mintmail.png"; done
command -v update-desktop-database >/dev/null 2>&1 && $SUDO update-desktop-database "$APPS" >/dev/null 2>&1 || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && $SUDO gtk-update-icon-cache -q -t "$(dirname "$(dirname "$(dirname "$ICONS")")")" >/dev/null 2>&1 || true
command -v xdg-mime >/dev/null 2>&1 && xdg-mime default me.saec.mintmail.desktop x-scheme-handler/mailto >/dev/null 2>&1 || true

# --- interface Qt : PySide6 dans un venv privé de l'utilisateur (sans droits administrateur) ; le premier démarrage le fait aussi tout seul
if ! python3 -c "import PySide6" 2>/dev/null; then
  echo "==> Installation de l'interface Qt (PySide6) — quelques minutes la première fois…"
  "$BIN/mintmail" --install-qt || echo "    (échec : relancez plus tard « mintmail --install-qt »)"
fi

echo "==> Terminé. Lancez « mintmail » ou cherchez MintMail dans le menu."
case ":$PATH:" in *":$BIN:"*) ;; *) echo "    Astuce : ajoutez $BIN à votre PATH (ou redémarrez la session).";; esac
echo "    Configuration conservée dans ~/.config/mintmail, cache dans ~/.local/share/mintmail"
