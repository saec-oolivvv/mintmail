"""Chaîne de publication signée : clés, version, signature, paquet, étiquette, Release (faux gh, faux dépôt distant). Exécutée dans le dépôt complet seulement."""
import os, shutil, stat, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
NEEDED = ("tools/release.sh", "tools/make-signing-key.sh", "tools/sign-release.sh", "tools/bump-version.sh", "tools/check-version.py", "packaging/build-deb.sh", "tools/backup-signing-key.sh", "tools/rotate-signing-key.sh")
AVAILABLE = all(os.path.exists(os.path.join(ROOT, n)) for n in NEEDED) and all(shutil.which(b) for b in ("git", "openssl", "dpkg-deb"))


def sh(cmd, cwd, env=None, ok=True, input=None):
    e = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t", MINTMAIL_LANG="fr")
    e.update(env or {})
    r = subprocess.run(cmd, cwd=cwd, env=e, capture_output=True, text=True, shell=isinstance(cmd, str), input=input, timeout=600)
    if ok is True:
        assert r.returncode == 0, "%s\n%s\n%s" % (cmd, r.stdout[-800:], r.stderr[-800:])
    elif ok is False:
        assert r.returncode != 0, "devait échouer : %s\n%s" % (cmd, r.stdout[-400:])
    return r


def make_repo():
    d = tempfile.mkdtemp()
    work = os.path.join(d, "repo")
    shutil.copytree(ROOT, work, ignore=shutil.ignore_patterns(".git", "dist", "__pycache__", "*.pyc", "build"))
    for stale in ("data/update-pubkey.pem",):
        if os.path.exists(os.path.join(work, stale)):
            os.unlink(os.path.join(work, stale))
    sh("git init -q -b main && git add -A && git commit -q -m base", work)
    bare = os.path.join(d, "origin.git")
    sh("git init -q --bare %s" % bare, d)
    sh("git remote add origin %s" % bare, work)
    fakebin = os.path.join(d, "bin")
    os.makedirs(fakebin)
    log = os.path.join(d, "gh.log")
    open(os.path.join(fakebin, "gh"), "w").write('#!/bin/sh\nprintf "%s\\n" "$*" >> ' + log + '\n')
    os.chmod(os.path.join(fakebin, "gh"), 0o755)
    keys = os.path.join(d, "keys")
    env = {"MINTMAIL_KEYDIR": keys, "MINTMAIL_SIGNING_KEY": os.path.join(keys, "signing.key"), "PATH": fakebin + ":" + os.environ["PATH"]}
    return work, bare, log, env


def test_signing_key_creation_never_overwrites_and_protects_the_private_key():
    if not AVAILABLE:
        return
    work, bare, log, env = make_repo()
    r = sh("tools/make-signing-key.sh --no-passphrase", work, env)
    key = os.path.join(env["MINTMAIL_KEYDIR"], "signing.key")
    assert os.path.exists(key) and stat.S_IMODE(os.stat(key).st_mode) == 0o600 and stat.S_IMODE(os.stat(env["MINTMAIL_KEYDIR"]).st_mode) == 0o700
    pub = open(os.path.join(work, "data", "update-pubkey.pem")).read()
    assert "BEGIN PUBLIC KEY" in pub and "PRIVATE" not in pub and "sauvegarde" in r.stdout.lower()
    before = open(key, "rb").read()
    r2 = sh("tools/make-signing-key.sh --no-passphrase", work, env, ok=False)
    assert open(key, "rb").read() == before and "JAMAIS" in r2.stdout                               # une clé existante n'est jamais écrasée
    assert "signing.key" in open(os.path.join(work, ".gitignore")).read() or "*.key" in open(os.path.join(work, ".gitignore")).read()
    pubder = subprocess.run(["openssl", "pkey", "-in", key, "-pubout"], capture_output=True, text=True).stdout
    assert pubder == pub                                                                              # la clé publique du dépôt correspond à la clé privée


