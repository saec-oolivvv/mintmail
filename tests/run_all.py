#!/usr/bin/env python3
"""Lance tous les tests (GTK simulé) puis le test de fumée. Code de sortie non nul au moindre échec.
Les tests qui exigent un vrai GTK sont signalés « ignorés » (jamais comptés comme réussis)."""
import glob
import os
import subprocess
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
ok = bad = skipped = 0
for path in sorted(glob.glob(os.path.join(HERE, "test_*.py"))):
    mod = __import__(os.path.basename(path)[:-3])
    for name in sorted(n for n in dir(mod) if n.startswith("test_") and callable(getattr(mod, n))):
        try:
            getattr(mod, name)()
            ok += 1
        except ValueError as e:
            if "Namespace" in str(e) and "not available" in str(e):
                skipped += 1
                print("IGNORÉ (GTK réel requis) :", mod.__name__, name)
            else:
                bad += 1
                traceback.print_exc()
                print("ÉCHEC :", mod.__name__, name)
        except BaseException:
            bad += 1
            traceback.print_exc()
            print("ÉCHEC :", mod.__name__, name)
print("\nTests : %d réussis, %d échecs, %d ignorés" % (ok, bad, skipped))
smoke = subprocess.run([sys.executable, os.path.join(HERE, "stub_smoke.py")], capture_output=True, text=True)
print("Test de fumée :", smoke.stdout.strip().splitlines()[-1] if smoke.stdout.strip() else smoke.stderr[-300:])
sys.exit(1 if bad or smoke.returncode else 0)
