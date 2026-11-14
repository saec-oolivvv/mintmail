#!/usr/bin/env python3
"""Lance tous les tests (moteur, modules purs et, si PySide6 est installé, la fenêtre Qt). Code de sortie non nul au moindre échec."""
import glob
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
# Isolation TOTALE : les tests n'utilisent jamais le trousseau, le dossier personnel, les réglages ni le cache réels de la personne qui les lance.
import tempfile
os.environ["MINTMAIL_NO_KEYRING"] = "1"
os.environ["HOME"] = os.environ["XDG_DATA_HOME"] = os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp(prefix="mintmail-tests-")
os.environ["MINTMAIL_LANG"] = os.environ.get("MINTMAIL_TEST_LANG", "fr")   # les tests attendent le français ; les tests anglais fixent leur propre langue
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
ok = bad = 0
for path in sorted(glob.glob(os.path.join(HERE, "test_*.py"))):
    try:
        mod = __import__(os.path.basename(path)[:-3])
    except BaseException:
        bad += 1
        traceback.print_exc()
        print("ÉCHEC (import) :", path)
        continue
    for name in sorted(n for n in dir(mod) if n.startswith("test_") and callable(getattr(mod, n))):
        try:
            getattr(mod, name)()
            ok += 1
        except BaseException:
            bad += 1
            traceback.print_exc()
            print("ÉCHEC :", mod.__name__, name)
print("\nTests : %d réussis, %d échecs" % (ok, bad))
sys.exit(1 if bad else 0)
