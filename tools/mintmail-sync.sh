#!/bin/sh
# mintmail-sync.sh — compare votre dépôt MintMail LOCAL et GitHub, montre l'écart, puis fait le nécessaire pour tout publier.
#
#   sh mintmail-sync.sh                 état des lieux, puis propose les actions (enregistrer, envoyer, étiqueter, publier la Release)
#   sh mintmail-sync.sh --dry-run       état des lieux seulement, ne modifie rien
#   sh mintmail-sync.sh --yes           n'interroge pas (sauf la phrase secrète de signature)
#   sh mintmail-sync.sh --skip-tests    publie sans la batterie de tests (à réserver à un échec compris et sans lien avec le code)
#   sh mintmail-sync.sh --diagnose      lance seul le test en échec 3 fois et écrit un rapport à m'envoyer (~/mintmail-diagnostic.txt)
#   --repo DOSSIER                      dépôt (défaut : $MINTMAIL_REPO, sinon ~/Documents/github/mintmail)
#
# Ce que le script règle : commits locaux non envoyés, retard sur GitHub (mise à jour sans conflit), étiquette locale jamais envoyée,
# version courante sans Release signée (tools/release.sh). Il s'arrête, sans rien casser, si les deux côtés ont divergé
# ou si des fichiers suivis sont modifiés. Les fichiers non suivis (scripts, .patch, notes) sont ignorés.
set -u
die() { echo "✗ $*" >&2; exit 1; }
info() { echo "• $*"; }
ok() { echo "✓ $*"; }

REPO="${MINTMAIL_REPO:-$HOME/Documents/github/mintmail}"
DRY=""; YES=""; SKIP=""; DIAG=""
while [ $# -gt 0 ]; do
    case "$1" in
        --repo) [ $# -ge 2 ] || die "--repo demande un dossier"; REPO="$2"; shift 2 ;;
        --dry-run) DRY=1; shift ;;
        --yes|-y) YES=1; shift ;;
        --skip-tests) SKIP="--skip-tests"; shift ;;
        --diagnose) DIAG=1; shift ;;
        -h|--help) sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) die "Option inconnue : $1 (voir --help)" ;;
    esac
done
[ -d "$REPO/.git" ] && [ -f "$REPO/VERSION" ] && [ -f "$REPO/tools/release.sh" ] || die "$REPO n'est pas votre dépôt MintMail (option --repo DOSSIER)."
cd "$REPO" || die "dossier inaccessible : $REPO"
ask() { [ -n "$YES" ] && return 0; printf '%s [o/N] ' "$1"; read -r r; case "$r" in o|O|oui|y|Y) return 0 ;; *) return 1 ;; esac; }

