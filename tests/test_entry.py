"""Démarrage : message clair sans GTK, diagnostic sans secrets, mise de côté des données, nettoyage de l'ancienne installation."""
import json, os, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(args, env_extra=None, home=None):
    tmp = home or tempfile.mkdtemp()
    env = dict(os.environ, HOME=tmp, XDG_CONFIG_HOME=tmp + "/cfg", XDG_DATA_HOME=tmp + "/data", PYTHONPATH=ROOT)
    env.update(env_extra or {})
    r = subprocess.run([sys.executable, "-m", "mintmail"] + args, capture_output=True, text=True, cwd=ROOT, env=env, timeout=60)
    return r, tmp


def test_version_and_friendly_error_without_gtk():
    r, _ = run(["--version"])
    assert r.returncode == 0 and r.stdout.startswith("MintMail ")
    try:
        import gi
        gi.require_version("Gtk", "3.0")
        return   # GTK présent sur cette machine : le test ne s'applique pas
    except (ImportError, ValueError):
        pass
    r, _ = run([])
    assert r.returncode == 1 and "Traceback" not in r.stderr          # message clair, pas une trace brute
    assert "apt install python3-gi" in r.stderr and "--diagnose" in r.stderr and "/usr/bin/mintmail" in r.stderr


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
    os.makedirs(tmp + "/.local/bin"); os.makedirs(tmp + "/.local/share/mintmail-app/app")
    open(tmp + "/.local/bin/mintmail", "w").write("#!/bin/sh")
    r3, _ = run(["--remove-local-install"], home=tmp)
    assert not os.path.exists(tmp + "/.local/bin/mintmail") and "conservés" in r3.stdout


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
