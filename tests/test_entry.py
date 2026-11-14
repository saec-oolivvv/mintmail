"""Démarrage : message clair sans GTK, diagnostic sans secrets, mise de côté des données, nettoyage de l'ancienne installation."""
import json, os, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(args, env_extra=None, home=None):
    tmp = home or tempfile.mkdtemp()
    env = dict(os.environ, HOME=tmp, XDG_CONFIG_HOME=tmp + "/cfg", XDG_DATA_HOME=tmp + "/data", PYTHONPATH=ROOT)
    env.update(env_extra or {})
    r = subprocess.run([sys.executable, "-m", "mintmail"] + args, capture_output=True, text=True, cwd=ROOT, env=env, timeout=60)
    return r, tmp


def test_version_and_friendly_error_without_pyside():
    r, _ = run(["--version"])
    assert r.returncode == 0 and r.stdout.startswith("MintMail ")
    try:
        import PySide6  # noqa: F401
        return   # PySide6 présent sur cette machine : lancer sans option ouvrirait une vraie fenêtre, le test ne s'applique pas
    except ImportError:
        pass
    r, _ = run([], env_extra={"MINTMAIL_NO_AUTOINSTALL": "1"})
    assert r.returncode == 1 and "Traceback" not in r.stderr          # message clair, pas une trace brute
    assert "--install-qt" in r.stderr and "--diagnose" in r.stderr and "/usr/bin/mintmail" in r.stderr


def test_the_old_gtk_option_is_ignored_and_never_crashes():
    r, _ = run(["--gtk", "--version"])
    assert r.returncode == 0 and r.stdout.startswith("MintMail ")


def test_diagnose_reports_problems_without_leaking_secrets():
    tmp = tempfile.mkdtemp()
    os.makedirs(tmp + "/cfg/mintmail"); os.makedirs(tmp + "/data/mintmail")
    json.dump({"accounts": [{"id": "a1", "email": "secret.perso@exemple.be", "imap_host": "imap.exemple.be"}],
               "passwords": {"a1": "mot-de-passe-secret"}, "nvidia_api_key": "nvapi-secret"},
              open(tmp + "/cfg/mintmail/config.json", "w"))
    open(tmp + "/data/mintmail/cache.db", "wb").write(b"ceci n'est pas une base sqlite" * 50)       # base corrompue
    r, _ = run(["--diagnose"], home=tmp)
    out = r.stdout
    assert r.returncode == 0 and "Rapport MintMail" in out and "Interpréteur" in out and "Modules MintMail" in out
    assert "imap.exemple.be" in out and "cache.db illisible" in out                                # problème repéré
    for secret in ("secret.perso@exemple.be", "mot-de-passe-secret", "nvapi-secret"):
        assert secret not in out, secret
    assert os.path.exists(tmp + "/data/mintmail/diagnostic.txt")


def test_reset_sets_aside_without_deleting_and_remove_local_install():
    tmp = tempfile.mkdtemp()
    os.makedirs(tmp + "/cfg/mintmail"); os.makedirs(tmp + "/data/mintmail")
    open(tmp + "/cfg/mintmail/config.json", "w").write("{}")
    open(tmp + "/data/mintmail/cache.db", "wb").write(b"x")
    r, _ = run(["--reset"], home=tmp)
    assert r.returncode == 0 and not os.path.exists(tmp + "/cfg/mintmail/config.json")
    assert [f for f in os.listdir(tmp + "/cfg/mintmail") if f.startswith("config.json.bak-")]          # sauvegarde conservée
    assert [f for f in os.listdir(tmp + "/data/mintmail") if f.startswith("cache.db.bak-")]
    r2, _ = run(["--reset"], home=tmp)
    assert "Rien à réinitialiser" in r2.stdout


def test_diagnose_does_not_flag_usrmerge_symlinks_but_flags_real_shadowing():
    tmp = tempfile.mkdtemp()
    a, c = tmp + "/a", tmp + "/c"
    os.makedirs(a); os.makedirs(c)
    open(a + "/mintmail", "w").write("#!/bin/sh"); open(c + "/mintmail", "w").write("#!/bin/sh")
    os.symlink(a, tmp + "/b")                                              # comme /bin -> /usr/bin
    r, _ = run(["--diagnose"], env_extra={"PATH": "%s:%s/b:%s" % (a, tmp, os.environ["PATH"])})
    line = [l for l in r.stdout.splitlines() if l.startswith("Lanceurs")][0]
    assert line.count(tmp) == 1, line                                      # un seul lanceur compté
    r2, _ = run(["--diagnose"], env_extra={"PATH": "%s:%s:%s" % (c, a, os.environ["PATH"])})
    assert "passe avant" in r2.stdout                                      # un autre fichier devant : signalé


def test_remove_local_install_lists_first_then_sets_aside_never_deletes():
    tmp = tempfile.mkdtemp()
    app = tmp + "/.local/share/mintmail-app"
    os.makedirs(app + "/app"); os.makedirs(tmp + "/.local/bin"); os.makedirs(tmp + "/.config/mintmail")
    open(app + "/VERSION", "w").write("3.0.1\n")                                          # une version que ce paquet ne connaît pas
    launcher = tmp + "/.local/bin/mintmail"
    open(launcher, "w").write('#!/bin/sh\nexec env PYTHONPATH="%s/app${PYTHONPATH:+:$PYTHONPATH}" python3 -m mintmail "$@"\n' % app)
    open(tmp + "/.config/mintmail/config.json", "w").write("{}")
    # 1) sans --yes : liste, signale la version inconnue, ne modifie RIEN
    r, _ = run(["--remove-local-install"], home=tmp)
    assert "3.0.1" in r.stdout and "INCONNUE" in r.stdout and "Rien n'a été modifié" in r.stdout
    assert os.path.exists(launcher) and os.path.isdir(app)
    # 2) avec --yes : mis de côté (pas supprimé), réglages intacts
    r2, _ = run(["--remove-local-install", "--yes"], home=tmp)
    backups = [d for d in os.listdir(tmp) if d.startswith("mintmail-sauvegarde-")]
    assert len(backups) == 1 and not os.path.exists(launcher) and not os.path.exists(app)
    assert len(os.listdir(tmp + "/" + backups[0])) == 2 and os.path.exists(tmp + "/.config/mintmail/config.json")
    assert "hash -r" in r2.stdout
    # 3) un fichier qui n'est pas de MintMail n'est jamais déplacé
    open(launcher, "w").write("#!/bin/sh\necho script personnel\n")
    r3, _ = run(["--remove-local-install", "--yes"], home=tmp)
    assert os.path.exists(launcher) and "Conservé" in r3.stdout


def test_diagnose_shows_launcher_versions_without_running_them():
    tmp = tempfile.mkdtemp()
    app = tmp + "/.local/share/mintmail-app"
    os.makedirs(app + "/app"); os.makedirs(tmp + "/.local/bin")
    open(app + "/VERSION", "w").write("3.0.1\n")
    marker = tmp + "/EXECUTE"
    open(tmp + "/.local/bin/mintmail", "w").write('#!/bin/sh\ntouch %s\nexec env PYTHONPATH="%s/app" python3 -m mintmail\n' % (marker, app))
    os.chmod(tmp + "/.local/bin/mintmail", 0o755)
    r, _ = run(["--diagnose"], home=tmp, env_extra={"PATH": tmp + "/.local/bin:" + os.environ["PATH"]})
    assert "[3.0.1]" in r.stdout and "passe avant" in r.stdout and "met de côté au lieu de supprimer" in r.stdout
    assert not os.path.exists(marker)                                                      # le lanceur inconnu n'est jamais exécuté
