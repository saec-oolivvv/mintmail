"""Installation transparente de l'interface Qt (PySide6) : où chercher un interpréteur qui l'a, comment créer le venv privé de MintMail.
Module SANS Qt, testé partout ; les commandes sont fixes (aucun texte externe n'y entre)."""
import os
import subprocess
import sys
from typing import Callable, List, Tuple

SYSTEM_VENV = "/usr/lib/mintmail/venv"                 # créé par le paquet .deb (propriété de root)


def _py(venv: str) -> str:
    return os.path.join(venv, "Scripts", "python.exe") if os.name == "nt" else os.path.join(venv, "bin", "python")


def user_venv(home: str = "") -> str:
    """Venv privé de l'utilisateur (installation sans droits administrateur, ex. MintMail lancé depuis les sources)."""
    home = home or os.path.expanduser("~")
    if os.name == "nt":
        return os.path.join(os.environ.get("LOCALAPPDATA", home), "MintMail", "qt-venv")
    return os.path.join(home, ".local", "share", "mintmail", "qt-venv")


def candidates(env=None, home: str = "") -> List[str]:
    """Interpréteurs à essayer pour trouver PySide6, dans l'ordre : réglage explicite, venv du paquet, venv de l'utilisateur, ancien venv manuel."""
    env = os.environ if env is None else env
    home = home or os.path.expanduser("~")
    out = [env.get("MINTMAIL_QT_PYTHON", ""), _py(SYSTEM_VENV), _py(user_venv(home)), _py(os.path.join(home, "mintmail-qt-venv"))]
    return [p for p in out if p]


def create_venv(venv: str, run: Callable = subprocess.run, out: Callable = print, python: str = "") -> Tuple[bool, str]:
    """Crée le venv (avec les paquets du système : MintMail, keyring…) puis y installe PySide6. Retourne (réussi, détail)."""
    python = python or sys.executable
    try:
        os.makedirs(os.path.dirname(venv), exist_ok=True)
        steps = [([python, "-m", "venv", "--system-site-packages", venv], "venv"),
                 ([_py(venv), "-m", "pip", "install", "--disable-pip-version-check", "--upgrade", "PySide6"], "pip")]
        for cmd, name in steps:
            out("→ " + name)
            r = run(cmd, capture_output=True, text=True, timeout=3600)
            if r.returncode != 0:
                return False, ((r.stderr or r.stdout or "").strip()[-300:] or name)
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)[:200]
    return True, ""


def works(py: str, run: Callable = subprocess.run) -> bool:
    """Cet interpréteur sait-il importer MintMail ET PySide6 ?"""
    try:
        return run([py, "-c", "import mintmail, PySide6"], capture_output=True, timeout=30).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False