def test_version_must_be_consistent_and_bumping_requires_a_real_changelog():
    if not AVAILABLE:
        return
    work, bare, log, env = make_repo()
    sh("python3 tools/check-version.py", work)
    cur = open(os.path.join(work, "VERSION")).read().strip()
    major, minor, patch = (int(x) for x in cur.split("."))
    new = "%d.%d.%d" % (major, minor + 1, 0)
    for bad in ("1.2", "v1.2.3", "1.2.3.4", "abc", ""):
        sh(["tools/bump-version.sh", bad], work, ok=False)
    sh(["tools/bump-version.sh", new], work)
    assert open(os.path.join(work, "VERSION")).read().strip() == new == open(os.path.join(work, "mintmail", "VERSION")).read().strip()
    r = sh("python3 tools/check-version.py", work, ok=False)
    assert "à compléter" in r.stdout                                                                  # impossible de publier avec un journal vide
    log_text = open(os.path.join(work, "CHANGELOG.md"), encoding="utf-8").read().replace("(à compléter)", "Nouvelle fonction de test")
    open(os.path.join(work, "CHANGELOG.md"), "w", encoding="utf-8").write(log_text)
    sh("python3 tools/check-version.py", work)
    sh(["tools/bump-version.sh", new], work, ok=False)                                                # section déjà présente
    open(os.path.join(work, "mintmail", "VERSION"), "w").write("0.0.1\n")
    assert "diffèrent" in sh("python3 tools/check-version.py", work, ok=False).stdout


def test_release_dry_run_builds_signs_and_embeds_the_public_key_and_refuses_unsafe_states():
    if not AVAILABLE:
        return
    work, bare, log, env = make_repo()
    r = sh("tools/release.sh --dry-run --skip-tests", work, env, ok=False)
    assert "update-pubkey.pem" in r.stdout                                                           # pas de clé publique : refus net
    sh("tools/make-signing-key.sh --no-passphrase", work, env)
    r = sh("tools/release.sh --dry-run --skip-tests", work, env, ok=False)
    assert "enregistrée dans git" in r.stdout                                                        # la clé publique doit être versionnée
    sh("git add -A && git commit -q -m 'Clé publique de signature des mises à jour'", work)
    version = open(os.path.join(work, "VERSION")).read().strip()
    r = sh("tools/release.sh --dry-run --skip-tests", work, env)
    assert "[essai]" in r.stdout and sh("git tag", work).stdout.strip() == "" and not os.path.exists(log)       # essai : ni étiquette ni Release
    deb = os.path.join(work, "dist", "mintmail_%s_all.deb" % version)
    sig, sums = deb + ".sig", os.path.join(work, "dist", "SHA256SUMS")
    assert os.path.exists(deb) and os.path.exists(sig) and os.path.exists(sums)
    pub = os.path.join(work, "data", "update-pubkey.pem")
    v = subprocess.run(["openssl", "dgst", "-sha256", "-verify", pub, "-signature", sig, deb], capture_output=True, text=True)
    assert v.returncode == 0 and "Verified OK" in v.stdout
    assert subprocess.run("sha256sum -c SHA256SUMS", shell=True, cwd=os.path.join(work, "dist"), capture_output=True).returncode == 0
    emb = subprocess.run("dpkg-deb --fsys-tarfile %s | tar -xO ./usr/share/mintmail/update-pubkey.pem" % deb, shell=True, capture_output=True, text=True).stdout
    assert emb == open(pub).read()                                                                    # le paquet contient exactement la clé publique du dépôt
    listing = subprocess.run(["dpkg-deb", "-c", deb], capture_output=True, text=True).stdout
    for needle in ("./usr/lib/mintmail/apply-update", "./usr/share/polkit-1/actions/me.saec.mintmail.update.policy", "./usr/share/mintmail/update-pubkey.pem"):
        assert needle in listing, needle
    line = [l for l in listing.splitlines() if l.endswith("./usr/lib/mintmail/apply-update")][0]
    assert line.startswith("-rwxr-xr-x root/root") and [l for l in listing.splitlines() if l.endswith("update-pubkey.pem")][0].startswith("-rw-r--r-- root/root")
    ctrl = subprocess.run(["dpkg-deb", "--field", deb, "Depends", "Recommends"], capture_output=True, text=True).stdout
    assert "openssl" in ctrl and ("pkexec" in ctrl or "policykit" in ctrl)
    # un paquet signé avec une AUTRE clé privée est refusé par sign-release
    other = os.path.join(os.path.dirname(env["MINTMAIL_KEYDIR"]), "autre.key")
    subprocess.run(["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048", "-out", other], check=True, capture_output=True)
    os.unlink(sig)
    r = sh(["tools/sign-release.sh", deb, other], work, env, ok=False)
    assert "ne correspond PAS" in r.stdout and not os.path.exists(sig)
    # états dangereux
    sh("echo x >> README.md", work)
    assert "modifications non enregistrées" in sh("tools/release.sh --dry-run --skip-tests", work, env, ok=False).stdout
    sh("git checkout README.md", work)
    assert "introuvable" in sh("tools/release.sh --dry-run --skip-tests", work, dict(env, MINTMAIL_SIGNING_KEY="/nulle/part.key"), ok=False).stdout
    sh("git tag v%s" % version, work)
    assert "existe déjà" in sh("tools/release.sh --dry-run --skip-tests", work, env, ok=False).stdout


