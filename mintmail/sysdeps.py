"""Dépendances au système (Linux / macOS / Windows) rassemblées en UN endroit : dossiers de données, notifications, ouverture de fichiers.
Le moteur de MintMail (courrier, cache, IA, synchronisation…) n'importe jamais GTK ni Qt ; tout ce qui change d'un système à l'autre passe ici.
Linux : comportement historique inchangé (XDG). macOS et Windows : emplacements usuels du système."""
import os
import shutil
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


NOTIFIER = None        # défini par la fenêtre principale : notification émise PAR l'application (un clic dessus rouvre MintMail)

SOUNDS = {
    "macos": {"received": ["/System/Library/Sounds/Glass.aiff"], "sent": ["/System/Library/Sounds/Hero.aiff", "/System/Library/Sounds/Blow.aiff"]},
    "linux": {"received": ["/usr/share/sounds/freedesktop/stereo/message-new-instant.oga", "/usr/share/sounds/freedesktop/stereo/message.oga",
                           "/usr/share/sounds/freedesktop/stereo/bell.oga"],
              "sent": ["/usr/share/sounds/freedesktop/stereo/message-sent-instant.oga", "/usr/share/sounds/freedesktop/stereo/complete.oga",
                       "/usr/share/sounds/freedesktop/stereo/message.oga"]},
}
LINUX_EVENTS = {"received": "message-new-instant", "sent": "message-sent-instant"}


def sound_command(kind, system_name=None, exists=os.path.isfile, which=shutil.which):
    """Commande qui joue le son « received » (nouveau message) ou « sent » (message envoyé), ou None si rien n'est disponible."""
    s = system_name or system()
    files = [f for f in SOUNDS.get(s, {}).get(kind, []) if exists(f)]
    if s == "macos":
        return ["afplay", files[0]] if files and which("afplay") else None
    if s == "linux":
        if which("canberra-gtk-play"):
            return ["canberra-gtk-play", "-i", LINUX_EVENTS[kind]]
        for player in ("paplay", "pw-play", "aplay"):
            if files and which(player):
                return [player, files[0]]
    return None


def play(kind):
    """Joue le son sans bloquer ni jamais lever d'erreur. Retourne True si un son a été lancé."""
    try:
        if system() == "windows":
            import winsound
            winsound.MessageBeep(winsound.MB_ICONASTERISK if kind == "received" else winsound.MB_OK)
            return True
        cmd = sound_command(kind)
        if not cmd:
            return False
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def notify(title, body="", timeout=5):
    """Notification de bureau, sans jamais lever d'erreur (une notification manquée ne doit rien casser). Retourne True si une commande a été lancée."""
    if NOTIFIER is not None:
        try:
            if NOTIFIER(title, body):
                return True
        except Exception:
            pass
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
