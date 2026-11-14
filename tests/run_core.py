#!/usr/bin/env python3
"""Tests du MOTEUR seul (sans GTK ni outils Linux) : c'est ce que les machines Windows et macOS de la CI exécutent (voir .github/workflows/portable.yml).
Même isolation que run_all.py : jamais le trousseau, le dossier personnel ni les réglages réels. Code de sortie non nul au moindre échec."""
import glob
import os
import sys
import tempfile
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["MINTMAIL_NO_KEYRING"] = "1"
os.environ["HOME"] = os.environ["USERPROFILE"] = os.environ["XDG_DATA_HOME"] = os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp(prefix="mintmail-tests-")
os.environ["MINTMAIL_LANG"] = os.environ.get("MINTMAIL_TEST_LANG", "fr")
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
CORE_TESTS = {"test_core_portable", "test_sysdeps", "test_store2", "test_backend", "test_backend2", "test_ai", "test_ai2", "test_sync", "test_tasks_slots",
              "test_p2p_discovery", "test_security", "test_hermetic", "test_senddue", "test_folder_replication", "test_qt_viewmodel", "test_qt_window"}
ok = bad = 0
for path in sorted(glob.glob(os.path.join(HERE, "test_*.py"))):
    name = os.path.basename(path)[:-3]
    if name not in CORE_TESTS:
        continue
    mod = __import__(name)
    for t in sorted(n for n in dir(mod) if n.startswith("test_") and callable(getattr(mod, n))):
        try:
            getattr(mod, t)()
            ok += 1
        except BaseException:
            bad += 1
            traceback.print_exc()
            print("ÉCHEC :", name, t)
print("\nMoteur — tests : %d réussis, %d échecs" % (ok, bad))
sys.exit(1 if bad else 0)
