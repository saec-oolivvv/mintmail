"""tools/mintmail-maj.sh : mise à jour du dépôt depuis un correctif, de bout en bout (vrai git, faux gh, faux dépôt distant GitHub)."""
import os, shutil, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_release_tools import make_repo, sh, AVAILABLE, ROOT

SCRIPT = os.path.join(ROOT, "tools", "mintmail-maj.sh")


def user_repo():
    """Dépôt de l'utilisateur : clé publique enregistrée, déjà poussé sur « GitHub » (dépôt nu), faux gh, dossier Téléchargements."""
    work, bare, log, env = make_repo()
    sh("tools/make-signing-key.sh --no-passphrase", work, env)
    sh("git add -A && git commit -q -m clé && git push -q origin HEAD:main", work)
    home = os.path.join(os.path.dirname(bare), "home")
    dl = os.path.join(home, "Téléchargements")
    os.makedirs(dl)
    env = dict(env, HOME=home, MINTMAIL_RELEASE_ARGS="--skip-tests")
    return work, bare, log, env, dl


def make_patch(work, dest, name, header=None, extra_line="essai"):
    """Fabrique un vrai correctif (git diff) : un nouveau fichier + une ligne ajoutée à un document."""
    clone = tempfile.mkdtemp()
    subprocess.run(["git", "clone", "-q", work, clone], check=True, capture_output=True)
    with open(os.path.join(clone, "docs", "ESSAI.md"), "w", encoding="utf-8") as f:
        f.write("# Essai\n%s\n" % extra_line)
    with open(os.path.join(clone, "docs", "RELEASING.md"), "a", encoding="utf-8") as f:
        f.write("\nLigne ajoutée par le correctif d'essai.\n")
    subprocess.run(["git", "add", "-A", "-N"], cwd=clone, check=True, capture_output=True)
    body = subprocess.run(["git", "diff"], cwd=clone, check=True, capture_output=True, text=True).stdout
    path = os.path.join(dest, name)
    with open(path, "w", encoding="utf-8") as f:
        if header:
            f.write("# mintmail-patch\n" + "".join("# %s: %s\n" % (k, v) for k, v in header) + "\n")
        f.write(body)
    return path


def run(args, work, env, ok=True, input=None, cwd=None):
    return sh(["sh", SCRIPT, "--repo", work] + args, cwd or os.path.dirname(work), env, ok=ok, input=input)


def version(work):
    return open(os.path.join(work, "VERSION")).read().strip()


def head_msg(work):
    return sh("git log -1 --format=%s", work).stdout.strip()


def test_full_run_finds_the_patch_applies_bumps_notes_commits_and_publishes_without_leaving_traces():
    if not AVAILABLE:
        return
    work, bare, log, env, dl = user_repo()
    cur = version(work)
    patch = make_patch(work, dl, "mintmail-9.9.9.patch", [("version", "9.9.9"), ("base", "0.0.1 %s" % cur), ("note", "Première nouveauté « avec accents »"), ("note", "Deuxième nouveauté")])
    r = run(["--yes"], work, env)
    assert "Correctif appliqué" in r.stdout and "Publié : v9.9.9" in r.stdout and "Terminé" in r.stdout, r.stdout[-600:]
    assert version(work) == "9.9.9" and open(os.path.join(work, "mintmail", "VERSION")).read().strip() == "9.9.9"
    changelog = open(os.path.join(work, "CHANGELOG.md"), encoding="utf-8").read()
    assert "## 9.9.9\n- Première nouveauté « avec accents »\n- Deuxième nouveauté\n" in changelog and "(à compléter)" not in changelog
    assert os.path.exists(os.path.join(work, "docs", "ESSAI.md")) and head_msg(work) == "MintMail 9.9.9" and sh("git status --short", work).stdout == ""
    assert "mintmail-9.9.9.patch" not in sh("git ls-files", work).stdout and os.path.exists(patch)               # le fichier de l'utilisateur n'est ni supprimé ni versionné
    assert sh("git tag", work).stdout.split() == ["v9.9.9"]
    assert subprocess.run(["git", "--git-dir", bare, "tag"], capture_output=True, text=True).stdout.split() == ["v9.9.9"]
    assert subprocess.run(["git", "--git-dir", bare, "log", "-1", "--format=%s", "main"], capture_output=True, text=True).stdout.strip() == "MintMail 9.9.9"      # GitHub est à jour
    assert open(log, encoding="utf-8").read().startswith("release create v9.9.9 ")


