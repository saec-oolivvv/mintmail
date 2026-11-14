"""Bibliothèques système exigées par Qt (Linux) : détection AVANT d'ouvrir la fenêtre, pour ne jamais « planter en silence ».
Sans elles (ex. libxcb-cursor0), Qt interrompt le programme sans rien afficher. Module SANS Qt, testé partout ; commandes fixes."""
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import time
from typing import Callable, List, Optional

# bibliothèque (nom de fichier) → paquet Debian / Ubuntu / Mint
PACKAGES = {
    "libxcb-cursor.so.0": "libxcb-cursor0", "libxkbcommon-x11.so.0": "libxkbcommon-x11-0", "libxkbcommon.so.0": "libxkbcommon0",
    "libEGL.so.1": "libegl1", "libGL.so.1": "libgl1", "libOpenGL.so.0": "libopengl0", "libfontconfig.so.1": "libfontconfig1",
    "libdbus-1.so.3": "libdbus-1-3", "libglib-2.0.so.0": "libglib2.0-0", "libfreetype.so.6": "libfreetype6",
    "libxcb.so.1": "libxcb1", "libX11.so.6": "libx11-6", "libX11-xcb.so.1": "libx11-xcb1", "libSM.so.6": "libsm6", "libICE.so.6": "libice6",
    "libwayland-client.so.0": "libwayland-client0", "libwayland-cursor.so.0": "libwayland-cursor0", "libwayland-egl.so.1": "libwayland-egl1",
}
# paquets à installer d'office avec MintMail (le .deb les exige)
BASE_PACKAGES = ["libxcb-cursor0", "libxkbcommon-x11-0", "libxcb-icccm4", "libxcb-image0", "libxcb-keysyms1", "libxcb-render-util0",
                 "libxcb-xinerama0", "libxcb-shape0", "libxcb-xkb1", "libegl1", "libgl1", "libfontconfig1", "libdbus-1-3"]


def package_for(lib: str) -> str:
    """Paquet qui fournit une bibliothèque ; « libxcb-X.so.N » → « libxcb-XN » (convention Debian) ; sinon le nom de la bibliothèque."""
    if lib in PACKAGES:
        return PACKAGES[lib]
    m = re.fullmatch(r"(libxcb-[a-z0-9-]+)\.so\.(\d+)", lib)
    return m.group(1) + m.group(2) if m else lib


def packages_for(libs) -> List[str]:
    out: List[str] = []
    for lib in libs:
        p = package_for(lib)
        if p not in out:
            out.append(p)
    return out


def parse_ldd(text: str) -> List[str]:
    """Noms des bibliothèques « not found » dans la sortie de ldd."""
    out: List[str] = []
    for line in (text or "").splitlines():
        m = re.match(r"\s*(\S+)\s*=>\s*not found", line)
        if m and m.group(1) not in out:
            out.append(m.group(1))
    return out


def platform_plugins(env=None) -> List[str]:
    """Plugins de plateforme de PySide6 (sans importer Qt) : xcb, et wayland si la session l'est."""
    env = os.environ if env is None else env
    try:
        spec = importlib.util.find_spec("PySide6")
    except (ImportError, ValueError):
        spec = None
    if not spec or not spec.submodule_search_locations:
        return []
    base = os.path.join(list(spec.submodule_search_locations)[0], "Qt", "plugins", "platforms")
    names = ["libqxcb.so"]
    if env.get("WAYLAND_DISPLAY") or env.get("XDG_SESSION_TYPE") == "wayland":
        names.append("libqwayland-generic.so")
    return [os.path.join(base, n) for n in names if os.path.exists(os.path.join(base, n))]


def _ldd(path: str) -> str:
    try:
        return subprocess.run(["ldd", path], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def missing_libs(plugins: Optional[List[str]] = None, ldd: Callable[[str], str] = _ldd, platform: str = sys.platform) -> List[str]:
    """Bibliothèques manquantes. Vide si au moins UN plugin de plateforme est complet (Qt retombe sur xcb sous Wayland), ou si on ne peut pas savoir."""
    if not platform.startswith("linux"):
        return []
    plugins = platform_plugins() if plugins is None else plugins
    if not plugins:
        return []
    first: List[str] = []
    for p in plugins:
        miss = parse_ldd(ldd(p))
        if not miss:
            return []
        first = first or miss
    return first


def apt_command(pkgs) -> str:
    return "sudo apt install " + " ".join(pkgs)


def install_command(pkgs, which=shutil.which) -> List[str]:
    """Commande d'installation graphique (mot de passe demandé par polkit, sans terminal) ; [] si pkexec ou apt-get manque."""
    if not which("pkexec") or not which("apt-get"):
        return []
    return ["pkexec", "apt-get", "install", "-y"] + list(pkgs)


def due(marker: str, now: Optional[float] = None, every: float = 86400) -> bool:
    """Vrai si la dernière tentative date de plus de « every » secondes (et l'enregistre) : pas de demande de mot de passe à chaque lancement."""
    now = time.time() if now is None else now
    try:
        if os.path.exists(marker) and now - os.path.getmtime(marker) < every:
            return False
        os.makedirs(os.path.dirname(marker), exist_ok=True)
        with open(marker, "w") as f:
            f.write(str(now))
        return True
    except OSError:
        return False


# --- filet de sécurité : un démarrage de Qt qui s'arrête brutalement (cause inconnue) est détecté au lancement suivant ---
def start_marker(data_dir: str) -> str:
    return os.path.join(data_dir, "qt-start.marker")


def begin_start(marker: str) -> bool:
    """Pose le témoin de démarrage. Renvoie False s'il existait déjà = le démarrage précédent n'est jamais arrivé jusqu'à la fenêtre."""
    crashed = os.path.exists(marker)
    try:
        os.makedirs(os.path.dirname(marker), exist_ok=True)
        with open(marker, "w") as f:
            f.write(str(time.time()))
    except OSError:
        pass
    return not crashed


def end_start(marker: str) -> None:
    try:
        os.remove(marker)
    except OSError:
        pass
