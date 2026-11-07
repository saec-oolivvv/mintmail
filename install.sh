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
  python3 -c "import gi; gi.require_version('Gtk','3.0'); from gi.repository import Gtk" 2>/dev/null || MISSING+=(python3-gi gir1.2-gtk-3.0)
  if ! python3 - <<'PY' 2>/dev/null
import gi
for v in ("4.1","4.0"):
    try:
        gi.require_version("WebKit2", v); break
    except ValueError:
        pass
else:
    raise SystemExit(1)
PY
  then
    if apt-cache show gir1.2-webkit2-4.1 >/dev/null 2>&1; then MISSING+=(gir1.2-webkit2-4.1); else MISSING+=(gir1.2-webkit2-4.0); fi
  fi
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
exec env PYTHONPATH="$PREFIX/app\${PYTHONPATH:+:\$PYTHONPATH}" python3 -m mintmail "\$@"
LAUNCH
$SUDO install -m 755 "$LAUNCHER" "$BIN/mintmail"; rm -f "$LAUNCHER"

# --- entrée de menu
DESKTOP="$(mktemp)"
sed "s|@EXEC@|$BIN/mintmail|" "$HERE/data/mintmail.desktop" > "$DESKTOP"
$SUDO install -m 644 "$DESKTOP" "$APPS/mintmail.desktop"; rm -f "$DESKTOP"
command -v update-desktop-database >/dev/null 2>&1 && $SUDO update-desktop-database "$APPS" >/dev/null 2>&1 || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && $SUDO gtk-update-icon-cache -q -t "$(dirname "$(dirname "$(dirname "$ICONS")")")" >/dev/null 2>&1 || true
command -v xdg-mime >/dev/null 2>&1 && xdg-mime default mintmail.desktop x-scheme-handler/mailto >/dev/null 2>&1 || true

echo "==> Terminé. Lancez « mintmail » ou cherchez MintMail dans le menu."
case ":$PATH:" in *":$BIN:"*) ;; *) echo "    Astuce : ajoutez $BIN à votre PATH (ou redémarrez la session).";; esac
echo "    Configuration conservée dans ~/.config/mintmail, cache dans ~/.local/share/mintmail"
