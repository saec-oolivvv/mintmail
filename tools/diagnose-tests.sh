#!/bin/sh
# diagnose-tests.sh — lance TOUS les tests et écrit un rapport des échecs (noms + détail) dans ~/mintmail-diagnostic.txt, à m'envoyer.
#   sh tools/diagnose-tests.sh
cd "$(dirname "$0")/.." || exit 1
OUT="$HOME/mintmail-diagnostic.txt"
{
    echo "== MintMail $(cat VERSION) — $(date) =="
    git log --oneline -3 2>/dev/null
    echo "-- système --"; uname -a; python3 --version; python3 -c "import PySide6; print('PySide6', PySide6.__version__)" 2>&1 | tail -1
    echo "-- tous les tests --"
    python3 tests/run_all.py > "$OUT.full" 2>&1
    echo "code de sortie : $?"
    tail -3 "$OUT.full"
    echo "-- noms des tests en échec --"; grep -E "^ÉCHEC" "$OUT.full"
    echo "-- détail des échecs (30 lignes avant chaque ÉCHEC) --"
    grep -B30 -E "^ÉCHEC" "$OUT.full" | head -250
    echo "-- fichiers locaux modifiés --"; git status --porcelain --untracked-files=no 2>/dev/null
} > "$OUT" 2>&1
rm -f "$OUT.full"
echo "Rapport écrit : $OUT — envoyez-moi son contenu."