def test_dry_run_checks_everything_and_changes_nothing():
    if not AVAILABLE:
        return
    work, bare, log, env, dl = user_repo()
    cur = version(work)
    make_patch(work, dl, "mintmail-9.9.9.patch", [("version", "9.9.9"), ("base", cur), ("note", "Essai")])
    before = sh("git rev-parse HEAD", work).stdout
    r = run(["--dry-run"], work, env)
    assert "[essai]" in r.stdout and "s'applique proprement" in r.stdout and version(work) == cur and sh("git rev-parse HEAD", work).stdout == before
    assert sh("git status --short", work).stdout == "" and not os.path.exists(os.path.join(work, "docs", "ESSAI.md")) and not os.path.exists(log)


def test_a_patch_for_another_version_is_explained_and_nothing_changes():
    if not AVAILABLE:
        return
    work, bare, log, env, dl = user_repo()
    cur = version(work)
    other = make_patch(work, dl, "mintmail-8.0.0.patch", [("version", "8.0.0"), ("base", "7.7.7"), ("note", "x")])
    r = run([], work, env, ok=False)
    assert "Aucun correctif trouvé ne s'applique à la version %s" % cur in r.stderr and "7.7.7" in r.stderr and "mintmail-8.0.0.patch" in r.stderr
    r = run([other], work, env, ok=False)
    assert "prévu pour la version 7.7.7" in r.stderr and version(work) == cur and sh("git status --short", work).stdout == ""
    empty = tempfile.mkdtemp()
    r = sh(["sh", SCRIPT, "--repo", work], empty, dict(env, HOME=empty), ok=False)                                 # aucun fichier du tout
    assert "Aucun fichier mintmail-*.patch" in r.stderr


def test_the_right_patch_is_chosen_among_several_by_version_not_by_name():
    if not AVAILABLE:
        return
    work, bare, log, env, dl = user_repo()
    cur = version(work)
    make_patch(work, dl, "mintmail-9.9.9-incremental.patch", [("version", "9.9.9"), ("base", cur), ("note", "Bon correctif")])
    make_patch(work, dl, "mintmail-9.9.9-cumulatif.patch", [("version", "9.9.9"), ("base", "0.0.1"), ("note", "Mauvais correctif")])
    os.utime(os.path.join(dl, "mintmail-9.9.9-cumulatif.patch"), None)                                           # le plus récent n'est pas le bon
    run(["--no-release"], work, env)
    assert "Bon correctif" in open(os.path.join(work, "CHANGELOG.md"), encoding="utf-8").read() and "Mauvais correctif" not in open(os.path.join(work, "CHANGELOG.md"), encoding="utf-8").read()


def test_an_already_applied_patch_is_detected_and_does_nothing_twice():
    if not AVAILABLE:
        return
    work, bare, log, env, dl = user_repo()
    cur = version(work)
    patch = make_patch(work, dl, "mintmail-9.9.9.patch", [("version", "9.9.9"), ("base", "9.9.9 %s" % cur), ("note", "Essai")])
    run(["--no-release"], work, env)
    head = sh("git rev-parse HEAD", work).stdout
    r = run([patch], work, env)
    assert "DÉJÀ appliqué" in r.stdout and sh("git rev-parse HEAD", work).stdout == head and sh("git status --short", work).stdout == ""




def test_a_failure_before_the_commit_rolls_everything_back():
    if not AVAILABLE:
        return
    work, bare, log, env, dl = user_repo()
    cur = version(work)
    make_patch(work, dl, "mintmail-same.patch", [("version", cur), ("base", cur), ("note", "Version identique : refusée par bump-version")])
    before = sh("git rev-parse HEAD", work).stdout
    r = run([], work, env, ok=False)
    assert "annulées" in r.stderr and sh("git status --short", work).stdout == "" and sh("git rev-parse HEAD", work).stdout == before
    assert not os.path.exists(os.path.join(work, "docs", "ESSAI.md")) and version(work) == cur            # le fichier créé par le correctif a disparu
    assert "Ligne ajoutée par le correctif" not in open(os.path.join(work, "docs", "RELEASING.md"), encoding="utf-8").read()


