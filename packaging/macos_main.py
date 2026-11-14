"""Point d'entrée de l'application macOS (PyInstaller) : interface Qt."""
import os
import sys

os.environ.setdefault("MINTMAIL_NO_AUTOINSTALL", "1")      # PySide6 est déjà dans l'application : rien à installer
from mintmail.entry import main

if __name__ == "__main__":
    sys.exit(main())
