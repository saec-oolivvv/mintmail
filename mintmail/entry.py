"""Point d'entrée sans GTK : options utilitaires et message clair si l'interface ne peut pas démarrer."""
import os
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


def remove_local_install() -> int:
    """Supprime l'ancienne installation par install.sh (~/.local) qui masquerait le paquet .deb. Garde réglages et mails."""
    home = Path.home()
    paths = [home / ".local/share/mintmail-app", home / ".local/bin/mintmail",
             home / ".local/share/applications/mintmail.desktop",
             home / ".local/share/icons/hicolor/scalable/apps/mintmail.svg"]
    done = []
    for p in paths:
        try:
            if p.is_dir():
                shutil.rmtree(p)
                done.append(str(p))
            elif p.exists() or p.is_symlink():
                p.unlink()
                done.append(str(p))
        except OSError as e:
            print("Impossible de supprimer %s : %s" % (p, e))
    print("Ancienne installation locale supprimée :" if done else "Aucune ancienne installation locale.")
    for d in done:
        print("  -", d)
    print("Vos réglages (~/.config/mintmail) et votre courrier en cache sont conservés.")
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


def main(argv=None) -> int:
    argv = list(argv if argv is not None else sys.argv)
    if "--version" in argv:
        print("%s %s" % (APP_NAME, __version__))
        return 0
    if "--diagnose" in argv:
        from .diagnose import print_report
        return print_report()
    if "--remove-local-install" in argv:
        return remove_local_install()
    if "--reset" in argv:
        return reset_data()
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
