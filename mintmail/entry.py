"""Point d'entrée sans GTK : options utilitaires et message clair si l'interface ne peut pas démarrer."""
import os
import re
import shutil
import sys
import time
from pathlib import Path

from . import APP_NAME, __version__
from .log import install_hook, log, log_exception
from .store import CONFIG_DIR, DATA_DIR

GUI_HELP = """MintMail ne peut pas démarrer : %s

Causes habituelles :
  - le Python utilisé n'est pas celui du système (conda, pyenv, venv…) : lancez /usr/bin/mintmail ;
  - il manque un composant : sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1
  - pas de session graphique (DISPLAY / WAYLAND_DISPLAY).
Pour un rapport complet : /usr/bin/mintmail --diagnose
"""


def _head(path: Path, n: int = 4096) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:n]
    except OSError:
        return ""


def _launcher_version(path: Path) -> str:
    """Version d'un lanceur d'une installation locale/système, SANS l'exécuter (lit le fichier VERSION à côté de l'appli)."""
    m = re.search(r'PYTHONPATH="([^"$:]+)', _head(path))
    if m:
        v = Path(m.group(1)).parent / "VERSION"
        try:
            return v.read_text(encoding="utf-8").strip()
        except OSError:
            pass
    return "?"


def local_installs():
    """Installations de MintMail hors paquet .deb : [(chemin, description, version)] — rien n'est modifié."""
    home = Path.home()
    found = []
    app = home / ".local/share/mintmail-app"
    if app.is_dir():
        try:
            ver = (app / "VERSION").read_text(encoding="utf-8").strip()
        except OSError:
            ver = "?"
        found.append((app, "application locale", ver))
    for p, what in ((home / ".local/bin/mintmail", "lanceur local"), (Path("/usr/local/bin/mintmail"), "lanceur système (/usr/local)")):
        if p.exists() or p.is_symlink():
            found.append((p, what, _launcher_version(p) if "mintmail" in _head(p) else "?"))
    for p, what in ((home / ".local/share/applications/mintmail.desktop", "entrée de menu locale"),
                    (home / ".local/share/applications/me.saec.mintmail.desktop", "entrée de menu locale"),
                    (home / ".local/share/icons/hicolor/scalable/apps/mintmail.svg", "icône locale")):
        if p.exists():
            found.append((p, what, ""))
    opt = Path("/opt/mintmail")
    if opt.is_dir():
        try:
            ver = (opt / "VERSION").read_text(encoding="utf-8").strip()
        except OSError:
            ver = "?"
        found.append((opt, "application système (/opt)", ver))
    return found


def remove_local_install(argv=None) -> int:
    """Sans --yes : LISTE seulement ce qui masque le paquet (aucune modification). Avec --yes : met de côté, sans rien
    supprimer, les éléments de votre dossier personnel dans ~/mintmail-sauvegarde-<date>/ (réglages et courrier conservés)."""
    argv = list(argv if argv is not None else sys.argv)
    home = Path.home()
    items = local_installs()
    if not items:
        print("Aucune installation de MintMail hors paquet .deb.")
        return 0
    print("Installations de MintMail hors paquet .deb (le paquet installé est la version %s) :" % __version__)
    for p, what, ver in items:
        flag = ""
        if ver and ver != "?" and not ver.startswith("1."):
            flag = "   <-- version INCONNUE de ce paquet : peut-être votre propre version, ne la retirez pas sans vérifier"
        print("  - %-30s %s%s%s" % (what, p, ("  [version %s]" % ver) if ver else "", flag))
    mine = [(p, w, v) for p, w, v in items if str(p).startswith(str(home))]
    system = [(p, w, v) for p, w, v in items if not str(p).startswith(str(home))]
    if system:
        print("\nÉléments système (ce programme n'y touche jamais) : retirez-les vous-même si besoin, par ex.")
        for p, _w, _v in system:
            print("    sudo mv %s %s.sauvegarde" % (p, p))
    if "--yes" not in argv:
        print("\nRien n'a été modifié. Pour METTRE DE CÔTÉ (sans supprimer) les éléments de votre dossier personnel :")
        print("    /usr/bin/mintmail --remove-local-install --yes")
        return 0
    dest = home / ("mintmail-sauvegarde-" + time.strftime("%Y%m%d-%H%M%S"))
    moved = []
    for p, what, ver in mine:
        if p.is_file() and p.suffix != ".svg" and "mintmail" not in _head(p):
            print("Conservé (ne semble pas venir de MintMail) : %s" % p)
            continue
        try:
            dest.mkdir(exist_ok=True)
            target = dest / str(p.relative_to(home)).replace("/", "__")
            shutil.move(str(p), str(target))
            moved.append((p, target))
        except OSError as e:
            print("Impossible de déplacer %s : %s" % (p, e))
    for p, t in moved:
        print("Mis de côté : %s  ->  %s" % (p, t))
    print("\nVos réglages (~/.config/mintmail) et votre courrier en cache n'ont pas été touchés.")
    if moved:
        print("Pour tout restaurer, remettez les éléments de %s à leur place d'origine." % dest)
        print("Ouvrez un nouveau terminal (ou tapez : hash -r) puis lancez : mintmail")
    return 0


