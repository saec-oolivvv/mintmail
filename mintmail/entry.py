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
from .i18n import tr

GUI_HELP = tr("""MintMail ne peut pas démarrer : %s

Causes habituelles :
  - le Python utilisé n'est pas celui du système (conda, pyenv, venv…) : lancez /usr/bin/mintmail ;
  - il manque un composant : sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1
  - pas de session graphique (DISPLAY / WAYLAND_DISPLAY).
Pour un rapport complet : /usr/bin/mintmail --diagnose
""")


def _qt_python() -> str:
    """Interpréteur d'un venv où MintMail ET PySide6 sont importables (voir qtsetup.candidates) ; « » si aucun."""
    from . import qtsetup
    for py in qtsetup.candidates():
        if os.access(py, os.X_OK) and os.path.realpath(py) != os.path.realpath(sys.executable) and qtsetup.works(py):
            return py
    return ""


def install_qt_cli() -> int:
    """mintmail --install-qt : installe PySide6 dans le venv privé de MintMail (sans droits administrateur), avec le détail à l'écran."""
    from . import qtsetup
    venv = qtsetup.user_venv()
    print(tr("Installation de l'interface Qt (PySide6) dans %s — quelques minutes, ~1 Go de téléchargement…") % venv)
    ok, detail = qtsetup.create_venv(venv)
    print(tr("Interface Qt installée : elle s'ouvrira au prochain démarrage de MintMail.") if ok else tr("Échec de l'installation de l'interface Qt : %s") % detail)
    return 0 if ok else 1


