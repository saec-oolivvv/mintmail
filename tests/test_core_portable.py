"""Garde-fou du portage Windows / macOS : le MOTEUR (courrier, cache, IA, synchro…) ne doit jamais dépendre de GTK (ni de Qt) ;
seule l'interface en dépend. Si un module du moteur importe l'interface par erreur, ce test échoue — sur les trois systèmes."""
import os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE = ["models", "util", "i18n", "log", "netutil", "htmlsafe", "ical", "caldav", "gcal", "contacts", "tasks", "slots", "unsub", "store", "offline",
        "backend", "ai_service", "ai_engine", "oauth", "syncdata", "p2p", "updater", "update_text", "sysdeps", "help_format", "style"]
UI = ["window", "listing", "reader", "folders", "settings", "settings_extra", "settings_more", "compose", "extras", "widgets", "assistant",
      "updates_ui", "help_view", "ai_features", "app"]          # interface GTK : à remplacer par Qt, module par module


def test_core_modules_import_without_any_gui_toolkit():
    code = ("import sys, importlib\n"
            "for blocked in ('gi', 'PySide6', 'PyQt6', 'PyQt5', 'tkinter'):\n"
            "    sys.modules[blocked] = None\n"           # tout import d'un toolkit lève ImportError
            "sys.path.insert(0, %r)\n"
            "bad = []\n"
            "for name in %r:\n"
            "    try:\n"
            "        importlib.import_module('mintmail.' + name)\n"
            "    except Exception as e:\n"
            "        bad.append('%%s : %%s' %% (name, e))\n"
            "print('\\n'.join(bad)); sys.exit(1 if bad else 0)\n") % (ROOT, CORE)
    env = dict(os.environ, MINTMAIL_NO_KEYRING="1")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
    assert r.returncode == 0, "Modules du moteur qui dépendent d'une interface graphique :\n" + r.stdout + r.stderr[-400:]


def test_core_sources_never_mention_a_gui_toolkit_import():
    import ast
    for name in CORE:
        tree = ast.parse(open(os.path.join(ROOT, "mintmail", name + ".py"), encoding="utf-8").read())
        for node in ast.walk(tree):
            mods = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""] if isinstance(node, ast.ImportFrom) else []
            assert not any(m.split(".")[0] in ("gi", "PySide6", "PyQt6", "PyQt5") for m in mods), (name, mods)


def test_every_module_is_classified_so_a_new_one_cannot_slip_through():
    known = set(CORE) | set(UI) | {"__init__", "__main__", "entry", "diagnose", "apply_update", "help_content"}
    present = {f[:-3] for f in os.listdir(os.path.join(ROOT, "mintmail")) if f.endswith(".py")}
    assert present <= known, "Module non classé (moteur ou interface ?) : %s" % sorted(present - known)
