#!/bin/sh
# mintmail-maj.sh — met à jour votre dépôt MintMail depuis un correctif (.patch) téléchargé, puis publie la version.
#
#   sh mintmail-maj.sh                    cherche le bon correctif dans Téléchargements, l'applique, change la version, note le journal, enregistre, publie
#   sh mintmail-maj.sh FICHIER.patch      idem avec ce fichier
#   sh mintmail-maj.sh --dry-run          vérifie TOUT sans rien modifier
#   sh mintmail-maj.sh --no-release       applique et enregistre, ne publie pas
#   sh mintmail-maj.sh --yes              ne demande pas confirmation avant la publication
#   --repo DOSSIER                        dépôt (défaut : $MINTMAIL_REPO, sinon ~/Documents/github/mintmail)
#   --version X.Y.Z --note "texte"        pour un correctif SANS en-tête « # mintmail-patch »
#   MINTMAIL_RELEASE_ARGS="--skip-tests"  options passées à tools/release.sh (essais)
#
# Sûr par construction : refuse des fichiers SUIVIS modifiés (les fichiers non suivis à la racine — ce script, des .patch, des notes — sont ignorés et jamais enregistrés), un correctif qui ne correspond pas à votre version ou déjà appliqué ;
# n'écrase rien ; si une étape échoue AVANT l'enregistrement, tout est annulé et le dépôt revient à son état d'avant.
set -u
usage() { sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; }
die() { echo "✗ $*" >&2; exit 1; }
info() { echo "• $*"; }

REPO="${MINTMAIL_REPO:-$HOME/Documents/github/mintmail}"
PATCH=""; DRY=""; NOREL=""; YES=""; VER=""; NOTE_ARG=""
while [ $# -gt 0 ]; do
    case "$1" in
        --repo) [ $# -ge 2 ] || die "--repo demande un dossier"; REPO="$2"; shift 2 ;;
        --dry-run) DRY=1; shift ;;
        --no-release) NOREL=1; shift ;;
        --yes|-y) YES=1; shift ;;
        --version) [ $# -ge 2 ] || die "--version demande un numéro"; VER="$2"; shift 2 ;;
        --note) [ $# -ge 2 ] || die "--note demande un texte"; NOTE_ARG="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        -*) die "Option inconnue : $1 (voir --help)" ;;
        *) PATCH="$1"; shift ;;
    esac
done

[ -d "$REPO/.git" ] && [ -f "$REPO/VERSION" ] && [ -f "$REPO/tools/release.sh" ] || die "$REPO n'est pas votre dépôt MintMail (option --repo DOSSIER)."
REPO="$(cd "$REPO" && pwd -P)"
cd "$REPO" || die "dossier inaccessible : $REPO"
CUR="$(cat VERSION)"
info "Dépôt : $REPO — version actuelle : $CUR"

hdr() { head -40 "$1" | sed -n "s/^# $2: *//p"; }                       # champ d'en-tête (première occurrence pour « version » et « base »)
is_mm_patch() { head -1 "$1" 2>/dev/null | grep -q '^# mintmail-patch'; }
has_word() { for w in $1; do [ "$w" = "$2" ] && return 0; done; return 1; }

# ---------------------------------------------------------------- 1. quel correctif ?
if [ -z "$PATCH" ]; then
    DL="$(xdg-user-dir DOWNLOAD 2>/dev/null || true)"
    LIST="$(mktemp)"
    for d in "$DL" "$HOME/Téléchargements" "$HOME/Downloads" "$REPO" "$(pwd -P)" "$(dirname "$REPO")"; do
        [ -n "$d" ] && [ -d "$d" ] && find "$d" -maxdepth 1 -type f -name 'mintmail-*.patch' -printf '%T@ %p\n' 2>/dev/null
    done | sort -rn | cut -d' ' -f2- | awk '!seen[$0]++' > "$LIST"
    [ -s "$LIST" ] || { rm -f "$LIST"; die "Aucun fichier mintmail-*.patch trouvé (Téléchargements, dépôt, dossier courant). Téléchargez le correctif, ou indiquez son chemin : sh $0 CHEMIN.patch"; }
    PATCH="$(while IFS= read -r f; do
        is_mm_patch "$f" || continue
        has_word "$(hdr "$f" base)" "$CUR" || continue
        printf '%s\t%s\n' "$(hdr "$f" version)" "$f"
    done < "$LIST" | sort -t "$(printf '\t')" -k1,1V | tail -1 | cut -f2-)"          # plusieurs conviennent : la version la plus haute l'emporte, pas la date du fichier
    if [ -z "$PATCH" ]; then
        echo "✗ Aucun correctif trouvé ne s'applique à la version $CUR. Trouvés :" >&2
        while IFS= read -r f; do
            if is_mm_patch "$f"; then echo "    $f  → pour la version : $(hdr "$f" base)  (apporte $(hdr "$f" version))" >&2; else echo "    $f  (sans en-tête : utilisez --version et --note)" >&2; fi
        done < "$LIST"
        rm -f "$LIST"; exit 1
    fi
    rm -f "$LIST"
