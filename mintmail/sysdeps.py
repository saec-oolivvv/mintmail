"""Dépendances au système (Linux / macOS / Windows) rassemblées en UN endroit : dossiers de données, notifications, ouverture de fichiers.
Le moteur de MintMail (courrier, cache, IA, synchronisation…) n'importe jamais GTK ni Qt ; tout ce qui change d'un système à l'autre passe ici.
Linux : comportement historique inchangé (XDG). macOS et Windows : emplacements usuels du système."""
import os
import subprocess
import sys
import webbrowser
from pathlib import Path

APP_DIR = "mintmail"


def system(platform=None):
    """'linux' | 'macos' | 'windows'."""
    p = sys.platform if platform is None else platform
    return "windows" if p.startswith(("win", "cygwin")) else "macos" if p == "darwin" else "linux"


def _base(kind, system_name, env, home):
    """kind : 'config' ou 'data'. Les variables XDG_* priment partout si elles sont définies (tests, installations portables)."""
    xdg = env.get("XDG_CONFIG_HOME" if kind == "config" else "XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / APP_DIR
    if system_name == "windows":
        root = env.get("APPDATA" if kind == "config" else "LOCALAPPDATA") or str(home / "AppData" / ("Roaming" if kind == "config" else "Local"))
        return Path(root) / "MintMail" / kind
    if system_name == "macos":
        return home / "Library" / "Application Support" / "MintMail" / kind
    return home / (".config" if kind == "config" else ".local/share") / APP_DIR


def config_dir(system_name=None, env=None, home=None):
    return _base("config", system_name or system(), os.environ if env is None else env, home or Path.home())


def data_dir(system_name=None, env=None, home=None):
    return _base("data", system_name or system(), os.environ if env is None else env, home or Path.home())


def system_clients_path(system_name=None, env=None):
    """Identifiants OAuth communs à tous les utilisateurs de la machine (déploiement en équipe)."""
    s, env = system_name or system(), os.environ if env is None else env
    if s == "windows":
        return str(Path(env.get("PROGRAMDATA", r"C:\ProgramData")) / "MintMail" / "oauth-clients.json")
    if s == "macos":
        return "/Library/Application Support/MintMail/oauth-clients.json"
    return "/etc/mintmail/oauth-clients.json"


def notify(title, body="", timeout=5):
    """Notification de bureau, sans jamais lever d'erreur (une notification manquée ne doit rien casser). Retourne True si une commande a été lancée."""
    s = system()
    try:
        if s == "linux":
            cmd = ["notify-send", title, body]
        elif s == "macos":
            esc = lambda t: str(t).replace("\\", "\\\\").replace('"', '\\"')
            cmd = ["osascript", "-e", 'display notification "%s" with title "%s"' % (esc(body), esc(title))]
        else:
            q = lambda t: str(t).replace("'", "''")
            ps = ("Add-Type -AssemblyName System.Windows.Forms; $n = New-Object System.Windows.Forms.NotifyIcon; "
                  "$n.Icon = [System.Drawing.SystemIcons]::Information; $n.Visible = $true; "
                  "$n.ShowBalloonTip(%d, '%s', '%s', 'Info'); Start-Sleep -Seconds %d; $n.Dispose()" % (timeout * 1000, q(title), q(body), timeout))
            cmd = ["powershell", "-NoProfile", "-Command", ps]
        subprocess.run(cmd, timeout=timeout + 5, capture_output=True)
        return True
    except Exception:
        return False


def open_path(path):
    """Ouvre un fichier ou un dossier avec l'application par défaut du système."""
    s = system()
    try:
        if s == "windows":
            os.startfile(str(path))                                        # noqa: only exists on Windows
        else:
            subprocess.Popen(["open" if s == "macos" else "xdg-open", str(path)])
        return True
    except Exception:
        return False


def open_url(url):
    try:
        return bool(webbrowser.open(url))
    except Exception:
        return False
