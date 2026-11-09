"""Rapport de diagnostic (sans GTK, sans secrets) : à lancer avec « mintmail --diagnose » quand quelque chose ne démarre pas."""
import importlib
import json
import os
import platform
import sqlite3
import subprocess
import sys
import threading
import time

from . import __version__
from .store import CONFIG_DIR, DATA_DIR

MODULES = ("models", "util", "store", "backend", "syncdata", "p2p", "ai_service", "ai_engine", "style", "widgets",
           "reader", "compose", "settings_extra", "settings", "assistant", "listing", "folders", "ai_features", "window", "app")


def _run(cmd, timeout=5):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (r.stdout or r.stderr).strip()
    except Exception as e:
        return "indisponible (%s)" % type(e).__name__


def _os_name():
    try:
        for line in open("/etc/os-release", encoding="utf-8"):
            if line.startswith("PRETTY_NAME="):
                return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return platform.platform()


def _keyring_name():
    box = {}

    def run():
        try:
            import keyring
            box["v"] = str(keyring.get_keyring())
        except Exception as e:
            box["v"] = "indisponible (%s)" % type(e).__name__
    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(4)
    return box.get("v", "ne répond pas (trousseau verrouillé ?)")


def build_report() -> str:
    L = []
    add = L.append
    ok = lambda b: "OK " if b else "KO "
    add("=== Rapport MintMail %s — %s ===" % (__version__, time.strftime("%Y-%m-%d %H:%M:%S")))
    add("Système     : %s" % _os_name())
    add("Python      : %s" % sys.version.split()[0])
    add("Interpréteur: %s%s" % (sys.executable, "" if sys.executable == "/usr/bin/python3" else
                                "   <-- PAS le Python du système : python3-gi n'y est peut-être pas visible"))
    add("Paquet      : %s" % os.path.dirname(os.path.abspath(__file__)))
    add("Version dpkg: %s" % (_run(["dpkg-query", "-W", "-f=${Version}", "mintmail"]) or "non installé par dpkg"))
    shadows, seen = [], set()
    for d in os.environ.get("PATH", "").split(":"):
        p = os.path.join(d, "mintmail") if d else ""
        if p and os.path.exists(p) and os.path.realpath(p) not in seen:   # /bin est un lien vers /usr/bin : même fichier
            seen.add(os.path.realpath(p))
            shadows.append(p)
    from .entry import _launcher_version
    detail = []
    for sp in shadows:
        v = _launcher_version(__import__("pathlib").Path(sp)) if os.path.realpath(sp) != os.path.realpath("/usr/bin/mintmail") else __version__
        detail.append("%s [%s]" % (sp, v))
    add("Lanceurs    : %s" % (", ".join(detail) or "aucun dans le PATH"))
    if shadows and os.path.realpath(shadows[0]) != os.path.realpath("/usr/bin/mintmail"):
        add("               ^ ce lanceur passe avant /usr/bin/mintmail. Lancez « /usr/bin/mintmail --remove-local-install »")
        add("                 (il LISTE d'abord, ne modifie rien sans --yes, et met de côté au lieu de supprimer)")
    add("Session     : %s  DISPLAY=%s  WAYLAND_DISPLAY=%s" % (os.environ.get("XDG_SESSION_TYPE", "?"),
                                                             os.environ.get("DISPLAY", "-"), os.environ.get("WAYLAND_DISPLAY", "-")))
    add("")
    add("--- GTK / WebKit ---")
    try:
        import gi
        add(ok(True) + "PyGObject %s" % getattr(gi, "__version__", "?"))
        for ns, vers in (("Gtk", ("3.0",)), ("Gdk", ("3.0",)), ("Pango", ("1.0",)), ("Gio", ("2.0",)), ("WebKit2", ("4.1", "4.0"))):
            found = None
            for v in vers:
                try:
                    gi.require_version(ns, v)
                    found = v
                    break
                except ValueError:
                    continue
            add("%s%s %s" % (ok(found), ns, found or ("introuvable (paquet : %s)" % (
                "gir1.2-webkit2-4.1" if ns == "WebKit2" else "gir1.2-gtk-3.0"))))
        try:
            from gi.repository import Gtk
            add(ok(True) + "GTK %d.%d.%d" % (Gtk.get_major_version(), Gtk.get_minor_version(), Gtk.get_micro_version()))
        except Exception as e:
            add(ok(False) + "GTK non chargeable : %s" % e)
    except ImportError as e:
        add(ok(False) + "PyGObject (module gi) absent pour cet interpréteur : %s" % e)
        add("               -> sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1")
    add("Trousseau   : %s" % _keyring_name())
    try:
        _cfgd = json.loads((CONFIG_DIR / "config.json").read_text(encoding="utf-8")) if (CONFIG_DIR / "config.json").exists() else {}
        n_clear = len(_cfgd.get("passwords") or {}) + (1 if _cfgd.get("nvidia_api_key") else 0)
        add("%sSecrets     : %s" % ("KO  " if n_clear else "OK  ", "%d mot(s) de passe / clé(s) en CLAIR dans config.json (0600) faute de trousseau : installez "
            "python3-keyring + un trousseau (gnome-keyring) puis réenregistrez vos comptes" % n_clear if n_clear else "aucun secret en clair dans config.json"))
        from .store import DATA_DIR as _D
        wide = [p for p in (CONFIG_DIR, _D, CONFIG_DIR / "config.json", _D / "cache.db") if p.exists() and p.stat().st_mode & 0o077]
        add("%sPermissions : %s" % ("KO  " if wide else "OK  ", ("lisibles par d'autres comptes : %s (corrigé au prochain démarrage)" % ", ".join(map(str, wide))) if wide else "réglages et courrier en cache réservés à votre compte"))
    except Exception as e:
        add("Secrets / permissions : vérification impossible (%s)" % type(e).__name__)
    add("")
    add("--- Modules MintMail ---")
    bad = 0
    for name in MODULES:
        try:
            importlib.import_module("mintmail." + name)
        except Exception as e:
            bad += 1
            add("KO  %s : %s: %s" % (name, type(e).__name__, str(e)[:160]))
    add("%s%d module(s) chargés sur %d" % (ok(not bad), len(MODULES) - bad, len(MODULES)))
    add("")
    add("--- Synchronisation entre machines ---")
    try:
        from . import netutil
        cfgd = json.loads((CONFIG_DIR / "config.json").read_text(encoding="utf-8")) if (CONFIG_DIR / "config.json").exists() else {}
        code = str(cfgd.get("p2p_secret") or "")
        from .store import P2P_MIN_SECRET
        add("%ssynchro activée : %s ; code : %d caractère(s) (%d minimum)%s" % (
            ok(bool(cfgd.get("p2p_enabled")) and len(code) >= P2P_MIN_SECRET), bool(cfgd.get("p2p_enabled")), len(code), P2P_MIN_SECRET,
            "" if len(code) >= P2P_MIN_SECRET or not code else "   <-- trop court : synchro désactivée, générer un nouveau code"))
        ifs = netutil.interfaces()
        add("Interfaces  : %s" % ("; ".join("%s %s/%d" % (i["if"], i["ip"], i["prefix"]) for i in ifs) or "aucune (réseau déconnecté ?)"))
        add("Diffusions  : %s" % ", ".join(netutil.broadcast_targets()))
        import socket as _s
        for kind, port, typ in (("UDP", cfgd.get("p2p_disc_port", 54321), _s.SOCK_DGRAM), ("TCP", cfgd.get("p2p_port", 54322), _s.SOCK_STREAM)):
            sk = _s.socket(_s.AF_INET, typ)
            sk.setsockopt(_s.SOL_SOCKET, _s.SO_REUSEADDR, 1)
            try:
                sk.bind(("", int(port)))
                add("%sport %s %s libre en local" % (ok(True), kind, port))
            except OSError as e:
                add("%sport %s %s : %s (MintMail déjà ouvert ? autre programme ?)" % (ok(False), kind, port, e.strerror))
            finally:
                sk.close()
        add("Pairs fixes : %s" % (cfgd.get("p2p_static_peers") or "aucun"))
    except Exception as e:
        add("KO  synchro : %s" % e)
    add("")
    add("--- Données ---")
    cfg = CONFIG_DIR / "config.json"
    try:
        data = json.loads(cfg.read_text(encoding="utf-8")) if cfg.exists() else {}
        accs = data.get("accounts", [])
        add("%sconfig.json : %d octets, %d compte(s) %s, style=%s, synchro=%s" % (
            ok(True), cfg.stat().st_size if cfg.exists() else 0, len(accs),
            [a.get("imap_host") for a in accs], data.get("style"), data.get("p2p_enabled")))
    except Exception as e:
        add("%sconfig.json illisible : %s   -> « mintmail --reset » le met de côté" % (ok(False), e))
    db = DATA_DIR / "cache.db"
    try:
        if db.exists():
            con = sqlite3.connect(str(db))
            integ = con.execute("PRAGMA integrity_check").fetchone()[0]
            cols = [r[1] for r in con.execute("PRAGMA table_info(messages)")]
            n = con.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
            con.close()
            add("%scache.db : %d Ko, %d message(s), intégrité=%s, colonnes=%d" % (ok(integ == "ok"), db.stat().st_size // 1024, n, integ, len(cols)))
        else:
            add("cache.db : absent (sera créé)")
    except Exception as e:
        add("%scache.db illisible : %s   -> « mintmail --reset » le met de côté" % (ok(False), e))
    add("Écriture    : %s" % ("OK" if os.access(str(DATA_DIR) if DATA_DIR.exists() else str(DATA_DIR.parent), os.W_OK) else "KO (droits)"))
    add("")
    add("--- Journal (dernières lignes) ---")
    try:
        from .log import tail
        add(tail(25).rstrip())
    except Exception as e:
        add("journal indisponible : %s" % e)
    return "\n".join(L) + "\n"


def print_report() -> int:
    text = build_report()
    print(text)
    try:
        from .store import private_dir, write_private
        private_dir(DATA_DIR)
        path = DATA_DIR / "diagnostic.txt"
        write_private(path, text)
        print("Rapport enregistré dans %s — copiez-le dans votre message si le problème persiste." % path)
    except OSError:
        pass
    return 0
