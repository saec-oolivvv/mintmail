"""Couche système : emplacements des données sur les trois systèmes, Linux inchangé, notifications sans exception."""
import os, sys
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mintmail import sysdeps as S

HOME = Path("/home/u")


def test_linux_keeps_the_historic_xdg_locations():
    assert S.config_dir("linux", {}, HOME) == HOME / ".config" / "mintmail"
    assert S.data_dir("linux", {}, HOME) == HOME / ".local" / "share" / "mintmail"
    assert S.config_dir("linux", {"XDG_CONFIG_HOME": "/x"}, HOME) == Path("/x/mintmail")


def test_macos_and_windows_use_the_native_locations():
    assert S.config_dir("macos", {}, HOME) == HOME / "Library" / "Application Support" / "MintMail" / "config"
    assert S.data_dir("macos", {}, HOME) == HOME / "Library" / "Application Support" / "MintMail" / "data"
    w = {"APPDATA": "C:/Users/u/AppData/Roaming", "LOCALAPPDATA": "C:/Users/u/AppData/Local"}
    assert S.config_dir("windows", w, HOME) == Path("C:/Users/u/AppData/Roaming/MintMail/config")
    assert S.data_dir("windows", w, HOME) == Path("C:/Users/u/AppData/Local/MintMail/data")
    assert S.config_dir("windows", {}, HOME) == HOME / "AppData" / "Roaming" / "MintMail" / "config"       # variables absentes : repli sûr
    assert S.config_dir("macos", {"XDG_CONFIG_HOME": "/t"}, HOME) == Path("/t/mintmail")                  # les tests / installations portables priment


def test_config_and_data_never_share_a_folder():
    for s in ("linux", "macos", "windows"):
        assert S.config_dir(s, {}, HOME) != S.data_dir(s, {}, HOME)


def test_system_and_machine_wide_oauth_clients_path():
    assert S.system_clients_path("linux", {}) == "/etc/mintmail/oauth-clients.json"
    assert S.system_clients_path("macos", {}).startswith("/Library/Application Support/MintMail")
    assert S.system("win32") == "windows" and S.system("darwin") == "macos" and S.system("linux") == "linux" and S.system("cygwin") == "windows"
    assert "MintMail" in S.system_clients_path("windows", {"PROGRAMDATA": "D:/PD"})


def test_notify_never_raises():
    import subprocess
    real = subprocess.run
    subprocess.run = lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("notify-send absent"))
    try:
        assert S.notify("t", "b") is False                             # commande absente : False, jamais d'exception
    finally:
        subprocess.run = real