def _auto_install_qt_in_background() -> None:
    """PySide6 manque et aucun venv n'existe : on installe en arrière-plan (une tentative par jour), MintMail démarre tout de suite avec l'ancienne interface."""
    if os.environ.get("MINTMAIL_NO_AUTOINSTALL"):
        return
    import subprocess
    marker = Path(DATA_DIR) / "qt-install.attempt"
    try:
        if marker.exists() and time.time() - marker.stat().st_mtime < 86400:
            return
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(str(time.time()))
        subprocess.Popen([sys.executable, "-m", "mintmail", "--install-qt"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
        if shutil.which("notify-send"):
            subprocess.Popen(["notify-send", "-i", "mintmail", "MintMail", tr("Installation de l'interface Qt en arrière-plan : elle s'ouvrira au prochain démarrage.")],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


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
        found.append((app, tr("application locale"), ver))
    for p, what in ((home / ".local/bin/mintmail", tr("lanceur local")), (Path("/usr/local/bin/mintmail"), tr("lanceur système (/usr/local)"))):
        if p.exists() or p.is_symlink():
            found.append((p, what, _launcher_version(p) if "mintmail" in _head(p) else "?"))
    for p, what in ((home / ".local/share/applications/mintmail.desktop", tr("entrée de menu locale")),
                    (home / ".local/share/applications/me.saec.mintmail.desktop", tr("entrée de menu locale")),
                    (home / ".local/share/icons/hicolor/scalable/apps/mintmail.svg", tr("icône locale"))):
        if p.exists():
            found.append((p, what, ""))
    opt = Path("/opt/mintmail")
    if opt.is_dir():
        try:
            ver = (opt / "VERSION").read_text(encoding="utf-8").strip()
        except OSError:
            ver = "?"
        found.append((opt, tr("application système (/opt)"), ver))
    return found


def remove_local_install(argv=None) -> int:
    """Sans --yes : LISTE seulement ce qui masque le paquet (aucune modification). Avec --yes : met de côté, sans rien
    supprimer, les éléments de votre dossier personnel dans ~/mintmail-sauvegarde-<date>/ (réglages et courrier conservés)."""
    argv = list(argv if argv is not None else sys.argv)
    home = Path.home()
    items = local_installs()
    if not items:
        print(tr("Aucune installation de MintMail hors paquet .deb."))
        return 0
    print(tr("Installations de MintMail hors paquet .deb (le paquet installé est la version %s) :") % __version__)
    for p, what, ver in items:
        flag = ""
        if ver and ver != "?" and not ver.startswith("1."):
            flag = tr("   <-- version INCONNUE de ce paquet : peut-être votre propre version, ne la retirez pas sans vérifier")
        print("  - %-30s %s%s%s" % (what, p, ("  [version %s]" % ver) if ver else "", flag))
    mine = [(p, w, v) for p, w, v in items if str(p).startswith(str(home))]
    system = [(p, w, v) for p, w, v in items if not str(p).startswith(str(home))]
    if system:
        print(tr("\nÉléments système (ce programme n'y touche jamais) : retirez-les vous-même si besoin, par ex."))
        for p, _w, _v in system:
            print("    sudo mv %s %s.sauvegarde" % (p, p))
    if "--yes" not in argv:
        print(tr("\nRien n'a été modifié. Pour METTRE DE CÔTÉ (sans supprimer) les éléments de votre dossier personnel :"))
        print("    /usr/bin/mintmail --remove-local-install --yes")
        return 0
    dest = home / ("mintmail-sauvegarde-" + time.strftime("%Y%m%d-%H%M%S"))
    moved = []
    for p, what, ver in mine:
        if p.is_file() and p.suffix != ".svg" and "mintmail" not in _head(p):
            print(tr("Conservé (ne semble pas venir de MintMail) : %s") % p)
            continue
        try:
            dest.mkdir(exist_ok=True)
            target = dest / str(p.relative_to(home)).replace("/", "__")
            shutil.move(str(p), str(target))
            moved.append((p, target))
        except OSError as e:
            print(tr("Impossible de déplacer %s : %s") % (p, e))
    for p, t in moved:
        print(tr("Mis de côté : %s  ->  %s") % (p, t))
    print(tr("\nVos réglages (~/.config/mintmail) et votre courrier en cache n'ont pas été touchés."))
    if moved:
        print(tr("Pour tout restaurer, remettez les éléments de %s à leur place d'origine.") % dest)
        print(tr("Ouvrez un nouveau terminal (ou tapez : hash -r) puis lancez : mintmail"))
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
                print(tr("Impossible de déplacer %s : %s") % (src, e))
    for src, dst in moved:
        print(tr("Mis de côté : %s -> %s") % (src, dst.name))
    print(tr("Réglages et cache réinitialisés.") if moved else tr("Rien à réinitialiser."))
    return 0


def send_due() -> int:
    """Envoie les messages programmés (ou en attente après une coupure) dont l'heure est venue, SANS ouvrir l'interface.
    Appelé chaque minute par la minuterie systemd de l'utilisateur ; une réservation atomique évite tout double envoi
    si la fenêtre MintMail est ouverte en même temps."""
    from .backend import make_backend, is_retryable
    from .store import Cache, Config, harden_permissions
    harden_permissions()
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
                from . import sysdeps
                sysdeps.notify(tr("MintMail : envoi impossible"), "%s — %s" % (out.subject[:50], str(e)[:120]))
    print(tr("Envois différés : %d envoyé(s), %d abandonné(s).") % (sent, failed))
    return 0


def _init_language() -> str:
    """Choisit la langue AVANT toute chaîne affichée : réglage « Langue de l'interface », variable MINTMAIL_LANG, sinon langue du système."""
    import json
    from . import i18n
    try:
        with open(CONFIG_DIR / "config.json", encoding="utf-8") as f:
            value = json.load(f).get("ui_lang", "auto")
    except (OSError, ValueError, AttributeError):
        value = "auto"
    return i18n.init_from_config(value if isinstance(value, str) else "auto")


def check_update_cli(api=None, allow_loopback=False, out=print) -> int:
    """`mintmail --check-update` : cherche une mise à jour et dit EXACTEMENT où on en est, sans interface et sans rien installer.
    Code de sortie : 0 à jour, 10 mise à jour disponible, 1 erreur."""
    import time
    from . import updater
    from .store import Config
    from .update_text import explain
    cfg = Config()
    repo = cfg.get("update_repo") or updater.DEFAULT_REPO
    out("%s %s (%s)" % (APP_NAME, __version__, tr("version en cours d'exécution")))
    pend = updater.restart_pending()
    if pend:
        out(tr("Version installée sur le disque : %s — relancez MintMail pour l'utiliser.") % pend)
    out(tr("Dépôt consulté : %s") % repo)
    ok, why = updater.can_install()
    out(tr("Installation automatique : prête (clé de vérification présente).") if ok else
        tr("Installation automatique désactivée : %s Vous serez seulement informé des nouvelles versions.") % explain(why))
    stored = updater.update_from_dict(cfg.get("update_available"), __version__)
    until = float(cfg.get("update_snooze_until") or 0)
    if stored is None:
        banner = tr("aucune mise à jour mémorisée")
    elif cfg.get("update_snooze_version") == stored.version and time.time() < until:
        banner = tr("version %s mémorisée, repoussée jusqu'à %s") % (stored.version, time.strftime("%Y-%m-%d %H:%M", time.localtime(until)))
    else:
        banner = tr("version %s mémorisée : le bandeau s'affiche au lancement") % stored.version
    out(tr("Bandeau de mise à jour : %s") % banner)
    last = cfg.get("update_last_check", 0)
    if last:
        out(tr("Dernière vérification enregistrée : %s") % time.strftime("%Y-%m-%d %H:%M", time.localtime(last)))
    res = updater.check(repo, api=api or updater.API, allow_loopback=allow_loopback)
    if res.state == "available":
        out(tr("⬆ La version %s est disponible.") % res.update.version)
        out(tr("Nouveautés : %s") % updater.short_notes(res.update.notes) if updater.short_notes(res.update.notes) else tr("(pas de notes de version)"))
        out(tr("Page de la version : %s") % (res.update.page or "—"))
        out(tr("Signature publiée : %s") % (tr("oui") if res.update.sig_url else tr("NON (la version sera refusée)")))
        return 10
    if res.state == "uptodate":
        out(tr("MintMail est à jour (version %s).") % __version__)
        return 0
    out(tr("Erreur : %s") % explain(res.code) + " (%s)" % res.code)
    return 1


def check_pins_cli(test=True, out=print, cfg=None, factory=None) -> int:
    """`mintmail --check-pins` : pour chaque compte, dit si le serveur GARDE les épingles (étiquette Gmail ou mot-clé IMAP), par un essai réversible.
    --no-test : lecture seule. Code de sortie : 0 tout va bien, 1 un compte ne garde pas les épingles ou n'est pas joignable."""
    from .backend import PIN_LABEL, make_backend
    from .store import Config
    cfg = cfg or Config()
    accounts = [a for a in cfg["accounts"] if not a.get("demo")]
    if not accounts:
        out(tr("Aucun compte configuré : rien à vérifier."))
        return 1
    bad = 0
    for acc in accounts:
        out("")
        out("== %s" % (acc.get("email") or acc.get("id")))
        be = (factory or make_backend)(dict(acc), cfg)
        try:
            d = be.pin_diagnostic(test)
        finally:
            try:
                be.close()
            except Exception:
                pass
        if not d["connected"]:
            out(tr("Connexion impossible : %s") % (d["error"] or "?"))
            bad += 1
            continue
        out(tr("Connexion : OK"))
        if d["mode"] == "gmail":
            out(tr("Type de serveur : Gmail — l'épingle est l'étiquette « %s », visible dans Gmail (web et mobile).") % PIN_LABEL)
        else:
            out(tr("Type de serveur : IMAP standard — l'épingle est un mot-clé IMAP (invisible dans la plupart des messageries web, vu par vos autres postes MintMail)."))
        if d["count"] is not None:
            out(tr("Messages épinglés sur le serveur (boîte de réception) : %d") % d["count"])
        if d["tested"]:
            if d["supported"]:
                out(tr("Essai réversible sur le message le plus récent : RÉUSSI — ce serveur garde les épingles."))
            else:
                out(tr("Essai réversible sur le message le plus récent : ÉCHEC — ce serveur ne garde pas les épingles : elles restent sur chaque poste."))
                bad += 1
        elif test:
            out(tr("Aucun message dans la boîte de réception : essai impossible."))
        else:
            out(tr("Lecture seule : aucun essai effectué."))
        if d["error"]:
            out(tr("Remarque : %s") % d["error"])
    return 1 if bad else 0


def main(argv=None) -> int:
    argv = list(argv if argv is not None else sys.argv)
    _init_language()
    if "--help" in argv or "-h" in argv:
        from . import help_content as H
        from .store import CONFIG_DIR, DATA_DIR
        print(tr("MintMail %s — options :\n") % __version__)
        print(H.cli_text({"config": str(CONFIG_DIR), "data": str(DATA_DIR), "version": __version__}))
        print(tr("\nAide complète dans l'application : touche F1."))
        return 0
    if "--version" in argv:
        print("%s %s" % (APP_NAME, __version__))
        return 0
    if "--diagnose" in argv:
        from .diagnose import print_report
        return print_report()
    if "--remove-local-install" in argv:
        return remove_local_install(argv)
    if "--install-qt" in argv:
        return install_qt_cli()
    if "--reset" in argv:
        return reset_data()
    if "--send-due" in argv:
        return send_due()
    if "--check-update" in argv:
        return check_update_cli()
    if "--check-pins" in argv:
        return check_pins_cli(test="--no-test" not in argv)
    use_gtk = "--gtk" in argv or os.environ.get("MINTMAIL_UI") == "gtk"
    auto_qt = os.environ.get("MINTMAIL_UI", "auto") == "auto" and os.environ.get("MINTMAIL_NO_KEYRING") != "1"     # (les tests ne lancent jamais une vraie fenêtre)
    if not use_gtk and ("--qt" in argv or auto_qt):          # interface Qt : l'interface PAR DÉFAUT (la version GTK reste en secours : --gtk)
        try:
            from .qt.window import run as run_qt
        except ImportError as e:
            py = _qt_python()
            if py and not os.environ.get("MINTMAIL_REEXEC"):         # PySide6 est dans un venv (celui du paquet, ou celui de l'utilisateur) : on s'y relance
                os.environ["MINTMAIL_REEXEC"] = "1"
                os.execv(py, [py, "-m", "mintmail"] + [a for a in argv if a != "--gtk"])
            if "--qt" in argv:
                sys.stderr.write(tr("L'interface Qt demande PySide6 (pip install PySide6, ou le venv avec --system-site-packages) : %s") % e + "\n")
                return 1
            _auto_install_qt_in_background()
            sys.stderr.write(tr("Interface Qt indisponible (PySide6 absent) : l'ancienne interface GTK est utilisée à la place.") + "\n")
        else:
            return run_qt([a for a in argv if a not in ("--qt", "--gtk")])
    from .store import harden_permissions
    harden_permissions()                    # dossiers 0700 / fichiers 0600, même pour les anciennes installations
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