fi
[ -f "$PATCH" ] || die "Fichier introuvable : $PATCH"
PATCH="$(cd "$(dirname "$PATCH")" && pwd -P)/$(basename "$PATCH")"
info "Correctif : $PATCH  (empreinte $(sha256sum "$PATCH" | cut -c1-16))"

if is_mm_patch "$PATCH"; then
    NEWV="$(hdr "$PATCH" version)"; BASES="$(hdr "$PATCH" base)"
    NOTES="$(head -40 "$PATCH" | sed -n 's/^# note: *//p')"
    [ -z "$VER" ] || NEWV="$VER"
    [ -z "$NOTE_ARG" ] || NOTES="$NOTE_ARG"
    has_word "$BASES" "$CUR" || die "Ce correctif est prévu pour la version $BASES, la vôtre est $CUR. Prenez le correctif qui correspond (ou le cumulatif)."
else
    [ -n "$VER" ] && [ -n "$NOTE_ARG" ] || die "Ce correctif n'a pas d'en-tête : précisez --version X.Y.Z et --note \"texte du journal\"."
    NEWV="$VER"; NOTES="$NOTE_ARG"
fi
echo "$NEWV" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$' || die "Numéro de version invalide : $NEWV"
[ -n "$NOTES" ] || die "Aucune note pour le journal des changements (--note)."
info "Version à publier : $NEWV"

# ---------------------------------------------------------------- 2. le dépôt est-il prêt ?
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
cp "$PATCH" "$WORK/patch"
DIRTY="$(git status --porcelain --untracked-files=no)"
if [ -n "$DIRTY" ]; then
    echo "✗ Des fichiers SUIVIS du dépôt sont modifiés et non enregistrés :" >&2
    echo "$DIRTY" | sed 's/^/    /' >&2
    die "Enregistrez-les (git commit) ou annulez-les (git checkout -- fichier) d'abord ; rien n'a été changé."
fi
STRAY_SHIPPED="$(git ls-files --others --exclude-standard -- mintmail data docs packaging)"
if [ -n "$STRAY_SHIPPED" ]; then
    echo "$STRAY_SHIPPED" | sed 's/^/    /' >&2
    die "Fichiers non suivis dans un dossier embarqué dans le paquet (ils seraient livrés) : ajoutez-les (git add) ou retirez-les. Rien n'a été changé."
fi
OTHERS="$(git ls-files --others --exclude-standard | wc -l)"
[ "$OTHERS" -eq 0 ] || info "$OTHERS fichier(s) non suivi(s) à la racine (ce correctif, ce script, des notes…) : ignorés, ils ne seront pas inclus dans le commit."
BR="$(git rev-parse --abbrev-ref HEAD)"
[ "$BR" = "main" ] || info "⚠ Vous êtes sur la branche « $BR » (et non « main »)."
if git fetch -q origin main 2>/dev/null; then
    git merge-base --is-ancestor origin/main HEAD || die "GitHub contient des commits absents de votre dépôt : faites d'abord « git pull --ff-only » (ou demandez de l'aide)."
    info "GitHub est joignable et votre dépôt est à jour avec lui."
else
    info "⚠ GitHub injoignable : l'application sera faite, mais la publication échouera tant que le réseau manque."
