"""Isolation des tests : jamais le trousseau, le dossier personnel ni les réglages réels de l'utilisateur
(défaut corrigé en 1.12.1 : sur une machine avec trousseau, la batterie écrasait la vraie clé d'API « ai:nvidia » par « nvapi-test »).
Importer ce module AVANT mintmail : il pointe HOME / XDG_* vers un dossier temporaire."""
import os
import sys
import tempfile

tmp = tempfile.mkdtemp()
os.environ["XDG_DATA_HOME"] = tmp
os.environ["XDG_CONFIG_HOME"] = tmp
os.environ["MINTMAIL_NO_KEYRING"] = "1"
os.environ["HOME"] = tmp
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