def test_real_release_tags_pushes_and_creates_a_github_release_with_signed_assets():
    if not AVAILABLE:
        return
    work, bare, log, env = make_repo()
    sh("tools/make-signing-key.sh --no-passphrase", work, env)
    sh("git add -A && git commit -q -m clé", work)
    version = open(os.path.join(work, "VERSION")).read().strip()
    sh("tools/release.sh --skip-tests", work, env)
    assert sh("git tag", work).stdout.split() == ["v" + version]
    assert subprocess.run(["git", "--git-dir", bare, "tag"], capture_output=True, text=True).stdout.split() == ["v" + version]       # étiquette poussée
    text = open(log, encoding="utf-8").read()                                                                                       # les notes de version contiennent des retours à la ligne
    assert text.count("release create ") == 1 and text.startswith("release create v%s " % version), text[:200]
    head = text.split("--notes")[0]
    assert "mintmail_%s_all.deb" % version in head and ".deb.sig" in head and "SHA256SUMS" in head                                   # les 3 fichiers attendus par MintMail
    import re
    section = re.search(r"^## %s\s*\n((?:- .+\n)+)" % re.escape(version), open(os.path.join(work, "CHANGELOG.md"), encoding="utf-8").read(), re.M).group(1)
    first_bullet = section.splitlines()[0][2:40]
    assert "--title MintMail %s" % version in head and first_bullet in text.split("--notes", 1)[1]                                   # notes = section du CHANGELOG de CETTE version
    sh("tools/release.sh --skip-tests", work, env, ok=False)                                                                         # on ne republie pas la même version


def _verifies(pub_pem, sig, deb):
    return subprocess.run(["openssl", "dgst", "-sha256", "-verify", pub_pem, "-signature", sig, deb], capture_output=True, text=True).returncode == 0


def _bump(work, version, note="Essai"):
    sh(["tools/bump-version.sh", version], work)
    p = os.path.join(work, "CHANGELOG.md")
    t = open(p, encoding="utf-8").read().replace("- (à compléter)", "- " + note, 1)
    open(p, "w", encoding="utf-8").write(t)
    sh("git add -A && git commit -q -m 'MintMail %s'" % version, work)


