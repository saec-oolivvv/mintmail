"""Icône du programme pour l'interface Qt : fenêtres, barre des tâches, sélecteur de fenêtres (mêmes images que la version GTK)."""
import glob
import os

from PySide6.QtGui import QIcon

ICON_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icons")
DESKTOP_ID = "me.saec.mintmail"                   # nom du lanceur (me.saec.mintmail.desktop) : lie la fenêtre à son icône sous Wayland


def files(directory=ICON_DIR):
    """Images de l'icône : le vectoriel d'abord, puis les PNG par taille croissante."""
    svg = os.path.join(directory, "mintmail.svg")
    png = sorted(glob.glob(os.path.join(directory, "mintmail-*.png")), key=lambda f: int(os.path.basename(f)[9:-4] or 0))
    return ([svg] if os.path.isfile(svg) else []) + png


def load() -> QIcon:
    icon = QIcon()
    for f in files():
        icon.addFile(f)
    return icon if not icon.isNull() else QIcon.fromTheme("mintmail")