def test_a_patch_without_header_needs_version_and_note_and_then_works():
    if not AVAILABLE:
        return
    work, bare, log, env, dl = user_repo()
    patch = make_patch(work, dl, "mintmail-ancien.patch")
    r = run([patch], work, env, ok=False)
    assert "sans en-tête" in r.stderr or "pas d'en-tête" in r.stderr
    r = run([patch], work, env, ok=False, cwd=dl)
    run([patch, "--version", "9.9.9", "--note", "Essai sans en-tête", "--no-release"], work, env)
    assert version(work) == "9.9.9" and "Essai sans en-tête" in open(os.path.join(work, "CHANGELOG.md"), encoding="utf-8").read()
    run([patch, "--version", "9.9.10", "--note", "x"], work, env, ok=True)                                  # déjà appliqué : message, pas d'erreur


def test_declining_the_confirmation_commits_but_does_not_publish_and_a_failed_release_keeps_the_commit():
    if not AVAILABLE:
        return
    work, bare, log, env, dl = user_repo()
    cur = version(work)
    make_patch(work, dl, "mintmail-9.9.9.patch", [("version", "9.9.9"), ("base", cur), ("note", "Essai")])
    r = run([], work, env, input="n\n")
    assert "Non publié" in r.stdout and head_msg(work) == "MintMail 9.9.9" and sh("git tag", work).stdout.strip() == "" and not os.path.exists(log)
    work2, bare2, log2, env2, dl2 = user_repo()
    make_patch(work2, dl2, "mintmail-9.9.9.patch", [("version", "9.9.9"), ("base", version(work2)), ("note", "Essai")])
    r = sh(["sh", SCRIPT, "--repo", work2, "--yes"], os.path.dirname(work2), dict(env2, MINTMAIL_SIGNING_KEY="/nulle/part.key"), ok=False)      # clé de signature absente : la publication échoue
    assert "Votre code est enregistré" in r.stderr and head_msg(work2) == "MintMail 9.9.9" and sh("git status --short", work2).stdout == ""


def test_an_unreachable_remote_only_warns_and_help_and_bad_options_behave():
    if not AVAILABLE:
        return
    work, bare, log, env, dl = user_repo()
    cur = version(work)
    make_patch(work, dl, "mintmail-9.9.9.patch", [("version", "9.9.9"), ("base", cur), ("note", "Essai")])
    sh("git remote set-url origin /nulle/part.git", work)
    r = run(["--no-release"], work, env)
    assert "injoignable" in r.stdout and version(work) == "9.9.9"
    h = sh(["sh", SCRIPT, "--help"], work, env)
    assert "mintmail-maj.sh" in h.stdout and "--dry-run" in h.stdout and "set -u" not in h.stdout
    assert "Option inconnue" in sh(["sh", SCRIPT, "--nimportequoi"], work, env, ok=False).stderr
    assert "n'est pas votre dépôt" in sh(["sh", SCRIPT, "--repo", tempfile.mkdtemp()], work, env, ok=False).stderr


def test_the_update_script_is_executable_documented_and_shipped_in_the_repository():
    p = SCRIPT
    assert os.path.exists(p) and os.access(p, os.X_OK)
    assert "mintmail-maj.sh" in open(os.path.join(ROOT, "docs", "RELEASING.md"), encoding="utf-8").read()
    assert "# mintmail-patch" in open(p, encoding="utf-8").read()                                              # il documente le format d'en-tête qu'il lit