def test_key_backup_makes_a_verified_copy_refuses_the_repository_and_never_prints_the_key():
    if not AVAILABLE:
        return
    import glob, re
    work, bare, log, env = make_repo()
    dest = tempfile.mkdtemp()
    assert "introuvable" in sh(["tools/backup-signing-key.sh", dest], work, env, ok=False).stdout                     # pas de clé : rien à sauvegarder
    sh("tools/make-signing-key.sh --no-passphrase", work, env)
    keydir = env["MINTMAIL_KEYDIR"]
    key = os.path.join(keydir, "signing.key")
    r = sh(["tools/backup-signing-key.sh", dest, "--verify"], work, env)
    (out,) = glob.glob(os.path.join(dest, "mintmail-signing-backup-*"))
    assert open(os.path.join(out, "signing.key"), "rb").read() == open(key, "rb").read() and stat.S_IMODE(os.stat(os.path.join(out, "signing.key")).st_mode) == 0o600
    assert subprocess.run("sha256sum -c SHA256SUMS", shell=True, cwd=out, capture_output=True).returncode == 0
    assert "Contrôle fonctionnel" in r.stdout and "Sauvegarde créée" in r.stdout
    fp = re.search(r"^\s+([0-9a-f]{64})$", r.stdout, re.M).group(1)
    der = subprocess.run(["openssl", "pkey", "-pubin", "-in", os.path.join(work, "data", "update-pubkey.pem"), "-outform", "DER"], capture_output=True).stdout
    assert fp == __import__("hashlib").sha256(der).hexdigest()                                                           # empreinte = celle de la clé publique du dépôt
    body = "".join(l for l in open(key).read().splitlines() if "-----" not in l)
    assert "PRIVATE KEY" not in r.stdout + r.stderr and body[:40] not in r.stdout + r.stderr                            # la clé n'est jamais affichée
    inside = os.path.join(work, "sauvegarde")
    os.makedirs(inside)
    r = sh(["tools/backup-signing-key.sh", inside], work, env, ok=False)
    assert "dépôt git" in r.stdout and os.listdir(inside) == []                                                        # jamais la clé privée dans le dépôt
    assert "dépôt git" in sh(["tools/backup-signing-key.sh", work], work, env, ok=False).stdout
    assert "elle-même" in sh(["tools/backup-signing-key.sh", keydir], work, env, ok=False).stdout
    sh(["tools/backup-signing-key.sh", "/nulle/part"], work, env, ok=False)
    good = open(key, "rb").read()
    open(key, "w").write("n'importe quoi")                                                                              # fichier qui n'est pas une clé : la sauvegarde est refusée
    assert "pas une clé privée" in sh(["tools/backup-signing-key.sh", tempfile.mkdtemp()], work, env, ok=False).stdout
    open(key, "wb").write(good)