def reset_data() -> int:
    """Met de côté (sans rien supprimer) la configuration et le cache : MintMail repart propre ; les mots de passe du
    trousseau et le courrier sur les serveurs ne sont pas touchés. Avec la synchro, les comptes reviennent seuls."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    moved = []
    for src in (CONFIG_DIR / "config.json", DATA_DIR / "cache.db", DATA_DIR / "cache.db-wal", DATA_DIR / "cache.db-shm"):
        if src.exists():
            dst = src.with_name(src.name + ".bak-" + stamp)
            try:
                os.replace(src, dst)
                moved.append((src, dst))
            except OSError as e:
                print("Impossible de déplacer %s : %s" % (src, e))
    for src, dst in moved:
        print("Mis de côté : %s -> %s" % (src, dst.name))
    print("Réglages et cache réinitialisés." if moved else "Rien à réinitialiser.")
    return 0


def send_due() -> int:
    """Envoie les messages programmés (ou en attente après une coupure) dont l'heure est venue, SANS ouvrir l'interface.
    Appelé chaque minute par la minuterie systemd de l'utilisateur ; une réservation atomique évite tout double envoi
    si la fenêtre MintMail est ouverte en même temps."""
    from .backend import make_backend, is_retryable
    from .store import Cache, Config
    cache = Cache()
    due = cache.outbox_due()
    if not due:
        return 0
    cfg = Config()
    sent = failed = 0
    for oid, out in due:
        if not cache.outbox_claim(oid):
            continue
        acc = next((a for a in cfg["accounts"] if a["id"] == out.account), None)
        if acc is None or acc.get("demo"):
            cache.outbox_remove(oid)
            continue
        try:
            make_backend(acc, cfg).send(out)
            cache.outbox_remove(oid)
            sent += 1
        except Exception as e:
            if is_retryable(e) and cache.outbox_tries(oid) < 10:
                cache.outbox_reschedule(oid, time.time() + 120)           # réseau absent : on réessaie plus tard
            else:
                cache.outbox_remove(oid)
                failed += 1
                log("Envoi différé abandonné (%s) : %s" % (out.subject[:40], e))
                try:
                    import subprocess
                    subprocess.run(["notify-send", "MintMail : envoi impossible", "%s — %s" % (out.subject[:50], str(e)[:120])], timeout=5)
                except Exception:
                    pass
    print("Envois différés : %d envoyé(s), %d abandonné(s)." % (sent, failed))
    return 0


def main(argv=None) -> int:
    argv = list(argv if argv is not None else sys.argv)
    if "--version" in argv:
        print("%s %s" % (APP_NAME, __version__))
        return 0
    if "--diagnose" in argv:
        from .diagnose import print_report
        return print_report()
    if "--remove-local-install" in argv:
        return remove_local_install(argv)
    if "--reset" in argv:
        return reset_data()
    if "--send-due" in argv:
        return send_due()
    install_hook()
    log("Démarrage MintMail %s (%s)" % (__version__, sys.executable))
    try:
        from .app import run
    except (ImportError, ValueError) as e:
        log_exception("import de l'interface")
        sys.stderr.write(GUI_HELP % e + "\n")
        return 1
    return run([a for a in argv if a not in ("--settings", "--window")], settings="--settings" in argv,
               window="--window" in argv)