def test_modified_tracked_files_block_and_are_listed_and_a_remote_ahead_of_you_is_refused():
    if not AVAILABLE:
        return
    work, bare, log, env, dl = user_repo()
    cur = version(work)
    make_patch(work, dl, "mintmail-9.9.9.patch", [("version", "9.9.9"), ("base", cur), ("note", "Essai")])
    with open(os.path.join(work, "README.md"), "a", encoding="utf-8") as f:
        f.write("\nmodif locale non enregistrée\n")
    r = run([], work, env, ok=False)
    assert "SUIVIS" in r.stderr and "README.md" in r.stderr and version(work) == cur and not os.path.exists(os.path.join(work, "docs", "ESSAI.md"))      # le fichier fautif est NOMMÉ
    sh("git checkout -- README.md", work)
    other = tempfile.mkdtemp()
    subprocess.run(["git", "clone", "-q", "-b", "main", bare, other], check=True, capture_output=True)
    sh("git commit -q --allow-empty -m 'fait ailleurs' && git push -q origin HEAD:main", other)
    r = run([], work, env, ok=False)
    assert "GitHub contient des commits absents" in r.stderr and version(work) == cur and not os.path.exists(os.path.join(work, "docs", "ESSAI.md"))


def test_untracked_files_at_the_root_never_block_and_never_enter_the_commit_even_with_spaces_and_parentheses_in_the_name():
    if not AVAILABLE:
        return
    work, bare, log, env, dl = user_repo()
    cur = version(work)
    inside = make_patch(work, work, "mintmail-9.9.9 (1).patch", [("version", "9.9.9"), ("base", cur), ("note", "Essai")])     # le cas réel : téléchargé deux fois, déposé dans le dépôt
    shutil.copy(SCRIPT, os.path.join(work, "mintmail-maj.sh"))
    open(os.path.join(work, "notes.txt"), "w").write("à moi\n")
    r = run(["--yes"], work, env)
    assert "non suivi(s) à la racine" in r.stdout and "Publié : v9.9.9" in r.stdout, r.stdout[-500:]
    files = set(sh("git show --name-only --format= HEAD", work).stdout.split())
    assert files == {"VERSION", "mintmail/VERSION", "CHANGELOG.md", "docs/ESSAI.md", "docs/RELEASING.md"}, files          # SEULEMENT ce que le correctif touche
    assert os.path.exists(inside) and os.path.exists(os.path.join(work, "notes.txt"))                                  # rien n'est supprimé ni déplacé
    assert sorted(l[3:].strip('"') for l in sh("git status --short", work).stdout.splitlines()) == ["mintmail-9.9.9 (1).patch", "mintmail-maj.sh", "notes.txt"]
    assert sh("git tag", work).stdout.split() == ["v9.9.9"]


def test_an_untracked_file_inside_a_directory_shipped_in_the_package_is_refused_by_the_script_and_by_the_release():
    if not AVAILABLE:
        return
    work, bare, log, env, dl = user_repo()
    cur = version(work)
    make_patch(work, dl, "mintmail-9.9.9.patch", [("version", "9.9.9"), ("base", cur), ("note", "Essai")])
    open(os.path.join(work, "mintmail", "brouillon.py"), "w").write("print('pas à livrer')\n")
    r = run([], work, env, ok=False)
    assert "seraient livrés" in r.stderr and "mintmail/brouillon.py" in r.stderr and version(work) == cur and not os.path.exists(os.path.join(work, "docs", "ESSAI.md"))
    r = sh("tools/release.sh --dry-run --skip-tests", work, env, ok=False)
    assert "seraient livrés" in r.stdout and "mintmail/brouillon.py" in r.stdout
    os.unlink(os.path.join(work, "mintmail", "brouillon.py"))
    open(os.path.join(work, "racine-libre.txt"), "w").write("x\n")
    assert "[essai]" in sh("tools/release.sh --dry-run --skip-tests", work, env).stdout                               # à la racine : la publication passe


def test_among_matching_patches_the_highest_version_wins_not_the_newest_file():
    if not AVAILABLE:
        return
    work, bare, log, env, dl = user_repo()
    cur = version(work)
    make_patch(work, dl, "mintmail-9.9.10.patch", [("version", "9.9.10"), ("base", cur), ("note", "Le plus haut")])
    make_patch(work, dl, "mintmail-9.9.9.patch", [("version", "9.9.9"), ("base", cur), ("note", "Plus bas mais plus récent")])
    os.utime(os.path.join(dl, "mintmail-9.9.10.patch"), (1000, 1000))                                                  # le plus haut est aussi le plus ANCIEN fichier
    run(["--no-release"], work, env)
    assert version(work) == "9.9.10" and "Le plus haut" in open(os.path.join(work, "CHANGELOG.md"), encoding="utf-8").read()