fi
if git apply --check --reverse --whitespace=nowarn "$WORK/patch" 2>/dev/null; then
    if [ "$CUR" = "$NEWV" ]; then
        info "Ce correctif est DÉJÀ appliqué et la version est déjà $NEWV : rien à faire. (Publier : tools/release.sh)"
    else
        info "Ce correctif semble DÉJÀ appliqué (version $CUR). Rien à faire."
    fi
    exit 0
fi
git apply --check --whitespace=nowarn "$WORK/patch" 2>"$WORK/err" || { cat "$WORK/err" >&2; die "Le correctif ne s'applique pas à ce dépôt (fichier incomplet, ou dépôt modifié). Rien n'a été changé."; }
N="$(git apply --numstat "$WORK/patch" | wc -l)"
info "Le correctif s'applique proprement ($N fichiers)."
if [ -n "$DRY" ]; then
    info "[essai] Rien n'a été modifié. En vrai : version $CUR → $NEWV, journal :"
    echo "$NOTES" | sed 's/^/      - /'
    exit 0
fi

# ---------------------------------------------------------------- 3. application (annulée en cas d'échec avant l'enregistrement)
rollback() {
    git checkout -q -- VERSION mintmail/VERSION CHANGELOG.md 2>/dev/null
    git apply --reverse --whitespace=nowarn "$WORK/patch" >/dev/null 2>&1
    echo "↩ Étape échouée : toutes les modifications ont été annulées, votre dépôt est revenu à son état d'avant." >&2
    exit 1
}
git apply --whitespace=nowarn "$WORK/patch" || rollback
info "✓ Correctif appliqué."
sh tools/bump-version.sh "$NEWV" >/dev/null 2>"$WORK/err" || { cat "$WORK/err" >&2; echo "✗ Changement de version refusé (la nouvelle version doit être plus récente que $CUR)." >&2; rollback; }
echo "$NOTES" > "$WORK/notes"
python3 - "$NEWV" "$WORK/notes" <<'PY' || rollback
import sys
notes = [l.strip().lstrip("-").strip() for l in open(sys.argv[2], encoding="utf-8") if l.strip()]
p = "CHANGELOG.md"
t = open(p, encoding="utf-8").read()
new = t.replace("- (à compléter)", "\n".join("- " + n for n in notes), 1)
assert new != t, "marqueur « (à compléter) » introuvable"
open(p, "w", encoding="utf-8").write(new)
PY
python3 tools/check-version.py >/dev/null 2>"$WORK/err" || { cat "$WORK/err" >&2; rollback; }
info "✓ Version $NEWV, journal des changements complété."
IDENT=""
git config user.name >/dev/null 2>&1 || IDENT="-c user.name=SAEC -c user.email=contact@saec.me"
git apply --numstat -z "$WORK/patch" | tr '\0' '\n' | cut -f3- | while IFS= read -r p; do [ -n "$p" ] && git add -- "$p"; done
git add -- VERSION mintmail/VERSION CHANGELOG.md || rollback
git $IDENT commit -q -m "MintMail $NEWV" || rollback
info "✓ Enregistré (commit « MintMail $NEWV »)."

# ---------------------------------------------------------------- 4. publication
if [ -n "$NOREL" ]; then
    info "Non publié (--no-release). Pour publier : cd $REPO && tools/release.sh"
    exit 0
fi
echo
echo "Prêt à publier MintMail $NEWV : tests, paquet, signature (votre phrase secrète sera demandée), envoi sur GitHub, Release."
if [ -z "$YES" ]; then
    printf "Publier maintenant ? [o/N] "
    read -r ANS
    case "$ANS" in o|O|oui|OUI|y|Y|yes) ;; *) info "Non publié. Plus tard : cd $REPO && tools/release.sh"; exit 0 ;; esac
fi
# shellcheck disable=SC2086
tools/release.sh ${MINTMAIL_RELEASE_ARGS:-} || {
    echo "✗ La publication s'est arrêtée (voir le message ci-dessus). Votre code est enregistré. Corrigez la cause, puis : cd $REPO && tools/release.sh" >&2
    echo "  (si l'étiquette v$NEWV existe déjà en local sans avoir été envoyée : git tag -d v$NEWV, puis relancez)" >&2
    exit 1
}
echo
info "✓ Terminé. Dans MintMail : Paramètres → Mises à jour → Vérifier maintenant (ou « mintmail --check-update » dans un terminal)."
