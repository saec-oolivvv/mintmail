"""Chaîne de publication signée : clés, version, signature, paquet, étiquette, Release (faux gh, faux dépôt distant). Exécutée dans le dépôt complet seulement."""
import os, shutil, stat, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
NEEDED = ("tools/release.sh", "tools/make-signing-key.sh", "tools/sign-release.sh", "tools/bump-version.sh", "tools/check-version.py", "packaging/build-deb.sh")
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