if [ -n "$DIAG" ]; then
    OUT="$HOME/mintmail-diagnostic.txt"
    {
        echo "== MintMail $(cat VERSION) — $(date) =="
        git log --oneline -3
        for i in 1 2 3; do
            echo "-- essai $i du test test_review_tools --"
            MINTMAIL_NO_KEYRING=1 python3 - <<'PY' 2>&1 | tail -15
import sys, importlib, traceback
sys.path.insert(0, "tests"); sys.path.insert(0, ".")
m = importlib.import_module("test_review_tools")
for n in dir(m):
    if n.startswith("test_") and "works_end_to_end" in n:
        try:
            getattr(m, n)(); print("OK", n)
        except Exception:
            traceback.print_exc(); print("ÉCHEC", n)
PY
        done
        echo "-- test_review_tools.py lignes 85-125 --"
        sed -n 85,125p tests/test_review_tools.py
        echo "-- fichiers de langue : fins de ligne --"
        for l in mintmail/locale/*.json; do printf '%s ' "$l"; tail -c 2 "$l" | od -An -c | tr -s ' '; done
        echo "-- fichiers locaux modifiés --"; git status --porcelain --untracked-files=no
    } > "$OUT" 2>&1
    ok "Rapport écrit : $OUT — envoyez-moi son contenu."
    exit 0
fi

BR="$(git rev-parse --abbrev-ref HEAD)"
[ "$BR" != "HEAD" ] || die "tête détachée : placez-vous sur une branche (git switch main)."
VER="$(tr -d '[:space:]' < VERSION)"
info "Dépôt : $REPO — branche $BR — version locale $VER"
git fetch --tags --prune origin >/dev/null 2>&1 || die "GitHub injoignable (réseau, gh auth login ?) : rien n'a été modifié."
UP="origin/$BR"
git rev-parse --verify -q "$UP" >/dev/null || die "la branche $UP n'existe pas sur GitHub (premier envoi : git push -u origin $BR)."
AHEAD="$(git rev-list --count "$UP..HEAD")"; BEHIND="$(git rev-list --count "HEAD..$UP")"
DIRTY="$(git status --porcelain --untracked-files=no)"

echo; echo "── Comparaison local / GitHub ──"
echo "  commits locaux non envoyés : $AHEAD"
echo "  commits GitHub non récupérés : $BEHIND"
[ -z "$DIRTY" ] && echo "  fichiers suivis modifiés : aucun" || { echo "  fichiers suivis modifiés :"; echo "$DIRTY" | sed 's/^/    /'; }
[ "$AHEAD" -gt 0 ] && git log --oneline "$UP..HEAD" | sed 's/^/    ↑ /'
[ "$BEHIND" -gt 0 ] && git log --oneline "HEAD..$UP" | sed 's/^/    ↓ /'
REMOTE_TAGS="$(git ls-remote --tags origin 2>/dev/null | sed -n 's#.*refs/tags/\(v[0-9][^ ^]*\)$#\1#p' | sort -u)"
LOCAL_ONLY=""
for t in $(git tag -l 'v[0-9]*'); do echo "$REMOTE_TAGS" | grep -qx "$t" || LOCAL_ONLY="$LOCAL_ONLY $t"; done
[ -n "$LOCAL_ONLY" ] && echo "  étiquettes locales non envoyées :$LOCAL_ONLY" || echo "  étiquettes locales non envoyées : aucune"
HAVE_REL=""; REL_KNOWN=""
if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
    REL_KNOWN=1
    gh release view "v$VER" >/dev/null 2>&1 && HAVE_REL=1
    [ -n "$HAVE_REL" ] && echo "  Release GitHub v$VER : publiée" || echo "  Release GitHub v$VER : ABSENTE"
else
    echo "  Release GitHub v$VER : inconnue (gh non installé ou non connecté : gh auth login)"
fi
echo

if [ "$BEHIND" -gt 0 ] && [ "$AHEAD" -gt 0 ]; then
    die "local et GitHub ont chacun des commits différents (divergence). Rien n'a été modifié. Montrez-moi : git log --oneline --graph --all -15"
fi
if [ -n "$DIRTY" ]; then
    echo "$DIRTY" | grep -q '^[UAD][UAD]' && die "conflit de fusion en cours : résolvez-le d'abord."
    info "Des fichiers suivis sont modifiés et non enregistrés."
    if [ -z "$DRY" ] && ask "Les enregistrer dans un commit « MintMail $VER : modifications locales » ?"; then
        git add -u && git commit -qm "MintMail $VER : modifications locales" && ok "Enregistré." || die "échec de l'enregistrement."
        AHEAD=$((AHEAD + 1))
    else
        [ -n "$DRY" ] || die "arrêt : enregistrez ou annulez ces modifications, puis relancez."
    fi
fi

TODO=""
[ "$BEHIND" -gt 0 ] && TODO="$TODO\n  - récupérer $BEHIND commit(s) de GitHub (sans conflit possible : vous n'avez rien en plus)"
[ "$AHEAD" -gt 0 ] && TODO="$TODO\n  - envoyer $AHEAD commit(s) local(aux) sur GitHub"
[ -n "$LOCAL_ONLY" ] && TODO="$TODO\n  - envoyer les étiquettes :$LOCAL_ONLY"
NEED_REL=""
[ -n "$REL_KNOWN" ] && [ -z "$HAVE_REL" ] && { NEED_REL=1; TODO="$TODO\n  - publier la Release signée v$VER (tests, paquet .deb, signature, envoi)"; }
if [ -z "$TODO" ]; then ok "Local et GitHub sont identiques, la Release v$VER est publiée : rien à faire."; exit 0; fi
printf 'À faire :%b\n\n' "$TODO"
[ -z "$DRY" ] || { info "--dry-run : rien n'a été modifié."; exit 0; }
ask "Faire le nécessaire maintenant ?" || { info "Annulé : rien n'a été modifié."; exit 0; }

if [ "$BEHIND" -gt 0 ]; then
    git merge --ff-only "$UP" >/dev/null 2>&1 || die "récupération impossible sans conflit : rien n'a été modifié."
    ok "Dépôt mis à jour depuis GitHub."
    VER="$(tr -d '[:space:]' < VERSION)"
fi
if [ "$NEED_REL" = 1 ]; then
    # release.sh refuse une étiquette déjà présente en local : si elle n'a jamais été envoyée et qu'aucune Release n'existe, on la retire d'abord
    if git rev-parse -q --verify "refs/tags/v$VER" >/dev/null && ! echo "$REMOTE_TAGS" | grep -qx "v$VER"; then
        git tag -d "v$VER" >/dev/null && info "Étiquette locale v$VER jamais envoyée : retirée (release.sh la recrée)."
    fi
    info "Publication de v$VER : votre phrase secrète de signature va être demandée."
    # shellcheck disable=SC2086
    sh tools/release.sh $SKIP || {
        echo
        echo "✗ La publication s'est arrêtée (message ci-dessus). Votre code est enregistré ET envoyé si possible ci-dessous."
        [ "$AHEAD" -gt 0 ] && git push origin HEAD >/dev/null 2>&1 && ok "Commits envoyés malgré tout."
        echo "  Si c'est un test : sh mintmail-sync.sh --diagnose   (puis envoyez-moi ~/mintmail-diagnostic.txt)"
        exit 1
    }
    exit 0
fi
if [ "$AHEAD" -gt 0 ]; then git push origin HEAD || die "envoi refusé."; ok "Commits envoyés."; fi
if [ -n "$LOCAL_ONLY" ]; then for t in $LOCAL_ONLY; do git push origin "$t" || die "envoi de $t refusé."; done; ok "Étiquettes envoyées."; fi
ok "Terminé : local et GitHub sont synchronisés."
