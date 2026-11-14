#!/bin/bash
# Essai de MintMail sur un Mac, sans rien installer de définitif : double-clic (ou « bash mac-essai.command »).
# Crée un environnement Python privé dans ce dossier (.venv-essai : PySide6 + keyring, ~1 Go la première fois), puis ouvre MintMail.
# Vos données restent dans ~/Library/Application Support/MintMail. Pour tout effacer : supprimez ce dossier.
# Si macOS refuse d'ouvrir le fichier : clic droit → Ouvrir, ou « chmod +x mac-essai.command » dans le Terminal.
cd "$(dirname "$0")" || exit 1
[ -d mintmail ] || cd .. 2>/dev/null
[ -d mintmail ] || { echo "Dossier du programme introuvable (il doit contenir « mintmail »)."; exit 1; }
PY=$(command -v python3.12 || command -v python3.11 || command -v python3.10 || command -v python3)
[ -n "$PY" ] || { echo "Python 3 est requis : installez-le depuis https://www.python.org/downloads/ puis relancez."; exit 1; }
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' || { echo "Python 3.9 ou plus récent est requis (trouvé : $("$PY" -V))."; exit 1; }
if [ ! -x .venv-essai/bin/python ]; then
    echo "→ Première fois : préparation de l'environnement (quelques minutes)…"
    "$PY" -m venv .venv-essai || exit 1
    .venv-essai/bin/pip install --quiet --upgrade pip || exit 1
    .venv-essai/bin/pip install --quiet PySide6 keyring certifi || { echo "Échec du téléchargement de PySide6 (réseau ?)."; exit 1; }
fi
export MINTMAIL_NO_AUTOINSTALL=1
echo "→ Lancement de MintMail $(cat VERSION 2>/dev/null)…  (journal d'erreurs : ~/Library/Application Support/MintMail/data/mintmail.log)"
exec .venv-essai/bin/python -m mintmail "$@"