def test_planned_key_rotation_old_key_signs_the_bridge_release_then_the_new_key_takes_over():
    if not AVAILABLE:
        return
    import glob
    work, bare, log, env = make_repo()
    keydir = env["MINTMAIL_KEYDIR"]
    old_key, tmpd = os.path.join(keydir, "signing.key"), os.path.dirname(keydir)
    sh("tools/make-signing-key.sh --no-passphrase", work, env)
    sh("git add -A && git commit -q -m clé", work)
    pubfile = os.path.join(work, "data", "update-pubkey.pem")
    old_pub = open(pubfile).read()
    old_bytes = open(old_key, "rb").read()
    sh("tools/rotate-signing-key.sh --no-passphrase", work, env)
    new_pub = open(pubfile).read()
    assert new_pub != old_pub and open(old_key, "rb").read() == old_bytes                                              # l'ancienne clé n'est pas touchée
    assert open(os.path.join(keydir, "previous-pubkey.pem")).read() == old_pub and os.path.exists(os.path.join(keydir, "next", "signing.key"))
    assert stat.S_IMODE(os.stat(os.path.join(keydir, "next", "signing.key")).st_mode) == 0o600
    assert "déjà préparée" in sh("tools/rotate-signing-key.sh --no-passphrase", work, env, ok=False).stdout           # jamais d'écrasement
    sh("git add -A && git commit -q -m rotation", work)
    _bump(work, "9.9.9")
    r = sh("tools/release.sh --dry-run --skip-tests", work, env, ok=False)
    assert "ne correspond PAS" in r.stdout                                                                               # sans --rotation, l'ancienne clé ne signe plus un dépôt qui porte la nouvelle
    assert "Rotation : indiquez" in sh("tools/release.sh --dry-run --skip-tests --rotation", work, env, ok=False).stdout
    prev = os.path.join(keydir, "previous-pubkey.pem")
    assert "--rotation" in sh("tools/release.sh --dry-run --skip-tests", work, dict(env, MINTMAIL_VERIFY_PUBKEY=prev), ok=False).stdout
    assert "pas une rotation" in sh("tools/release.sh --dry-run --skip-tests --rotation", work, dict(env, MINTMAIL_VERIFY_PUBKEY=pubfile), ok=False).stdout
    r = sh("tools/release.sh --skip-tests --rotation", work, dict(env, MINTMAIL_SIGNING_KEY=old_key, MINTMAIL_VERIFY_PUBKEY=prev))
    assert "ROTATION" in r.stdout and "Publié" in r.stdout and "Rotation de la clé de signature" in open(log, encoding="utf-8").read()
    deb = os.path.join(work, "dist", "mintmail_9.9.9_all.deb")
    sig = deb + ".sig"
    embedded = os.path.join(tmpd, "embedded.pem")
    open(embedded, "w").write(subprocess.run("dpkg-deb --fsys-tarfile %s | tar -xO ./usr/share/mintmail/update-pubkey.pem" % deb, shell=True, capture_output=True, text=True).stdout)
    assert open(embedded).read() == new_pub                                                                              # le paquet de transition porte la NOUVELLE clé publique
    assert _verifies(prev, sig, deb) and not _verifies(pubfile, sig, deb)                                               # …mais est signé avec l'ANCIENNE : les machines installées l'acceptent
    sh("tools/rotate-signing-key.sh --finish", work, env)
    (retired,) = glob.glob(os.path.join(keydir, "retired-*"))
    assert open(os.path.join(retired, "signing.key"), "rb").read() == old_bytes and not os.path.exists(os.path.join(keydir, "next"))
    derived = subprocess.run(["openssl", "pkey", "-in", old_key, "-pubout"], capture_output=True, text=True).stdout
    assert derived == new_pub                                                                                            # la clé courante est maintenant la nouvelle
    assert "Aucune rotation" in sh("tools/rotate-signing-key.sh --finish", work, env, ok=False).stdout
    _bump(work, "9.9.10")
    sh("tools/release.sh --skip-tests", work, env)                                                                       # la version suivante se signe normalement, avec la nouvelle clé
    deb2 = os.path.join(work, "dist", "mintmail_9.9.10_all.deb")
    assert _verifies(embedded, deb2 + ".sig", deb2) and not _verifies(prev, deb2 + ".sig", deb2)                         # vérifiable avec la clé que la machine tient désormais du paquet de transition


def test_the_key_recovery_guide_names_only_tools_and_options_that_exist():
    doc = open(os.path.join(ROOT, "docs", "KEY-RECOVERY.md"), encoding="utf-8").read()
    for tool in ("tools/backup-signing-key.sh", "tools/rotate-signing-key.sh", "tools/release.sh --rotation", "tools/make-signing-key.sh", "tools/bump-version.sh", "--finish", "--verify"):
        assert tool in doc, tool
    for f in ("tools/backup-signing-key.sh", "tools/rotate-signing-key.sh", "tools/review_translations.py"):
        assert os.path.exists(os.path.join(ROOT, f)) and os.access(os.path.join(ROOT, f), os.X_OK), f              # présents ET exécutables
    assert "KEY-RECOVERY.md" in open(os.path.join(ROOT, "SECURITY.md"), encoding="utf-8").read() and "KEY-RECOVERY.md" in open(os.path.join(ROOT, "docs", "RELEASING.md"), encoding="utf-8").read()
    assert "review_translations.py" in open(os.path.join(ROOT, "docs", "I18N.md"), encoding="utf-8").read()
